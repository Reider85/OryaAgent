"""Heuristics for retrieval strategy selection."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import numpy as np
from app.core.retrieval.models import RetrievalStrategy, StrategyDecision
from app.core.observability.spans import emit_span


@dataclass
class HeuristicResult:
    """Result of a heuristic evaluation."""
    
    strategy: RetrievalStrategy
    confidence: float
    matched: bool
    reason: str


class HeuristicsEngine:
    """Heuristics for retrieval strategy selection."""
    
    def __init__(self):
        self.patterns = {
            "referential_markers": re.compile(
                r"(помнишь|обсуждали|ранее|в прошлый раз|раньше|предыдущий|раньше)"
            ),
            "code_intent": re.compile(
                r"(найти|поиск|сигнатура|определение|референс|ссылка|где находится|как используется)"
            ),
            "memory_intent": re.compile(
                r"(вспомни|напомни|что мы|ранее обсуждали|раньше говорили|до этого)"
            ),
            "first_turn": re.compile(r"^(помоги|привет|здравствуйте|начать|сделать|создать)"),
        }
        
        # Embedding model for similarity (mock in BETA)
        self.embedding_model = MockEmbeddingModel()
    
    def evaluate_heuristics(
        self, session_state: Dict[str, Any]
    ) -> List[HeuristicResult]:
        """Evaluate all heuristics against session state."""
        results = []
        
        # First turn heuristic
        first_turn_result = self.first_turn_heuristic(session_state)
        results.append(first_turn_result)
        
        # Referential markers heuristic
        referential_result = self.referential_marker_heuristic(session_state)
        results.append(referential_result)
        
        # Similar tokens heuristic
        similarity_result = self.similarity_tokens_heuristic(session_state)
        results.append(similarity_result)
        
        # Code intent heuristic
        code_result = self.code_intent_heuristic(session_state)
        results.append(code_result)
        
        # Memory intent heuristic
        memory_result = self.memory_intent_heuristic(session_state)
        results.append(memory_result)
        
        return results
    
    def first_turn_heuristic(self, session_state: Dict[str, Any]) -> HeuristicResult:
        """First turn heuristic."""
        turn_count = session_state.get("turn_count", 0)
        last_message = session_state.get("last_message", "").lower()
        
        if turn_count == 0:
            return HeuristicResult(
                strategy=RetrievalStrategy.STANDARD,
                confidence=0.9,
                matched=True,
                reason="First turn - provide context"
            )
        
        # Check if message looks like a first turn greeting
        if self.patterns["first_turn"].match(last_message):
            return HeuristicResult(
                strategy=RetrievalStrategy.STANDARD,
                confidence=0.8,
                matched=True,
                reason="Greeting detected - provide context"
            )
        
        return HeuristicResult(
            strategy=RetrievalStrategy.NONE,
            confidence=0.0,
            matched=False,
            reason="Not first turn"
        )
    
    def referential_marker_heuristic(
        self, session_state: Dict[str, Any]
    ) -> HeuristicResult:
        """Referential markers heuristic."""
        message = session_state.get("last_message", "").lower()
        
        if self.patterns["referential_markers"].search(message):
            return HeuristicResult(
                strategy=RetrievalStrategy.EXPLICIT_RECALL,
                confidence=0.8,
                matched=True,
                reason="Referential markers detected"
            )
        
        return HeuristicResult(
            strategy=RetrievalStrategy.NONE,
            confidence=0.0,
            matched=False,
            reason="No referential markers"
        )
    
    def similarity_tokens_heuristic(
        self, session_state: Dict[str, Any]
    ) -> HeuristicResult:
        """Similar tokens heuristic."""
        turn_count = session_state.get("turn_count", 0)
        last_message = session_state.get("last_message", "").lower()
        
        if turn_count < 2:
            return HeuristicResult(
                strategy=RetrievalStrategy.NONE,
                confidence=0.0,
                matched=False,
                reason="Not enough history for similarity"
            )
        
        # Get previous messages for similarity comparison
        previous_messages = session_state.get("previous_messages", [])
        if not previous_messages:
            return HeuristicResult(
                strategy=RetrievalStrategy.NONE,
                confidence=0.0,
                matched=False,
                reason="No previous messages for similarity"
            )
        
        # Calculate similarity with previous messages (mock in BETA)
        try:
            similarity_score = self.embedding_model.similarity(
                last_message, previous_messages[-1]
            )
            
            if similarity_score > 0.7:
                return HeuristicResult(
                    strategy=RetrievalStrategy.TOPIC_CONTINUATION,
                    confidence=min(similarity_score, 1.0),
                    matched=True,
                    reason=f"High similarity detected: {similarity_score:.2f}"
                )
        except Exception as e:
            logger.warning(f"Similarity calculation failed: {e}")
        
        return HeuristicResult(
            strategy=RetrievalStrategy.NONE,
            confidence=0.0,
            matched=False,
            reason="No high similarity detected"
        )
    
    def code_intent_heuristic(
        self, session_state: Dict[str, Any]
    ) -> HeuristicResult:
        """Code intent heuristic."""
        message = session_state.get("last_message", "").lower()
        
        if self.patterns["code_intent"].search(message):
            return HeuristicResult(
                strategy=RetrievalStrategy.CODE_LOOKUP,
                confidence=0.9,
                matched=True,
                reason="Code intent detected"
            )
        
        # Check for file extensions in message
        file_extensions = [".py", ".js", ".ts", ".java", ".rs", ".go", ".cpp", ".c"]
        for ext in file_extensions:
            if ext in message:
                return HeuristicResult(
                    strategy=RetrievalStrategy.CODE_LOOKUP,
                    confidence=0.8,
                    matched=True,
                    reason=f"File extension detected: {ext}"
                )
        
        return HeuristicResult(
            strategy=RetrievalStrategy.NONE,
            confidence=0.0,
            matched=False,
            reason="No code intent detected"
        )
    
    def memory_intent_heuristic(
        self, session_state: Dict[str, Any]
    ) -> HeuristicResult:
        """Memory intent heuristic."""
        message = session_state.get("last_message", "").lower()
        
        if self.patterns["memory_intent"].search(message):
            return HeuristicResult(
                strategy=RetrievalStrategy.EXPLICIT_RECALL,
                confidence=0.7,
                matched=True,
                reason="Memory intent detected"
            )
        
        # Check for asking about past work
        memory_keywords = ["раньше", "до этого", "предыдущий", "ранее", "в прошлый раз"]
        if any(keyword in message for keyword in memory_keywords):
            return HeuristicResult(
                strategy=RetrievalStrategy.EXPLICIT_RECALL,
                confidence=0.6,
                matched=True,
                reason="Past work reference detected"
            )
        
        return HeuristicResult(
            strategy=RetrievalStrategy.NONE,
            confidence=0.0,
            matched=False,
            reason="No memory intent detected"
        )
    
    def make_decision(
        self, session_state: Dict[str, Any]
    ) -> StrategyDecision:
        """Make a strategy decision based on heuristics."""
        results = self.evaluate_heuristics(session_state)
        
        # Find the best matching strategy
        best_result = max(results, key=lambda x: x.confidence if x.matched else 0.0)
        
        # If no heuristic matched, use default
        if not best_result.matched:
            return StrategyDecision(
                strategy=RetrievalStrategy.NONE,
                confidence=0.0,
                reasoning="No heuristics matched - no retrieval",
                heuristics_matched=[],
                context=session_state,
            )
        
        # Handle strategy conflicts
        matched_strategies = [r for r in results if r.matched]
        if len(matched_strategies) > 1:
            # Priority order: EXPLICIT_RECALL > CODE_LOOKUP > TOPIC_CONTINUATION > STANDARD
            priority_order = [
                RetrievalStrategy.EXPLICIT_RECALL,
                RetrievalStrategy.CODE_LOOKUP,
                RetrievalStrategy.TOPIC_CONTINUATION,
                RetrievalStrategy.STANDARD,
            ]
            
            for strategy in priority_order:
                for result in matched_strategies:
                    if result.strategy == strategy:
                        return StrategyDecision(
                            strategy=strategy,
                            confidence=result.confidence,
                            reasoning=f"Priority strategy selected: {strategy.value}",
                            heuristics_matched=[r.strategy.value for r in matched_strategies],
                            context=session_state,
                        )
        
        return StrategyDecision(
            strategy=best_result.strategy,
            confidence=best_result.confidence,
            reasoning=best_result.reason,
            heuristics_matched=[best_result.strategy.value],
            context=session_state,
        )


class MockEmbeddingModel:
    """Mock embedding model for similarity calculation (BETA placeholder)."""
    
    def similarity(self, text1: str, text2: str) -> float:
        """Calculate mock similarity between two texts."""
        # Simple mock similarity based on word overlap
        words1 = set(text1.lower().split())
        words2 = set(text2.lower().split())
        
        if not words1 or not words2:
            return 0.0
        
        intersection = words1.intersection(words2)
        union = words1.union(words2)
        
        return len(intersection) / len(union)


# Global heuristics engine instance
_heuristics_engine: Optional[HeuristicsEngine] = None


def get_heuristics_engine() -> HeuristicsEngine:
    """Get global heuristics engine instance."""
    global _heuristics_engine
    if _heuristics_engine is None:
        _heuristics_engine = HeuristicsEngine()
    return _heuristics_engine