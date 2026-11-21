"""Integration helpers for CapabilityRegistry with session state (B-29)."""

from __future__ import annotations

import logging
from typing import Any

from app.core.tools.context import TurnContext

logger = logging.getLogger(__name__)


def create_turn_context_from_session(session_state: dict[str, Any]) -> TurnContext:
    """Create TurnContext from session state with enhanced context extraction.

    Args:
        session_state: LangGraph session state dictionary.

    Returns:
        TurnContext instance populated with enhanced context.
    """
    context = TurnContext.from_session_state(session_state)

    # Enhance context with additional analysis
    _enhance_context_with_file_analysis(context, session_state)
    _enhance_context_with_intent_analysis(context, session_state)
    _enhance_context_with_language_context(context, session_state)

    return context


def _enhance_context_with_file_analysis(
    context: TurnContext, session_state: dict[str, Any]
) -> None:
    """Enhance context with file-specific analysis."""
    if context.file_path and context.file_content:
        # Analyze file content for additional context
        content_lower = context.file_content.lower()

        # Check for code patterns
        if any(
            keyword in content_lower
            for keyword in ["class ", "def ", "function ", "import ", "from "]
        ):
            context.intent = context.intent or "code"

        # Check for configuration patterns
        if any(
            keyword in content_lower
            for keyword in ["config", "setting", "env", "property"]
        ):
            context.intent = context.intent or "config"

        # Check for test patterns
        if any(
            keyword in content_lower for keyword in ["test", "spec", "mock", "fixture"]
        ):
            context.intent = context.intent or "test"

        # Check for build patterns
        if any(
            keyword in content_lower
            for keyword in ["build", "compile", "make", "gradle", "maven"]
        ):
            context.intent = context.intent or "build"


def _enhance_context_with_intent_analysis(
    context: TurnContext, session_state: dict[str, Any]
) -> None:
    """Enhance context with intent analysis from user message."""
    if not context.last_message:
        return

    message_lower = context.last_message.lower()

    # Analyze specific intents
    if any(
        keyword in message_lower for keyword in ["rename", "renaming", "change name"]
    ):
        context.intent = context.intent or "rename"
    elif any(
        keyword in message_lower for keyword in ["search", "find", "locate", "grep"]
    ):
        context.intent = context.intent or "search"
    elif any(
        keyword in message_lower for keyword in ["build", "compile", "make", "run"]
    ):
        context.intent = context.intent or "build"
    elif any(
        keyword in message_lower for keyword in ["test", "check", "validate", "verify"]
    ):
        context.intent = context.intent or "test"
    elif any(keyword in message_lower for keyword in ["debug", "fix", "error", "bug"]):
        context.intent = context.intent or "debug"
    elif any(
        keyword in message_lower for keyword in ["refactor", "optimize", "improve"]
    ):
        context.intent = context.intent or "refactor"


def _enhance_context_with_language_context(
    context: TurnContext, session_state: dict[str, Any]
) -> None:
    """Enhance context with language-specific analysis."""
    if not context.language:
        return

    # Check if multiple files are involved (cross-project search)
    files_in_context = session_state.get("files", [])
    if len(files_in_context) > 3:
        context.cross_project_search = True

    # Check for LSP-specific context
    if context.language in ["python", "typescript", "javascript", "rust", "go", "java"]:
        # Check if cursor position is available
        cursor_info = session_state.get("cursor_position", {})
        if cursor_info and cursor_info.get("line") is not None:
            context.has_symbol_at_cursor = True


def get_filtered_tools_for_session(
    session_id: str, session_state: dict[str, Any]
) -> list:
    """Get filtered tools for a specific session.

    Args:
        session_id: Session identifier.
        session_state: LangGraph session state dictionary.

    Returns:
        Filtered list of tools for the session.
    """
    from app.core.tools import get_tools

    # Get all tools
    all_tools = get_tools()

    # Create context from session state
    context = create_turn_context_from_session(session_state)

    # Apply filtering
    from app.core.tools.capability_registry import get_capability_registry

    registry = get_capability_registry()
    filtered_tools = registry.filter_tools(all_tools, context)

    logger.info(
        "Session %s: %d -> %d tools (%.1f%% reduction)",
        session_id,
        len(all_tools),
        len(filtered_tools),
        (1 - len(filtered_tools) / len(all_tools)) * 100,
    )

    return filtered_tools


def validate_capability_filtering(session_state: dict[str, Any]) -> dict[str, Any]:
    """Validate that capability filtering is working correctly.

    Args:
        session_state: LangGraph session state dictionary.

    Returns:
        Validation results and statistics.
    """
    from app.core.tools import get_tools
    from app.core.tools.capability_registry import get_capability_registry

    all_tools = get_tools()
    context = create_turn_context_from_session(session_state)
    registry = get_capability_registry()

    filtered_tools = registry.filter_tools(all_tools, context)
    stats = registry.get_statistics()

    # Check if filtering is working as expected
    validation_result = {
        "original_count": len(all_tools),
        "filtered_count": len(filtered_tools),
        "expected_reduction": len(all_tools) > 15,  # Should reduce if too many tools
        "max_tools_limit": len(filtered_tools) <= 15,
        "basic_tools_present": any(
            getattr(tool, "name", "")
            in {"read", "write", "edit", "bash", "grep", "glob"}
            for tool in filtered_tools
        ),
        "context_relevant_tools": len(filtered_tools) < len(all_tools),
        "statistics": stats,
    }

    return validation_result
