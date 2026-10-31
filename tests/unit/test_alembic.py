"""Unit tests for A-11 — alembic wiring: config, revision chain, .sql 1:1.

Static contract only (no database): the upgrade/downgrade flow itself runs
against real PostgreSQL in ``tests/integration/test_db_postgres.py``.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from alembic.script import ScriptDirectory

from app.core.config import clear_settings_cache
from app.db.migrate import (
    ALEMBIC_INI,
    MIGRATIONS_DIR,
    alembic_config,
    revisions_between,
    sync_url,
)

VERSIONS_DIR = Path(__file__).parents[2] / "alembic" / "versions"


@pytest.fixture(autouse=True)
def isolated_config(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Sandbox settings: no inherited ORYA_*/DATABASE_URL env, no repo .env."""
    for name in list(os.environ):
        if name.startswith("ORYA_") or name in {
            "DATABASE_URL",
            "DATABASE_POOL_SIZE",
            "DATABASE_MAX_OVERFLOW",
        }:
            monkeypatch.delenv(name, raising=False)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ORYA_CONFIG_PATH", str(tmp_path / "config.yaml"))
    clear_settings_cache()
    yield
    clear_settings_cache()


def _script() -> ScriptDirectory:
    # alembic_config() pins script_location to the repo (CWD-independent).
    return ScriptDirectory.from_config(alembic_config())


# --- config ----------------------------------------------------------------


def test_alembic_ini_present_and_points_at_alembic_dir():
    assert ALEMBIC_INI.is_file()
    text = ALEMBIC_INI.read_text(encoding="utf-8")
    assert "script_location = alembic" in text
    # sqlalchemy.url must come from Settings, never be hard-coded in the ini.
    assignments = [
        line.strip()
        for line in text.splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    assert not any(line.startswith("sqlalchemy.url") for line in assignments)


def test_alembic_config_reads_url_from_settings(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("DATABASE_URL", "postgresql://alice:s3cret@db:5432/orya")
    clear_settings_cache()

    cfg = alembic_config()

    assert (
        cfg.get_main_option("sqlalchemy.url")
        == "postgresql+psycopg://alice:s3cret@db:5432/orya"
    )


def test_alembic_config_url_override_wins(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://default:default@db/orya")
    clear_settings_cache()

    cfg = alembic_config("postgresql://rt:rt@db/orya?options=-c%20search_path%3Drt")

    assert cfg.get_main_option("sqlalchemy.url") == (
        "postgresql+psycopg://rt:rt@db/orya?options=-c%20search_path%3Drt"
    )


def test_sync_url_normalizes_asyncpg_dsn_styles():
    cases = {
        "postgresql://u:p@h/db": "postgresql+psycopg://u:p@h/db",
        "postgres://u:p@h/db": "postgresql+psycopg://u:p@h/db",
        "postgresql+asyncpg://u:p@h/db": "postgresql+psycopg://u:p@h/db",
        "postgresql+psycopg://u:p@h/db": "postgresql+psycopg://u:p@h/db",
        "other://x": "other://x",
    }
    for source, expected in cases.items():
        assert sync_url(source) == expected, source


# --- revision chain --------------------------------------------------------


def test_revision_chain_is_linear_with_single_head():
    script = _script()
    revisions = {rev.revision: rev for rev in script.walk_revisions()}
    assert set(revisions) == {"0001_init", "0002_session_log_encryption"}
    assert script.get_heads() == ["0002_session_log_encryption"]
    assert revisions["0001_init"].down_revision is None
    assert revisions["0002_session_log_encryption"].down_revision == "0001_init"


def test_sql_files_revisions_and_version_modules_match_1to1():
    """A schema change needs .sql + revision wrapper — neither may be forgotten."""
    sql_stems = {path.stem for path in MIGRATIONS_DIR.glob("*.sql")}
    version_modules = {path.stem for path in VERSIONS_DIR.glob("*.py")}
    revision_ids = {rev.revision for rev in _script().walk_revisions()}
    assert sql_stems == version_modules == revision_ids
    assert "0001_init" in sql_stems  # the initial schema is always required


def test_revision_wrappers_execute_the_matching_sql_file():
    for path in VERSIONS_DIR.glob("*.py"):
        source = path.read_text(encoding="utf-8")
        assert "MIGRATIONS_DIR" in source, f"{path.name} must read the .sql file"
        assert f'"{path.stem}.sql"' in source, f"{path.name} reads the wrong file"
        assert "def downgrade()" in source, f"{path.name} must support downgrade"


def test_wrappers_contain_real_downgrade_ddl():
    """ROADMAP5 §18.2 rollback story: `alembic downgrade base` must work."""
    init = (VERSIONS_DIR / "0001_init.py").read_text(encoding="utf-8")
    for table in ("tool_calls", "messages", "memory_audit_log", "sessions"):
        assert f"DROP TABLE IF EXISTS {table}" in init, f"missing DROP for {table}"
    encryption = (VERSIONS_DIR / "0002_session_log_encryption.py").read_text(
        encoding="utf-8"
    )
    assert "DROP EXTENSION IF EXISTS pgcrypto" in encryption


def test_revisions_between_walks_chain_oldest_first():
    script = _script()
    assert revisions_between(script, "0002_session_log_encryption", None) == [
        "0001_init",
        "0002_session_log_encryption",
    ]
    assert revisions_between(script, "0002_session_log_encryption", "0001_init") == [
        "0002_session_log_encryption"
    ]
    assert (
        revisions_between(
            script, "0002_session_log_encryption", "0002_session_log_encryption"
        )
        == []
    )
    assert revisions_between(script, None, "0001_init") == []


def test_load_migrations_lists_every_wrapped_file():
    from app.db.migrate import load_migrations

    versions = [version for version, _ in load_migrations()]
    assert versions == sorted(versions)
    assert set(versions) == {path.stem for path in MIGRATIONS_DIR.glob("*.sql")}
