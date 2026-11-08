"""MCP server wrapper for LSP tools."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Dict, List, Optional

from app.core.lsp.bus import get_lsp_bus
from app.core.lsp.tools import (
    lsp_hover,
    lsp_definition,
    lsp_references,
    lsp_symbol_search,
    lsp_rename,
    lsp_diagnostics,
    lsp_code_action,
)
from app.core.tools._validators import validate_path

logger = logging.getLogger(__name__)


class LSPMCPServer:
    """MCP server wrapper for LSP tools."""

    def __init__(self):
        self.name = "lsp-mcp"
        self.version = "1.0.0"
        self.tools = {
            "lsp.hover": lsp_hover,
            "lsp.def": lsp_definition,
            "lsp.refs": lsp_references,
            "lsp.symbol_search": lsp_symbol_search,
            "lsp.rename": lsp_rename,
            "lsp.diagnostics": lsp_diagnostics,
            "lsp.codeAction": lsp_code_action,
        }
        self.initialized = False

    async def initialize(self) -> None:
        """Initialize the MCP server."""
        self.initialized = True
        logger.info("LSP MCP server initialized")

    async def list_tools(self) -> List[Dict[str, Any]]:
        """List available tools."""
        tools = []

        for tool_name, tool_func in self.tools.items():
            # Get tool schema from function
            schema = getattr(tool_func, "__annotations__", {})

            tools.append(
                {
                    "name": tool_name,
                    "description": tool_func.__doc__ or f"LSP tool: {tool_name}",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "file_path": {
                                "type": "string",
                                "description": "Path to the file",
                            },
                            "line": {
                                "type": "integer",
                                "description": "Line number (0-based)",
                            },
                            "column": {
                                "type": "integer",
                                "description": "Column number (0-based)",
                            },
                            "workspace": {
                                "type": "string",
                                "description": "Workspace directory",
                                "default": ".",
                            },
                            "query": {"type": "string", "description": "Search query"},
                            "new_name": {
                                "type": "string",
                                "description": "New name for the symbol",
                            },
                            "include_declaration": {
                                "type": "boolean",
                                "description": "Whether to include the declaration itself",
                                "default": True,
                            },
                            "limit": {
                                "type": "integer",
                                "description": "Maximum number of results",
                                "default": 10,
                            },
                        },
                    },
                }
            )

        return tools

    async def call_tool(
        self, tool_name: str, arguments: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Call an LSP tool."""
        if not self.initialized:
            raise RuntimeError("LSP MCP server not initialized")

        if tool_name not in self.tools:
            raise ValueError(f"Unknown tool: {tool_name}")

        try:
            # Get the tool function
            tool_func = self.tools[tool_name]

            # Prepare arguments
            kwargs = {}

            # Handle different argument names
            if "file_path" in arguments:
                kwargs["file_path"] = arguments["file_path"]
            if "line" in arguments:
                kwargs["line"] = arguments["line"]
            if "column" in arguments:
                kwargs["column"] = arguments["column"]
            if "workspace" in arguments:
                kwargs["workspace"] = arguments["workspace"]
            if "query" in arguments:
                kwargs["query"] = arguments["query"]
            if "new_name" in arguments:
                kwargs["new_name"] = arguments["new_name"]
            if "include_declaration" in arguments:
                kwargs["include_declaration"] = arguments["include_declaration"]
            if "limit" in arguments:
                kwargs["limit"] = arguments["limit"]

            # Call the tool function
            result = await tool_func(**kwargs)

            # Convert result to MCP format
            return {
                "result": result,
                "metadata": {
                    "tool": tool_name,
                    "success": result.get("success", True),
                    "language": result.get("language"),
                },
            }

        except Exception as e:
            logger.error(f"Error calling tool {tool_name}: {e}")
            return {
                "result": {
                    "success": False,
                    "error": str(e),
                    "message": f"Tool execution failed: {str(e)}",
                },
                "metadata": {
                    "tool": tool_name,
                    "success": False,
                    "error": str(e),
                },
            }

    async def get_server_info(self) -> Dict[str, Any]:
        """Get server information."""
        return {
            "name": self.name,
            "version": self.version,
            "tools": len(self.tools),
            "initialized": self.initialized,
        }

    async def health_check(self) -> Dict[str, Any]:
        """Perform health check."""
        try:
            # Check LSP bus
            lsp_bus = get_lsp_bus()
            supported_languages = lsp_bus.get_supported_languages()

            # Check if any servers are running
            running_servers = []
            for language in supported_languages:
                # Try to get server (this will start it if not running)
                try:
                    workspace_path = validate_path(".")
                    server = await lsp_bus.get_server(language, workspace_path)
                    if server:
                        running_servers.append(language)
                except Exception:
                    continue

            return {
                "status": "healthy",
                "supported_languages": supported_languages,
                "running_servers": running_servers,
                "total_tools": len(self.tools),
            }

        except Exception as e:
            logger.error(f"Health check failed: {e}")
            return {
                "status": "unhealthy",
                "error": str(e),
            }


class LSPMCPHandler:
    """Handler for LSP MCP server."""

    def __init__(self):
        self.server = LSPMCPServer()

    async def handle_initialize(self) -> Dict[str, Any]:
        """Handle initialize request."""
        await self.server.initialize()

        return {
            "protocolVersion": "2024-11-05",
            "capabilities": {
                "tools": {
                    "listChanged": True,
                }
            },
            "serverInfo": {
                "name": self.server.name,
                "version": self.server.version,
            },
        }

    async def handle_list_tools(self) -> List[Dict[str, Any]]:
        """Handle list tools request."""
        return await self.server.list_tools()

    async def handle_call_tool(
        self, tool_name: str, arguments: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Handle call tool request."""
        return await self.server.call_tool(tool_name, arguments)

    async def handle_server_info(self) -> Dict[str, Any]:
        """Handle server info request."""
        return await self.server.get_server_info()

    async def handle_health_check(self) -> Dict[str, Any]:
        """Handle health check request."""
        return await self.server.health_check()


# Global MCP handler instance
_lsp_mcp_handler: Optional[LSPMCPHandler] = None


def get_lsp_mcp_handler() -> LSPMCPHandler:
    """Get global LSP MCP handler instance."""
    global _lsp_mcp_handler
    if _lsp_mcp_handler is None:
        _lsp_mcp_handler = LSPMCPHandler()
    return _lsp_mcp_handler


def initialize_lsp_mcp() -> LSPMCPHandler:
    """Initialize global LSP MCP handler."""
    global _lsp_mcp_handler
    _lsp_mcp_handler = LSPMCPHandler()
    return _lsp_mcp_handler
