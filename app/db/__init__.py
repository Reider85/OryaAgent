"""Database access (M-03): asyncpg connection pool + SQL migrations.

Usage::

    from app.db import apply_migrations, close_pool, get_asyncpg_pool

    pool = await get_asyncpg_pool()
    await apply_migrations(pool)

The pool is a process-wide lazy singleton bound to the running event loop
(asyncpg pools cannot be shared across loops). First use reads
``settings.database_url`` / pool sizes from :mod:`app.core.config`.
"""

from __future__ import annotations

import asyncio
from typing import Any

import asyncpg

from app.core.config import get_settings

__all__ = [
    "apply_migrations",
    "close_pool",
    "get_asyncpg_pool",
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
        # Pool was created on a different (likely closed) loop — replace it.
        await _pool.close()
    _pool = await asyncpg.create_pool(
        dsn=settings.database_url,
        min_size=settings.database_pool_size,
        max_size=settings.database_pool_size + settings.database_max_overflow,
    )
    _pool_loop = loop
    return _pool


async def close_pool() -> None:
    """Close the shared pool and drop the singleton (safe to call twice)."""
    global _pool, _pool_loop
    if _pool is not None:
        await _pool.close()
    _pool = None
    _pool_loop = None
