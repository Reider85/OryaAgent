"""UKB Router - Unified Knowledge Bus for LSP + Memory + Code + KB."""

from __future__ import annotations

import asyncio
import hashlib
import logging
from typing import Any, Dict, List, Optional, Union

from app.core.observability.spans import emit_span

logger = logging.getLogger(__name__)


class RetrievedChunk:
    """Represents a retrieved chunk from knowledge sources."""

    def __init__(
        self,
        content: str,
        source: str,
        score: float = 1.0,
        metadata: Dict[str, Any] = None,
        chunk_id: Optional[str] = None,
    ):
        self.content = content
        self.source = source
        self.score = score
        self.metadata = metadata or {}
        self.chunk_id = chunk_id or self._generate_chunk_id()

    def _generate_chunk_id(self) -> str:
        """Generate unique chunk ID."""
        content_hash = hashlib.sha256(self.content.encode()).hexdigest()
        return f"{self.source}_{content_hash[:8]}"

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "content": self.content,
            "source": self.source,
            "score": self.score,
            "metadata": self.metadata,
            "chunk_id": self.chunk_id,
        }


class UKBRouter:
    """Unified Knowledge Bus router for LSP + Memory + Code + KB."""

    def __init__(self):
        self.namespaces = {
            "lsp": self._lsp_namespace,
            "memory": self._memory_namespace,  # Mock in BETA, full in PROD
            "code": self._code_namespace,  # Mock in BETA
            "kb": self._kb_namespace,  # Mock in BETA
        }

        # Routing rules
        self.routing_rules = {
            "lsp.def": "lsp",
            "lsp.hover": "lsp",
            "lsp.refs": "lsp",
            "lsp.symbol_search": "lsp",
            "lsp.rename": "lsp",
            "lsp.diagnostics": "lsp",
            "lsp.codeAction": "lsp",
            "memory.semantic": "memory",
            "memory.lexical": "memory",
            "code.search": "code",
            "kb.fact": "kb",
            "kb.concept": "kb",
        }

        # Cache for results
        self._cache: Dict[str, List[RetrievedChunk]] = {}
        self._cache_ttl = 300  # 5 minutes

    async def lookup(
        self,
        query: str,
        capability: Optional[str] = None,
        filters: Optional[Dict[str, Any]] = None,
        top_k: int = 5,
        use_cache: bool = True,
    ) -> List[RetrievedChunk]:
        """Unified lookup across all namespaces.

        Args:
            query: Search query
            capability: Specific capability to route to (e.g., "lsp.def", "memory.semantic")
            filters: Filter criteria for results
            top_k: Maximum number of results
            use_cache: Whether to use cached results

        Returns:
            List of retrieved chunks, merged and deduplicated
        """
        with emit_span(
            "ukb.lookup",
            {
                "query": query,
                "capability": capability,
                "top_k": top_k,
                "use_cache": use_cache,
            },
        ) as span:
            # Check cache first
            cache_key = self._generate_cache_key(query, capability, filters)
            if use_cache and cache_key in self._cache:
                cached_results = self._cache[cache_key]
                if len(cached_results) > 0:
                    logger.debug(f"Cache hit for query: {query}")
                    span.set_attribute("cache_hit", True)
                    return self._filter_and_rank(cached_results, filters, top_k)

            # Determine routing
            if capability:
                # Explicit capability routing
                namespace = self._resolve_capability_to_namespace(capability)
                results = await self._lookup_single_namespace(
                    query, namespace, capability, filters
                )
            else:
                # Default: parallel lookup all namespaces
                results = await self._lookup_all_namespaces(query, filters)

            # Merge and deduplicate
            merged_results = self._merge_and_dedup(results)

            # Filter and rank
            final_results = self._filter_and_rank(merged_results, filters, top_k)

            # Cache results
            if use_cache:
                self._cache[cache_key] = final_results

            span.set_attribute("total_results", len(final_results))
            span.set_attribute("cache_key", cache_key)
            span.set_attribute("merged_count", len(merged_results))

            return final_results

    async def _lookup_single_namespace(
        self,
        query: str,
        namespace: str,
        capability: str,
        filters: Optional[Dict[str, Any]] = None,
    ) -> List[RetrievedChunk]:
        """Lookup in a single namespace."""
        if namespace not in self.namespaces:
            logger.warning(f"Unknown namespace: {namespace}")
            return []

        lookup_func = self.namespaces[namespace]
        try:
            results = await lookup_func(query, capability, filters)
            logger.debug(f"Found {len(results)} results in {namespace} namespace")
            return results
        except Exception as e:
            logger.error(f"Error in {namespace} namespace lookup: {e}")
            return []

    async def _lookup_all_namespaces(
        self,
        query: str,
        filters: Optional[Dict[str, Any]] = None,
    ) -> List[RetrievedChunk]:
        """Lookup in all namespaces in parallel."""
        tasks = []

        for namespace in self.namespaces:
            task = self._lookup_single_namespace(query, namespace, None, filters)
            tasks.append(task)

        # Run all lookups in parallel
        all_results = await asyncio.gather(*tasks, return_exceptions=True)

        # Flatten results
        results = []
        for namespace_result in all_results:
            if isinstance(namespace_result, Exception):
                logger.error(f"Namespace lookup failed: {namespace_result}")
            elif namespace_result:
                results.extend(namespace_result)

        return results

    def _resolve_capability_to_namespace(self, capability: str) -> str:
        """Resolve capability to namespace."""
        return self.routing_rules.get(capability, "default")

    def _merge_and_dedup(self, results: List[RetrievedChunk]) -> List[RetrievedChunk]:
        """Merge results and remove duplicates."""
        seen_ids = set()
        unique_results = []

        for result in results:
            if result.chunk_id not in seen_ids:
                seen_ids.add(result.chunk_id)
                unique_results.append(result)

        return unique_results

    def _filter_and_rank(
        self,
        results: List[RetrievedChunk],
        filters: Optional[Dict[str, Any]] = None,
        top_k: int = 5,
    ) -> List[RetrievedChunk]:
        """Filter and rank results."""
        if not results:
            return []

        # Apply filters
        if filters:
            filtered_results = []
            for result in results:
                if self._matches_filters(result, filters):
                    filtered_results.append(result)
            results = filtered_results

        # Sort by score
        results.sort(key=lambda x: x.score, reverse=True)

        # Return top k
        return results[:top_k]

    def _matches_filters(self, result: RetrievedChunk, filters: Dict[str, Any]) -> bool:
        """Check if result matches filters."""
        for key, value in filters.items():
            if key == "source" and result.source != value:
                return False
            elif key == "min_score" and result.score < value:
                return False
            elif key == "max_score" and result.score > value:
                return False
            elif key in result.metadata and result.metadata[key] != value:
                return False
        return True

    def _generate_cache_key(
        self,
        query: str,
        capability: Optional[str],
        filters: Optional[Dict[str, Any]],
    ) -> str:
        """Generate cache key."""
        import json

        key_data = {
            "query": query,
            "capability": capability,
            "filters": filters,
        }
        return hashlib.md5(json.dumps(key_data).encode()).hexdigest()

    async def _lsp_namespace(
        self,
        query: str,
        capability: Optional[str],
        filters: Optional[Dict[str, Any]] = None,
    ) -> List[RetrievedChunk]:
        """LSP namespace lookup."""
        from app.core.lsp.bus import get_lsp_bus

        lsp_bus = get_lsp_bus()
        results = []

        try:
            if capability == "lsp.def":
                # Mock definition lookup
                results.append(
                    RetrievedChunk(
                        content=f"Definition of '{query}' found in main.py at line 25",
                        source="lsp",
                        score=0.9,
                        metadata={
                            "file": "main.py",
                            "line": 25,
                            "capability": "definition",
                        },
                    )
                )
            elif capability == "lsp.hover":
                # Mock hover lookup
                results.append(
                    RetrievedChunk(
                        content=f"Function {query}(): string - Returns a formatted string",
                        source="lsp",
                        score=0.95,
                        metadata={
                            "file": "utils.py",
                            "line": 10,
                            "capability": "hover",
                        },
                    )
                )
            elif capability == "lsp.refs":
                # Mock references lookup
                results.append(
                    RetrievedChunk(
                        content=f"Reference to '{query}' in main.py at line 42",
                        source="lsp",
                        score=0.8,
                        metadata={
                            "file": "main.py",
                            "line": 42,
                            "capability": "reference",
                        },
                    )
                )
            elif capability == "lsp.symbol_search":
                # Mock symbol search
                results.append(
                    RetrievedChunk(
                        content=f"Class {query} - Main application class",
                        source="lsp",
                        score=0.9,
                        metadata={"file": "app.py", "line": 1, "capability": "symbol"},
                    )
                )
            else:
                # General LSP lookup
                results.append(
                    RetrievedChunk(
                        content=f"LSP result for '{query}'",
                        source="lsp",
                        score=0.7,
                        metadata={"capability": capability or "general"},
                    )
                )

        except Exception as e:
            logger.error(f"LSP namespace lookup failed: {e}")

        return results

    async def _memory_namespace(
        self,
        query: str,
        capability: Optional[str],
        filters: Optional[Dict[str, Any]] = None,
    ) -> List[RetrievedChunk]:
        """Memory namespace lookup (mock in BETA, full in PROD)."""
        results = []

        try:
            if capability == "memory.semantic":
                # Mock semantic memory search
                results.append(
                    RetrievedChunk(
                        content=f"Semantic memory: User prefers Python for data analysis tasks",
                        source="memory",
                        score=0.8,
                        metadata={"type": "semantic", "capability": "preference"},
                    )
                )
            elif capability == "memory.lexical":
                # Mock lexical memory search
                results.append(
                    RetrievedChunk(
                        content=f"Lexical memory: Previous session discussed pandas DataFrame operations",
                        source="memory",
                        score=0.7,
                        metadata={"type": "lexical", "capability": "context"},
                    )
                )
            else:
                # General memory lookup
                results.append(
                    RetrievedChunk(
                        content=f"Memory result for '{query}'",
                        source="memory",
                        score=0.6,
                        metadata={"capability": capability or "general"},
                    )
                )

        except Exception as e:
            logger.error(f"Memory namespace lookup failed: {e}")

        return results

    async def _code_namespace(
        self,
        query: str,
        capability: Optional[str],
        filters: Optional[Dict[str, Any]] = None,
    ) -> List[RetrievedChunk]:
        """Code namespace lookup (mock in BETA)."""
        results = []

        try:
            # Mock code search
            results.append(
                RetrievedChunk(
                    content=f"Code pattern: {query} - Common implementation found in utils.py",
                    source="code",
                    score=0.75,
                    metadata={"file": "utils.py", "capability": "pattern"},
                )
            )

        except Exception as e:
            logger.error(f"Code namespace lookup failed: {e}")

        return results

    async def _kb_namespace(
        self,
        query: str,
        capability: Optional[str],
        filters: Optional[Dict[str, Any]] = None,
    ) -> List[RetrievedChunk]:
        """KB namespace lookup (mock in BETA)."""
        results = []

        try:
            # Mock knowledge base lookup
            results.append(
                RetrievedChunk(
                    content=f"KB fact: {query} - Documentation reference available",
                    source="kb",
                    score=0.85,
                    metadata={"type": "fact", "capability": "documentation"},
                )
            )

        except Exception as e:
            logger.error(f"KB namespace lookup failed: {e}")

        return results

    def clear_cache(self) -> None:
        """Clear the result cache."""
        self._cache.clear()
        logger.info("UKB cache cleared")

    def get_cache_stats(self) -> Dict[str, Any]:
        """Get cache statistics."""
        return {
            "cache_size": len(self._cache),
            "cache_keys": list(self._cache.keys()),
        }

    def get_supported_namespaces(self) -> List[str]:
        """Get list of supported namespaces."""
        return list(self.namespaces.keys())

    def get_supported_capabilities(self) -> List[str]:
        """Get list of supported capabilities."""
        return list(self.routing_rules.keys())


# Global UKB router instance
_ukb_router: Optional[UKBRouter] = None


def get_ukb_router() -> UKBRouter:
    """Get global UKB router instance."""
    global _ukb_router
    if _ukb_router is None:
        _ukb_router = UKBRouter()
    return _ukb_router


def initialize_ukb_router() -> UKBRouter:
    """Initialize global UKB router."""
    global _ukb_router
    _ukb_router = UKBRouter()
    return _ukb_router
