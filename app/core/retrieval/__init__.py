"""Retrieval orchestrator with 7 strategies and heuristics-based decision making."""

from __future__ import annotations

from app.core.retrieval.heuristics import (
    HeuristicResult,
    HeuristicsEngine,
    get_heuristics_engine,
)
from app.core.retrieval.models import (
    RetrievalStrategy,
    RetrievedChunk,
    StrategyDecision,
)
from app.core.retrieval.orchestrator import (
    RetrievalOrchestrator,
    get_retrieval_orchestrator,
    initialize_retrieval_orchestrator,
)
from app.core.retrieval.strategies import (
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
    # Main orchestrator
    "get_retrieval_orchestrator",
    "initialize_retrieval_orchestrator",
    "RetrievalOrchestrator",
    # Models
    "RetrievalStrategy",
    "StrategyDecision",
    "RetrievedChunk",
    # Heuristics
    "get_heuristics_engine",
    "HeuristicsEngine",
    "HeuristicResult",
    # Strategies
    "get_strategy",
    "get_available_strategies",
    "BaseStrategy",
    "NoneStrategy",
    "StandardStrategy",
    "TopicContinuationStrategy",
    "SpeculativePrefetchStrategy",
    "ExplicitRecallStrategy",
    "CodeLookupStrategy",
    "DegradedStrategy",
]
