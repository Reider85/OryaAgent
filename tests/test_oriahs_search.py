"""Unit tests for oriahs_search tool (B-02)."""

from unittest.mock import AsyncMock, patch

import pytest

from app.mcp.client import MCPClient, MCPClientConfig
from app.tools.oriahs_search import _format_search_results, oriahs_search


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

            assert "Score: 0.950" in result
            assert "app/main.py" in result
            assert "app/core/utils.py" in result
            assert "function" in result

            # Verify MCP client was called correctly
            mock_client.health_check.assert_called_once()
            mock_client.call_tool.assert_called_once_with(
                "hybrid_search", {"query": "main function", "top_k": 10, "filters": {}}
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
                "hybrid_search", {"query": "test", "top_k": 5, "filters": {}}
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
                "hybrid_search", {"query": "test", "top_k": 10, "filters": filters}
            )

    @pytest.mark.asyncio
    async def test_mcp_server_unavailable(self):
        """Test graceful degradation when MCP server is unavailable."""
        mock_client = AsyncMock()
        mock_client.health_check.return_value = False

        with patch("app.tools.oriahs_search.get_mcp_client", return_value=mock_client):
            with pytest.raises(Exception, match="not available"):
                await oriahs_search.ainvoke({"query": "test"})

    @pytest.mark.asyncio
    async def test_mcp_server_error(self):
        """Test error handling when MCP server returns an error."""
        mock_client = AsyncMock()
        mock_client.health_check.return_value = True
        mock_client.call_tool.side_effect = Exception("Connection failed")

        with patch("app.tools.oriahs_search.get_mcp_client", return_value=mock_client):
            with pytest.raises(
                Exception, match="Semantic search unavailable: Connection failed"
            ):
                await oriahs_search.ainvoke({"query": "test"})

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
        with pytest.raises(Exception, match="top_k must be between 1 and 50"):
            await oriahs_search.ainvoke({"query": "test", "top_k": 0})

        with pytest.raises(Exception, match="top_k must be between 1 and 50"):
            await oriahs_search.ainvoke({"query": "test", "top_k": 51})

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

            assert "Score: 0.950" in result
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
            assert "Score: 0.950" in result
            assert "app/main.py" in result
            assert "Score: 0.870" in result
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

        assert "[1] Score: 0.950" in result
        assert "app/main.py" in result
        assert "function" in result
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

        assert "[1] Score: 0.950" in result
        assert "[2] Score: 0.870" in result
        assert "app/main.py" in result
        assert "app/utils.py" in result

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
            mock_response = AsyncMock()
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
            mock_response = AsyncMock()
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
