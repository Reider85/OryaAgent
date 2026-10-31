"""Tool-result cache seam (M-07) + Redis CacheWrapper (M-21).

The agent re-reads the same files many times per session; caching the
rendered tool output saves latency and tokens (TRIZ #28 mechanics
substitution). This module owns the seam and both backends:

* ``CacheLike`` - the contract tools code against (``get``/``set``);
* ``MemoryCache`` - process-local dict with per-entry TTL, path index
  and hit/miss counters (single-process dev/test default);
* ``CacheWrapper`` - the M-21 Redis backend (``redis.asyncio``): same
  contract, plus an eager per-path invalidation index and best-effort
  ``orya:cache_stats:{date}:{tool}`` counters (BACKLOG5);
* ``get_cache()`` / ``set_cache()`` - runtime registration; tools only
  ever call ``get_cache()`` and stay backend-agnostic;
* ``build_cache_key()`` - stable key = ``sha256(serialized(args) +
  mtime)`` per PROMPT_MVP M-21, so a file edit (mtime change)
  automatically invalidates stale entries;
* ``init_cache()`` / ``close_cache()`` - lifespan wiring: probe Redis
  per ``settings.cache_backend`` (``auto`` falls back to memory with a
  warning, mirroring the M-14 soft-fail philosophy); ``redis`` requires
  a reachable server, ``memory`` never touches it;
* ``get_cache_stats()`` - per-tool hits/misses/hit_rate for the
  ``/metrics`` and ``/tools/cache-stats`` endpoints.

Usage::

    from app.core.cache import build_cache_key, get_cache

    key = build_cache_key("read", {"path": "a.py"}, mtime_ns=123)
    cached = await get_cache().get(key)
    await get_cache().set(key, result, path="/abs/a.py")

Design constraints (see ``analytics/PROMPT_MVP.md`` 4 #6, 9):

* only ``str`` values are cached (tool outputs are text);
* side-effect tools (write/edit/bash) are never cached - the registry
  (M-12) decides what is cacheable, not the backend; write/edit call
  ``app.hooks.cache_invalidation.invalidate_cache_for_path`` instead;
* Redis errors never fail a tool call: ``CacheWrapper`` degrades to a
  cache miss / a skipped write with a warning log.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from collections import OrderedDict
from contextlib import suppress
from datetime import date
from typing import Any, Protocol, runtime_checkable

from langchain_core.messages import ToolMessage

logger = logging.getLogger(__name__)

#: Default TTL in seconds (BACKLOG5 M-21: 5 minutes, configurable via
#: ``ORYA_CACHE_TTL_SECONDS``).
DEFAULT_TTL_SECONDS = 300.0

#: Key prefix matching the M-21 naming scheme: ``orya:tool_cache:{tool}:{sha256}``.
KEY_PREFIX = "orya:tool_cache"

#: Per-path invalidation index: ``orya:tool_cache:idx:{path}`` -> SET of keys.
IDX_PREFIX = "orya:tool_cache:idx"

#: Daily Redis stats counters (BACKLOG5: ``orya:cache_stats:{date}:{tool}``).
STATS_PREFIX = "orya:cache_stats"

#: Retention for the daily Redis stats hashes.
STATS_TTL_SECONDS = 7 * 24 * 3600

#: Startup probe timeout for ``settings.cache_backend == "auto"|"redis"``.
REDIS_PROBE_TIMEOUT_S = 1.0


@runtime_checkable
class CacheLike(Protocol):
    """Minimal cache contract used by tools (M-21 invariant #6)."""

    async def get(self, key: str) -> str | None:
        """Return the cached value or ``None`` on miss/expiry."""
        ...

    async def set(
        self,
        key: str,
        value: str,
        ttl: float | None = None,
        *,
        path: str | None = None,
    ) -> None:
        """Store ``value`` under ``key`` for ``ttl`` seconds.

        ``path`` (absolute, normalized) registers the key in the
        per-path invalidation index used by M-21 write/edit hooks.
        """
        ...


def _tool_from_key(key: str) -> str:
    """Extract the tool name from ``orya:tool_cache:{tool}:{digest}``."""
    prefix = f"{KEY_PREFIX}:"
    if not key.startswith(prefix):
        return "unknown"
    rest = key[len(prefix) :]
    return rest.split(":", 1)[0] or "unknown"


def _idx_key(path: str) -> str:
    return f"{IDX_PREFIX}:{path}"


class _Stats:
    """Per-tool hit/miss counters shared by both backends."""

    def __init__(self) -> None:
        self.hits = 0
        self.misses = 0
        self.evictions = 0
        self._tools: dict[str, dict[str, int]] = {}

    def bump(self, tool: str, field: str) -> None:
        counts = self._tools.setdefault(tool, {"hits": 0, "misses": 0, "evictions": 0})
        counts[field] += 1
        if field == "hits":
            self.hits += 1
        elif field == "misses":
            self.misses += 1
        else:  # evictions
            self.evictions += 1

    def snapshot(self) -> dict[str, dict[str, int]]:
        return {tool: dict(counts) for tool, counts in self._tools.items()}

    def reset(self) -> None:
        self.hits = 0
        self.misses = 0
        self.evictions = 0
        self._tools.clear()


class MemoryCache:
    """Process-local TTL cache with hit/miss counters and LRU eviction.

    Single-process only (dev/test default). ``init_cache()`` swaps it
    for the Redis :class:`CacheWrapper` when the server is reachable -
    tools keep calling :func:`get_cache` and stay backend-agnostic.
    """

    def __init__(
        self, default_ttl: float = DEFAULT_TTL_SECONDS, max_entries: int = 1024
    ) -> None:
        self.default_ttl = default_ttl
        self.max_entries = max_entries
        self._stats = _Stats()
        self._entries: OrderedDict[str, tuple[str, float | None]] = OrderedDict()
        self._by_path: dict[str, set[str]] = {}

    @property
    def hits(self) -> int:
        """Total cache hits (kept for existing tests/smoke checks)."""
        return self._stats.hits

    @property
    def misses(self) -> int:
        """Total cache misses (kept for existing tests/smoke checks)."""
        return self._stats.misses

    @property
    def evictions(self) -> int:
        """Total cache evictions (A-07 LRU)."""
        return self._stats.evictions

    def _alive(self, key: str) -> str | None:
        entry = self._entries.get(key)
        if entry is None:
            return None
        value, expires_at = entry
        if expires_at is not None and time.monotonic() >= expires_at:
            del self._entries[key]
            return None
        return value

    async def get(self, key: str) -> str | None:
        value = self._alive(key)
        tool = _tool_from_key(key)
        if value is None:
            self._stats.bump(tool, "misses")
            return None
        # LRU: move to end on access
        if key in self._entries:
            self._entries.move_to_end(key)
        self._stats.bump(tool, "hits")
        return value

    async def set(
        self,
        key: str,
        value: str,
        ttl: float | None = None,
        *,
        path: str | None = None,
    ) -> None:
        effective = self.default_ttl if ttl is None else ttl
        expires_at = time.monotonic() + effective if effective > 0 else None
        self._entries[key] = (value, expires_at)
        if path:
            self._by_path.setdefault(path, set()).add(key)

        # LRU eviction: remove oldest if over capacity
        if self.max_entries > 0 and len(self._entries) > self.max_entries:
            oldest_key, _ = self._entries.popitem(last=False)
            # Remove from path index if present
            for _path_key, keys in self._by_path.items():
                if oldest_key in keys:
                    keys.remove(oldest_key)
                    # Remove empty path entries to keep index clean
                    if not keys:
                        del self._by_path[_path_key]
                    break
            self._stats.bump(_tool_from_key(oldest_key), "evictions")

    async def invalidate(self, path: str) -> None:
        """Drop every cached key registered for ``path`` (M-21 hook)."""
        for key in self._by_path.pop(path, set()):
            self._entries.pop(key, None)

    def stats(self) -> dict[str, dict[str, int]]:
        return self._stats.snapshot()

    def clear(self) -> None:
        """Drop all entries (tests / manual invalidation)."""
        self._entries.clear()
        self._by_path.clear()
        self._stats.reset()


class CacheWrapper:
    """Redis-backed tool-result cache (M-21 ``CacheWrapper``).

    Key scheme (PROMPT_MVP M-21 / ARCHITECT5 7.2)::

        orya:tool_cache:{tool}:{sha256(args + mtime)}  -> value (TTL)
        orya:tool_cache:idx:{path}                     -> SET of keys
        orya:cache_stats:{YYYY-MM-DD}:{tool}           -> hash hits/misses

    Correctness comes from the mtime inside the key (a changed file
    produces a new key); the idx set only frees stale entries eagerly
    when write/edit call ``invalidate()``. All Redis failures degrade
    to a miss / a skipped write with a warning - a broken cache must
    never break a tool call.
    """

    def __init__(self, redis: Any, ttl: float = DEFAULT_TTL_SECONDS) -> None:
        self.redis = redis
        self.ttl = ttl
        self._stats = _Stats()

    @property
    def hits(self) -> int:
        return self._stats.hits

    @property
    def misses(self) -> int:
        return self._stats.misses

    async def _mirror(self, tool: str, field: str) -> None:
        """Best-effort daily counter in Redis (BACKLOG5 constraint)."""
        key = f"{STATS_PREFIX}:{date.today().isoformat()}:{tool}"
        try:
            first = await self.redis.hincrby(key, field, 1)
            if first == 1:
                await self.redis.expire(key, STATS_TTL_SECONDS)
        except Exception as exc:  # noqa: BLE001 - stats must not break reads
            logger.debug("cache stats mirror failed (%s)", exc)

    async def get(self, key: str) -> str | None:
        tool = _tool_from_key(key)
        try:
            value = await self.redis.get(key)
        except Exception as exc:
            logger.warning("redis cache get failed (%s); treating as miss", exc)
            self._stats.bump(tool, "misses")
            return None
        if value is None:
            self._stats.bump(tool, "misses")
            await self._mirror(tool, "misses")
            return None
        if isinstance(value, bytes):
            value = value.decode("utf-8", errors="replace")
        self._stats.bump(tool, "hits")
        await self._mirror(tool, "hits")
        return value

    async def set(
        self,
        key: str,
        value: str,
        ttl: float | None = None,
        *,
        path: str | None = None,
    ) -> None:
        effective = self.ttl if ttl is None else ttl
        try:
            if effective and effective > 0:
                await self.redis.set(key, value, ex=max(1, int(effective)))
            else:
                await self.redis.set(key, value)
            if path:
                idx = _idx_key(path)
                await self.redis.sadd(idx, key)
                # Refresh the index TTL alongside the entries it tracks.
                await self.redis.expire(idx, max(1, int(effective or self.ttl)))
        except Exception as exc:
            logger.warning("redis cache set failed (%s); entry skipped", exc)

    async def invalidate(self, path: str) -> None:
        """Delete every cached key registered for ``path`` (M-21 hook)."""
        idx = _idx_key(path)
        try:
            keys = list(await self.redis.smembers(idx))
            if keys:
                await self.redis.delete(*keys)
            await self.redis.delete(idx)
        except Exception as exc:
            logger.warning("redis cache invalidate failed (%s)", exc)

    def stats(self) -> dict[str, dict[str, int]]:
        return self._stats.snapshot()

    async def ping(self) -> bool:
        """True when the Redis server answers."""
        try:
            return bool(await self.redis.ping())
        except Exception:
            return False

    async def close(self) -> None:
        with suppress(Exception):
            close = getattr(self.redis, "aclose", None) or getattr(
                self.redis, "close", None
            )
            if close is not None:
                await close()


_cache: CacheLike = MemoryCache()
_redis_client: Any | None = None
_initialized = False


def get_cache() -> CacheLike:
    """Return the currently registered tool-result cache."""
    return _cache


def set_cache(cache: CacheLike | None) -> None:
    """Register the cache backend (M-21 Redis wrapper, tests).

    ``None`` restores a fresh :class:`MemoryCache`. This is a manual
    override: ``init_cache()`` (idempotent per process) will not
    replace a backend until :func:`close_cache` resets it.
    """
    global _cache
    _cache = MemoryCache() if cache is None else cache
    logger.debug("Tool cache backend set to %s", type(_cache).__name__)


async def init_cache(*, force: bool = False) -> None:
    """Probe Redis and register the backend per ``settings.cache_backend``.

    Idempotent (Chainlit ``on_chat_start`` and the FastAPI lifespan both
    call it). ``auto`` falls back to :class:`MemoryCache` with a warning
    when Redis is unreachable; ``redis`` re-raises (fail-fast); ``memory``
    never touches the network.
    """
    global _redis_client, _initialized
    if _initialized and not force:
        return
    from app.core.config import get_settings

    settings = get_settings()
    ttl = settings.cache_ttl_seconds
    max_entries = settings.cache_max_entries
    backend = settings.cache_backend
    if backend == "memory":
        set_cache(MemoryCache(default_ttl=ttl, max_entries=max_entries))
        _initialized = True
        logger.info(
            "Tool cache backend: MemoryCache (TTL %.0fs, max_entries=%s)",
            ttl,
            max_entries if max_entries > 0 else "unlimited",
        )
        return

    from redis.asyncio import Redis

    client = Redis.from_url(
        settings.redis_url,
        decode_responses=True,
        max_connections=settings.redis_pool_max_connections,
        socket_connect_timeout=settings.redis_socket_timeout_seconds,
        socket_timeout=settings.redis_socket_timeout_seconds,
        health_check_interval=30,
    )
    try:
        await asyncio.wait_for(client.ping(), timeout=REDIS_PROBE_TIMEOUT_S)
    except Exception as exc:
        with suppress(Exception):
            await client.aclose()
        if backend == "redis":
            raise
        logger.warning(
            "Redis unavailable (%s); tool cache falling back to MemoryCache", exc
        )
        set_cache(MemoryCache(default_ttl=ttl, max_entries=max_entries))
        _initialized = True
        return
    _redis_client = client
    set_cache(CacheWrapper(client, ttl=ttl))
    _initialized = True
    logger.info(
        "Tool cache backend: CacheWrapper/Redis at %s (TTL %.0fs, max_connections=%d, socket_timeout=%.1fs)",
        settings.redis_url,
        ttl,
        settings.redis_pool_max_connections,
        settings.redis_socket_timeout_seconds,
    )


async def close_cache() -> None:
    """Close the Redis client (if any) and restore a fresh MemoryCache.

    Also resets the ``init_cache()`` idempotence flag so the next
    ``init_cache()`` call probes again (test teardown / shutdown).
    """
    global _redis_client, _initialized
    if _redis_client is not None:
        client, _redis_client = _redis_client, None
        with suppress(Exception):
            await client.aclose()
    set_cache(None)
    _initialized = False


def get_cache_stats() -> dict[str, Any]:
    """Aggregate stats for the metrics endpoints (M-21).

    Returns ``{backend, ttl_seconds, max_entries, evictions, tools: {tool: {hits, misses,
    hit_rate}}}``. Counters are process-local for both backends (the
    Redis mirror keys are for cross-process tooling; A-15 formalizes
    Prometheus/Grafana + daily aggregation).
    """
    cache = get_cache()
    stats_fn = getattr(cache, "stats", None)
    raw = stats_fn() if callable(stats_fn) else {}
    tools: dict[str, dict[str, float]] = {}
    for tool, counts in raw.items():
        hits = int(counts.get("hits", 0))
        misses = int(counts.get("misses", 0))
        total = hits + misses
        tools[tool] = {
            "hits": hits,
            "misses": misses,
            "hit_rate": round(hits / total, 4) if total else 0.0,
        }
    ttl = getattr(cache, "default_ttl", None)
    if ttl is None:
        ttl = getattr(cache, "ttl", None)
    max_entries = getattr(cache, "max_entries", None)
    evictions = getattr(cache, "_stats.evictions", 0) if hasattr(cache, "_stats") else 0
    return {
        "backend": type(cache).__name__,
        "ttl_seconds": ttl,
        "max_entries": max_entries,
        "evictions": evictions,
        "tools": tools,
    }


def build_cache_key(tool_name: str, args: dict[str, Any], mtime_ns: int) -> str:
    """Stable cache key for a tool call on a file with a known mtime.

    ``sha256(json.dumps(args, sort_keys=True) + mtime_ns)`` - per
    PROMPT_MVP M-21. The mtime component is the invalidation hook:
    any file change produces a new key (stale entries are deleted
    eagerly by write/edit hooks and expire by TTL as a backstop).
    """
    serialized = json.dumps(args, sort_keys=True, ensure_ascii=False, default=str)
    digest = hashlib.sha256(f"{serialized}|{mtime_ns}".encode()).hexdigest()
    return f"{KEY_PREFIX}:{tool_name}:{digest}"


def from_cache_result(
    content: str, *, name: str, tool_call_id: str | None
) -> ToolMessage | str:
    """Shape a cache hit for the caller (BACKLOG5 M-21 AC).

    Through the graph's ToolNode a hit becomes a ``ToolMessage`` bound
    to ``tool_call_id`` with ``metadata={"from_cache": True}``. Without
    a call id (direct ``ainvoke()``) the payload stays the plain
    ``str`` - byte-identical to a fresh render, so existing direct
    invocation tests are unaffected.
    """
    if not tool_call_id:
        return content
    return ToolMessage(
        content=content,
        tool_call_id=tool_call_id,
        name=name,
        metadata={"from_cache": True},
    )
