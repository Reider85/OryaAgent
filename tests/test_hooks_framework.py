"""Tests for hooks framework (B-04)."""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.core.hooks import (
    BaseHook,
    HookContext,
    HookExecutor,
    HookRegistry,
    HookResult,
    PostToolHook,
    PreToolHook,
    FunctionPostToolHook,
    FunctionPreToolHook,
    get_hook_registry,
    get_hook_executor,
    pre_tool_hook,
    post_tool_hook,
    pre_tool_hook_for_all_tools,
    post_tool_hook_for_all_tools,
)


class MockPreHook(PreToolHook):
    """Mock pre-tool hook for testing."""
    
    @property
    def name(self) -> str:
        return "mock_pre_hook"
    
    @property
    def version(self) -> str:
        return "1.0.0"
    
    async def execute(self, context: HookContext) -> HookResult:
        return HookResult(success=True, data=f"Pre: {context.tool_name}")


class MockPostHook(PostToolHook):
    """Mock post-tool hook for testing."""
    
    @property
    def name(self) -> str:
        return "mock_post_hook"
    
    @property
    def version(self) -> str:
        return "1.0.0"
    
    async def execute(self, context: HookContext, result: HookResult) -> HookResult:
        return HookResult(
            success=result.success,
            data=f"Post: {context.tool_name} - {result.data}",
            message=f"Post hook executed for {context.tool_name}",
        )


class FailingHook(BaseHook):
    """Hook that always fails."""
    
    @property
    def name(self) -> str:
        return "failing_hook"
    
    @property
    def version(self) -> str:
        return "1.0.0"
    
    async def execute(self, context: HookContext, result: HookResult = None) -> HookResult:
        return HookResult(success=False, message="Hook failed")


class SkipHook(PreToolHook):
    """Hook that skips tool execution."""
    
    @property
    def name(self) -> str:
        return "skip_hook"
    
    @property
    def version(self) -> str:
        return "1.0.0"
    
    async def execute(self, context: HookContext) -> HookResult:
        return HookResult(
            success=True,
            should_skip_tool=True,
            message="Skipping tool execution",
        )


class TestHookContext:
    """Test HookContext."""
    
    def test_hook_context_creation(self):
        """Test HookContext creation."""
        context = HookContext(
            session_id="test_session",
            tool_name="test_tool",
            tool_args={"arg1": "value1"},
            tool_kwargs={"kwarg1": "value1"},
            turn_id="test_turn",
        )
        
        assert context.session_id == "test_session"
        assert context.tool_name == "test_tool"
        assert context.tool_args == {"arg1": "value1"}
        assert context.tool_kwargs == {"kwarg1": "value1"}
        assert context.turn_id == "test_turn"
        assert context.metadata == {}


class TestHookResult:
    """Test HookResult."""
    
    def test_hook_result_defaults(self):
        """Test HookResult default values."""
        result = HookResult()
        
        assert result.success is True
        assert result.data is None
        assert result.message is None
        assert result.should_skip_tool is False
    
    def test_hook_result_with_values(self):
        """Test HookResult with custom values."""
        result = HookResult(
            success=False,
            data="test_data",
            message="test message",
            should_skip_tool=True,
        )
        
        assert result.success is False
        assert result.data == "test_data"
        assert result.message == "test message"
        assert result.should_skip_tool is True


