"""Alembic-backed migration runner (M-03 → A-11).

Plain-``.sql`` migrations stay the source of truth for upgrades (the project
is asyncpg-only at runtime — no ORM, no SQLAlchemy imports outside this CLI
path); Alembic orchestrates them and owns bookkeeping:

- ``alembic/versions/NNNN_name.py`` — thin wrapper per ``app/db/migrations/
  NNNN_name.sql`` file: ``upgrade()`` executes the ``.sql``, ``downgrade()``
  is inline DDL (``alembic downgrade base`` works, per ROADMAP rollback §18.2).
- version table — ``alembic_version`` (supersedes the legacy
  ``schema_migrations`` table, dropped after the first Alembic upgrade);
- revision ids are the ``.sql`` file stems, so phase-boundary rollbacks read
  naturally: ``alembic downgrade 0002_session_log_encryption``.

Legacy databases migrate transparently: every ``.sql`` file is idempotent
(``IF NOT EXISTS``), so ``upgrade head`` on a pre-Alembic database re-applies
nothing and only stamps ``alembic_version``.

CLI::

    python -m app.db.migrate [migrate|downgrade REVISION|current]
    # or: orya db migrate / orya db downgrade / orya db current
"""

from __future__ import annotations

import argparse
import asyncio
import logging
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, text

from alembic import command
from app.core.config import get_settings

logger = logging.getLogger(__name__)

MIGRATIONS_DIR = Path(__file__).parent / "migrations"
REPO_ROOT = Path(__file__).resolve().parents[2]
ALEMBIC_INI = REPO_ROOT / "alembic.ini"


def load_migrations(directory: Path | None = None) -> list[tuple[str, str]]:
    """Return ``(version, sql)`` pairs sorted by version (file stem)."""
    directory = directory or MIGRATIONS_DIR
    migrations: list[tuple[str, str]] = []
    for path in sorted(directory.glob("*.sql")):
        migrations.append((path.stem, path.read_text(encoding="utf-8")))
    return migrations


