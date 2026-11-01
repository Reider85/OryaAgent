"""Unit tests for A-18 — TieredModelRouter (app.core.llm.tiered_router).

Tier decides the model (``small``/``large``/``tournament``), the budget
can only lower the tier to ``small`` at >=0.9 and block at >=1.0. The
``tier=None`` path of ``resolve_turn_model`` must stay byte-for-byte the
v6 CostAwareRouter behavior.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from app.core.config import clear_settings_cache
from app.core.cost_tracker import MemoryCostStore, set_cost_store
from app.core.llm.cost_router import (
    CostAwareRouter,
    ModelSelection,
    get_switch_stats,
    reset_switch_stats,
    resolve_turn_model,
)
from app.core.llm.registry import resolve_model
from app.core.llm.tiered_router import (
    TieredModelRouter,
    normalize_tier,
    tier_models,
)
from app.core.observability.spans import (
    take_pending_span_attributes,
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
        "AGENT_OBS_ENABLED",
        "TIERED_ROUTER_SMALL_MODEL",
        "TIERED_ROUTER_LARGE_MODEL",
        "TIERED_ROUTER_TOURNAMENT_MODEL",
    }
)

_SMALL = "claude-haiku-3.5"
_LARGE = "claude-sonnet-3.5"


@pytest.fixture(autouse=True)
def isolated(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Sandbox env/config, fresh store + switch counter + pending attrs."""
    for name in list(os.environ):
        if name.startswith("ORYA_") or name in _MANAGED_ENV_VARS:
            monkeypatch.delenv(name, raising=False)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ORYA_CONFIG_PATH", str(tmp_path / "config.yaml"))
    clear_settings_cache()
    set_cost_store(None)
    reset_switch_stats()
    take_pending_span_attributes()
    yield
    set_cost_store(None)
    reset_switch_stats()
    take_pending_span_attributes()
    clear_settings_cache()


def _write_config(tmp_path: Path, text: str) -> None:
    (tmp_path / "config.yaml").write_text(text, encoding="utf-8")


async def _store_at(ratio: float) -> MemoryCostStore:
    """A store whose spend/limit ratio is ``ratio`` (limit = $50)."""
    store = MemoryCostStore()
    await store.set_limit("session:s1", 50.0)
    await store.add_spend("session:s1", 50.0 * ratio)
    return store


# --- tier_models() config precedence -------------------------------------------


def test_tier_models_defaults() -> None:
    assert tier_models() == {
        "small": [_SMALL],
        "large": [_LARGE],
        "tournament": [_LARGE],
    }


def test_tier_models_reads_yaml_section(tmp_path: Path) -> None:
    _write_config(
        tmp_path,
        "tiered_router:\n"
        "  models:\n"
        '    small: ["glm-4-flash", "claude-haiku-3.5"]\n'
        '    large: ["claude-opus-4"]\n'
        '    tournament: ["claude-sonnet-3.5", "deepseek-chat"]\n',
    )
    assert tier_models() == {
        "small": ["glm-4-flash", "claude-haiku-3.5"],
        "large": ["claude-opus-4"],
        "tournament": ["claude-sonnet-3.5", "deepseek-chat"],
    }


def test_tier_models_env_wins_over_yaml(tmp_path: Path) -> None:
    _write_config(
        tmp_path,
        'tiered_router:\n  models:\n    small: ["glm-4-flash"]\n',
    )
    os.environ["ORYA_TIERED_ROUTER_SMALL_MODEL"] = "glm-4-plus"
    clear_settings_cache()
    try:
        models = tier_models()
    finally:
        del os.environ["ORYA_TIERED_ROUTER_SMALL_MODEL"]
        clear_settings_cache()
    assert models["small"] == ["glm-4-plus"]
    assert models["large"] == [_LARGE]  # untouched tier keeps the default


def test_tier_models_ignores_malformed_yaml(tmp_path: Path) -> None:
    _write_config(
        tmp_path,
        "tiered_router:\n"
        "  models:\n"
        '    small: "not-a-list"\n'
        "    large: []\n"
        "    tournament: [42, null]\n",
    )
    assert tier_models() == {
        "small": [_SMALL],
        "large": [_LARGE],
        "tournament": [_LARGE],
    }


def test_tier_models_aliases_exist_in_models_yaml() -> None:
    """No fake aliases (the spec sample used haiku-3.5/qwen-3b): every
    configured model must resolve through the models.yaml registry."""
    for tier, aliases in tier_models().items():
        for alias in aliases:
            spec = resolve_model(None, alias)
            assert spec.model_id, f"{tier}: alias {alias!r} did not resolve"


# --- normalize_tier -------------------------------------------------------------


def test_normalize_tier_fail_safe() -> None:
    assert normalize_tier(None) == "large"
    assert normalize_tier("") == "large"
    assert normalize_tier("small") == "small"
    assert normalize_tier("  LARGE ") == "large"
    assert normalize_tier("tournament") == "large"  # PROD-only (A-18 stub)
    assert normalize_tier("bogus") == "large"


# --- TieredModelRouter.select ---------------------------------------------------


async def test_select_small_returns_small_model() -> None:
    router = TieredModelRouter(models=tier_models())
    selection = await router.select("small", "session:s1")
    assert selection.model == _SMALL
    assert selection.tier == "small"
    assert selection.degraded is False
    assert selection.blocked is False
    assert selection.ratio == 0.0


async def test_select_large_returns_large_model() -> None:
    router = TieredModelRouter(models=tier_models())
    selection = await router.select("large", "session:s1")
    assert selection.model == _LARGE
    assert selection.tier == "large"
    assert selection.degraded is False