class TestHookRegistry:
    """Test HookRegistry."""
    
    def setup_method(self):
        """Setup test registry."""
        self.registry = HookRegistry()
    
    def test_register_pre_hook(self):
        """Test registering a pre-hook."""
        hook = MockPreHook()
        self.registry.register_pre_hook("test_tool", hook)
        
        assert "test_tool" in self.registry._pre_hooks
        assert len(self.registry._pre_hooks["test_tool"]) == 1
        assert self.registry._pre_hooks["test_tool"][0] == hook
    
    def test_register_post_hook(self):
        """Test registering a post-hook."""
        hook = MockPostHook()
        self.registry.register_post_hook("test_tool", hook)
        
        assert "test_tool" in self.registry._post_hooks
        assert len(self.registry._post_hooks["test_tool"]) == 1
        assert self.registry._post_hooks["test_tool"][0] == hook
    
    def test_register_multiple_hooks(self):
        """Test registering multiple hooks for the same tool."""
        hook1 = MockPreHook()
        hook2 = MockPreHook()
        
        self.registry.register_pre_hook("test_tool", hook1)
        self.registry.register_pre_hook("test_tool", hook2)
        
        assert len(self.registry._pre_hooks["test_tool"]) == 2
        assert self.registry._pre_hooks["test_tool"][0] == hook1
        assert self.registry._pre_hooks["test_tool"][1] == hook2
    
    def test_replace_hooks(self):
        """Test replacing existing hooks."""
        hook1 = MockPreHook()
        hook2 = MockPreHook()
        
        self.registry.register_pre_hook("test_tool", hook1)
        self.registry.register_pre_hook("test_tool", hook2, replace=True)
        
        assert len(self.registry._pre_hooks["test_tool"]) == 1
        assert self.registry._pre_hooks["test_tool"][0] == hook2
    
    def test_get_hooks(self):
        """Test getting hooks."""
        hook = MockPreHook()
        self.registry.register_pre_hook("test_tool", hook)
        
        pre_hooks = self.registry.get_pre_hooks("test_tool")
        assert len(pre_hooks) == 1
        assert pre_hooks[0] == hook
        
        post_hooks = self.registry.get_post_hooks("test_tool")
        assert len(post_hooks) == 0
    
    def test_list_hooks(self):
        """Test listing hooks."""
        hook = MockPreHook()
        self.registry.register_pre_hook("test_tool", hook)
        
        hooks = self.registry.list_hooks()
        
        assert "pre_hooks" in hooks
        assert "post_hooks" in hooks
        assert "test_tool" in hooks["pre_hooks"]
        assert "mock_pre_hook" in hooks["pre_hooks"]["test_tool"]
    
    def test_unregister_hooks(self):
        """Test unregistering hooks."""
        hook = MockPreHook()
        self.registry.register_pre_hook("test_tool", hook)
        
        self.registry.unregister_hooks("test_tool")
        
        assert "test_tool" not in self.registry._pre_hooks
    
    def test_clear_all_hooks(self):
        """Test clearing all hooks."""
        hook = MockPreHook()
        self.registry.register_pre_hook("test_tool", hook)
        self.registry.register_post_hook("test_tool", hook)
        
        self.registry.clear_all_hooks()
        
        assert len(self.registry._pre_hooks) == 0
        assert len(self.registry._post_hooks) == 0


