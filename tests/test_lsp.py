"""Tests for LSP components."""

import pytest
import asyncio
from unittest.mock import Mock, AsyncMock, patch, MagicMock
from pathlib import Path

from app.core.lsp.bus import LSPBus, LSPServerConfig, LSPClient
from app.core.lsp.watcher import LSPFileWatcher, FileChangeEvent
from app.core.lsp.tools import (
    lsp_hover,
    lsp_definition,
    lsp_references,
    lsp_symbol_search,
    lsp_rename,
    lsp_diagnostics,
    lsp_code_action,
)
from app.core.lsp.tools import LSPToolException


class TestLSPServerConfig:
    """Test LSP server configuration."""

    def test_config_creation(self):
        """Test configuration creation."""
        config = LSPServerConfig(
            language="python",
            command=["pyright-langserver", "--stdio"],
            file_extensions=[".py"],
        )

        assert config.language == "python"
        assert config.command == ["pyright-langserver", "--stdio"]
        assert config.file_extensions == [".py"]
        assert config.timeout == 30
        assert config.max_restarts == 3

    def test_get_command_with_args(self):
        """Test command with arguments."""
        config = LSPServerConfig(
            language="python",
            command=["pyright-langserver", "--stdio"],
            file_extensions=[".py"],
        )

        workspace = Path("/tmp/workspace")
        cmd = config.get_command_with_args(workspace)

        assert cmd == ["pyright-langserver", "--stdio"]

    def test_get_command_with_args_java(self):
        """Test Java command with arguments."""
        config = LSPServerConfig(
            language="java",
            command=["jdtls"],
            file_extensions=[".java"],
        )

        workspace = Path("/tmp/workspace")
        cmd = config.get_command_with_args(workspace)

        assert "-data" in cmd
        assert str(workspace / ".jdtls") in cmd


class TestLSPClient:
    """Test LSP client functionality."""

    def test_client_creation(self):
        """Test client creation."""
        config = LSPServerConfig(
            language="python",
            command=["pyright-langserver", "--stdio"],
            file_extensions=[".py"],
        )

        client = LSPClient(config)

        assert client.config == config
        assert client.request_id == 0
        assert client.pending_requests == {}
        assert client.is_running is False
        assert client.restart_count == 0

    @pytest.mark.asyncio
    async def test_client_start_stop(self):
        """Test client start and stop."""
        config = LSPServerConfig(
            language="python",
            command=["echo"],  # Simple command for testing
            file_extensions=[".py"],
        )

        client = LSPClient(config)
        workspace = Path("/tmp")

        # Mock subprocess
        with patch("asyncio.create_subprocess_exec") as mock_create:
            mock_process = Mock()
            mock_process.stdout = AsyncMock()
            mock_process.stdin = AsyncMock()
            mock_process.wait = AsyncMock()
            mock_create.return_value = mock_process

            # Mock initialize
            with patch.object(client, "_initialize") as mock_init:
                mock_init.return_value = {}

                # Start client
                await client.start(workspace)

                # Check that process was started
                mock_create.assert_called_once()
                assert client.is_running is True

                # Stop client
                await client.stop()

                # Check that process was stopped
                mock_process.terminate.assert_called_once()
                assert client.is_running is False

    @pytest.mark.asyncio
    async def test_client_restart(self):
        """Test client restart."""
        config = LSPServerConfig(
            language="python",
            command=["echo"],
            file_extensions=[".py"],
            max_restarts=2,
        )

        client = LSPClient(config)
        workspace = Path("/tmp")

        # Mock successful restart
        with (
            patch.object(client, "stop") as mock_stop,
            patch.object(client, "start") as mock_start,
        ):
            mock_stop.return_value = None
            mock_start.return_value = None

            result = await client.restart(workspace)

            assert result is True
            assert client.restart_count == 1
            mock_stop.assert_called_once()
            mock_start.assert_called_once()

    @pytest.mark.asyncio
    async def test_client_restart_max_restarts(self):
        """Test client restart with max restarts exceeded."""
        config = LSPServerConfig(
            language="python",
            command=["echo"],
            file_extensions=[".py"],
            max_restarts=1,
        )

        client = LSPClient(config)
        client.restart_count = 1  # Already at max
        workspace = Path("/tmp")

        result = await client.restart(workspace)

        assert result is False
        assert client.restart_count == 1  # Should not increment


