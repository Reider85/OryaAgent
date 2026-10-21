"""Tool-result cache seam (M-07 in-memory backend; M-21 adds Redis).

The agent re-reads the same files many times per session; caching the
rendered tool output saves latency and tokens (TRIZ #28 mechanics
substitution). This module defines the *seam*:

* ``CacheLike`` - the protocol both backends implement (``get``/``set``);
* ``MemoryCache`` - process-local dict with per-entry TTL and
  hit/miss counters (good enough for single-process MVP);
* ``get_cache()`` / ``set_cache()`` - runtime registration so M-21
  plugs the Redis ``CacheWrapper`` in without touching the tools;
* ``build_cache_key()`` - stable key = ``sha256(serialized(args) +
  mtime)`` per PROMPT_MVP M-21, so a file edit (mtime change)
  automatically invalidates stale entries.

Usage::

    from app.core.cache import build_cache_key, get_cache

    key = build_cache_key("read", {"path": "a.py"}, mtime_ns=123)
    cached = await get_cache().get(key)

Design constraints (see ``analytics/PROMPT_MVP.md`` 4 #6, 9):

* only ``str`` values are cached (tool outputs are text);
* side-effect tools (write/edit/bash) are never cached - the registry
  (M-12/M-21) decides what is cacheable, not the backend;
* no in-memory fallback will survive horizontal scaling - M-21
  replaces the default backend with Redis via ``set_cache()``.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from typing import Any, Protocol, runtime_checkable

logger = logging.getLogger(__name__)

#: Default TTL in seconds (PROMPT_MVP M-21: ``set(key, value, ttl=3600)``).
DEFAULT_TTL_SECONDS = 3600.0

#: Key prefix matching the M-21 naming scheme.
KEY_PREFIX = "orya:tool_cache"


@runtime_checkable
class CacheLike(Protocol):
    """Minimal cache contract used by tools (M-21 invariant #6)."""

    async def get(self, key: str) -> str | None:
        """Return the cached value or ``None`` on miss/expiry."""
        ...

    async def set(self, key: str, value: str, ttl: float | None = None) -> None:
        """Store ``value`` under ``key`` for ``ttl`` seconds."""
        ...


class MemoryCache:
    """Process-local TTL cache with hit/miss counters.

    Single-process only (MVP default). M-21 swaps this for a Redis
    wrapper through :func:`set_cache` - tools keep calling
    ``get_cache()`` and stay backend-agnostic.
    """

    def __init__(self, default_ttl: float = DEFAULT_TTL_SECONDS) -> None:
        self.default_ttl = default_ttl
        self.hits = 0
        self.misses = 0
        self._entries: dict[str, tuple[str, float | None]] = {}

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
        if value is None:
            self.misses += 1
            return None
        self.hits += 1
        return value

    async def set(self, key: str, value: str, ttl: float | None = None) -> None:
        effective = self.default_ttl if ttl is None else ttl
        expires_at = time.monotonic() + effective if effective > 0 else None
        self._entries[key] = (value, expires_at)

    def clear(self) -> None:
        """Drop all entries (tests / manual invalidation)."""
        self._entries.clear()
        self.hits = 0
        self.misses = 0


_cache: CacheLike = MemoryCache()


def get_cache() -> CacheLike:
    """Return the currently registered tool-result cache."""
    return _cache


def set_cache(cache: CacheLike | None) -> None:
    """Register the cache backend (M-21 Redis wrapper, tests).

    ``None`` restores a fresh :class:`MemoryCache`.
    """
    global _cache
    _cache = MemoryCache() if cache is None else cache
    logger.debug("Tool cache backend set to %s", type(_cache).__name__)


def build_cache_key(tool_name: str, args: dict[str, Any], mtime_ns: int) -> str:
    """Stable cache key for a tool call on a file with a known mtime.

    ``sha256(json.dumps(args, sort_keys=True) + mtime_ns)`` - per
    PROMPT_MVP M-21. The mtime component is the invalidation hook:
    any file change produces a new key (stale entries expire by TTL).
    """
    serialized = json.dumps(args, sort_keys=True, ensure_ascii=False, default=str)
    digest = hashlib.sha256(f"{serialized}|{mtime_ns}".encode()).hexdigest()
    return f"{KEY_PREFIX}:{tool_name}:{digest}"
