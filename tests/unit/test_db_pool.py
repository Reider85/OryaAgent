"""Unit tests for M-03 — asyncpg pool singleton and SQL migration runner (mocked)."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest

import app.db as db
from app.core.config import clear_settings_cache
from app.db.migrate import apply_migrations, load_migrations

# --- fakes -----------------------------------------------------------------


class FakeConnection:
    def __init__(self, fetch_rows: list[dict] | None = None):
        self.executed: list[tuple[str, tuple]] = []
        self.fetch_rows = fetch_rows if fetch_rows is not None else []
        self.transactions = 0

    async def execute(self, query: str, *args: Any) -> str:
        self.executed.append((query, args))
        return "OK"

    async def fetch(self, query: str, *args: Any) -> list[dict]:
        self.executed.append((query, args))
        return list(self.fetch_rows)

    def transaction(self) -> Any:
        conn = self

        class _Tx:
            async def __aenter__(self) -> None:
                conn.transactions += 1

            async def __aexit__(self, *exc: object) -> bool:
                return False

        return _Tx()


class FakePool:
    def __init__(self, conn: FakeConnection):
        self._conn = conn
        self.closed = False

    def acquire(self) -> Any:
        pool_conn = self._conn

        class _Acquire:
            async def __aenter__(self) -> FakeConnection:
                return pool_conn

            async def __aexit__(self, *exc: object) -> bool:
                return False

        return _Acquire()

    async def close(self) -> None:
        self.closed = True


@pytest.fixture(autouse=True)
def isolated(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """No inherited env/.env, reset pool + checkpointer singletons."""
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
    db._pool = None
    db._pool_loop = None
    yield
    db._pool = None
    db._pool_loop = None
    clear_settings_cache()


# --- pool ------------------------------------------------------------------


async def test_get_asyncpg_pool_uses_settings(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@host:5432/db")
    monkeypatch.setenv("DATABASE_POOL_SIZE", "3")
    monkeypatch.setenv("DATABASE_MAX_OVERFLOW", "7")
    clear_settings_cache()

    captured: dict[str, Any] = {}
    fake_pool = FakePool(FakeConnection())

    async def fake_create_pool(**kwargs: Any) -> FakePool:
        captured.update(kwargs)
        return fake_pool

    monkeypatch.setattr(db.asyncpg, "create_pool", fake_create_pool)

    pool = await db.get_asyncpg_pool()

    assert pool is fake_pool
    assert captured["dsn"] == "postgresql://u:p@host:5432/db"
    assert captured["min_size"] == 3
    assert captured["max_size"] == 10  # pool_size + max_overflow


async def test_get_asyncpg_pool_is_singleton(monkeypatch: pytest.MonkeyPatch):
    calls = 0

    async def fake_create_pool(**kwargs: Any) -> FakePool:
        nonlocal calls
        calls += 1
        return FakePool(FakeConnection())

    monkeypatch.setattr(db.asyncpg, "create_pool", fake_create_pool)

    first = await db.get_asyncpg_pool()
    second = await db.get_asyncpg_pool()
    assert first is second
    assert calls == 1


async def test_close_pool_resets_singleton(monkeypatch: pytest.MonkeyPatch):
    pools: list[FakePool] = []

    async def fake_create_pool(**kwargs: Any) -> FakePool:
        pool = FakePool(FakeConnection())
        pools.append(pool)
        return pool

    monkeypatch.setattr(db.asyncpg, "create_pool", fake_create_pool)

    await db.get_asyncpg_pool()
    await db.close_pool()
    assert pools[0].closed is True
    assert db._pool is None

    await db.get_asyncpg_pool()
    assert len(pools) == 2


async def test_pool_recreated_when_loop_changes(monkeypatch: pytest.MonkeyPatch):
    pools: list[FakePool] = []

    async def fake_create_pool(**kwargs: Any) -> FakePool:
        pool = FakePool(FakeConnection())
        pools.append(pool)
        return pool

    monkeypatch.setattr(db.asyncpg, "create_pool", fake_create_pool)

    first = await db.get_asyncpg_pool()
    # Simulate a pool left over from a previous (closed) event loop.
    db._pool_loop = object()  # type: ignore[assignment]
    second = await db.get_asyncpg_pool()
    assert first is not second
    assert first.closed is True


# --- migrate ---------------------------------------------------------------


def test_load_migrations_reads_files(tmp_path: Path):
    (tmp_path / "0002_b.sql").write_text("SELECT 2;", encoding="utf-8")
    (tmp_path / "0001_a.sql").write_text("SELECT 1;", encoding="utf-8")
    migrations = load_migrations(tmp_path)
    assert [v for v, _ in migrations] == ["0001_a", "0002_b"]
    assert migrations[0][1] == "SELECT 1;"


async def test_apply_migrations_skips_already_applied():
    conn = FakeConnection(fetch_rows=[{"version": "0001_init"}])
    pool = FakePool(conn)
    applied = await apply_migrations(pool)  # type: ignore[arg-type]
    assert applied == []
    # schema_migrations bookkeeping table ensured, nothing else executed
    assert any("schema_migrations" in q for q, _ in conn.executed)
    assert not any(
        q.lower().startswith("create table if not exists sessions")
        for q, _ in conn.executed
    )


async def test_apply_migrations_applies_pending_in_transaction():
    conn = FakeConnection(fetch_rows=[])
    pool = FakePool(conn)
    applied = await apply_migrations(pool)  # type: ignore[arg-type]
    assert applied == ["0001_init"]
    assert conn.transactions == 1

    executed_sql = [q for q, _ in conn.executed]
    assert any("create table if not exists sessions" in q.lower() for q in executed_sql)
    inserts = [
        (q, args) for q, args in conn.executed if "INSERT INTO schema_migrations" in q
    ]
    assert inserts == [
        ("INSERT INTO schema_migrations (version) VALUES ($1)", ("0001_init",))
    ]


async def test_apply_migrations_with_empty_dir_is_noop(tmp_path: Path):
    conn = FakeConnection(fetch_rows=[])
    pool = FakePool(conn)
    applied = await apply_migrations(pool, directory=tmp_path)  # type: ignore[arg-type]
    assert applied == []
    assert conn.transactions == 0
