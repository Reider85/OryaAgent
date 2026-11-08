"""DFC metrics collection."""

from __future__ import annotations

import logging
from typing import Any, Dict
from prometheus_client import Counter, Gauge, Histogram

logger = logging.getLogger(__name__)


class DFCMetrics:
    """Metrics for DFC components."""

    def __init__(self):
        # DFC layer sizes
        self.dfc_hot_size_tokens = Gauge(
            "orya_dfc_hot_size_tokens", "Current size of HOT layer in tokens"
        )

        self.dfc_warm_size_tokens = Gauge(
            "orya_dfc_warm_size_tokens", "Current size of WARM layer in tokens"
        )

        self.dfc_cold_size = Gauge(
            "orya_dfc_cold_size", "Current number of items in COLD layer"
        )

        self.dfc_heat_cache_size = Gauge(
            "orya_dfc_heat_cache_size", "Current size of HEAT cache in tokens"
        )

        # Compaction metrics
        self.dfc_compaction_total = Counter(
            "orya_dfc_compaction_total",
            "Total number of compaction operations",
            ["layer"],
        )

        self.dfc_compaction_duration_ms = Histogram(
            "orya_dfc_compaction_duration_ms",
            "Duration of compaction operations in milliseconds",
        )

        # Layer transitions
        self.dfc_promote_to_hot_total = Counter(
            "orya_dfc_promote_to_hot_total", "Total number of promotions to HOT layer"
        )

        self.dfc_demote_to_warm_total = Counter(
            "orya_dfc_demote_to_warm_total", "Total number of demotions to WARM layer"
        )

        # Cache metrics
        self.dfc_heat_cache_hits_total = Counter(
            "orya_dfc_heat_cache_hits_total", "Total number of HEAT cache hits"
        )

        self.dfc_heat_cache_misses_total = Counter(
            "orya_dfc_heat_cache_misses_total", "Total number of HEAT cache misses"
        )

        # Performance metrics
        self.dfc_assemble_hot_duration_ms = Histogram(
            "orya_dfc_assemble_hot_duration_ms",
            "Duration of HOT context assembly in milliseconds",
        )

        self.dfc_snapshot_duration_ms = Histogram(
            "orya_dfc_snapshot_duration_ms",
            "Duration of DFC snapshot creation in milliseconds",
        )

    def update_layer_sizes(
        self, hot_size: int, warm_size: int, cold_size: int, heat_cache_size: int
    ) -> None:
        """Update layer size metrics."""
        self.dfc_hot_size_tokens.set(hot_size)
        self.dfc_warm_size_tokens.set(warm_size)
        self.dfc_cold_size.set(cold_size)
        self.dfc_heat_cache_size.set(heat_cache_size)

    def increment_compaction(self, layer: str) -> None:
        """Increment compaction counter."""
        self.dfc_compaction_total.labels(layer=layer).inc()

    def observe_compaction_duration(self, duration_ms: float) -> None:
        """Observe compaction duration."""
        self.dfc_compaction_duration_ms.observe(duration_ms)

    def increment_promote_to_hot(self) -> None:
        """Increment promote to HOT counter."""
        self.dfc_promote_to_hot_total.inc()

    def increment_demote_to_warm(self) -> None:
        """Increment demote to WARM counter."""
        self.dfc_demote_to_warm_total.inc()

    def increment_heat_cache_hits(self) -> None:
        """Increment HEAT cache hits counter."""
        self.dfc_heat_cache_hits_total.inc()

    def increment_heat_cache_misses(self) -> None:
        """Increment HEAT cache misses counter."""
        self.dfc_heat_cache_misses_total.inc()

    def observe_assemble_hot_duration(self, duration_ms: float) -> None:
        """Observe HOT context assembly duration."""
        self.dfc_assemble_hot_duration_ms.observe(duration_ms)

    def observe_snapshot_duration(self, duration_ms: float) -> None:
        """Observe snapshot creation duration."""
        self.dfc_snapshot_duration_ms.observe(duration_ms)


# Global metrics instance
_dfc_metrics: Optional[DFCMetrics] = None


def get_dfc_metrics() -> DFCMetrics:
    """Get global DFC metrics instance."""
    global _dfc_metrics
    if _dfc_metrics is None:
        _dfc_metrics = DFCMetrics()
    return _dfc_metrics
