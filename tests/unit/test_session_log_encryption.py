"""Unit tests for A-05 — session-log encryption at rest (mocked pools)."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest

from app.core.config import Settings, clear_settings_cache
from app.db.session_log import (
    _decrypt_content_sql,
    _decrypt_tool_calls_sql,
    _encryption_key,
    list_messages,
    log_message,
)

_KEY = "unit-test-passphrase-32chars!!"


class FakePool:
    """Minimal asyncpg.Pool stand-in recording executed SQL."""

    def __init__(self, returning_id: int = 1, fetch_rows: list[Any] | None = None):
        self.executed: list[tuple[str, tuple]] = []
        self.returning_id = returning_id
        self.fetch_rows = fetch_rows or []

    async def execute(self, query: str, *args: Any) -> str:
        self.executed.append((query, args))
        return "INSERT 0 1"

    async def fetch(self, query: str, *args: Any) -> list[Any]:
        self.executed.append((query, args))
        return self.fetch_rows

    async def fetchrow(self, query: str, *args: Any) -> dict:
        self.executed.append((query, args))
        return {"id": self.returning_id}


@pytest.fixture(autouse=True)
def isolated(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Sandbox env/config; each test opts into encryption explicitly."""
    for name in list(os.environ):
        if name.startswith("ORYA_") or name in {"DATABASE_URL", "LOG_LEVEL"}:
            monkeypatch.delenv(name, raising=False)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ORYA_CONFIG_PATH", str(tmp_path / "config.yaml"))
    clear_settings_cache()
    yield
    clear_settings_cache()


# --- config validation -----------------------------------------------------


def test_encryption_disabled_by_default():
    settings = Settings()
    assert settings.session_log_encryption_enabled is False
    assert settings.session_log_encryption_key is None


def test_encryption_enabled_with_key_is_valid(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("ORYA_SESSION_LOG_ENCRYPTION_ENABLED", "true")
    monkeypatch.setenv("ORYA_SESSION_LOG_ENCRYPTION_KEY", _KEY)
    clear_settings_cache()
    settings = Settings()
    assert settings.session_log_encryption_enabled is True
    assert settings.session_log_encryption_key is not None


def test_enabled_without_key_fails_fast(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("ORYA_SESSION_LOG_ENCRYPTION_ENABLED", "true")
    clear_settings_cache()
    with pytest.raises(ValueError, match="requires SESSION_LOG_ENCRYPTION_KEY"):
        Settings()


def test_short_encryption_key_rejected(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("ORYA_SESSION_LOG_ENCRYPTION_ENABLED", "true")
    monkeypatch.setenv("ORYA_SESSION_LOG_ENCRYPTION_KEY", "short")
    clear_settings_cache()
    with pytest.raises(ValueError, match="at least 16 characters"):
        Settings()


# --- SQL fragment helpers --------------------------------------------------


def test_decrypt_content_sql_uses_armor_prefix_and_key_param():
    fragment = _decrypt_content_sql("content", "4")
    assert "-----BEGIN PGP MESSAGE-----" in fragment
    assert "pgp_sym_decrypt" in fragment
    assert "convert_from" in fragment
    assert "$4" in fragment
    assert "ELSE content END" in fragment


def test_decrypt_tool_calls_sql_guards_null_and_jsonb():
    fragment = _decrypt_tool_calls_sql("tool_calls", "4")
    assert "IS NULL THEN NULL" in fragment
    assert "#>> '{}'" in fragment
    assert "pgp_sym_decrypt" in fragment
    assert "::jsonb" in fragment
    assert "$4" in fragment


# --- log_message (flag off keeps SQL byte-identical) -----------------------


async def test_log_message_flag_off_sql_unchanged():
    pool = FakePool(returning_id=9)
    message_id = await log_message("s1", "user", "hello", pool=pool)
    assert message_id == 9
    _, args = pool.executed[1]
    insert_query = pool.executed[1][0]
    assert "pgp_sym_encrypt" not in insert_query
    assert "armor(" not in insert_query
    assert args == ("s1", "user", "hello", None, None)


# --- log_message (flag on encrypts in SQL) ---------------------------------


async def test_log_message_flag_on_encrypts_content_and_tool_calls(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("ORYA_SESSION_LOG_ENCRYPTION_ENABLED", "true")
    monkeypatch.setenv("ORYA_SESSION_LOG_ENCRYPTION_KEY", _KEY)
    clear_settings_cache()
    pool = FakePool(returning_id=3)
    calls = [{"name": "read", "args": {"path": "a.py"}, "id": "c1"}]
    await log_message("s1", "assistant", "secret", tool_calls=calls, pool=pool)

    insert_query, args = pool.executed[1]
    assert "armor(pgp_sym_encrypt(convert_to($3, 'UTF8'), $6))" in insert_query
    assert (
        "to_jsonb(armor(pgp_sym_encrypt(convert_to($4, 'UTF8'), $6)))" in insert_query
    )
    # args = (session_id, role, content, payload, tool_call_id, key)
    assert args[0] == "s1"
    assert args[1] == "assistant"
    assert args[2] == "secret"
    assert args[4] is None
    assert args[5] == _KEY


async def test_log_message_flag_on_null_tool_calls_stays_null(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("ORYA_SESSION_LOG_ENCRYPTION_ENABLED", "true")
    monkeypatch.setenv("ORYA_SESSION_LOG_ENCRYPTION_KEY", _KEY)
    clear_settings_cache()
    pool = FakePool()
    await log_message("s1", "user", "hi", pool=pool)
    _, args = pool.executed[1]
    assert args[3] is None  # payload stays NULL -> CASE keeps NULL


# --- list_messages (flag off/on) -------------------------------------------


async def test_list_messages_flag_off_sql_unchanged():
    pool = FakePool(fetch_rows=[])
    await list_messages("s1", pool=pool)
    query, args = pool.executed[0]
    assert "pgp_sym_decrypt" not in query
    assert args == ("s1", 1000, 0)


async def test_list_messages_flag_on_decrypts_in_sql(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("ORYA_SESSION_LOG_ENCRYPTION_ENABLED", "true")
    monkeypatch.setenv("ORYA_SESSION_LOG_ENCRYPTION_KEY", _KEY)
    clear_settings_cache()
    pool = FakePool(fetch_rows=[])
    await list_messages("s1", limit=10, offset=5, pool=pool)
    query, args = pool.executed[0]
    assert "pgp_sym_decrypt" in query
    assert "convert_from" in query
    # args = (session_id, limit, offset, key)
    assert args == ("s1", 10, 5, _KEY)


# --- _encryption_key defensive path ----------------------------------------


async def test_encryption_key_raises_when_enabled_but_empty(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("ORYA_SESSION_LOG_ENCRYPTION_ENABLED", "true")
    monkeypatch.setenv("ORYA_SESSION_LOG_ENCRYPTION_KEY", _KEY)
    clear_settings_cache()
    # Bypass Settings validation by nuking the key post-validation.
    from app.core.config import get_settings

    settings = get_settings()
    object.__setattr__(settings, "session_log_encryption_key", None)
    with pytest.raises(RuntimeError, match="SESSION_LOG_ENCRYPTION_KEY"):
        _encryption_key()
