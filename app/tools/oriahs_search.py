"""Tool: oriahs_search - semantic codebase search through MCP (B-02).

Contract: oriahs_search(query, top_k=10, filters=None) -> str

Behaviour:
* Semantic search using OriaHS hybrid retrieval (sparse + dense vectors)
* MCP integration through oriahs-mcp server
* Injection detection on search results
* Caching for repeated queries
* Error handling for MCP server unavailability
"""

from __future__ import annotations

import json
import logging
import time
from typing import Annotated, Any

from langchain_core.tools import InjectedToolArg, ToolException, tool
from langgraph.prebuilt import ToolRuntime

from app.core.cache import build_cache_key, from_cache_result, get_cache
from app.core.mcp_config import get_mcp_config
from app.core.observability.metrics import (
    MCPMetricsContext,
    SemanticSearchMetricsContext,
    increment_mcp_connection_error,
    increment_semantic_search,
    observe_semantic_search_results_count,
    set_mcp_server_health,
)
from app.core.observability.spans import (
    emit_mcp_span,
    emit_semantic_search_span,
)
from app.core.security import (
    check_injection,
    injection_warning,
    sanitize_untrusted,
    session_id_from_config,
)
from app.mcp.client import get_mcp_client

logger = logging.getLogger(__name__)


def _format_search_results(results: list[dict[str, Any]]) -> str:
    """Format OriaHS search results for LLM consumption."""
    if not results:
        return "No results found."

    formatted = []
    for i, result in enumerate(results, 1):
        formatted.append(
            f"[{i}] Score: {result.get('score', 0):.3f}\n"
            f"Path: {result.get('path', 'unknown')}\n"
            f"Type: {result.get('type', 'unknown')}\n"
            f"Content: {result.get('content', '')[:500]}...\n"
        )
    return "\n".join(formatted)


