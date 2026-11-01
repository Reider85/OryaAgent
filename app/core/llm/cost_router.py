"""Cost-aware model router (A-13, A-17): budget-based degrade between turns.

Wraps the ``get_llm`` seam with a per-identity daily budget check
(PROMPT_ALPHA A-13, BACKLOG5 §A-13, ARCHITECT5 §6.1): spend is recorded
by ``app.core.cost_tracker`` after every LLM call; before each turn the
route asks :func:`resolve_turn_model` which alias the graph should be
built with.

A-17: when ``ratio >= 0.90`` (warning or blocked), ``cost.over_budget="true"`` is
staged for the ``agent.loop`` span (consumed by ``_agent_loop_span`` if
``agent_obs_enabled``).

Thresholds on ``budget_ratio = today's spend / daily limit``:

* ``< 0.70`` — primary model, not degraded;
* ``0.70 <= ratio < 0.90`` — fallback model, ``degraded``;
* ``0.90 <= ratio < 1.00` — fallback model, ``degraded`` + ``warning``;
* ``>= 1.00`` — ``blocked`` (the route answers 429).

Switching happens **only between turns**: the sessions routes rebuild
the graph per request, so the selection is applied at graph-assembly
time and never inside a running turn. When the router is enabled the
budget always wins over an explicit per-turn model request — the
``ORYA_COST_ROUTER_ENABLED`` kill-switch is the only escape hatch.

Every actual switch increments the process-local
``orya_cost_aware_switch_total{from_model,to_model}`` counter rendered
by ``/metrics``.
"""

from __future__ import annotations

import logging
from collections import Counter

from app.core.config import get_settings
from app.core.observability.spans import set_pending_span_attributes
from dataclasses import dataclass
from typing import Any

from app.core.config import get_settings
from app.core.cost_tracker import get_cost_store

__all__ = [
    "BLOCK_RATIO",
    "DEGRADE_RATIO",
    "WARN_RATIO",
    "CostAwareRouter",
    "ModelSelection",
    "get_switch_stats",
    "resolve_turn_model",
    "reset_switch_stats",
]

logger = logging.getLogger(__name__)

#: budget_ratio at which the turn moves to the fallback model.
DEGRADE_RATIO = 0.7

#: budget_ratio at which the degrade additionally raises a warning.
WARN_RATIO = 0.9

#: budget_ratio at which the turn is refused (HTTP 429).
BLOCK_RATIO = 1.0

#: Process-local switch counter (mirrors the M-22 injection counter).
_switch_counts: Counter[tuple[str, str]] = Counter()


def get_switch_stats() -> dict[tuple[str, str], int]:
    """``{(from_model, to_model): count}`` for the /metrics renderer."""
    return dict(_switch_counts)


def reset_switch_stats() -> None:
    """Drop all switch counts (tests)."""
    _switch_counts.clear()


def _count_switch(from_model: str, to_model: str) -> None:
    _switch_counts[(from_model, to_model)] += 1


@dataclass(frozen=True)
class ModelSelection:
    """Outcome of one budget check for a turn (A-13).

    ``model`` is the models.yaml alias the graph should be built with
    (``None`` = pass-through to the ``get_llm`` default); ``blocked``
    means the budget is exhausted and the route must refuse with 429.
    """

    model: str | None = None
    degraded: bool = False
    warning: bool = False
    blocked: bool = False
    ratio: float = 0.0
    primary: str = ""
    fallback: str = ""

    def as_dict(self) -> dict[str, Any]:
        """Serializable payload for SSE frames / result dicts."""
        return {
            "degraded": self.degraded,
            "warning": self.warning,
            "blocked": self.blocked,
            "ratio": round(self.ratio, 4),
            "model": self.model,
            "primary": self.primary,
            "fallback": self.fallback,
        }


class CostAwareRouter:
    """Selects the turn's model alias by the identity's budget ratio.

    ``store`` is a cost backend (``add_spend``/``get_spend``/``get_limit``
    — see ``app.core.cost_tracker``); when omitted the process-wide
    store is looked up per call (tests inject fakes via
    ``set_cost_store``).
    """

    def __init__(
        self,
        primary_model: str,
        fallback_model: str,
        store: Any | None = None,
    ) -> None:
        self.primary = primary_model
        self.fallback = fallback_model
        self._store = store

    @property
    def store(self) -> Any:
        return self._store if self._store is not None else get_cost_store()

    async def get_budget_ratio(self, identity: str) -> float:
        """``today's spend / daily limit`` (inf when the limit is <= 0)."""
        spend = await self.store.get_spend(identity)
        limit = await self.store.get_limit(identity)
        if limit <= 0:
            return float("inf")
        return float(spend) / float(limit)

    async def get_model_for_user(
        self, identity: str, *, requested_model: str | None = None
    ) -> ModelSelection:
        """Pick this turn's model alias for ``identity`` (spec entry point).

        A-17: when ratio >= 0.90 (warning or blocked), stage
        ``cost.over_budget="true"`` for the ``agent.loop`` span.

        ``requested_model`` is the client's explicit per-turn choice (if
        any) — recorded as the switch's ``from_model`` when the budget
        forces a degrade; it never overrides the budget.
        """
        ratio = await self.get_budget_ratio(identity)
        from_model = requested_model or self.primary
        if ratio < DEGRADE_RATIO:
            return ModelSelection(
                model=self.primary,
                ratio=ratio,
                primary=self.primary,
                fallback=self.fallback,
            )
        _count_switch(from_model, self.fallback)
        if ratio < WARN_RATIO:
            return ModelSelection(
                model=self.fallback,
                degraded=True,
                ratio=ratio,
                primary=self.primary,
                fallback=self.fallback,
            )
        # A-17: cost.over_budget=true on warning or blocked (ratio >= 0.90)
        if get_settings().agent_obs_enabled and ratio >= WARN_RATIO:
            set_pending_span_attributes({"cost.over_budget": "true"})
        if ratio < BLOCK_RATIO:
            return ModelSelection(
                model=self.fallback,
                degraded=True,
                warning=True,
                ratio=ratio,
                primary=self.primary,
                fallback=self.fallback,
            )
        return ModelSelection(
            model=self.fallback,
            degraded=True,
            warning=True,
            blocked=True,
            ratio=ratio,
            primary=self.primary,
            fallback=self.fallback,
        )


async def resolve_turn_model(
    identity: str,
    requested_model: str | None = None,
    requested_provider: str | None = None,
) -> ModelSelection:
    """Resolve the model alias for one turn (the route's entry point).

    Kill-switch off → pass-through (``model`` echoes the request, zero
    behavior change). Enabled → budget check; the budget always wins
    over ``requested_model``. ``blocked`` selections must be refused
    with 429 before the graph is built. ``requested_provider`` is
    accepted for call-site symmetry and intentionally ignored: the
    degrade targets the fallback alias' own provider.
    """
    settings = get_settings()
    primary = requested_model or settings.llm_model
    if not settings.cost_router_enabled:
        return ModelSelection(
            model=requested_model,
            primary=primary,
            fallback=settings.cost_router_fallback_model,
        )
    router = CostAwareRouter(
        primary_model=primary,
        fallback_model=settings.cost_router_fallback_model,
    )
    selection = await router.get_model_for_user(
        identity, requested_model=requested_model
    )
    if selection.degraded:
        logger.warning(
            "cost budget degrade (identity=%s ratio=%.2f%% model=%s->%s%s)",
            identity,
            selection.ratio * 100,
            requested_model or settings.llm_model,
            selection.model,
            ", warning" if selection.warning else "",
        )
    return selection
