"""Tool-registry exports (B-29)."""

from __future__ import annotations

from app.core.tools.capability_registry import (
    get_capability_registry,
    reset_capability_registry,
    CapabilityRegistry,
)
from app.core.tools.context import TurnContext
from app.core.tools.triggers import (
    create_triggers,
    get_trigger_for_tool,
    get_tool_capabilities,
    group_tools_by_capability,
    LSP_LANGUAGES,
)
from app.tools import bash, edit, glob, grep, read, write

__all__ = [
    "get_capability_registry",
    "reset_capability_registry", 
    "CapabilityRegistry",
    "TurnContext",
    "create_triggers",
    "get_trigger_for_tool",
    "get_tool_capabilities",
    "group_tools_by_capability",
    "LSP_LANGUAGES",
    "get_tools",
]


def get_tools():
    """Get all available tools in the order they should be used.
    
    Returns:
        List of all available tools in the canonical order.
    """
    return [read, write, edit, bash, grep, glob]