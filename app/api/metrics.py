"""Metrics API (M-21/M-22): /metrics (Prometheus text) + /tools/cache-stats.

Exposes the per-tool cache hit/miss counters of the active backend
(``app.core.cache``): the hand-rolled Prometheus exposition carries
``orya_tool_cache_hits_total{tool}`` / ``orya_tool_cache_misses_total{tool}``
(BACKLOG5 M-21 AC, ARCHITECT5 9.1) without a prometheus-client
dependency - the formal Prometheus/Grafana setup (hit-rate gauge, daily
``cache_stats`` aggregation) is the separate A-15 ticket. Counters are
process-local for both backends; the Redis mirror keys
``orya:cache_stats:{date}:{tool}`` exist for cross-process tooling.

M-22 adds ``orya_prompt_injection_warnings_total{source,pattern}`` —
the injection-detection counter of ``app.core.security``
(BACKLOG5 M-22 AC), fed by read/bash/grep/user-input detections.
A-13 adds ``orya_cost_aware_switch_total{from_model,to_model}`` — the
CostAwareRouter's model-degrade counter (BACKLOG5 A-13 AC), incremented
once per turn the budget actually forces a different model.
A-14 adds ``orya_llm_cost_usd_total{model}`` — the per-model USD spend
accumulated by the LLM seam's ``cost.*`` span attributes (PROMPT_ALPHA
A-14), counting every priced call regardless of the budget identity.
A-15 adds ``orya_langfuse_export_spans_total`` /
``orya_langfuse_export_errors_total`` — delivered/dropped counters of
the Langfuse OTLP exporter (``app.core.observability.langfuse``).
A-20 adds ``orya_llm_pool_size`` / ``orya_llm_pool_hit_rate`` /
``orya_llm_pool_unhealthy_total`` — the keepalive connection pool of the
LLM seam (``app.core.llm.connection_pool``): current clients per
provider, cumulative reuse ratio and killed-connection counter.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Response

from app.core.cache import get_cache_stats
from app.core.cost_tracker import get_cost_totals
from app.core.llm.connection_pool import get_pool_stats
from app.core.llm.cost_router import get_switch_stats
from app.core.observability.langfuse import get_export_stats
from app.core.security import get_injection_stats

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
    return lines


def _render_injection_counters() -> list[str]:
    """Render the M-22 injection-detection counter (always one HELP/TYPE)."""
    metric = "orya_prompt_injection_warnings_total"
    lines = [
        f"# HELP {metric} Suspected prompt-injection detections (M-22).",
        f"# TYPE {metric} counter",
    ]
    stats = get_injection_stats()
    for source in sorted(stats["by_source"]):
        patterns = stats["by_source"][source]
        for pattern in sorted(patterns):
            labels = (
                f'source="{_escape_label(source)}",pattern="{_escape_label(pattern)}"'
            )
            lines.append(f"{metric}{{{labels}}} {patterns[pattern]}")
    return lines


def _render_switch_counters() -> list[str]:
    """Render the A-13 cost-aware model-switch counter (one HELP/TYPE)."""
    metric = "orya_cost_aware_switch_total"
    lines = [
        f"# HELP {metric} Cost-aware router model switches by label pair (A-13).",
        f"# TYPE {metric} counter",
    ]
    for (from_model, to_model), count in sorted(get_switch_stats().items()):
        labels = (
            f'from_model="{_escape_label(from_model)}",'
            f'to_model="{_escape_label(to_model)}"'
        )
        lines.append(f"{metric}{{{labels}}} {count}")
    return lines


def _render_cost_totals() -> list[str]:
    """Render the A-14 per-model spend counter (one HELP/TYPE)."""
    metric = "orya_llm_cost_usd_total"
    lines = [
        f"# HELP {metric} Total USD spend per model from llm.call spans (A-14).",
        f"# TYPE {metric} counter",
    ]
    for model, total in sorted(get_cost_totals().items()):
        lines.append(f'{metric}{{model="{_escape_label(model)}"}} {total}')
    return lines


def _render_langfuse_export_counters() -> list[str]:
    """Render the A-15 Langfuse OTLP export counters (one HELP/TYPE each)."""
    stats = get_export_stats()
    spans_metric = "orya_langfuse_export_spans_total"
    errors_metric = "orya_langfuse_export_errors_total"
    return [
        f"# HELP {spans_metric} Spans delivered to the Langfuse OTLP endpoint (A-15).",
        f"# TYPE {spans_metric} counter",
        f"{spans_metric} {stats['exported_total']}",
        f"# HELP {errors_metric} Spans dropped or failed by the Langfuse exporter (A-15).",
        f"# TYPE {errors_metric} counter",
        f"{errors_metric} {stats['failed_total']}",
    ]


def _render_pool_metrics() -> list[str]:
    """Render the A-20 connection-pool gauges/counters (HELP/TYPE always)."""
    size_metric = "orya_llm_pool_size"
    hit_metric = "orya_llm_pool_hit_rate"
    unhealthy_metric = "orya_llm_pool_unhealthy_total"
    lines = [
        f"# HELP {size_metric} Hot keepalive connections currently pooled per provider (A-20).",
        f"# TYPE {size_metric} gauge",
        f"# HELP {hit_metric} Cumulative pool acquire hit ratio per provider (A-20).",
        f"# TYPE {hit_metric} gauge",
        f"# HELP {unhealthy_metric} Connections killed by the health-check per provider (A-20).",
        f"# TYPE {unhealthy_metric} counter",
    ]
    for provider, stats in get_pool_stats().items():
        label = f'provider="{_escape_label(provider)}"'
        lines.append(f"{size_metric}{{{label}}} {stats['size']}")
        lines.append(f"{hit_metric}{{{label}}} {stats['hit_rate']:.4f}")
        lines.append(f"{unhealthy_metric}{{{label}}} {stats['unhealthy_total']}")
    return lines


@router.get("/metrics")
async def metrics() -> Response:
    """Prometheus exposition: cache (M-21), injection (M-22), switch (A-13), cost (A-14), Langfuse export (A-15), pool (A-20)."""
    lines = (
        _render_prometheus(get_cache_stats())
        + _render_injection_counters()
        + _render_switch_counters()
        + _render_cost_totals()
        + _render_langfuse_export_counters()
        + _render_pool_metrics()
    )
    return Response(content="\n".join(lines) + "\n", media_type=PROMETHEUS_MEDIA_TYPE)


@router.get("/tools/cache-stats")
async def cache_stats() -> dict[str, Any]:
    """Per-tool cache statistics: hits, misses, hit_rate, backend, TTL."""
    return get_cache_stats()