async def test_select_none_defaults_to_large() -> None:
    router = TieredModelRouter(models=tier_models())
    selection = await router.select(None, "session:s1")
    assert selection.model == _LARGE
    assert selection.tier == "large"


async def test_select_tournament_degrades_to_large_without_degraded() -> None:
    """ALPHA: tournament → large stub, ``degraded`` stays budget-only."""
    router = TieredModelRouter(models=tier_models())
    selection = await router.select("tournament", "session:s1")
    assert selection.model == _LARGE
    assert selection.tier == "large"
    assert selection.degraded is False
    assert selection.blocked is False


async def test_budget_below_warn_keeps_tier_independent_of_budget() -> None:
    """The A-18 point: ratio 0.8 (v6 would degrade) still runs tier=large."""
    store = await _store_at(0.8)
    router = TieredModelRouter(CostAwareRouter(_LARGE, _SMALL, store=store))
    selection = await router.select("large", "session:s1")
    assert selection.model == _LARGE
    assert selection.tier == "large"
    assert selection.degraded is False
    assert get_switch_stats() == {}


async def test_budget_at_warn_lowers_tier_to_small() -> None:
    store = await _store_at(0.9)
    router = TieredModelRouter(
        CostAwareRouter(_LARGE, _SMALL, store=store), models=tier_models()
    )
    selection = await router.select("large", "session:s1")
    assert selection.tier == "small"
    assert selection.model == _SMALL
    assert selection.degraded is True
    assert selection.warning is True
    assert selection.blocked is False
    assert selection.ratio == pytest.approx(0.9)
    assert get_switch_stats() == {(_LARGE, _SMALL): 1}


async def test_budget_full_blocks_the_turn() -> None:
    store = await _store_at(1.0)
    router = TieredModelRouter(
        CostAwareRouter(_LARGE, _SMALL, store=store), models=tier_models()
    )
    selection = await router.select("large", "session:s1")
    assert selection.blocked is True
    assert selection.degraded is True
    assert selection.warning is True
    assert selection.tier == "small"


async def test_budget_low_does_not_raise_a_small_tier() -> None:
    """Cost-aware fallback only downgrades: tier=small stays small."""
    router = TieredModelRouter(models=tier_models())
    selection = await router.select("small", "session:s1")
    assert selection.tier == "small"
    assert selection.model == _SMALL
    assert selection.degraded is False


# --- span attributes (A-17 pending seam) ----------------------------------------


async def test_select_stages_tier_span_attrs() -> None:
    router = TieredModelRouter(models=tier_models())
    await router.select("small", "session:s1")
    pending = take_pending_span_attributes()
    assert pending == {
        "agent.execute.tier": "small",
        "agent.execute.degraded": "false",
    }


async def test_select_stages_tier_and_over_budget_on_warning() -> None:
    store = await _store_at(0.95)
    router = TieredModelRouter(
        CostAwareRouter(_LARGE, _SMALL, store=store), models=tier_models()
    )
    await router.select("large", "session:s1")
    pending = take_pending_span_attributes()
    assert pending == {
        "agent.execute.tier": "small",
        "agent.execute.degraded": "true",
        "cost.over_budget": "true",
    }


async def test_select_stages_nothing_when_obs_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AGENT_OBS_ENABLED", "0")
    clear_settings_cache()
    router = TieredModelRouter(models=tier_models())
    await router.select("small", "session:s1")
    assert take_pending_span_attributes() == {}


def test_as_dict_carries_tier_only_when_set() -> None:
    assert "tier" in ModelSelection(model=_SMALL, tier="small").as_dict()
    payload = ModelSelection(model=_LARGE).as_dict()
    assert "tier" not in payload  # v6 shape untouched (A-13 test locks it)


# --- resolve_turn_model tier seam -----------------------------------------------


async def test_resolve_tier_none_is_the_v6_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """tier=None keeps the v6 rules: pass-through when the kill-switch is
    off, 0.7-degrade when it is on — even at ratio 0.8."""
    selection = await resolve_turn_model("session:s1", "claude-opus-4", None)
    assert selection.model == "claude-opus-4"  # pass-through, no tier
    assert selection.tier == ""

    monkeypatch.setenv("ORYA_COST_ROUTER_ENABLED", "true")
    clear_settings_cache()
    store = await _store_at(0.8)
    set_cost_store(store)
    selection = await resolve_turn_model("session:s1", None, None)
    assert selection.model == _SMALL  # v6 degrades at 0.7, not 0.9
    assert selection.degraded is True
    assert selection.tier == ""


async def test_resolve_tier_small_selects_small_at_zero_budget() -> None:
    selection = await resolve_turn_model(
        "session:s1", "claude-opus-4", None, tier="small"
    )
    assert selection.model == _SMALL
    assert selection.tier == "small"
    assert selection.degraded is False
    # the tier wins over the explicit per-turn model (BETA planner contract)
    assert selection.model != "claude-opus-4"


async def test_resolve_tier_keeps_429_contract_at_full_budget() -> None:
    store = await _store_at(1.0)
    set_cost_store(store)
    selection = await resolve_turn_model("session:s1", None, None, tier="large")
    assert selection.blocked is True  # routes raise HTTP 429 on this


async def test_resolve_tier_none_with_router_on_still_blocks() -> None:
    store = await _store_at(1.0)
    set_cost_store(store)
    # kill-switch stays off: v6 path without the router never blocks …
    selection = await resolve_turn_model("session:s1", None, None)
    assert selection.blocked is False
    # … but the tiered seam honors the same 429 contract.
    selection = await resolve_turn_model("session:s1", None, None, tier="large")
    assert selection.blocked is True
