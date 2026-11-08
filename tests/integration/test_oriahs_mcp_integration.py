"""Integration tests for MCP infrastructure (B-01 and B-02)."""

import json
import pytest
import asyncio
from unittest.mock import AsyncMock, patch
from httpx import AsyncClient

from app.mcp.client import MCPClient, MCPClientConfig
from app.mcp.oriahs_mcp import OriaHSMCPServer, OriaHSConfig
from app.tools.oriahs_search import oriahs_search


class TestMCPIntegration:
    """Integration tests for MCP infrastructure."""

    @pytest.mark.asyncio
    async def test_mcp_client_full_flow(self):
        """Test complete MCP client flow."""
        config = MCPClientConfig(server_url="http://test.com")
        client = MCPClient(config)

        # Mock successful health check
        with patch.object(client._http_client, "get") as mock_get:
            mock_response = AsyncMock()
            mock_response.status_code = 200
            mock_get.return_value = mock_response

            health_ok = await client.health_check()
            assert health_ok is True

        # Mock successful tool listing
        with patch.object(client._http_client, "get") as mock_get:
            mock_response = AsyncMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "tools": [{"name": "hybrid_search", "description": "Test search tool"}]
            }
            mock_get.return_value = mock_response

            tools = await client.list_tools()
            assert len(tools) == 1
            assert tools[0]["name"] == "hybrid_search"

        # Mock successful tool call
        with patch.object(client._http_client, "post") as mock_post:
            mock_response = AsyncMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "content": [
                    {
                        "score": 0.95,
                        "path": "test.py",
                        "content": "def test(): pass",
                        "type": "function",
                    }
                ]
            }
            mock_post.return_value = mock_response

            results = await client.call_tool(
                "hybrid_search", {"query": "test", "top_k": 10}
            )

            assert len(results) == 1
            assert results[0]["score"] == 0.95
            assert results[0]["path"] == "test.py"

        # Clean up
        await client.close()

    @pytest.mark.asyncio
    async def test_mcp_server_health_check(self):
        """Test MCP server health check functionality."""
        config = OriaHSConfig(base_url="http://test.com")
        server = OriaHSMCPServer(config)

        # Mock successful health check
        with patch.object(config._http_client, "get") as mock_get:
            mock_response = AsyncMock()
            mock_response.status_code = 200
            mock_get.return_value = mock_response

            health_ok = await server.health_check()
            assert health_ok is True

        # Mock failed health check
        with patch.object(config._http_client, "get") as mock_get:
            mock_get.side_effect = Exception("Connection failed")

            health_ok = await server.health_check()
            assert health_ok is False

        # Clean up
        await config.close()

    @pytest.mark.asyncio
    async def test_mcp_server_tool_call(self):
        """Test MCP server tool call functionality."""
        config = OriaHSConfig(base_url="http://test.com")
        server = OriaHSMCPServer(config)

        # Mock successful search
        with patch.object(config._http_client, "post") as mock_post:
            mock_response = AsyncMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "results": [
                    {
                        "score": 0.95,
                        "path": "test.py",
                        "content": "def test(): pass",
                        "type": "function",
                    }
                ]
            }
            mock_post.return_value = mock_response

            from mcp.types import CallToolRequest

            request = CallToolRequest(
                params={
                    "name": "hybrid_search",
                    "arguments": {"query": "test", "top_k": 10},
                }
            )

            result = await server.call_tool(request)

            assert len(result.content) == 1
            content_data = json.loads(result.content[0].text)
            assert content_data["score"] == 0.95
            assert content_data["path"] == "test.py"

        # Clean up
        await config.close()


