"""Alembic environment (A-11) — runs the ``.sql`` files in
``app/db/migrations/`` through the revision wrappers in ``alembic/versions/``.

The engine URL comes from ``Settings.database_url``: ``app.db.migrate.
alembic_config()`` injects it before programmatic commands run, and this
module falls back to the same source so a bare ``alembic upgrade head`` from
the repo root works. No ORM models exist in this project — ``target_metadata``
is ``None`` and autogenerate is never used; the schema truth stays in
``app/db/schema.sql`` (checked by ``tests/unit/test_db_schema.py``).
"""

from __future__ import annotations

import logging
import sys
from logging.config import fileConfig
from pathlib import Path

from sqlalchemy import engine_from_config, pool

from alembic import context

# Repo root on sys.path: revision wrappers import app.db.migrate (works from
# any CWD and inside the deploy/Dockerfile image where WORKDIR is /app).
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

config = context.config

if config.config_file_name is not None and not logging.getLogger().handlers:
    # Only the bare `alembic` CLI has an unconfigured root logger. When the
    # app/CLI/tests invoke Alembic programmatically the root already carries
    # handlers — applying the ini would reset its level to WARN and swallow
    # the migration summary (A-11).
    fileConfig(config.config_file_name, disable_existing_loggers=False)

if not config.get_main_option("sqlalchemy.url"):
    from app.core.config import get_settings
    from app.db.migrate import sync_url

    # set_main_option runs through ConfigParser interpolation — double "%".
    config.set_main_option(
        "sqlalchemy.url", sync_url(get_settings().database_url).replace("%", "%%")
    )

# No ORM models — there is nothing to reflect.
target_metadata = None


def run_migrations_offline() -> None:
    """Emit SQL to stdout without a DBAPI connection (``alembic upgrade head --sql``)."""
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection) -> None:  # noqa: ANN001 - sqlalchemy Connection
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations against the configured database."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        # NullPool: no pooled connections linger in a long-running process —
        # migrations are rare CLI/startup events, not a hot path (A-11).
        poolclass=pool.NullPool,
    )
    try:
        with connectable.connect() as connection:
            do_run_migrations(connection)
    finally:
        connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
