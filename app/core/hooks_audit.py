"""Audit logging utilities for hooks framework (B-04, B-20)."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any, Optional

from app.core.observability.spans import current_turn_trace_id

# In-memory storage for hook execution history (in production, this would be in a database)
_hook_execution_history: list[dict[str, Any]] = []
_max_history_entries = 1000


def _add_hook_execution(entry: dict[str, Any]) -> None:
    """Add a hook execution entry to the history."""
    _hook_execution_history.append(entry)
    
    # Keep only the most recent entries
    if len(_hook_execution_history) > _max_history_entries:
        _hook_execution_history.pop(0)


def _filter_hook_executions(
    session_id: Optional[str] = None,
    tool_name: Optional[str] = None,
    hook_name: Optional[str] = None,
    hook_type: Optional[str] = None,
    success: Optional[bool] = None,
    hours: Optional[int] = None,
) -> list[dict[str, Any]]:
    """Filter hook execution history based on criteria."""
    filtered = _hook_execution_history
    
    if session_id:
        filtered = [e for e in filtered if e.get("session_id") == session_id]
    
    if tool_name:
        filtered = [e for e in filtered if e.get("tool_name") == tool_name]
    
    if hook_name:
        filtered = [e for e in filtered if e.get("hook_name") == hook_name]
    
    if hook_type:
        filtered = [e for e in filtered if e.get("hook_type") == hook_type]
    
    if success is not None:
        filtered = [e for e in filtered if e.get("success") == success]
    
    if hours:
        cutoff_time = datetime.utcnow() - timedelta(hours=hours)
        filtered = [e for e in filtered if e.get("timestamp", datetime.min) >= cutoff_time]
    
    return sorted(filtered, key=lambda x: x.get("timestamp", datetime.min), reverse=True)


def record_hook_execution(
    session_id: str,
    tool_name: str,
    hook_name: str,
    hook_type: str,
    success: bool,
    message: Optional[str] = None,
    duration_ms: Optional[float] = None,
    turn_id: Optional[str] = None,
) -> None:
    """Record a hook execution in the audit log.
    
    This function should be called from the hooks framework to record executions.
    """
    entry = {
        "session_id": session_id,
        "tool_name": tool_name,
        "hook_name": hook_name,
        "hook_type": hook_type,
        "success": success,
        "message": message,
        "duration_ms": duration_ms,
        "timestamp": datetime.utcnow(),
        "turn_id": turn_id,
        "trace_id": current_turn_trace_id(),
    }
    
    _add_hook_execution(entry)


def get_hook_executions(
    session_id: Optional[str] = None,
    tool_name: Optional[str] = None,
    hook_name: Optional[str] = None,
    hook_type: Optional[str] = None,
    success: Optional[bool] = None,
    hours: int = 24,
    limit: int = 100,
    offset: int = 0,
) -> dict[str, Any]:
    """Get hook execution records with filtering and pagination."""
    filtered = _filter_hook_executions(
        session_id=session_id,
        tool_name=tool_name,
        hook_name=hook_name,
        hook_type=hook_type,
        success=success,
        hours=hours,
    )
    
    # Apply pagination
    total = len(filtered)
    paginated = filtered[offset:offset + limit]
    
    # Convert to serializable format
    entries = []
    for entry in paginated:
        entries.append({
            "session_id": entry.get("session_id"),
            "tool_name": entry.get("tool_name"),
            "hook_name": entry.get("hook_name"),
            "hook_type": entry.get("hook_type"),
            "success": entry.get("success"),
            "message": entry.get("message"),
            "duration_ms": entry.get("duration_ms"),
            "timestamp": entry.get("timestamp").isoformat() if entry.get("timestamp") else None,
            "turn_id": entry.get("turn_id"),
            "trace_id": entry.get("trace_id"),
        })
    
    return {
        "total": total,
        "offset": offset,
        "limit": limit,
        "entries": entries,
        "filters": {
            "session_id": session_id,
            "tool_name": tool_name,
            "hook_name": hook_name,
            "hook_type": hook_type,
            "success": success,
            "hours": hours,
        }
    }


def get_hook_statistics(hours: int = 24) -> dict[str, Any]:
    """Get hook execution statistics."""
    filtered = _filter_hook_executions(hours=hours)
    
    if not filtered:
        return {
            "total_executions": 0,
            "success_rate": 0.0,
            "average_duration_ms": 0.0,
            "by_tool": {},
            "by_hook": {},
            "by_type": {"pre": 0, "post": 0},
        }
    
    total_executions = len(filtered)
    successful_executions = sum(1 for e in filtered if e.get("success"))
    success_rate = (successful_executions / total_executions) * 100 if total_executions > 0 else 0.0
    
    durations = [e.get("duration_ms") for e in filtered if e.get("duration_ms") is not None]
    average_duration_ms = sum(durations) / len(durations) if durations else 0.0
    
    # Group by tool
    by_tool = {}
    for entry in filtered:
        tool_name = entry.get("tool_name")
        if tool_name not in by_tool:
            by_tool[tool_name] = {"total": 0, "successful": 0}
        by_tool[tool_name]["total"] += 1
        if entry.get("success"):
            by_tool[tool_name]["successful"] += 1
    
    # Group by hook
    by_hook = {}
    for entry in filtered:
        hook_name = entry.get("hook_name")
        if hook_name not in by_hook:
            by_hook[hook_name] = {"total": 0, "successful": 0}
        by_hook[hook_name]["total"] += 1
        if entry.get("success"):
            by_hook[hook_name]["successful"] += 1
    
    # Group by type
    by_type = {"pre": 0, "post": 0}
    for entry in filtered:
        hook_type = entry.get("hook_type")
        if hook_type in by_type:
            by_type[hook_type] += 1
    
    return {
        "total_executions": total_executions,
        "successful_executions": successful_executions,
        "success_rate": success_rate,
        "average_duration_ms": average_duration_ms,
        "by_tool": by_tool,
        "by_hook": by_hook,
        "by_type": by_type,
        "time_window_hours": hours,
    }


def clear_hook_history() -> int:
    """Clear hook execution history."""
    count = len(_hook_execution_history)
    _hook_execution_history.clear()
    return count