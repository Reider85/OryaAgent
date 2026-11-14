"""Memory management UI endpoints for B-16."""

import json
from typing import List, Optional, Dict, Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from app.api.memory import (
    list_memories_endpoint,
    search_memories_endpoint,
    get_memory_stats_endpoint,
    forget_memory_endpoint,
    add_memory_endpoint,
)
from app.core.security import get_current_user
from app.core.memory.sqlitestore import get_sqlite_store

router = APIRouter()
templates = Jinja2Templates(directory="app/web/templates")


class MemoryRequest(BaseModel):
    content: str
    metadata: Dict[str, Any] = {}


class MemoryEditRequest(BaseModel):
    content: str
    metadata: Dict[str, Any] = {}


@router.get("/memory", response_class=HTMLResponse)
async def memory_management_page(request: Request, current_user: str = Depends(get_current_user)):
    """Memory management page with list, edit, delete functionality."""
    return templates.TemplateResponse("memory.html", {
        "request": request,
        "user": current_user,
    })


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
    query: str,
    session_id: str,
    limit: int = 10,
    current_user: str = Depends(get_current_user),
):
    """Search memories using FTS5."""
    try:
        memories = await search_memories_endpoint(
            session_id=session_id,
            query=query,
            limit=limit,
        )
        return {"memories": memories}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/memory/remember")
async def add_memory(
    request: MemoryRequest,
    session_id: str,
    current_user: str = Depends(get_current_user),
):
    """Add a new memory."""
    try:
        memory_id = await add_memory_endpoint(
            session_id=session_id,
            content=request.content,
            metadata=request.metadata,
        )
        return {"id": memory_id, "message": "Memory added successfully"}
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