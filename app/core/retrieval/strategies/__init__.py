"""Strategy implementations package."""

from __future__ import annotations

from app.core.retrieval.strategies.base import (
    BaseStrategy,
    NoneStrategy,
    StandardStrategy,
    TopicContinuationStrategy,
    SpeculativePrefetchStrategy,
    ExplicitRecallStrategy,
    CodeLookupStrategy,
    DegradedStrategy,
    STRATEGY_REGISTRY,
    get_strategy,
    get_available_strategies,
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