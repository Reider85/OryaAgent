"""Next.js Web UI API endpoints for session management (B-12).

This module provides web-specific endpoints for the Next.js frontend,
wrapping the existing session API with the expected format and functionality.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Query, WebSocket, WebSocketDisconnect

from app.api.sessions import (
    create_new_session,
    delete_session,
    get_session_endpoint,
    list_sessions_endpoint,
    patch_session,
)

router = APIRouter(prefix="/web/api/sessions", tags=["web sessions"])


# WebSocket manager for session updates
class SessionWebSocketManager:
    """Manager for WebSocket connections to session updates."""

    def __init__(self):
        self.active_connections: dict[str, list[WebSocket]] = {}

    async def connect(self, websocket: WebSocket, session_id: str):
        """Accept a WebSocket connection for a specific session."""
        await websocket.accept()
        if session_id not in self.active_connections:
            self.active_connections[session_id] = []
        self.active_connections[session_id].append(websocket)

    def disconnect(self, websocket: WebSocket, session_id: str):
        """Remove a WebSocket connection."""
        if session_id in self.active_connections:
            if websocket in self.active_connections[session_id]:
                self.active_connections[session_id].remove(websocket)
            if not self.active_connections[session_id]:
                del self.active_connections[session_id]

    async def broadcast_session_update(self, session_id: str, message: dict):
        """Broadcast a session update to all connected clients for this session."""
        if session_id in self.active_connections:
            for websocket in self.active_connections[session_id]:
                try:
                    await websocket.send_text(json.dumps(message))
                except Exception:
                    # Remove disconnected clients
                    self.active_connections[session_id].remove(websocket)


session_websocket_manager = SessionWebSocketManager()


class WebSessionCreate:
    """Request body for POST /web/api/sessions."""

    name: str
    description: str | None = None
    workspace: str | None = None


class WebSessionFilter:
    """Query parameters for session filtering and search."""

    search: str | None = Query(
        None, description="Search by session name or description"
    )
    status: list[str] | None = Query(
        None, description="Filter by status (active, completed, archived)"
    )
    limit: int = Query(20, ge=1, le=100, description="Maximum number of results")
    offset: int = Query(0, ge=0, description="Offset for pagination")


class WebSessionResponse:
    """Response format for session data."""

    id: str
    name: str
    description: str | None
    created_at: str
    updated_at: str
    status: str
    message_count: int
    workspace: str | None
    branch_count: int | None
    last_message: str | None


def _format_session_response(session: dict[str, Any]) -> WebSessionResponse:
    """Format session data to match TypeScript interface."""
    # Map status from backend to frontend format
    status_map = {
        "active": "active",
        "completed": "completed",
        "closed": "archived",  # Backend uses 'closed' for archived
    }
    session_status = session.get("status", "active")
    frontend_status = status_map.get(session_status, session_status)

    return WebSessionResponse(
        id=session["session_id"],
        name=session.get("title", session.get("name", "Unnamed Session")),
        description=session.get("description"),
        created_at=session["created_at"],
        updated_at=session["updated_at"],
        status=frontend_status,
        message_count=len(session.get("messages", [])),
        workspace=session.get("working_dir"),
        branch_count=session.get("branch_count", 0),
        last_message=_get_last_message(session),
    )


def _get_last_message(session: dict[str, Any]) -> str | None:
    """Extract the last message from a session."""
    messages = session.get("messages", [])
    if not messages:
        return None

    # Get the last assistant message
    for msg in reversed(messages):
        if msg.get("role") == "assistant":
            content = msg.get("content", "")
            return content[:100] + "..." if len(content) > 100 else content

    return None


@router.post("")
async def create_web_session(body: WebSessionCreate) -> WebSessionResponse:
    """Create a new session for Next.js frontend."""
    try:
        # Convert to format expected by existing API
        session_data = {
            "title": body.name,
            "working_dir": body.workspace,
        }
        if body.description:
            session_data["metadata"] = {"description": body.description}

        # Create session using existing API
        session = await create_new_session(session_data)

        return _format_session_response(session)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/list")
async def list_web_sessions(filters: WebSessionFilter) -> dict[str, Any]:
    """List sessions with search and filtering for Next.js frontend."""
    try:
        # Map status filters
        status_map = {
            "active": "active",
            "completed": "completed",
            "archived": "closed",  # Frontend 'archived' maps to backend 'closed'
        }

        # Get sessions using existing API
        result = await list_sessions_endpoint(page=1, size=filters.limit)

        # Apply status filtering
        sessions = result["items"]
        if filters.status:
            status_filter_values = [status_map.get(s, s) for s in filters.status]
            sessions = [s for s in sessions if s.get("status") in status_filter_values]

        # Apply search filter
        if filters.search:
            search_term = filters.search.lower()
            sessions = [
                s
                for s in sessions
                if search_term in s.get("title", "").lower()
                or search_term in s.get("metadata", {}).get("description", "").lower()
                or any(
                    search_term in msg.get("content", "").lower()
                    for msg in s.get("messages", [])
                )
            ]

        # Apply offset
        if filters.offset > 0:
            sessions = sessions[filters.offset :]

        # Limit results
        sessions = sessions[: filters.limit]

        return {
            "sessions": [_format_session_response(s) for s in sessions],
            "total": len(sessions),
            "limit": filters.limit,
            "offset": filters.offset,
        }

    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/{session_id}")
async def get_web_session(session_id: str) -> WebSessionResponse:
    """Get session details for Next.js frontend."""
    try:
        session = await get_session_endpoint(session_id)
        return _format_session_response(session)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.patch("/{session_id}")
async def update_web_session(
    session_id: str, updates: dict[str, Any]
) -> WebSessionResponse:
    """Update session for Next.js frontend."""
    try:
        # Convert to format expected by existing API
        patch_data = {}

        if "name" in updates:
            patch_data["title"] = updates["name"]

        if "description" in updates:
            patch_data["metadata"] = {"description": updates["description"]}

        if "status" in updates:
            # Map status values (frontend to backend)
            status_map = {
                "archived": "closed",
                "completed": "completed",
                "active": "active",
            }
            patch_data["status"] = status_map.get(updates["status"], updates["status"])

        if patch_data:
            session = await patch_session(session_id, patch_data)
        else:
            session = await get_session_endpoint(session_id)

        return _format_session_response(session)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{session_id}")
async def delete_web_session(session_id: str) -> dict[str, str]:
    """Delete session for Next.js frontend."""
    try:
        await delete_session(session_id)

        # Broadcast session deletion to all connected clients
        await session_websocket_manager.broadcast_session_update(
            session_id,
            {
                "type": "session_deleted",
                "sessionId": session_id,
                "timestamp": datetime.utcnow().isoformat(),
            },
        )

        return {"session_id": session_id, "status": "deleted"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.websocket("/ws")
async def sessions_websocket_endpoint(websocket: WebSocket):
    """WebSocket endpoint for session updates (Next.js frontend)."""
    await websocket.accept()

    # This is a general session updates WebSocket
    # In a real implementation, you might want to subscribe to specific sessions
    try:
        while True:
            # Keep the connection alive and listen for client messages
            data = await websocket.receive_text()
            try:
                message = json.loads(data)

                # Handle client subscription requests
                if message.get("type") == "subscribe":
                    session_id = message.get("sessionId")
                    if session_id:
                        await session_websocket_manager.connect(websocket, session_id)
                        await websocket.send_text(
                            json.dumps(
                                {
                                    "type": "subscribed",
                                    "sessionId": session_id,
                                    "timestamp": datetime.utcnow().isoformat(),
                                }
                            )
                        )

            except json.JSONDecodeError:
                await websocket.send_text(
                    json.dumps(
                        {
                            "type": "error",
                            "message": "Invalid JSON message",
                            "timestamp": datetime.utcnow().isoformat(),
                        }
                    )
                )

    except WebSocketDisconnect:
        # Clean up all connections for this websocket
        for (
            session_id,
            connections,
        ) in session_websocket_manager.active_connections.items():
            if websocket in connections:
                session_websocket_manager.disconnect(websocket, session_id)
