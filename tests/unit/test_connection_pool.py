"""Unit tests for A-20 — ConnectionPool (keepalive + hot adapters)."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from langchain_core.messages import AIMessage, HumanMessage
from pydantic import ValidationError

from app.api.metrics import _render_pool_metrics
from app.core.config import clear_settings_cache
from app.core.llm import get_connection_pool, get_llm, reset_connection_pool
from app.core.llm.connection_pool import (
    PROBE_TIMEOUT_S,
    ConnectionPool,
    PooledConnection,
    clear_tcp_attrs,
    get_pool_stats,
    peek_tcp_attrs,
    pool_health_worker,
    stage_tcp_attrs,
)
from app.core.llm.registry import clear_registry_cache
from app.core.llm.tracing import TracedChatModel
from app.core.observability.spans import clear_span_buffer, get_span_buffer

#: Non-ORYA spellings of the A-20 settings (conftest pins the health
#: interval for the app lifespan; these tests need the real defaults).
_MANAGED_ENV_VARS = frozenset(
    {
        "LLM_POOL_SIZE",
        "LLM_POOL_HEALTH_INTERVAL",
        "CONNECTION_POOL_ENABLED",
        "LLM_POOL_ENABLED",
        "LLM_PROMPT_CACHE_ENABLED",
        "LLM_PROMPT_CACHE_TTL",
        "LLM_PROMPT_CACHE_MAX_SIZE",
    }
)


@pytest.fixture(autouse=True)
def isolated(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Sandbox settings/pool/span state around every test."""
    for name in list(os.environ):
        if name.startswith("ORYA_") or name in _MANAGED_ENV_VARS:
            monkeypatch.delenv(name, raising=False)
    monkeypatch.chdir(tmp_path)
    clear_settings_cache()
    clear_registry_cache()
    reset_connection_pool()
    clear_tcp_attrs()
    clear_span_buffer()
    yield
    clear_tcp_attrs()
    clear_span_buffer()
    reset_connection_pool()
    clear_registry_cache()
    clear_settings_cache()


# --- settings -------------------------------------------------------------


def test_settings_defaults():
    from app.core.config import get_settings

    settings = get_settings()
    assert settings.llm_pool_enabled is True
    assert settings.llm_pool_size == 4
    assert settings.llm_pool_health_interval == 30


def test_settings_env_overrides(monkeypatch: pytest.MonkeyPatch):
    from app.core.config import get_settings

    monkeypatch.setenv("CONNECTION_POOL_ENABLED", "false")
    monkeypatch.setenv("LLM_POOL_SIZE", "8")
    monkeypatch.setenv("LLM_POOL_HEALTH_INTERVAL", "0")
    clear_settings_cache()
    settings = get_settings()
    assert settings.llm_pool_enabled is False
    assert settings.llm_pool_size == 8
    assert settings.llm_pool_health_interval == 0

    # First alias wins when both spellings are present.
    monkeypatch.setenv("ORYA_LLM_POOL_SIZE", "2")
    clear_settings_cache()
    assert get_settings().llm_pool_size == 8


def test_settings_pool_size_bounds(monkeypatch: pytest.MonkeyPatch):
    from app.core.config import get_settings

    for bad in ("0", "17"):
        monkeypatch.setenv("LLM_POOL_SIZE", bad)
        clear_settings_cache()
        with pytest.raises(ValidationError):
            get_settings()
        monkeypatch.delenv("LLM_POOL_SIZE", raising=False)
    clear_settings_cache()


# --- acquire --------------------------------------------------------------


def test_acquire_miss_then_hit_reuses_client():
    pool = ConnectionPool(max_size=4)
    first = pool.acquire("deepseek", base_url="https://api.deepseek.com/v1")
    second = pool.acquire("deepseek", base_url="https://api.deepseek.com/v1")

    assert first.pool_hit is False
    assert second.pool_hit is True
    assert first.client is second.client
    assert second.connect_duration_ms < 50  # warm AC: ≤ 50 ms

    stats = pool.stats()["deepseek"]
    assert stats == {
        "size": 1,
        "hits": 1,
        "misses": 1,
        "hit_rate": 0.5,
        "unhealthy_total": 0,
        "evicted_total": 0,
        "max_size": 4,
    }


def test_providers_are_isolated():
    pool = ConnectionPool()
    a = pool.acquire("anthropic", flavor="httpx2")
    b = pool.acquire("deepseek")

    assert a.client is not b.client
    assert type(a.client).__module__.partition(".")[0] == "httpx2"
    assert type(b.client).__module__.partition(".")[0] == "httpx"
    assert set(pool.stats()) == {"anthropic", "deepseek"}
    assert pool.stats()["anthropic"]["size"] == 1


def test_hit_rate_over_sequential_acquires():
    pool = ConnectionPool()
    pool.acquire("p")
    for _ in range(3):
        pool.acquire("p")
    assert pool.stats()["p"]["hit_rate"] == 0.75


