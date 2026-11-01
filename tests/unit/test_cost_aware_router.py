"""Unit tests for A-13 вЂ” CostAwareRouter (app.core.llm.cost_router).

Thresholds on ``budget_ratio``: <0.7 primary; 0.7-0.9 fallback +
``degraded``; 0.9-1.0 fallback + ``warning``; >=1.0 ``blocked``. The
kill-switch off path must be a pure pass-through.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from app.core.config import clear_settings_cache, get_settings
from app.core.cost_tracker import MemoryCostStore, set_cost_store
from app.core.llm.cost_router import (
    CostAwareRouter,
    ModelSelection,
    get_switch_stats,
    reset_switch_stats,
    resolve_turn_model,
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

_PRIMARY = "claude-sonnet-3.5"
_FALLBACK = "claude-haiku-3.5"


@pytest.fixture(autouse=True)
def isolated(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Sandbox env/config, fresh store + switch counter (A-13 tests)."""
    for name in list(os.environ):
        if name.startswith("ORYA_") or name in _MANAGED_ENV_VARS:
            monkeypatch.delenv(name, raising=False)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ORYA_CONFIG_PATH", str(tmp_path / "config.yaml"))
    clear_settings_cache()
    set_cost_store(None)
    reset_switch_stats()
    yield
    set_cost_store(None)
    reset_switch_stats()
    clear_settings_cache()


# --- thresholds ----------------------------------------------------------------


async def test_below_degrade_ratio_keeps_primary() -> None:
    store = MemoryCostStore()
    router = CostAwareRouter(_PRIMARY, _FALLBACK, store=store)
    selection = await router.get_model_for_user("session:s1")
    assert selection.model == _PRIMARY
    assert selection.degraded is False
    assert selection.warning is False
    assert selection.blocked is False
    assert selection.ratio == 0.0
    assert get_switch_stats() == {}


async def test_just_below_degrade_ratio_keeps_primary() -> None:
    store = MemoryCostStore()
    await store.set_limit("session:s1", 50.0)
    await store.add_spend("session:s1", 34.99)  # ratio 0.6998
    router = CostAwareRouter(_PRIMARY, _FALLBACK, store=store)
    selection = await router.get_model_for_user("session:s1")
    assert selection.model == _PRIMARY
    assert selection.degraded is False


async def test_at_degrade_ratio_switches_to_fallback() -> None:
    store = MemoryCostStore()
    await store.set_limit("session:s1", 50.0)
    await store.add_spend("session:s1", 35.0)  # ratio 0.70
    router = CostAwareRouter(_PRIMARY, _FALLBACK, store=store)
    selection = await router.get_model_for_user("session:s1")
    assert selection.model == _FALLBACK
    assert selection.degraded is True
    assert selection.warning is False
    assert selection.blocked is False
    assert selection.ratio == pytest.approx(0.7)
    assert get_switch_stats() == {(_PRIMARY, _FALLBACK): 1}


async def test_just_below_warn_ratio_degrades_without_warning() -> None:
    store = MemoryCostStore()
    await store.set_limit("session:s1", 50.0)
    await store.add_spend("session:s1", 44.99)  # ratio 0.8998
    router = CostAwareRouter(_PRIMARY, _FALLBACK, store=store)
    selection = await router.get_model_for_user("session:s1")
    assert selection.degraded is True
    assert selection.warning is False


async def test_at_warn_ratio_adds_warning() -> None:
    store = MemoryCostStore()
    await store.set_limit("session:s1", 50.0)
    await store.add_spend("session:s1", 45.0)  # ratio 0.90
    router = CostAwareRouter(_PRIMARY, _FALLBACK, store=store)
    selection = await router.get_model_for_user("session:s1")
    assert selection.model == _FALLBACK
    assert selection.degraded is True
    assert selection.warning is True
    assert selection.blocked is False


async def test_at_full_budget_blocks() -> None:
    store = MemoryCostStore()
    await store.set_limit("session:s1", 50.0)
    await store.add_spend("session:s1", 50.0)  # ratio 1.00
    router = CostAwareRouter(_PRIMARY, _FALLBACK, store=store)
    selection = await router.get_model_for_user("session:s1")
    assert selection.blocked is True
    assert selection.degraded is True
    assert selection.warning is True