class TestLSPBus:
    """Test LSP bus functionality."""

    def test_bus_creation(self):
        """Test bus creation."""
        bus = LSPBus()

        assert len(bus.server_configs) == 6  # 6 supported languages
        assert "python" in bus.server_configs
        assert "typescript" in bus.server_configs
        assert "rust" in bus.server_configs
        assert "go" in bus.server_configs
        assert "java" in bus.server_configs
        assert "lua" in bus.server_configs

    def test_detect_language(self):
        """Test language detection."""
        bus = LSPBus()

        assert bus.detect_language(Path("test.py")) == "python"
        assert bus.detect_language(Path("test.ts")) == "typescript"
        assert bus.detect_language(Path("test.rs")) == "rust"
        assert bus.detect_language(Path("test.go")) == "go"
        assert bus.detect_language(Path("test.java")) == "java"
        assert bus.detect_language(Path("test.lua")) == "lua"
        assert bus.detect_language(Path("test.txt")) is None

    def test_get_supported_languages(self):
        """Test getting supported languages."""
        bus = LSPBus()

        languages = bus.get_supported_languages()

        assert len(languages) == 6
        assert "python" in languages
        assert "typescript" in languages
        assert "rust" in languages
        assert "go" in languages
        assert "java" in languages
        assert "lua" in languages

    def test_get_file_extensions(self):
        """Test getting file extensions."""
        bus = LSPBus()

        assert bus.get_file_extensions("python") == [".py"]
        assert bus.get_file_extensions("typescript") == [".ts", ".tsx", ".js", ".jsx"]
        assert bus.get_file_extensions("rust") == [".rs"]
        assert bus.get_file_extensions("go") == [".go"]
        assert bus.get_file_extensions("java") == [".java"]
        assert bus.get_file_extensions("lua") == [".lua"]
        assert bus.get_file_extensions("unknown") == []

    @pytest.mark.asyncio
    async def test_bus_start_stop(self):
        """Test bus start and stop."""
        bus = LSPBus()

        # Mock server
        mock_server = Mock()
        mock_server.is_running = False
        mock_server.stop = AsyncMock()

        with patch.object(bus, "ensure_server") as mock_ensure:
            mock_ensure.return_value = mock_server

            # Start bus
            await bus.start()

            assert bus.is_running is True

            # Stop bus
            await bus.stop()

            assert bus.is_running is False
            mock_server.stop.assert_called_once()


class TestLSPFileWatcher:
    """Test LSP file watcher functionality."""

    def test_watcher_creation(self):
        """Test watcher creation."""
        watcher = LSPFileWatcher(workspace="/tmp")

        assert watcher.workspace_path == Path("/tmp").resolve()
        assert watcher.debounce_interval == 0.1
        assert watcher.max_file_size == 1024 * 1024
        assert len(watcher.watched_files) == 0
        assert len(watcher.file_events) == 0
        assert watcher.is_running is False

    def test_file_event_creation(self):
        """Test file event creation."""
        event = FileChangeEvent(Path("test.py"), "create", "# content")

        assert event.file_path == Path("test.py")
        assert event.change_type == "create"
        assert event.content == "# content"
        assert event.timestamp is not None

    @pytest.mark.asyncio
    async def test_watcher_start_stop(self):
        """Test watcher start and stop."""
        watcher = LSPFileWatcher()

        # Mock watch task
        with patch.object(watcher, "_watch_loop") as mock_watch:
            mock_watch.return_value = None

            # Start watcher
            await watcher.start()

            assert watcher.is_running is True
            mock_watch.assert_called_once()

            # Stop watcher
            await watcher.stop()

            assert watcher.is_running is False

    @pytest.mark.asyncio
    async def test_add_file(self):
        """Test adding file to watcher."""
        watcher = LSPFileWatcher()

        # Mock handle file event
        with patch.object(watcher, "_handle_file_event") as mock_handle:
            mock_handle.return_value = None

            # Add file
            await watcher.add_file("test.py", "# content")

            assert len(watcher.watched_files) == 1
            assert Path("test.py") in watcher.watched_files
            mock_handle.assert_called_once()

    @pytest.mark.asyncio
    async def test_modify_file(self):
        """Test modifying file."""
        watcher = LSPFileWatcher()

        # Add file first
        await watcher.add_file("test.py", "# content")

        # Mock debounce task
        with patch("asyncio.create_task") as mock_create_task:
            mock_task = Mock()
            mock_create_task.return_value = mock_task

            # Modify file
            await watcher.modify_file("test.py", "# new content")

            assert len(watcher._debounce_tasks) == 1
            mock_create_task.assert_called_once()

    @pytest.mark.asyncio
    async def test_delete_file(self):
        """Test deleting file."""
        watcher = LSPFileWatcher()

        # Add file first
        await watcher.add_file("test.py", "# content")

        # Mock handle file event
        with patch.object(watcher, "_handle_file_event") as mock_handle:
            mock_handle.return_value = None

            # Delete file
            await watcher.delete_file("test.py")

            assert len(watcher.watched_files) == 0
            mock_handle.assert_called_once()

    def test_detect_language(self):
        """Test language detection in watcher."""
        watcher = LSPFileWatcher()

        # Mock LSP bus
        with patch("app.core.lsp.bus.get_lsp_bus") as mock_get_bus:
            mock_bus = Mock()
            mock_bus.detect_language.return_value = "python"
            mock_get_bus.return_value = mock_bus

            language = watcher._detect_language(Path("test.py"))

            assert language == "python"
            mock_bus.detect_language.assert_called_once_with(Path("test.py"))


