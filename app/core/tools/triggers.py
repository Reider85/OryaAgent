"""Triggers for capability-based tool filtering (B-29)."""

from __future__ import annotations

from typing import Callable

from app.core.tools.context import TurnContext


# Supported LSP languages
LSP_LANGUAGES = {
    "python", "typescript", "javascript", "rust", "go", "java", "lua", 
    "cpp", "c", "csharp", "kotlin", "scala", "swift", "php", "ruby"
}


def create_triggers() -> dict[str, Callable[[TurnContext], bool]]:
    """Create trigger functions for tool relevance.
    
    Returns:
        Dictionary mapping tool names to trigger functions that determine
        if the tool should be available based on current context.
    """
    return {
        # LSP tools - only visible when language is supported
        "lsp.hover": lambda ctx: ctx.language in LSP_LANGUAGES,
        "lsp.definition": lambda ctx: ctx.language in LSP_LANGUAGES and ctx.has_symbol_at_cursor,
        "lsp.references": lambda ctx: ctx.language in LSP_LANGUAGES,
        "lsp.symbol_search": lambda ctx: ctx.language in LSP_LANGUAGES,
        "lsp.rename": lambda ctx: ctx.intent == "rename" and ctx.language in LSP_LANGUAGES,
        "lsp.diagnostics": lambda ctx: ctx.language in LSP_LANGUAGES,
        "lsp.code_action": lambda ctx: ctx.language in LSP_LANGUAGES,
        
        # Memory tools - visible when user is asking about past work
        "memory.search": lambda ctx: ctx.referential_marker or ctx.asking_about_past,
        
        # Search tools - visible for cross-project search or when no specific language
        "oriahs_search": lambda ctx: ctx.cross_project_search or ctx.language is None,
        "oriahs_index": lambda ctx: ctx.cross_project_search or ctx.language is None,
        
        # UKB tool - always visible (default retrieval)
        "ukb.lookup": lambda ctx: True,
        
        # Basic tools - always visible
        "read": lambda ctx: True,
        "write": lambda ctx: True,
        "edit": lambda ctx: True,
        "bash": lambda ctx: True,
        "grep": lambda ctx: True,
        "glob": lambda ctx: True,
        
        # Retrieval orchestration - visible when appropriate
        "retrieval_orchestrate": lambda ctx: ctx.referential_marker or ctx.asking_about_past,
    }


def get_trigger_for_tool(tool_name: str) -> Callable[[TurnContext], bool] | None:
    """Get trigger function for a specific tool.
    
    Args:
        tool_name: Name of the tool.
        
    Returns:
        Trigger function or None if no trigger exists.
    """
    triggers = create_triggers()
    return triggers.get(tool_name)


def get_tool_capabilities() -> dict[str, list[str]]:
    """Get mapping of tools to their capabilities.
    
    Returns:
        Dictionary mapping tool names to their capabilities.
    """
    return {
        "read": ["file", "basic"],
        "write": ["file", "basic"],
        "edit": ["file", "basic"],
        "bash": ["system", "basic"],
        "grep": ["search", "basic"],
        "glob": ["search", "basic"],
        "lsp.hover": ["code", "language-specific"],
        "lsp.definition": ["code", "language-specific"],
        "lsp.references": ["code", "language-specific"],
        "lsp.symbol_search": ["code", "language-specific"],
        "lsp.rename": ["code", "language-specific"],
        "lsp.diagnostics": ["code", "language-specific"],
        "lsp.code_action": ["code", "language-specific"],
        "oriahs_search": ["search", "semantic"],
        "oriahs_index": ["search", "semantic"],
        "memory.search": ["memory", "past"],
        "ukb.lookup": ["retrieval", "unified"],
        "retrieval_orchestrate": ["retrieval", "orchestrated"],
    }


def group_tools_by_capability() -> dict[str, list[str]]:
    """Group tools by their capabilities.
    
    Returns:
        Dictionary mapping capability names to lists of tool names.
    """
    capabilities = get_tool_capabilities()
    tool_groups = {}
    
    for tool_name, tool_caps in capabilities.items():
        for cap in tool_caps:
            if cap not in tool_groups:
                tool_groups[cap] = []
            tool_groups[cap].append(tool_name)
    
    return tool_groups