def test_exclusive_spawns_and_holds_up_to_max_size():
    pool = ConnectionPool(max_size=4)
    clients = [pool.acquire("p", exclusive=True).client for _ in range(4)]
    assert pool.stats()["p"]["size"] == 4
    assert len({id(c) for c in clients}) == 4


async def test_lru_eviction_on_fifth_exclusive_call():
    """Spec AC: max_size=4, 5th provider call evicts the oldest connection."""
    pool = ConnectionPool(max_size=4)
    first = pool.acquire("p", exclusive=True).client
    for _ in range(3):
        pool.acquire("p", exclusive=True)
    fifth = pool.acquire("p", exclusive=True)
    await asyncio.sleep(0.05)  # scheduled aclose runs

    stats = pool.stats()["p"]
    assert stats["size"] == 4
    assert stats["evicted_total"] == 1
    assert first.is_closed is True
    assert fifth.client.is_closed is False


def test_kill_switch_off_returns_untracked_client():
    pool = ConnectionPool(enabled=False)
    result = pool.acquire("p")
    assert result.pool_hit is False
    assert isinstance(result.client, httpx.AsyncClient)
    assert pool.stats() == {}


def test_acquire_fail_open_when_spawn_broken(monkeypatch: pytest.MonkeyPatch):
    pool = ConnectionPool()
    real = pool._new_client
    calls = {"n": 0}

    def broken(flavor: str = "httpx"):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("spawn boom")
        return real(flavor)

    monkeypatch.setattr(pool, "_new_client", broken)
    result = pool.acquire("z")

    assert isinstance(result.client, httpx.AsyncClient)
    assert result.pool_hit is False
    assert pool.stats() == {}  # nothing half-tracked


# --- health-check ---------------------------------------------------------


async def test_health_check_kills_unhealthy_and_fails_open():
    pool = ConnectionPool()
    pool.acquire("y")

    async def probe_ok(entry: PooledConnection) -> tuple[bool, float]:
        return False, 1.0

    pool._probe = probe_ok  # type: ignore[method-assign]
    summary = await pool.health_check()

    assert summary["checked"] == 1
    assert summary["unhealthy"] and summary["unhealthy"][0].startswith("y:")
    assert pool.stats()["y"]["size"] == 0
    assert pool.stats()["y"]["unhealthy_total"] == 1

    # Fail-open: the next acquire spawns a replacement (a miss).
    again = pool.acquire("y")
    assert again.pool_hit is False
    assert pool.stats()["y"]["size"] == 1


async def test_health_check_keeps_healthy_entries():
    pool = ConnectionPool()
    pool.acquire("y")

    async def probe_ok(entry: PooledConnection) -> tuple[bool, float]:
        return True, 4.2

    pool._probe = probe_ok  # type: ignore[method-assign]
    summary = await pool.health_check()

    assert summary["unhealthy"] == []
    entry = next(iter(pool._pools["y"].values()))
    assert entry.last_probe_ms == 4.2
    assert pool.stats()["y"]["size"] == 1


async def test_probe_head_uses_health_url():
    pool = ConnectionPool()
    pool.acquire(
        "local",
        base_url="http://localhost:11434/v1",
        health_url="http://localhost:11434/api/tags",
    )
    entry = next(iter(pool._pools["local"].values()))

    entry.client.head = AsyncMock(return_value=SimpleNamespace(status_code=200))
    ok, _ = await pool._probe(entry)
    assert ok is True
    entry.client.head.assert_awaited_once_with(
        "http://localhost:11434/api/tags", timeout=PROBE_TIMEOUT_S
    )

    # 5xx = dead endpoint (405/401 still count as alive).
    entry.client.head = AsyncMock(return_value=SimpleNamespace(status_code=503))
    ok, _ = await pool._probe(entry)
    assert ok is False


