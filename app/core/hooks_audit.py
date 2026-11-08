"""Audit logging utilities for hooks framework (B-04, B-20)."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any, Optional

from app.core.observability.spans import current_turn_trace_id
from app.core.sqlite_store import get_sqlite_store


def _add_hook_execution(entry: dict[str, Any]) -> None:
    """Add a hook execution entry to the SQLite store."""
    store = get_sqlite_store()

    # Convert datetime to ISO format for storage
    if entry.get("timestamp"):
        entry["timestamp"] = entry["timestamp"].isoformat()

    # Store the entry
    store.add_hook_execution(entry)


async def _filter_hook_executions(
    session_id: Optional[str] = None,
    tool_name: Optional[str] = None,
    hook_name: Optional[str] = None,
    hook_type: Optional[str] = None,
    success: Optional[bool] = None,
    hours: Optional[int] = None,
) -> list[dict[str, Any]]:
    """Filter hook execution history based on criteria."""
    store = get_sqlite_store()

    # Convert hours to start_date if provided
    start_date = None
    if hours:
        start_date = (datetime.utcnow() - timedelta(hours=hours)).isoformat()

    # Get filtered results from SQLite
    results = await store.get_hook_executions(
        session_id=session_id,
        tool_name=tool_name,
        hook_name=hook_name,
        hook_type=hook_type,
        success=success,
        start_date=start_date,
    )

    return results


async def record_hook_execution(
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
        "id": f"hook_exec_{datetime.utcnow().strftime('%Y%m%d_%H%M%S_%f')}",
        "session_id": session_id,
        "tool_name": tool_name,
        "hook_name": hook_name,
        "hook_type": hook_type,
        "success": success,
        "message": message,
        "duration_ms": duration_ms,
        "timestamp": datetime.utcnow().isoformat(),
        "turn_id": turn_id,
        "trace_id": current_turn_trace_id(),
        "metadata": {"recorded_at": datetime.utcnow().isoformat()},
    }

    await _add_hook_execution(entry)


async def get_hook_executions(
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
    # Convert hours to start_date
    start_date = None
    if hours:
        start_date = (datetime.utcnow() - timedelta(hours=hours)).isoformat()

    # Get filtered results from SQLite
    store = get_sqlite_store()
    filtered = await store.get_hook_executions(
        session_id=session_id,
        tool_name=tool_name,
        hook_name=hook_name,
        hook_type=hook_type,
        success=success,
        start_date=start_date,
        limit=limit,
        offset=offset,
    )

    # Convert to serializable format
    entries = []
    for entry in filtered:
        entries.append(
            {
                "id": entry.get("id"),
                "session_id": entry.get("session_id"),
                "tool_name": entry.get("tool_name"),
                "hook_name": entry.get("hook_name"),
                "hook_type": entry.get("hook_type"),
                "success": entry.get("success"),
                "message": entry.get("message"),
                "duration_ms": entry.get("duration_ms"),
                "timestamp": entry.get("timestamp"),
                "metadata": entry.get("metadata", {}),
            }
        )

    return {
        "total": len(filtered),
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
        },
    }


async def get_hook_statistics(hours: int = 24) -> dict[str, Any]:
    """Get hook execution statistics."""
    # Get statistics from SQLite store
    store = get_sqlite_store()
    stats = await store.get_hooks_statistics(hours)

    # Group by type
    by_type = {"pre": 0, "post": 0}
    for entry in stats["tool_breakdown"]:
        hook_type = entry.get("hook_type", "unknown")
        if hook_type in by_type:
            by_type[hook_type] += entry["total"]

    return {
        "total_executions": stats["total_executions"],
        "successful_executions": stats["successful_executions"],
        "success_rate": stats["success_rate"] * 100,  # Convert to percentage
        "average_duration_ms": stats["average_duration_ms"],
        "by_tool": stats["tool_breakdown"],
        "by_hook": {},  # TODO: Implement hook breakdown in SQLiteStore
        "by_type": by_type,
        "time_window_hours": hours,
    }


async def get_hook_execution(execution_id: str) -> Optional[dict[str, Any]]:
    """Get a specific hook execution by ID."""
    store = get_sqlite_store()
    result = await store.get_hook_execution(execution_id)

    if result:
        return {
            "id": result.get("id"),
            "session_id": result.get("session_id"),
            "tool_name": result.get("tool_name"),
            "hook_name": result.get("hook_name"),
            "hook_type": result.get("hook_type"),
            "success": result.get("success"),
            "message": result.get("message"),
            "duration_ms": result.get("duration_ms"),
            "timestamp": result.get("timestamp"),
            "metadata": result.get("metadata", {}),
        }

    return None


async def clear_hook_history() -> int:
    """Clear hook execution history."""
    store = get_sqlite_store()

    # Get current count before clearing
    current_executions = await store.get_hook_executions()
    count = len(current_executions)

    # Clear all entries
    for entry in current_executions:
        await store.delete_hook_execution(entry["id"])

    return count
