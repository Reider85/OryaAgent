"""Hooks UI: view executed hooks (B-20) - audit log.

Provides web interface for viewing and managing hook execution logs.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from app.core.hooks import get_hook_registry
from app.core.hooks_audit import get_hook_audit_log

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ui/api", tags=["nextjs-web-ui"])


class HookExecutionModel(BaseModel):
    """Hook execution model."""
    id: str
    session_id: str
    tool_name: str
    hook_name: str
    hook_type: str
    success: bool
    message: str
    duration_ms: float
    timestamp: str
    metadata: Dict[str, Any]


class HookFilter(BaseModel):
    """Hook execution filter model."""
    session_id: Optional[str] = None
    tool_name: Optional[str] = None
    hook_name: Optional[str] = None
    hook_type: Optional[str] = None
    success: Optional[bool] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    limit: int = 100
    offset: int = 0


class HookStatisticsModel(BaseModel):
    """Hook statistics model."""
    total_executions: int
    successful_executions: int
    failed_executions: int
    success_rate: float
    average_duration_ms: float
    tool_breakdown: Dict[str, Dict[str, Any]]
    hook_breakdown: Dict[str, Dict[str, Any]]
    recent_failures: List[Dict[str, Any]]


class HooksUI:
    """UI for managing hooks and viewing execution logs."""

    def __init__(self):
        self.hook_registry = get_hook_registry()
        self.audit_log = get_hook_audit_log()

    async def list_hook_executions(self, filter: HookFilter) -> Dict[str, Any]:
        """List hook executions with filtering."""
        try:
            # Get all executions
            all_executions = await self.audit_log.get_hook_executions()
            
            # Apply session filter
            if filter.session_id:
                all_executions = [
                    exec for exec in all_executions
                    if exec.get("session_id") == filter.session_id
                ]
            
            # Apply tool filter
            if filter.tool_name:
                all_executions = [
                    exec for exec in all_executions
                    if exec.get("tool_name") == filter.tool_name
                ]
            
            # Apply hook filter
            if filter.hook_name:
                all_executions = [
                    exec for exec in all_executions
                    if exec.get("hook_name") == filter.hook_name
                ]
            
            # Apply hook type filter
            if filter.hook_type:
                all_executions = [
                    exec for exec in all_executions
                    if exec.get("hook_type") == filter.hook_type
                ]
            
            # Apply success filter
            if filter.success is not None:
                all_executions = [
                    exec for exec in all_executions
                    if exec.get("success") == filter.success
                ]
            
            # Apply date filters
            if filter.start_date:
                start_dt = datetime.fromisoformat(filter.start_date.replace('Z', '+00:00'))
                all_executions = [
                    exec for exec in all_executions
                    if datetime.fromisoformat(exec.get("timestamp", "").replace('Z', '+00:00')) >= start_dt
                ]
            
            if filter.end_date:
                end_dt = datetime.fromisoformat(filter.end_date.replace('Z', '+00:00'))
                all_executions = [
                    exec for exec in all_executions
                    if datetime.fromisoformat(exec.get("timestamp", "").replace('Z', '+00:00')) <= end_dt
                ]
            
            # Sort by timestamp (newest first)
            all_executions.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
            
            # Apply pagination
            total_count = len(all_executions)
            paginated_executions = all_executions[filter.offset : filter.offset + filter.limit]
            
            # Format execution models
            execution_models = []
            for execution in paginated_executions:
                execution_models.append(HookExecutionModel(
                    id=execution.get("id", ""),
                    session_id=execution.get("session_id", ""),
                    tool_name=execution.get("tool_name", ""),
                    hook_name=execution.get("hook_name", ""),
                    hook_type=execution.get("hook_type", ""),
                    success=execution.get("success", False),
                    message=execution.get("message", ""),
                    duration_ms=execution.get("duration_ms", 0.0),
                    timestamp=execution.get("timestamp", ""),
                    metadata=execution.get("metadata", {}),
                ))
            
            return {
                "executions": execution_models,
                "total_count": total_count,
                "filtered_count": len(all_executions),
                "limit": filter.limit,
                "offset": filter.offset,
            }

        except Exception as e:
            logger.error(f"Failed to list hook executions: {e}")
            raise HTTPException(status_code=500, detail=f"Failed to list hook executions: {str(e)}")

    async def get_hook_execution(self, execution_id: str) -> HookExecutionModel:
        """Get detailed information about a specific hook execution."""
        try:
            execution = await self.audit_log.get_hook_execution(execution_id)
            if not execution:
                raise HTTPException(status_code=404, detail="Hook execution not found")
            
            return HookExecutionModel(
                id=execution.get("id", ""),
                session_id=execution.get("session_id", ""),
                tool_name=execution.get("tool_name", ""),
                hook_name=execution.get("hook_name", ""),
                hook_type=execution.get("hook_type", ""),
                success=execution.get("success", False),
                message=execution.get("message", ""),
                duration_ms=execution.get("duration_ms", 0.0),
                timestamp=execution.get("timestamp", ""),
                metadata=execution.get("metadata", {}),
            )

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Failed to get hook execution: {e}")
            raise HTTPException(status_code=500, detail=f"Failed to get hook execution: {str(e)}")

    async def get_hook_statistics(self, days: int = 7) -> HookStatisticsModel:
        """Get hook execution statistics."""
        try:
            # Get executions for the specified time period
            end_date = datetime.utcnow()
            start_date = end_date - timedelta(days=days)
            
            all_executions = await self.audit_log.get_hook_executions()
            
            # Filter by date
            filtered_executions = []
            for execution in all_executions:
                exec_timestamp = datetime.fromisoformat(execution.get("timestamp", "").replace('Z', '+00:00'))
                if start_date <= exec_timestamp <= end_date:
                    filtered_executions.append(execution)
            
            # Calculate basic statistics
            total_executions = len(filtered_executions)
            successful_executions = len([e for e in filtered_executions if e.get("success")])
            failed_executions = total_executions - successful_executions
            success_rate = successful_executions / total_executions if total_executions > 0 else 0
            
            # Calculate average duration
            durations = [e.get("duration_ms", 0) for e in filtered_executions]
            average_duration_ms = sum(durations) / len(durations) if durations else 0
            
            # Build tool breakdown
            tool_breakdown = {}
            for execution in filtered_executions:
                tool_name = execution.get("tool_name", "unknown")
                if tool_name not in tool_breakdown:
                    tool_breakdown[tool_name] = {
                        "total": 0,
                        "successful": 0,
                        "failed": 0,
                        "average_duration_ms": 0,
                    }
                
                tool_breakdown[tool_name]["total"] += 1
                if execution.get("success"):
                    tool_breakdown[tool_name]["successful"] += 1
                else:
                    tool_breakdown[tool_name]["failed"] += 1
            
            # Calculate average duration per tool
            for tool_name, stats in tool_breakdown.items():
                tool_executions = [e for e in filtered_executions if e.get("tool_name") == tool_name]
                durations = [e.get("duration_ms", 0) for e in tool_executions]
                stats["average_duration_ms"] = sum(durations) / len(durations) if durations else 0
            
            # Build hook breakdown
            hook_breakdown = {}
            for execution in filtered_executions:
                hook_name = execution.get("hook_name", "unknown")
                hook_type = execution.get("hook_type", "unknown")
                hook_key = f"{hook_name}_{hook_type}"
                
                if hook_key not in hook_breakdown:
                    hook_breakdown[hook_key] = {
                        "name": hook_name,
                        "type": hook_type,
                        "total": 0,
                        "successful": 0,
                        "failed": 0,
                        "average_duration_ms": 0,
                    }
                
                hook_breakdown[hook_key]["total"] += 1
                if execution.get("success"):
                    hook_breakdown[hook_key]["successful"] += 1
                else:
                    hook_breakdown[hook_key]["failed"] += 1
            
            # Calculate average duration per hook
            for hook_key, stats in hook_breakdown.items():
                hook_executions = [e for e in filtered_executions if f"{e.get('hook_name')}_{e.get('hook_type')}" == hook_key]
                durations = [e.get("duration_ms", 0) for e in hook_executions]
                stats["average_duration_ms"] = sum(durations) / len(durations) if durations else 0
            
            # Get recent failures
            recent_failures = [
                {
                    "id": e.get("id"),
                    "session_id": e.get("session_id"),
                    "tool_name": e.get("tool_name"),
                    "hook_name": e.get("hook_name"),
                    "message": e.get("message"),
                    "timestamp": e.get("timestamp"),
                }
                for e in filtered_executions
                if not e.get("success")
            ][:10]  # Limit to 10 most recent failures
            
            return HookStatisticsModel(
                total_executions=total_executions,
                successful_executions=successful_executions,
                failed_executions=failed_executions,
                success_rate=success_rate,
                average_duration_ms=average_duration_ms,
                tool_breakdown=tool_breakdown,
                hook_breakdown=hook_breakdown,
                recent_failures=recent_failures,
            )

        except Exception as e:
            logger.error(f"Failed to get hook statistics: {e}")
            raise HTTPException(status_code=500, detail=f"Failed to get hook statistics: {str(e)}")

    async def get_hook_registry_info(self) -> Dict[str, Any]:
        """Get information about registered hooks."""
        try:
            registry_info = self.hook_registry.list_hooks()
            
            # Get additional information about each hook
            hooks_info = {}
            for tool_name, hooks in registry_info.get("pre_hooks", {}).items():
                hooks_info[tool_name] = {
                    "pre_hooks": [hook.name for hook in hooks],
                    "post_hooks": [],
                }
            
            for tool_name, hooks in registry_info.get("post_hooks", {}).items():
                if tool_name not in hooks_info:
                    hooks_info[tool_name] = {
                        "pre_hooks": [],
                        "post_hooks": [],
                    }
                hooks_info[tool_name]["post_hooks"] = [hook.name for hook in hooks]
            
            return {
                "registry_info": registry_info,
                "hooks_by_tool": hooks_info,
                "total_pre_hooks": sum(len(hooks) for hooks in registry_info.get("pre_hooks", {}).values()),
                "total_post_hooks": sum(len(hooks) for hooks in registry_info.get("post_hooks", {}).values()),
            }

        except Exception as e:
            logger.error(f"Failed to get hook registry info: {e}")
            raise HTTPException(status_code=500, detail=f"Failed to get hook registry info: {str(e)}")

    async def clear_hook_executions(self, older_than_days: int = 30) -> Dict[str, Any]:
        """Clear old hook execution records."""
        try:
            cutoff_date = datetime.utcnow() - timedelta(days=older_than_days)
            
            # Get executions to delete
            all_executions = await self.audit_log.get_hook_executions()
            to_delete = [
                exec for exec in all_executions
                if datetime.fromisoformat(exec.get("timestamp", "").replace('Z', '+00:00')) < cutoff_date
            ]
            
            # Delete executions
            deleted_count = 0
            for execution in to_delete:
                await self.audit_log.delete_hook_execution(execution.get("id", ""))
                deleted_count += 1
            
            return {
                "success": True,
                "deleted_count": deleted_count,
                "cutoff_date": cutoff_date.isoformat(),
                "message": f"Deleted {deleted_count} hook execution records older than {older_than_days} days",
            }

        except Exception as e:
            logger.error(f"Failed to clear hook executions: {e}")
            raise HTTPException(status_code=500, detail=f"Failed to clear hook executions: {str(e)}")

    async def export_hook_executions(self, filter: HookFilter) -> str:
        """Export hook executions to JSON format."""
        try:
            # Get filtered executions
            executions_data = await self.list_hook_executions(filter)
            
            # Add export metadata
            export_data = {
                "export_timestamp": datetime.utcnow().isoformat(),
                "filter": filter.dict(),
                "executions": [exec.model_dump() for exec in executions_data["executions"]],
            }
            
            return export_data

        except Exception as e:
            logger.error(f"Failed to export hook executions: {e}")
            raise HTTPException(status_code=500, detail=f"Failed to export hook executions: {str(e)}")


# Global instance
_hooks_ui = None


def get_hooks_ui() -> HooksUI:
    """Get the global hooks UI instance."""
    global _hooks_ui
    if _hooks_ui is None:
        _hooks_ui = HooksUI()
    return _hooks_ui


@router.get("/hooks/executions")
async def list_hook_executions(
    session_id: Optional[str] = Query(None, description="Filter by session ID"),
    tool_name: Optional[str] = Query(None, description="Filter by tool name"),
    hook_name: Optional[str] = Query(None, description="Filter by hook name"),
    hook_type: Optional[str] = Query(None, description="Filter by hook type"),
    success: Optional[bool] = Query(None, description="Filter by success status"),
    start_date: Optional[str] = Query(None, description="Start date (ISO format)"),
    end_date: Optional[str] = Query(None, description="End date (ISO format)"),
    limit: int = Query(100, ge=1, le=1000, description="Maximum number of executions"),
    offset: int = Query(0, ge=0, description="Offset for pagination"),
):
    """List hook executions with optional filtering."""
    filter = HookFilter(
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
    hooks_ui = get_hooks_ui()
    return await hooks_ui.list_hook_executions(filter)


@router.get("/hooks/executions/{execution_id}")
async def get_hook_execution(execution_id: str):
    """Get detailed information about a specific hook execution."""
    hooks_ui = get_hooks_ui()
    return await hooks_ui.get_hook_execution(execution_id)


@router.get("/hooks/statistics")
async def get_hook_statistics(days: int = Query(7, ge=1, le=365, description="Number of days to analyze")):
    """Get hook execution statistics."""
    hooks_ui = get_hooks_ui()
    return await hooks_ui.get_hook_statistics(days)


@router.get("/hooks/registry")
async def get_hook_registry_info():
    """Get information about registered hooks."""
    hooks_ui = get_hooks_ui()
    return await hooks_ui.get_hook_registry_info()


@router.delete("/hooks/executions")
async def clear_hook_executions(older_than_days: int = Query(30, ge=1, le=365, description="Delete records older than N days")):
    """Clear old hook execution records."""
    hooks_ui = get_hooks_ui()
    return await hooks_ui.clear_hook_executions(older_than_days)


@router.get("/hooks/executions/export")
async def export_hook_executions(
    session_id: Optional[str] = Query(None, description="Filter by session ID"),
    tool_name: Optional[str] = Query(None, description="Filter by tool name"),
    hook_name: Optional[str] = Query(None, description="Filter by hook name"),
    hook_type: Optional[str] = Query(None, description="Filter by hook type"),
    success: Optional[bool] = Query(None, description="Filter by success status"),
    start_date: Optional[str] = Query(None, description="Start date (ISO format)"),
    end_date: Optional[str] = Query(None, description="End date (ISO format)"),
    limit: int = Query(1000, ge=1, le=10000, description="Maximum number of executions"),
    offset: int = Query(0, ge=0, description="Offset for pagination"),
):
    """Export hook executions to JSON format."""
    filter = HookFilter(
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
    hooks_ui = get_hooks_ui()
    return await hooks_ui.export_hook_executions(filter)