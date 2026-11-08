"""Next.js Web UI: tool-call visualization (B-14) - collapsible JSON tree.

Provides visualization of tool calls in a user-friendly interface.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.core.observability.spans import get_span_buffer
from app.core.session import SessionManager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ui/api", tags=["nextjs-web-ui"])


class ToolCallModel(BaseModel):
    """Tool call model."""

    id: str
    name: str
    arguments: Dict[str, Any]
    start_time: str
    end_time: Optional[str] = None
    duration_ms: Optional[float] = None
    status: str = "running"
    result: Optional[Any] = None
    error: Optional[str] = None
    children: List["ToolCallModel"] = []


class VisualizationNode:
    """Visualization node for tool calls."""

    def __init__(self, tool_call: ToolCallModel):
        self.id = tool_call.id
        self.name = tool_call.name
        self.arguments = tool_call.arguments
        self.start_time = tool_call.start_time
        self.end_time = tool_call.end_time
        self.duration_ms = tool_call.duration_ms
        self.status = tool_call.status
        self.result = tool_call.result
        self.error = tool_call.error
        self.children = [VisualizationNode(child) for child in tool_call.children]

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "id": self.id,
            "name": self.name,
            "arguments": self.arguments,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "duration_ms": self.duration_ms,
            "status": self.status,
            "result": self.result,
            "error": self.error,
            "children": [child.to_dict() for child in self.children],
        }


class ToolCallVisualizer:
    """Visualizer for tool calls."""

    def __init__(self):
        self.session_manager = SessionManager()

    async def get_session_tool_calls(self, session_id: str) -> List[ToolCallModel]:
        """Get tool calls for a session."""
        try:
            # Get turns from session
            turns = await self.session_manager.get_session_turns(session_id)

            tool_calls = []
            for turn in turns:
                for tool_call in turn.get("tool_calls", []):
                    tool_call_model = ToolCallModel(
                        id=tool_call.get("id", str(uuid.uuid4())),
                        name=tool_call.get("name", "unknown"),
                        arguments=tool_call.get("arguments", {}),
                        start_time=tool_call.get(
                            "start_time", datetime.utcnow().isoformat()
                        ),
                        end_time=tool_call.get("end_time"),
                        duration_ms=tool_call.get("duration_ms"),
                        status=tool_call.get("status", "completed"),
                        result=tool_call.get("result"),
                        error=tool_call.get("error"),
                    )
                    tool_calls.append(tool_call_model)

            return tool_calls

        except Exception as e:
            logger.error(f"Failed to get session tool calls: {e}")
            raise HTTPException(
                status_code=500, detail=f"Failed to get session tool calls: {str(e)}"
            )

    async def get_tool_call_tree(self, session_id: str) -> List[Dict[str, Any]]:
        """Get tool calls as a tree structure."""
        try:
            tool_calls = await self.get_session_tool_calls(session_id)

            # Build tree structure
            root_nodes = []
            call_map = {}

            # First pass: create all nodes
            for tool_call in tool_calls:
                node = VisualizationNode(tool_call)
                call_map[node.id] = node

            # Second pass: build tree hierarchy
            for tool_call in tool_calls:
                node = call_map[tool_call.id]

                # Find parent and add to children
                parent_id = tool_call.get("parent_id")
                if parent_id and parent_id in call_map:
                    call_map[parent_id].children.append(node)
                else:
                    root_nodes.append(node)

            return [node.to_dict() for node in root_nodes]

        except Exception as e:
            logger.error(f"Failed to get tool call tree: {e}")
            raise HTTPException(
                status_code=500, detail=f"Failed to get tool call tree: {str(e)}"
            )

    async def get_tool_call_details(
        self, session_id: str, tool_call_id: str
    ) -> Dict[str, Any]:
        """Get detailed information about a specific tool call."""
        try:
            tool_calls = await self.get_session_tool_calls(session_id)

            for tool_call in tool_calls:
                if tool_call.id == tool_call_id:
                    return VisualizationNode(tool_call).to_dict()

            raise HTTPException(status_code=404, detail="Tool call not found")

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Failed to get tool call details: {e}")
            raise HTTPException(
                status_code=500, detail=f"Failed to get tool call details: {str(e)}"
            )

    async def get_tool_call_statistics(self, session_id: str) -> Dict[str, Any]:
        """Get statistics about tool calls in a session."""
        try:
            tool_calls = await self.get_session_tool_calls(session_id)

            # Calculate statistics
            total_calls = len(tool_calls)
            successful_calls = len(
                [tc for tc in tool_calls if tc.status == "completed"]
            )
            failed_calls = len([tc for tc in tool_calls if tc.status == "failed"])

            # Calculate average duration
            durations = [
                tc.duration_ms for tc in tool_calls if tc.duration_ms is not None
            ]
            avg_duration = sum(durations) / len(durations) if durations else 0

            # Group by tool name
            tool_counts = {}
            for tool_call in tool_calls:
                tool_name = tool_call.name
                tool_counts[tool_name] = tool_counts.get(tool_name, 0) + 1

            # Group by status
            status_counts = {}
            for tool_call in tool_calls:
                status = tool_call.status
                status_counts[status] = status_counts.get(status, 0) + 1

            return {
                "total_calls": total_calls,
                "successful_calls": successful_calls,
                "failed_calls": failed_calls,
                "success_rate": successful_calls / total_calls
                if total_calls > 0
                else 0,
                "average_duration_ms": avg_duration,
                "tool_counts": tool_counts,
                "status_counts": status_counts,
            }

        except Exception as e:
            logger.error(f"Failed to get tool call statistics: {e}")
            raise HTTPException(
                status_code=500, detail=f"Failed to get tool call statistics: {str(e)}"
            )

    async def search_tool_calls(
        self, session_id: str, query: str
    ) -> List[Dict[str, Any]]:
        """Search tool calls by name or arguments."""
        try:
            tool_calls = await self.get_session_tool_calls(session_id)

            results = []
            query_lower = query.lower()

            for tool_call in tool_calls:
                # Search by name
                if query_lower in tool_call.name.lower():
                    results.append(VisualizationNode(tool_call).to_dict())
                    continue

                # Search by arguments
                for key, value in tool_call.arguments.items():
                    if (
                        query_lower in str(key).lower()
                        or query_lower in str(value).lower()
                    ):
                        results.append(VisualizationNode(tool_call).to_dict())
                        break

            return results

        except Exception as e:
            logger.error(f"Failed to search tool calls: {e}")
            raise HTTPException(
                status_code=500, detail=f"Failed to search tool calls: {str(e)}"
            )

    def format_tool_call_for_display(self, tool_call: Dict[str, Any]) -> Dict[str, Any]:
        """Format tool call for display with human-readable information."""
        try:
            # Format arguments for display
            formatted_args = {}
            for key, value in tool_call.get("arguments", {}).items():
                if isinstance(value, str) and len(value) > 100:
                    # Truncate long strings
                    formatted_args[key] = value[:100] + "..."
                else:
                    formatted_args[key] = value

            # Format result for display
            formatted_result = None
            result = tool_call.get("result")
            if result:
                if isinstance(result, str) and len(result) > 200:
                    formatted_result = result[:200] + "..."
                else:
                    formatted_result = result

            # Format duration
            duration_ms = tool_call.get("duration_ms")
            duration_str = f"{duration_ms:.2f}ms" if duration_ms else "N/A"

            return {
                "id": tool_call.get("id"),
                "name": tool_call.get("name"),
                "arguments": formatted_args,
                "start_time": tool_call.get("start_time"),
                "end_time": tool_call.get("end_time"),
                "duration": duration_str,
                "status": tool_call.get("status"),
                "result": formatted_result,
                "error": tool_call.get("error"),
            }

        except Exception as e:
            logger.error(f"Failed to format tool call for display: {e}")
            return tool_call


# Global instance
_tool_call_visualizer = None


def get_tool_call_visualizer() -> ToolCallVisualizer:
    """Get the global tool call visualizer instance."""
    global _tool_call_visualizer
    if _tool_call_visualizer is None:
        _tool_call_visualizer = ToolCallVisualizer()
    return _tool_call_visualizer


@router.get("/sessions/{session_id}/tool-calls")
async def get_session_tool_calls(session_id: str):
    """Get tool calls for a session."""
    visualizer = get_tool_call_visualizer()
    return await visualizer.get_session_tool_calls(session_id)


@router.get("/sessions/{session_id}/tool-calls/tree")
async def get_tool_call_tree(session_id: str):
    """Get tool calls as a tree structure."""
    visualizer = get_tool_call_visualizer()
    return await visualizer.get_tool_call_tree(session_id)


@router.get("/sessions/{session_id}/tool-calls/{tool_call_id}")
async def get_tool_call_details(session_id: str, tool_call_id: str):
    """Get detailed information about a specific tool call."""
    visualizer = get_tool_call_visualizer()
    return await visualizer.get_tool_call_details(session_id, tool_call_id)


@router.get("/sessions/{session_id}/tool-calls/statistics")
async def get_tool_call_statistics(session_id: str):
    """Get statistics about tool calls in a session."""
    visualizer = get_tool_call_visualizer()
    return await visualizer.get_tool_call_statistics(session_id)


@router.get("/sessions/{session_id}/tool-calls/search")
async def search_tool_calls(session_id: str, q: str):
    """Search tool calls by name or arguments."""
    visualizer = get_tool_call_visualizer()
    return await visualizer.search_tool_calls(session_id, q)


@router.get("/sessions/{session_id}/tool-calls/{tool_call_id}/formatted")
async def get_formatted_tool_call(session_id: str, tool_call_id: str):
    """Get formatted tool call for display."""
    visualizer = get_tool_call_visualizer()

    # Get tool call details
    tool_call = await visualizer.get_tool_call_details(session_id, tool_call_id)

    # Format for display
    return visualizer.format_tool_call_for_display(tool_call)