class TestLSPTools:
    """Test LSP tools functionality."""

    @pytest.mark.asyncio
    async def test_lsp_hover_success(self):
        """Test successful lsp_hover call."""
        # Mock LSP bus
        with patch("app.core.lsp.tools.get_lsp_bus") as mock_get_bus:
            mock_bus = Mock()
            mock_server = Mock()
            mock_server.hover.return_value = {"contents": "test hover"}
            mock_bus.ensure_server.return_value = mock_server
            mock_bus.detect_language.return_value = "python"
            mock_get_bus.return_value = mock_bus

            # Call tool
            result = await lsp_hover("test.py", 10, 20, "/workspace")

            assert result["success"] is True
            assert result["language"] == "python"
            assert result["hover"] == {"contents": "test hover"}
            assert result["position"] == {"line": 10, "column": 20}

    @pytest.mark.asyncio
    async def test_lsp_hover_failure(self):
        """Test failed lsp_hover call."""
        # Mock LSP bus
        with patch("app.core.lsp.tools.get_lsp_bus") as mock_get_bus:
            mock_bus = Mock()
            mock_bus.detect_language.return_value = None
            mock_get_bus.return_value = mock_bus

            # Call tool
            with pytest.raises(LSPToolException, match="Unsupported file type"):
                await lsp_hover("test.txt", 10, 20, "/workspace")

    @pytest.mark.asyncio
    async def test_lsp_definition_success(self):
        """Test successful lsp_definition call."""
        # Mock LSP bus
        with patch("app.core.lsp.tools.get_lsp_bus") as mock_get_bus:
            mock_bus = Mock()
            mock_server = Mock()
            mock_server.definition.return_value = [{"uri": "test.py", "range": {}}]
            mock_bus.ensure_server.return_value = mock_server
            mock_bus.detect_language.return_value = "python"
            mock_get_bus.return_value = mock_bus

            # Call tool
            result = await lsp_definition("test.py", 10, 20, "/workspace")

            assert result["success"] is True
            assert result["language"] == "python"
            assert result["definition"] == [{"uri": "test.py", "range": {}}]

    @pytest.mark.asyncio
    async def test_lsp_references_success(self):
        """Test successful lsp_references call."""
        # Mock LSP bus
        with patch("app.core.lsp.tools.get_lsp_bus") as mock_get_bus:
            mock_bus = Mock()
            mock_server = Mock()
            mock_server.references.return_value = [{"uri": "test.py", "range": {}}]
            mock_bus.ensure_server.return_value = mock_server
            mock_bus.detect_language.return_value = "python"
            mock_get_bus.return_value = mock_bus

            # Call tool
            result = await lsp_references("test.py", 10, 20, True, "/workspace")

            assert result["success"] is True
            assert result["language"] == "python"
            assert result["references"] == [{"uri": "test.py", "range": {}}]

    @pytest.mark.asyncio
    async def test_lsp_symbol_search_success(self):
        """Test successful lsp_symbol_search call."""
        # Mock LSP bus
        with patch("app.core.lsp.tools.get_lsp_bus") as mock_get_bus:
            mock_bus = Mock()
            mock_server = Mock()
            mock_server.symbol_search.return_value = [
                {"name": "test", "kind": "function"}
            ]
            mock_bus.ensure_server.return_value = mock_server
            mock_bus.get_supported_languages.return_value = ["python"]
            mock_get_bus.return_value = mock_bus

            # Call tool
            result = await lsp_symbol_search("test", "/workspace")

            assert result["success"] is True
            assert result["query"] == "test"
            assert len(result["symbols"]) == 1
            assert result["symbols"][0]["name"] == "test"

    @pytest.mark.asyncio
    async def test_lsp_rename_success(self):
        """Test successful lsp_rename call."""
        # Mock LSP bus
        with patch("app.core.lsp.tools.get_lsp_bus") as mock_get_bus:
            mock_bus = Mock()
            mock_server = Mock()
            mock_server.rename.return_value = {"changes": [{"newName": "new_name"}]}
            mock_bus.ensure_server.return_value = mock_server
            mock_bus.detect_language.return_value = "python"
            mock_get_bus.return_value = mock_bus

            # Call tool
            result = await lsp_rename("test.py", 10, 20, "new_name", "/workspace")

            assert result["success"] is True
            assert result["language"] == "python"
            assert result["new_name"] == "new_name"
            assert result["old_name"] == "new_name"  # From result

    @pytest.mark.asyncio
    async def test_lsp_diagnostics_success(self):
        """Test successful lsp_diagnostics call."""
        # Mock LSP bus
        with patch("app.core.lsp.tools.get_lsp_bus") as mock_get_bus:
            mock_bus = Mock()
            mock_server = Mock()
            mock_server.diagnostics.return_value = [
                {"severity": 1, "message": "Error"},
                {"severity": 2, "message": "Warning"},
            ]
            mock_bus.ensure_server.return_value = mock_server
            mock_bus.detect_language.return_value = "python"
            mock_get_bus.return_value = mock_bus

            # Call tool
            result = await lsp_diagnostics("test.py", "/workspace")

            assert result["success"] is True
            assert result["language"] == "python"
            assert result["error_count"] == 1
            assert result["warning_count"] == 1
            assert result["info_count"] == 0

    @pytest.mark.asyncio
    async def test_lsp_code_action_success(self):
        """Test successful lsp_code_action call."""
        # Mock LSP bus
        with patch("app.core.lsp.tools.get_lsp_bus") as mock_get_bus:
            mock_bus = Mock()
            mock_server = Mock()
            mock_server.code_action.return_value = [
                {"title": "Fix this", "kind": "quickfix"}
            ]
            mock_bus.ensure_server.return_value = mock_server
            mock_bus.detect_language.return_value = "python"
            mock_get_bus.return_value = mock_bus

            # Call tool
            result = await lsp_code_action("test.py", 10, 20, "/workspace")

            assert result["success"] is True
            assert result["language"] == "python"
            assert result["action_count"] == 1
            assert result["code_actions"] == [{"title": "Fix this", "kind": "quickfix"}]


