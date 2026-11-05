"""Metrics for MCP and semantic search operations (B-02).

Provides metrics collection and export for MCP client operations and semantic search.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# Metrics definitions for MCP operations
MCP_METRICS = {
    "mcp_call_total": {
        "name": "orya_mcp_call_total",
        "description": "Total MCP tool calls",
        "type": "counter",
        "labels": ["tool_name", "status", "server_url"],
    },
    "mcp_call_latency_ms": {
        "name": "orya_mcp_call_latency_ms",
        "description": "MCP call latency in milliseconds",
        "type": "histogram",
        "buckets": [10, 50, 100, 500, 1000, 2000],
        "labels": ["tool_name", "server_url"],
    },
    "mcp_server_health_status": {
        "name": "orya_mcp_server_health_status",
        "description": "MCP server health status (1=healthy, 0=unhealthy)",
        "type": "gauge",
        "labels": ["server_url"],
    },
    "mcp_connection_errors_total": {
        "name": "orya_mcp_connection_errors_total",
        "description": "Total MCP connection errors",
        "type": "counter",
        "labels": ["server_url", "error_type"],
    },
}

# Metrics definitions for semantic search operations
SEMANTIC_SEARCH_METRICS = {
    "semantic_search_total": {
        "name": "orya_semantic_search_total",
        "description": "Total semantic searches",
        "type": "counter",
        "labels": ["status", "source", "has_injection"],
    },
    "semantic_search_latency_ms": {
        "name": "orya_semantic_search_latency_ms",
        "description": "Semantic search latency in milliseconds",
        "type": "histogram",
        "buckets": [50, 100, 500, 1000, 2000, 5000],
        "labels": ["source", "status"],
    },
    "semantic_search_results_count": {
        "name": "orya_semantic_search_results_count",
        "description": "Number of results per search",
        "type": "histogram",
        "buckets": [1, 5, 10, 20, 50, 100],
        "labels": ["status"],
    },
    "semantic_search_cache_hits_total": {
        "name": "orya_semantic_search_cache_hits_total",
        "description": "Total semantic search cache hits",
        "type": "counter",
        "labels": ["server_url"],
    },
    "semantic_search_cache_misses_total": {
        "name": "orya_semantic_search_cache_misses_total",
        "description": "Total semantic search cache misses",
        "type": "counter",
        "labels": ["server_url"],
    },
}

# All metrics combined
ALL_METRICS = {**MCP_METRICS, **SEMANTIC_SEARCH_METRICS}


class MetricCollector:
    """Simple metric collector for MCP and semantic search operations."""

    def __init__(self):
        self._counters = {}
        self._gauges = {}
        self._histograms = {}

    def counter_inc(
        self, name: str, labels: dict[str, str] | None = None, value: int = 1
    ):
        """Increment a counter metric."""
        key = (name, tuple(sorted(labels.items()))) if labels else (name, ())
        self._counters[key] = self._counters.get(key, 0) + value

    def gauge_set(self, name: str, value: float, labels: dict[str, str] | None = None):
        """Set a gauge metric."""
        key = (name, tuple(sorted(labels.items()))) if labels else (name, ())
        self._gauges[key] = value

    def histogram_observe(
        self, name: str, value: float, labels: dict[str, str] | None = None
    ):
        """Observe a value in a histogram."""
        key = (name, tuple(sorted(labels.items()))) if labels else (name, ())
        if key not in self._histograms:
            self._histograms[key] = []
        self._histograms[key].append(value)

    def get_metrics(self) -> dict[str, Any]:
        """Get all collected metrics."""
        return {
            "counters": dict(self._counters),
            "gauges": dict(self._gauges),
            "histograms": {
                key: {
                    "count": len(values),
                    "sum": sum(values),
                    "avg": sum(values) / len(values) if values else 0,
                    "min": min(values) if values else 0,
                    "max": max(values) if values else 0,
                    "values": values,
                }
                for key, values in self._histograms.items()
            },
        }

    def clear(self):
        """Clear all collected metrics."""
        self._counters.clear()
        self._gauges.clear()
        self._histograms.clear()


# Global metric collector instance
_metric_collector = MetricCollector()


def get_metric_collector() -> MetricCollector:
    """Get the global metric collector instance."""
    return _metric_collector


def increment_mcp_call(tool_name: str, status: str, server_url: str):
    """Increment MCP call counter."""
    _metric_collector.counter_inc(
        "mcp_call_total",
        {"tool_name": tool_name, "status": status, "server_url": server_url},
        1,
    )


def observe_mcp_latency(tool_name: str, server_url: str, latency_ms: float):
    """Observe MCP call latency."""
    _metric_collector.histogram_observe(
        "mcp_call_latency_ms",
        latency_ms,
        {"tool_name": tool_name, "server_url": server_url},
    )


def set_mcp_server_health(server_url: str, is_healthy: bool):
    """Set MCP server health gauge."""
    _metric_collector.gauge_set(
        "mcp_server_health_status",
        1.0 if is_healthy else 0.0,
        {"server_url": server_url},
    )


def increment_mcp_connection_error(server_url: str, error_type: str):
    """Increment MCP connection error counter."""
    _metric_collector.counter_inc(
        "mcp_connection_errors_total",
        {"server_url": server_url, "error_type": error_type},
        1,
    )


def increment_semantic_search(status: str, source: str, has_injection: bool = False):
    """Increment semantic search counter."""
    _metric_collector.counter_inc(
        "semantic_search_total",
        {"status": status, "source": source, "has_injection": str(has_injection)},
        1,
    )


def observe_semantic_search_latency(source: str, status: str, latency_ms: float):
    """Observe semantic search latency."""
    _metric_collector.histogram_observe(
        "semantic_search_latency_ms", latency_ms, {"source": source, "status": status}
    )


def observe_semantic_search_results_count(results_count: int, status: str):
    """Observe semantic search results count."""
    _metric_collector.histogram_observe(
        "semantic_search_results_count", float(results_count), {"status": status}
    )


def increment_semantic_search_cache_hit(server_url: str):
    """Increment semantic search cache hit counter."""
    _metric_collector.counter_inc(
        "semantic_search_cache_hits_total", {"server_url": server_url}, 1
    )


def increment_semantic_search_cache_miss(server_url: str):
    """Increment semantic search cache miss counter."""
    _metric_collector.counter_inc(
        "semantic_search_cache_misses_total", {"server_url": server_url}, 1
    )


# Context managers for automatic metric collection
class MCPMetricsContext:
    """Context manager for MCP operation metrics."""

    def __init__(self, tool_name: str, server_url: str):
        self.tool_name = tool_name
        self.server_url = server_url
        self.start_time = None
        self.status = "success"
        self.error = None

    def __enter__(self):
        self.start_time = __import__("time").time()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        latency_ms = (__import__("time").time() - self.start_time) * 1000

        if exc_type is not None:
            self.status = "error"
            self.error = str(exc_val)
            increment_mcp_connection_error(self.server_url, "operation_error")

        increment_mcp_call(self.tool_name, self.status, self.server_url)
        observe_mcp_latency(self.tool_name, self.server_url, latency_ms)


class SemanticSearchMetricsContext:
    """Context manager for semantic search operation metrics."""

    def __init__(self, query: str, top_k: int, server_url: str):
        self.query = query
        self.top_k = top_k
        self.server_url = server_url
        self.start_time = None
        self.status = "success"
        self.source = "mcp"
        self.results_count = 0
        self.has_injection = False

    def __enter__(self):
        self.start_time = __import__("time").time()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        latency_ms = (__import__("time").time() - self.start_time) * 1000

        if exc_type is not None:
            self.status = "error"

        increment_semantic_search(self.status, self.source, self.has_injection)
        observe_semantic_search_latency(self.source, self.status, latency_ms)
        observe_semantic_search_results_count(self.results_count, self.status)

        if self.source == "cache":
            increment_semantic_search_cache_hit(self.server_url)
        else:
            increment_semantic_search_cache_miss(self.server_url)
