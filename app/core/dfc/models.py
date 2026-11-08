"""DFC models and dataclasses."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class CompactSummary:
    """Compact summary for COLD layer."""

    content_hash: str
    summary: str
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: Optional[float] = None

    def __post_init__(self):
        if self.created_at is None:
            import time

            self.created_at = time.time()


@dataclass
class DFCConfig:
    """Configuration for DFC layers."""

    max_hot_size: int = 8000
    max_warm_size: int = 32000
    heat_cache_size: int = 4000
    compaction_interval: int = 60  # seconds
    compaction_threshold: int = 100  # items in warm layer
    cold_layer_max_size: Optional[int] = None  # None = unlimited

    @classmethod
    def from_settings(cls, settings: Any) -> "DFCConfig":
        """Create DFCConfig from settings."""
        # In a real implementation, this would read from settings
        return cls()


@dataclass
class Plan:
    """Plan dataclass for Tri-Model Pipeline."""

    steps: List[str]
    criteria: List[str]
    prefetch_hints: List[str]
    tier: str  # small|large|tournament
    cacheable_prefix: str = ""
    dynamic_suffix: str = ""

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "steps": self.steps,
            "criteria": self.criteria,
            "prefetch_hints": self.prefetch_hints,
            "tier": self.tier,
            "cacheable_prefix": self.cacheable_prefix,
            "dynamic_suffix": self.dynamic_suffix,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Plan":
        """Create from dictionary."""
        return cls(
            steps=data.get("steps", []),
            criteria=data.get("criteria", []),
            prefetch_hints=data.get("prefetch_hints", []),
            tier=data.get("tier", "small"),
            cacheable_prefix=data.get("cacheable_prefix", ""),
            dynamic_suffix=data.get("dynamic_suffix", ""),
        )


@dataclass
class DFCStats:
    """Statistics for DFC layers."""

    hot_size: int = 0
    warm_size: int = 0
    cold_size: int = 0
    heat_cache_size: int = 0
    heat_cache_hits: int = 0
    heat_cache_misses: int = 0
    compaction_count: int = 0
    last_compaction: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "hot_size": self.hot_size,
            "warm_size": self.warm_size,
            "cold_size": self.cold_size,
            "heat_cache_size": self.heat_cache_size,
            "heat_cache_hits": self.heat_cache_hits,
            "heat_cache_misses": self.heat_cache_misses,
            "compaction_count": self.compaction_count,
            "last_compaction": self.last_compaction,
        }
