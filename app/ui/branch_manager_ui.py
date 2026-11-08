"""BranchManager UI for B-18: visualize branches, merge dialog."""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.core.branch_manager import get_branch_manager
from app.core.security import get_current_user
from app.core.observability.spans import emit_span

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/ui/branches", tags=["branch-ui"])
templates = Jinja2Templates(directory="app/ui/templates")


@router.get("/", response_class=HTMLResponse)
async def branches_list_ui(
    request: Request,
    session_id: str = None,
    current_user: str = Depends(get_current_user),
):
    """Branches list UI page with enhanced visualization."""
    try:
        branch_manager = get_branch_manager()

        if session_id:
            branches = await branch_manager.list_branches(session_id)
            # Get performance metrics
            performance_metrics = await branch_manager.get_branch_performance_metrics(
                session_id
            )
        else:
            branches = []
            performance_metrics = {"branch_count": 0}

        # Process branches for better visualization
        processed_branches = []
        for branch in branches:
            branch_data = {
                **branch,
                "created_at_relative": _format_relative_time(branch["created_at"]),
                "status_class": _get_status_class(branch["status"]),
                "has_merge_history": len(
                    await branch_manager.get_merge_history(branch["id"])
                )
                > 0,
            }
            processed_branches.append(branch_data)

        return templates.TemplateResponse(
            "branches/list.html",
            {
                "request": request,
                "branches": processed_branches,
                "session_id": session_id,
                "performance_metrics": performance_metrics,
                "current_user": current_user,
            },
        )

    except Exception as e:
        logger.error(f"Error in branches list UI: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to load branches list: {str(e)}"
        )


@router.get("/tree", response_class=HTMLResponse)
async def branches_tree_ui(
    request: Request,
    session_id: str = None,
    current_user: str = Depends(get_current_user),
):
    """Branches tree visualization UI page."""
    try:
        branch_manager = get_branch_manager()

        if session_id:
            branches = await branch_manager.list_branches(session_id)
            # Build tree structure for visualization
            tree_data = _build_branch_tree(branches)
        else:
            tree_data = []

        return templates.TemplateResponse(
            "branches/tree.html",
            {
                "request": request,
                "tree_data": tree_data,
                "session_id": session_id,
                "current_user": current_user,
            },
        )

    except Exception as e:
        logger.error(f"Error in branches tree UI: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to load branches tree: {str(e)}"
        )


@router.get("/dashboard", response_class=HTMLResponse)
async def branches_dashboard_ui(
    request: Request,
    current_user: str = Depends(get_current_user),
):
    """Branches dashboard UI page with overview and statistics."""
    try:
        branch_manager = get_branch_manager()

        # Get all sessions with branches
        from app.db.session_log import list_sessions

        sessions = await list_sessions(limit=50)

        # Process sessions for dashboard
        dashboard_data = []
        for session in sessions:
            session_id = session["session_id"]
            branches = await branch_manager.list_branches(session_id)
            performance_metrics = await branch_manager.get_branch_performance_metrics(
                session_id
            )

            dashboard_item = {
                "session_id": session_id,
                "session_title": session.get("title", "Untitled Session"),
                "branch_count": len(branches),
                "performance_metrics": performance_metrics,
                "latest_activity": session.get("last_activity_at"),
                "created_at": session.get("created_at"),
            }
            dashboard_data.append(dashboard_item)

        return templates.TemplateResponse(
            "branches/dashboard.html",
            {
                "request": request,
                "dashboard_data": dashboard_data,
                "current_user": current_user,
            },
        )

    except Exception as e:
        logger.error(f"Error in branches dashboard UI: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to load branches dashboard: {str(e)}"
        )


@router.get("/compare/{branch_session_id}", response_class=HTMLResponse)
async def branches_compare_ui(
    request: Request,
    branch_session_id: str,
    current_user: str = Depends(get_current_user),
):
    """Branch comparison UI page."""
    try:
        branch_manager = get_branch_manager()

        # Get branch info
        branch_info = await branch_manager.get_branch_info(branch_session_id)
        if not branch_info:
            raise HTTPException(status_code=404, detail="Branch not found")

        # Get parent session info
        parent_session_id = branch_info["parent_session_id"]
        parent_branches = await branch_manager.list_branches(parent_session_id)

        # Get merge history
        merge_history = await branch_manager.get_merge_history(branch_session_id)

        return templates.TemplateResponse(
            "branches/compare.html",
            {
                "request": request,
                "branch_info": branch_info,
                "parent_session_id": parent_session_id,
                "parent_branches": parent_branches,
                "merge_history": merge_history,
                "current_user": current_user,
            },
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in branches compare UI: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to load branches compare: {str(e)}"
        )


