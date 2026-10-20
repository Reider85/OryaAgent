"""LangGraph PostgresSaver checkpointer (M-03).

``AsyncPostgresSaver`` stores LangGraph state in dedicated ``checkpoints``
tables (plus ``checkpoint_blobs``, ``checkpoint_writes``,
``checkpoint_migrations``). Those tables are created and migrated by the
package itself via ``await checkpointer.setup()`` — they are intentionally
not part of ``app/db/schema.sql``.

Usage (M-04 graph wiring)::

    from app.db.checkpoints import get_checkpointer

    checkpointer = await get_checkpointer()   # calls setup() on first use
    graph = build_graph().compile(checkpointer=checkpointer)
"""

from __future__ import annotations

import asyncio
import logging

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg_pool import AsyncConnectionPool

from app.core.config import get_settings

logger = logging.getLogger(__name__)

_checkpointer: AsyncPostgresSaver | None = None
_pool: AsyncConnectionPool | None = None


def _require_compatible_loop() -> None:
    """psycopg async mode cannot run on Windows ProactorEventLoop.

    uvicorn uses SelectorEventLoop on Windows, so production is fine;
    raw ``asyncio.run`` (CLI, some test setups) needs an explicit loop
    factory on win32.
    """
    loop = asyncio.get_running_loop()
    proactor = getattr(asyncio, "ProactorEventLoop", None)
    if proactor is not None and isinstance(loop, proactor):
        raise RuntimeError(
            "psycopg (LangGraph PostgresSaver) cannot run on Windows "
            "ProactorEventLoop. Use uvicorn, or run with "
            "asyncio.run(..., loop_factory=lambda: "
            "asyncio.SelectorEventLoop(selectors.SelectSelector()))."
        )


async def get_checkpointer(*, setup: bool = True) -> AsyncPostgresSaver:
    """Return the shared AsyncPostgresSaver (created on first use).

    Uses its own psycopg connection pool pointed at the same
    ``settings.database_url`` (langgraph-checkpoint-postgres is psycopg-based,
    while application tables use asyncpg).
    """
    global _checkpointer, _pool
    if _checkpointer is not None:
        return _checkpointer
    _require_compatible_loop()
    settings = get_settings()
    _pool = AsyncConnectionPool(
        conninfo=settings.database_url,
        open=False,
        min_size=1,
        max_size=max(1, settings.database_pool_size),
        # Mirror AsyncPostgresSaver.from_conn_string(): setup() runs
        # CREATE INDEX CONCURRENTLY, which needs autocommit.
        kwargs={"autocommit": True, "prepare_threshold": 0},
    )
    await _pool.open()
    _checkpointer = AsyncPostgresSaver(_pool)
    if setup:
        await _checkpointer.setup()
        logger.info("PostgresSaver checkpoint tables are up to date")
    return _checkpointer


async def close_checkpointer() -> None:
    """Close the checkpointer pool and drop the singleton."""
    global _checkpointer, _pool
    _checkpointer = None
    if _pool is not None:
        await _pool.close()
    _pool = None
