"""L0 memory entry model (M-25) — one markdown block per record.

Record format follows ARCHITECT6 §3.1.1::

    - [fact] id=fact_001 | confidence=1.0 | source=user_explicit | ts=2026-10-20T10:10:00Z
      Project uses PostgreSQL 16.

One entry = one block: a meta line (``- [kind] k=v | k=v | ...``) followed by
the indented text, separated from the next entry by a blank line. Blocks are
hand-editable — a block without a meta line parses as free text with the
file's natural kind (``default_kind``), so users can keep editing
``LEARNED.md`` in an editor without breaking the parser.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime

#: kind -> id prefix used by :func:`next_id` and :meth:`MemoryItem.create`.
ID_PREFIXES: dict[str, str] = {
    "project": "proj",
    "preference": "pref",
    "learned": "learn",
    "fact": "fact",
    "decision": "dec",
    "index": "idx",
}

#: L0 filename -> the kind its entries carry by default.
KIND_BY_FILE: dict[str, str] = {
    "PROJECT.md": "project",
    "LEARNED.md": "learned",
    "PREFERENCES.md": "preference",
    "FACTS.md": "fact",
    "DECISIONS.md": "decision",
    "MEMORY_INDEX.md": "index",
}

#: ``- [kind] id=... | confidence=... | source=... | ts=...``
_META_RE = re.compile(r"^-\s*\[(?P<kind>[a-z]+)\]\s*(?P<meta>.*)$")
_KV_RE = re.compile(r"(?P<key>[a-z_]+)=(?P<value>[^|\s]+)")


def utc_now() -> str:
    """Timestamp for new records: ``2026-10-20T10:10:00Z`` (second precision)."""
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def kind_for(filename: str) -> str:
    """Default :class:`MemoryItem` kind for an L0 filename."""
    return KIND_BY_FILE.get(filename, "fact")


def next_id(content: str, kind: str) -> str:
    """First unused ``{prefix}_{nnn}`` id for ``kind`` inside ``content``.

    ``next_id("", "fact")`` -> ``fact_001``; with ``fact_001``/``fact_003``
    present -> ``fact_004`` (gaps are not reused, ids stay monotonic).
    """
    prefix = ID_PREFIXES.get(kind, kind[:4] or "mem")
    highest = 0
    for match in re.finditer(rf"id={prefix}_(\d+)\b", content):
        highest = max(highest, int(match.group(1)))
    return f"{prefix}_{highest + 1:03d}"


@dataclass(frozen=True, slots=True)
class MemoryItem:
    """A single L0 record; ``to_markdown`` / :func:`parse_entries` round-trip."""

    kind: str
    text: str
    id: str | None = None
    confidence: float = 1.0
    source: str = "user_explicit"
    ts: str = ""

    @classmethod
    def create(
        cls,
        kind: str,
        text: str,
        *,
        id: str | None = None,
        confidence: float = 1.0,
        source: str = "user_explicit",
        ts: str | None = None,
    ) -> MemoryItem:
        """Build an entry, filling ``ts`` with the current UTC time."""
        return cls(
            kind=kind,
            text=text.strip(),
            id=id,
            confidence=confidence,
            source=source,
            ts=ts if ts is not None else utc_now(),
        )

    def to_markdown(self) -> str:
        """Render as a self-contained block ending in a blank line."""
        meta = f"- [{self.kind}]"
        if self.id:
            meta += f" id={self.id}"
        meta += (
            f" | confidence={self.confidence}"
            f" | source={self.source}"
            f" | ts={self.ts or utc_now()}"
        )
        body = "".join(f"  {line}\n" for line in self.text.splitlines())
        return f"{meta}\n{body}\n"


def parse_entries(content: str, *, default_kind: str | None = None) -> list[MemoryItem]:
    """Parse an L0 file body into entries.

    Blocks are split on blank lines. A block starting with ``- [kind]`` is a
    structured entry; any other block (free text, hand-edited) is returned
    only when ``default_kind`` is given, carrying that kind and
    ``source="manual"``. Section headers (``# ...``) are skipped.
    """
    if not content or not content.strip():
        return []
    items: list[MemoryItem] = []
    for block in re.split(r"\n[ \t]*\n", content.strip()):
        lines = [line for line in block.splitlines() if line.strip()]
        if not lines:
            continue
        first = lines[0].strip()
        if first.startswith("#"):
            continue
        match = _META_RE.match(first)
        if match is None:
            if default_kind is None:
                continue
            items.append(
                MemoryItem(
                    kind=default_kind,
                    text="\n".join(_dedent(line) for line in lines),
                    source="manual",
                )
            )
            continue
        meta = dict(_KV_RE.findall(match.group("meta")))
        items.append(
            MemoryItem(
                kind=match.group("kind"),
                text="\n".join(_dedent(line) for line in lines[1:]).strip(),
                id=meta.get("id"),
                confidence=float(meta.get("confidence", 1.0)),
                source=meta.get("source", "manual"),
                ts=meta.get("ts", ""),
            )
        )
    return items


def _dedent(line: str) -> str:
    """Drop the two-space entry indent (tolerates hand-edited spacing)."""
    return line[2:] if line.startswith("  ") else line.lstrip()
