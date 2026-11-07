"""Example hooks for demonstration purposes."""

from __future__ import annotations

import logging
import time
from typing import Any

from app.core.hooks import (
    HookContext,
    HookResult,
    PostToolHook,
    PreToolHook,
    get_hook_registry,
    post_tool_hook,
    pre_tool_hook,
    pre_tool_hook_for_all_tools,
    post_tool_hook_for_all_tools,
    _hook_registry,
)

logger = logging.getLogger(__name__)


@pre_tool_hook("write")
async def logging_pre_write_hook(context: HookContext) -> HookResult:
    """Log before write operations."""
    logger.info(f"Writing to {context.tool_args.get('path', 'unknown')}")
    return HookResult(success=True)


@post_tool_hook("write")
async def logging_post_write_hook(
    context: HookContext, result: HookResult
) -> HookResult:
    """Log after write operations."""
    logger.info(f"Write operation completed: {result.success}")
    return result


@pre_tool_hook("bash")
async def timeout_pre_bash_hook(context: HookContext) -> HookResult:
    """Add timeout to bash commands."""
    timeout = context.tool_kwargs.get("timeout", 30)
    logger.info(f"Bash command with timeout: {timeout}s")
    return HookResult(success=True)


@post_tool_hook("bash")
async def metrics_post_bash_hook(
    context: HookContext, result: HookResult
) -> HookResult:
    """Collect metrics for bash operations."""
    logger.info(f"Bash operation took {result.message or 'unknown time'}")
    return result


@pre_tool_hook_for_all_tools()
async def audit_pre_hook(context: HookContext) -> HookResult:
    """Audit all tool calls."""
    logger.info(
        f"Audit: {context.session_id} used {context.tool_name} "
        f"with args: {context.tool_args}"
    )
    return HookResult(success=True)


@post_tool_hook_for_all_tools()
async def audit_post_hook(context: HookContext, result: HookResult) -> HookResult:
    """Audit all tool results."""
    logger.info(
        f"Audit: {context.tool_name} completed with "
        f"success: {result.success}, data: {result.data}"
    )
    return result


class ValidationHook(PreToolHook):
    """Example validation hook."""

    @property
    def name(self) -> str:
        return "validation_hook"

    @property
    def version(self) -> str:
        return "1.0.0"

    async def execute(self, context: HookContext) -> HookResult:
        """Validate tool arguments."""
        if context.tool_name == "write":
            path = context.tool_args.get("path", "")
            if not path.endswith(".py"):
                return HookResult(
                    success=False,
                    message="Only Python files can be written",
                    should_skip_tool=True,
                )

        return HookResult(success=True)


class MetricsHook(PostToolHook):
    """Example metrics hook."""

    @property
    def name(self) -> str:
        return "metrics_hook"

    @property
    def version(self) -> str:
        return "1.0.0"

    async def execute(self, context: HookContext, result: HookResult) -> HookResult:
        """Collect metrics."""
        logger.info(
            f"Tool {context.tool_name} executed in "
            f"{time.time():.2f}s with result: {result.success}"
        )
        return result


def register_example_hooks() -> None:
    """Register example hooks."""
    registry = get_hook_registry()

    # Register class-based hooks
    registry.register_pre_hook("write", ValidationHook())
    registry.register_post_hook("write", MetricsHook())

    # Function-based hooks are already registered via decorators
    logger.info("Example hooks registered")


def clear_example_hooks() -> None:
    """Clear example hooks."""
    registry = get_hook_registry()

    # Clear specific hooks
    registry.unregister_hooks("write")

    # Clear all hooks
    registry.clear_all_hooks()

    logger.info("Example hooks cleared")
