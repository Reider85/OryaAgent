"""Integration tests for CapabilityRegistry with session state (B-29)."""

from unittest.mock import patch

import pytest

from app.core.tools.context import TurnContext
from app.core.tools.integration import (
    create_turn_context_from_session,
    get_filtered_tools_for_session,
    validate_capability_filtering,
)


class MockTool:
    """Mock tool for integration testing."""

    def __init__(self, name: str):
        self.name = name

    def __repr__(self):
        return f"MockTool({self.name})"


class TestCapabilityRegistryIntegration:
    """Test CapabilityRegistry integration with session state."""

    def setup_method(self):
        """Setup for each test method."""
        # Mock tools
        self.tools = [
            MockTool("read"),
            MockTool("write"),
            MockTool("edit"),
            MockTool("bash"),
            MockTool("grep"),
            MockTool("glob"),
            MockTool("lsp.hover"),
            MockTool("lsp.definition"),
            MockTool("lsp.references"),
            MockTool("lsp.rename"),
            MockTool("lsp.symbol_search"),
            MockTool("lsp.diagnostics"),
            MockTool("lsp.code_action"),
            MockTool("oriahs_search"),
            MockTool("oriahs_index"),
            MockTool("memory.search"),
            MockTool("ukb.lookup"),
            MockTool("retrieval_orchestrate"),
        ]

    def test_create_turn_context_from_session(self):
        """Test context creation from session state."""
        session_state = {
            "turn_count": 5,
            "last_message": "Помнишь, мы обсуждали authentication?",
            "previous_messages": ["Hello", "Let's start", "We need auth"],
            "file_path": "src/auth.py",
            "file_content": "def authenticate(user, password):",
            "current_dir": "/project",
            "intent": "code",
            "cursor_position": {"line": 10, "column": 5},
            "files": ["src/auth.py", "src/main.py", "tests/test_auth.py", "config.py"],
        }

        context = create_turn_context_from_session(session_state)

        # Basic fields
        assert context.turn_count == 5
        assert context.last_message == "Помнишь, мы обсуждали authentication?"
        assert context.previous_messages == ["Hello", "Let's start", "We need auth"]
        assert context.current_dir == "/project"

        # Derived fields
        assert context.language == "python"
        assert context.file_path == "src/auth.py"
        assert context.file_content == "def authenticate(user, password):"
        assert context.referential_marker  # Russian "Помнишь"
        assert context.asking_about_past
        assert context.has_symbol_at_cursor
        assert context.cross_project_search  # Multiple files
        assert context.intent == "code"

    def test_create_turn_context_from_session_no_context(self):
        """Test context creation with minimal session state."""
        session_state = {
            "turn_count": 1,
            "last_message": "Hello",
            "previous_messages": [],
        }

        context = create_turn_context_from_session(session_state)

        assert context.turn_count == 1
        assert context.last_message == "Hello"
        assert context.previous_messages == []
        assert context.language is None
        assert context.file_path is None
        assert not context.referential_marker
        assert not context.asking_about_past

    @patch("app.core.tools.integration.get_tools")
    def test_get_filtered_tools_for_session(self, mock_get_tools):
        """Test getting filtered tools for session."""
        mock_get_tools.return_value = self.tools

        session_state = {
            "turn_count": 3,
            "last_message": "Help me with Python code",
            "file_path": "src/main.py",
            "previous_messages": ["Hello"],
        }

        filtered_tools = get_filtered_tools_for_session("session_123", session_state)

        # Should return a list of tools
        assert isinstance(filtered_tools, list)

        # Should have fewer tools than original (filtering should work)
        assert len(filtered_tools) <= len(self.tools)

        # Should include basic tools
        tool_names = [t.name for t in filtered_tools]
        basic_tools = ["read", "write", "edit", "bash", "grep", "glob", "ukb.lookup"]
        for basic_tool in basic_tools:
            assert basic_tool in tool_names

        # Should include Python LSP tools
        python_lsp_tools = [
            "lsp.hover",
            "lsp.definition",
            "lsp.references",
            "lsp.symbol_search",
            "lsp.diagnostics",
            "lsp.code_action",
        ]
        for lsp_tool in python_lsp_tools:
            assert lsp_tool in tool_names

        # Should not include rename (no rename intent)
        assert "lsp.rename" not in tool_names

    @patch("app.core.tools.integration.get_tools")
    def test_get_filtered_tools_for_session_with_rename_intent(self, mock_get_tools):
        """Test getting filtered tools for session with rename intent."""
        mock_get_tools.return_value = self.tools

        session_state = {
            "turn_count": 2,
            "last_message": "rename the User class to Customer",
            "file_path": "src/models.py",
            "intent": "rename",
        }

        filtered_tools = get_filtered_tools_for_session("session_456", session_state)

        tool_names = [t.name for t in filtered_tools]

        # Should include rename tool
        assert "lsp.rename" in tool_names

        # Should not include other LSP tools (only rename intent)
        assert "lsp.hover" not in tool_names
        assert "lsp.definition" not in tool_names

    @patch("app.core.tools.integration.get_tools")
    def test_get_filtered_tools_for_session_with_memory_intent(self, mock_get_tools):
        """Test getting filtered tools for session with memory intent."""
        mock_get_tools.return_value = self.tools

        session_state = {
            "turn_count": 4,
            "last_message": "Помнишь, какие решения мы принимали?",
            "previous_messages": ["We discussed auth", "Let's implement it"],
        }

        filtered_tools = get_filtered_tools_for_session("session_789", session_state)

        tool_names = [t.name for t in filtered_tools]

        # Should include memory search tools
        assert "memory.search" in tool_names
        assert "retrieval_orchestrate" in tool_names

    @patch("app.core.tools.integration.get_tools")
    def test_validate_capability_filtering(self, mock_get_tools):
        """Test capability filtering validation."""
        mock_get_tools.return_value = self.tools

        session_state = {
            "turn_count": 1,
            "last_message": "Hello",
            "file_path": "test.txt",
        }

        validation_result = validate_capability_filtering(session_state)

        # Should return validation results
        assert isinstance(validation_result, dict)
        assert "original_count" in validation_result
        assert "filtered_count" in validation_result
        assert "expected_reduction" in validation_result
        assert "max_tools_limit" in validation_result
        assert "basic_tools_present" in validation_result
        assert "context_relevant_tools" in validation_result
        assert "statistics" in validation_result

        # Should have original count matching our tools
        assert validation_result["original_count"] == len(self.tools)

        # Should enforce max tools limit
        assert validation_result["max_tools_limit"]

        # Should have basic tools present
        assert validation_result["basic_tools_present"]

    @patch("app.core.tools.integration.get_tools")
    def test_validate_capability_filtering_python_context(self, mock_get_tools):
        """Test capability filtering validation with Python context."""
        mock_get_tools.return_value = self.tools

        session_state = {
            "turn_count": 2,
            "last_message": "Help me with Python code",
            "file_path": "src/main.py",
        }

        validation_result = validate_capability_filtering(session_state)

        # Should have context-relevant tools (LSP tools added)
        assert validation_result["context_relevant_tools"]

        # Should have filtered fewer tools (Python context adds LSP tools)
        assert validation_result["filtered_count"] > 6  # Basic tools + some others


