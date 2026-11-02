"""Unit tests for M-21 — /metrics (Prometheus text) + /tools/cache-stats."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.cache import MemoryCache, set_cache
from app.core.config import clear_settings_cache
from app.core.cost_tracker import add_cost_total, reset_cost_totals

_MANAGED_ENV_VARS = frozenset(
    {
        "REDIS_URL",
        "CACHE_BACKEND",
        "CACHE_TTL_SECONDS",
        "ORYA_REDIS_URL",
        "ORYA_CACHE_BACKEND",
        "ORYA_CACHE_TTL_SECONDS",
    }
)


@pytest.fixture(autouse=True)
def isolated(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Sandbox settings and pin a fresh MemoryCache for deterministic stats."""
    for name in list(os.environ):
        if name.startswith("ORYA_") or name in _MANAGED_ENV_VARS:
            monkeypatch.delenv(name, raising=False)
    monkeypatch.chdir(tmp_path)
    clear_settings_cache()
    set_cache(MemoryCache())
    reset_cost_totals()
    yield
    set_cache(None)
    reset_cost_totals()
    clear_settings_cache()


async def _seed_cache_async(reads: int = 1, misses: int = 1) -> None:
    """Drive ``reads`` hits and ``misses`` misses through the read cache."""
    from app.core.cache import build_cache_key, get_cache

    cache = get_cache()
    fresh = build_cache_key("read", {"path": "seed"}, 1)
    await cache.set(fresh, "payload")
    for _ in range(misses):
        await cache.get(build_cache_key("read", {"path": "miss"}, 1))
    for _ in range(reads):
        await cache.get(fresh)


def _seed_cache(reads: int = 1, misses: int = 1) -> None:
    """Sync wrapper: these endpoint tests are sync (TestClient)."""
    asyncio.run(_seed_cache_async(reads, misses))


def test_metrics_is_prometheus_text(client: TestClient):
    response = client.get("/metrics")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    assert "version=0.0.4" in response.headers["content-type"]
    body = response.text
    assert "# HELP orya_tool_cache_hits_total" in body
    assert "# TYPE orya_tool_cache_hits_total counter" in body
    assert "# TYPE orya_tool_cache_misses_total counter" in body
    assert "# TYPE orya_cost_aware_switch_total counter" in body
    assert "# TYPE orya_llm_cost_usd_total counter" in body
    assert "# TYPE orya_langfuse_export_spans_total counter" in body
    assert "# TYPE orya_langfuse_export_errors_total counter" in body
    # A-20: connection-pool gauges (HELP/TYPE always present)
    assert "# TYPE orya_llm_pool_size gauge" in body
    assert "# TYPE orya_llm_pool_hit_rate gauge" in body
    assert "# TYPE orya_llm_pool_unhealthy_total counter" in body


def test_metrics_reports_cost_aware_switches(client: TestClient):
    """A-13: an actual degrade shows up as a labelled switch counter."""
    import asyncio

    from app.core.cost_tracker import MemoryCostStore, set_cost_store
    from app.core.llm.cost_router import (
        CostAwareRouter,
        reset_switch_stats,
    )

    reset_switch_stats()
    store = MemoryCostStore()

    async def _degrade() -> None:
        await store.set_limit("session:m1", 50.0)
        await store.add_spend("session:m1", 40.0)
        router = CostAwareRouter("claude-sonnet-3.5", "claude-haiku-3.5", store=store)
        await router.get_model_for_user("session:m1")

    asyncio.run(_degrade())
    try:
        body = client.get("/metrics").text
        assert (
            'orya_cost_aware_switch_total{from_model="claude-sonnet-3.5",'
            'to_model="claude-haiku-3.5"} 1' in body
        )
    finally:
        set_cost_store(None)
        reset_switch_stats()


def test_metrics_reports_per_tool_counters(client: TestClient):
    _seed_cache(reads=2, misses=1)

    body = client.get("/metrics").text

    assert 'orya_tool_cache_hits_total{tool="read"} 2' in body
    assert 'orya_tool_cache_misses_total{tool="read"} 1' in body


def test_metrics_reports_cost_totals(client: TestClient):
    """A-14: per-model spend accumulated by the seam's cost.* attributes."""
    reset_cost_totals()
    add_cost_total("deepseek-chat", 0.25)
    add_cost_total("deepseek-chat", 0.5)
    add_cost_total("local-model", 0.0)

    body = client.get("/metrics").text

    assert "# HELP orya_llm_cost_usd_total" in body
    assert 'orya_llm_cost_usd_total{model="deepseek-chat"} 0.75' in body
    # unpriced/free models keep a visible zero-valued series
    assert 'orya_llm_cost_usd_total{model="local-model"} 0.0' in body


def test_metrics_cost_totals_empty_state(client: TestClient):
    reset_cost_totals()

    body = client.get("/metrics").text

    assert "# TYPE orya_llm_cost_usd_total counter" in body
    assert "orya_llm_cost_usd_total{" not in body


def test_metrics_accumulates_across_requests(client: TestClient):
    _seed_cache(reads=1, misses=1)
    first = client.get("/metrics").text
    _seed_cache(reads=1, misses=0)
    second = client.get("/metrics").text

    assert 'orya_tool_cache_hits_total{tool="read"} 1' in first
    assert 'orya_tool_cache_hits_total{tool="read"} 2' in second


def test_cache_stats_endpoint_shape(client: TestClient):
    _seed_cache(reads=1, misses=3)

    response = client.get("/tools/cache-stats")

    assert response.status_code == 200
    data = response.json()
    assert data["backend"] == "MemoryCache"
    assert data["ttl_seconds"] == 300.0
    assert data["tools"]["read"] == {
        "hits": 1,
        "misses": 3,
        "hit_rate": 0.25,
    }


def test_metrics_registered_on_app(client: TestClient):
    from app.main import app

    paths = set(app.openapi()["paths"])
    assert "/metrics" in paths
    assert "/tools/cache-stats" in paths
