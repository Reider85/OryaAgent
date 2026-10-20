"""Unit tests for M-03 — app/db/schema.sql and migration files."""

from __future__ import annotations

import re
from pathlib import Path

from app.db.migrate import MIGRATIONS_DIR, load_migrations

SCHEMA_PATH = Path(__file__).parents[2] / "app" / "db" / "schema.sql"

REQUIRED_TABLES = ("sessions", "messages", "tool_calls", "memory_audit_log")


def _schema_sql() -> str:
    return SCHEMA_PATH.read_text(encoding="utf-8").lower()


def test_schema_declares_all_required_tables():
    sql = _schema_sql()
    for table in REQUIRED_TABLES:
        assert f"create table if not exists {table}" in sql, f"missing table {table}"


def test_schema_messages_references_sessions():
    sql = _schema_sql()
    assert "references sessions (session_id) on delete cascade" in sql


def test_schema_tool_calls_references_sessions_and_messages():
    sql = _schema_sql()
    assert "references sessions (session_id) on delete cascade" in sql
    assert "references messages (id) on delete set null" in sql


def test_schema_messages_seq_unique_per_session():
    sql = _schema_sql()
    assert "unique (session_id, seq)" in sql


def test_schema_has_expected_indexes():
    sql = _schema_sql()
    for index in (
        "idx_messages_session_id",
        "idx_tool_calls_session_id",
        "idx_memory_audit_log_ts",
    ):
        assert index in sql, f"missing index {index}"


def test_schema_status_and_outcome_check_constraints():
    sql = _schema_sql()
    assert "('active', 'closed', 'aborted')" in sql
    assert "('success', 'error', 'denied', 'aborted', 'timeout')" in sql


def test_migrations_dir_has_initial_migration():
    assert (MIGRATIONS_DIR / "0001_init.sql").exists()


def test_migration_file_names_follow_convention():
    for path in MIGRATIONS_DIR.glob("*.sql"):
        assert re.fullmatch(r"\d{4}_[a-z0-9_]+", path.stem), (
            f"migration {path.name} must match NNNN_name.sql"
        )


def test_load_migrations_sorted_unique_versions():
    migrations = load_migrations()
    versions = [version for version, _ in migrations]
    assert versions == sorted(versions)
    assert len(versions) == len(set(versions))
    assert "0001_init" in versions


def test_every_schema_table_appears_in_migrations():
    """schema.sql (canonical) must not drift from applied migrations."""
    combined = "\n".join(sql for _, sql in load_migrations()).lower()
    for table in REQUIRED_TABLES:
        assert f"create table if not exists {table}" in combined
