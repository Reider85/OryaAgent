"""agent_program capability-router function for B-30 multi-language programming.

This function serves as the central entry point for activating language-specific
programming capabilities, including skill-bundles, hook-sets, and LSP server
initialization.
"""

from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path
from typing import Any

from app.core.capability.language_registry import get_language_capability_registry
from app.core.dfc import get_dfc
from app.core.observability.metrics import get_metric_collector
from app.core.observability.spans import emit_span

logger = logging.getLogger(__name__)


async def agent_program(language: str, task: str) -> str:
    """Activate language-specific programming capabilities for a given task.

    This is the central capability-router function for B-30 multi-language
    programming. It activates language-specific skill-bundles, hook-sets,
    and ensures LSP server lazy initialization without blocking the agent loop.

    Args:
        language: Target language (java, rust, go, javascript, frontend)
        task: Description of the programming task

    Returns:
        Ready message indicating the language capability has been activated

    Raises:
        ValueError: If language is not supported
    """
    start_time = time.time()

    emit_span(
        span_type="language.program",
        name="language.program",
        attributes={
            "language": language,
            "task": task[:100] + "..." if len(task) > 100 else task,
        },
    )

    # Get language capability
    language_registry = get_language_capability_registry()
    capability = language_registry.resolve(language)

    # Get registries (lazy import to avoid circular dependency)
    from app.core.skills import get_skill_registry
    from app.core.tools import get_capability_registry

    skill_registry = await get_skill_registry()
    capability_registry = get_capability_registry()
    dfc = get_dfc()

    # Activate skill-bundle for this language: the bundle YAMLs in
    # app/skills/*.yaml are loaded by the registry on first use, so this is
    # an by-name activation of the already-loaded skill (the previous code
    # called a nonexistent registry.activate() and swallowed the error, so
    # bundles never activated).
    try:
        await skill_registry.activate_skill(capability.skill_bundle)
        logger.info(
            f"Activated skill-bundle: {capability.skill_bundle} for language: {language}"
        )
    except Exception as e:
        logger.warning(
            f"Failed to activate skill-bundle {capability.skill_bundle}: {e}"
        )
        # Continue without skill-bundle activation

    # Ensure LSP server is available (lazy initialization)
    try:
        from app.core.lsp import get_lsp_bus

        lsp_bus = get_lsp_bus()

        # Get workspace from current context (simplified for now)
        workspace = Path.cwd()

        # Ensure LSP server is started (lazy, non-blocking)
        asyncio.create_task(lsp_bus.ensure_server(capability.lsp_server, workspace))
        logger.info(
            f"Ensured LSP server availability: {capability.lsp_server} for language: {language}"
        )
    except Exception as e:
        logger.warning(f"Failed to ensure LSP server {capability.lsp_server}: {e}")
        # Continue without LSP server
        pass

    # Add capability information to DFC for context
    try:
        capability_info = _build_capability_info(capability)
        dfc.promote_to_hot("language_capability", capability_info)
        logger.debug(f"Added language capability info to DFC for language: {language}")
    except Exception as e:
        logger.warning(f"Failed to add capability info to DFC: {e}")
        # Continue without DFC integration
        pass

    # Update capability registry to include language-specific tools
    try:
        _update_capability_registry(capability_registry, capability)
        logger.debug(f"Updated capability registry for language: {language}")
    except Exception as e:
        logger.warning(f"Failed to update capability registry: {e}")
        # Continue without capability registry update
        pass

    # Record metrics
    metrics = get_metric_collector()
    metrics.counter_inc("orya_language_program_total", {"language": language})
    duration_ms = int((time.time() - start_time) * 1000)
    metrics.gauge_set(
        "orya_language_program_duration_ms", duration_ms, {"language": language}
    )

    # Return ready message
    return f"Ready for {language} programming. LSP server: {capability.lsp_server}, Skill bundle: {capability.skill_bundle}, Build: {capability.build_cmd}, Test: {capability.test_cmd}"


def _build_capability_info(capability: Any) -> str:
    """Build capability information string for DFC."""
    lines = [
        f"Active language: {capability.language} ({capability.lsp_server} LSP)",
        f"Skills: {capability.skill_bundle}",
        f"Hooks: {', '.join(capability.hooks)}",
        f"Build: `{capability.get_build_cmd_with_settings()}`",
        f"Test: `{capability.get_test_cmd_with_settings()}`",
    ]

    if capability.lint_cmd:
        lines.append(f"Lint: `{capability.get_lint_cmd_with_settings()}`")

    if capability.format_cmd:
        lines.append(f"Format: `{capability.get_format_cmd_with_settings()}`")

    return "\n".join(lines)


def _update_capability_registry(capability_registry: Any, capability: Any) -> None:
    """Update capability registry to include language-specific tools."""
    # This would integrate with B-29 CapabilityRegistry to make language-specific
    # tools visible when the language matches the current context
    # For now, this is a placeholder for the integration logic

    # In a full implementation, this would:
    # 1. Get the current TurnContext
    # 2. Add a trigger for language-specific tools
    # 3. Update the tool filtering rules

    # For BETA, this integration is handled in the CapabilityRegistry itself
    # through the existing trigger system
    pass


# Import asyncio at module level for compatibility
