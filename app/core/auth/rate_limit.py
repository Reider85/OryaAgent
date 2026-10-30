"""Rate-limiter seam (A-01): fixed-window RPM counters, Redis or in-memory.

Backs ``RateLimitMiddleware`` (``app/api/middleware.py``): every identity
(``user:{jwt sub}`` or ``user:{client ip}`` when auth is off) gets
``settings.rate_limit_rpm`` requests per calendar minute; the ``/learn``
endpoints add a tighter ``settings.rate_limit_learn_rpm`` bucket on top.

Two backends over one ``hit(key, limit) -> RateDecision`` contract:

* :class:`RedisRateLimiter` — ``INCR`` + ``EXPIRE`` on
  ``orya:rate:{key}:{window}`` (shared across workers; matches the M-21
  Redis-first philosophy).
* :class:`MemoryRateLimiter` — process-local dict; the degraded fallback
  when Redis is unreachable (``ORYA_RATE_LIMIT_BACKEND=auto``) and the
  no-infra backend for unit tests.

Redis mid-flight errors fail open (request allowed, warning logged) — the
same soft-fail stance the M-21 ``CacheWrapper`` takes; startup probe
(``init_rate_limiter``) follows ``ORYA_RATE_LIMIT_BACKEND``
(auto→memory, redis→fail-fast).

Settings are read through ``get_settings()`` inside each call — never bind
an instance at import time (tests sandbox the env and call
``clear_settings_cache()``).
"""

from __future__ import annotations

import asyncio
import logging
import time
from contextlib import suppress
from dataclasses import dataclass
from typing import Any

from app.core.config import get_settings

__all__ = [
    "MemoryRateLimiter",
    "RateDecision",
    "RedisRateLimiter",
    "close_rate_limiter",
    "get_rate_limiter",
    "init_rate_limiter",
    "set_rate_limiter",
]

logger = logging.getLogger(__name__)

#: Fixed-window length — the spec's unit is requests per minute.
WINDOW_SECONDS = 60

#: Redis TTL for a window key (2x window: survives clock jitter, self-cleans).
REDIS_KEY_TTL_SECONDS = 2 * WINDOW_SECONDS

#: Prefix for all limiter keys (ops greppability, like ``orya:cache_stats:``).
KEY_PREFIX = "orya:rate"

#: Startup probe timeout (mirrors the M-21 cache probe).
REDIS_PROBE_TIMEOUT_S = 2.0

#: In-memory backend prunes stale windows once the dict grows past this.
_MEMORY_PRUNE_THRESHOLD = 4096


@dataclass(frozen=True)
class RateDecision:
    """Outcome of one bucket hit.

    ``retry_after`` is seconds until the fixed window resets (0 when
    allowed) — the value the middleware puts into the 429 response.
    """

    allowed: bool
    limit: int
    remaining: int
    retry_after: int


def _window_id(now: float | None = None) -> int:
    """Calendar-minute index the counter lives in."""
    moment = time.time() if now is None else now
    return int(moment // WINDOW_SECONDS)


def _retry_after(now: float | None = None) -> int:
    """Seconds until the current window ends (>= 1)."""
    moment = time.time() if now is None else now
    return max(1, WINDOW_SECONDS - int(moment % WINDOW_SECONDS))


def _decision(count: int, limit: int, now: float | None = None) -> RateDecision:
    allowed = count <= limit
    return RateDecision(
        allowed=allowed,
        limit=limit,
        remaining=max(0, limit - count),
        retry_after=0 if allowed else _retry_after(now),
    )


class MemoryRateLimiter:
    """Process-local fixed-window counters (degraded fallback, tests)."""

    def __init__(self) -> None:
        self._buckets: dict[str, tuple[int, int]] = {}
        self._lock = asyncio.Lock()

    async def hit(self, key: str, limit: int) -> RateDecision:
        """Consume one slot of ``key``'s current window."""
        window = _window_id()
        async with self._lock:
            stored = self._buckets.get(key)
            count = 1 if stored is None or stored[0] != window else stored[1] + 1
            self._buckets[key] = (window, count)
            if len(self._buckets) > _MEMORY_PRUNE_THRESHOLD:
                for stale in [k for k, (w, _) in self._buckets.items() if w != window]:
                    self._buckets.pop(stale, None)
        return _decision(count, limit)


class RedisRateLimiter:
    """Redis fixed-window counters shared across workers (A-01 prod backend)."""

    def __init__(self, redis: Any) -> None:
        self.redis = redis

    async def hit(self, key: str, limit: int) -> RateDecision:
        """INCR the window key; first touch stamps the TTL."""
        window = _window_id()
        redis_key = f"{KEY_PREFIX}:{key}:{window}"
        try:
            count = int(await self.redis.incr(redis_key))
            if count == 1:
                await self.redis.expire(redis_key, REDIS_KEY_TTL_SECONDS)
        except Exception as exc:  # noqa: BLE001 - availability over strictness
            logger.warning("redis rate-limit hit failed (%s); allowing request", exc)
            return RateDecision(
                allowed=True, limit=limit, remaining=max(0, limit - 1), retry_after=0
            )
        return _decision(count, limit)


_limiter: Any = MemoryRateLimiter()
_redis_client: Any | None = None
_initialized = False


def get_rate_limiter() -> Any:
    """Return the currently registered limiter (``hit(key, limit)``)."""
    return _limiter


def set_rate_limiter(limiter: Any | None) -> None:
    """Register the limiter backend (``RedisRateLimiter``, tests).

    ``None`` restores a fresh :class:`MemoryRateLimiter`. Manual override
    survives ``init_rate_limiter()`` until :func:`close_rate_limiter`
    resets it (same contract as ``set_cache``).
    """
    global _limiter
    _limiter = MemoryRateLimiter() if limiter is None else limiter
    logger.debug("Rate limiter backend set to %s", type(_limiter).__name__)


async def init_rate_limiter(*, force: bool = False) -> None:
    """Probe Redis per ``settings.rate_limit_backend`` and register it (A-01).

    Idempotent (the FastAPI lifespan calls it once; tests use ``force``).
    Skips the probe entirely while the ``ORYA_RATE_LIMIT_ENABLED``
    kill-switch is off — the default startup path stays zero-cost. ``auto``
    falls back to :class:`MemoryRateLimiter` with a warning when Redis is
    unreachable; ``redis`` re-raises (fail-fast); ``memory`` never touches
    the network.
    """
    global _redis_client, _initialized
    if _initialized and not force:
        return
    settings = get_settings()
    if not settings.rate_limit_enabled:
        set_rate_limiter(MemoryRateLimiter())
        _initialized = True
        logger.debug("Rate limiter: disabled (ORYA_RATE_LIMIT_ENABLED=false)")
        return
    backend = settings.rate_limit_backend
    if backend == "memory":
        set_rate_limiter(MemoryRateLimiter())
        _initialized = True
        logger.info("Rate limiter backend: MemoryRateLimiter")
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
        logger.warning(
            "Redis unavailable (%s); rate limiter falling back to memory", exc
        )
        set_rate_limiter(MemoryRateLimiter())
        _initialized = True
        return
    _redis_client = client
    set_rate_limiter(RedisRateLimiter(client))
    _initialized = True
    logger.info("Rate limiter backend: RedisRateLimiter at %s", settings.redis_url)


async def close_rate_limiter() -> None:
    """Close the Redis client (if any) and restore a fresh memory limiter."""
    global _redis_client, _initialized
    if _redis_client is not None:
        client, _redis_client = _redis_client, None
        with suppress(Exception):
            await client.aclose()
    set_rate_limiter(None)
    _initialized = False