@tool
async def oriahs_search(
    query: Annotated[str, "Natural language search query for semantic codebase search"],
    top_k: Annotated[
        int, "Maximum number of results to return (default: 10, max: 50)"
    ] = 10,
    filters: Annotated[
        dict, "Optional filters for search (e.g., file type, date range)"
    ] = None,
    runtime: Annotated[
        ToolRuntime | None,
        InjectedToolArg,
        "Injected by ToolNode; carries tool_call_id for caching",
    ] = None,
) -> str:
    """Search the codebase semantically using OriaHS through MCP.

    Performs hybrid search combining lexical and semantic matching.
    Returns relevant code snippets with scores and metadata.
    """
    mcp_config = get_mcp_config()

    # Validate inputs
    if not query.strip():
        increment_semantic_search("error", "mcp")
        emit_semantic_search_span(
            query=query,
            top_k=top_k,
            results_count=0,
            status="error",
            error="Query cannot be empty",
        )
        raise ToolException("Query cannot be empty")

    if top_k < 1 or top_k > 50:
        increment_semantic_search("error", "mcp")
        emit_semantic_search_span(
            query=query,
            top_k=top_k,
            results_count=0,
            status="error",
            error="top_k must be between 1 and 50",
        )
        raise ToolException("top_k must be between 1 and 50")

    # Build cache key
    cache_key = build_cache_key(
        "oriahs_search",
        {"query": query, "top_k": top_k, "filters": filters},
        None,  # No file-based caching for search results
    )

    # Check cache first
    cache = get_cache()
    cached_result = await cache.get(cache_key)
    if cached_result is not None:
        result = from_cache_result(
            cached_result,
            name="oriahs_search",
            tool_call_id=getattr(runtime, "tool_call_id", None),
        )
        increment_semantic_search("success", "cache")
        observe_semantic_search_results_count(
            len(result.split("\n")) if result else 0, "success"
        )
        emit_semantic_search_span(
            query=query,
            top_k=top_k,
            results_count=len(result.split("\n")) if result else 0,
            status="success",
            source="cache",
        )
        emit_mcp_span(
            tool_name="hybrid_search",
            server_url=mcp_config.server_url,
            status="success",
            source="cache",
        )
        return result

    # Use metrics context for automatic metric collection
    with SemanticSearchMetricsContext(
        query, top_k, mcp_config.server_url
    ) as metrics_context:
        try:
            # Get MCP client
            mcp_client = get_mcp_client()

            # Check MCP server health first
            health_check_start = time.time()
            is_healthy = await mcp_client.health_check()
            (time.time() - health_check_start) * 1000

            set_mcp_server_health(mcp_config.server_url, is_healthy)

            if not is_healthy:
                increment_mcp_connection_error(
                    mcp_config.server_url, "health_check_failed"
                )
                raise ToolException("OriaHS MCP server is not available")

            # Execute search through MCP with metrics context
            with MCPMetricsContext(
                "hybrid_search", mcp_config.server_url
            ) as mcp_context:
                results = await mcp_client.call_tool(
                    "hybrid_search",
                    {"query": query, "top_k": top_k, "filters": filters or {}},
                )
                mcp_context.status = "success"

            # Parse results
            parsed_results = []
            for result in results:
                try:
                    if isinstance(result, dict) and "score" in result:
                        parsed_results.append(result)
                    elif isinstance(result, str):
                        # Parse JSON string result
                        parsed = json.loads(result)
                        if isinstance(parsed, dict):
                            parsed_results.append(parsed)
                except (json.JSONDecodeError, TypeError):
                    logger.warning(f"Failed to parse search result: {result}")
                    continue

            # Update metrics with results count
            metrics_context.results_count = len(parsed_results)

            # Format results
            formatted_results = _format_search_results(parsed_results)

            # Apply security checks
            injection_check = check_injection(formatted_results, source="oriahs_search")
            has_injection = False
            if injection_check and injection_warning in injection_check:
                has_injection = True
                # Add injection warning to results
                formatted_results += f"\n{injection_check}"
            metrics_context.has_injection = has_injection

            # Apply untrusted content framing
            sanitized_results = sanitize_untrusted(
                formatted_results,
                source="oriahs_search",
                session_id=session_id_from_config(getattr(runtime, "config", None)),
            )

            # Cache results
            await cache.set(cache_key, sanitized_results, ttl=3600)  # 1 hour TTL

            # Update metrics with final status
            metrics_context.status = "success"

            # Emit spans
            emit_semantic_search_span(
                query=query,
                top_k=top_k,
                results_count=len(parsed_results),
                status="success",
                has_injection=has_injection,
                source="mcp",
            )
            emit_mcp_span(
                tool_name="hybrid_search",
                server_url=mcp_config.server_url,
                status="success",
                has_injection=has_injection,
            )

            return sanitized_results

        except Exception as e:
            # Log the error for debugging
            logger.error(f"Semantic search failed: {e}")

            # Update metrics with error
            metrics_context.status = "error"

            # Fall back to lexical search if MCP fails
            if "not available" in str(e).lower() or "connection" in str(e).lower():
                logger.warning("MCP server unavailable, semantic search failed")
                increment_mcp_connection_error(
                    mcp_config.server_url, "server_unavailable"
                )
                raise ToolException(
                    f"Semantic search unavailable: {str(e)}. "
                    "Please try a lexical search with grep tool instead."
                )
            else:
                increment_mcp_connection_error(mcp_config.server_url, "operation_error")
                raise ToolException(f"Search failed: {str(e)}")


# Alternative fallback function for when MCP is completely unavailable
def _fallback_lexical_search(query: str, top_k: int = 10) -> str:
    """Fallback to lexical search using grep when MCP is unavailable."""
    # This would integrate with the existing grep tool
    # For now, return a helpful message
    return (
        f"Semantic search is currently unavailable. "
        f"Please use the grep tool for lexical search: "
        f'grep("{query}", max_matches={top_k})'
    )
