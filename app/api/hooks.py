"""Hooks audit logging API (B-04, B-20).

Provides endpoints for viewing executed hooks and hook execution history.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any, Optional

from fastapi import APIRouter, Query, Depends
from fastapi.responses import JSONResponse

from app.core.config import get_settings
from app.core.hooks import get_hook_registry
from app.core.hooks_audit import get_hook_executions, get_hook_statistics, clear_hook_history
from app.db.checkpoints import get_checkpointer
from app.core.security import get_current_user

router = APIRouter(prefix="/hooks", tags=["hooks"])








@router.get("/executed")
async def get_executed_hooks(
    session_id: Optional[str] = Query(None, description="Filter by session ID"),
    tool_name: Optional[str] = Query(None, description="Filter by tool name"),
    hook_name: Optional[str] = Query(None, description="Filter by hook name"),
    hook_type: Optional[str] = Query(None, regex="^(pre|post)$", description="Filter by hook type"),
    success: Optional[bool] = Query(None, description="Filter by success status"),
    hours: int = Query(24, ge=1, le=168, description="Filter by hours (default: 24)"),
    limit: int = Query(100, ge=1, le=1000, description="Maximum number of results"),
    offset: int = Query(0, ge=0, description="Offset for pagination"),
    current_user = Depends(get_current_user),
) -> dict[str, Any]:
    """Get executed hooks audit log (B-04, B-20).
    
    Returns a paginated list of hook execution history with filtering capabilities.
    """
    result = get_hook_executions(
        session_id=session_id,
        tool_name=tool_name,
        hook_name=hook_name,
        hook_type=hook_type,
        success=success,
        hours=hours,
        limit=limit,
        offset=offset,
    )
    
    return result


@router.get("/registry")
async def get_hook_registry_info(current_user = Depends(get_current_user)) -> dict[str, Any]:
    """Get information about registered hooks (B-04).
    
    Returns the current state of the hook registry including all registered hooks.
    """
    registry = get_hook_registry()
    
    return {
        "pre_hooks": registry._pre_hooks,
        "post_hooks": registry._post_hooks,
        "total_hooks": len(registry._pre_hooks) + len(registry._post_hooks),
        "hook_types": list(registry._hook_types.keys()),
    }


@router.get("/statistics")
async def get_hook_statistics_endpoint(
    hours: int = Query(24, ge=1, le=168, description="Time window in hours"),
    current_user = Depends(get_current_user),
) -> dict[str, Any]:
    """Get hook execution statistics (B-20).
    
    Returns statistics about hook execution over the specified time period.
    """
    return get_hook_statistics(hours=hours)


