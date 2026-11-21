"""Memory API — M-27 union paths + B-23 SQLite-backed memories.

Two families share one module (the M-26 union-path precedent):

* **M-27** (``app/core/memory``): ``POST /memory/compact``,
  ``GET /memory/stats`` and the session-scoped twins
  ``/sessions/{session_id}/memory[/compact|/stats]`` used by the Chainlit
  ``/memory*`` slash-commands. The memory store is project-level
  (``settings.memory_dir``): ``session_id`` only travels into the audit rows,
  exactly like ``/learn`` (M-26).

  ``GET /memory`` (the JSON "cat") is intentionally **not** registered here:
  since B-16 that path serves the HTML Memory Management page
  (``app/web/memory_ui.py``, linked from ``base.html``); the chainlit
  ``/memory cat`` command uses the session-scoped
  ``GET /sessions/{session_id}/memory`` twin instead.

* **B-23**: session-scoped SQLite memory CRUD over
  ``app/core/memory/sqlitestore`` — ``/memory/{session_id}/remember|list|
  search|stats|export|import|forget``. The original B-23 routes omitted
  ``{session_id}`` from the path while the handlers declared it as a
  ``Path`` parameter, so every endpoint answered 422; the paths now carry
  the parameter.

Response shapes of the M-27 stats/compact endpoints are unions of the two
spec contracts (PROMPT_MVP §3.7 + BACKLOG6 §4.4): ``/memory/stats`` ships
BACKLOG6's ``files[{name, size_bytes, entries_count, last_write_ts}]`` +
``total_size_bytes`` *and* PROMPT_MVP's ``line_counts`` / ``token_counts`` /
``last_compacted`` (tokens are the ``chars/4`` approximation used elsewhere in
MVP). ``POST /memory/compact`` returns one result per file — synchronously
compacted, the only place where compaction may run inside a request (BACKLOG6
forbids blocking a *user turn*, not this explicit endpoint).
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Path
from pydantic import BaseModel

from app.core.memory.compactor import (
    CompactionResult,
    get_compactor,
    read_last_compacted,
)
from app.core.memory.md_store import get_md_store
from app.core.memory.sqlitestore import get_sqlite_store
from app.core.observability.spans import timed_span
from app.core.security import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(tags=["memory"])

#: The four files ``GET /memory`` cats (AC order = prompt-section order).
CAT_FILES = ("LEARNED.md", "PREFERENCES.md", "FACTS.md", "DECISIONS.md")


# --- M-27: models ------------------------------------------------------------


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
    """``GET /sessions/{id}/memory`` — the four L0 bodies as a dict + markdown."""

    files: dict[str, str]
    markdown: str


# --- M-27: helpers -----------------------------------------------------------


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


# --- M-27: endpoints (union of both spec path families) ---------------------


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


@router.get("/sessions/{session_id}/memory", response_model=MemoryContentResponse)
def session_memory_content(session_id: str) -> MemoryContentResponse:
    """Concatenation of the four L0 files as markdown (chainlit ``/memory cat``)."""
    return _memory_content()


# --- B-23: SQLite memory CRUD (session-scoped) -------------------------------


class MemoryRequest(BaseModel):
    """Request model for adding memories."""

    content: str
    metadata: dict[str, Any] | None = None
    expires_in_hours: int | None = None


class MemoryResponse(BaseModel):
    """Response model for memory operations."""

    id: str
    session_id: str
    content: str
    metadata: dict[str, Any]
    created_at: str
    updated_at: str
    expires_at: str | None


class SearchQuery(BaseModel):
    """Request model for memory search."""

    query: str
    limit: int = 10
    offset: int = 0


class ImportRequest(BaseModel):
    """Request model for memory import."""

    data: dict[str, Any]


@timed_span(span_type="memory.add", name="memory.add")
async def add_memory_endpoint(
    request: MemoryRequest,
    session_id: str = Path(..., description="Session ID"),
    current_user: str = Depends(get_current_user),
) -> MemoryResponse:
    """Add a memory to the store."""
    try:
        store = await get_sqlite_store()
        memory_id = await store.add_memory(
            session_id=session_id,
            content=request.content,
            metadata=request.metadata,
            expires_in_hours=request.expires_in_hours,
        )

        memory = await store.get_memory(memory_id)
        if not memory:
            raise HTTPException(
                status_code=404, detail="Memory not found after creation"
            )

        return MemoryResponse(
            id=memory["id"],
            session_id=memory["session_id"],
            content=memory["content"],
            metadata=memory["metadata"],
            created_at=memory["created_at"],
            updated_at=memory["updated_at"],
            expires_at=memory["expires_at"],
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to add memory: {str(e)}")


@timed_span(span_type="memory.delete", name="memory.delete")
async def forget_memory_endpoint(
    memory_id: str = Path(..., description="Memory ID"),
    session_id: str = Path(..., description="Session ID"),
    current_user: str = Depends(get_current_user),
) -> dict[str, Any]:
    """Forget a specific memory."""
    try:
        store = await get_sqlite_store()
        success = await store.forget_memory(memory_id)

        if not success:
            raise HTTPException(status_code=404, detail="Memory not found")

        return {"message": "Memory forgotten successfully", "memory_id": memory_id}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to forget memory: {str(e)}"
        )


@timed_span(span_type="memory.search", name="memory.search")
async def search_memories_endpoint(
    request: SearchQuery,
    session_id: str = Path(..., description="Session ID"),
    current_user: str = Depends(get_current_user),
) -> list[MemoryResponse]:
    """Search memories using FTS5."""
    try:
        store = await get_sqlite_store()
        memories = await store.search_memories(
            session_id=session_id,
            query=request.query,
            limit=request.limit,
            offset=request.offset,
        )

        return [
            MemoryResponse(
                id=memory["id"],
                session_id=memory["session_id"],
                content=memory["content"],
                metadata=memory["metadata"],
                created_at=memory["created_at"],
                updated_at=memory["updated_at"],
                expires_at=memory["expires_at"],
            )
            for memory in memories
        ]

    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to search memories: {str(e)}"
        )


@timed_span(span_type="memory.list", name="memory.list")
async def list_memories_endpoint(
    session_id: str = Path(..., description="Session ID"),
    limit: int = 50,
    offset: int = 0,
    order_by: str = "created_at",
    order_dir: str = "DESC",
    current_user: str = Depends(get_current_user),
) -> list[MemoryResponse]:
    """List memories for a session."""
    try:
        store = await get_sqlite_store()
        memories = await store.list_memories(
            session_id=session_id,
            limit=limit,
            offset=offset,
            order_by=order_by,
            order_dir=order_dir,
        )

        return [
            MemoryResponse(
                id=memory["id"],
                session_id=memory["session_id"],
                content=memory["content"],
                metadata=memory["metadata"],
                created_at=memory["created_at"],
                updated_at=memory["updated_at"],
                expires_at=memory["expires_at"],
            )
            for memory in memories
        ]

    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to list memories: {str(e)}"
        )


@timed_span(span_type="memory.export", name="memory.export")
async def export_memories_endpoint(
    session_id: str = Path(..., description="Session ID"),
    current_user: str = Depends(get_current_user),
) -> dict[str, Any]:
    """Export all memories for a session."""
    try:
        store = await get_sqlite_store()
        export_data = await store.export_memories(session_id)

        return export_data

    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to export memories: {str(e)}"
        )


@timed_span(span_type="memory.import", name="memory.import")
async def import_memories_endpoint(
    request: ImportRequest,
    session_id: str = Path(..., description="Session ID"),
    current_user: str = Depends(get_current_user),
) -> dict[str, Any]:
    """Import memories for a session."""
    try:
        store = await get_sqlite_store()
        imported_count = await store.import_memories(session_id, request.data)

        return {
            "message": f"Successfully imported {imported_count} memories",
            "imported_count": imported_count,
            "session_id": session_id,
        }

    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to import memories: {str(e)}"
        )


@timed_span(span_type="memory.stats", name="memory.stats")
async def get_memory_stats_endpoint(
    session_id: str = Path(..., description="Session ID"),
    current_user: str = Depends(get_current_user),
) -> dict[str, Any]:
    """Get memory statistics for a session."""
    try:
        store = await get_sqlite_store()
        stats = await store.get_memory_stats(session_id)

        return stats

    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to get memory stats: {str(e)}"
        )


# Define the B-23 routes: the handlers declare ``session_id`` as a path
# parameter, so every path carries ``{session_id}`` (the pre-B-23 paths
# omitted it and answered 422 on every call).
router.add_api_route(
    "/memory/{session_id}/remember",
    add_memory_endpoint,
    methods=["POST"],
    summary="Add a memory",
    description="Add a new memory to the store with optional expiration",
)

router.add_api_route(
    "/memory/{session_id}/forget/{memory_id}",
    forget_memory_endpoint,
    methods=["DELETE"],
    summary="Forget a memory",
    description="Delete a specific memory by ID",
)

router.add_api_route(
    "/memory/{session_id}/search",
    search_memories_endpoint,
    methods=["POST"],
    summary="Search memories",
    description="Search memories using full-text search",
)

router.add_api_route(
    "/memory/{session_id}/list",
    list_memories_endpoint,
    methods=["GET"],
    summary="List memories",
    description="List all memories for a session with pagination",
)

router.add_api_route(
    "/memory/{session_id}/export",
    export_memories_endpoint,
    methods=["POST"],
    summary="Export memories",
    description="Export all memories for a session",
)

router.add_api_route(
    "/memory/{session_id}/import",
    import_memories_endpoint,
    methods=["POST"],
    summary="Import memories",
    description="Import memories from exported data",
)

router.add_api_route(
    "/memory/{session_id}/stats",
    get_memory_stats_endpoint,
    methods=["GET"],
    summary="Get memory statistics",
    description="Get statistics about memory usage for a session",
)
