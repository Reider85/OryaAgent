"""BranchManager UI (B-18) - visualize branches, merge dialog.

Provides web interface for managing session branches and merges.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from app.core.branch_manager import get_branch_manager
from app.core.branch_merger import get_branch_merger
from app.core.session import SessionManager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ui/api", tags=["nextjs-web-ui"])


class BranchModel(BaseModel):
    """Branch model."""
    id: str
    name: str
    parent_session_id: str
    parent_turn_id: str
    created_at: str
    status: str
    turn_count: int
    metadata: Dict[str, Any]


class MergeModel(BaseModel):
    """Merge model."""
    id: str
    parent_session_id: str
    branch_session_id: str
    merge_strategy: str
    conflict_resolution: str
    created_at: str
    status: str
    result: Optional[Dict[str, Any]] = None


class BranchFilter(BaseModel):
    """Branch filter model."""
    parent_session_id: Optional[str] = None
    status: Optional[str] = None
    search: Optional[str] = None
    limit: int = 50
    offset: int = 0


class BranchManagerUI:
    """UI for managing session branches."""

    def __init__(self):
        self.branch_manager = get_branch_manager()
        self.branch_merger = get_branch_merger()
        self.session_manager = SessionManager()

    async def list_branches(self, filter: BranchFilter) -> Dict[str, Any]:
        """List branches with filtering."""
        try:
            # Get all branches
            if filter.parent_session_id:
                branches = await self.branch_manager.list_branches(filter.parent_session_id)
            else:
                # Get all sessions and filter branches
                all_sessions = await self.session_manager.list_sessions()
                branches = []
                for session in all_sessions:
                    if session.get("metadata", {}).get("parent_session_id"):
                        session_branches = await self.branch_manager.list_branches(session["id"])
                        branches.extend(session_branches)

            # Apply search filter
            if filter.search:
                search_term = filter.search.lower()
                filtered_branches = [
                    branch for branch in branches
                    if search_term in branch.get("name", "").lower()
                    or search_term in branch.get("metadata", {}).get("branch_name", "").lower()
                ]
            else:
                filtered_branches = branches

            # Apply status filter
            if filter.status:
                filtered_branches = [
                    branch for branch in filtered_branches
                    if branch.get("status") == filter.status
                ]

            # Sort by created_at (newest first)
            filtered_branches.sort(key=lambda x: x.get("created_at", ""), reverse=True)

            # Apply pagination
            total_count = len(filtered_branches)
            paginated_branches = filtered_branches[filter.offset : filter.offset + filter.limit]

            # Format branch models
            branch_models = []
            for branch in paginated_branches:
                turn_count = await self.session_manager.get_session_turn_count(branch["id"])
                branch_models.append(BranchModel(
                    id=branch["id"],
                    name=branch.get("name", "Untitled Branch"),
                    parent_session_id=branch.get("parent_session_id", ""),
                    parent_turn_id=branch.get("parent_turn_id", ""),
                    created_at=branch.get("created_at", ""),
                    status=branch.get("status", "active"),
                    turn_count=turn_count,
                    metadata=branch.get("metadata", {}),
                ))

            return {
                "branches": branch_models,
                "total_count": total_count,
                "filtered_count": len(filtered_branches),
                "limit": filter.limit,
                "offset": filter.offset,
            }

        except Exception as e:
            logger.error(f"Failed to list branches: {e}")
            raise HTTPException(status_code=500, detail=f"Failed to list branches: {str(e)}")

    async def get_branch_info(self, branch_id: str) -> BranchModel:
        """Get detailed information about a branch."""
        try:
            branch_info = await self.branch_manager.get_branch_info(branch_id)
            if not branch_info:
                raise HTTPException(status_code=404, detail="Branch not found")

            turn_count = await self.session_manager.get_session_turn_count(branch_id)
            
            return BranchModel(
                id=branch_info["id"],
                name=branch_info["name"],
                parent_session_id=branch_info["parent_session_id"],
                parent_turn_id=branch_info["parent_turn_id"],
                created_at=branch_info["created_at"],
                status=branch_info["status"],
                turn_count=turn_count,
                metadata=branch_info["metadata"],
            )

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Failed to get branch info: {e}")
            raise HTTPException(status_code=500, detail=f"Failed to get branch info: {str(e)}")

    async def create_branch(
        self,
        parent_session_id: str,
        parent_turn_id: Optional[str] = None,
        branch_name: Optional[str] = None,
    ) -> BranchModel:
        """Create a new branch."""
        try:
            branch_id = await self.branch_manager.fork_session(
                parent_session_id, parent_turn_id, branch_name
            )

            # Get branch info
            branch_info = await self.branch_manager.get_branch_info(branch_id)
            turn_count = await self.session_manager.get_session_turn_count(branch_id)

            return BranchModel(
                id=branch_info["id"],
                name=branch_info["name"],
                parent_session_id=branch_info["parent_session_id"],
                parent_turn_id=branch_info["parent_turn_id"],
                created_at=branch_info["created_at"],
                status=branch_info["status"],
                turn_count=turn_count,
                metadata=branch_info["metadata"],
            )

        except Exception as e:
            logger.error(f"Failed to create branch: {e}")
            raise HTTPException(status_code=500, detail=f"Failed to create branch: {str(e)}")

    async def delete_branch(self, branch_id: str) -> bool:
        """Delete a branch."""
        try:
            success = await self.branch_manager.delete_branch(branch_id)
            if not success:
                raise HTTPException(status_code=404, detail="Branch not found")
            return True

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Failed to delete branch: {e}")
            raise HTTPException(status_code=500, detail=f"Failed to delete branch: {str(e)}")

    async def merge_branches(
        self,
        parent_session_id: str,
        branch_session_id: str,
        merge_strategy: str = "auto",
        conflict_resolution: str = "parent_wins",
    ) -> MergeModel:
        """Merge a branch into the parent session."""
        try:
            # Perform merge
            merge_result = await self.branch_merger.merge_branches(
                parent_session_id,
                branch_session_id,
                merge_strategy,
                conflict_resolution,
            )

            # Create merge record
            merge_id = f"merge_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            merge_model = MergeModel(
                id=merge_id,
                parent_session_id=parent_session_id,
                branch_session_id=branch_session_id,
                merge_strategy=merge_strategy,
                conflict_resolution=conflict_resolution,
                created_at=datetime.utcnow().isoformat(),
                status="completed",
                result=merge_result,
            )

            return merge_model

        except Exception as e:
            logger.error(f"Failed to merge branches: {e}")
            raise HTTPException(status_code=500, detail=f"Failed to merge branches: {str(e)}")

    async def list_merge_history(self, session_id: str) -> List[Dict[str, Any]]:
        """List merge history for a session."""
        try:
            return await self.branch_merger.list_merge_history(session_id)

        except Exception as e:
            logger.error(f"Failed to list merge history: {e}")
            return []

    async def get_branch_differences(self, parent_session_id: str, branch_session_id: str) -> Dict[str, Any]:
        """Get differences between parent and branch."""
        try:
            # Get turns from both sessions
            parent_turns = await self.session_manager.get_session_turns(parent_session_id)
            branch_turns = await self.session_manager.get_session_turns(branch_session_id)

            # Find fork point
            fork_point = await self.branch_merger._find_fork_point(parent_turns, branch_turns)
            if not fork_point:
                return {"error": "Could not find fork point"}

            # Analyze differences
            differences = await self.branch_merger._analyze_differences(
                parent_turns, branch_turns, fork_point
            )

            return {
                "fork_point": fork_point,
                "differences": differences,
                "parent_turns_after_fork": len(differences["unique_parent"]),
                "branch_turns_after_fork": len(differences["unique_branch"]),
                "conflicts": len(differences["conflicts"]),
            }

        except Exception as e:
            logger.error(f"Failed to get branch differences: {e}")
            return {"error": str(e)}

    async def get_merge_strategies(self) -> List[Dict[str, Any]]:
        """Get available merge strategies."""
        return [
            {
                "name": "auto",
                "description": "Automatically merge turns, resolving conflicts based on strategy",
                "conflict_resolution_options": ["parent_wins", "branch_wins", "manual"],
            },
            {
                "name": "preserve_branch",
                "description": "Preserve all branch turns and append to parent session",
                "conflict_resolution_options": ["append_all"],
            },
        ]

    async def get_branch_statistics(self) -> Dict[str, Any]:
        """Get branch statistics."""
        try:
            # Get all sessions
            all_sessions = await self.session_manager.list_sessions()
            
            # Count branches
            branches = 0
            active_branches = 0
            total_merges = 0
            
            for session in all_sessions:
                if session.get("metadata", {}).get("parent_session_id"):
                    branches += 1
                    if session.get("status") == "active":
                        active_branches += 1
                
                # Count merges
                merge_history = await self.branch_merger.list_merge_history(session["id"])
                total_merges += len(merge_history)

            return {
                "total_branches": branches,
                "active_branches": active_branches,
                "completed_branches": branches - active_branches,
                "total_merges": total_merges,
                "average_branches_per_session": branches / len(all_sessions) if all_sessions else 0,
            }

        except Exception as e:
            logger.error(f"Failed to get branch statistics: {e}")
            return {"error": str(e)}


# Global instance
_branch_manager_ui = None


def get_branch_manager_ui() -> BranchManagerUI:
    """Get the global branch manager UI instance."""
    global _branch_manager_ui
    if _branch_manager_ui is None:
        _branch_manager_ui = BranchManagerUI()
    return _branch_manager_ui


@router.get("/branches")
async def list_branches(
    parent_session_id: Optional[str] = Query(None, description="Filter by parent session ID"),
    status: Optional[str] = Query(None, description="Filter by status"),
    search: Optional[str] = Query(None, description="Search term"),
    limit: int = Query(50, ge=1, le=100, description="Maximum number of branches"),
    offset: int = Query(0, ge=0, description="Offset for pagination"),
):
    """List branches with optional filtering."""
    filter = BranchFilter(
        parent_session_id=parent_session_id,
        status=status,
        search=search,
        limit=limit,
        offset=offset,
    )
    branch_manager_ui = get_branch_manager_ui()
    return await branch_manager_ui.list_branches(filter)


@router.get("/branches/{branch_id}")
async def get_branch_info(branch_id: str):
    """Get detailed information about a branch."""
    branch_manager_ui = get_branch_manager_ui()
    return await branch_manager_ui.get_branch_info(branch_id)


@router.post("/branches")
async def create_branch(
    parent_session_id: str,
    parent_turn_id: Optional[str] = None,
    branch_name: Optional[str] = None,
):
    """Create a new branch."""
    branch_manager_ui = get_branch_manager_ui()
    return await branch_manager_ui.create_branch(parent_session_id, parent_turn_id, branch_name)


@router.delete("/branches/{branch_id}")
async def delete_branch(branch_id: str):
    """Delete a branch."""
    branch_manager_ui = get_branch_manager_ui()
    success = await branch_manager_ui.delete_branch(branch_id)
    return {"success": success}


@router.post("/branches/{branch_id}/merge")
async def merge_branches(
    branch_id: str,
    parent_session_id: str,
    merge_strategy: str = "auto",
    conflict_resolution: str = "parent_wins",
):
    """Merge a branch into the parent session."""
    branch_manager_ui = get_branch_manager_ui()
    return await branch_manager_ui.merge_branches(
        parent_session_id, branch_id, merge_strategy, conflict_resolution
    )


@router.get("/branches/{branch_id}/differences")
async def get_branch_differences(branch_id: str, parent_session_id: str):
    """Get differences between parent and branch."""
    branch_manager_ui = get_branch_manager_ui()
    return await branch_manager_ui.get_branch_differences(parent_session_id, branch_id)


@router.get("/branches/statistics")
async def get_branch_statistics():
    """Get branch statistics."""
    branch_manager_ui = get_branch_manager_ui()
    return await branch_manager_ui.get_branch_statistics()


@router.get("/merge/strategies")
async def get_merge_strategies():
    """Get available merge strategies."""
    branch_manager_ui = get_branch_manager_ui()
    return await branch_manager_ui.get_merge_strategies()


@router.get("/sessions/{session_id}/merge-history")
async def get_merge_history(session_id: str):
    """Get merge history for a session."""
    branch_manager_ui = get_branch_manager_ui()
    return await branch_manager_ui.list_merge_history(session_id)