class TestContextEnhancement:
    """Test context enhancement functionality."""

    def test_enhance_with_file_analysis(self):
        """Test file content analysis enhancement."""
        from app.core.tools.integration import _enhance_context_with_file_analysis

        context = TurnContext()
        session_state = {
            "file_content": "class User:\n    def authenticate(self):\n        pass\n"
        }

        _enhance_context_with_file_analysis(context, session_state)

        # Should detect code intent
        assert context.intent == "code"

    def test_enhance_with_intent_analysis(self):
        """Test intent analysis enhancement."""
        from app.core.tools.integration import _enhance_context_with_intent_analysis

        context = TurnContext()
        session_state = {"last_message": "rename the function to calculate_total"}

        _enhance_context_with_intent_analysis(context, session_state)

        # Should detect rename intent
        assert context.intent == "rename"

    def test_enhance_with_language_context(self):
        """Test language context enhancement."""
        from app.core.tools.integration import _enhance_context_with_language_context

        context = TurnContext()
        session_state = {
            "file_path": "src/main.py",
            "cursor_position": {"line": 10, "column": 5},
            "files": ["src/main.py", "src/utils.py", "tests/test_main.py"],
        }

        _enhance_context_with_language_context(context, session_state)

        # Should detect Python language
        assert context.language == "python"

        # Should detect symbol at cursor
        assert context.has_symbol_at_cursor

        # Should detect cross-project search (multiple files)
        assert context.cross_project_search


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
