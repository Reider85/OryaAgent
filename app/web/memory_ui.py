"""Memory management UI endpoints for B-16."""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from app.api.memory import (
    MemoryRequest as ApiMemoryRequest,
)
from app.api.memory import (
    SearchQuery,
    add_memory_endpoint,
    forget_memory_endpoint,
    get_memory_stats_endpoint,
    list_memories_endpoint,
    search_memories_endpoint,
)
from app.core.security import get_current_user

router = APIRouter()
templates = Jinja2Templates(directory="app/web/templates")


class MemoryRequest(BaseModel):
    """Body of POST /api/memory/remember — matches the memory.html JS
    (``{session_id, content, metadata}``; session_id rides in the body, not
    as a query parameter)."""

    session_id: str
    content: str
    metadata: dict[str, Any] = {}


class MemorySearchRequest(BaseModel):
    """Body of POST /api/memory/search — same JSON-body contract."""

    query: str
    session_id: str
    limit: int = 10


class MemoryEditRequest(BaseModel):
    content: str
    metadata: dict[str, Any] = {}


@router.get("/memory", response_class=HTMLResponse)
async def memory_management_page(
    request: Request, current_user: str = Depends(get_current_user)
):
    """Memory management page with list, edit, delete functionality."""
    return templates.TemplateResponse(
        request,
        "memory.html",
        {"user": current_user},
    )


@router.get("/api/memory/list")
async def get_memory_list(
    session_id: str,
    limit: int = 50,
    offset: int = 0,
    current_user: str = Depends(get_current_user),
):
    """Get list of memories for a session."""
    try:
        memories = await list_memories_endpoint(
            session_id=session_id,
            limit=limit,
            offset=offset,
        )
        return {"memories": memories}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/memory/stats")
async def get_memory_stats(
    session_id: str,
    current_user: str = Depends(get_current_user),
):
    """Get memory statistics for a session."""
    try:
        stats = await get_memory_stats_endpoint(session_id=session_id)
        return stats
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/memory/search")
async def search_memories(
    body: MemorySearchRequest,
    current_user: str = Depends(get_current_user),
):
    """Search memories using FTS5 (JSON body, per memory.html + tests)."""
    try:
        memories = await search_memories_endpoint(
            request=SearchQuery(query=body.query, limit=body.limit),
            session_id=body.session_id,
        )
        return {"memories": memories}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/memory/remember")
async def add_memory(
    request: MemoryRequest,
    current_user: str = Depends(get_current_user),
):
    """Add a new memory (session_id comes in the JSON body)."""
    try:
        memory = await add_memory_endpoint(
            request=ApiMemoryRequest(
                content=request.content, metadata=request.metadata
            ),
            session_id=request.session_id,
        )
        return {"id": memory.id, "message": "Memory added successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/api/memory/forget/{memory_id}")
async def delete_memory(
    memory_id: str,
    session_id: str,
    current_user: str = Depends(get_current_user),
):
    """Delete a memory."""
    try:
        success = await forget_memory_endpoint(
            memory_id=memory_id,
            session_id=session_id,
        )
        if success:
            return {"message": "Memory deleted successfully", "memory_id": memory_id}
        else:
            raise HTTPException(status_code=404, detail="Memory not found")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
