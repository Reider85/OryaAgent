"""Unit tests for CapabilityRegistry (B-29)."""

from unittest.mock import Mock, patch

import pytest
from langchain_core.tools import BaseTool

from app.core.tools.capability_registry import (
    get_capability_registry,
    reset_capability_registry,
)
from app.core.tools.context import TurnContext
from app.core.tools.triggers import create_triggers, get_tool_capabilities


class MockTool(BaseTool):
    """Mock tool for testing."""

    def __init__(self, name: str, description: str = "Mock tool"):
        super().__init__(name=name, description=description, func=lambda x: x)

    def _run(self, *args, **kwargs):
        return f"Mock result for {self.name}"


class TestCapabilityRegistry:
    """Test CapabilityRegistry functionality."""

    def setup_method(self):
        """Setup for each test method."""
        reset_capability_registry()
        self.registry = get_capability_registry()
        self.basic_tools = [
            MockTool("read"),
            MockTool("write"),
            MockTool("edit"),
            MockTool("bash"),
            MockTool("grep"),
            MockTool("glob"),
        ]
        self.lsp_tools = [
            MockTool("lsp.hover"),
            MockTool("lsp.definition"),
            MockTool("lsp.references"),
            MockTool("lsp.symbol_search"),
            MockTool("lsp.rename"),
            MockTool("lsp.diagnostics"),
            MockTool("lsp.code_action"),
        ]
        self.search_tools = [
            MockTool("oriahs_search"),
            MockTool("oriahs_index"),
            MockTool("memory.search"),
            MockTool("ukb.lookup"),
            MockTool("retrieval_orchestrate"),
        ]
        self.all_tools = self.basic_tools + self.lsp_tools + self.search_tools

    def test_filter_tools_no_context(self):
        """Test tool filtering with no specific context."""
        context = TurnContext()
        filtered = self.registry.filter_tools(self.all_tools, context)

        # Should include basic tools and some others
        tool_names = [t.name for t in filtered]

        # Basic tools should always be present
        for basic_name in ["read", "write", "edit", "bash", "grep", "glob"]:
            assert basic_name in tool_names

        # UKB should always be present
        assert "ukb.lookup" in tool_names

        # LSP tools should not be present (no language context)
        for lsp_name in ["lsp.hover", "lsp.definition", "lsp.rename"]:
            assert lsp_name not in tool_names

    def test_filter_tools_python_context(self):
        """Test tool filtering with Python file context."""
        context = TurnContext(language="python", file_path="src/main.py")
        filtered = self.registry.filter_tools(self.all_tools, context)

        tool_names = [t.name for t in filtered]

        # Basic tools should be present
        for basic_name in ["read", "write", "edit", "bash", "grep", "glob"]:
            assert basic_name in tool_names

        # Python LSP tools should be present
        for lsp_name in [
            "lsp.hover",
            "lsp.definition",
            "lsp.references",
            "lsp.symbol_search",
            "lsp.diagnostics",
            "lsp.code_action",
        ]:
            assert lsp_name in tool_names

        # Rename should not be present (no rename intent)
        assert "lsp.rename" not in tool_names

    def test_filter_tools_rename_intent(self):
        """Test tool filtering with rename intent."""
        context = TurnContext(language="python", intent="rename")
        filtered = self.registry.filter_tools(self.all_tools, context)

        tool_names = [t.name for t in filtered]

        # Basic tools should be present
        for basic_name in ["read", "write", "edit", "bash", "grep", "glob"]:
            assert basic_name in tool_names

        # Rename LSP tool should be present
        assert "lsp.rename" in tool_names

        # Other LSP tools should not be present (no general code intent)
        for lsp_name in ["lsp.hover", "lsp.definition", "lsp.references"]:
            assert lsp_name not in tool_names

    def test_filter_tools_referential_marker(self):
        """Test tool filtering with referential markers."""
        context = TurnContext(
            last_message="Помнишь, мы обсуждали authentication?",
            referential_marker=True,
        )
        filtered = self.registry.filter_tools(self.all_tools, context)

        tool_names = [t.name for t in filtered]

        # Basic tools should be present
        for basic_name in ["read", "write", "edit", "bash", "grep", "glob"]:
            assert basic_name in tool_names

        # Memory search should be present
        assert "memory.search" in tool_names

        # Retrieval orchestration should be present
        assert "retrieval_orchestrate" in tool_names

    def test_filter_tools_max_limit(self):
        """Test that tool filtering respects maximum limit."""
        # Create many tools to test the limit
        many_tools = self.all_tools + [MockTool(f"extra_{i}") for i in range(20)]

        context = TurnContext(language="python")
        filtered = self.registry.filter_tools(many_tools, context)

        # Should not exceed 15 tools
        assert len(filtered) <= 15

        # Basic tools should be prioritized
        tool_names = [t.name for t in filtered]
        basic_count = sum(
            1
            for name in ["read", "write", "edit", "bash", "grep", "glob", "ukb.lookup"]
            if name in tool_names
        )
        assert basic_count >= 5  # At least basic tools should be present

    def test_is_relevant(self):
        """Test tool relevance checking."""
        context = TurnContext(language="python")

        # Basic tools should always be relevant
        for tool in self.basic_tools:
            assert self.registry.is_relevant(tool, context)

        # Python LSP tools should be relevant
        for tool in self.lsp_tools:
            assert self.registry.is_relevant(tool, context)

        # Search tools without specific intent should not be relevant
        search_context = TurnContext()
        for tool in self.search_tools[:2]:  # oriahs_search, oriahs_index
            assert not self.registry.is_relevant(tool, search_context)

    def test_statistics(self):
        """Test filtering statistics."""
        context = TurnContext(language="python")

        # Perform some filtering operations
        self.registry.filter_tools(self.all_tools, context)
        self.registry.filter_tools(self.all_tools, TurnContext())  # No context

        stats = self.registry.get_statistics()

        assert stats["total_filters"] == 2
        assert stats["active_count"] > 0
        assert stats["filtered_out_count"] >= 0
        assert 0 <= stats["active_tools_percentage"] <= 100

    def test_metrics_emission(self):
        """Test that metrics are properly emitted."""
        with patch(
            "app.core.tools.capability_registry.get_metric_collector"
        ) as mock_metrics:
            mock_collector = Mock()
            mock_metrics.return_value = mock_collector

            context = TurnContext(language="python")
            self.registry.filter_tools(self.all_tools, context)

            # Verify metrics were called
            mock_collector.gauge.assert_called()
            mock_collector.counter.assert_called()


