"""Unit tests for oriahs_search tool (P-01)."""

import os
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.config import clear_settings_cache
from app.core.oriahs_client import ORIAHS_FALLBACK_MESSAGE
from app.mcp.client import MCPClient, MCPClientConfig
from app.tools.oriahs_search import _format_search_results, oriahs_search

_LEGACY_ENV = (
    "ORIAHS_URL",
    "ORIAHS_TIMEOUT_S",
    "ORIAHS_SEARCH_DEFAULT_TOP_K",
    "ORIAHS_SEARCH_MAX_RESULTS",
    "ORIAHS_SEARCH_CACHE_TTL",
    "MCP_SERVER_URL",
)


@pytest.fixture(autouse=True)
def isolated_oriahs_config(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Sandbox settings: repo .env / host env must not leak into P-01 tests."""
    for name in list(os.environ):
        if name.startswith("ORYA_") or name in _LEGACY_ENV:
            monkeypatch.delenv(name, raising=False)
    monkeypatch.chdir(tmp_path)
    clear_settings_cache()
    yield
    clear_settings_cache()


class TestOriaHS:
    """Test cases for oriahs_search tool."""

    @pytest.mark.asyncio
    async def test_semantic_search_success(self):
        """Test successful semantic search through MCP."""
        # Mock MCP client
        mock_client = AsyncMock()
        mock_client.health_check.return_value = True
        mock_client.call_tool.return_value = [
            {
                "score": 0.95,
                "path": "app/main.py",
                "content": "def main():",
                "type": "function",
            },
            {
                "score": 0.87,
                "path": "app/core/utils.py",
                "content": "def helper():",
                "type": "function",
            },
        ]

        with patch("app.tools.oriahs_search.get_mcp_client", return_value=mock_client):
            result = await oriahs_search.ainvoke({"query": "main function"})

            assert "score 0.950" in result
            assert "app/main.py" in result
            assert "app/core/utils.py" in result
            assert "function" in result

            # Verify MCP client was called correctly
            mock_client.health_check.assert_called_once()
            mock_client.call_tool.assert_called_once_with(
                "hybrid_search",
                {
                    "query": "main function",
                    "top_k": 20,
                    "filters": {},
                    "rerank": True,
                    "fusion": "rrf",
                    "explain": False,
                },
            )

    @pytest.mark.asyncio
    async def test_semantic_search_with_custom_top_k(self):
        """Test semantic search with custom top_k parameter."""
        mock_client = AsyncMock()
        mock_client.health_check.return_value = True
        mock_client.call_tool.return_value = [
            {
                "score": 0.95,
                "path": "app/main.py",
                "content": "def main():",
                "type": "function",
            }
        ]

        with patch("app.tools.oriahs_search.get_mcp_client", return_value=mock_client):
            await oriahs_search.ainvoke({"query": "test", "top_k": 5})

            # Verify top_k was passed correctly
            mock_client.call_tool.assert_called_once_with(
                "hybrid_search",
                {
                    "query": "test",
                    "top_k": 5,
                    "filters": {},
                    "rerank": True,
                    "fusion": "rrf",
                    "explain": False,
                },
            )

    @pytest.mark.asyncio
    async def test_semantic_search_with_filters(self):
        """Test semantic search with filters."""
        mock_client = AsyncMock()
        mock_client.health_check.return_value = True
        mock_client.call_tool.return_value = []

        filters = {"file_type": "python", "date_range": "2024"}

        with patch("app.tools.oriahs_search.get_mcp_client", return_value=mock_client):
            await oriahs_search.ainvoke({"query": "test", "filters": filters})

            # Verify filters were passed correctly
            mock_client.call_tool.assert_called_once_with(
                "hybrid_search",
                {
                    "query": "test",
                    "top_k": 20,
                    "filters": filters,
                    "rerank": True,
                    "fusion": "rrf",
                    "explain": False,
                },
            )

    @pytest.mark.asyncio
    async def test_mcp_server_unavailable(self):
        """P-00: an unreachable MCP server returns the exact fallback string."""
        mock_client = AsyncMock()
        mock_client.health_check.return_value = False

        with patch("app.tools.oriahs_search.get_mcp_client", return_value=mock_client):
            result = await oriahs_search.ainvoke({"query": "test"})

        assert result == "service unavailable, use grep"

    @pytest.mark.asyncio
    async def test_mcp_server_error(self):
        """P-00: transport failures degrade to the same fallback string."""
        mock_client = AsyncMock()
        mock_client.health_check.return_value = True
        mock_client.call_tool.side_effect = Exception("Connection failed")

        with patch("app.tools.oriahs_search.get_mcp_client", return_value=mock_client):
            result = await oriahs_search.ainvoke({"query": "test"})

        assert result == "service unavailable, use grep"

    @pytest.mark.asyncio
    async def test_cache_hit(self):
        """Test caching behavior for repeated queries."""
        # Mock cache
        mock_cache = AsyncMock()
        mock_cache.get.return_value = "cached result"

        with patch("app.tools.oriahs_search.get_cache", return_value=mock_cache):
            with patch("app.tools.oriahs_search.get_mcp_client") as mock_get_client:
                result = await oriahs_search.ainvoke({"query": "test"})

                # Should return cached result without calling MCP
                assert result == "cached result"
                mock_get_client.assert_not_called()
                mock_cache.get.assert_called_once()

    @pytest.mark.asyncio
    async def test_empty_query(self):
        """Test error handling for empty query."""
        with pytest.raises(Exception, match="Query cannot be empty"):
            await oriahs_search.ainvoke({"query": ""})

    @pytest.mark.asyncio
    async def test_invalid_top_k(self):
        """Test error handling for invalid top_k values."""
        with pytest.raises(Exception, match="top_k must be between 1 and 100"):
            await oriahs_search.ainvoke({"query": "test", "top_k": 0})

        with pytest.raises(Exception, match="top_k must be between 1 and 100"):
            await oriahs_search.ainvoke({"query": "test", "top_k": 101})

    @pytest.mark.asyncio
    async def test_result_parsing_json_strings(self):
        """Test parsing JSON string results from MCP."""
        mock_client = AsyncMock()
        mock_client.health_check.return_value = True
        mock_client.call_tool.return_value = [
            '{"score": 0.95, "path": "app/main.py", "content": "def main():", "type": "function"}',
            '{"score": 0.87, "path": "app/utils.py", "content": "def helper():", "type": "function"}',
        ]

        with patch("app.tools.oriahs_search.get_mcp_client", return_value=mock_client):
            result = await oriahs_search.ainvoke({"query": "test"})

            assert "score 0.950" in result
            assert "app/main.py" in result
            assert "app/utils.py" in result

    @pytest.mark.asyncio
    async def test_result_parsing_invalid_json(self):
        """Test handling of invalid JSON in results."""
        mock_client = AsyncMock()
        mock_client.health_check.return_value = True
        mock_client.call_tool.return_value = [
            '{"score": 0.95, "path": "app/main.py", "content": "def main():", "type": "function"}',
            "invalid json string",
            {
                "score": 0.87,
                "path": "app/utils.py",
                "content": "def helper():",
                "type": "function",
            },
        ]

        with patch("app.tools.oriahs_search.get_mcp_client", return_value=mock_client):
            result = await oriahs_search.ainvoke({"query": "test"})

            # Should still work with valid results, ignoring invalid ones
            assert "score 0.950" in result
            assert "app/main.py" in result
            assert "score 0.870" in result
            assert "app/utils.py" in result


class TestFormatSearchResults:
    """Test cases for _format_search_results function."""

    def test_empty_results(self):
        """Test formatting empty results."""
        result = _format_search_results([])
        assert result == "No results found."

    def test_single_result(self):
        """Test formatting single result."""
        results = [
            {
                "score": 0.95,
                "path": "app/main.py",
                "content": "def main(): pass",
                "type": "function",
            }
        ]
        result = _format_search_results(results)

        assert "1. app/main.py (score 0.950, type function)" in result
        assert "def main(): pass" in result

    def test_multiple_results(self):
        """Test formatting multiple results."""
        results = [
            {
                "score": 0.95,
                "path": "app/main.py",
                "content": "def main(): pass",
                "type": "function",
            },
            {
                "score": 0.87,
                "path": "app/utils.py",
                "content": "def helper(): pass",
                "type": "function",
            },
        ]
        result = _format_search_results(results)

        assert "1. app/main.py (score 0.950, type function)" in result
        assert "2. app/utils.py (score 0.870, type function)" in result

    def test_content_truncation(self):
        """Test that long content is truncated."""
        long_content = "a" * 1000
        results = [
            {
                "score": 0.95,
                "path": "app/main.py",
                "content": long_content,
                "type": "function",
            }
        ]
        result = _format_search_results(results)

        # Content should be truncated to 500 chars
        assert len(result) < len(long_content) + 100  # Allow some overhead
        assert long_content[:500] in result
        assert "..." in result


class TestMCPClient:
    """Test cases for MCP client."""

    @pytest.mark.asyncio
    async def test_health_check_success(self):
        """Test successful health check."""
        config = MCPClientConfig(server_url="http://test.com")
        client = MCPClient(config)

        # Mock successful response
        with patch.object(client._http_client, "get") as mock_get:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_get.return_value = mock_response

            result = await client.health_check()
            assert result is True
            mock_get.assert_called_once_with("/health")

    @pytest.mark.asyncio
    async def test_health_check_failure(self):
        """Test failed health check."""
        config = MCPClientConfig(server_url="http://test.com")
        client = MCPClient(config)

        # Mock failed response
        with patch.object(client._http_client, "get") as mock_get:
            mock_get.side_effect = Exception("Connection failed")

            result = await client.health_check()
            assert result is False

    @pytest.mark.asyncio
    async def test_call_tool_success(self):
        """Test successful tool call."""
        config = MCPClientConfig(server_url="http://test.com")
        client = MCPClient(config)

        with patch.object(client._http_client, "post") as mock_post:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {"content": [{"test": "data"}]}
            mock_post.return_value = mock_response

            result = await client.call_tool("test_tool", {"param": "value"})

            assert result == [{"test": "data"}]
            mock_post.assert_called_once_with(
                "/call", json={"name": "test_tool", "arguments": {"param": "value"}}
            )

    @pytest.mark.asyncio
    async def test_call_tool_error(self):
        """Test tool call error handling."""
        config = MCPClientConfig(server_url="http://test.com")
        client = MCPClient(config)

        with patch.object(client._http_client, "post") as mock_post:
            mock_post.side_effect = Exception("API Error")

            with pytest.raises(Exception, match="API Error"):
                await client.call_tool("test_tool", {"param": "value"})


class TestP01Contract:
    """P-01 contract: forwarded knobs, file:line output, kill-switch."""

    @pytest.mark.asyncio
    async def test_custom_contract_params_are_forwarded(self):
        mock_client = AsyncMock()
        mock_client.health_check.return_value = True
        mock_client.call_tool.return_value = []

        with patch("app.tools.oriahs_search.get_mcp_client", return_value=mock_client):
            await oriahs_search.ainvoke(
                {
                    "query": "test",
                    "top_k": 7,
                    "rerank": False,
                    "fusion": "weighted",
                    "explain": True,
                }
            )

        args = mock_client.call_tool.call_args.args[1]
        assert args == {
            "query": "test",
            "top_k": 7,
            "filters": {},
            "rerank": False,
            "fusion": "weighted",
            "explain": True,
        }

    @pytest.mark.asyncio
    async def test_invalid_fusion_is_rejected(self):
        with pytest.raises(Exception, match="fusion must be 'rrf' or 'weighted'"):
            await oriahs_search.ainvoke({"query": "test", "fusion": "bm25"})

    @pytest.mark.asyncio
    async def test_kill_switch_degrades_without_mcp_call(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setenv("ORYA_ORIAHS_SEARCH_ENABLED", "false")
        clear_settings_cache()
        mock_client = AsyncMock()

        with patch("app.tools.oriahs_search.get_mcp_client", return_value=mock_client):
            result = await oriahs_search.ainvoke({"query": "test"})

        assert result == ORIAHS_FALLBACK_MESSAGE
        mock_client.health_check.assert_not_awaited()
        mock_client.call_tool.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_cache_ttl_comes_from_settings(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("ORYA_ORIAHS_SEARCH_CACHE_TTL_S", "17")
        clear_settings_cache()
        mock_client = AsyncMock()
        mock_client.health_check.return_value = True
        mock_client.call_tool.return_value = [
            {"score": 0.9, "path": "a.py", "line": 3, "content": "x", "type": "py"}
        ]
        mock_cache = AsyncMock()
        mock_cache.get.return_value = None

        with (
            patch("app.tools.oriahs_search.get_mcp_client", return_value=mock_client),
            patch("app.tools.oriahs_search.get_cache", return_value=mock_cache),
        ):
            result = await oriahs_search.ainvoke({"query": "test"})

        assert "a.py:3" in result
        assert mock_cache.set.call_args.kwargs["ttl"] == 17

    def test_format_includes_file_and_line(self):
        result = _format_search_results(
            [{"score": 0.9, "path": "a.py", "line": 12, "content": "x", "type": "py"}]
        )
        assert result.startswith("1. a.py:12 (score 0.900, type py)")