async def test_zero_limit_is_always_blocked() -> None:
    store = MemoryCostStore()
    await store.set_limit("session:s1", 0.0)
    router = CostAwareRouter(_PRIMARY, _FALLBACK, store=store)
    selection = await router.get_model_for_user("session:s1")
    assert selection.blocked is True


async def test_budget_ratio_reports_inf_on_zero_limit() -> None:
    store = MemoryCostStore()
    await store.set_limit("session:s1", 0.0)
    router = CostAwareRouter(_PRIMARY, _FALLBACK, store=store)
    assert await router.get_budget_ratio("session:s1") == float("inf")


# --- switch counter + payload --------------------------------------------------


async def test_switch_counter_records_requested_model_as_source() -> None:
    store = MemoryCostStore()
    await store.set_limit("session:s1", 50.0)
    await store.add_spend("session:s1", 45.0)
    router = CostAwareRouter(_PRIMARY, _FALLBACK, store=store)
    await router.get_model_for_user("session:s1", requested_model="claude-opus-4")
    assert get_switch_stats() == {("claude-opus-4", _FALLBACK): 1}


def test_model_selection_as_dict_shape() -> None:
    payload = ModelSelection(
        model=_FALLBACK,
        degraded=True,
        warning=True,
        ratio=0.9123456,
        primary=_PRIMARY,
        fallback=_FALLBACK,
    ).as_dict()
    assert payload == {
        "degraded": True,
        "warning": True,
        "blocked": False,
        "ratio": 0.9123,
        "model": _FALLBACK,
        "primary": _PRIMARY,
        "fallback": _FALLBACK,
    }


# --- resolve_turn_model (route entry point) ------------------------------------


async def test_resolve_turn_model_passthrough_when_disabled() -> None:
    assert get_settings().cost_router_enabled is False
    selection = await resolve_turn_model("session:s1", "claude-opus-4", None)
    assert selection.model == "claude-opus-4"
    assert selection.degraded is False
    assert selection.blocked is False


async def test_resolve_turn_model_passthrough_default_when_disabled() -> None:
    selection = await resolve_turn_model("session:s1", None, None)
    assert selection.model is None  # factory default path unchanged


async def _enable_router(monkeypatch: pytest.MonkeyPatch, **env: str) -> None:
    monkeypatch.setenv("ORYA_COST_ROUTER_ENABLED", "true")
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    clear_settings_cache()


