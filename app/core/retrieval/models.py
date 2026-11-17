"""Data models for RetrievalOrchestrator."""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class RetrievalStrategy(Enum):
    """Enumeration of retrieval strategies."""
    
    NONE = "none"
    STANDARD = "standard"
    TOPIC_CONTINUATION = "topic_continuation"
    SPECULATIVE_PREFETCH = "speculative_prefetch"
    EXPLICIT_RECALL = "explicit_recall"
    CODE_LOOKUP = "code_lookup"
    DEGRADED = "degraded"


@dataclass
class StrategyDecision:
    """Represents a strategy decision with reasoning."""
    
    strategy: RetrievalStrategy
    confidence: float
    reasoning: str
    heuristics_matched: List[str] = field(default_factory=list)
    context: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "strategy": self.strategy.value,
            "confidence": self.confidence,
            "reasoning": self.reasoning,
            "heuristics_matched": self.heuristics_matched,
            "context": self.context,
        }


@dataclass
class RetrievedChunk:
    """Enhanced retrieved chunk with DFC integration."""
    
    content: str
    source: str
    score: float = 1.0
    metadata: Dict[str, Any] = field(default_factory=dict)
    chunk_id: str = None
    strategy_used: RetrievalStrategy = None
    promoted_to_dfc: bool = False
    
    def __post_init__(self):
        """Generate chunk ID if not provided."""
        if self.chunk_id is None:
            self.chunk_id = self._generate_chunk_id()
    
    def _generate_chunk_id(self) -> str:
        """Generate unique chunk ID."""
        content_hash = hashlib.sha256(self.content.encode()).hexdigest()
        return f"{self.source}_{content_hash[:8]}"
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "content": self.content,
            "source": self.source,
            "score": self.score,
            "metadata": self.metadata,
            "chunk_id": self.chunk_id,
            "strategy_used": self.strategy_used.value if self.strategy_used else None,
            "promoted_to_dfc": self.promoted_to_dfc,
        }
    
    def promote_to_dfc(self, key: str) -> None:
        """Mark this chunk as promoted to DFC."""
        self.promoted_to_dfc = True
        self.metadata["promoted_key"] = key