class TestTriggers:
    """Test trigger functions."""

    def test_create_triggers(self):
        """Test trigger creation."""
        triggers = create_triggers()

        # Should have triggers for all expected tools
        expected_tools = [
            "lsp.hover",
            "lsp.definition",
            "lsp.references",
            "lsp.symbol_search",
            "lsp.rename",
            "lsp.diagnostics",
            "lsp.code_action",
            "memory.search",
            "oriahs_search",
            "oriahs_index",
            "ukb.lookup",
            "read",
            "write",
            "edit",
            "bash",
            "grep",
            "glob",
            "retrieval_orchestrate",
        ]

        for tool in expected_tools:
            assert tool in triggers

    def test_trigger_for_tool(self):
        """Test getting trigger for specific tool."""
        from app.core.tools.triggers import get_trigger_for_tool

        # Should have trigger for LSP tools
        trigger = get_trigger_for_tool("lsp.hover")
        assert trigger is not None

        # Should have trigger for basic tools
        trigger = get_trigger_for_tool("read")
        assert trigger is not None

        # Should return None for unknown tools
        trigger = get_trigger_for_tool("unknown_tool")
        assert trigger is None

    def test_tool_capabilities(self):
        """Test tool capabilities mapping."""
        capabilities = get_tool_capabilities()

        # Should have capabilities for all tools
        assert "read" in capabilities
        assert "write" in capabilities
        assert "lsp.hover" in capabilities
        assert "ukb.lookup" in capabilities

        # Should have expected capabilities
        assert "basic" in capabilities["read"]
        assert "file" in capabilities["read"]
        assert "language-specific" in capabilities["lsp.hover"]
        assert "code" in capabilities["lsp.hover"]


class TestTurnContext:
    """Test TurnContext functionality."""

    def test_context_creation(self):
        """Test basic context creation."""
        context = TurnContext()
        assert context.language is None
        assert context.file_path is None
        assert context.intent is None
        assert context.turn_count == 0
        assert context.last_message == ""
        assert context.previous_messages == []

    def test_context_from_session_state(self):
        """Test context creation from session state."""
        session_state = {
            "turn_count": 3,
            "last_message": "Help me with Python",
            "previous_messages": ["Hello", "How are you?"],
            "file_path": "src/main.py",
            "current_dir": "/project",
        }

        context = TurnContext.from_session_state(session_state)

        assert context.turn_count == 3
        assert context.last_message == "Help me with Python"
        assert context.previous_messages == ["Hello", "How are you?"]
        assert context.file_path == "src/main.py"
        assert context.current_dir == "/project"
        assert context.language == "python"  # Detected from file path

    def test_language_detection(self):
        """Test language detection from file paths."""
        test_cases = [
            ("src/main.py", "python"),
            ("lib.rs", "rust"),
            ("main.go", "go"),
            ("app.js", "javascript"),
            ("component.tsx", "frontend"),
            ("test.java", "java"),
            ("unknown.xyz", None),
        ]

        for file_path, expected_lang in test_cases:
            detected = TurnContext._detect_language_from_path(file_path)
            assert detected == expected_lang, (
                f"Failed for {file_path}: expected {expected_lang}, got {detected}"
            )

    def test_referential_marker_detection(self):
        """Test referential marker detection."""
        test_cases = [
            ("Помнишь, мы обсуждали authentication?", True),
            ("ранее мы решали эту проблему", True),
            ("remember our discussion", True),
            ("What should I do now?", False),
            ("Let's start fresh", False),
            ("", False),
        ]

        for message, expected in test_cases:
            result = TurnContext._has_referential_marker(message)
            assert result == expected, (
                f"Failed for '{message}': expected {expected}, got {result}"
            )

    def test_asking_about_past_detection(self):
        """Test asking about past detection."""
        test_cases = [
            ("что мы делали раньше", True),
            ("какие решения мы принимали", True),
            ("what did we accomplish", True),
            ("Let's move forward", False),
            ("What's next?", False),
            ("", False),
        ]

        for message, expected in test_cases:
            result = TurnContext._is_asking_about_past(message)
            assert result == expected, (
                f"Failed for '{message}': expected {expected}, got {result}"
            )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
