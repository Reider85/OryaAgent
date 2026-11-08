"""Tests for oriahs_index tool (B-03)."""

import json
import os
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.tools import ToolException

from app.tools.oriahs_index import (
    oriahs_index,
    _get_git_ignored_files,
    _should_index_file,
)


class MockPath:
    """Mock Path class for testing."""

    def __init__(self, path_str):
        self.path_str = path_str
        self._exists = False
        self._is_file = False
        self._is_dir = False

    def exists(self):
        return self._exists

    def is_file(self):
        return self._is_file

    def is_dir(self):
        return self._is_dir

    def rglob(self, pattern):
        """Mock rglob method."""
        return []

    def iterdir(self):
        """Mock iterdir method."""
        return []


class TestOriahsIndex:
    """Test cases for oriahs_index tool."""

    def test_get_git_ignored_files(self):
        """Test git ignored files detection."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)

            # Create a mock git repository
            gitignore_path = temp_path / ".gitignore"
            gitignore_path.write_text("*.log\n__pycache__/\n")

            # Mock subprocess to simulate git status
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(
                    returncode=0, stdout="!! test.log\n!! __pycache__/\n"
                )

                ignored = _get_git_ignored_files(temp_path)
                assert "test.log" in ignored
                assert "__pycache__/" in ignored

    def test_get_git_ignored_files_error(self):
        """Test error handling in git ignored files detection."""
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.CalledProcessError(1, "git")

            ignored = _get_git_ignored_files(Path("/nonexistent"))
            assert ignored == set()

    def test_should_index_file(self):
        """Test file indexing decision."""
        # Test valid file
        valid_file = Path("test.py")
        ignored_files = set()
        assert _should_index_file(valid_file, ignored_files) is True

        # Test ignored file
        ignored_file = Path("test.log")
        ignored_files = {"test.log"}
        assert _should_index_file(ignored_file, ignored_files) is False

        # Test invalid extension
        invalid_file = Path("test.xyz")
        assert _should_index_file(invalid_file, ignored_files) is False

    @pytest.mark.asyncio
    async def test_index_file_success(self):
        """Test successful file indexing."""
        with patch("app.tools.oriahs_index.get_mcp_client") as mock_get_client:
            mock_client = AsyncMock()
            mock_get_client.return_value = mock_client

            # Mock successful MCP response
            mock_client.call_tool.return_value = [
                {"path": "test.py", "status": "success", "message": "File indexed"}
            ]

            with patch("app.tools.oriahs_index.validate_path") as mock_validate:
                mock_path = MockPath("/test.py")
                mock_path._exists = True
                mock_path._is_file = True
                mock_validate.return_value = mock_path

                result = await oriahs_index.ainvoke({"path": "/test.py"})
                assert "test.py" in result
                assert "✅" in result
                assert "success" in result

    @pytest.mark.asyncio
    async def test_index_directory_success(self):
        """Test successful directory indexing."""
        with patch("app.tools.oriahs_index.get_mcp_client") as mock_get_client:
            mock_client = AsyncMock()
            mock_get_client.return_value = mock_client

            # Mock successful MCP response
            mock_client.call_tool.return_value = [
                {"path": "test.py", "status": "success", "message": "File indexed"}
            ]

            with patch("app.tools.oriahs_index.validate_path") as mock_validate:
                mock_path = MockPath("/test_dir")
                mock_path._exists = True
                mock_path._is_dir = True
                mock_validate.return_value = mock_path

                with patch(
                    "app.tools.oriahs_index._get_git_ignored_files"
                ) as mock_ignored:
                    mock_ignored.return_value = set()

                    with patch(
                        "app.tools.oriahs_index._should_index_file"
                    ) as mock_should_index:
                        mock_should_index.return_value = True

                        # Create a mock file that will be found by rglob
                        mock_file = MockPath("test.py")
                        mock_file._exists = True
                        mock_file._is_file = True

                        # Mock the rglob method to return our mock file
                        def mock_rglob(pattern):
                            return [mock_file]

                        mock_path.rglob = mock_rglob

                        result = await oriahs_index.ainvoke(
                            {"path": "/test_dir", "recursive": True}
                        )
                        assert "test.py" in result
                        assert "✅" in result

    @pytest.mark.asyncio
    async def test_index_empty_path(self):
        """Test empty path handling."""
        with pytest.raises(ToolException, match="Path cannot be empty"):
            await oriahs_index.ainvoke({"path": ""})

    @pytest.mark.asyncio
    async def test_index_invalid_path(self):
        """Test invalid path handling."""
        with patch("app.tools.oriahs_index.validate_path") as mock_validate:
            mock_validate.side_effect = ToolException("Invalid path")

            with pytest.raises(ToolException, match="Invalid path"):
                await oriahs_index.ainvoke({"path": "/nonexistent"})

    @pytest.mark.asyncio
    async def test_index_mcp_server_unavailable(self):
        """Test MCP server unavailable handling."""
        with patch("app.tools.oriahs_index.get_mcp_client") as mock_get_client:
            mock_client = AsyncMock()
            mock_client.health_check.return_value = False
            mock_get_client.return_value = mock_client

            with patch("app.tools.oriahs_index.validate_path") as mock_validate:
                mock_path = MockPath("/test.py")
                mock_path._exists = True
                mock_path._is_file = True
                mock_validate.return_value = mock_path

                with pytest.raises(
                    ToolException, match="OriaHS MCP server is not available"
                ):
                    await oriahs_index.ainvoke({"path": "/test.py"})

    @pytest.mark.asyncio
    async def test_index_caching(self):
        """Test caching functionality."""
        with patch("app.tools.oriahs_index.get_cache") as mock_cache:
            mock_cache_instance = AsyncMock()
            mock_cache_instance.get.return_value = json.dumps({"cached": "result"})
            mock_cache.return_value = mock_cache_instance

            with patch("app.tools.oriahs_index.validate_path") as mock_validate:
                mock_path = MockPath("/test.py")
                mock_path._exists = True
                mock_path._is_file = True
                mock_validate.return_value = mock_path

                result = await oriahs_index.ainvoke({"path": "/test.py"})
                assert "cached" in result
                # Verify cache was called
                mock_cache_instance.get.assert_called_once()

    def test_format_indexing_results(self):
        """Test formatting of indexing results."""
        from app.tools.oriahs_index import _format_indexing_results

        results = [
            {"path": "test.py", "status": "success", "message": "File indexed"},
            {"path": "test.log", "status": "error", "message": "Failed to index"},
        ]

        formatted = _format_indexing_results(results)
        assert "test.py" in formatted
        assert "test.log" in formatted
        assert "✅" in formatted
        assert "❌" in formatted
