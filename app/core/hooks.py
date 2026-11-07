"""Hooks framework (B-04) - pre/post-tool registry and execution.

Provides a flexible system for executing custom logic before and after tool calls.
Supports synchronous and asynchronous hooks with error handling and logging.
"""

from __future__ import annotations

import asyncio
import logging
import time
from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import Any

from app.core.hooks_audit import record_hook_execution
from app.core.observability.spans import emit_span

logger = logging.getLogger(__name__)


class HookContext:
    """Context information passed to hooks during execution."""

    def __init__(
        self,
        session_id: str,
        tool_name: str,
        tool_args: dict[str, Any],
        tool_kwargs: dict[str, Any],
        turn_id: str | None = None,
    ):
        self.session_id = session_id
        self.tool_name = tool_name
        self.tool_args = tool_args
        self.tool_kwargs = tool_kwargs
        self.turn_id = turn_id
        self.metadata: dict[str, Any] = {}


class HookResult:
    """Result from hook execution."""

    def __init__(
        self,
        success: bool = True,
        data: Any | None = None,
        message: str | None = None,
        should_skip_tool: bool = False,
    ):
        self.success = success
        self.data = data
        self.message = message
        self.should_skip_tool = should_skip_tool


class BaseHook(ABC):
    """Base class for all hooks."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Return the hook name."""
        pass

    @property
    @abstractmethod
    def version(self) -> str:
        """Return the hook version."""
        pass

    @property
    def description(self) -> str:
        """Return the hook description."""
        return f"Hook: {self.name} v{self.version}"

    @abstractmethod
    async def execute(
        self, context: HookContext, result: HookResult | None = None
    ) -> HookResult:
        """Execute the hook with given context and optional result.

        Args:
            context: Hook execution context
            result: Optional result from post-tool hook execution

        Returns:
            HookResult with execution status and data
        """
        pass


class PreToolHook(BaseHook):
    """Base class for pre-tool hooks."""

    @abstractmethod
    async def execute(self, context: HookContext) -> HookResult:
        """Execute pre-tool logic.

        Args:
            context: Hook execution context

        Returns:
            HookResult with execution status and data
            Set should_skip_tool=True to skip the actual tool execution
        """
        pass


class PostToolHook(BaseHook):
    """Base class for post-tool hooks."""

    @abstractmethod
    async def execute(self, context: HookContext, result: HookResult) -> HookResult:
        """Execute post-tool logic.

        Args:
            context: Hook execution context
            result: Result from the tool execution

        Returns:
            HookResult with execution status and modified data
        """
        pass


class HookRegistry:
    """Registry for managing hooks."""

    def __init__(self):
        self._pre_hooks: dict[str, list[PreToolHook]] = {}
        self._post_hooks: dict[str, list[PostToolHook]] = {}
        self._hook_types: dict[str, type[BaseHook]] = {}

    def register_hook_type(self, hook_type: type[BaseHook]) -> None:
        """Register a hook type."""
        self._hook_types[hook_type.name] = hook_type

    def register_pre_hook(
        self, tool_name: str, hook: PreToolHook, replace: bool = False
    ) -> None:
        """Register a pre-tool hook for a specific tool.

        Args:
            tool_name: Name of the tool this hook applies to
            hook: PreToolHook instance
            replace: Replace existing hooks if True
        """
        if tool_name not in self._pre_hooks:
            self._pre_hooks[tool_name] = []

        if replace:
            self._pre_hooks[tool_name] = [hook]
        else:
            self._pre_hooks[tool_name].append(hook)

    def register_post_hook(
        self, tool_name: str, hook: PostToolHook, replace: bool = False
    ) -> None:
        """Register a post-tool hook for a specific tool.

        Args:
            tool_name: Name of the tool this hook applies to
            hook: PostToolHook instance
            replace: Replace existing hooks if True
        """
        if tool_name not in self._post_hooks:
            self._post_hooks[tool_name] = []

        if replace:
            self._post_hooks[tool_name] = [hook]
        else:
            self._post_hooks[tool_name].append(hook)

    def register_hooks_for_all_tools(self, hook: BaseHook) -> None:
        """Register a hook for all tools."""
        if isinstance(hook, PreToolHook):
            for tool_name in self._pre_hooks:
                if tool_name not in self._pre_hooks:
                    self._pre_hooks[tool_name] = []
                self._pre_hooks[tool_name].append(hook)
        elif isinstance(hook, PostToolHook):
            for tool_name in self._post_hooks:
                if tool_name not in self._post_hooks:
                    self._post_hooks[tool_name] = []
                self._post_hooks[tool_name].append(hook)

    def get_pre_hooks(self, tool_name: str) -> list[PreToolHook]:
        """Get all pre-tool hooks for a tool."""
        return self._pre_hooks.get(tool_name, [])

    def get_post_hooks(self, tool_name: str) -> list[PostToolHook]:
        """Get all post-tool hooks for a tool."""
        return self._post_hooks.get(tool_name, [])

    def list_hooks(self) -> dict[str, dict[str, list[str]]]:
        """List all registered hooks."""
        return {
            "pre_hooks": {
                tool: [hook.name for hook in hooks]
                for tool, hooks in self._pre_hooks.items()
            },
            "post_hooks": {
                tool: [hook.name for hook in hooks]
                for tool, hooks in self._post_hooks.items()
            },
        }

    def unregister_hooks(self, tool_name: str) -> None:
        """Unregister all hooks for a tool."""
        self._pre_hooks.pop(tool_name, None)
        self._post_hooks.pop(tool_name, None)

    def clear_all_hooks(self) -> None:
        """Clear all registered hooks."""
        self._pre_hooks.clear()
        self._post_hooks.clear()


