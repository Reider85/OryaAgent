"""Tool-registry exports (B-29)."""

from __future__ import annotations

from app.core.tools.capability_registry import (
    CapabilityRegistry,
    get_capability_registry,
    reset_capability_registry,
)
from app.core.tools.context import TurnContext
from app.core.tools.triggers import (
    LSP_LANGUAGES,
    create_triggers,
    get_tool_capabilities,
    get_trigger_for_tool,
    group_tools_by_capability,
)
from app.tools import bash, edit, glob, grep, oriahs_health, read, write

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


def get_tools(session_id: str | None = None) -> list:
    """Get all available tools in the canonical M-12 order.

    Returns the registry in the architectural-invariant order
    ``[read, write, edit, bash, grep, glob, oriahs_health]`` (AGENTS.md #3 —
    the graph, the system-prompt builder and the UI all consume this list;
    P-00 appends the health probe without moving the canonical prefix).

    ``session_id`` is reserved for per-session filtering (M-13+/BETA
    ``CapabilityRegistry``) and intentionally unused here: the agent loop
    calls ``get_tools(thread_id)`` (``app/core/agent.py``), so the parameter
    must exist even while the list stays global.
    """
    return [read, write, edit, bash, grep, glob, oriahs_health]
