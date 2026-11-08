"""MCP server: oriahs-mcp (B-01) - OriaHS semantic search MCP server.

Wraps OriaHS API as an MCP server providing semantic codebase search capabilities.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

import httpx
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import (
    CallToolRequest,
    CallToolResult,
    ListToolsResult,
    TextContent,
    Tool,
)

logger = logging.getLogger(__name__)


class OriaHSConfig:
    """Configuration for OriaHS backend."""

    def __init__(
        self,
        base_url: str = "http://localhost:8000",
        token: str | None = None,
        timeout: float = 10.0,
        max_retries: int = 3,
    ):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout = timeout
        self.max_retries = max_retries

        # HTTP client for OriaHS API
        self._http_client = httpx.AsyncClient(
            base_url=self.base_url,
            headers={"Authorization": f"Bearer {self.token}"} if self.token else {},
            timeout=timeout,
        )

    async def close(self) -> None:
        """Close the HTTP client."""
        await self._http_client.aclose()


class OriaHSMCPServer:
    """MCP server wrapping OriaHS semantic search and indexing capabilities."""

    def __init__(self, config: OriaHSConfig):
        self.config = config
        self.server = Server("oriahs-mcp")

        # Register tools
        self.server.list_tools()(self.list_tools)
        self.server.call_tool()(self.call_tool)

    async def list_tools(self) -> ListToolsResult:
        """List available tools from OriaHS MCP server."""
        return ListToolsResult(
            tools=[
                Tool(
                    name="hybrid_search",
                    description="Semantic codebase search using hybrid (sparse+dense) retrieval",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "query": {
                                "type": "string",
                                "description": "Natural language search query",
                            },
                            "top_k": {
                                "type": "integer",
                                "default": 10,
                                "minimum": 1,
                                "maximum": 50,
                                "description": "Maximum number of results to return",
                            },
                            "filters": {
                                "type": "object",
                                "description": "Optional filters for search (file type, date range, etc.)",
                            },
                        },
                        "required": ["query"],
                    },
                ),
                Tool(
                    name="index_file",
                    description="Index a single file in the codebase",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "file_path": {
                                "type": "string",
                                "description": "Path to the file to index",
                            },
                        },
                        "required": ["file_path"],
                    },
                ),
                Tool(
                    name="index_directory",
                    description="Index a directory with optional recursive indexing",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "directory_path": {
                                "type": "string",
                                "description": "Path to the directory to index",
                            },
                            "recursive": {
                                "type": "boolean",
                                "default": False,
                                "description": "Index subdirectories recursively",
                            },
                        },
                        "required": ["directory_path"],
                    },
                ),
            ]
        )

    async def call_tool(self, request: CallToolRequest) -> CallToolResult:
        """Call a tool on the OriaHS MCP server."""
        try:
            tool_name = request.params.name
            arguments = request.params.arguments

            if tool_name == "hybrid_search":
                return await self._call_hybrid_search(arguments)
            elif tool_name == "index_file":
                return await self._call_index_file(arguments)
            elif tool_name == "index_directory":
                return await self._call_index_directory(arguments)
            else:
                raise ValueError(f"Unknown tool: {tool_name}")

        except Exception as e:
            logger.error(f"Error calling tool {request.params.name}: {e}")
            return CallToolResult(
                content=[TextContent(type="text", text=f"Error: {str(e)}")],
                isError=True,
            )

    async def _call_hybrid_search(self, arguments: dict[str, Any]) -> CallToolResult:
        """Execute semantic search through OriaHS."""
        query = arguments.get("query", "")
        top_k = arguments.get("top_k", 10)
        filters = arguments.get("filters", {})

        if not query:
            raise ValueError("Query is required")

        if top_k < 1 or top_k > 50:
            raise ValueError("top_k must be between 1 and 50")

        # Prepare search request
        search_request = {
            "query": query,
            "top_k": top_k,
            "mode": "hybrid",  # Sparse + dense retrieval
            "filters": filters,
        }

        # Execute search
        try:
            response = await self.config._http_client.post(
                "/search", json=search_request
            )
            response.raise_for_status()
            results = response.json().get("results", [])

            # Format results for MCP
            formatted_results = []
            for i, result in enumerate(results, 1):
                formatted_results.append(
                    TextContent(
                        type="text",
                        text=json.dumps(
                            {
                                "rank": i,
                                "score": result.get("score", 0.0),
                                "path": result.get("path", ""),
                                "content": result.get("content", ""),
                                "type": result.get("type", "unknown"),
                            },
                            ensure_ascii=False,
                        ),
                    )
                )

            return CallToolResult(content=formatted_results)

        except httpx.HTTPStatusError as e:
            error_msg = f"OriaHS API error: {e.response.status_code}"
            if e.response.text:
                error_msg += f" - {e.response.text}"
            raise ValueError(error_msg)
        except Exception as e:
            raise ValueError(f"Search failed: {str(e)}")

    async def _call_index_file(self, arguments: dict[str, Any]) -> CallToolResult:
        """Execute file indexing through OriaHS."""
        file_path = arguments.get("file_path", "")

        if not file_path:
            raise ValueError("File path is required")

        try:
            # Convert to absolute path and validate
            abs_path = Path(file_path).resolve()
            if not abs_path.exists():
                raise ValueError(f"File does not exist: {file_path}")

            if not abs_path.is_file():
                raise ValueError(f"Path is not a file: {file_path}")

            # Prepare indexing request
            index_request = {
                "file_path": str(abs_path),
                "operation": "index",
            }

            # Execute indexing
            response = await self.config._http_client.post("/index", json=index_request)
            response.raise_for_status()
            result = response.json()

            # Format result for MCP
            formatted_result = TextContent(
                type="text",
                text=json.dumps(
                    {
                        "path": str(abs_path),
                        "status": "success",
                        "message": result.get("message", "File indexed successfully"),
                        "indexed_at": result.get("indexed_at"),
                    },
                    ensure_ascii=False,
                ),
            )

            return CallToolResult(content=[formatted_result])

        except httpx.HTTPStatusError as e:
            error_msg = f"OriaHS API error: {e.response.status_code}"
            if e.response.text:
                error_msg += f" - {e.response.text}"
            raise ValueError(error_msg)
        except Exception as e:
            raise ValueError(f"File indexing failed: {str(e)}")

    async def _call_index_directory(self, arguments: dict[str, Any]) -> CallToolResult:
        """Execute directory indexing through OriaHS."""
        directory_path = arguments.get("directory_path", "")
        recursive = arguments.get("recursive", False)

        if not directory_path:
            raise ValueError("Directory path is required")

        try:
            # Convert to absolute path and validate
            abs_path = Path(directory_path).resolve()
            if not abs_path.exists():
                raise ValueError(f"Directory does not exist: {directory_path}")

            if not abs_path.is_dir():
                raise ValueError(f"Path is not a directory: {directory_path}")

            # Prepare indexing request
            index_request = {
                "directory_path": str(abs_path),
                "recursive": recursive,
                "operation": "index",
            }

            # Execute indexing
            response = await self.config._http_client.post("/index", json=index_request)
            response.raise_for_status()
            result = response.json()

            # Format result for MCP
            formatted_result = TextContent(
                type="text",
                text=json.dumps(
                    {
                        "directory": str(abs_path),
                        "status": "success",
                        "recursive": recursive,
                        "message": result.get(
                            "message", "Directory indexed successfully"
                        ),
                        "indexed_files": result.get("indexed_files", 0),
                        "indexed_at": result.get("indexed_at"),
                    },
                    ensure_ascii=False,
                ),
            )

            return CallToolResult(content=[formatted_result])

        except httpx.HTTPStatusError as e:
            error_msg = f"OriaHS API error: {e.response.status_code}"
            if e.response.text:
                error_msg += f" - {e.response.text}"
            raise ValueError(error_msg)
        except Exception as e:
            raise ValueError(f"Directory indexing failed: {str(e)}")

    async def health_check(self) -> bool:
        """Check if OriaHS backend is healthy."""
        try:
            response = await self.config._http_client.get("/health")
            response.raise_for_status()
            return True
        except Exception as e:
            logger.warning(f"OriaHS health check failed: {e}")
            return False


async def run_server(config: OriaHSConfig):
    """Run the OriaHS MCP server."""
    server = OriaHSMCPServer(config)

    async with stdio_server() as (read_stream, write_stream):
        await server.server.run(read_stream, write_stream)


if __name__ == "__main__":
    import os

    # Configuration from environment
    config = OriaHSConfig(
        base_url=os.getenv("ORIAHS_BASE_URL", "http://localhost:8000"),
        token=os.getenv("ORIAHS_TOKEN"),
        timeout=float(os.getenv("ORIAHS_TIMEOUT", "10.0")),
    )

    async def main():
        try:
            await run_server(config)
        except KeyboardInterrupt:
            print("Shutting down OriaHS MCP server...")
        finally:
            await config.close()

    asyncio.run(main())