class TestLSPMCP:
    """Test LSP MCP server functionality."""

    def test_mcp_server_creation(self):
        """Test MCP server creation."""
        from app.core.mcp.lsp_mcp import LSPMCPServer

        server = LSPMCPServer()

        assert server.name == "lsp-mcp"
        assert server.version == "1.0.0"
        assert len(server.tools) == 7
        assert server.initialized is False

    @pytest.mark.asyncio
    async def test_mcp_server_initialize(self):
        """Test MCP server initialization."""
        from app.core.mcp.lsp_mcp import LSPMCPServer

        server = LSPMCPServer()

        await server.initialize()

        assert server.initialized is True

    @pytest.mark.asyncio
    async def test_mcp_server_list_tools(self):
        """Test MCP server list tools."""
        from app.core.mcp.lsp_mcp import LSPMCPServer

        server = LSPMCPServer()
        await server.initialize()

        tools = await server.list_tools()

        assert len(tools) == 7
        tool_names = [tool["name"] for tool in tools]
        assert "lsp.hover" in tool_names
        assert "lsp.def" in tool_names
        assert "lsp.refs" in tool_names
        assert "lsp.symbol_search" in tool_names
        assert "lsp.rename" in tool_names
        assert "lsp.diagnostics" in tool_names
        assert "lsp.codeAction" in tool_names

    @pytest.mark.asyncio
    async def test_mcp_server_call_tool(self):
        """Test MCP server call tool."""
        from app.core.mcp.lsp_mcp import LSPMCPServer

        server = LSPMCPServer()
        await server.initialize()

        # Mock successful tool call
        with patch("app.core.mcp.lsp_mcp.lsp_hover") as mock_hover:
            mock_hover.return_value = {"success": True, "result": "test"}

            result = await server.call_tool(
                "lsp.hover",
                {
                    "file_path": "test.py",
                    "line": 10,
                    "column": 20,
                    "workspace": "/workspace",
                },
            )

            assert result["result"]["success"] is True
            assert result["result"]["result"] == "test"
            assert result["metadata"]["tool"] == "lsp.hover"
            assert result["metadata"]["success"] is True

    @pytest.mark.asyncio
    async def test_mcp_server_health_check(self):
        """Test MCP server health check."""
        from app.core.mcp.lsp_mcp import LSPMCPServer

        server = LSPMCPServer()

        # Mock LSP bus
        with patch("app.core.mcp.lsp_mcp.get_lsp_bus") as mock_get_bus:
            mock_bus = Mock()
            mock_bus.get_supported_languages.return_value = ["python", "typescript"]
            mock_get_bus.return_value = mock_bus

            health = await server.health_check()

            assert "status" in health
            assert "supported_languages" in health
            assert "running_servers" in health
            assert "total_tools" in health