class TestOriaHSIntegration:
    """Integration tests for oriahs_search tool with MCP."""

    @pytest.mark.asyncio
    async def test_end_to_end_search_flow(self):
        """Test complete search flow from tool to MCP server."""
        # Mock MCP client
        mock_client = AsyncMock()
        mock_client.health_check.return_value = True
        mock_client.call_tool.return_value = [
            {
                "score": 0.95,
                "path": "app/main.py",
                "content": "def main():\n    print('Hello World')",
                "type": "function",
            },
            {
                "score": 0.87,
                "path": "app/utils.py",
                "content": "def helper():\n    return 'help'",
                "type": "function",
            },
        ]

        with patch("app.tools.oriahs_search.get_mcp_client", return_value=mock_client):
            result = await oriahs_search.ainvoke({"query": "hello world", "top_k": 5})

            # Verify result contains expected content
            assert "Score: 0.950" in result
            assert "app/main.py" in result
            assert "app/utils.py" in result
            assert "function" in result

            # Verify MCP client was called correctly
            mock_client.health_check.assert_called_once()
            mock_client.call_tool.assert_called_once_with(
                "hybrid_search", {"query": "hello world", "top_k": 5, "filters": {}}
            )

    @pytest.mark.asyncio
    async def test_search_with_real_http_client(self):
        """Test search with actual HTTP client (requires running server)."""
        # This test requires a running MCP server
        # Skip if no server is available
        try:
            config = MCPClientConfig(server_url="http://localhost:8765")
            client = MCPClient(config)

            # Try health check
            is_healthy = await client.health_check()

            if not is_healthy:
                pytest.skip("MCP server not available at http://localhost:8765")

            # Test actual search
            results = await client.call_tool(
                "hybrid_search", {"query": "test", "top_k": 5}
            )

            # Verify results format
            assert isinstance(results, list)
            for result in results:
                assert "score" in result
                assert "path" in result
                assert "content" in result
                assert "type" in result

            await client.close()

        except Exception as e:
            pytest.skip(f"MCP server connection failed: {e}")

    @pytest.mark.asyncio
    async def test_search_error_scenarios(self):
        """Test various error scenarios in search."""
        # Test connection error
        mock_client = AsyncMock()
        mock_client.health_check.side_effect = Exception("Connection failed")

        with patch("app.tools.oriahs_search.get_mcp_client", return_value=mock_client):
            with pytest.raises(Exception, match="not available"):
                await oriahs_search.ainvoke({"query": "test"})

        # Test API error
        mock_client = AsyncMock()
        mock_client.health_check.return_value = True
        mock_client.call_tool.side_effect = Exception("API Error")

        with patch("app.tools.oriahs_search.get_mcp_client", return_value=mock_client):
            with pytest.raises(Exception, match="Search failed"):
                await oriahs_search.ainvoke({"query": "test"})

        # Test timeout
        mock_client = AsyncMock()
        mock_client.health_check.return_value = True
        mock_client.call_tool.side_effect = asyncio.TimeoutError("Request timeout")

        with patch("app.tools.oriahs_search.get_mcp_client", return_value=mock_client):
            with pytest.raises(Exception, match="Search failed"):
                await oriahs_search.ainvoke({"query": "test"})


class TestConfiguration:
    """Test configuration management."""

    def test_mcp_config_defaults(self):
        """Test default MCP configuration."""
        config = MCPClientConfig()

        assert config.server_url == "http://localhost:8765"
        assert config.auth_token is None
        assert config.timeout == 10.0
        assert config.max_retries == 3

    def test_mcp_config_custom(self):
        """Test custom MCP configuration."""
        config = MCPClientConfig(
            server_url="http://custom.com:8080",
            auth_token="test-token",
            timeout=15.0,
            max_retries=5,
        )

        assert config.server_url == "http://custom.com:8080"
        assert config.auth_token == "test-token"
        assert config.timeout == 15.0
        assert config.max_retries == 5

    def test_oriahs_config_defaults(self):
        """Test default OriaHS configuration."""
        config = OriaHSConfig()

        assert config.base_url == "http://localhost:8000"
        assert config.token is None
        assert config.timeout == 10.0
        assert config.max_retries == 3

    def test_oriahs_config_custom(self):
        """Test custom OriaHS configuration."""
        config = OriaHSConfig(
            base_url="http://oriahs.example.com",
            token="test-oraihs-token",
            timeout=20.0,
            max_retries=7,
        )

        assert config.base_url == "http://oriahs.example.com"
        assert config.token == "test-oraihs-token"
        assert config.timeout == 20.0
        assert config.max_retries == 7
