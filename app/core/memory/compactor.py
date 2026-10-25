"""L0 compactor: strategy-based soft compaction into the archive (M-27).

MVP has no L1 SQLite yet (B-21), so compaction is *soft*: blocks rejected by
the per-file strategy are appended to ``{memory_dir}/archive/{stem}_{date}.md``
and the L0 file is rewritten atomically with what is kept. Nothing is ever
deleted (BACKLOG6 M-27 forbidden pattern «удалять записи навсегда»), and the
archive is append-only — a second run on the same UTC day appends to the same
file.

Strategies (ARCHITECT6 §4.2.2, one per file)::

    PREFERENCES.md   keep ``source=agent_inferred`` only when confidence >= 0.8
                     (every other block — user_explicit, manual text — is kept)
    LEARNED.md       keep the last 10 entries and confidence >= 0.9, then the
                     size-guard archives the oldest kept entries until the file
                     fits its budget (at least the newest entry survives)
    FACTS.md         keep confidence >= 0.9, archive the rest
    DECISIONS.md     keep everything without a superseded marker
                     (``superseded_by=`` / ``[superseded]`` / ``superseded:``)

``PROJECT.md`` and ``MEMORY_INDEX.md`` have no strategy: they are context /
placeholders without confidence metadata, so they only show up in stats.

Ordering (crash safety): the archived blocks are appended to the archive
*first*, then the L0 file is rewritten through :meth:`MDStore.rewrite` — a
crash in between leaves a duplicate in the archive (harmless) but never loses
an entry. The rewrite itself is tmp + ``fsync`` + ``os.replace`` under the
per-file lock, so a concurrent ``append`` cannot interleave either.

Every compact run is recorded best-effort in ``memory_audit_log`` (action
``memory.compact``: who / when / what / why) and stamps
``{memory_dir}/compaction.json`` — the source of ``last_compacted`` in
``/memory/stats``.

The periodic worker (:func:`compaction_worker`, BACKLOG6 «каждые 24 часа»)
sleeps ``settings.memory_compact_interval_s`` between passes and is started by
the FastAPI lifespan; ``interval <= 0`` disables it.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import threading
from collections.abc import Awaitable, Callable
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from app.core.memory.audit import record_memory_op
from app.core.memory.md_store import MDStore, get_md_store
from app.core.memory.models import MemoryItem, kind_for, parse_entries

logger = logging.getLogger(__name__)

#: Files with a compaction strategy, in prompt-section order (ARCHITECT6 §4.2.2).
STRATEGIES: dict[str, str] = {
    "PREFERENCES.md": "keep-user-explicit",
    "LEARNED.md": "keep-recent-and-high-confidence",
    "FACTS.md": "keep-high-confidence",
    "DECISIONS.md": "keep-non-superseded",
}

#: ``LEARNED.md`` always keeps this many of the newest entries.
LEARNED_KEEP = 10

#: Archive subdirectory + the ``last_compacted`` state file.
ARCHIVE_DIRNAME = "archive"
STATE_FILENAME = "compaction.json"

#: A decision is superseded when its block carries one of these markers
#: (there is no ``superseded`` field in the M-25 record format — user decision).
SUPERSEDED_RE = re.compile(
    r"superseded_by\s*=|\[superseded\]|superseded\s*:", re.IGNORECASE
)

#: Same split as :func:`parse_entries` — one entry per blank-line block.
_BLOCK_SPLIT_RE = re.compile(r"\n[ \t]*\n")

_state_lock = threading.Lock()
_compactors_guard = threading.Lock()
_COMPACTORS: dict[str, Compactor] = {}


@dataclass(frozen=True, slots=True)
class CompactionResult:
    """Outcome of one file's compaction (per-file item of ``/memory/compact``)."""

    file: str
    changed: bool
    before_bytes: int
    after_bytes: int
    kept: int
    archived: int
    archive_path: str | None = None
    over_limit: bool = False


def get_compactor(memory_dir: Path | str | None = None) -> Compactor:
    """Cached :class:`Compactor` for ``memory_dir`` (default ``settings.memory_dir``).

    Same per-path cache pattern as :func:`get_md_store` — the compactor only
    wraps a store, so sharing one instance across endpoints and the periodic
    worker is safe.
    """
    if memory_dir is None:
        from app.core.config import get_settings

        memory_dir = get_settings().memory_dir
    key = str(Path(memory_dir))
    with _compactors_guard:
        compactor = _COMPACTORS.get(key)
        if compactor is None:
            compactor = _COMPACTORS[key] = Compactor(get_md_store(memory_dir))
        return compactor


def read_last_compacted(memory_dir: Path | str) -> dict[str, str]:
    """Per-file ISO timestamps of the last compaction that archived something."""
    path = Path(memory_dir) / STATE_FILENAME
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {key: value for key, value in data.items() if isinstance(value, str)}


