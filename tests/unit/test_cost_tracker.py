"""Unit tests for A-13 — cost tracker seam (app.core.cost_tracker).

No infra: the Redis backend is exercised through a fake client, the
memory backend is the default. Pricing math is checked against the real
``pricing.yaml`` entries (haiku/sonnet list prices).
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from app.core.config import clear_settings_cache, get_settings
from app.core.cost_tracker import (
    MemoryCostStore,
    RedisCostStore,
    close_cost_store,
    get_cost_identity,
    get_cost_store,
    init_cost_store,
    record_usage,
    set_cost_identity,
    set_cost_store,
    with_cost_identity,
)

_MANAGED_ENV_VARS = frozenset(
    {
        "DATABASE_URL",
        "LOG_LEVEL",
        "REDIS_URL",
        "COST_ROUTER_ENABLED",
        "COST_ROUTER_FALLBACK_MODEL",
        "COST_BUDGET_DEFAULT_USD",
        "COST_BACKEND",
    }
)


@pytest.fixture(autouse=True)
def isolated(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Sandbox env/config, fresh cost store + settings (A-13 tests)."""
    for name in list(os.environ):
        if name.startswith("ORYA_") or name in _MANAGED_ENV_VARS:
            monkeypatch.delenv(name, raising=False)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ORYA_CONFIG_PATH", str(tmp_path / "config.yaml"))
    clear_settings_cache()
    set_cost_store(None)
    set_cost_identity(None)
    yield
    set_cost_store(None)
    set_cost_identity(None)
    clear_settings_cache()


# --- settings ------------------------------------------------------------------


def test_settings_defaults() -> None:
    settings = get_settings()
    assert settings.cost_router_enabled is False
    assert settings.cost_router_fallback_model == "claude-haiku-3.5"
    assert settings.cost_budget_default_usd == 50.0
    assert settings.cost_backend == "auto"


# --- memory store --------------------------------------------------------------


async def test_memory_store_accumulates_daily_spend() -> None:
    store = MemoryCostStore()
    assert await store.get_spend("session:s1") == 0.0
    await store.add_spend("session:s1", 1.25)
    await store.add_spend("session:s1", 2.5)
    assert await store.get_spend("session:s1") == pytest.approx(3.75)
    # identities are independent
    assert await store.get_spend("session:s2") == 0.0


async def test_memory_store_limit_default_and_override() -> None:
    store = MemoryCostStore()
    assert await store.get_limit("session:s1") == pytest.approx(50.0)
    await store.set_limit("session:s1", 10.0)
    assert await store.get_limit("session:s1") == pytest.approx(10.0)
    assert await store.get_limit("session:s2") == pytest.approx(50.0)


def test_default_limit_follows_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ORYA_COST_BUDGET_DEFAULT_USD", "12.5")
    clear_settings_cache()
    assert get_settings().cost_budget_default_usd == pytest.approx(12.5)


# --- record_usage --------------------------------------------------------------


async def test_record_usage_is_noop_without_identity() -> None:
    set_cost_store(MemoryCostStore())
    await record_usage("anthropic", "claude-3-5-haiku-latest", 1000, 500)
    assert await get_cost_store().get_spend("session:s1") == 0.0
    assert get_cost_identity() is None


async def test_record_usage_prices_haiku_from_pricing_yaml() -> None:
    store = MemoryCostStore()
    set_cost_store(store)
    set_cost_identity("session:s1")
    # haiku: input 0.0008 / output 0.004 per 1k → 1000 in + 500 out = 0.0028
    await record_usage("anthropic", "claude-3-5-haiku-latest", 1000, 500)
    assert await store.get_spend("session:s1") == pytest.approx(0.0028)


async def test_record_usage_prices_sonnet_from_pricing_yaml() -> None:
    store = MemoryCostStore()
    set_cost_store(store)
    set_cost_identity("user:u1")
    # sonnet: input 0.003 / output 0.015 per 1k → 2000 in + 1000 out = 0.021
    await record_usage("anthropic", "claude-3-5-sonnet-latest", 2000, 1000)
    assert await store.get_spend("user:u1") == pytest.approx(0.021)


async def test_record_usage_unknown_model_costs_zero() -> None:
    store = MemoryCostStore()
    set_cost_store(store)
    set_cost_identity("session:s1")
    await record_usage("acme", "acme-unknown-model", 10_000, 10_000)
    assert await store.get_spend("session:s1") == 0.0


async def test_record_usage_never_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    class _BrokenStore:
        async def add_spend(self, identity: str, usd: float) -> None:
            raise RuntimeError("store down")

    set_cost_store(_BrokenStore())
    set_cost_identity("session:s1")
    await record_usage("anthropic", "claude-3-5-haiku-latest", 1000, 500)  # no raise


def test_with_cost_identity_restores_previous() -> None:
    set_cost_identity("session:outer")
    with with_cost_identity("session:inner"):
        assert get_cost_identity() == "session:inner"
    assert get_cost_identity() == "session:outer"


# --- redis store ---------------------------------------------------------------


class CountingRedis:
    """Minimal async Redis double: INCRBYFLOAT + GET + EXPIRE + SET."""

    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.values: dict[str, str] = {}
        self.expire_calls: list[str] = []
        self.set_calls: list[tuple[str, str]] = []

    def _check(self) -> None:
        if self.fail:
            raise ConnectionError("redis down")

    async def incrbyfloat(self, key: str, amount: float) -> float:
        self._check()
        self.values[key] = str(float(self.values.get(key, "0")) + float(amount))
        return float(self.values[key])

    async def get(self, key: str) -> str | None:
        self._check()
        return self.values.get(key)

    async def expire(self, key: str, seconds: int) -> bool:
        self._check()
        self.expire_calls.append(key)
        return True

    async def set(self, key: str, value: str) -> bool:
        self._check()
        self.set_calls.append((key, value))
        self.values[key] = value
        return True


async def test_redis_store_uses_orya_cost_and_limit_keys() -> None:
    redis = CountingRedis()
    store = RedisCostStore(redis)
    await store.add_spend("session:s1", 1.5)
    await store.add_spend("session:s1", 0.25)
    assert await store.get_spend("session:s1") == pytest.approx(1.75)
    assert any(k.startswith("orya:cost:session:s1:") for k in redis.values)
    assert redis.expire_calls, "first touch must stamp the TTL"

    assert await store.get_limit("session:s1") == pytest.approx(50.0)
    await store.set_limit("session:s1", 5.0)
    assert await store.get_limit("session:s1") == pytest.approx(5.0)
    assert redis.set_calls[0][0] == "orya:limit:session:s1"


async def test_redis_store_fails_soft() -> None:
    store = RedisCostStore(CountingRedis(fail=True))
    await store.add_spend("session:s1", 9.99)  # no raise
    assert await store.get_spend("session:s1") == 0.0
    assert await store.get_limit("session:s1") == pytest.approx(50.0)


# --- init / close --------------------------------------------------------------


async def test_init_cost_store_disabled_by_kill_switch() -> None:
    assert get_settings().cost_router_enabled is False
    await init_cost_store()
    assert isinstance(get_cost_store(), MemoryCostStore)


async def test_init_cost_store_memory_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ORYA_COST_ROUTER_ENABLED", "true")
    monkeypatch.setenv("ORYA_COST_BACKEND", "memory")
    clear_settings_cache()
    await init_cost_store(force=True)
    assert isinstance(get_cost_store(), MemoryCostStore)


async def test_close_cost_store_restores_memory() -> None:
    set_cost_store(RedisCostStore(CountingRedis()))
    await close_cost_store()
    assert isinstance(get_cost_store(), MemoryCostStore)
