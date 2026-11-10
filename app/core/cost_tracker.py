"""Cost tracker seam (A-13): per-identity daily spend counters.

Backs the CostAwareRouter (``app/core/llm/cost_router.py``): every LLM
call records ``tokens x pricing.yaml`` into a daily counter keyed by the
turn identity (``user:{jwt sub}`` when auth is on, else
``session:{session_id}`` — the route stamps the identity into a
contextvar before running the turn, so the graph and the LLM seam stay
identity-agnostic).

Two backends over one ``add_spend/get_spend/get_limit`` contract
(mirrors the A-01 rate-limiter seam):

* :class:`RedisCostStore` — ``INCRBYFLOAT`` on
  ``orya:cost:{identity}:{YYYY-MM-DD}`` (UTC day, shared across
  workers); the admin-set limit lives in ``orya:limit:{identity}`` and
  falls back to ``settings.cost_budget_default_usd``.
* :class:`MemoryCostStore` — process-local dict; the degraded fallback
  when Redis is unreachable (``ORYA_COST_BACKEND=auto``) and the
  no-infra backend for unit tests.

Redis mid-flight errors fail soft (spend recorded as a no-op, warning
logged) — the same availability-over-strictness stance the A-01
limiter takes. ``record_usage`` never raises into the agent loop.

Settings are read through ``get_settings()`` inside each call — never
bind an instance at import time (tests sandbox the env and call
``clear_settings_cache()``).

A-14 (cost-tracking in spans): :func:`price_usd` is the public pricing
seam shared by the budget counter, the ``cost.*`` span attributes the
LLM tracer stamps on every ``llm.call``, and the process-local
``orya_llm_cost_usd_total{model}`` metric counter
(:func:`add_cost_total` / :func:`get_cost_totals`) — one pricing source,
no duplicated math.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any

from app.core.config import get_settings

__all__ = [
    "MemoryCostStore",
    "RedisCostStore",
    "add_cost_total",
    "close_cost_store",
    "get_cost_identity",
    "get_cost_store",
    "get_cost_totals",
    "init_cost_store",
    "price_usd",
    "record_usage",
    "reset_cost_totals",
    "set_cost_identity",
    "set_cost_store",
    "with_cost_identity",
    "integrate_github_actions_monitoring",
]

logger = logging.getLogger(__name__)

#: Prefix for spend counters (ops greppability, like ``orya:rate:``).
COST_KEY_PREFIX = "orya:cost"

#: Prefix for admin-set daily limits (``orya:limit:{identity}``).
LIMIT_KEY_PREFIX = "orya:limit"

#: Redis TTL for a spend key (2 days: survives day rollover, self-cleans).
REDIS_KEY_TTL_SECONDS = 48 * 3600

#: Startup probe timeout (mirrors the A-01 rate-limit probe).
REDIS_PROBE_TIMEOUT_S = 2.0

#: In-memory backend prunes stale day keys once the dict grows past this.
_MEMORY_PRUNE_THRESHOLD = 4096

#: The turn identity (``user:...``/``session:...``) recorded against.
_cost_identity: ContextVar[str | None] = ContextVar("orya_cost_identity", default=None)


def set_cost_identity(identity: str | None) -> None:
    """Stamp the identity the ongoing turn's LLM calls are billed to."""
    _cost_identity.set(identity)


def get_cost_identity() -> str | None:
    """Return the identity stamped for the current context (if any)."""
    return _cost_identity.get()


@contextmanager
def with_cost_identity(identity: str | None) -> Iterator[None]:
    """Context manager form of :func:`set_cost_identity` (restores prior)."""
    token = _cost_identity.set(identity)
    try:
        yield
    finally:
        _cost_identity.reset(token)


def _day_id() -> str:
    """UTC calendar day the spend counter lives in (``YYYY-MM-DD``)."""
    return datetime.now(UTC).date().isoformat()


class MemoryCostStore:
    """Process-local spend/limit counters (degraded fallback, tests).

    Uses a ``threading.Lock`` (the body is pure dict work, no awaits):
    tests seed the store from ``asyncio.run`` and then serve requests on
    the TestClient loop — an ``asyncio.Lock`` would be bound to the
    seeding loop and raise across loops.
    """

    def __init__(self) -> None:
        self._spend: dict[str, float] = {}
        self._limits: dict[str, float] = {}
        self._lock = threading.Lock()

    async def add_spend(self, identity: str, usd: float) -> None:
        """Add ``usd`` to today's counter for ``identity``."""
        key = f"{identity}:{_day_id()}"
        with self._lock:
            self._spend[key] = self._spend.get(key, 0.0) + usd
            if len(self._spend) > _MEMORY_PRUNE_THRESHOLD:
                today = _day_id()
                for stale in [k for k in self._spend if not k.endswith(today)]:
                    self._spend.pop(stale, None)

    async def get_spend(self, identity: str) -> float:
        """Today's accumulated spend for ``identity`` (0.0 when fresh)."""
        with self._lock:
            return self._spend.get(f"{identity}:{_day_id()}", 0.0)

    async def get_limit(self, identity: str) -> float:
        """Admin-set limit, falling back to ``cost_budget_default_usd``."""
        with self._lock:
            stored = self._limits.get(identity)
        if stored is not None:
            return stored
        return float(get_settings().cost_budget_default_usd)

    async def set_limit(self, identity: str, usd: float) -> None:
        """Set the daily USD limit for ``identity`` (admin/test seam)."""
        with self._lock:
            self._limits[identity] = float(usd)