def _stamp_compacted(memory_dir: Path, file: str, ts: str) -> None:
    """Record ``file``'s compaction time in the state file (atomic rewrite)."""
    with _state_lock:
        state = read_last_compacted(memory_dir)
        state[file] = ts
        tmp = memory_dir / f".{STATE_FILENAME}.tmp"
        try:
            tmp.write_text(
                json.dumps(state, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            tmp.replace(memory_dir / STATE_FILENAME)
        except OSError as exc:
            logger.warning("cannot persist the compaction state: %s", exc)
            with suppress(OSError):
                tmp.unlink()
            return


def _entry(block: str, file: str) -> MemoryItem | None:
    """The block's record, or ``None`` for section headers (always kept)."""
    items = parse_entries(block, default_kind=kind_for(file))
    return items[0] if items else None


class Compactor:
    """Strategy-based L0 compaction (M-27): keep here, archive the rest."""

    STRATEGIES = STRATEGIES

    def __init__(self, store: MDStore) -> None:
        self.store = store

    # -- public async API (ARCHITECT6 §6.1.4) --------------------------------

    async def compact(
        self,
        file: str,
        *,
        trigger: str = "manual",
        actor: str = "user",
        session_id: str | None = None,
    ) -> CompactionResult:
        """Compact one strategy file regardless of its size (``POST .../compact``)."""
        if file not in STRATEGIES:
            raise ValueError(
                f"no compaction strategy for {file!r}; expected one of {tuple(STRATEGIES)}"
            )
        return await asyncio.to_thread(
            self._compact_sync,
            file,
            trigger=trigger,
            actor=actor,
            session_id=session_id,
        )

    async def compact_all(
        self,
        *,
        trigger: str = "manual",
        actor: str = "user",
        session_id: str | None = None,
    ) -> dict[str, CompactionResult]:
        """Compact the four strategy files, keyed by filename."""
        results: dict[str, CompactionResult] = {}
        for file in STRATEGIES:
            results[file] = await self.compact(
                file, trigger=trigger, actor=actor, session_id=session_id
            )
        return results

    async def compact_if_needed(
        self,
        file: str,
        *,
        actor: str = "system",
        session_id: str | None = None,
    ) -> bool:
        """Compact ``file`` when it exceeds its budget (M-25 hook → M-27 work).

        Returns ``True`` when the file was over budget and a compaction ran —
        the budget itself may still be exceeded afterwards (``over_limit`` in
        the result) when everything left is protected by the strategy.
        Files without a strategy are a no-op.
        """
        if file not in STRATEGIES:
            logger.debug("no compaction strategy for %s — skipping", file)
            return False
        if not self.store.needs_compaction(file):
            return False
        result = await asyncio.to_thread(
            self._compact_sync,
            file,
            trigger="auto",
            actor=actor,
            session_id=session_id,
        )
        logger.info(
            "compacted %s: %d -> %d bytes (kept %d, archived %d)",
            result.file,
            result.before_bytes,
            result.after_bytes,
            result.kept,
            result.archived,
        )
        return True

    async def compact_all_if_needed(
        self, *, actor: str = "system", session_id: str | None = None
    ) -> dict[str, CompactionResult]:
        """Periodic pass: compact only the files that broke their budget."""

        def _needed(file: str) -> bool:
            return self.store.needs_compaction(file)

        results: dict[str, CompactionResult] = {}
        for file in STRATEGIES:
            if not _needed(file):
                continue
            results[file] = await asyncio.to_thread(
                self._compact_sync,
                file,
                trigger="periodic",
                actor=actor,
                session_id=session_id,
            )
        return results

    # -- core (runs in a worker thread) --------------------------------------

    def _compact_sync(
        self, file: str, *, trigger: str, actor: str, session_id: str | None
    ) -> CompactionResult:
        outcome: dict = {
            "before": 0,
            "after": 0,
            "kept": 0,
            "archived": 0,
            "archive_path": None,
            "changed": False,
            "preview": "",
        }

        def _transform(old: str) -> str:
            """Read-modify-write inside the store's per-file lock."""
            blocks = [b for b in _BLOCK_SPLIT_RE.split(old.strip()) if b.strip()]
            outcome["before"] = len(old.encode("utf-8"))
            outcome["kept"] = len(blocks)
            if not blocks:
                return old
            keep, archive = self._partition(file, blocks)
            if not archive:
                return old
            keep.sort()
            archive.sort()
            kept_blocks = [blocks[index] for index in keep]
            archived_blocks = [blocks[index] for index in archive]
            new_body = "\n\n".join(kept_blocks) + "\n" if kept_blocks else ""
            archive_path = self._append_archive(file, archived_blocks)
            outcome.update(
                after=len(new_body.encode("utf-8")),
                kept=len(kept_blocks),
                archived=len(archived_blocks),
                archive_path=str(archive_path),
                changed=True,
                preview=archived_blocks[0],
            )
            return new_body

        body = self.store.rewrite(file, _transform)
        max_bytes = self.store.max_bytes(file)
        before = outcome["before"]
        after = outcome["after"] if outcome["changed"] else before
        result = CompactionResult(
            file=file,
            changed=outcome["changed"],
            before_bytes=before,
            after_bytes=after,
            kept=outcome["kept"],
            archived=outcome["archived"],
            archive_path=outcome["archive_path"],
            over_limit=len(body.encode("utf-8")) > max_bytes,
        )
        record_memory_op(
            "memory.compact",
            file,
            outcome["preview"],
            reason=(
                f"trigger={trigger} kept={result.kept} "
                f"archived={result.archived} bytes={before}->{after}"
                + (f" archive={result.archive_path}" if result.archive_path else "")
            ),
            actor=actor,
            session_id=session_id,
            memory_dir=self.store.memory_dir,
        )
        if result.changed:
            ts = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
            _stamp_compacted(self.store.memory_dir, file, ts)
        return result

    # -- strategies ----------------------------------------------------------

    def _partition(self, file: str, blocks: list[str]) -> tuple[list[int], list[int]]:
        """Split block indices into ``(keep, archive)`` for ``file``'s strategy."""
        parsed = [_entry(block, file) for block in blocks]
        if file == "LEARNED.md":
            return self._partition_learned(blocks, parsed)
        keep: list[int] = []
        archive: list[int] = []
        for index, block in enumerate(blocks):
            item = parsed[index]
            if item is None:  # section header — never archived
                keep.append(index)
                continue
            if file == "PREFERENCES.md":
                low_confidence_inferred = (
                    item.source == "agent_inferred" and item.confidence < 0.8
                )
                (archive if low_confidence_inferred else keep).append(index)
            elif file == "FACTS.md":
                (archive if item.confidence < 0.9 else keep).append(index)
            elif file == "DECISIONS.md":
                (archive if SUPERSEDED_RE.search(block) else keep).append(index)
            else:  # pragma: no compiles - STRATEGIES gates the callers
                keep.append(index)
        return keep, archive

    def _partition_learned(
        self, blocks: list[str], parsed: list[MemoryItem | None]
    ) -> tuple[list[int], list[int]]:
        """«Last 10 + confidence >= 0.9», then the size-guard (see module doc)."""
        entry_indexes = [index for index, item in enumerate(parsed) if item is not None]
        recent = set(entry_indexes[-LEARNED_KEEP:])
        keep: list[int] = []
        for index, item in enumerate(parsed):
            if item is None or index in recent or item.confidence >= 0.9:
                keep.append(index)
        archive = [index for index in range(len(blocks)) if index not in set(keep)]

        budget = self.store.max_bytes("LEARNED.md")
        kept_entries = [index for index in sorted(keep) if parsed[index] is not None]
        while len(kept_entries) > 1 and self._encoded_size(blocks, keep) > budget:
            drop = kept_entries.pop(0)
            keep.remove(drop)
            archive.append(drop)
        return keep, archive

    @staticmethod
    def _encoded_size(blocks: list[str], indexes: list[int]) -> int:
        """Byte size the file would have with exactly ``indexes`` kept."""
        body = "\n\n".join(blocks[index] for index in sorted(indexes))
        return len((body + "\n").encode("utf-8"))

    # -- archive + helpers ---------------------------------------------------

    def _append_archive(self, file: str, blocks: list[str]) -> Path:
        """Append archived blocks to ``archive/{stem}_{YYYYMMDD}.md`` (append-only)."""
        memory_dir = self.store.memory_dir
        archive_dir = memory_dir / ARCHIVE_DIRNAME
        archive_dir.mkdir(parents=True, exist_ok=True)
        day = datetime.now(UTC).strftime("%Y%m%d")
        path = archive_dir / f"{Path(file).stem}_{day}.md"
        payload = "".join(str(block).strip("\n") + "\n\n" for block in blocks).encode(
            "utf-8"
        )
        MDStore._write_append(path, payload)
        return path


async def compaction_worker(
    interval: float,
    *,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> None:
    """Periodic compaction pass every ``interval`` seconds (BACKLOG6 M-27).

    ``interval <= 0`` disables the worker (the lifespan skips it). The ``sleep``
    hook exists for tests — the periodic AC is checked with a mocked clock.
    """
    if interval <= 0:
        logger.info("periodic memory compaction disabled (interval=%s)", interval)
        return
    while True:
        await sleep(interval)
        try:
            results = await get_compactor().compact_all_if_needed()
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - the cron must survive one bad pass
            logger.exception("periodic memory compaction failed")
            continue
        if results:
            logger.info(
                "periodic compaction: %s",
                ", ".join(
                    f"{name} -{result.archived}" for name, result in results.items()
                ),
            )
