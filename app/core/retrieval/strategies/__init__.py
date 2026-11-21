"""Strategy implementations package."""

from __future__ import annotations

from app.core.retrieval.strategies.base import (
    STRATEGY_REGISTRY,
    BaseStrategy,
    CodeLookupStrategy,
    DegradedStrategy,
    ExplicitRecallStrategy,
    NoneStrategy,
    SpeculativePrefetchStrategy,
    StandardStrategy,
    TopicContinuationStrategy,
    get_available_strategies,
    get_strategy,
)

__all__ = [
    "BaseStrategy",
    "NoneStrategy",
    "StandardStrategy",
    "TopicContinuationStrategy",
    "SpeculativePrefetchStrategy",
    "ExplicitRecallStrategy",
    "CodeLookupStrategy",
    "DegradedStrategy",
    "STRATEGY_REGISTRY",
    "get_strategy",
    "get_available_strategies",
]
