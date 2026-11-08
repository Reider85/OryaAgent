"""Hooks-integrated tool execution system (B-04).

This module provides a wrapper that executes tools through the hooks framework,
ensuring all tool calls go through pre and post hooks as specified in B-04.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from langchain_core.tools import BaseTool
from langgraph.prebuilt import ToolNode

from app.core.hooks import get_hook_executor, HookResult

logger = logging.getLogger(__name__)


class HooksIntegratedToolNode:
    """ToolNode that executes tools through the hooks framework.

    This wrapper ensures all tool calls go through pre and post hooks,
    providing the hooks execution functionality required by B-04.
    """

    def __init__(self, tools: list[BaseTool]):
        """Initialize the hooks-integrated tool node.

        Args:
            tools: List of LangChain tools to execute
        """
        self.tool_node = ToolNode(tools)
        self.hook_executor = get_hook_executor()

    async def ainvoke(
        self,
        state: dict[str, Any],
        config: dict[str, Any] | None = None,
    ) -> list[Any]:
        """Execute tools through the hooks framework.

        Args:
            state: LangGraph state containing messages
            config: Optional configuration

        Returns:
            List of tool results (ToolMessage instances)
        """
        messages = state.get("messages", [])
        if not messages:
            return []

        # Get the last AI message which contains tool calls
        last_message = messages[-1]
        tool_calls = getattr(last_message, "tool_calls", None)
        if not tool_calls:
            return []

        results = []

        # Execute each tool call through hooks
        for tool_call in tool_calls:
            tool_name = tool_call.get("name", "")
            tool_args = tool_call.get("args", {})
            tool_id = tool_call.get("id", "")

            try:
                # Execute pre-hooks
                hook_result = await self.hook_executor.execute_pre_hooks(
                    session_id=state.get("session_id", ""),
                    tool_name=tool_name,
                    tool_args=tool_args,
                    tool_kwargs={},
                    turn_id=state.get("turn_id"),
                )

                # If a hook requested to skip the tool, create a skip result
                if hook_result.should_skip_tool:
                    results.append(
                        self._create_skip_result(tool_name, tool_id, hook_result)
                    )
                    continue

                # If pre-hook failed, create an error result
                if not hook_result.success:
                    results.append(
                        self._create_error_result(
                            tool_name, tool_id, hook_result.message
                        )
                    )
                    continue

                # Execute the actual tool
                tool_result = await self._execute_tool(
                    tool_name, tool_args, tool_id, state
                )

                # Execute post-hooks
                post_hook_result = await self.hook_executor.execute_post_hooks(
                    session_id=state.get("session_id", ""),
                    tool_name=tool_name,
                    tool_args=tool_args,
                    tool_kwargs={},
                    tool_result=tool_result,
                    turn_id=state.get("turn_id"),
                )

                # Combine the tool result with hook modifications
                final_result = self._combine_results(tool_result, post_hook_result)
                results.append(final_result)

            except Exception as e:
                logger.error(f"Tool execution failed for {tool_name}: {e}")
                results.append(self._create_error_result(tool_name, tool_id, str(e)))

        return results

    async def _execute_tool(
        self,
        tool_name: str,
        tool_args: dict[str, Any],
        tool_id: str,
        state: dict[str, Any],
    ) -> HookResult:
        """Execute a single tool.

        Args:
            tool_name: Name of the tool to execute
            tool_args: Tool arguments
            tool_id: Tool call ID
            state: Current state

        Returns:
            HookResult containing the tool execution result
        """
        try:
            # Create a temporary state for this tool call
            temp_state = state.copy()
            temp_state["messages"] = [
                *state.get("messages", []),
                # Add a temporary message with the tool call
                type(
                    "ToolCallMessage",
                    (),
                    {
                        "tool_calls": [
                            {
                                "id": tool_id,
                                "name": tool_name,
                                "args": tool_args,
                            }
                        ]
                    },
                )(),
            ]

            # Execute the tool through the original ToolNode
            raw_results = await self.tool_node.ainvoke(temp_state)

            # Extract the result for this specific tool call
            tool_result = None
            for result in raw_results:
                if hasattr(result, "tool_call_id") and result.tool_call_id == tool_id:
                    tool_result = result
                    break

            if tool_result is None:
                raise Exception(f"Tool result not found for {tool_name}")

            return HookResult(
                success=True,
                data=tool_result,
                message=f"Tool {tool_name} executed successfully",
            )

        except Exception as e:
            return HookResult(success=False, message=f"Tool execution failed: {str(e)}")

    def _create_skip_result(
        self,
        tool_name: str,
        tool_id: str,
        hook_result: HookResult,
    ) -> Any:
        """Create a result for a skipped tool.

        Args:
            tool_name: Name of the skipped tool
            tool_id: Tool call ID
            hook_result: Hook result that requested the skip

        Returns:
            ToolMessage indicating the tool was skipped
        """
        from langchain_core.messages import ToolMessage

        return ToolMessage(
            content=hook_result.message or f"Tool {tool_name} skipped by pre-hook",
            tool_call_id=tool_id,
            name=tool_name,
            status="skipped",
        )

    def _create_error_result(
        self,
        tool_name: str,
        tool_id: str,
        error_message: str,
    ) -> Any:
        """Create an error result.

        Args:
            tool_name: Name of the failed tool
            tool_id: Tool call ID
            error_message: Error message

        Returns:
            ToolMessage indicating the tool failed
        """
        from langchain_core.messages import ToolMessage

        return ToolMessage(
            content=error_message,
            tool_call_id=tool_id,
            name=tool_name,
            status="error",
        )

    def _combine_results(
        self,
        tool_result: HookResult,
        post_hook_result: HookResult,
    ) -> Any:
        """Combine tool result with post-hook modifications.

        Args:
            tool_result: Original tool execution result
            post_hook_result: Result from post-hook execution

        Returns:
            Combined result
        """
        # If post-hook modified the data, use that
        if post_hook_result.data is not None:
            return post_hook_result.data

        # Otherwise return the original tool result
        return tool_result.data


def create_hooks_integrated_tool_node(tools: list[BaseTool]) -> HooksIntegratedToolNode:
    """Create a hooks-integrated tool node.

    Args:
        tools: List of LangChain tools

    Returns:
        HooksIntegratedToolNode instance
    """
    return HooksIntegratedToolNode(tools)