# Helper functions for enhanced UI
def _format_relative_time(timestamp: str) -> str:
    """Format timestamp as relative time for display."""
    try:
        dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        now = datetime.now(dt.tzinfo)
        delta = now - dt

        if delta.days > 0:
            return f"{delta.days} days ago"
        elif delta.seconds > 3600:
            hours = delta.seconds // 3600
            return f"{hours} hours ago"
        elif delta.seconds > 60:
            minutes = delta.seconds // 60
            return f"{minutes} minutes ago"
        else:
            return "just now"
    except:
        return timestamp


def _get_status_class(status: str) -> str:
    """Get CSS class for status display."""
    status_classes = {
        "active": "status-active",
        "merged": "status-merged",
        "closed": "status-closed",
        "archived": "status-archived",
    }
    return status_classes.get(status, "status-unknown")


def _build_branch_tree(branches: List[Dict]) -> List[Dict]:
    """Build tree structure for branch visualization."""
    tree = []

    # Group branches by parent session
    parent_groups = {}
    for branch in branches:
        parent_id = branch["parent_session_id"]
        if parent_id not in parent_groups:
            parent_groups[parent_id] = []
        parent_groups[parent_id].append(branch)

    # Build tree structure
    for parent_id, child_branches in parent_groups.items():
        parent_node = {
            "id": parent_id,
            "type": "parent",
            "branches": child_branches,
            "children": [],
        }

        # Add nested branches if they have their own branches
        for child_branch in child_branches:
            # In a real implementation, we'd check if this branch has its own children
            parent_node["children"].append(
                {
                    "id": child_branch["id"],
                    "type": "branch",
                    "branch_info": child_branch,
                    "children": [],
                }
            )

        tree.append(parent_node)

    return tree


@router.get("/create", response_class=HTMLResponse)
async def branches_create_ui(
    request: Request,
    session_id: str = None,
    turn_id: str = None,
    current_user: str = Depends(get_current_user),
):
    """Branches create UI page."""
    try:
        return templates.TemplateResponse(
            "branches/create.html",
            {
                "request": request,
                "session_id": session_id,
                "turn_id": turn_id,
                "current_user": current_user,
            },
        )

    except Exception as e:
        logger.error(f"Error in branches create UI: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to load branches create: {str(e)}"
        )


@router.post("/create")
async def branches_create_post(
    request: Request,
    current_user: str = Depends(get_current_user),
):
    """Create a new branch via UI."""
    try:
        form_data = await request.form()
        session_id = form_data.get("session_id")
        turn_id = form_data.get("turn_id")
        branch_name = form_data.get("branch_name")

        if not session_id:
            raise HTTPException(status_code=400, detail="Session ID is required")

        branch_manager = get_branch_manager()
        new_branch_id = await branch_manager.fork_session(
            session_id=session_id,
            turn_id=turn_id,
            branch_name=branch_name,
        )

        return RedirectResponse(
            f"/ui/branches/?session_id={new_branch_id}", status_code=303
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating branch: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to create branch: {str(e)}"
        )


@router.get("/merge", response_class=HTMLResponse)
async def branches_merge_ui(
    request: Request,
    session_id: str,
    branch_id: str,
    current_user: str = Depends(get_current_user),
):
    """Branch merge UI page with conflict resolution interface."""
    try:
        branch_manager = get_branch_manager()

        # Get branch information
        branch_info = await branch_manager.get_branch_info(branch_id)
        if not branch_info:
            raise HTTPException(status_code=404, detail=f"Branch {branch_id} not found")

        # Get available branches for merge source selection
        available_branches = await branch_manager.list_branches(session_id)

        # Filter out the current branch and non-active branches
        available_branches = [
            branch
            for branch in available_branches
            if branch["id"] != branch_id and branch["status"] == "active"
        ]

        # Get merge history for context
        merge_history = await branch_manager.get_merge_history(session_id)

        return templates.TemplateResponse(
            "branches/merge.html",
            {
                "request": request,
                "session_id": session_id,
                "branch_id": branch_id,
                "branch_info": branch_info,
                "available_branches": available_branches,
                "merge_history": merge_history,
                "current_user": current_user,
                "merge_strategies": ["append", "interleave", "replace"],
                "conflict_resolutions": ["manual", "auto", "source"],
            },
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in branches merge UI: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to load branches merge: {str(e)}"
        )


