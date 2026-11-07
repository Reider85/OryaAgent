"""Next.js Web UI: session sidebar (B-12) - list, search, filter.

Provides session management functionality with search and filtering.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from app.core.session import SessionManager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ui/api", tags=["nextjs-web-ui"])


class SessionInfo(BaseModel):
    """Session information model."""
    id: str
    name: str
    created_at: str
    updated_at: str
    turn_count: int
    status: str


class SessionFilter(BaseModel):
    """Session filter model."""
    search: Optional[str] = None
    status: Optional[str] = None
    limit: int = 50
    offset: int = 0


class SessionSidebar:
    """Session sidebar for managing sessions."""

    def __init__(self):
        self.session_manager = SessionManager()

    async def list_sessions(self, filter: SessionFilter) -> Dict[str, Any]:
        """List sessions with filtering."""
        try:
            # Get all sessions
            all_sessions = await self.session_manager.list_sessions()
            
            # Apply search filter
            filtered_sessions = all_sessions
            if filter.search:
                search_term = filter.search.lower()
                filtered_sessions = [
                    session for session in all_sessions
                    if search_term in session["name"].lower()
                    or search_term in session.get("metadata", {}).get("description", "").lower()
                ]

            # Apply status filter
            if filter.status:
                filtered_sessions = [
                    session for session in filtered_sessions
                    if session.get("status") == filter.status
                ]

            # Sort by updated_at (newest first)
            filtered_sessions.sort(key=lambda x: x.get("updated_at", ""), reverse=True)

            # Apply pagination
            total_count = len(filtered_sessions)
            paginated_sessions = filtered_sessions[filter.offset : filter.offset + filter.limit]

            # Format session info
            session_infos = []
            for session in paginated_sessions:
                turn_count = await self.session_manager.get_session_turn_count(session["id"])
                session_infos.append(SessionInfo(
                    id=session["id"],
                    name=session.get("name", "Untitled Session"),
                    created_at=session.get("created_at", ""),
                    updated_at=session.get("updated_at", ""),
                    turn_count=turn_count,
                    status=session.get("status", "active"),
                ))

            return {
                "sessions": session_infos,
                "total_count": total_count,
                "filtered_count": len(filtered_sessions),
                "limit": filter.limit,
                "offset": filter.offset,
            }

        except Exception as e:
            logger.error(f"Failed to list sessions: {e}")
            raise HTTPException(status_code=500, detail=f"Failed to list sessions: {str(e)}")

    async def get_session_info(self, session_id: str) -> SessionInfo:
        """Get detailed information about a session."""
        try:
            session = await self.session_manager.get_session(session_id)
            if not session:
                raise HTTPException(status_code=404, detail="Session not found")

            turn_count = await self.session_manager.get_session_turn_count(session_id)
            
            return SessionInfo(
                id=session["id"],
                name=session.get("name", "Untitled Session"),
                created_at=session.get("created_at", ""),
                updated_at=session.get("updated_at", ""),
                turn_count=turn_count,
                status=session.get("status", "active"),
            )

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Failed to get session info: {e}")
            raise HTTPException(status_code=500, detail=f"Failed to get session info: {str(e)}")

    async def delete_session(self, session_id: str) -> bool:
        """Delete a session."""
        try:
            success = await self.session_manager.delete_session(session_id)
            if not success:
                raise HTTPException(status_code=404, detail="Session not found")
            return True

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Failed to delete session: {e}")
            raise HTTPException(status_code=500, detail=f"Failed to delete session: {str(e)}")

    async def update_session_name(self, session_id: str, name: str) -> bool:
        """Update session name."""
        try:
            session = await self.session_manager.get_session(session_id)
            if not session:
                raise HTTPException(status_code=404, detail="Session not found")

            # Update session name
            session["name"] = name
            await self.session_manager.update_session(session_id, {"name": name})
            return True

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Failed to update session name: {e}")
            raise HTTPException(status_code=500, detail=f"Failed to update session name: {str(e)}")

    async def get_session_statistics(self) -> Dict[str, Any]:
        """Get session statistics."""
        try:
            sessions = await self.session_manager.list_sessions()
            
            total_sessions = len(sessions)
            active_sessions = len([s for s in sessions if s.get("status") == "active"])
            completed_sessions = len([s for s in sessions if s.get("status") == "completed"])
            
            # Calculate average turns per session
            total_turns = 0
            for session in sessions:
                turn_count = await self.session_manager.get_session_turn_count(session["id"])
                total_turns += turn_count
            
            avg_turns = total_turns / total_sessions if total_sessions > 0 else 0

            return {
                "total_sessions": total_sessions,
                "active_sessions": active_sessions,
                "completed_sessions": completed_sessions,
                "average_turns_per_session": round(avg_turns, 2),
                "total_turns": total_turns,
            }

        except Exception as e:
            logger.error(f"Failed to get session statistics: {e}")
            raise HTTPException(status_code=500, detail=f"Failed to get session statistics: {str(e)}")


# Global instance
_session_sidebar = None


def get_session_sidebar() -> SessionSidebar:
    """Get the global session sidebar instance."""
    global _session_sidebar
    if _session_sidebar is None:
        _session_sidebar = SessionSidebar()
    return _session_sidebar


@router.get("/sessions")
async def list_sessions(
    search: Optional[str] = Query(None, description="Search term for session names"),
    status: Optional[str] = Query(None, description="Filter by status"),
    limit: int = Query(50, ge=1, le=100, description="Maximum number of sessions to return"),
    offset: int = Query(0, ge=0, description="Offset for pagination"),
):
    """List sessions with optional filtering and pagination."""
    filter = SessionFilter(search=search, status=status, limit=limit, offset=offset)
    session_sidebar = get_session_sidebar()
    return await session_sidebar.list_sessions(filter)


@router.get("/sessions/{session_id}")
async def get_session_info(session_id: str):
    """Get detailed information about a session."""
    session_sidebar = get_session_sidebar()
    return await session_sidebar.get_session_info(session_id)


@router.delete("/sessions/{session_id}")
async def delete_session(session_id: str):
    """Delete a session."""
    session_sidebar = get_session_sidebar()
    success = await session_sidebar.delete_session(session_id)
    return {"success": success}


@router.put("/sessions/{session_id}/name")
async def update_session_name(session_id: str, name: str):
    """Update session name."""
    session_sidebar = get_session_sidebar()
    success = await session_sidebar.update_session_name(session_id, name)
    return {"success": success}


@router.get("/sessions/statistics")
async def get_session_statistics():
    """Get session statistics."""
    session_sidebar = get_session_sidebar()
    return await session_sidebar.get_session_statistics()