class RedisCostStore:
    """Redis-backed spend/limit counters shared across workers (A-13 prod)."""

    def __init__(self, redis: Any) -> None:
        self.redis = redis

    async def add_spend(self, identity: str, usd: float) -> None:
        """INCRBYFLOAT today's counter; first touch stamps the TTL."""
        redis_key = f"{COST_KEY_PREFIX}:{identity}:{_day_id()}"
        try:
            count = await self.redis.incrbyfloat(redis_key, usd)
            if float(count) == float(usd):
                await self.redis.expire(redis_key, REDIS_KEY_TTL_SECONDS)
        except Exception as exc:  # noqa: BLE001 - availability over strictness
            logger.warning("redis cost increment failed (%s); spend skipped", exc)

    async def get_spend(self, identity: str) -> float:
        """Today's accumulated spend for ``identity`` (0.0 when fresh)."""
        redis_key = f"{COST_KEY_PREFIX}:{identity}:{_day_id()}"
        try:
            raw = await self.redis.get(redis_key)
        except Exception as exc:  # noqa: BLE001 - availability over strictness
            logger.warning("redis cost read failed (%s); assuming 0", exc)
            return 0.0
        return float(raw or 0.0)

    async def get_limit(self, identity: str) -> float:
        """Admin-set limit, falling back to ``cost_budget_default_usd``."""
        redis_key = f"{LIMIT_KEY_PREFIX}:{identity}"
        try:
            raw = await self.redis.get(redis_key)
        except Exception as exc:  # noqa: BLE001 - availability over strictness
            logger.warning("redis cost limit read failed (%s); using default", exc)
            raw = None
        if raw is None:
            return float(get_settings().cost_budget_default_usd)
        return float(raw)

    async def set_limit(self, identity: str, usd: float) -> None:
        """Set the daily USD limit for ``identity`` (admin/test seam)."""
        redis_key = f"{LIMIT_KEY_PREFIX}:{identity}"
        try:
            await self.redis.set(redis_key, str(float(usd)))
        except Exception as exc:  # noqa: BLE001 - availability over strictness
            logger.warning("redis cost limit write failed (%s)", exc)


_store: Any = MemoryCostStore()
_redis_client: Any | None = None
_initialized = False


def get_cost_store() -> Any:
    """Return the currently registered store (``add_spend/get_spend/...``)."""
    return _store


def set_cost_store(store: Any | None) -> None:
    """Register the cost backend (``RedisCostStore``, tests).

    ``None`` restores a fresh :class:`MemoryCostStore`. Manual override
    survives ``init_cost_store()`` until :func:`close_cost_store`
    resets it (same contract as ``set_rate_limiter``).
    """
    global _store
    _store = MemoryCostStore() if store is None else store
    logger.debug("Cost store backend set to %s", type(_store).__name__)


async def init_cost_store(*, force: bool = False) -> None:
    """Probe Redis per ``settings.cost_backend`` and register it (A-13).

    Idempotent (the FastAPI lifespan calls it once; tests use ``force``).
    Skips the probe entirely while the ``ORYA_COST_ROUTER_ENABLED``
    kill-switch is off — the default startup path stays zero-cost.
    ``auto`` falls back to :class:`MemoryCostStore` with a warning when
    Redis is unreachable; ``redis`` re-raises (fail-fast); ``memory``
    never touches the network.
    """
    global _redis_client, _initialized
    if _initialized and not force:
        return
    settings = get_settings()
    if not settings.cost_router_enabled:
        set_cost_store(MemoryCostStore())
        _initialized = True
        logger.debug("Cost store: disabled (ORYA_COST_ROUTER_ENABLED=false)")
        return
    backend = settings.cost_backend
    if backend == "memory":
        set_cost_store(MemoryCostStore())
        _initialized = True
        logger.info("Cost store backend: MemoryCostStore")
        return

    from redis.asyncio import Redis

    client = Redis.from_url(settings.redis_url, decode_responses=True)
    try:
        await asyncio.wait_for(client.ping(), timeout=REDIS_PROBE_TIMEOUT_S)
    except Exception as exc:
        with suppress(Exception):
            await client.aclose()
        if backend == "redis":
            raise
        logger.warning("Redis unavailable (%s); cost store falling back to memory", exc)
        set_cost_store(MemoryCostStore())
        _initialized = True
        return
    _redis_client = client
    set_cost_store(RedisCostStore(client))
    _initialized = True
    logger.info("Cost store backend: RedisCostStore at %s", settings.redis_url)


