"""Strategy implementations for RetrievalOrchestrator."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any

from app.core.observability.spans import timed_span
from app.core.retrieval.heuristics import get_heuristics_engine
from app.core.retrieval.models import RetrievedChunk
from app.core.ukb.router import get_ukb_router

logger = logging.getLogger(__name__)


class BaseStrategy(ABC):
    """Base class for retrieval strategies."""

    def __init__(self, name: str):
        self.name = name
        self.ukb_router = get_ukb_router()
        self.heuristics = get_heuristics_engine()

    @abstractmethod
    async def retrieve(
        self, session_state: dict[str, Any], top_k: int = 5
    ) -> list[RetrievedChunk]:
        """Execute retrieval strategy."""
        pass

    @abstractmethod
    def should_use(self, session_state: dict[str, Any]) -> bool:
        """Check if this strategy should be used."""
        pass

    def get_top_k_for_strategy(self, strategy: str) -> int:
        """Get top_k value for specific strategy."""
        strategy_top_k = {
            "none": 0,
            "standard": 3,
            "topic_continuation": 5,
            "speculative_prefetch": 2,
            "explicit_recall": 10,
            "code_lookup": 5,
            "degraded": 1,
        }
        return strategy_top_k.get(strategy, 3)


class NoneStrategy(BaseStrategy):
    """None strategy - no retrieval."""

    def __init__(self):
        super().__init__("none")

    async def retrieve(
        self, session_state: dict[str, Any], top_k: int = 5
    ) -> list[RetrievedChunk]:
        """Execute none strategy - return empty list."""
        with timed_span(span_type="retrieval.execute", name="retrieval.none.execute"):
            return []

    def should_use(self, session_state: dict[str, Any]) -> bool:
        """Always return False - this strategy is never selected automatically."""
        return False


class StandardStrategy(BaseStrategy):
    """Standard strategy - basic retrieval."""

    def __init__(self):
        super().__init__("standard")

    async def retrieve(
        self, session_state: dict[str, Any], top_k: int = 5
    ) -> list[RetrievedChunk]:
        """Execute standard strategy."""
        with timed_span(
            span_type="retrieval.execute", name="retrieval.standard.execute"
        ):
            return await self.ukb_router.lookup(
                query="general context",
                capability=None,
                top_k=top_k,
                use_cache=True,
            )

    def should_use(self, session_state: dict[str, Any]) -> bool:
        """Use for first turns or general context requests."""
        return True  # Default fallback strategy


class TopicContinuationStrategy(BaseStrategy):
    """Topic continuation strategy - retrieve related content."""

    def __init__(self):
        super().__init__("topic_continuation")

    async def retrieve(
        self, session_state: dict[str, Any], top_k: int = 5
    ) -> list[RetrievedChunk]:
        """Execute topic continuation strategy."""
        with timed_span(
            span_type="retrieval.execute", name="retrieval.topic_continuation.execute"
        ):
            # Use the last message as query for topic continuation
            last_message = session_state.get("last_message", "")
            return await self.ukb_router.lookup(
                query=last_message,
                capability=None,
                top_k=top_k,
                use_cache=True,
            )

    def should_use(self, session_state: dict[str, Any]) -> bool:
        """Use when there's high similarity with previous messages."""
        return True  # Handled by heuristics


class SpeculativePrefetchStrategy(BaseStrategy):
    """Speculative prefetch strategy - predict and prefetch likely content."""

    def __init__(self):
        super().__init__("speculative_prefetch")

    async def retrieve(
        self, session_state: dict[str, Any], top_k: int = 5
    ) -> list[RetrievedChunk]:
        """Execute speculative prefetch strategy."""
        with timed_span(
            span_type="retrieval.execute", name="retrieval.speculative_prefetch.execute"
        ):
            # Mock speculative queries based on context
            speculative_queries = [
                "general programming patterns",
                "best practices",
                "common implementations",
            ]

            # Get results for all speculative queries
            all_results = []
            for query in speculative_queries:
                results = await self.ukb_router.lookup(
                    query=query,
                    capability=None,
                    top_k=2,  # Fewer results for prefetch
                    use_cache=True,
                )
                all_results.extend(results)

            # Remove duplicates and return top_k
            seen_ids = set()
            unique_results = []
            for result in all_results:
                if result.chunk_id not in seen_ids:
                    seen_ids.add(result.chunk_id)
                    unique_results.append(result)

            return unique_results[:top_k]

    def should_use(self, session_state: dict[str, Any]) -> bool:
        """Use for predictive scenarios (placeholder in BETA)."""
        return True  # Placeholder implementation


class ExplicitRecallStrategy(BaseStrategy):
    """Explicit recall strategy - retrieve from memory."""

    def __init__(self):
        super().__init__("explicit_recall")

    async def retrieve(
        self, session_state: dict[str, Any], top_k: int = 5
    ) -> list[RetrievedChunk]:
        """Execute explicit recall strategy."""
        with timed_span(
            span_type="retrieval.execute", name="retrieval.explicit_recall.execute"
        ):
            return await self.ukb_router.lookup(
                query="memory recall",
                capability="memory.semantic",
                top_k=top_k,
                use_cache=True,
            )

    def should_use(self, session_state: dict[str, Any]) -> bool:
        """Use when referential markers or memory intent is detected."""
        return True  # Handled by heuristics


class CodeLookupStrategy(BaseStrategy):
    """Code lookup strategy - retrieve code-related content."""

    def __init__(self):
        super().__init__("code_lookup")

    async def retrieve(
        self, session_state: dict[str, Any], top_k: int = 5
    ) -> list[RetrievedChunk]:
        """Execute code lookup strategy."""
        with timed_span(
            span_type="retrieval.execute", name="retrieval.code_lookup.execute"
        ):
            # Use LSP capabilities for code lookup
            return await self.ukb_router.lookup(
                query="code definition",
                capability="lsp.def",
                top_k=top_k,
                use_cache=True,
            )

    def should_use(self, session_state: dict[str, Any]) -> bool:
        """Use when code intent or file extensions are detected."""
        return True  # Handled by heuristics


class DegradedStrategy(BaseStrategy):
    """Degraded strategy - minimal retrieval for fallback."""

    def __init__(self):
        super().__init__("degraded")

    async def retrieve(
        self, session_state: dict[str, Any], top_k: int = 5
    ) -> list[RetrievedChunk]:
        """Execute degraded strategy - minimal retrieval."""
        with timed_span(
            span_type="retrieval.execute", name="retrieval.degraded.execute"
        ):
            # Only retrieve one result with basic query
            results = await self.ukb_router.lookup(
                query="basic information",
                capability=None,
                top_k=1,
                use_cache=True,
            )
            return results

    def should_use(self, session_state: dict[str, Any]) -> bool:
        """Use as fallback when other strategies fail."""
        return True  # Fallback strategy


# Strategy registry
STRATEGY_REGISTRY = {
    "none": NoneStrategy,
    "standard": StandardStrategy,
    "topic_continuation": TopicContinuationStrategy,
    "speculative_prefetch": SpeculativePrefetchStrategy,
    "explicit_recall": ExplicitRecallStrategy,
    "code_lookup": CodeLookupStrategy,
    "degraded": DegradedStrategy,
}


def get_strategy(name: str) -> BaseStrategy:
    """Get a strategy instance by name."""
    if name not in STRATEGY_REGISTRY:
        raise ValueError(f"Unknown strategy: {name}")

    return STRATEGY_REGISTRY[name]()


def get_available_strategies() -> list[str]:
    """Get list of available strategy names."""
    return list(STRATEGY_REGISTRY.keys())