async def test_resolve_turn_model_uses_fallback_alias(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _enable_router(monkeypatch)
    store = MemoryCostStore()
    await store.set_limit("session:s1", 50.0)
    await store.add_spend("session:s1", 40.0)
    set_cost_store(store)
    selection = await resolve_turn_model("session:s1", None, None)
    assert selection.model == "claude-haiku-3.5"
    assert selection.degraded is True
    assert selection.primary == get_settings().llm_model


async def test_resolve_turn_model_budget_wins_over_explicit_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _enable_router(monkeypatch)
    store = MemoryCostStore()
    await store.set_limit("session:s1", 50.0)
    await store.add_spend("session:s1", 40.0)
    set_cost_store(store)
    selection = await resolve_turn_model("session:s1", "claude-opus-4", None)
    assert selection.model == "claude-haiku-3.5"
    assert selection.degraded is True
    assert get_switch_stats() == {("claude-opus-4", "claude-haiku-3.5"): 1}


async def test_resolve_turn_model_blocks_at_full_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _enable_router(monkeypatch)
    store = MemoryCostStore()
    await store.set_limit("session:s1", 50.0)
    await store.add_spend("session:s1", 50.0)
    set_cost_store(store)
    selection = await resolve_turn_model("session:s1", None, None)
    assert selection.blocked is True


async def test_resolve_turn_model_custom_fallback_alias(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _enable_router(monkeypatch, ORYA_COST_ROUTER_FALLBACK_MODEL="glm-4-flash")
    store = MemoryCostStore()
    await store.set_limit("session:s1", 50.0)
    await store.add_spend("session:s1", 40.0)
    set_cost_store(store)
    selection = await resolve_turn_model("session:s1", None, None)
    assert selection.model == "glm-4-flash"


# A-17: Tests for pending span attributes (cost.over_budget)
async def test_get_model_for_user_emits_cost_over_budget_on_warning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A-17: When ratio >= 0.90, set cost.over_budget=true for agent.loop span."""
    await _enable_router(monkeypatch)
    store = MemoryCostStore()
    # Set budget to $50, spend $45 (ratio = 0.90) в†’ warning + cost.over_budget
    await store.set_limit("session:s1", 50.0)
    await store.add_spend("session:s1", 45.0)
    set_cost_store(store)

    router = CostAwareRouter(_PRIMARY, _FALLBACK, store)
    monkeypatch.setenv("AGENT_OBS_ENABLED", "1")

    # Clear any pending attrs before test
    from app.core.observability.spans import take_pending_span_attributes

    take_pending_span_attributes()

    selection = await router.get_model_for_user("session:s1")
    assert selection.warning is True
    assert selection.blocked is False
    assert selection.ratio == 0.90

    # A-17: cost.over_budget should be staged for agent.loop span
    pending = take_pending_span_attributes()
    assert pending == {"cost.over_budget": "true"}


async def test_get_model_for_user_emits_cost_over_budget_on_blocked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A-17: When ratio >= 1.0, set cost.over_budget=true for agent.loop span."""
    await _enable_router(monkeypatch)
    store = MemoryCostStore()
    # Set budget to $50, spend $50 (ratio = 1.0) в†’ blocked + cost.over_budget
    await store.set_limit("session:s1", 50.0)
    await store.add_spend("session:s1", 50.0)
    set_cost_store(store)

    router = CostAwareRouter(_PRIMARY, _FALLBACK, store)
    monkeypatch.setenv("AGENT_OBS_ENABLED", "1")

    # Clear any pending attrs before test
    from app.core.observability.spans import take_pending_span_attributes

    take_pending_span_attributes()

    selection = await router.get_model_for_user("session:s1")
    assert selection.blocked is True
    assert selection.ratio == 1.0

    # A-17: cost.over_budget should be staged for agent.loop span
    pending = take_pending_span_attributes()
    assert pending == {"cost.over_budget": "true"}


async def test_get_model_for_no_cost_over_budget_below_warning_threshold(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A-17: Below 0.90 ratio, no cost.over_budget attribute is set."""
    await _enable_router(monkeypatch)
    store = MemoryCostStore()
    # Set budget to $50, spend $36 (ratio = 0.72) в†’ degraded only
    await store.set_limit("session:s1", 50.0)
    await store.add_spend("session:s1", 36.0)
    set_cost_store(store)

    router = CostAwareRouter(_PRIMARY, _FALLBACK, store)
    monkeypatch.setenv("AGENT_OBS_ENABLED", "1")

    # Clear any pending attrs before test
    from app.core.observability.spans import take_pending_span_attributes

    take_pending_span_attributes()

    selection = await router.get_model_for_user("session:s1")
    assert selection.degraded is True
    assert selection.warning is False
    assert selection.ratio == 0.72

    # A-17: No cost.over_budget below warning threshold
    pending = take_pending_span_attributes()
    assert pending == {}


async def test_get_model_for_user_no_pending_attrs_when_obs_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A-17: When AGENT_OBS_ENABLED=0, no pending attrs are set even at warning."""
    await _enable_router(monkeypatch)
    store = MemoryCostStore()
    # Set budget to $50, spend $45 (ratio = 0.90) в†’ warning
    await store.set_limit("session:s1", 50.0)
    await store.add_spend("session:s1", 45.0)
    set_cost_store(store)

    router = CostAwareRouter(_PRIMARY, _FALLBACK, store)
    # Clear settings cache to ensure the env var takes effect
    from app.core.config import clear_settings_cache

    clear_settings_cache()
    monkeypatch.setenv("AGENT_OBS_ENABLED", "0")
    # Force settings reload to pick up the env var
    get_settings()

    # Clear any pending attrs before test
    from app.core.observability.spans import take_pending_span_attributes

    take_pending_span_attributes()

    selection = await router.get_model_for_user("session:s1")
    assert selection.warning is True
    assert selection.blocked is False
    assert selection.ratio == 0.90

    # A-17: No cost.over_budget when obs disabled
    pending = take_pending_span_attributes()
    assert pending == {}
