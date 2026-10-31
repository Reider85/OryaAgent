"""Database access (M-03 → A-11): asyncpg connection pool + Alembic migrations.

Usage::

    from app.db import apply_migrations, close_pool, get_asyncpg_pool

    applied = await apply_migrations()  # alembic upgrade head, worker thread
    pool = await get_asyncpg_pool()

The pool is a process-wide lazy singleton bound to the running event loop
(asyncpg pools cannot be shared across loops). First use reads
``settings.database_url`` / pool sizes from :mod:`app.core.config`.
Migrations no longer use the pool — they run through Alembic's sync engine
(see :mod:`app.db.migrate`).
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import asyncpg

from app.core.config import get_settings

logger = logging.getLogger(__name__)

__all__ = [
    "apply_migrations",
    "close_pool",
    "get_asyncpg_pool",
    "get_pool_if_created",
    "load_migrations",
]

_pool: asyncpg.Pool | None = None
_pool_loop: asyncio.AbstractEventLoop | None = None


def __getattr__(name: str) -> Any:
    """Lazy re-export of migration helpers (PEP 562).

    Keeps ``app.db.migrate`` out of package import time so
    ``python -m app.db.migrate`` does not double-import the module.
    """
    if name in ("apply_migrations", "load_migrations"):
        from app.db import migrate

        return getattr(migrate, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


async def get_asyncpg_pool() -> asyncpg.Pool:
    """Return the shared asyncpg pool (created on first use)."""
    global _pool, _pool_loop
    settings = get_settings()
    loop = asyncio.get_running_loop()
    if _pool is not None and _pool_loop is loop:
        return _pool
    if _pool is not None:
        # The pool is bound to the loop that created it — awaiting close()
        # from another (usually dead) loop raises "attached to a different
        # loop". Drop the singleton instead; the old pool dies with its own
        # loop (per-function test loops hit this path).
        logger.debug("Replacing asyncpg pool created on a different event loop")
        _pool = None
    _pool = await asyncpg.create_pool(
        dsn=settings.database_url,
        min_size=settings.database_pool_size,
        max_size=settings.database_pool_size + settings.database_max_overflow,
    )
    _pool_loop = loop
    return _pool


def get_pool_if_created() -> asyncpg.Pool | None:
    """Return the shared pool when it already exists on this loop.

    Unlike :func:`get_asyncpg_pool` this never connects: callers that
    only *want* to write when the database is already in use (the M-22
    security-incident audit) use it as a non-blocking probe. Returns
    ``None`` outside a running event loop or when the pool was built on
    a different loop.
    """
    if _pool is None:
        return None
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return None
    return _pool if _pool_loop is loop else None


async def close_pool() -> None:
    """Close the shared asyncpg pool and drop the singleton (safe to call twice)."""
    global _pool, _pool_loop
    if _pool is not None and _pool_loop is asyncio.get_running_loop():
        await _pool.close()
    # Foreign-loop pools are dropped without close (cross-loop await raises).
    _pool = None
    _pool_loop = None
