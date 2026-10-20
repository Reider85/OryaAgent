"""Integration tests for M-03 — real PostgreSQL (skipped when unreachable).

Start infrastructure first::

    make db-up && make db-migrate
"""

from __future__ import annotations

import asyncio
import json
import uuid

import asyncpg
import pytest

from app.core.config import get_settings
from app.db import apply_migrations, close_pool, get_asyncpg_pool
from app.db.checkpoints import close_checkpointer, get_checkpointer

APP_TABLES = ("sessions", "messages", "tool_calls", "memory_audit_log")
CHECKPOINT_TABLES = (
    "checkpoints",
    "checkpoint_blobs",
    "checkpoint_writes",
    "checkpoint_migrations",
)


async def _database_reachable() -> bool:
    try:
        conn = await asyncio.wait_for(
            asyncpg.connect(get_settings().database_url), timeout=2.0
        )
    except (OSError, TimeoutError, asyncpg.PostgresError):
        return False
    await conn.close()
    return True


@pytest.fixture
async def pool():
    if not await _database_reachable():
        pytest.skip("PostgreSQL not reachable — run `make db-up` first")
    p = await get_asyncpg_pool()
    yield p
    await close_pool()
    await close_checkpointer()


async def test_migrations_apply_idempotently(pool: asyncpg.Pool):
    first = await apply_migrations(pool)
    second = await apply_migrations(pool)
    assert second == []
    if first:
        assert "0001_init" in first


async def test_schema_tables_and_indexes_exist(pool: asyncpg.Pool):
    await apply_migrations(pool)
    rows = await pool.fetch(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema = 'public' AND table_name = ANY($1)",
        list(APP_TABLES),
    )
    found = {row["table_name"] for row in rows}
    assert found == set(APP_TABLES)

    idx_rows = await pool.fetch(
        "SELECT indexname FROM pg_indexes "
        "WHERE schemaname = 'public' AND indexname = ANY($1)",
        [
            "idx_messages_session_id",
            "idx_tool_calls_session_id",
            "idx_memory_audit_log_ts",
        ],
    )
    assert len(idx_rows) == 3


async def test_crud_roundtrip_all_tables(pool: asyncpg.Pool):
    await apply_migrations(pool)
    session_id = f"20261020-000000-{uuid.uuid4().hex[:8]}"
    try:
        await pool.execute(
            "INSERT INTO sessions (session_id, title, provider, model, working_dir, metadata) "
            "VALUES ($1, $2, $3, $4, $5, $6)",
            session_id,
            "M-03 test",
            "anthropic",
            "claude-sonnet-3.5",
            "/tmp",
            json.dumps({"source": "integration"}),
        )
        msg_row = await pool.fetchrow(
            "INSERT INTO messages (session_id, seq, role, content) "
            "VALUES ($1, 1, 'user', 'hello') RETURNING id",
            session_id,
        )
        assert msg_row is not None
        message_id = msg_row["id"]

        await pool.execute(
            "INSERT INTO tool_calls "
            "(session_id, message_id, call_id, tool_name, args, result, outcome, approved_by, duration_ms) "
            "VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)",
            session_id,
            message_id,
            "call_1",
            "read",
            json.dumps({"path": "README.md"}),
            "# OryaAgent",
            "success",
            "user",
            12,
        )
        await pool.execute(
            "INSERT INTO memory_audit_log (actor, action, file, content_preview, reason, session_id) "
            "VALUES ($1, $2, $3, $4, $5, $6)",
            "user",
            "append",
            "LEARNED.md",
            "fact preview",
            "/learn",
            session_id,
        )

        session = await pool.fetchrow(
            "SELECT * FROM sessions WHERE session_id = $1", session_id
        )
        assert session is not None
        assert session["status"] == "active"
        assert json.loads(session["metadata"]) == {"source": "integration"}

        msg = await pool.fetchrow(
            "SELECT * FROM messages WHERE session_id = $1 AND seq = 1", session_id
        )
        assert msg is not None
        assert msg["role"] == "user"
        assert msg["content"] == "hello"

        call = await pool.fetchrow(
            "SELECT * FROM tool_calls WHERE session_id = $1", session_id
        )
        assert call is not None
        assert call["tool_name"] == "read"
        assert json.loads(call["args"]) == {"path": "README.md"}
        assert call["outcome"] == "success"

        audit = await pool.fetchrow(
            "SELECT * FROM memory_audit_log WHERE session_id = $1", session_id
        )
        assert audit is not None
        assert audit["action"] == "append"
    finally:
        await pool.execute("DELETE FROM sessions WHERE session_id = $1", session_id)
        await pool.execute(
            "DELETE FROM memory_audit_log WHERE session_id = $1", session_id
        )


async def test_session_delete_cascades_messages_and_tool_calls(pool: asyncpg.Pool):
    await apply_migrations(pool)
    session_id = f"20261020-000000-{uuid.uuid4().hex[:8]}"
    await pool.execute("INSERT INTO sessions (session_id) VALUES ($1)", session_id)
    msg_row = await pool.fetchrow(
        "INSERT INTO messages (session_id, seq, role, content) "
        "VALUES ($1, 1, 'user', 'x') RETURNING id",
        session_id,
    )
    await pool.execute(
        "INSERT INTO tool_calls (session_id, message_id, call_id, tool_name) "
        "VALUES ($1, $2, 'c', 'read')",
        session_id,
        msg_row["id"],
    )

    await pool.execute("DELETE FROM sessions WHERE session_id = $1", session_id)

    remaining_msgs = await pool.fetchval(
        "SELECT count(*) FROM messages WHERE session_id = $1", session_id
    )
    remaining_calls = await pool.fetchval(
        "SELECT count(*) FROM tool_calls WHERE session_id = $1", session_id
    )
    assert remaining_msgs == 0
    assert remaining_calls == 0


def test_checkpointer_setup_creates_tables():
    """Runs on its own SelectorEventLoop: psycopg cannot use ProactorEventLoop."""
    import selectors
    import sys

    async def scenario() -> None:
        if not await _database_reachable():
            pytest.skip("PostgreSQL not reachable — run `make db-up` first")
        p = await get_asyncpg_pool()
        try:
            await apply_migrations(p)
            await get_checkpointer()
            rows = await p.fetch(
                "SELECT tablename FROM pg_tables "
                "WHERE schemaname = 'public' AND tablename = ANY($1)",
                list(CHECKPOINT_TABLES),
            )
            found = {row["tablename"] for row in rows}
            assert "checkpoints" in found
        finally:
            await close_checkpointer()
            await close_pool()

    if sys.platform == "win32":
        loop = asyncio.SelectorEventLoop(selectors.SelectSelector())
        try:
            loop.run_until_complete(scenario())
        finally:
            loop.close()
    else:
        asyncio.run(scenario())
