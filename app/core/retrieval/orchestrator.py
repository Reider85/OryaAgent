"""RetrievalOrchestrator - Coordinates retrieval across multiple knowledge sources."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, Optional, Union, Callable

from app.core.observability.spans import emit_span
from app.core.ukb.router import get_ukb_router, RetrievedChunk

logger = logging.getLogger(__name__)


class RetrievalRequest:
    """Represents a retrieval request."""

    def __init__(
        self,
        query: str,
        capability: Optional[str] = None,
        filters: Optional[Dict[str, Any]] = None,
        top_k: int = 5,
        strategies: Optional[List[str]] = None,
        context: Optional[Dict[str, Any]] = None,
    ):
        self.query = query
        self.capability = capability
        self.filters = filters or {}
        self.top_k = top_k
        self.strategies = strategies or ["ukb", "semantic", "lexical"]
        self.context = context or {}


class RetrievalStrategy:
    """Base class for retrieval strategies."""

    def __init__(self, name: str):
        self.name = name

    async def retrieve(
        self,
        request: RetrievalRequest,
        ukb_router: Any,
    ) -> List[RetrievedChunk]:
        """Execute retrieval strategy."""
        raise NotImplementedError


class UKBRetrievalStrategy(RetrievalStrategy):
    """UKB-based retrieval strategy."""

    def __init__(self):
        super().__init__("ukb")

    async def retrieve(
        self,
        request: RetrievalRequest,
        ukb_router: Any,
    ) -> List[RetrievedChunk]:
        """Retrieve using UKB router."""
        with emit_span(
            "retrieval.ukb", {"query": request.query, "capability": request.capability}
        ):
            return await ukb_router.lookup(
                query=request.query,
                capability=request.capability,
                filters=request.filters,
                top_k=request.top_k,
                use_cache=True,
            )


class SemanticRetrievalStrategy(RetrievalStrategy):
    """Semantic retrieval strategy."""

    def __init__(self):
        super().__init__("semantic")

    async def retrieve(
        self,
        request: RetrievalRequest,
        ukb_router: Any,
    ) -> List[RetrievedChunk]:
        """Retrieve using semantic search."""
        with emit_span("retrieval.semantic", {"query": request.query}):
            # Use memory semantic capability
            return await ukb_router.lookup(
                query=request.query,
                capability="memory.semantic",
                filters=request.filters,
                top_k=request.top_k,
                use_cache=True,
            )


class LexicalRetrievalStrategy(RetrievalStrategy):
    """Lexical retrieval strategy."""

    def __init__(self):
        super().__init__("lexical")

    async def retrieve(
        self,
        request: RetrievalRequest,
        ukb_router: Any,
    ) -> List[RetrievedChunk]:
        """Retrieve using lexical search."""
        with emit_span("retrieval.lexical", {"query": request.query}):
            # Use memory lexical capability
            return await ukb_router.lookup(
                query=request.query,
                capability="memory.lexical",
                filters=request.filters,
                top_k=request.top_k,
                use_cache=True,
            )


class HybridRetrievalStrategy(RetrievalStrategy):
    """Hybrid retrieval strategy combining multiple strategies."""

    def __init__(self, strategies: List[RetrievalStrategy]):
        super().__init__("hybrid")
        self.strategies = strategies

    async def retrieve(
        self,
        request: RetrievalRequest,
        ukb_router: Any,
    ) -> List[RetrievedChunk]:
        """Retrieve using multiple strategies."""
        with emit_span(
            "retrieval.hybrid",
            {"query": request.query, "strategies": [s.name for s in self.strategies]},
        ):
            # Execute all strategies in parallel
            tasks = []
            for strategy in self.strategies:
                task = strategy.retrieve(request, ukb_router)
                tasks.append(task)

            # Wait for all strategies to complete
            all_results = await asyncio.gather(*tasks, return_exceptions=True)

            # Flatten and deduplicate results
            results = []
            for strategy_result in all_results:
                if isinstance(strategy_result, Exception):
                    logger.error(f"Strategy {strategy.name} failed: {strategy_result}")
                elif strategy_result:
                    results.extend(strategy_result)

            # Remove duplicates by chunk_id
            seen_ids = set()
            unique_results = []
            for result in results:
                if result.chunk_id not in seen_ids:
                    seen_ids.add(result.chunk_id)
                    unique_results.append(result)

            # Sort by score
            unique_results.sort(key=lambda x: x.score, reverse=True)

            return unique_results[: request.top_k]


class RetrievalOrchestrator:
    """Coordinates retrieval across multiple knowledge sources."""

    def __init__(self):
        self.ukb_router = get_ukb_router()

        # Available strategies
        self.strategies = {
            "ukb": UKBRetrievalStrategy(),
            "semantic": SemanticRetrievalStrategy(),
            "lexical": LexicalRetrievalStrategy(),
            "hybrid": HybridRetrievalStrategy(
                [
                    UKBRetrievalStrategy(),
                    SemanticRetrievalStrategy(),
                    LexicalRetrievalStrategy(),
                ]
            ),
        }

        # Strategy selection rules
        self.strategy_rules = {
            "lsp.def": ["ukb"],
            "lsp.hover": ["ukb"],
            "lsp.refs": ["ukb"],
            "lsp.symbol_search": ["ukb"],
            "lsp.rename": ["ukb"],
            "lsp.diagnostics": ["ukb"],
            "lsp.codeAction": ["ukb"],
            "memory.semantic": ["semantic"],
            "memory.lexical": ["lexical"],
            "code.search": ["hybrid"],
            "kb.fact": ["ukb"],
            "kb.concept": ["ukb"],
            "default": ["hybrid"],
        }

        # Cache for results
        self._cache: Dict[str, List[RetrievedChunk]] = {}
        self._cache_ttl = 300  # 5 minutes

    async def retrieve(
        self,
        query: str,
        capability: Optional[str] = None,
        filters: Optional[Dict[str, Any]] = None,
        top_k: int = 5,
        strategies: Optional[List[str]] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> List[RetrievedChunk]:
        """Execute retrieval orchestration.

        Args:
            query: Search query
            capability: Specific capability to retrieve for
            filters: Filter criteria for results
            top_k: Maximum number of results
            strategies: Specific strategies to use (overrides defaults)
            context: Additional context for retrieval

        Returns:
            List of retrieved chunks, processed and ranked
        """
        with emit_span(
            "retrieval.orchestrator",
            {
                "query": query,
                "capability": capability,
                "top_k": top_k,
                "strategies": strategies,
            },
        ) as span:
            # Create retrieval request
            request = RetrievalRequest(
                query=query,
                capability=capability,
                filters=filters,
                top_k=top_k,
                strategies=strategies,
                context=context,
            )

            # Determine strategies to use
            if strategies:
                selected_strategies = strategies
            else:
                selected_strategies = self._select_strategies(capability)

            # Execute strategies in parallel
            results = await self._execute_strategies(selected_strategies, request)

            # Post-process results
            processed_results = self._post_process_results(results, request)

            # Cache results
            cache_key = self._generate_cache_key(query, capability, filters, strategies)
            self._cache[cache_key] = processed_results

            span.set_attribute("total_results", len(processed_results))
            span.set_attribute("cache_key", cache_key)
            span.set_attribute("selected_strategies", selected_strategies)

            return processed_results

    def _select_strategies(self, capability: Optional[str]) -> List[str]:
        """Select appropriate strategies based on capability."""
        if capability:
            return self.strategy_rules.get(capability, self.strategy_rules["default"])
        return self.strategy_rules["default"]

    async def _execute_strategies(
        self,
        strategy_names: List[str],
        request: RetrievalRequest,
    ) -> List[RetrievedChunk]:
        """Execute multiple retrieval strategies."""
        tasks = []

        for strategy_name in strategy_names:
            if strategy_name in self.strategies:
                strategy = self.strategies[strategy_name]
                task = strategy.retrieve(request, self.ukb_router)
                tasks.append((strategy_name, task))
            else:
                logger.warning(f"Unknown strategy: {strategy_name}")

        # Execute all strategies
        results = []
        for strategy_name, task in tasks:
            try:
                strategy_results = await task
                logger.debug(
                    f"Strategy {strategy_name} returned {len(strategy_results)} results"
                )
                results.extend(strategy_results)
            except Exception as e:
                logger.error(f"Strategy {strategy_name} failed: {e}")

        return results

    def _post_process_results(
        self,
        results: List[RetrievedChunk],
        request: RetrievalRequest,
    ) -> List[RetrievedChunk]:
        """Post-process retrieval results."""
        if not results:
            return []

        # Apply context-aware scoring
        if request.context:
            results = self._apply_context_scoring(results, request.context)

        # Apply filters
        if request.filters:
            results = [r for r in results if self._matches_filters(r, request.filters)]

        # Sort by score
        results.sort(key=lambda x: x.score, reverse=True)

        # Return top k
        return results[: request.top_k]

    def _apply_context_scoring(
        self,
        results: List[RetrievedChunk],
        context: Dict[str, Any],
    ) -> List[RetrievedChunk]:
        """Apply context-aware scoring to results."""
        # Example: Boost scores based on file type relevance
        if "file_type" in context:
            file_type = context["file_type"]
            for result in results:
                if result.metadata.get("file", "").endswith(f".{file_type}"):
                    result.score *= 1.2  # Boost score by 20%

        # Example: Boost scores based on language relevance
        if "language" in context:
            language = context["language"]
            for result in results:
                if result.source == language:
                    result.score *= 1.1  # Boost score by 10%

        return results

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
        strategies: Optional[List[str]],
    ) -> str:
        """Generate cache key."""
        import json

        key_data = {
            "query": query,
            "capability": capability,
            "filters": filters,
            "strategies": strategies,
        }
        return hashlib.md5(json.dumps(key_data).encode()).hexdigest()

    def add_strategy(self, name: str, strategy: RetrievalStrategy) -> None:
        """Add a new retrieval strategy."""
        self.strategies[name] = strategy
        logger.info(f"Added retrieval strategy: {name}")

    def remove_strategy(self, name: str) -> None:
        """Remove a retrieval strategy."""
        if name in self.strategies:
            del self.strategies[name]
            logger.info(f"Removed retrieval strategy: {name}")

    def get_available_strategies(self) -> List[str]:
        """Get list of available strategies."""
        return list(self.strategies.keys())

    def get_supported_capabilities(self) -> List[str]:
        """Get list of supported capabilities."""
        return list(self.strategy_rules.keys())

    def clear_cache(self) -> None:
        """Clear the result cache."""
        self._cache.clear()
        logger.info("Retrieval orchestrator cache cleared")

    def get_cache_stats(self) -> Dict[str, Any]:
        """Get cache statistics."""
        return {
            "cache_size": len(self._cache),
            "cache_keys": list(self._cache.keys()),
        }

    async def health_check(self) -> Dict[str, Any]:
        """Perform health check."""
        try:
            # Test UKB router
            test_results = await self.ukb_router.lookup(
                query="test",
                capability=None,
                top_k=1,
                use_cache=False,
            )

            # Test strategies
            strategy_status = {}
            for name, strategy in self.strategies.items():
                try:
                    if hasattr(strategy, "retrieve"):
                        # Mock test request
                        request = RetrievalRequest("test", top_k=1)
                        await strategy.retrieve(request, self.ukb_router)
                        strategy_status[name] = "healthy"
                    else:
                        strategy_status[name] = "unknown"
                except Exception as e:
                    strategy_status[name] = f"error: {str(e)}"

            return {
                "status": "healthy",
                "ukb_router": "healthy",
                "strategies": strategy_status,
                "cache_size": len(self._cache),
            }
        except Exception as e:
            logger.error(f"Health check failed: {e}")
            return {
                "status": "unhealthy",
                "error": str(e),
            }


# Global retrieval orchestrator instance
_retrieval_orchestrator: Optional[RetrievalOrchestrator] = None


def get_retrieval_orchestrator() -> RetrievalOrchestrator:
    """Get global retrieval orchestrator instance."""
    global _retrieval_orchestrator
    if _retrieval_orchestrator is None:
        _retrieval_orchestrator = RetrievalOrchestrator()
    return _retrieval_orchestrator


def initialize_retrieval_orchestrator() -> RetrievalOrchestrator:
    """Initialize global retrieval orchestrator."""
    global _retrieval_orchestrator
    _retrieval_orchestrator = RetrievalOrchestrator()
    return _retrieval_orchestrator