async def test_probe_tcp_connect_probe():
    """No health_path → TCP connect probe against the provider base_url."""
    server = await asyncio.start_server(lambda r, w: w.close(), "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    pool = ConnectionPool()
    entry = PooledConnection(
        id="tcp",
        provider="local",
        client=pool._new_client(),
        base_url=f"http://127.0.0.1:{port}",
    )
    try:
        ok, latency = await pool._probe(entry)
        assert ok is True
        assert latency >= 0.0
    finally:
        server.close()
        await server.wait_closed()

    # Server gone → connection refused → unhealthy.
    ok, _ = await pool._probe(entry)
    assert ok is False


async def test_worker_runs_a_health_pass(monkeypatch: pytest.MonkeyPatch):
    import app.core.llm.connection_pool as cp

    pool = ConnectionPool()
    pool.acquire("w")

    async def probe_bad(entry: PooledConnection) -> tuple[bool, float]:
        return False, 2.5

    pool._probe = probe_bad  # type: ignore[method-assign]
    monkeypatch.setattr(cp, "_pool", pool)

    task = asyncio.create_task(cp.pool_health_worker(0.05))
    await asyncio.sleep(0.2)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

    assert pool.stats()["w"]["unhealthy_total"] == 1


async def test_worker_disabled_interval_returns_immediately():
    await asyncio.wait_for(pool_health_worker(0), timeout=1.0)


# --- span staging + tracing ----------------------------------------------


def test_stage_and_peek_tcp_attrs():
    stage_tcp_attrs("deepseek", pool_hit=True, connect_duration_ms=0.5)
    stage_tcp_attrs("openai", pool_hit=False, connect_duration_ms=120.0)

    assert peek_tcp_attrs("deepseek") == (True, 0.5)
    assert peek_tcp_attrs("openai") == (False, 120.0)
    assert peek_tcp_attrs("unknown") is None

    clear_tcp_attrs()
    assert peek_tcp_attrs("deepseek") is None


async def test_traced_model_stamps_tcp_span_attributes():
    stage_tcp_attrs("deepseek", pool_hit=True, connect_duration_ms=0.016)
    inner = SimpleNamespace(
        ainvoke=AsyncMock(return_value=AIMessage(content="ok")),
    )
    llm = TracedChatModel(
        inner=inner, llm_provider="deepseek", llm_model="deepseek-chat"
    )
    result = await llm.ainvoke([HumanMessage(content="hi")])

    assert result.content == "ok"
    spans = [s for s in get_span_buffer() if s.span_type == "llm.call"]
    assert spans, "llm.call span expected"
    assert spans[-1].attributes["tcp.pool_hit"] is True
    assert spans[-1].attributes["tcp.connect_duration_ms"] == 0.016


def test_traced_model_without_staging_has_no_tcp_attributes():
    inner = SimpleNamespace(
        invoke=lambda *a, **k: AIMessage(content="ok"),
    )
    llm = TracedChatModel(
        inner=inner, llm_provider="deepseek", llm_model="deepseek-chat"
    )
    llm.invoke([HumanMessage(content="hi")])

    spans = [s for s in get_span_buffer() if s.span_type == "llm.call"]
    assert spans
    assert "tcp.pool_hit" not in spans[-1].attributes


# --- factory wiring -------------------------------------------------------


def test_factory_wires_openai_compat_client():
    llm = get_llm("deepseek", "deepseek-chat", api_key="sk-fake")
    pool = get_connection_pool()
    entry = next(iter(pool._pools["deepseek"].values()))

    assert llm.http_async_client is entry.client
    staged = peek_tcp_attrs("deepseek")
    assert staged is not None
    assert staged[0] is False  # first construction = miss (cold)

    # Second construction reuses the warm connection.
    get_llm("deepseek", "deepseek-chat", api_key="sk-fake")
    assert pool.stats()["deepseek"]["hits"] == 1
    assert peek_tcp_attrs("deepseek")[0] is True


def test_factory_wires_anthropic_httpx2_client():
    llm = get_llm("anthropic", "claude-sonnet-3.5", api_key="sk-ant-fake")
    pool = get_connection_pool()
    entry = next(iter(pool._pools["anthropic"].values()))

    assert entry.flavor == "httpx2"
    # anthropic>=1.15 rejects httpx objects; the injected client is httpx2.
    assert type(entry.client).__module__.partition(".")[0] == "httpx2"
    assert llm._async_client._client is entry.client


def test_factory_wires_google_client():
    llm = get_llm("google", "gemini-2.0-flash", api_key="fake-key")
    pool = get_connection_pool()
    entry = next(iter(pool._pools["google"].values()))

    http_options = llm.client._api_client._http_options
    assert http_options.httpx_async_client is entry.client


def test_factory_kill_switch_off_skips_pool(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("CONNECTION_POOL_ENABLED", "false")
    clear_settings_cache()
    reset_connection_pool()

    llm = get_llm("deepseek", "deepseek-chat", api_key="sk-fake")

    assert get_connection_pool().stats() == {}
    assert peek_tcp_attrs("deepseek") is None
    assert getattr(llm, "http_async_client", None) is None


# --- metrics --------------------------------------------------------------


def test_pool_metrics_render():
    pool = get_connection_pool()
    pool.acquire("deepseek")
    pool.acquire("deepseek")

    text = "\n".join(_render_pool_metrics())
    assert "# HELP orya_llm_pool_size" in text
    assert "# TYPE orya_llm_pool_size gauge" in text
    assert 'orya_llm_pool_size{provider="deepseek"} 1' in text
    assert "# TYPE orya_llm_pool_hit_rate gauge" in text
    assert "# TYPE orya_llm_pool_unhealthy_total counter" in text
    assert 'orya_llm_pool_unhealthy_total{provider="deepseek"} 0' in text

    assert get_pool_stats()["deepseek"]["hit_rate"] == 0.5
