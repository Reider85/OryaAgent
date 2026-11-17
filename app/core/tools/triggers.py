"""Triggers for capability-based tool filtering (B-29 + B-30)."""

from __future__ import annotations

from typing import Callable

from app.core.tools.context import TurnContext
from app.core.capability import get_language_capability_registry


# Supported LSP languages
LSP_LANGUAGES = {
    "python", "typescript", "javascript", "rust", "go", "java", "lua", 
    "cpp", "c", "csharp", "kotlin", "scala", "swift", "php", "ruby"
}

# B-30 Language-specific capabilities
SUPPORTED_LANGUAGES = {
    "java", "rust", "go", "javascript", "frontend"
}


def create_triggers() -> dict[str, Callable[[TurnContext], bool]]:
    """Create trigger functions for tool relevance.
    
    Returns:
        Dictionary mapping tool names to trigger functions that determine
        if the tool should be available based on current context.
    """
    return {
        # LSP tools - only visible when language is supported
        "lsp.hover": lambda ctx: _is_language_supported(ctx.language),
        "lsp.definition": lambda ctx: _is_language_supported(ctx.language) and ctx.has_symbol_at_cursor,
        "lsp.references": lambda ctx: _is_language_supported(ctx.language),
        "lsp.symbol_search": lambda ctx: _is_language_supported(ctx.language),
        "lsp.rename": lambda ctx: ctx.intent == "rename" and _is_language_supported(ctx.language),
        "lsp.diagnostics": lambda ctx: _is_language_supported(ctx.language),
        "lsp.code_action": lambda ctx: _is_language_supported(ctx.language),
        
        # B-30 Language-specific tool triggers
        "lsp_extract_method": lambda ctx: _is_java_language(ctx.language),
        "lsp_convert_to_record": lambda ctx: _is_java_language(ctx.language),
        "lsp_generate_hashCode_equals": lambda ctx: _is_java_language(ctx.language),
        "lsp_add_missing_interface_methods": lambda ctx: _is_java_language(ctx.language),
        
        "lsp_extract_function": lambda ctx: _is_rust_or_go_language(ctx.language),
        "lsp_convert_to_async": lambda ctx: _is_rust_language(ctx.language),
        "lsp_generate_impl_block": lambda ctx: _is_rust_language(ctx.language),
        "lsp_fix_clippy_lint": lambda ctx: _is_rust_language(ctx.language),
        
        "lsp_extract_to_component": lambda ctx: _is_frontend_language(ctx.language),
        "lsp_fix_a11y_violation": lambda ctx: _is_frontend_language(ctx.language),
        
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


# B-30 Language-specific helper functions
def _is_language_supported(language: str | None) -> bool:
    """Check if language is supported by B-30 capabilities.
    
    Args:
        language: Language identifier to check
        
    Returns:
        True if language is supported, False otherwise
    """
    if language is None:
        return False
    
    try:
        language_registry = get_language_capability_registry()
        return language_registry.is_supported(language)
    except Exception:
        # Fallback to basic LSP languages if registry fails
        return language in LSP_LANGUAGES


def _is_java_language(language: str | None) -> bool:
    """Check if language is Java.
    
    Args:
        language: Language identifier to check
        
    Returns:
        True if language is Java, False otherwise
    """
    return language == "java"


def _is_rust_language(language: str | None) -> bool:
    """Check if language is Rust.
    
    Args:
        language: Language identifier to check
        
    Returns:
        True if language is Rust, False otherwise
    """
    return language == "rust"


def _is_go_language(language: str | None) -> bool:
    """Check if language is Go.
    
    Args:
        language: Language identifier to check
        
    Returns:
        True if language is Go, False otherwise
    """
    return language == "go"


def _is_javascript_language(language: str | None) -> bool:
    """Check if language is JavaScript.
    
    Args:
        language: Language identifier to check
        
    Returns:
        True if language is JavaScript, False otherwise
    """
    return language == "javascript"


def _is_frontend_language(language: str | None) -> bool:
    """Check if language is Frontend (TSX/JSX).
    
    Args:
        language: Language identifier to check
        
    Returns:
        True if language is Frontend, False otherwise
    """
    return language == "frontend"


def _is_rust_or_go_language(language: str | None) -> bool:
    """Check if language is Rust or Go.
    
    Args:
        language: Language identifier to check
        
    Returns:
        True if language is Rust or Go, False otherwise
    """
    return language in {"rust", "go"}


def get_language_specific_tools(language: str | None) -> list[str]:
    """Get language-specific tools for a given language.
    
    Args:
        language: Language identifier
        
    Returns:
        List of language-specific tool names
    """
    if language is None:
        return []
    
    language_tools = []
    
    if _is_java_language(language):
        language_tools.extend([
            "lsp_extract_method",
            "lsp_convert_to_record", 
            "lsp_generate_hashCode_equals",
            "lsp_add_missing_interface_methods"
        ])
    elif _is_rust_language(language):
        language_tools.extend([
            "lsp_extract_function",
            "lsp_convert_to_async",
            "lsp_generate_impl_block",
            "lsp_fix_clippy_lint"
        ])
    elif _is_go_language(language):
        language_tools.extend([
            "lsp_extract_function",
            "lsp_convert_to_interface",
            "lsp_implement_missing_methods",
            "lsp_fix_struct_tag"
        ])
    elif _is_javascript_language(language):
        language_tools.extend([
            "lsp_extract_to_function",
            "lsp_convert_to_arrow_function",
            "lsp_add_missing_return_type",
            "lsp_fix_eslint_rule"
        ])
    elif _is_frontend_language(language):
        language_tools.extend([
            "lsp_extract_to_component",
            "lsp_convert_to_arrow_function",
            "lsp_add_missing_return_type",
            "lsp_fix_eslint_rule",
            "lsp_fix_a11y_violation"
        ])
    
    return language_tools