"""CapabilityRegistry for dynamic tool filtering per turn (B-29)."""

from __future__ import annotations

import logging
from typing import Any

from langchain_core.tools import BaseTool

from app.core.observability.metrics import get_metric_collector
from app.core.observability.spans import emit_span
from app.core.tools.context import TurnContext
from app.core.tools.triggers import create_triggers

logger = logging.getLogger(__name__)


class CapabilityRegistry:
    """Dynamic tool filtering registry based on turn context.

    The CapabilityRegistry filters tools based on contextual triggers to reduce
    the number of tools visible to the LLM (from 15+ to 8-15 per turn),
    improving decision quality and reducing noise.
    """

    def __init__(self):
        """Initialize the CapabilityRegistry."""
        self.triggers = create_triggers()
        self.metrics = get_metric_collector()

        # Track filtering statistics
        self._active_count = 0
        self._filtered_out_count = 0
        self._total_filters = 0

    def filter_tools(
        self, all_tools: list[BaseTool], context: TurnContext
    ) -> list[BaseTool]:
        """Filter tools based on context and triggers.

        Args:
            all_tools: List of all available tools.
            context: Current turn context.

        Returns:
            Filtered list of tools relevant to the current context.
        """
        emit_span(
            span_type="capability.filter",
            name="capability.filter",
            attributes={"active_count": len(all_tools)},
        )

        filtered_tools = []

        for tool in all_tools:
            if self.is_relevant(tool, context):
                filtered_tools.append(tool)
            else:
                self._filtered_out_count += 1

        self._active_count = len(filtered_tools)
        self._total_filters += 1

        # Log filtering results
        logger.debug(
            "CapabilityRegistry filtered: %d -> %d tools (%d filtered out)",
            len(all_tools),
            len(filtered_tools),
            len(all_tools) - len(filtered_tools),
        )

        # Emit metrics
        self.metrics.gauge_set(
            "orya_capability_filter_active_count", self._active_count
        )
        self.metrics.counter_inc(
            "orya_capability_filter_filtered_out_total",
            value=len(all_tools) - len(filtered_tools),
        )

        # Enforce maximum active tools limit
        if len(filtered_tools) > 15:
            logger.warning(
                "Filtered tools count (%d) exceeds maximum (15), truncating",
                len(filtered_tools),
            )
            # Keep the most relevant tools (basic + context-specific)
            basic_tools = [t for t in filtered_tools if self._is_basic_tool(t)]
            context_tools = [t for t in filtered_tools if not self._is_basic_tool(t)]

            # Prioritize basic tools (always visible) and limit context tools
            filtered_tools = basic_tools + context_tools[:10]
            self._active_count = len(filtered_tools)

        return filtered_tools

    def is_relevant(self, tool: BaseTool, context: TurnContext) -> bool:
        """Check if tool is relevant for current context.

        Args:
            tool: Tool to check.
            context: Current turn context.

        Returns:
            True if tool should be available, False otherwise.
        """
        tool_name = getattr(tool, "name", "")
        if not tool_name:
            # Tool without name - assume it's always relevant
            return True

        # Get trigger function for this tool
        trigger_func = self.triggers.get(tool_name)
        if trigger_func is None:
            # No trigger defined - tool is always visible
            return True

        try:
            return trigger_func(context)
        except Exception as e:
            logger.warning("Error evaluating trigger for tool %s: %s", tool_name, e)
            # Fail-safe: if trigger fails, assume tool is not relevant
            return False

    def get_active_count(self) -> int:
        """Get number of active tools from last filter operation."""
        return self._active_count

    def get_filtered_out_count(self) -> int:
        """Get number of filtered out tools from last filter operation."""
        return self._filtered_out_count

    def get_total_filters(self) -> int:
        """Get total number of filter operations."""
        return self._total_filters

    def get_statistics(self) -> dict[str, Any]:
        """Get filtering statistics.

        Returns:
            Dictionary with filtering statistics.
        """
        return {
            "total_filters": self._total_filters,
            "active_count": self._active_count,
            "filtered_out_count": self._filtered_out_count,
            "active_tools_percentage": (
                self._active_count
                / max(1, self._active_count + self._filtered_out_count)
            )
            * 100,
        }

    def _is_basic_tool(self, tool: BaseTool) -> bool:
        """Check if tool is a basic tool (always visible).

        Args:
            tool: Tool to check.

        Returns:
            True if tool is basic.
        """
        tool_name = getattr(tool, "name", "")
        basic_tools = {"read", "write", "edit", "bash", "grep", "glob", "ukb.lookup"}
        return tool_name in basic_tools


# Global instance for easy access
_capability_registry_instance: CapabilityRegistry | None = None


def get_capability_registry() -> CapabilityRegistry:
    """Get global CapabilityRegistry instance.

    Returns:
        Global CapabilityRegistry instance.
    """
    global _capability_registry_instance
    if _capability_registry_instance is None:
        _capability_registry_instance = CapabilityRegistry()
    return _capability_registry_instance


def reset_capability_registry() -> None:
    """Reset global CapabilityRegistry instance (for testing)."""
    global _capability_registry_instance
    _capability_registry_instance = None