@router.post("/merge")
async def branches_merge_post(
    request: Request,
    current_user: str = Depends(get_current_user),
):
    """Perform branch merge via UI."""
    try:
        form_data = await request.form()
        session_id = form_data.get("session_id")
        source_session_id = form_data.get("source_session_id")
        merge_strategy = form_data.get("merge_strategy", "append")
        conflict_resolution = form_data.get("conflict_resolution", "manual")

        if not session_id or not source_session_id:
            raise HTTPException(
                status_code=400, detail="Session ID and source session ID are required"
            )

        branch_manager = get_branch_manager()

        # Perform the merge
        merge_result = await branch_manager.merge_branches(
            source_session_id=source_session_id,
            target_session_id=session_id,
            merge_strategy=merge_strategy,
            conflict_resolution=conflict_resolution,
        )

        # Redirect to session view with merge success message
        from urllib.parse import urlencode

        params = {
            "merge_success": "true",
            "merged_branch": merge_result["source_session"],
            "merge_strategy": merge_result["merge_strategy"],
            "merged_turns": merge_result["merged_turns"],
        }
        query_string = urlencode(params)
        return RedirectResponse(
            f"/sessions/{session_id}?{query_string}", status_code=303
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error merging branch: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to merge branch: {str(e)}")


@router.get("/merge/preview")
async def branches_merge_preview(
    session_id: str,
    source_session_id: str,
    merge_strategy: str = "append",
    current_user: str = Depends(get_current_user),
):
    """Preview merge operation without actually performing it."""
    try:
        branch_manager = get_branch_manager()

        # Get branch information
        source_branch = await branch_manager.get_branch_info(source_session_id)
        target_session = await branch_manager.get_session(session_id)

        if not source_branch:
            raise HTTPException(
                status_code=404, detail=f"Source branch not found: {source_session_id}"
            )
        if not target_session:
            raise HTTPException(
                status_code=404, detail=f"Target session not found: {session_id}"
            )

        # Get turns from both sessions
        source_turns = await branch_manager.session_manager.get_session_turns(
            source_session_id
        )
        target_turns = await branch_manager.session_manager.get_session_turns(
            session_id
        )

        # Simulate merge to get preview data
        preview_data = {
            "source_branch": source_branch["name"],
            "target_session": target_session["name"],
            "merge_strategy": merge_strategy,
            "source_turns_count": len(source_turns),
            "target_turns_count": len(target_turns),
            "estimated_merged_turns": len(source_turns) + len(target_turns)
            if merge_strategy == "append"
            else max(len(source_turns), len(target_turns)),
            "potential_conflicts": _detect_potential_conflicts(
                source_turns, target_turns
            ),
            "memory_files_to_merge": _get_memory_files_to_merge(
                source_session_id, session_id
            ),
        }

        return preview_data

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in merge preview: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to generate merge preview: {str(e)}"
        )


def _detect_potential_conflicts(
    source_turns: List[Dict], target_turns: List[Dict]
) -> List[Dict]:
    """Detect potential conflicts between source and target turns."""
    conflicts = []

    # Check for file modifications in both branches
    source_files = set()
    target_files = set()

    for turn in source_turns:
        for tool_call in turn.get("tool_calls", []):
            if tool_call.get("name") in ["write", "edit"]:
                args = tool_call.get("args", {})
                file_path = args.get("path")
                if file_path:
                    source_files.add(file_path)

    for turn in target_turns:
        for tool_call in turn.get("tool_calls", []):
            if tool_call.get("name") in ["write", "edit"]:
                args = tool_call.get("args", {})
                file_path = args.get("path")
                if file_path:
                    target_files.add(file_path)

    # Find conflicting files
    conflicting_files = source_files.intersection(target_files)
    for file_path in conflicting_files:
        conflicts.append(
            {
                "type": "file_modification",
                "file_path": file_path,
                "message": f"File '{file_path}' modified in both branches",
            }
        )

    return conflicts


def _get_memory_files_to_merge(
    source_session_id: str, target_session_id: str
) -> List[str]:
    """Get list of memory files that would be merged."""
    memory_files = [
        "PROJECT.md",
        "LEARNED.md",
        "PREFERENCES.md",
        "FACTS.md",
        "DECISIONS.md",
    ]
    return memory_files


