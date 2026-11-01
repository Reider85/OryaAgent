"""Tiered model router (A-18): tier-based selection + cost-aware fallback.

Extends the v6 ``CostAwareRouter`` (A-13) by composition: where A-13 picks
the model purely from the identity's budget ratio (cost-control), this
router picks it from a *tier* the caller asserts about the turn
(``small`` | ``large`` | ``tournament``) and uses the budget only as a
fallback layer that can lower — never raise — the tier
(``budget_ratio >= WARN_RATIO`` → ``small``, ARCHITECT7 §3 #30).

In ALPHA there is no planner yet, so no call site emits a tier: the route
passes ``tier=None`` through the untouched v6 path of
:func:`app.core.llm.cost_router.resolve_turn_model`. The BETA planner
(B-25) will start passing ``tier=...`` and this module takes over.

Decisions (plan `.opencode/plans/A-18-tiered-model-router.md`):

* ``tier=tournament`` is PROD-only (TournamentExecutor) — ALPHA degrades
  it to ``large`` with a warning, ``degraded`` stays ``false`` (it remains
  the *budget* signal, so the SSE ``budget`` frame never lies about the
  ratio); unknown tiers fail safe to ``large`` too.
* ``degraded``/``warning``/``blocked`` mirror A-13's thresholds: degrade
  at 90%, refuse with 429 at 100% — the route's ``_resolve_turn_model_or_raise``
  keeps working unchanged.
* Span attributes ``agent.execute.tier`` / ``agent.execute.degraded``
  (plus A-17's ``cost.over_budget``) are staged **before** the model is
  returned and land on the ``agent.loop`` span via the A-17 pending-
  attribute seam; values are ``"true"``/``"false"`` strings like A-17's.
* Model names never live in this module: they come from
  ``tiered_router.models.{tier}`` in ``~/.orya/config.yaml``, from the
  ``ORYA_TIERED_ROUTER_*_MODEL`` env fields, or from the Settings
  defaults (real ``models.yaml`` aliases only).
"""

from __future__ import annotations

import logging
from typing import Any

from app.core.config import get_settings, tiered_router_block
from app.core.llm.cost_router import (
    BLOCK_RATIO,
    WARN_RATIO,
    CostAwareRouter,
    ModelSelection,
    _count_switch,
)
from app.core.observability.spans import set_pending_span_attributes

__all__ = [
    "TIERS",
    "TieredModelRouter",
    "normalize_tier",
    "tier_models",
]

logger = logging.getLogger(__name__)

#: Routable tiers (``tournament`` is accepted but degrades in ALPHA).
TIERS = ("small", "large", "tournament")


def tier_models() -> dict[str, list[str]]:
    """Tier → ordered ``models.yaml`` aliases (first entry = the model).

    Precedence per tier, matching the repo's env → config → defaults
    order: an explicitly set env/``.env`` value (``model_fields_set``) >
    the ``tiered_router.models.{tier}`` list in the user config > the
    Settings field default. Non-list / empty YAML entries are ignored.
    """
    settings = get_settings()
    yaml_models = tiered_router_block().get("models")
    if not isinstance(yaml_models, dict):
        yaml_models = {}
    out: dict[str, list[str]] = {}
    for tier in TIERS:
        field = f"tiered_router_{tier}_model"
        env_value = getattr(settings, field, "")
        if field in settings.model_fields_set and env_value:
            out[tier] = [env_value]
            continue
        yaml_list = yaml_models.get(tier)
        if (
            isinstance(yaml_list, list)
            and yaml_list
            and all(isinstance(item, str) and item for item in yaml_list)
        ):
            out[tier] = list(yaml_list)
            continue
        out[tier] = [env_value]
    return out


def normalize_tier(tier: str | None) -> str:
    """Map a requested tier onto an ALPHA-routable one (fail-safe).

    ``None``/empty → ``large`` (the ALPHA default: no planner yet);
    ``tournament`` → ``large`` (TournamentExecutor is PROD); anything
    else unknown → ``large`` with a warning rather than a crash.
    """
    if tier is None:
        return "large"
    wanted = tier.strip().lower()
    if wanted in ("small", "large"):
        return wanted
    if wanted == "tournament":
        logger.warning(
            "tier=tournament is PROD-only (A-18); degrading the turn to large"
        )
        return "large"
    logger.warning("unknown tier %r (A-18); falling back to large", tier)
    return "large"


class TieredModelRouter:
    """Tier-based model selection layered over the v6 ``CostAwareRouter``.

    ``cost_aware`` supplies the budget ratio (composition per ARCHITECT7
    §3 #30); when omitted one is built from the current tier defaults so
    ``select()`` works standalone. ``models`` overrides the configured
    tier lists (tests).
    """

    def __init__(
        self,
        cost_aware: CostAwareRouter | None = None,
        *,
        models: dict[str, list[str]] | None = None,
    ) -> None:
        self.cost_aware = cost_aware
        self._models = models

    @property
    def models(self) -> dict[str, list[str]]:
        return self._models if self._models is not None else tier_models()

    async def select(self, tier: str | None, identity: str) -> ModelSelection:
        """Pick this turn's model alias for ``tier`` over ``identity``'s budget.

        The tier decides the model; the budget can only lower the tier to
        ``small`` (``ratio >= WARN_RATIO``) and block the turn
        (``ratio >= BLOCK_RATIO`` → the route answers 429). Span
        attributes are staged before returning (A-17 pending seam).
        """
        models = self.models
        requested = normalize_tier(tier)
        cost_aware = self.cost_aware
        if cost_aware is None:
            cost_aware = CostAwareRouter(
                primary_model=models["large"][0],
                fallback_model=models["small"][0],
            )
        ratio = await cost_aware.get_budget_ratio(identity)

        selected = requested
        degraded = False
        warning = False
        blocked = False
        if ratio >= BLOCK_RATIO:
            selected, degraded, warning, blocked = "small", True, True, True
        elif ratio >= WARN_RATIO:
            selected, degraded, warning = "small", True, True

        model = models[selected][0]
        if degraded:
            _count_switch(models[requested][0], model)

        # A-18: emit span attributes BEFORE the model is returned.
        if get_settings().agent_obs_enabled:
            attributes: dict[str, Any] = {
                "agent.execute.tier": selected,
                "agent.execute.degraded": "true" if degraded else "false",
            }
            if ratio >= WARN_RATIO:
                attributes["cost.over_budget"] = "true"
            set_pending_span_attributes(attributes)

        if degraded:
            logger.warning(
                "tiered budget degrade (identity=%s ratio=%.2f%% tier=%s->%s model=%s)",
                identity,
                ratio * 100,
                requested,
                selected,
                model,
            )
        return ModelSelection(
            model=model,
            tier=selected,
            degraded=degraded,
            warning=warning,
            blocked=blocked,
            ratio=ratio,
            primary=models[requested][0],
            fallback=models["small"][0],
        )
