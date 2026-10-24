"""Post-write cache invalidation hook (M-21).

BACKLOG5 M-21 forbids stale cache entries after ``write``/``edit``:
the tools themselves are never cached, but they must drop every
tool-result cached for the path they just changed. Correctness is
already guaranteed by the mtime inside ``build_cache_key()`` - this
hook deletes the stale entries eagerly instead of letting them linger
until TTL (the Redis idx set makes the lookup O(1)).

Failures degrade to a warning: a broken cache must never fail a write.
"""

from __future__ import annotations

import logging

from app.core.cache import get_cache

logger = logging.getLogger(__name__)


async def invalidate_cache_for_path(path: str) -> None:
    """Drop all cached tool results registered for ``path`` (M-21).

    ``path`` must be the resolved absolute path the tools pass to
    ``cache.set(..., path=...)`` (``str(resolved)``). Backends without
    an ``invalidate()`` method are skipped.
    """
    invalidate = getattr(get_cache(), "invalidate", None)
    if not callable(invalidate):
        return
    try:
        await invalidate(path)
    except Exception as exc:  # noqa: BLE001 - invalidation must not fail writes
        logger.warning("cache invalidation failed for %s (%s)", path, exc)
