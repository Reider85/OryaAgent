"""MCP server wrapper for UKB tools."""

from __future__ import annotations

import json
import logging
from typing import Any

from app.tools.ukb import ukb_lookup

logger = logging.getLogger(__name__)


class UKBMCPServer:
    """MCP server wrapper for UKB tools."""

    def __init__(self):
        self.name = "ukb-mcp"
        self.version = "1.0.0"
        self.tools = {
            "ukb.lookup": ukb_lookup,
        }
        self.initialized = False

    async def initialize(self) -> None:
        """Initialize the MCP server."""
        self.initialized = True
        logger.info("UKB MCP server initialized")

    async def list_tools(self) -> list[dict[str, Any]]:
        """List available tools."""
        tools = []
        for tool_name, tool in self.tools.items():
            tools.append(
                {
                    "name": tool_name,
                    "description": tool.description,
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "query": {
                                "type": "string",
                                "description": "Search query string",
                            },
                            "capability": {
                                "type": "string",
                                "description": "Specific capability to route to (e.g., 'lsp.def', 'memory.semantic')",
                            },
                            "top_k": {
                                "type": "integer",
                                "description": "Maximum number of results to return",
                                "default": 5,
                            },
                        },
                        "required": ["query"],
                    },
                }
            )
        return tools

    async def call_tool(
        self, tool_name: str, arguments: dict[str, Any]
    ) -> dict[str, Any]:
        """Call a UKB tool."""
        if not self.initialized:
            await self.initialize()

        if tool_name not in self.tools:
            raise ValueError(f"Unknown tool: {tool_name}")

        tool = self.tools[tool_name]

        try:
            # Prepare arguments for the tool
            tool_args = {
                "query": arguments.get("query", ""),
                "capability": arguments.get("capability"),
                "top_k": arguments.get("top_k", 5),
            }

            # Call the tool
            result = await tool._arun(**tool_args)

            return {
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps(result, indent=2, ensure_ascii=False),
                    }
                ]
            }

        except Exception as e:
            logger.error(f"UKB tool {tool_name} failed: {e}")
            return {
                "content": [
                    {"type": "text", "text": json.dumps({"error": str(e)}, indent=2)}
                ],
                " isError": True,
            }

    async def handle_message(self, message: dict[str, Any]) -> dict[str, Any]:
        """Handle MCP message."""
        method = message.get("method")

        if method == "initialize":
            await self.initialize()
            return {
                "jsonrpc": "2.0",
                "id": message.get("id"),
                "result": {"capabilities": {"tools": {"listChanged": False}}},
            }

        elif method == "tools/list":
            tools = await self.list_tools()
            return {
                "jsonrpc": "2.0",
                "id": message.get("id"),
                "result": {"tools": tools},
            }

        elif method == "tools/call":
            tool_name = message.get("params", {}).get("name")
            arguments = message.get("params", {}).get("arguments", {})

            result = await self.call_tool(tool_name, arguments)

            return {"jsonrpc": "2.0", "id": message.get("id"), "result": result}

        else:
            raise ValueError(f"Unknown method: {method}")


# Global instance
_ukb_mcp_server: UKBMCPServer | None = None


def get_ukb_mcp_server() -> UKBMCPServer:
    """Get global UKB MCP server instance."""
    global _ukb_mcp_server
    if _ukb_mcp_server is None:
        _ukb_mcp_server = UKBMCPServer()
    return _ukb_mcp_server


def initialize_ukb_mcp_server() -> UKBMCPServer:
    """Initialize global UKB MCP server."""
    global _ukb_mcp_server
    _ukb_mcp_server = UKBMCPServer()
    return _ukb_mcp_server