class HookExecutor:
    """Executor for running hooks."""

    def __init__(self, registry: HookRegistry):
        self.registry = registry

    async def execute_pre_hooks(
        self,
        session_id: str,
        tool_name: str,
        tool_args: dict[str, Any],
        tool_kwargs: dict[str, Any],
        turn_id: str | None = None,
    ) -> HookResult:
        """Execute all pre-tool hooks for a tool.

        Args:
            session_id: Session ID
            tool_name: Name of the tool
            tool_args: Tool arguments
            tool_kwargs: Tool keyword arguments
            turn_id: Optional turn ID

        Returns:
            HookResult from the last hook or default success result
        """
        context = HookContext(
            session_id=session_id,
            tool_name=tool_name,
            tool_args=tool_args,
            tool_kwargs=tool_kwargs,
            turn_id=turn_id,
        )

        hooks = self.registry.get_pre_hooks(tool_name)

        if not hooks:
            return HookResult(success=True)

        final_result = HookResult(success=True)

        for hook in hooks:
            start_time = time.time()
            try:
                emit_span(
                    span_type="tool.call",
                    name=f"hook.{hook.name}",
                    attributes={"tool_type": "pre_tool"},
                    status="running",
                )

                result = await hook.execute(context)

                duration_ms = (time.time() - start_time) * 1000

                # Record hook execution in audit log
                record_hook_execution(
                    session_id=session_id,
                    tool_name=tool_name,
                    hook_name=hook.name,
                    hook_type="pre",
                    success=result.success,
                    message=result.message,
                    duration_ms=duration_ms,
                    turn_id=turn_id,
                )

                if not result.success:
                    logger.warning(
                        f"Pre-hook {hook.name} failed for tool {tool_name}: "
                        f"{result.message}"
                    )

                # If any hook wants to skip the tool, respect that
                if result.should_skip_tool:
                    logger.info(
                        f"Pre-hook {hook.name} requested to skip tool {tool_name}"
                    )
                    return result

                final_result = result

            except Exception as e:
                duration_ms = (time.time() - start_time) * 1000
                logger.error(f"Pre-hook {hook.name} failed for tool {tool_name}: {e}")

                # Record hook execution failure in audit log
                record_hook_execution(
                    session_id=session_id,
                    tool_name=tool_name,
                    hook_name=hook.name,
                    hook_type="pre",
                    success=False,
                    message=f"Hook {hook.name} failed: {str(e)}",
                    duration_ms=duration_ms,
                    turn_id=turn_id,
                )

                # Continue with other hooks but mark as partially failed
                final_result = HookResult(
                    success=False, message=f"Hook {hook.name} failed: {str(e)}"
                )

        return final_result

    async def execute_post_hooks(
        self,
        session_id: str,
        tool_name: str,
        tool_args: dict[str, Any],
        tool_kwargs: dict[str, Any],
        tool_result: HookResult,
        turn_id: str | None = None,
    ) -> HookResult:
        """Execute all post-tool hooks for a tool.

        Args:
            session_id: Session ID
            tool_name: Name of the tool
            tool_args: Tool arguments
            tool_kwargs: Tool keyword arguments
            tool_result: Result from the tool execution
            turn_id: Optional turn ID

        Returns:
            HookResult from the last hook or the original result
        """
        context = HookContext(
            session_id=session_id,
            tool_name=tool_name,
            tool_args=tool_args,
            tool_kwargs=tool_kwargs,
            turn_id=turn_id,
        )

        hooks = self.registry.get_post_hooks(tool_name)

        if not hooks:
            return tool_result

        final_result = tool_result

        for hook in hooks:
            start_time = time.time()
            try:
                emit_span(
                    span_type="tool.call",
                    name=f"hook.{hook.name}",
                    attributes={"tool_type": "post_tool"},
                    status="running",
                )

                result = await hook.execute(context, final_result)

                duration_ms = (time.time() - start_time) * 1000

                # Record hook execution in audit log
                record_hook_execution(
                    session_id=session_id,
                    tool_name=tool_name,
                    hook_name=hook.name,
                    hook_type="post",
                    success=result.success,
                    message=result.message,
                    duration_ms=duration_ms,
                    turn_id=turn_id,
                )

                if not result.success:
                    logger.warning(
                        f"Post-hook {hook.name} failed for tool {tool_name}: "
                        f"{result.message}"
                    )

                # Update the result with hook modifications
                if result.data is not None:
                    final_result.data = result.data

                final_result.message = result.message or final_result.message

            except Exception as e:
                duration_ms = (time.time() - start_time) * 1000
                logger.error(f"Post-hook {hook.name} failed for tool {tool_name}: {e}")

                # Record hook execution failure in audit log
                record_hook_execution(
                    session_id=session_id,
                    tool_name=tool_name,
                    hook_name=hook.name,
                    hook_type="post",
                    success=False,
                    message=f"Hook {hook.name} failed: {str(e)}",
                    duration_ms=duration_ms,
                    turn_id=turn_id,
                )

                # Continue with other hooks but keep the original result
                final_result.message = (
                    f"{final_result.message or ''} (Hook {hook.name} failed: {str(e)})"
                )

        return final_result