class TestHookExecutor:
    """Test HookExecutor."""
    
    def setup_method(self):
        """Setup test registry and executor."""
        self.registry = HookRegistry()
        self.executor = HookExecutor(self.registry)
    
    @pytest.mark.asyncio
    async def test_execute_pre_hooks_success(self):
        """Test successful pre-hook execution."""
        hook = MockPreHook()
        self.registry.register_pre_hook("test_tool", hook)
        
        result = await self.executor.execute_pre_hooks(
            session_id="test_session",
            tool_name="test_tool",
            tool_args={"arg": "value"},
            tool_kwargs={},
        )
        
        assert result.success is True
        assert result.data == "Pre: test_tool"
    
    @pytest.mark.asyncio
    async def test_execute_pre_hooks_skip_tool(self):
        """Test pre-hook that skips tool execution."""
        skip_hook = SkipHook()
        self.registry.register_pre_hook("test_tool", skip_hook)
        
        result = await self.executor.execute_pre_hooks(
            session_id="test_session",
            tool_name="test_tool",
            tool_args={"arg": "value"},
            tool_kwargs={},
        )
        
        assert result.should_skip_tool is True
        assert result.message == "Skipping tool execution"
    
    @pytest.mark.asyncio
    async def test_execute_pre_hooks_failure(self):
        """Test pre-hook execution failure."""
        failing_hook = FailingHook()
        self.registry.register_pre_hook("test_tool", failing_hook)
        
        result = await self.executor.execute_pre_hooks(
            session_id="test_session",
            tool_name="test_tool",
            tool_args={"arg": "value"},
            tool_kwargs={},
        )
        
        assert result.success is False
        assert "Hook failed" in result.message
    
    @pytest.mark.asyncio
    async def test_execute_post_hooks_success(self):
        """Test successful post-hook execution."""
        hook = MockPostHook()
        self.registry.register_post_hook("test_tool", hook)
        
        tool_result = HookResult(success=True, data="tool_data")
        
        result = await self.executor.execute_post_hooks(
            session_id="test_session",
            tool_name="test_tool",
            tool_args={"arg": "value"},
            tool_kwargs={},
            tool_result=tool_result,
        )
        
        assert result.success is True
        assert result.data == "Post: test_tool - tool_data"
        assert "Post hook executed for test_tool" in result.message
    
    @pytest.mark.asyncio
    async def test_execute_post_hooks_failure(self):
        """Test post-hook execution failure."""
        failing_hook = FailingHook()
        self.registry.register_post_hook("test_tool", failing_hook)
        
        tool_result = HookResult(success=True, data="tool_data")
        
        result = await self.executor.execute_post_hooks(
            session_id="test_session",
            tool_name="test_tool",
            tool_args={"arg": "value"},
            tool_kwargs={},
            tool_result=tool_result,
        )
        
        assert result.success is True  # Original result should be preserved
        assert result.data == "tool_data"
        assert "Hook failed" in result.message


class TestFunctionHooks:
    """Test function-based hooks."""
    
    def test_function_pre_hook_decorator(self):
        """Test function pre-hook decorator."""
        @pre_tool_hook("test_tool")
        def mock_func(context: HookContext) -> HookResult:
            return HookResult(success=True, data="function_data")
        
        # The decorator should register the hook
        registry = get_hook_registry()
        hooks = registry.get_pre_hooks("test_tool")
        
        assert len(hooks) == 1
        assert isinstance(hooks[0], FunctionPreToolHook)
        assert hooks[0].name == "mock_func"
    
    def test_function_post_hook_decorator(self):
        """Test function post-hook decorator."""
        @post_tool_hook("test_tool")
        def mock_func(context: HookContext, result: HookResult) -> HookResult:
            return HookResult(success=True, data="post_data")
        
        # The decorator should register the hook
        registry = get_hook_registry()
        hooks = registry.get_post_hooks("test_tool")
        
        assert len(hooks) == 1
        assert isinstance(hooks[0], FunctionPostToolHook)
        assert hooks[0].name == "mock_func"
    
    def test_function_pre_hook_for_all_tools_decorator(self):
        """Test function pre-hook for all tools decorator."""
        @pre_tool_hook_for_all_tools()
        def mock_func(context: HookContext) -> HookResult:
            return HookResult(success=True, data="all_tools_data")
        
        # The decorator should register the hook
        registry = get_hook_registry()
        
        # Check that the hook is registered for some tools
        # (we can't predict which tools will be registered in advance)
        found_hook = False
        for tool_hooks in registry._pre_hooks.values():
            for hook in tool_hooks:
                if isinstance(hook, FunctionPreToolHook) and hook.name == "mock_func":
                    found_hook = True
                    break
        
        assert found_hook
    
    def test_function_post_hook_for_all_tools_decorator(self):
        """Test function post-hook for all tools decorator."""
        @post_tool_hook_for_all_tools()
        def mock_func(context: HookContext, result: HookResult) -> HookResult:
            return HookResult(success=True, data="all_tools_post_data")
        
        # The decorator should register the hook
        registry = get_hook_registry()
        
        # Check that the hook is registered for some tools
        found_hook = False
        for tool_hooks in registry._post_hooks.values():
            for hook in tool_hooks:
                if isinstance(hook, FunctionPostToolHook) and hook.name == "mock_func":
                    found_hook = True
                    break
        
        assert found_hook


