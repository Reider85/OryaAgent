"""API endpoints for SQLiteStore operations.

Provides REST API for accessing SQLiteStore data.
"""

from __future__ import annotations

import logging
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from app.core.sqlite_store import get_sqlite_store

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["sqlite-store"])


class HookExecutionFilter(BaseModel):
    """Hook execution filter model."""
    session_id: str | None = None
    tool_name: str | None = None
    hook_name: str | None = None
    hook_type: str | None = None
    success: bool | None = None
    start_date: str | None = None
    end_date: str | None = None
    limit: int = 100
    offset: int = 0


class SkillActivationRequest(BaseModel):
    """Skill activation request."""
    skill_name: str
    activate: bool = True


@router.get("/hooks/executions")
async def list_hook_executions(
    session_id: str | None = Query(None, description="Filter by session ID"),
    tool_name: str | None = Query(None, description="Filter by tool name"),
    hook_name: str | None = Query(None, description="Filter by hook name"),
    hook_type: str | None = Query(None, description="Filter by hook type"),
    success: bool | None = Query(None, description="Filter by success status"),
    start_date: str | None = Query(None, description="Start date (ISO format)"),
    end_date: str | None = Query(None, description="End date (ISO format)"),
    limit: int = Query(100, ge=1, le=1000, description="Maximum number of executions"),
    offset: int = Query(0, ge=0, description="Offset for pagination"),
):
    """List hook executions with optional filtering."""
    store = get_sqlite_store()
    results = await store.get_hook_executions(
        session_id=session_id,
        tool_name=tool_name,
        hook_name=hook_name,
        hook_type=hook_type,
        success=success,
        start_date=start_date,
        end_date=end_date,
        limit=limit,
        offset=offset,
    )
    return {"executions": results, "total": len(results)}


@router.get("/hooks/executions/{execution_id}")
async def get_hook_execution(execution_id: str):
    """Get a specific hook execution."""
    store = get_sqlite_store()
    result = await store.get_hook_execution(execution_id)
    if not result:
        raise HTTPException(status_code=404, detail="Hook execution not found")
    return result


@router.delete("/hooks/executions/{execution_id}")
async def delete_hook_execution(execution_id: str):
    """Delete a hook execution."""
    store = get_sqlite_store()
    success = await store.delete_hook_execution(execution_id)
    if not success:
        raise HTTPException(status_code=404, detail="Hook execution not found")
    return {"success": True}


@router.delete("/hooks/executions")
async def clear_old_hook_executions(
    older_than_days: int = Query(30, ge=1, le=365, description="Delete records older than N days")
):
    """Clear old hook execution records."""
    store = get_sqlite_store()
    count = await store.delete_old_hook_executions(older_than_days)
    return {"deleted_count": count, "older_than_days": older_than_days}


@router.get("/hooks/statistics")
async def get_hook_statistics(days: int = Query(7, ge=1, le=365, description="Number of days to analyze")):
    """Get hook execution statistics."""
    store = get_sqlite_store()
    return await store.get_hooks_statistics(days)


@router.get("/skills")
async def list_skills(
    category: str | None = Query(None, description="Filter by category"),
    is_active: bool | None = Query(None, description="Filter by active status"),
    limit: int = Query(100, ge=1, le=1000, description="Maximum number of skills"),
    offset: int = Query(0, ge=0, description="Offset for pagination"),
):
    """List skills with optional filtering."""
    store = get_sqlite_store()
    results = await store.get_skills_metadata(
        category=category,
        is_active=is_active,
        limit=limit,
        offset=offset,
    )
    return {"skills": results, "total": len(results)}


@router.get("/skills/{skill_name}")
async def get_skill(skill_name: str):
    """Get a specific skill."""
    store = get_sqlite_store()
    result = await store.get_skill_metadata(skill_name)
    if not result:
        raise HTTPException(status_code=404, detail="Skill not found")
    return result


@router.post("/skills/activate")
async def activate_skill(request: SkillActivationRequest):
    """Activate or deactivate a skill."""
    store = get_sqlite_store()
    success = await store.update_skill_activation(request.skill_name, request.activate)
    if not success:
        raise HTTPException(status_code=404, detail="Skill not found")
    return {"success": True, "skill_name": request.skill_name, "activated": request.activate}


@router.get("/skills/{skill_name}/dependencies")
async def get_skill_dependencies(skill_name: str):
    """Get dependencies for a skill."""
    store = get_sqlite_store()
    result = await store.get_skill_dependencies(skill_name)
    return {"skill_name": skill_name, "dependencies": result}


@router.get("/skills/statistics")
async def get_skills_statistics():
    """Get skills statistics."""
    store = get_sqlite_store()
    return await store.get_skills_statistics()


@router.post("/store/cleanup")
async def cleanup_store_data(max_days: int = Query(90, ge=1, le=365, description="Keep data newer than N days")):
    """Clean up old data from the store."""
    store = get_sqlite_store()
    result = await store.cleanup_old_data(max_days)
    return result


@router.get("/store/info")
async def get_store_info():
    """Get information about the SQLite store."""
    store = get_sqlite_store()
    
    # Get database file info
    db_path = store.db_path
    db_size = db_path.stat().st_size if db_path.exists() else 0
    
    # Get table counts
    hooks_count = len(await store.get_hook_executions(limit=1))
    skills_count = len(await store.get_skills_metadata(limit=1))
    
    return {
        "database_path": str(db_path),
        "database_size_bytes": db_size,
        "hooks_executions_count": hooks_count,
        "skills_count": skills_count,
        "tables": {
            "hooks_audit": "Stores hook execution records",
            "skills_metadata": "Stores skills metadata and activation state",
            "skills_dependencies": "Stores skills dependency relationships",
        }
    }