"""Memory API endpoints for B-23: /remember, /forget, /memory list/export/import."""

from __future__ import annotations

import json
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, Path
from pydantic import BaseModel

from app.core.memory.sqlitestore import get_sqlite_store
from app.core.memory.outbox import get_memory_outbox, MemoryOperationType
from app.core.security import get_current_user
from app.core.observability.spans import emit_span

router = APIRouter(prefix="/memory", tags=["memory"])


class MemoryRequest(BaseModel):
    """Request model for adding memories."""

    content: str
    metadata: Dict[str, Any] | None = None
    expires_in_hours: int | None = None


class MemoryResponse(BaseModel):
    """Response model for memory operations."""

    id: str
    session_id: str
    content: str
    metadata: Dict[str, Any]
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

    data: Dict[str, Any]


@emit_span(name="memory.add")
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


@emit_span(name="memory.delete")
async def forget_memory_endpoint(
    memory_id: str = Path(..., description="Memory ID"),
    session_id: str = Path(..., description="Session ID"),
    current_user: str = Depends(get_current_user),
) -> Dict[str, Any]:
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


@emit_span(name="memory.search")
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


@emit_span(name="memory.list")
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


@emit_span(name="memory.export")
async def export_memories_endpoint(
    session_id: str = Path(..., description="Session ID"),
    current_user: str = Depends(get_current_user),
) -> Dict[str, Any]:
    """Export all memories for a session."""
    try:
        store = await get_sqlite_store()
        export_data = await store.export_memories(session_id)

        return export_data

    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to export memories: {str(e)}"
        )


@emit_span(name="memory.import")
async def import_memories_endpoint(
    request: ImportRequest,
    session_id: str = Path(..., description="Session ID"),
    current_user: str = Depends(get_current_user),
) -> Dict[str, Any]:
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


@emit_span(name="memory.stats")
async def get_memory_stats_endpoint(
    session_id: str = Path(..., description="Session ID"),
    current_user: str = Depends(get_current_user),
) -> Dict[str, Any]:
    """Get memory statistics for a session."""
    try:
        store = await get_sqlite_store()
        stats = await store.get_memory_stats(session_id)

        return stats

    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to get memory stats: {str(e)}"
        )


# Define the routes
router.add_api_route(
    "/remember",
    add_memory_endpoint,
    methods=["POST"],
    summary="Add a memory",
    description="Add a new memory to the store with optional expiration",
)

router.add_api_route(
    "/forget/{memory_id}",
    forget_memory_endpoint,
    methods=["DELETE"],
    summary="Forget a memory",
    description="Delete a specific memory by ID",
)

router.add_api_route(
    "/search",
    search_memories_endpoint,
    methods=["POST"],
    summary="Search memories",
    description="Search memories using full-text search",
)

router.add_api_route(
    "/list",
    list_memories_endpoint,
    methods=["GET"],
    summary="List memories",
    description="List all memories for a session with pagination",
)

router.add_api_route(
    "/export",
    export_memories_endpoint,
    methods=["POST"],
    summary="Export memories",
    description="Export all memories for a session",
)

router.add_api_route(
    "/import",
    import_memories_endpoint,
    methods=["POST"],
    summary="Import memories",
    description="Import memories from exported data",
)

router.add_api_route(
    "/stats",
    get_memory_stats_endpoint,
    methods=["GET"],
    summary="Get memory statistics",
    description="Get statistics about memory usage for a session",
)
