"""MCP client infrastructure for B-02 oriahs_search tool.

Provides the MCPClient class for communicating with oriahs-mcp server.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx
from pydantic import BaseModel

logger = logging.getLogger(__name__)


class MCPClientConfig(BaseModel):
    """Configuration for MCP client."""

    server_url: str = "http://localhost:8765"
    auth_token: str | None = None
    timeout: float = 10.0
    max_retries: int = 3


class MCPToolCall(BaseModel):
    """MCP tool call request."""

    name: str
    arguments: dict[str, Any]


class MCPToolResult(BaseModel):
    """MCP tool call result."""

    content: list[dict[str, Any]]
    is_error: bool = False
    error: str | None = None


class MCPClient:
    """MCP client for communicating with oriahs-mcp server."""

    def __init__(self, config: MCPClientConfig):
        self.config = config
        headers = {}
        if config.auth_token:
            headers["Authorization"] = f"Bearer {config.auth_token}"

        self._http_client = httpx.AsyncClient(
            base_url=config.server_url,
            headers=headers,
            timeout=config.timeout,
        )
        self._lock = asyncio.Lock()

    async def close(self) -> None:
        """Close the HTTP client."""
        await self._http_client.aclose()

    async def health_check(self) -> bool:
        """Check if MCP server is healthy."""
        try:
            response = await self._http_client.get("/health")
            response.raise_for_status()
            return True
        except Exception as e:
            logger.warning(f"MCP health check failed: {e}")
            return False

    async def list_tools(self) -> list[dict[str, Any]]:
        """List available tools from MCP server."""
        try:
            response = await self._http_client.get("/tools")
            response.raise_for_status()
            data = response.json()
            return data.get("tools", [])
        except Exception as e:
            logger.error(f"Failed to list MCP tools: {e}")
            return []

    async def call_tool(
        self, tool_name: str, arguments: dict[str, Any]
    ) -> list[dict[str, Any]]:
        """Call a tool on the MCP server."""
        async with self._lock:
            try:
                response = await self._http_client.post(
                    "/call", json={"name": tool_name, "arguments": arguments}
                )
                response.raise_for_status()
                data = await response.json()
                return data.get("content", [])
            except Exception as e:
                logger.error(f"Failed to call MCP tool {tool_name}: {e}")
                raise

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()


# Global MCP client instance
_mcp_client_instance: MCPClient | None = None
_mcp_config: MCPClientConfig | None = None


def get_mcp_client() -> MCPClient:
    """Get or create MCP client instance."""
    global _mcp_client_instance, _mcp_config

    if _mcp_client_instance is None:
        if _mcp_config is None:
            # Load from environment or use defaults
            _mcp_config = MCPClientConfig()

        _mcp_client_instance = MCPClient(_mcp_config)

    return _mcp_client_instance


def set_mcp_config(config: MCPClientConfig) -> None:
    """Set MCP client configuration."""
    global _mcp_config, _mcp_client_instance

    _mcp_config = config
    # Close existing client if any
    if _mcp_client_instance is not None:
        asyncio.create_task(_mcp_client_instance.close())
        _mcp_client_instance = None


async def close_mcp_client() -> None:
    """Close the global MCP client."""
    global _mcp_client_instance

    if _mcp_client_instance is not None:
        await _mcp_client_instance.close()
        _mcp_client_instance = None
