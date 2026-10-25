"""Memory API (M-27): L0 compaction, stats and content (the ``/memory`` cat).

Specs disagreed on the paths, so both families exist over the same handlers
(M-26 union precedent):

* PROMPT_MVP §3.7 — ``POST /memory/compact``, ``GET /memory/stats``,
  ``GET /memory``;
* BACKLOG6/ARCHITECT6 §4.4 — ``POST|GET /sessions/{session_id}/memory[/compact|/stats]``.

The memory store is project-level (``settings.memory_dir``): ``session_id`` is
accepted but only travels into the audit rows, exactly like ``/learn`` (M-26).

Response shapes are unions of the two spec contracts: ``/memory/stats`` ships
BACKLOG6's ``files[{name, size_bytes, entries_count, last_write_ts}]`` +
``total_size_bytes`` *and* PROMPT_MVP's ``line_counts`` / ``token_counts`` /
``last_compacted`` (tokens are the ``chars/4`` approximation used elsewhere in
MVP). ``POST /memory/compact`` returns one result per file — synchronously
compacted, the only place where compaction may run inside a request (BACKLOG6
forbids blocking a *user turn*, not this explicit endpoint).

``GET /memory`` answers JSON ``{files, markdown}`` instead of a bare body so
CI and the Chainlit UI can pick either (AC: the markdown field is the
concatenation of the four files).
"""

from __future__ import annotations

import logging

from fastapi import APIRouter
from pydantic import BaseModel

from app.core.memory.compactor import (
    CompactionResult,
    get_compactor,
    read_last_compacted,
)
from app.core.memory.md_store import get_md_store

logger = logging.getLogger(__name__)

router = APIRouter(tags=["memory"])

#: The four files ``GET /memory`` cats (AC order = prompt-section order).
CAT_FILES = ("LEARNED.md", "PREFERENCES.md", "FACTS.md", "DECISIONS.md")


class CompactFileResult(BaseModel):
    """One file's outcome inside ``POST .../memory/compact``."""

    file: str
    changed: bool
    before_bytes: int
    after_bytes: int
    kept: int
    archived: int
    archive_path: str | None = None
    over_limit: bool = False


class CompactResponse(BaseModel):
    """Union of PROMPT_MVP (result per file) and BACKLOG6 (totals)."""

    status: str = "ok"
    results: list[CompactFileResult]
    total_archived: int


class StatsFile(BaseModel):
    """Per-file stats entry (BACKLOG6 shape + PROMPT_MVP counters)."""

    name: str
    size_bytes: int
    entries_count: int
    line_count: int
    token_count: int
    last_write_ts: str
    max_bytes: int
    over_limit: bool


class StatsResponse(BaseModel):
    """``GET .../memory/stats`` — sizes, counts, last-write, last-compacted."""

    files: list[StatsFile]
    total_size_bytes: int
    line_counts: dict[str, int]
    token_counts: dict[str, int]
    last_compacted: str | None


class MemoryContentResponse(BaseModel):
    """``GET .../memory`` — the four L0 bodies as a dict and concatenated."""

    files: dict[str, str]
    markdown: str


def _result_payload(result: CompactionResult) -> CompactFileResult:
    """Dataclass -> response model (explicit: the field names are the contract)."""
    return CompactFileResult(
        file=result.file,
        changed=result.changed,
        before_bytes=result.before_bytes,
        after_bytes=result.after_bytes,
        kept=result.kept,
        archived=result.archived,
        archive_path=result.archive_path,
        over_limit=result.over_limit,
    )


async def _compact_memory(session_id: str | None) -> CompactResponse:
    """Synchronously compact all four strategy files (explicit user action)."""
    results = await get_compactor().compact_all(session_id=session_id)
    payloads = [_result_payload(result) for result in results.values()]
    total = sum(result.archived for result in results.values())
    logger.info("memory compact (session=%s): %d entries archived", session_id, total)
    return CompactResponse(results=payloads, total_archived=total)


def _memory_stats() -> StatsResponse:
    """Sizes/counts/last-write per file + PROMPT_MVP's counters."""
    store = get_md_store()
    files: list[StatsFile] = []
    line_counts: dict[str, int] = {}
    token_counts: dict[str, int] = {}
    for name, info in store.stats().items():
        content = store.read(name)
        line_counts[name] = len(content.splitlines())
        token_counts[name] = len(content) // 4
        files.append(
            StatsFile(
                name=name,
                size_bytes=info["bytes"],
                entries_count=info["entries"],
                line_count=line_counts[name],
                token_count=token_counts[name],
                last_write_ts=info["last_write"],
                max_bytes=info["max_bytes"],
                over_limit=info["over_limit"],
            )
        )
    stamps = read_last_compacted(store.memory_dir)
    return StatsResponse(
        files=files,
        total_size_bytes=sum(entry.size_bytes for entry in files),
        line_counts=line_counts,
        token_counts=token_counts,
        last_compacted=max(stamps.values()) if stamps else None,
    )


def _memory_content() -> MemoryContentResponse:
    """The four L0 files, raw and concatenated as markdown."""
    store = get_md_store()
    files = {name: store.read(name) for name in CAT_FILES}
    sections = [
        f"## {name}\n{content if content.strip() else '(empty)'}"
        for name, content in files.items()
    ]
    return MemoryContentResponse(
        files=files,
        markdown="# Long-term Memory\n\n" + "\n\n".join(sections),
    )


# --- endpoints (union of both spec path families) ----------------------------


@router.post("/memory/compact", response_model=CompactResponse)
async def compact_memory() -> CompactResponse:
    """Compaction of all four L0 files (PROMPT_MVP M-27)."""
    return await _compact_memory(None)


@router.post("/sessions/{session_id}/memory/compact", response_model=CompactResponse)
async def compact_session_memory(session_id: str) -> CompactResponse:
    """Same compaction, session-scoped path (BACKLOG6 M-27); session in audit."""
    return await _compact_memory(session_id)


@router.get("/memory/stats", response_model=StatsResponse)
def memory_stats() -> StatsResponse:
    """Sizes, entry/line/token counts and last-write per file (PROMPT_MVP)."""
    return _memory_stats()


@router.get("/sessions/{session_id}/memory/stats", response_model=StatsResponse)
def session_memory_stats(session_id: str) -> StatsResponse:
    """Same stats over the session-scoped path (BACKLOG6 M-27)."""
    return _memory_stats()


@router.get("/memory", response_model=MemoryContentResponse)
def memory_content() -> MemoryContentResponse:
    """Concatenation of the four L0 files as markdown (PROMPT_MVP M-27)."""
    return _memory_content()


@router.get("/sessions/{session_id}/memory", response_model=MemoryContentResponse)
def session_memory_content(session_id: str) -> MemoryContentResponse:
    """Same content over the session-scoped path (BACKLOG6 M-27)."""
    return _memory_content()
