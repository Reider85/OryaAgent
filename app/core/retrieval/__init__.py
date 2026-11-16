"""Retrieval orchestrator with 7 strategies and heuristics-based decision making."""

from __future__ import annotations

from app.core.retrieval.orchestrator import (
    get_retrieval_orchestrator,
    initialize_retrieval_orchestrator,
    RetrievalOrchestrator,
)
from app.core.retrieval.models import (
    RetrievalStrategy,
    StrategyDecision,
    RetrievedChunk,
)
from app.core.retrieval.heuristics import (
    get_heuristics_engine,
    HeuristicsEngine,
    HeuristicResult,
)
from app.core.retrieval.strategies import (
    get_strategy,
    get_available_strategies,
    BaseStrategy,
    NoneStrategy,
    StandardStrategy,
    TopicContinuationStrategy,
    SpeculativePrefetchStrategy,
    ExplicitRecallStrategy,
    CodeLookupStrategy,
    DegradedStrategy,
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