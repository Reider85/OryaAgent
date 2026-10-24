"""Unit tests for M-21 — /metrics (Prometheus text) + /tools/cache-stats."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.cache import MemoryCache, set_cache
from app.core.config import clear_settings_cache

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
    yield
    set_cache(None)
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


def test_metrics_reports_per_tool_counters(client: TestClient):
    _seed_cache(reads=2, misses=1)

    body = client.get("/metrics").text

    assert 'orya_tool_cache_hits_total{tool="read"} 2' in body
    assert 'orya_tool_cache_misses_total{tool="read"} 1' in body


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