@router.get("/merge", response_class=HTMLResponse)
async def branches_merge_ui(
    request: Request,
    source_session_id: str = None,
    target_session_id: str = None,
    current_user: str = Depends(get_current_user),
):
    """Branches merge UI page."""
    try:
        branch_manager = get_branch_manager()

        # Get branch info for source and target
        source_info = None
        target_info = None

        if source_session_id:
            source_info = await branch_manager.get_branch_info(source_session_id)

        if target_session_id:
            target_info = await branch_manager.get_branch_info(target_session_id)

        # Get merge history for target
        merge_history = []
        if target_session_id:
            merge_history = await branch_manager.get_merge_history(target_session_id)

        return templates.TemplateResponse(
            "branches/merge.html",
            {
                "request": request,
                "source_session_id": source_session_id,
                "target_session_id": target_session_id,
                "source_info": source_info,
                "target_info": target_info,
                "merge_history": merge_history,
                "current_user": current_user,
            },
        )

    except Exception as e:
        logger.error(f"Error in branches merge UI: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to load branches merge: {str(e)}"
        )


@router.post("/merge")
async def branches_merge_post(
    request: Request,
    current_user: str = Depends(get_current_user),
):
    """Merge branches via UI."""
    try:
        form_data = await request.form()
        source_session_id = form_data.get("source_session_id")
        target_session_id = form_data.get("target_session_id")
        merge_strategy = form_data.get("merge_strategy", "append")
        conflict_resolution = form_data.get("conflict_resolution", "manual")

        if not source_session_id or not target_session_id:
            raise HTTPException(
                status_code=400, detail="Source and target session IDs are required"
            )

        branch_manager = get_branch_manager()
        merge_result = await branch_manager.merge_branches(
            source_session_id=source_session_id,
            target_session_id=target_session_id,
            merge_strategy=merge_strategy,
            conflict_resolution=conflict_resolution,
        )

        # Redirect to target session with success message
        return RedirectResponse(
            f"/ui/branches/?session_id={target_session_id}", status_code=303
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error merging branches: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to merge branches: {str(e)}"
        )


@router.get("/delete/{branch_session_id}", response_class=HTMLResponse)
async def branches_delete_ui(
    request: Request,
    branch_session_id: str,
    current_user: str = Depends(get_current_user),
):
    """Branches delete confirmation UI page."""
    try:
        branch_manager = get_branch_manager()
        branch_info = await branch_manager.get_branch_info(branch_session_id)

        if not branch_info:
            raise HTTPException(status_code=404, detail="Branch not found")

        return templates.TemplateResponse(
            "branches/delete.html",
            {
                "request": request,
                "branch_info": branch_info,
                "current_user": current_user,
            },
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in branches delete UI: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to load branches delete: {str(e)}"
        )


@router.post("/delete/{branch_session_id}")
async def branches_delete_post(
    branch_session_id: str,
    current_user: str = Depends(get_current_user),
):
    """Delete a branch via UI."""
    try:
        branch_manager = get_branch_manager()
        success = await branch_manager.delete_branch(branch_session_id)

        if not success:
            raise HTTPException(status_code=404, detail="Branch not found")

        # Redirect to parent session
        # In a real implementation, we'd get the parent session ID from branch_info
        return RedirectResponse("/ui/branches/", status_code=303)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting branch: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to delete branch: {str(e)}"
        )


@router.get("/info/{branch_session_id}", response_class=HTMLResponse)
async def branches_info_ui(
    request: Request,
    branch_session_id: str,
    current_user: str = Depends(get_current_user),
):
    """Branches info UI page."""
    try:
        branch_manager = get_branch_manager()
        branch_info = await branch_manager.get_branch_info(branch_session_id)

        if not branch_info:
            raise HTTPException(status_code=404, detail="Branch not found")

        # Get merge history
        merge_history = await branch_manager.get_merge_history(branch_session_id)

        return templates.TemplateResponse(
            "branches/info.html",
            {
                "request": request,
                "branch_info": branch_info,
                "merge_history": merge_history,
                "current_user": current_user,
            },
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in branches info UI: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to load branches info: {str(e)}"
        )


# Helper function to initialize the UI router
def setup_branch_ui():
    """Setup branch UI routes."""
    return router