def sync_url(url: str) -> str:
    """Rewrite an asyncpg-style DSN to the SQLAlchemy psycopg dialect.

    ``Settings.database_url`` is shared with the asyncpg pool (accepts
    ``postgres://``/``postgresql://``/``postgresql+asyncpg://``); Alembic's
    sync engine runs on psycopg (an explicit A-11 dependency).
    """
    if url.startswith("postgresql+psycopg://"):
        return url
    for prefix in ("postgresql+asyncpg://", "postgres://", "postgresql://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix) :]
    return url


def alembic_config(url: str | None = None) -> Config:
    """Build an alembic ``Config`` with the URL taken from Settings.

    ``url`` overrides ``settings.database_url`` (used by tests to run
    migrations against an isolated schema).
    """
    if not ALEMBIC_INI.is_file():
        raise RuntimeError(
            f"alembic.ini not found at {ALEMBIC_INI} — migrations must run "
            "from a checkout or the deploy image (A-11)"
        )
    cfg = Config(str(ALEMBIC_INI))
    # The ini's script_location is CWD-relative — pin it to the repo so the
    # CLI works from any directory (orya db migrate from a workspace, tests).
    cfg.set_main_option("script_location", str(REPO_ROOT / "alembic"))
    # set_main_option feeds ConfigParser interpolation — literal "%" must be "%%".
    resolved = sync_url(url or get_settings().database_url).replace("%", "%%")
    cfg.set_main_option("sqlalchemy.url", resolved)
    return cfg


def revisions_between(
    script: ScriptDirectory, newer: str | None, older: str | None
) -> list[str]:
    """Revision ids from ``older`` (exclusive) up to ``newer`` (inclusive).

    Walks the linear ``down_revision`` chain, oldest first — the chain this
    project uses (one revision per ``.sql`` file, no branches/merges).
    ``older=None`` means "from the base" (every revision up to ``newer``).
    """
    if newer is None or newer == older:
        return []
    collected: list[str] = []
    revision = script.get_revision(newer)
    while revision is not None and revision.revision != older:
        collected.append(revision.revision)
        down = revision.down_revision
        if not isinstance(down, str):
            break
        revision = script.get_revision(down)
    return list(reversed(collected))


def _current_revision(url: str | None = None) -> str | None:
    """HEAD revision recorded in ``alembic_version`` (None = not migrated)."""
    engine = create_engine(alembic_config(url).get_main_option("sqlalchemy.url"))
    try:
        with engine.connect() as conn:
            exists = conn.execute(
                text("SELECT to_regclass('alembic_version')")
            ).scalar()
            if not exists:
                return None
            # Linear chain (see revisions_between) — one row per branch head.
            return conn.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar()
    finally:
        engine.dispose()


def _drop_legacy_bookkeeping(cfg: Config) -> None:
    """Drop the pre-Alembic ``schema_migrations`` table when present (A-11)."""
    engine = create_engine(cfg.get_main_option("sqlalchemy.url"))
    try:
        with engine.begin() as conn:
            exists = conn.execute(text("SELECT to_regclass('schema_migrations')"))
            if exists.scalar():
                conn.execute(text("DROP TABLE schema_migrations"))
                logger.info("Dropped legacy schema_migrations table (A-11)")
    finally:
        engine.dispose()


def _upgrade_to_head(url: str | None = None) -> list[str]:
    """``alembic upgrade head``; returns the newly applied revision ids."""
    cfg = alembic_config(url)
    before = _current_revision(url)
    command.upgrade(cfg, "head")
    after = _current_revision(url)
    if after == before:
        return []
    applied = revisions_between(ScriptDirectory.from_config(cfg), after, before)
    _drop_legacy_bookkeeping(cfg)
    return applied


def _downgrade_to(revision: str, url: str | None = None) -> list[str]:
    """``alembic downgrade <revision>``; returns the reverted revision ids."""
    cfg = alembic_config(url)
    before = _current_revision(url)
    command.downgrade(cfg, revision)
    after = _current_revision(url)
    if after == before:
        return []
    return revisions_between(ScriptDirectory.from_config(cfg), before, after)


async def apply_migrations(url: str | None = None) -> list[str]:
    """Apply pending migrations (``alembic upgrade head``).

    Runs the sync Alembic machinery in a worker thread so callers stay on
    the event loop (lifespan, CLI, tests). Returns newly applied revision
    ids (empty when already at head). Migrations are idempotent — re-running
    is a no-op.
    """
    return await asyncio.to_thread(_upgrade_to_head, url)


async def downgrade(revision: str = "base", url: str | None = None) -> list[str]:
    """Downgrade to ``revision`` (``base`` drops everything); see ROADMAP §18.2."""
    return await asyncio.to_thread(_downgrade_to, revision, url)


async def current_revision(url: str | None = None) -> str | None:
    """Current ``alembic_version`` head (None = database not migrated)."""
    return await asyncio.to_thread(_current_revision, url)


async def _main(argv: list[str] | None = None) -> None:
    """``python -m app.db.migrate`` — migrate/downgrade/current and exit."""
    parser = argparse.ArgumentParser(
        prog="python -m app.db.migrate",
        description="Alembic-backed migrations (A-11)",
    )
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("migrate", help="apply pending migrations (default)")
    downgrade_parser = sub.add_parser(
        "downgrade", help="downgrade to a revision (e.g. base)"
    )
    downgrade_parser.add_argument(
        "revision",
        help="target revision id, e.g. base or 0002_session_log_encryption",
    )
    sub.add_parser("current", help="print the current database revision")

    args = parser.parse_args(argv)
    from app.core.logging_setup import configure_cli_logging

    configure_cli_logging()
    command_name = args.command or "migrate"
    if command_name == "migrate":
        applied = await apply_migrations()
        if applied:
            logger.info("Applied migrations: %s", ", ".join(applied))
        else:
            logger.info("No pending migrations.")
    elif command_name == "downgrade":
        reverted = await downgrade(args.revision)
        if reverted:
            logger.info("Downgraded from: %s", ", ".join(reverted))
        else:
            logger.info("Already at revision %s.", args.revision)
    else:  # current
        revision = await current_revision()
        if revision is None:
            logger.info("Current revision: (none — database not migrated)")
        else:
            logger.info("Current revision: %s", revision)


if __name__ == "__main__":
    asyncio.run(_main())
