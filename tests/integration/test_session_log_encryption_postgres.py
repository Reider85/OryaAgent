"""Integration tests for A-05 — session-log encryption at rest (real PostgreSQL).

Start infrastructure first::

    make db-up && make db-migrate

Covers the A-05 acceptance criteria: with
``ORYA_SESSION_LOG_ENCRYPTION_ENABLED=true`` + a key, the payload columns
``messages.content`` / ``messages.tool_calls`` are stored as pgcrypto armored
ciphertext (verified via a raw ``SELECT`` that forces text extraction), reads
through :func:`list_messages` return the original plaintext, and pre-existing
plaintext rows remain readable (tolerant decrypt). The pgcrypto extension is
installed by migration ``0002``.

The raw-ciphertext assertions extract columns to ``text`` in SQL (``#>>`` for
the JSONB ``tool_calls``) so they do not depend on asyncpg's json/jsonb codec
decoding behavior. Decrypted values are normalized with :func:`_json_text`.
"""

from __future__ import annotations

import asyncio
import json
import selectors
import sys
import uuid

import asyncpg
import pytest

from app.core.config import clear_settings_cache, get_settings
from app.db import apply_migrations, close_pool, get_asyncpg_pool
from app.db.session_log import list_messages, log_message

_KEY = "integration-passphrase-32chars!"
_ARMOR = "-----BEGIN PGP MESSAGE-----"


async def _database_reachable() -> bool:
    try:
        conn = await asyncio.wait_for(
            asyncpg.connect(get_settings().database_url), timeout=2.0
        )
    except (OSError, TimeoutError, asyncpg.PostgresError):
        return False
    await conn.close()
    return True


def _json_text(value) -> str:
    """Normalize a json/jsonb column value to its JSON text form.

    asyncpg may return json/jsonb either as a ``str`` (raw JSON text) or as a
    decoded Python object depending on codec registration; both are accepted
    here so the assertions are codec-agnostic.
    """
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False)


def _run_with_selector(scenario) -> None:
    """Run an async scenario on a SelectorEventLoop (psycopg-safe on win32)."""
    if sys.platform == "win32":
        loop = asyncio.SelectorEventLoop(selectors.SelectSelector())
        try:
            loop.run_until_complete(scenario())
        finally:
            loop.close()
            clear_settings_cache()
    else:
        try:
            asyncio.run(scenario())
        finally:
            clear_settings_cache()


def test_encrypted_roundtrip_and_tolerant_decrypt(
    monkeypatch: pytest.MonkeyPatch,
):
    """Full A-05 scenario on real infrastructure."""
    monkeypatch.setenv("ORYA_SESSION_LOG_ENCRYPTION_ENABLED", "true")
    monkeypatch.setenv("ORYA_SESSION_LOG_ENCRYPTION_KEY", _KEY)
    clear_settings_cache()

    async def scenario() -> None:
        if not await _database_reachable():
            pytest.skip("PostgreSQL not reachable — run `make db-up` first")
        pool = await get_asyncpg_pool()
        session_id = f"a05-{uuid.uuid4().hex[:8]}"
        try:
            await apply_migrations(pool)

            # AC: pgcrypto extension is installed by migration 0002.
            ext = await pool.fetchval(
                "SELECT extname FROM pg_extension WHERE extname = 'pgcrypto'"
            )
            assert ext == "pgcrypto"

            calls = [{"name": "read", "args": {"path": "a.py"}, "id": "c1"}]
            await log_message(session_id, "user", "hello world", pool=pool)
            await log_message(
                session_id,
                "assistant",
                "done",
                tool_calls=calls,
                pool=pool,
            )

            # AC: raw SELECT shows armored ciphertext, not plaintext. Content
            # is TEXT; tool_calls is JSONB so we extract to text via #>> to
            # force a string regardless of asyncpg's jsonb codec.
            rows = await pool.fetch(
                "SELECT seq, content, tool_calls #>> '{}' AS tc_text "
                "FROM messages WHERE session_id = $1 ORDER BY seq",
                session_id,
            )
            assert len(rows) == 2
            assert rows[0]["content"].startswith(_ARMOR)
            assert "hello world" not in rows[0]["content"]
            assert rows[1]["tc_text"].startswith(_ARMOR)
            assert "done" not in rows[1]["tc_text"]

            # AC: reads via list_messages decrypt back to the original.
            messages = await list_messages(session_id, pool=pool)
            assert [m["role"] for m in messages] == ["user", "assistant"]
            assert messages[0]["content"] == "hello world"
            assert messages[1]["content"] == "done"
            assert json.loads(_json_text(messages[1]["tool_calls"])) == calls

            # AC: a legacy plaintext row stays readable (tolerant decrypt).
            await pool.execute(
                "INSERT INTO messages (session_id, seq, role, content) "
                "VALUES ($1, 99, 'system', 'legacy plaintext')",
                session_id,
            )
            messages = await list_messages(session_id, pool=pool)
            by_seq_content = {m["seq"]: m["content"] for m in messages}
            assert by_seq_content[99] == "legacy plaintext"
        finally:
            await pool.execute("DELETE FROM sessions WHERE session_id = $1", session_id)
            await close_pool()

    _run_with_selector(scenario)


def test_plaintext_path_unchanged_when_flag_off(
    monkeypatch: pytest.MonkeyPatch,
):
    """With the kill-switch off, rows are stored in plaintext (no pgp)."""
    monkeypatch.delenv("ORYA_SESSION_LOG_ENCRYPTION_ENABLED", raising=False)
    monkeypatch.delenv("ORYA_SESSION_LOG_ENCRYPTION_KEY", raising=False)
    clear_settings_cache()

    async def scenario() -> None:
        if not await _database_reachable():
            pytest.skip("PostgreSQL not reachable — run `make db-up` first")
        pool = await get_asyncpg_pool()
        session_id = f"a05-plain-{uuid.uuid4().hex[:8]}"
        try:
            await apply_migrations(pool)
            await log_message(session_id, "user", "plain text", pool=pool)
            raw = await pool.fetchval(
                "SELECT content FROM messages WHERE session_id = $1", session_id
            )
            assert raw == "plain text"
            messages = await list_messages(session_id, pool=pool)
            assert messages[0]["content"] == "plain text"
        finally:
            await pool.execute("DELETE FROM sessions WHERE session_id = $1", session_id)
            await close_pool()

    _run_with_selector(scenario)
