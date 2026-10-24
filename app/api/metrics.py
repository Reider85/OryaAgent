"""Metrics API (M-21): /metrics (Prometheus text) + /tools/cache-stats.

Exposes the per-tool cache hit/miss counters of the active backend
(``app.core.cache``): the hand-rolled Prometheus exposition carries
``orya_tool_cache_hits_total{tool}`` / ``orya_tool_cache_misses_total{tool}``
(BACKLOG5 M-21 AC, ARCHITECT5 9.1) without a prometheus-client
dependency - the formal Prometheus/Grafana setup (hit-rate gauge, daily
``cache_stats`` aggregation) is the separate A-15 ticket. Counters are
process-local for both backends; the Redis mirror keys
``orya:cache_stats:{date}:{tool}`` exist for cross-process tooling.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Response

from app.core.cache import get_cache_stats

router = APIRouter(tags=["metrics"])

#: Prometheus text exposition format (0.0.4).
PROMETHEUS_MEDIA_TYPE = "text/plain; version=0.0.4; charset=utf-8"


def _escape_label(value: str) -> str:
    """Escape a Prometheus label value (backslash, quote, newline)."""
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def _render_prometheus(stats: dict[str, Any]) -> str:
    """Render cache counters in Prometheus text exposition format."""
    lines: list[str] = []
    for metric, field, help_text in (
        (
            "orya_tool_cache_hits_total",
            "hits",
            "Total tool-result cache hits per tool (M-21).",
        ),
        (
            "orya_tool_cache_misses_total",
            "misses",
            "Total tool-result cache misses per tool (M-21).",
        ),
    ):
        lines.append(f"# HELP {metric} {help_text}")
        lines.append(f"# TYPE {metric} counter")
        for tool in sorted(stats.get("tools", {})):
            value = stats["tools"][tool][field]
            lines.append(f'{metric}{{tool="{_escape_label(tool)}"}} {value}')
    return "\n".join(lines) + "\n"


@router.get("/metrics")
async def metrics() -> Response:
    """Prometheus exposition of the tool-cache counters (M-21 AC)."""
    return Response(
        content=_render_prometheus(get_cache_stats()), media_type=PROMETHEUS_MEDIA_TYPE
    )


@router.get("/tools/cache-stats")
async def cache_stats() -> dict[str, Any]:
    """Per-tool cache statistics: hits, misses, hit_rate, backend, TTL."""
    return get_cache_stats()
