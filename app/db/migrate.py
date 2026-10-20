"""SQL migration runner (M-03).

Plain-``.sql`` migrations instead of Alembic: the project is asyncpg-only
(no SQLAlchemy), and the MVP schema is a single initial DDL file plus
future deltas. Each migration file is applied inside one transaction and
recorded in ``schema_migrations`` — re-running is a no-op (idempotent).

Files: ``app/db/migrations/NNNN_name.sql`` — applied in lexicographic
order; the version is the file stem (e.g. ``0001_init``).

CLI::

    python -m app.db.migrate
    # or: orya db migrate
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

import asyncpg

logger = logging.getLogger(__name__)

MIGRATIONS_DIR = Path(__file__).parent / "migrations"

_SCHEMA_MIGRATIONS_DDL = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version    TEXT PRIMARY KEY,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
)
"""


def load_migrations(directory: Path | None = None) -> list[tuple[str, str]]:
    """Return ``(version, sql)`` pairs sorted by version (file stem)."""
    directory = directory or MIGRATIONS_DIR
    migrations: list[tuple[str, str]] = []
    for path in sorted(directory.glob("*.sql")):
        migrations.append((path.stem, path.read_text(encoding="utf-8")))
    return migrations


async def applied_versions(conn: asyncpg.Connection) -> set[str]:
    """Versions already recorded in ``schema_migrations``."""
    await conn.execute(_SCHEMA_MIGRATIONS_DDL)
    rows = await conn.fetch("SELECT version FROM schema_migrations")
    return {row["version"] for row in rows}


async def apply_migrations(
    pool: asyncpg.Pool, directory: Path | None = None
) -> list[str]:
    """Apply pending migrations; returns the list of newly applied versions.

    Each migration runs in its own transaction together with its
    bookkeeping insert — a failing file leaves no partial state.
    """
    pending = load_migrations(directory)
    results: list[str] = []
    async with pool.acquire() as conn:
        already = await applied_versions(conn)
        for version, sql in pending:
            if version in already:
                continue
            async with conn.transaction():
                await conn.execute(sql)
                await conn.execute(
                    "INSERT INTO schema_migrations (version) VALUES ($1)", version
                )
            logger.info("Applied migration %s", version)
            results.append(version)
    return results


async def _main() -> None:
    """``python -m app.db.migrate`` — apply pending migrations and exit."""
    from app.db import close_pool, get_asyncpg_pool

    pool = await get_asyncpg_pool()
    try:
        applied = await apply_migrations(pool)
    finally:
        await close_pool()
    if applied:
        print(f"Applied migrations: {', '.join(applied)}")
    else:
        print("No pending migrations.")


if __name__ == "__main__":
    asyncio.run(_main())
