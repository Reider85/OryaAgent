"""Integration tests for MCP infrastructure (B-01 and B-02)."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from fastapi.testclient import TestClient

from app.mcp.client import MCPClient, MCPClientConfig
from app.mcp.oriahs_mcp import OriaHSConfig, OriaHSMCPServer, create_http_app
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
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_get.return_value = mock_response

            health_ok = await client.health_check()
            assert health_ok is True

        # Mock successful tool listing
        with patch.object(client._http_client, "get") as mock_get:
            mock_response = MagicMock()
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
            mock_response = MagicMock()
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

        # Mock successful readiness probe (fresh OriaHS: GET /health/ready)
        with patch.object(config._http_client, "get") as mock_get:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.content = b'{"status": "ready", "checks": {}}'
            mock_response.json.return_value = {"status": "ready", "checks": {}}
            mock_get.return_value = mock_response

            health_ok = await server.health_check()
            assert health_ok is True
            mock_get.assert_called_once_with("/health/ready")

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
            mock_response = MagicMock()
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
        # Isolate the real in-memory cache: earlier tests may have cached a
        # successful ``query="test"`` under the same (query, top_k, filters)
        # key, which would turn every error scenario below into a cache hit
        # ("DID NOT RAISE") depending on file order.
        isolated_cache = AsyncMock()
        isolated_cache.get.return_value = None

        with patch("app.tools.oriahs_search.get_cache", return_value=isolated_cache):
            # Test connection error
            mock_client = AsyncMock()
            mock_client.health_check.side_effect = Exception("Connection failed")

            with patch(
                "app.tools.oriahs_search.get_mcp_client", return_value=mock_client
            ):
                # P-00: connectivity failures degrade to the exact fallback
                # string instead of raising into the UI.
                result = await oriahs_search.ainvoke({"query": "test"})
                assert result == "service unavailable, use grep"

            # Test API error
            mock_client = AsyncMock()
            mock_client.health_check.return_value = True
            mock_client.call_tool.side_effect = Exception("API Error")

            with patch(
                "app.tools.oriahs_search.get_mcp_client", return_value=mock_client
            ):
                with pytest.raises(Exception, match="Search failed"):
                    await oriahs_search.ainvoke({"query": "test"})

            # Test timeout
            mock_client = AsyncMock()
            mock_client.health_check.return_value = True
            mock_client.call_tool.side_effect = TimeoutError("Request timeout")

            with patch(
                "app.tools.oriahs_search.get_mcp_client", return_value=mock_client
            ):
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


class TestOriaHSHTTPTransport:
    """HTTP transport of oriahs-mcp (B-01/B-02 contract).

    The container previously ran the stdio transport while the compose
    healthchecks, the `api` dependency gate and app/mcp/client.py all speak
    HTTP — the app profile could never start. These tests pin the REST
    contract: /health is pure liveness (the OriaHS backend may be absent
    from the stack), /tools lists the MCP tools, /call unwraps TextContent
    JSON into the flat dicts oriahs_search parses, and backend failures
    surface as 502 so the client raises and the tools degrade.
    """

    def test_health_is_pure_liveness_without_backend(self):
        """No backend probe: api waits on service_healthy and may legitimately
        run without the OriaHS service."""
        app = create_http_app(OriaHSConfig(base_url="http://127.0.0.1:9"))
        client = TestClient(app)

        response = client.get("/health")

        assert response.status_code == 200
        assert response.json() == {"status": "ok"}

    def test_tools_endpoint_lists_the_mcp_tools(self):
        app = create_http_app(OriaHSConfig(base_url="http://127.0.0.1:9"))
        client = TestClient(app)

        response = client.get("/tools")

        assert response.status_code == 200
        tools = response.json()["tools"]
        names = {tool["name"] for tool in tools}
        assert names == {"hybrid_search", "index_file", "index_directory"}
        assert all(tool["description"] for tool in tools)

    def test_call_unwraps_textcontent_into_flat_dicts(self):
        config = OriaHSConfig(base_url="http://oriahs.test")
        app = create_http_app(config)

        with patch.object(config._http_client, "post") as mock_post:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "results": [
                    {
                        "score": 0.95,
                        "path": "app/main.py",
                        "content": "def main(): ...",
                        "type": "python",
                    }
                ]
            }
            mock_post.return_value = mock_response

            client = TestClient(app)
            response = client.post(
                "/call",
                json={"name": "hybrid_search", "arguments": {"query": "main"}},
            )

        assert response.status_code == 200
        content = response.json()["content"]
        # Flat dict with "score" — the shape oriahs_search parses, not an
        # MCP {"type": "text", "text": ...} envelope.
        assert content[0]["score"] == 0.95
        assert content[0]["path"] == "app/main.py"

    def test_call_backend_failure_returns_502(self):
        config = OriaHSConfig(base_url="http://oriahs.test")
        app = create_http_app(config)

        with patch.object(config._http_client, "post") as mock_post:
            mock_post.side_effect = httpx.ConnectError("backend down")

            client = TestClient(app)
            response = client.post(
                "/call",
                json={"name": "hybrid_search", "arguments": {"query": "x"}},
            )

        # MCPClient.raise_for_status turns this into an exception → the tools
        # report "Search failed" / "Indexing failed" instead of hanging.
        assert response.status_code == 502
        assert "Search failed" in response.json()["detail"]


class TestP00FreshOriaHSContract:
    """End-to-end wire contract against the fresh REST-only OriaHS (P-00)."""

    @staticmethod
    async def _server(
        handler, tenant_id: str = "tenant-1"
    ) -> tuple[OriaHSMCPServer, OriaHSConfig]:
        config = OriaHSConfig(base_url="http://oriahs.test", tenant_id=tenant_id)
        await config._http_client.aclose()
        config._http_client = httpx.AsyncClient(
            transport=httpx.MockTransport(handler), base_url="http://oriahs.test"
        )
        return OriaHSMCPServer(config), config

    @pytest.mark.asyncio
    async def test_search_maps_fresh_hits_through_mcp(self):
        from mcp.types import CallToolRequest

        captured: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["path"] = request.url.path
            captured["body"] = json.loads(request.content)
            return httpx.Response(
                200,
                json={
                    "hits": [
                        {
                            "doc_id": "d-1",
                            "score": 0.88,
                            "title": "app/main.py",
                            "snippet": "def main(): pass",
                            "attributes": {"path": "app/main.py", "type": "python"},
                        }
                    ]
                },
            )

        server, config = await self._server(handler)
        try:
            result = await server.call_tool(
                CallToolRequest(
                    params={"name": "hybrid_search", "arguments": {"query": "main"}}
                )
            )
        finally:
            await config.close()

        assert captured["path"] == "/search"
        assert captured["body"]["tenant_id"] == "tenant-1"
        assert "mode" not in captured["body"]
        assert len(result.content) == 1
        payload = json.loads(result.content[0].text)
        assert payload["path"] == "app/main.py"
        assert payload["content"] == "def main(): pass"
        assert payload["type"] == "python"

    @pytest.mark.asyncio
    async def test_health_uses_ready_endpoint(self):
        seen: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request.url.path)
            return httpx.Response(200, json={"status": "ready", "checks": {}})

        server, config = await self._server(handler)
        try:
            assert await server.health_check() is True
        finally:
            await config.close()

        assert seen == ["/health/ready"]