# Global hook registry and executor
_hook_registry = HookRegistry()
_hook_executor = HookExecutor(_hook_registry)


def get_hook_registry() -> HookRegistry:
    """Get the global hook registry."""
    return _hook_registry


def get_hook_executor() -> HookExecutor:
    """Get the global hook executor."""
    return _hook_executor


# Decorators for easy hook registration
def pre_tool_hook(tool_name: str, replace: bool = False):
    """Decorator to register a function as a pre-tool hook."""

    def decorator(func: Callable) -> PreToolHook:
        hook = FunctionPreToolHook(func)
        _hook_registry.register_pre_hook(tool_name, hook, replace)
        return hook

    return decorator


def post_tool_hook(tool_name: str, replace: bool = False):
    """Decorator to register a function as a post-tool hook."""

    def decorator(func: Callable) -> PostToolHook:
        hook = FunctionPostToolHook(func)
        _hook_registry.register_post_hook(tool_name, hook, replace)
        return hook

    return decorator


def pre_tool_hook_for_all_tools(replace: bool = False):
    """Decorator to register a function as a pre-tool hook for all tools."""

    def decorator(func: Callable) -> PreToolHook:
        hook = FunctionPreToolHook(func)
        _hook_registry.register_hooks_for_all_tools(hook)
        return hook

    return decorator


def post_tool_hook_for_all_tools(replace: bool = False):
    """Decorator to register a function as a post-tool hook for all tools."""

    def decorator(func: Callable) -> PostToolHook:
        hook = FunctionPostToolHook(func)
        _hook_registry.register_hooks_for_all_tools(hook)
        return hook

    return decorator


class FunctionPreToolHook(PreToolHook):
    """Pre-tool hook that wraps a function."""

    def __init__(self, func: Callable):
        self.func = func

    @property
    def name(self) -> str:
        return self.func.__name__

    @property
    def version(self) -> str:
        return "1.0.0"

    async def execute(self, context: HookContext) -> HookResult:
        """Execute the wrapped function."""
        if asyncio.iscoroutinefunction(self.func):
            result = await self.func(context)
        else:
            result = self.func(context)

        if isinstance(result, HookResult):
            return result

        return HookResult(success=True, data=result)


class FunctionPostToolHook(PostToolHook):
    """Post-tool hook that wraps a function."""

    def __init__(self, func: Callable):
        self.func = func

    @property
    def name(self) -> str:
        return self.func.__name__

    @property
    def version(self) -> str:
        return "1.0.0"

    async def execute(self, context: HookContext, result: HookResult) -> HookResult:
        """Execute the wrapped function."""
        if asyncio.iscoroutinefunction(self.func):
            new_result = await self.func(context, result)
        else:
            new_result = self.func(context, result)

        if isinstance(new_result, HookResult):
            return new_result

        # Return the original result but with the hook's data
        return HookResult(
            success=result.success,
            data=new_result,
            message=result.message,
        )
