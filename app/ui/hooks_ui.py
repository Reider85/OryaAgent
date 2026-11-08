"""Hooks UI for B-20: view executed hooks."""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.core.hooks import get_hook_registry, get_hook_executor
from app.core.security import get_current_user
from app.core.observability.spans import emit_span

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/ui/hooks", tags=["hooks-ui"])
templates = Jinja2Templates(directory="app/ui/templates")


@router.get("/", response_class=HTMLResponse)
async def hooks_list_ui(
    request: Request,
    session_id: str = None,
    current_user: str = Depends(get_current_user),
):
    """Hooks list UI page."""
    try:
        registry = get_hook_registry()
        executor = get_hook_executor()

        # Get all registered hooks
        hooks_info = registry.list_hooks()

        # Get hook execution statistics (this would be implemented in a real system)
        # For now, we'll use mock data
        hook_stats = {
            "total_hooks": sum(len(hooks) for hooks in hooks_info.values()),
            "successful_executions": 0,
            "failed_executions": 0,
            "recent_executions": [],
        }

        return templates.TemplateResponse(
            "hooks/list.html",
            {
                "request": request,
                "hooks_info": hooks_info,
                "hook_stats": hook_stats,
                "session_id": session_id,
                "current_user": current_user,
            },
        )

    except Exception as e:
        logger.error(f"Error in hooks list UI: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to load hooks list: {str(e)}"
        )


@router.get("/execution-log", response_class=HTMLResponse)
async def hooks_execution_log_ui(
    request: Request,
    session_id: str = None,
    tool_name: str = None,
    hook_name: str = None,
    hook_type: str = None,
    limit: int = 50,
    offset: int = 0,
    current_user: str = Depends(get_current_user),
):
    """Hooks execution log UI page."""
    try:
        # In a real implementation, this would query the audit log database
        # For now, we'll use mock data
        mock_executions = [
            {
                "id": "exec_1",
                "session_id": session_id or "default",
                "tool_name": "write",
                "hook_name": "auto_format",
                "hook_type": "post",
                "success": True,
                "message": "Auto-format completed successfully",
                "duration_ms": 150,
                "created_at": "2024-01-15T10:30:00Z",
            },
            {
                "id": "exec_2",
                "session_id": session_id or "default",
                "tool_name": "edit",
                "hook_name": "auto_lint",
                "hook_type": "post",
                "success": False,
                "message": "Linting failed: No linter found",
                "duration_ms": 50,
                "created_at": "2024-01-15T10:25:00Z",
            },
        ]

        # Filter executions based on parameters
        filtered_executions = mock_executions
        if session_id:
            filtered_executions = [
                e for e in filtered_executions if e["session_id"] == session_id
            ]
        if tool_name:
            filtered_executions = [
                e for e in filtered_executions if e["tool_name"] == tool_name
            ]
        if hook_name:
            filtered_executions = [
                e for e in filtered_executions if e["hook_name"] == hook_name
            ]
        if hook_type:
            filtered_executions = [
                e for e in filtered_executions if e["hook_type"] == hook_type
            ]

        # Apply pagination
        paginated_executions = filtered_executions[offset : offset + limit]

        return templates.TemplateResponse(
            "hooks/execution_log.html",
            {
                "request": request,
                "executions": paginated_executions,
                "total_executions": len(filtered_executions),
                "session_id": session_id,
                "tool_name": tool_name,
                "hook_name": hook_name,
                "hook_type": hook_type,
                "limit": limit,
                "offset": offset,
                "current_user": current_user,
            },
        )

    except Exception as e:
        logger.error(f"Error in hooks execution log UI: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to load hooks execution log: {str(e)}"
        )


@router.get("/detail/{hook_name}", response_class=HTMLResponse)
async def hooks_detail_ui(
    request: Request,
    hook_name: str,
    current_user: str = Depends(get_current_user),
):
    """Hooks detail UI page."""
    try:
        registry = get_hook_registry()
        executor = get_hook_executor()

        # Get hook information (this would be implemented in a real system)
        # For now, we'll use mock data
        hook_info = {
            "name": hook_name,
            "description": f"Hook: {hook_name}",
            "version": "1.0.0",
            "tools_applied_to": ["write", "edit"],
            "execution_stats": {
                "total_executions": 100,
                "successful_executions": 95,
                "failed_executions": 5,
                "average_duration_ms": 120,
            },
            "recent_executions": [
                {
                    "id": "exec_1",
                    "session_id": "default",
                    "tool_name": "write",
                    "success": True,
                    "message": "Hook executed successfully",
                    "duration_ms": 150,
                    "created_at": "2024-01-15T10:30:00Z",
                },
                {
                    "id": "exec_2",
                    "session_id": "default",
                    "tool_name": "edit",
                    "success": False,
                    "message": "Hook execution failed",
                    "duration_ms": 50,
                    "created_at": "2024-01-15T10:25:00Z",
                },
            ],
        }

        return templates.TemplateResponse(
            "hooks/detail.html",
            {
                "request": request,
                "hook_info": hook_info,
                "current_user": current_user,
            },
        )

    except Exception as e:
        logger.error(f"Error in hooks detail UI: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to load hooks detail: {str(e)}"
        )


