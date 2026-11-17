"""Tool: ukb_lookup - unified knowledge bus retrieval (B-27).

Provides a unified interface to search across multiple knowledge sources:
- LSP (code definitions, references, symbols, etc.)
- Memory (semantic and lexical search)
- Code (code patterns and implementations)
- KB (knowledge base facts and documentation)

Contract (B-27)::

    ukb_lookup(query, capability=None, top_k=5) -> list[dict]

Behaviour:

* query: The search query string
* capability: Optional specific capability to route to (e.g., "lsp.def", "memory.semantic")
* top_k: Maximum number of results to return (default: 5)
* Returns: List of RetrievedChunk dictionaries with content, source, score, metadata
* Routing: Explicit capability → specific namespace; default → parallel lookup all
* Merge & Dedup: Results are merged and deduplicated by content hash
* Caching: Results are cached for 5 minutes to improve performance
* Error Handling: Graceful fallback to empty results on namespace failures

Usage::

    from app.tools.ukb import ukb_lookup

    # Explicit capability routing
    await ukb_lookup.ainvoke({"query": "UserService.create", "capability": "lsp.def"})

    # Default parallel lookup
    await ukb_lookup.ainvoke({"query": "memory-tier design"})

    # Custom top_k
    await ukb_lookup.ainvoke({"query": "python patterns", "top_k": 10})
"""

from __future__ import annotations

import logging
from typing import Any

from langchain_core.tools import BaseTool

from app.core.ukb.router import get_ukb_router

logger = logging.getLogger(__name__)


class UKBLookupInput(BaseTool):
    """Input schema for UKB lookup tool."""

    name: str = "ukb_lookup"
    description: str = (
        "Unified knowledge bus retrieval across LSP, memory, code, and KB namespaces. "
        "Use 'capability' for specific routing (e.g., 'lsp.def', 'memory.semantic') "
        "or omit for parallel lookup across all namespaces."
    )
    args_schema: type = dict

    def _run(
        self,
        query: str,
        capability: str | None = None,
        top_k: int = 5,
        **kwargs: Any,
    ) -> list[dict[str, Any]]:
        """Synchronous wrapper - delegates to async method."""
        import asyncio

        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

        return loop.run_until_complete(
            self._arun(query=query, capability=capability, top_k=top_k, **kwargs)
        )

    async def _arun(
        self,
        query: str,
        capability: str | None = None,
        top_k: int = 5,
        **kwargs: Any,
    ) -> list[dict[str, Any]]:
        """Execute UKB lookup."""
        if not query or not query.strip():
            logger.warning("Empty query provided to ukb_lookup")
            return []

        try:
            ukb_router = get_ukb_router()
            results = await ukb_router.lookup(
                query=query,
                capability=capability,
                top_k=top_k,
                use_cache=True,
            )

            logger.info(
                f"UKB lookup returned {len(results)} results for query: {query}"
            )

            # Convert RetrievedChunk objects to dictionaries
            return [result.to_dict() for result in results]

        except Exception as e:
            logger.error(f"UKB lookup failed for query '{query}': {e}")
            return []


# Global instance
ukb_lookup = UKBLookupInput()
