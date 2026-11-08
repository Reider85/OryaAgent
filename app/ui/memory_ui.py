"""Memory UI components for B-16 and B-17: list, edit, delete, import/export."""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.core.memory.sqlitestore import get_sqlite_store
from app.core.security import get_current_user
from app.core.observability.spans import emit_span

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/ui/memory", tags=["memory-ui"])
templates = Jinja2Templates(directory="app/ui/templates")


@router.get("/", response_class=HTMLResponse)
async def memory_list_ui(
    request: Request,
    session_id: str = None,
    limit: int = 50,
    offset: int = 0,
    current_user: str = Depends(get_current_user),
):
    """Memory list UI page."""
    try:
        store = await get_sqlite_store()
        
        if session_id:
            memories = await store.list_memories(session_id, limit=limit, offset=offset)
            stats = await store.get_memory_stats(session_id)
        else:
            memories = []
            stats = {"total_memories": 0, "oldest_memory": None, "newest_memory": None}
        
        return templates.TemplateResponse(
            "memory/list.html",
            {
                "request": request,
                "memories": memories,
                "stats": stats,
                "session_id": session_id,
                "limit": limit,
                "offset": offset,
                "current_user": current_user,
            },
        )
        
    except Exception as e:
        logger.error(f"Error in memory list UI: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to load memory list: {str(e)}")


@router.get("/edit/{memory_id}", response_class=HTMLResponse)
async def memory_edit_ui(
    request: Request,
    memory_id: str,
    current_user: str = Depends(get_current_user),
):
    """Memory edit UI page."""
    try:
        store = await get_sqlite_store()
        memory = await store.get_memory(memory_id)
        
        if not memory:
            raise HTTPException(status_code=404, detail="Memory not found")
        
        return templates.TemplateResponse(
            "memory/edit.html",
            {
                "request": request,
                "memory": memory,
                "current_user": current_user,
            },
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in memory edit UI: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to load memory edit: {str(e)}")


@router.post("/update/{memory_id}")
async def memory_update_ui(
    request: Request,
    memory_id: str,
    current_user: str = Depends(get_current_user),
):
    """Update memory via UI."""
    try:
        form_data = await request.form()
        new_content = form_data.get("content", "")
        new_metadata = json.loads(form_data.get("metadata", "{}"))
        
        store = await get_sqlite_store()
        
        # Get the original memory
        original_memory = await store.get_memory(memory_id)
        if not original_memory:
            raise HTTPException(status_code=404, detail="Memory not found")
        
        # Supersede the memory
        new_memory_id = await store.supersede_memory(
            memory_id, new_content, new_metadata
        )
        
        return RedirectResponse(f"/ui/memory/edit/{new_memory_id}", status_code=303)
        
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid metadata JSON")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating memory: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to update memory: {str(e)}")


@router.post("/delete/{memory_id}")
async def memory_delete_ui(
    request: Request,
    memory_id: str,
    current_user: str = Depends(get_current_user),
):
    """Delete memory via UI."""
    try:
        store = await get_sqlite_store()
        success = await store.forget_memory(memory_id)
        
        if not success:
            raise HTTPException(status_code=404, detail="Memory not found")
        
        # Redirect to memory list
        referer = request.headers.get("referer", "/ui/memory")
        return RedirectResponse(referer, status_code=303)
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting memory: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to delete memory: {str(e)}")


@router.get("/export", response_class=HTMLResponse)
async def memory_export_ui(
    request: Request,
    session_id: str = None,
    current_user: str = Depends(get_current_user),
):
    """Memory export UI page."""
    try:
        store = await get_sqlite_store()
        
        if session_id:
            export_data = await store.export_memories(session_id)
        else:
            export_data = {"memories_count": 0, "memories": []}
        
        return templates.TemplateResponse(
            "memory/export.html",
            {
                "request": request,
                "export_data": json.dumps(export_data, indent=2),
                "session_id": session_id,
                "current_user": current_user,
            },
        )
        
    except Exception as e:
        logger.error(f"Error in memory export UI: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to load memory export: {str(e)}")


@router.post("/import")
async def memory_import_ui(
    request: Request,
    current_user: str = Depends(get_current_user),
):
    """Import memories via UI."""
    try:
        form_data = await request.form()
        import_data = json.loads(form_data.get("data", "{}"))
        session_id = form_data.get("session_id", "default")
        
        store = await get_sqlite_store()
        imported_count = await store.import_memories(session_id, import_data)
        
        return RedirectResponse(f"/ui/memory/?session_id={session_id}", status_code=303)
        
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid import data JSON")
    except Exception as e:
        logger.error(f"Error importing memories: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to import memories: {str(e)}")


@router.get("/stats/{session_id}", response_class=HTMLResponse)
async def memory_stats_ui(
    request: Request,
    session_id: str,
    current_user: str = Depends(get_current_user),
):
    """Memory statistics UI page."""
    try:
        store = await get_sqlite_store()
        stats = await store.get_memory_stats(session_id)
        
        return templates.TemplateResponse(
            "memory/stats.html",
            {
                "request": request,
                "stats": stats,
                "session_id": session_id,
                "current_user": current_user,
            },
        )
        
    except Exception as e:
        logger.error(f"Error in memory stats UI: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to load memory stats: {str(e)}")


# Helper function to initialize the UI router
def setup_memory_ui():
    """Setup memory UI routes."""
    return router