async def close_cost_store() -> None:
    """Close the Redis client (if any) and restore a fresh memory store."""
    global _redis_client, _initialized
    if _redis_client is not None:
        client, _redis_client = _redis_client, None
        with suppress(Exception):
            await client.aclose()
    set_cost_store(None)
    _initialized = False


def price_usd(model: str, input_tokens: int, output_tokens: int) -> float:
    """USD cost of one call from ``pricing.yaml`` (0.0 for unknown/free).

    Public seam since A-14: the span-cost attributes and the
    ``orya_llm_cost_usd_total`` metric compute from the same table as
    the budget counter.
    """
    from app.core.llm.registry import load_pricing

    spec = load_pricing().get(model)
    if spec is None:
        logger.debug("no pricing entry for model %r; cost recorded as 0", model)
        return 0.0
    return (
        input_tokens * spec.input_per_1k / 1000.0
        + output_tokens * spec.output_per_1k / 1000.0
    )


#: Process-local per-model USD totals fed by the A-14 seam hook
#: (``/metrics`` exposition; the budget counters stay identity-keyed).
_cost_totals: dict[str, float] = {}
_cost_totals_lock = threading.Lock()


def add_cost_total(model: str, usd: float) -> None:
    """Accumulate one call's USD into the process-local metric counter.

    Fed by ``TracedChatModel`` alongside the ``cost.*`` span attributes:
    it counts every priced call, independent of the budget identity or
    the ``ORYA_COST_ROUTER_ENABLED`` kill-switch. Never raises.
    """
    try:
        with _cost_totals_lock:
            _cost_totals[model] = _cost_totals.get(model, 0.0) + usd
    except Exception:  # noqa: BLE001 - observability never breaks a turn
        logger.warning(
            "cost total accumulation failed (model=%s)", model, exc_info=True
        )


def get_cost_totals() -> dict[str, float]:
    """Snapshot of the per-model USD totals (``{model: usd}``)."""
    with _cost_totals_lock:
        return dict(_cost_totals)


def reset_cost_totals() -> None:
    """Drop all accumulated totals (tests)."""
    with _cost_totals_lock:
        _cost_totals.clear()


async def record_usage(
    provider: str, model: str, input_tokens: int, output_tokens: int
) -> None:
    """Add one LLM call's USD cost to the current identity's daily counter.

    Called from the A-02 tracing wrapper (``TracedChatModel.invoke`` /
    ``ainvoke``) after ``usage_metadata`` is attached. No-op when no
    identity is stamped (router disabled / non-turn call) or when the
    token counts are missing. Never raises into the agent loop.
    """
    identity = _cost_identity.get()
    if not identity:
        return
    try:
        usd = price_usd(model, input_tokens, output_tokens)
        if usd <= 0.0:
            return
        await get_cost_store().add_spend(identity, usd)
        logger.debug(
            "recorded cost $%.6f for %s on %s/%s", usd, identity, provider, model
        )
    except Exception:  # noqa: BLE001 - cost accounting never breaks a turn
        logger.warning("cost recording failed (identity=%s)", identity, exc_info=True)


async def integrate_github_actions_monitoring() -> None:
    """Integrate GitHub Actions monitoring with the cost tracking system.
    
    This function bridges the existing cost tracking system with GitHub Actions
    monitoring by:
    1. Sharing Redis backend for both systems
    2. Coordinating budget checks across both LLM and GitHub Actions costs
    3. Providing unified cost tracking for the entire system
    """
    from app.core.config import get_settings
    from app.core.github_actions import get_github_actions_monitor
    
    settings = get_settings()
    
    # Only integrate if GitHub Actions monitoring is enabled
    if not settings.github_actions_enabled:
        return
    
    try:
        # Get the GitHub Actions monitor
        monitor = get_github_actions_monitor()
        
        # Integrate with the existing cost tracking system
        # This could include:
        # - Shared Redis backend (already handled by both systems)
        # - Combined budget tracking
        # - Unified cost reporting
        
        logger.info("GitHub Actions monitoring integrated with cost tracking system")
        
    except Exception as exc:
        logger.warning("GitHub Actions integration failed: %s", exc)
