"""MCP server: oriahs-mcp (B-01, P-00) - OriaHS semantic search MCP server.

Wraps the fresh OriaHS REST API (which has no MCP server of its own) through
the shared ``app.core.oriahs_client.OriaHSClient`` contract.

Two transports (B-02 wires the HTTP one):

* **HTTP (default)** — ``GET /health``, ``GET /tools``, ``POST /call`` exactly
  as ``app/mcp/client.py`` expects, and as the compose/Docker healthchecks
  probe them. The pre-B-01 container ran the stdio transport while everything
  around it spoke HTTP, so ``api``/``chainlit`` (``depends_on:
  service_healthy``) could never start. Bind with ``--host``/``--port``
  (containers pass ``--host 0.0.0.0``).
* **stdio** (``--stdio``) — the classic MCP stdio transport for external MCP
  clients that spawn the process themselves.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import (
    CallToolRequest,
    CallToolResult,
    ListToolsResult,
    TextContent,
    Tool,
)
from pydantic import BaseModel

from app.core.config import get_settings
from app.core.oriahs_client import OriaHSClient

logger = logging.getLogger(__name__)


class OriaHSConfig:
    """Configuration for OriaHS backend."""

    def __init__(
        self,
        base_url: str = "http://localhost:8000",
        token: str | None = None,
        timeout: float = 10.0,
        max_retries: int = 3,
        tenant_id: str = "11111111-1111-1111-1111-111111111111",
    ):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout = timeout
        self.max_retries = max_retries
        self.tenant_id = tenant_id

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
        self.client = OriaHSClient(
            base_url=config.base_url,
            timeout_s=config.timeout,
            tenant_id=config.tenant_id,
            token=config.token,
            max_retries=config.max_retries,
            http_client=config._http_client,
        )
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
        """Execute semantic search through the fresh OriaHS REST contract."""
        query = arguments.get("query", "")
        top_k = arguments.get("top_k", 10)
        filters = arguments.get("filters", {})

        if not query:
            raise ValueError("Query is required")

        if top_k < 1 or top_k > 50:
            raise ValueError("top_k must be between 1 and 50")

        try:
            results = await self.client.search(query, top_k=top_k, filters=filters)
        except httpx.HTTPStatusError as e:
            error_msg = f"OriaHS API error: {e.response.status_code}"
            if e.response.text:
                error_msg += f" - {e.response.text}"
            raise ValueError(error_msg) from e
        except Exception as e:
            raise ValueError(f"Search failed: {str(e)}") from e

        return CallToolResult(
            content=[
                TextContent(
                    type="text",
                    text=json.dumps(result, ensure_ascii=False),
                )
                for result in results
            ]
        )

    async def _call_index_file(self, arguments: dict[str, Any]) -> CallToolResult:
        """Index one file using the required OriaHS ``IndexRequest`` fields."""
        file_path = arguments.get("file_path", "")

        if not file_path:
            raise ValueError("File path is required")

        try:
            result = await self.client.index_file(file_path)
        except httpx.HTTPStatusError as e:
            error_msg = f"OriaHS API error: {e.response.status_code}"
            if e.response.text:
                error_msg += f" - {e.response.text}"
            raise ValueError(error_msg) from e
        except Exception as e:
            raise ValueError(f"File indexing failed: {str(e)}") from e

        return CallToolResult(
            content=[
                TextContent(type="text", text=json.dumps(result, ensure_ascii=False))
            ]
        )

    async def _call_index_directory(self, arguments: dict[str, Any]) -> CallToolResult:
        """Index a directory file-by-file through the OriaHS ``/index`` API."""
        directory_path = arguments.get("directory_path", "")
        recursive = arguments.get("recursive", False)

        if not directory_path:
            raise ValueError("Directory path is required")

        try:
            result = await self.client.index_directory(directory_path, recursive)
        except httpx.HTTPStatusError as e:
            error_msg = f"OriaHS API error: {e.response.status_code}"
            if e.response.text:
                error_msg += f" - {e.response.text}"
            raise ValueError(error_msg) from e
        except Exception as e:
            raise ValueError(f"Directory indexing failed: {str(e)}") from e

        return CallToolResult(
            content=[
                TextContent(type="text", text=json.dumps(result, ensure_ascii=False))
            ]
        )

    async def health_check(self) -> bool:
        """Probe the real OriaHS readiness endpoint (503 counts as unhealthy)."""
        return (await self.client.health()).ok


async def run_server(config: OriaHSConfig):
    """Run the OriaHS MCP server (stdio transport)."""
    server = OriaHSMCPServer(config)

    async with stdio_server() as (read_stream, write_stream):
        await server.server.run(read_stream, write_stream)


class CallPayload(BaseModel):
    """Body of ``POST /call`` — the shape app/mcp/client.py posts."""

    name: str
    arguments: dict[str, Any] = {}


def create_http_app(config: OriaHSConfig) -> FastAPI:
    """HTTP transport matching ``app/mcp/client.py``'s REST contract (B-02).

    ``GET /health`` is **pure liveness**: the compose ``api`` service waits on
    ``oriahs-mcp: service_healthy`` while the OriaHS backend itself may
    legitimately be absent from the stack — probing the backend here would
    deadlock the whole app profile. Backend failures surface per call as
    HTTP 502 (``MCPClient`` raises ``raise_for_status`` → the tools report
    ``Search failed`` / ``Indexing failed`` and the recover node takes over).

    ``POST /call`` unwraps each ``TextContent`` block: ``TextContent.text``
    carries a JSON payload (``{"score", "path", ...}``) which the client's
    callers (``oriahs_search`` / ``oriahs_index``) expect as a flat dict, not
    as an MCP content envelope.
    """
    server = OriaHSMCPServer(config)
    app = FastAPI(title="oriahs-mcp", version="1.0.0")

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/health/ready")
    async def ready() -> dict[str, Any]:
        result = await server.client.health()
        if not result.ok:
            raise HTTPException(
                status_code=503, detail=result.error or "OriaHS unavailable"
            )
        return {
            "status": result.status,
            "checks": result.checks,
            "latency_ms": result.latency_ms,
        }

    @app.get("/tools")
    async def list_tools_http() -> dict[str, Any]:
        result = await server.list_tools()
        return {"tools": [tool.model_dump() for tool in result.tools]}

    @app.post("/call")
    async def call_tool_http(payload: CallPayload) -> dict[str, Any]:
        request = CallToolRequest(
            params={"name": payload.name, "arguments": payload.arguments}
        )
        result = await server.call_tool(request)
        if result.isError:
            detail = (
                " | ".join(
                    getattr(block, "text", str(block)) for block in result.content
                )
                or f"tool {payload.name!r} failed"
            )
            logger.error("OriaHS tool %r failed: %s", payload.name, detail)
            raise HTTPException(status_code=502, detail=detail)

        content: list[Any] = []
        for block in result.content:
            text = getattr(block, "text", None)
            if text is None:
                content.append(block.model_dump())
                continue
            try:
                content.append(json.loads(text))
            except (json.JSONDecodeError, TypeError):
                content.append(text)
        return {"content": content}

    return app


def _build_config() -> OriaHSConfig:
    """Build the backend config from the single effective Settings source."""
    settings = get_settings()
    token = (
        settings.oriahs_token.get_secret_value()
        if settings.oriahs_token is not None
        else None
    )
    return OriaHSConfig(
        base_url=settings.oriahs_url,
        token=token,
        timeout=settings.oriahs_timeout_s,
        max_retries=settings.mcp_max_retries,
        tenant_id=settings.oriahs_tenant_id,
    )


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        prog="python -m app.mcp.oriahs_mcp",
        description=(
            "OriaHS MCP server. HTTP transport by default "
            "(/health, /tools, /call for app/mcp/client.py); "
            "--stdio runs the classic MCP stdio transport."
        ),
    )
    parser.add_argument(
        "--stdio",
        action="store_true",
        help="run the MCP stdio transport instead of HTTP",
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="HTTP bind address (default 127.0.0.1; containers use 0.0.0.0)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8765,
        help="HTTP port (default 8765)",
    )
    args = parser.parse_args()

    config = _build_config()

    if args.stdio:

        async def _stdio_main() -> None:
            try:
                await run_server(config)
            except KeyboardInterrupt:
                print("Shutting down OriaHS MCP server...")
            finally:
                await config.close()

        asyncio.run(_stdio_main())
    else:
        import uvicorn

        uvicorn.run(create_http_app(config), host=args.host, port=args.port)
