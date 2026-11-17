"""Enhanced RetrievalOrchestrator with 7 strategies and heuristics-based decision making."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, Optional

from app.core.retrieval.models import RetrievalStrategy, StrategyDecision, RetrievedChunk
from app.core.retrieval.heuristics import get_heuristics_engine
from app.core.retrieval.strategies import get_strategy, get_available_strategies
from app.core.dfc.integration import get_dfc_integration
from app.core.observability.spans import emit_span
from app.core.observability.metrics import get_metric_collector

logger = logging.getLogger(__name__)


class RetrievalOrchestrator:
    """Enhanced retrieval orchestrator with 7 strategies and heuristics-based decision making."""
    
    def __init__(self):
        self.heuristics = get_heuristics_engine()
        try:
            self.dfc_integration = get_dfc_integration()
        except RuntimeError:
            # DFC not initialized - create a mock integration
            self.dfc_integration = None
        self.metrics = get_metric_collector()
        
        # Strategy instances
        self.strategies = {
            strategy_name: get_strategy(strategy_name)
            for strategy_name in get_available_strategies()
        }
        
        # Cache for results
        self._cache: Dict[str, List[RetrievedChunk]] = {}
        self._cache_ttl = 300  # 5 minutes
        
        # Track strategy usage for metrics
        self._strategy_usage = {strategy: 0 for strategy in get_available_strategies()}
    
    def decide(self, session_state: Dict[str, Any]) -> StrategyDecision:
        """Decide which retrieval strategy to use.
        
        Args:
            session_state: Current session state including turn_count, last_message, etc.
            
        Returns:
            StrategyDecision with selected strategy and reasoning.
        """
        # Use heuristics engine to make decision
        decision = self.heuristics.make_decision(session_state)
        
        # Update strategy usage metrics
        self._strategy_usage[decision.strategy.value] += 1
        
        # Record decision metrics
        self.metrics.increment_counter(
            "orya_retrieval_strategy_total",
            {"strategy": decision.strategy.value}
        )
        
        logger.info(
            f"Retrieval decision: {decision.strategy.value} "
            f"(confidence: {decision.confidence:.2f}, "
            f"heuristics: {decision.heuristics_matched})"
        )
        
        return decision
    
    async def execute(
        self,
        strategy: RetrievalStrategy,
        session_state: Dict[str, Any],
        top_k: int = 5,
    ) -> List[RetrievedChunk]:
        """Execute a retrieval strategy.
        
        Args:
            strategy: The strategy to execute
            session_state: Current session state
            top_k: Maximum number of results to return
            
        Returns:
            List of retrieved chunks
        """
        strategy_name = strategy.value
        strategy_instance = self.strategies[strategy_name]
        
        # Get top_k for this specific strategy
        strategy_top_k = strategy_instance.get_top_k_for_strategy(strategy_name)
        effective_top_k = min(top_k, strategy_top_k)
        
        logger.info(f"Executing {strategy_name} strategy with top_k={effective_top_k}")
        
        try:
            # Execute the strategy
            results = await strategy_instance.retrieve(
                session_state=session_state,
                top_k=effective_top_k,
            )
            
            # Add strategy metadata to results
            for result in results:
                result.strategy_used = strategy
            
            # Promote results to DFC HOT layer if strategy supports it
            if results and strategy_name != "none" and self.dfc_integration:
                await self._promote_results_to_dfc(results, strategy_name)
            
            # Record execution metrics
            self.metrics.increment_counter(
                "orya_retrieval_execute_total",
                {"strategy": strategy_name}
            )
            
            # TODO: Add histogram support when available
            # self.metrics.histogram(
            #     "orya_retrieval_results_total",
            #     len(results),
            #     {"strategy": strategy_name}
            # )
            
            logger.info(f"Strategy {strategy_name} returned {len(results)} results")
            return results
            
        except Exception as e:
            logger.error(f"Strategy {strategy_name} failed: {e}")
            
            # Record error metrics
            self.metrics.increment_counter(
                "orya_retrieval_errors_total",
                {"strategy": strategy_name}
            )
            
            # Fallback to degraded strategy
            if strategy_name != "degraded":
                logger.info(f"Falling back to degraded strategy")
                degraded_strategy = RetrievalStrategy.DEGRADED
                return await self.execute(degraded_strategy, session_state, top_k)
            
            # If degraded strategy also failed, return empty list
            return []
    
    async def orchestrate(
        self,
        session_state: Dict[str, Any],
        top_k: int = 5,
    ) -> List[RetrievedChunk]:
        """Full orchestration: decide strategy and execute it.
        
        Args:
            session_state: Current session state
            top_k: Maximum number of results to return
            
        Returns:
            List of retrieved chunks
        """
        # with emit_span(
        #     "retrieval.orchestrate",
        #     {
        # Decide on strategy
        decision = self.decide(session_state)
            
        # Execute the chosen strategy
        results = await self.execute(
            decision.strategy,
            session_state,
            top_k,
        )
        
        # Record decision accuracy metrics (mock for now)
        if hasattr(session_state, "expected_strategy"):
                expected = session_state["expected_strategy"]
                actual = decision.strategy.value
                if expected == actual:
                    self.metrics.increment_counter(
                        "orya_retrieval_decision_accuracy_correct"
                    )
                else:
                    self.metrics.increment_counter(
                        "orya_retrieval_decision_accuracy_incorrect"
                    )
        
        return results
    
    async def _promote_results_to_dfc(
        self,
        results: List[RetrievedChunk],
        strategy_name: str
    ) -> None:
        """Promote retrieved results to DFC HOT layer."""
        if not self.dfc_integration:
            logger.warning("DFC integration not available - skipping promotion")
            return
            
        try:
            for i, result in enumerate(results):
                key = f"retrieval_{strategy_name}_{i}"
                result.promote_to_dfc(key)
                
                # Promote to DFC
                await self.dfc_integration.promote_tool_result(
                    key, result.content
                )
                
                logger.debug(f"Promoted result {key} to DFC HOT layer")
                
        except Exception as e:
            logger.warning(f"Failed to promote results to DFC: {e}")
    
    def get_strategy_usage_stats(self) -> Dict[str, int]:
        """Get strategy usage statistics."""
        return self._strategy_usage.copy()
    
    def get_cache_stats(self) -> Dict[str, Any]:
        """Get cache statistics."""
        return {
            "cache_size": len(self._cache),
            "cache_keys": list(self._cache.keys()),
        }
    
    def clear_cache(self) -> None:
        """Clear the result cache."""
        self._cache.clear()
        logger.info("Retrieval orchestrator cache cleared")
    
    async def health_check(self) -> Dict[str, Any]:
        """Perform health check."""
        try:
            # Test heuristics engine
            test_session_state = {
                "turn_count": 0,
                "last_message": "test",
                "previous_messages": [],
            }
            decision = self.decide(test_session_state)
            
            # Test strategy execution
            results = await self.execute(
                decision.strategy,
                test_session_state,
                top_k=1,
            )
            
            # Test DFC integration
            try:
                await self.dfc_integration.promote_tool_result(
                    "health_check", "test content"
                )
            except Exception as e:
                logger.warning(f"DFC integration health check failed: {e}")
            
            return {
                "status": "healthy",
                "heuristics": "healthy",
                "strategies": "healthy",
                "dfc_integration": "healthy" if "e" not in str(e).lower() else "degraded",
                "cache_size": len(self._cache),
                "strategy_usage": self.get_strategy_usage_stats(),
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