@router.get("/register", response_class=HTMLResponse)
async def hooks_register_ui(
    request: Request,
    current_user: str = Depends(get_current_user),
):
    """Hooks registration UI page."""
    try:
        registry = get_hook_registry()

        # Get available hook types (this would be implemented in a real system)
        # For now, we'll use mock data
        available_hooks = [
            {
                "name": "auto_format",
                "type": "post",
                "description": "Automatically formats code after write/edit operations",
                "supported_languages": ["python", "javascript", "java", "go", "rust"],
            },
            {
                "name": "auto_lint",
                "type": "post",
                "description": "Runs linters after write/edit operations",
                "supported_languages": ["python", "javascript", "java"],
            },
            {
                "name": "security_check",
                "type": "pre",
                "description": "Performs security checks before tool execution",
                "supported_tools": ["write", "edit", "bash"],
            },
        ]

        # Get currently registered hooks
        registered_hooks = registry.list_hooks()

        return templates.TemplateResponse(
            "hooks/register.html",
            {
                "request": request,
                "available_hooks": available_hooks,
                "registered_hooks": registered_hooks,
                "current_user": current_user,
            },
        )

    except Exception as e:
        logger.error(f"Error in hooks register UI: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to load hooks register: {str(e)}"
        )


@router.post("/register")
async def hooks_register_post(
    request: Request,
    current_user: str = Depends(get_current_user),
):
    """Register hooks via UI."""
    try:
        form_data = await request.form()
        hook_name = form_data.get("hook_name")
        tool_name = form_data.get("tool_name")
        hook_type = form_data.get("hook_type")

        if not hook_name or not tool_name or not hook_type:
            raise HTTPException(
                status_code=400, detail="Hook name, tool name, and type are required"
            )

        registry = get_hook_registry()

        # In a real implementation, this would register the hook
        # For now, we'll just log it
        logger.info(f"Registering hook {hook_name} for tool {tool_name} as {hook_type}")

        # Redirect to hooks list
        return RedirectResponse("/ui/hooks/", status_code=303)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error registering hook: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to register hook: {str(e)}"
        )


@router.post("/unregister")
async def hooks_unregister_post(
    request: Request,
    current_user: str = Depends(get_current_user),
):
    """Unregister hooks via UI."""
    try:
        form_data = await request.form()
        tool_name = form_data.get("tool_name")

        if not tool_name:
            raise HTTPException(status_code=400, detail="Tool name is required")

        registry = get_hook_registry()

        # In a real implementation, this would unregister the hooks for the tool
        # For now, we'll just log it
        logger.info(f"Unregistering hooks for tool {tool_name}")

        # Redirect to hooks list
        return RedirectResponse("/ui/hooks/", status_code=303)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error unregistering hooks: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to unregister hooks: {str(e)}"
        )


@router.get("/statistics", response_class=HTMLResponse)
async def hooks_statistics_ui(
    request: Request,
    current_user: str = Depends(get_current_user),
):
    """Hooks statistics UI page."""
    try:
        # In a real implementation, this would query the audit log database
        # For now, we'll use mock data
        statistics = {
            "total_hooks": 10,
            "successful_executions": 950,
            "failed_executions": 50,
            "average_duration_ms": 125,
            "hook_types": {
                "pre": 3,
                "post": 7,
            },
            "tool_usage": {
                "write": 300,
                "edit": 250,
                "read": 200,
                "bash": 150,
                "grep": 100,
            },
            "recent_failures": [
                {
                    "hook_name": "auto_lint",
                    "tool_name": "edit",
                    "error": "No linter found",
                    "count": 5,
                    "last_occurrence": "2024-01-15T10:25:00Z",
                },
                {
                    "hook_name": "security_check",
                    "tool_name": "write",
                    "error": "Permission denied",
                    "count": 3,
                    "last_occurrence": "2024-01-15T09:45:00Z",
                },
            ],
        }

        return templates.TemplateResponse(
            "hooks/statistics.html",
            {
                "request": request,
                "statistics": statistics,
                "current_user": current_user,
            },
        )

    except Exception as e:
        logger.error(f"Error in hooks statistics UI: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to load hooks statistics: {str(e)}"
        )


# Helper function to initialize the UI router
def setup_hooks_ui():
    """Setup hooks UI routes."""
    return router