class TestFunctionHookExecution:
    """Test function hook execution."""
    
    def setup_method(self):
        """Setup test registry and executor."""
        # Use fresh registry for each test to avoid interference
        self.registry = HookRegistry()
        self.executor = HookExecutor(self.registry)
    
    @pytest.mark.asyncio
    async def test_sync_function_pre_hook(self):
        """Test synchronous function pre-hook."""
        # Create function hook directly without decorator
        def sync_func(context: HookContext) -> HookResult:
            return HookResult(success=True, data="sync_data")
        
        hook = FunctionPreToolHook(sync_func)
        self.registry.register_pre_hook("test_tool", hook)
        
        result = await self.executor.execute_pre_hooks(
            session_id="test_session",
            tool_name="test_tool",
            tool_args={"arg": "value"},
            tool_kwargs={},
        )
        
        assert result.success is True
        assert result.data == "sync_data"
    
    @pytest.mark.asyncio
    async def test_async_function_pre_hook(self):
        """Test asynchronous function pre-hook."""
        # Create function hook directly without decorator
        async def async_func(context: HookContext) -> HookResult:
            await asyncio.sleep(0.01)  # Simulate async work
            return HookResult(success=True, data="async_data")
        
        hook = FunctionPreToolHook(async_func)
        self.registry.register_pre_hook("test_tool", hook)
        
        result = await self.executor.execute_pre_hooks(
            session_id="test_session",
            tool_name="test_tool",
            tool_args={"arg": "value"},
            tool_kwargs={},
        )
        
        assert result.success is True
        assert result.data == "async_data"
    
    @pytest.mark.asyncio
    async def test_sync_function_post_hook(self):
        """Test synchronous function post-hook."""
        # Create function hook directly without decorator
        def sync_func(context: HookContext, result: HookResult) -> HookResult:
            return HookResult(
                success=result.success,
                data=f"sync_{result.data}",
                message="sync hook executed",
            )
        
        hook = FunctionPostToolHook(sync_func)
        self.registry.register_post_hook("test_tool", hook)
        
        tool_result = HookResult(success=True, data="tool_data")
        
        result = await self.executor.execute_post_hooks(
            session_id="test_session",
            tool_name="test_tool",
            tool_args={"arg": "value"},
            tool_kwargs={},
            tool_result=tool_result,
        )
        
        assert result.success is True
        assert result.data == "sync_tool_data"
        assert result.message == "sync hook executed"
    
    @pytest.mark.asyncio
    async def test_async_function_post_hook(self):
        """Test asynchronous function post-hook."""
        # Create function hook directly without decorator
        async def async_func(context: HookContext, result: HookResult) -> HookResult:
            await asyncio.sleep(0.01)  # Simulate async work
            return HookResult(
                success=result.success,
                data=f"async_{result.data}",
                message="async hook executed",
            )
        
        hook = FunctionPostToolHook(async_func)
        self.registry.register_post_hook("test_tool", hook)
        
        tool_result = HookResult(success=True, data="tool_data")
        
        result = await self.executor.execute_post_hooks(
            session_id="test_session",
            tool_name="test_tool",
            tool_args={"arg": "value"},
            tool_kwargs={},
            tool_result=tool_result,
        )
        
        assert result.success is True
        assert result.data == "async_tool_data"
        assert result.message == "async hook executed"


class TestGlobalRegistry:
    """Test global registry and executor."""
    
    def test_get_hook_registry(self):
        """Test getting global hook registry."""
        registry = get_hook_registry()
        assert isinstance(registry, HookRegistry)
    
    def test_get_hook_executor(self):
        """Test getting global hook executor."""
        executor = get_hook_executor()
        assert isinstance(executor, HookExecutor)
    
    def test_global_registry_singleton(self):
        """Test that global registry is a singleton."""
        registry1 = get_hook_registry()
        registry2 = get_hook_registry()
        
        assert registry1 is registry2