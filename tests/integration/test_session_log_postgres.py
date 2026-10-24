"""Integration tests for M-14 — session log on real PostgreSQL + checkpoints.

Start infrastructure first::

    make db-up && make db-migrate

Covers the BACKLOG4 acceptance criteria: JSONL projection contains
user/ai/tool events after a graph run, the worker is idempotent (dedup by
ts), checkpoint state survives a checkpointer restart, and ``log_message``
round-trips through the typed ``messages`` table.
"""

from __future__ import annotations

import asyncio
import json
import selectors
import sys
import uuid
from pathlib import Path

import asyncpg
import pytest
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.tools import tool

from app.core.config import clear_settings_cache, get_settings
from app.core.graph import build_graph, default_run_config
from app.db import apply_migrations, close_pool, get_asyncpg_pool
from app.db.checkpoints import close_checkpointer, get_checkpointer
from app.db.session_log import (
    discover_thread_ids,
    log_message,
    project_thread,
    session_jsonl_path,
)


@tool
def echo(text: str) -> str:
    """Echo the given text back to the caller."""
    return f"echo: {text}"


async def _database_reachable() -> bool:
    try:
        conn = await asyncio.wait_for(
            asyncpg.connect(get_settings().database_url), timeout=2.0
        )
    except (OSError, TimeoutError, asyncpg.PostgresError):
        return False
    await conn.close()
    return True


def _tool_turn_model() -> FakeMessagesListChatModel:
    return FakeMessagesListChatModel(
        responses=[
            AIMessage(
                content="",
                tool_calls=[{"name": "echo", "args": {"text": "hi"}, "id": "call_1"}],
            ),
            AIMessage(content="done"),
        ]
    )


def test_session_log_projection_and_restart(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    """Full M-14 scenario on real infrastructure (SelectorEventLoop on win32)."""
    monkeypatch.setenv("ORYA_SESSIONS_DIR", str(tmp_path / "sessions"))
    clear_settings_cache()

    async def scenario() -> None:
        if not await _database_reachable():
            pytest.skip("PostgreSQL not reachable — run `make db-up` first")
        pool = await get_asyncpg_pool()
        thread_id = f"m14-{uuid.uuid4().hex[:8]}"
        try:
            await apply_migrations(pool)
            checkpointer = await get_checkpointer()
            graph = build_graph([echo], _tool_turn_model(), checkpointer, None)
            config = default_run_config(thread_id)

            result = await graph.ainvoke({"messages": [HumanMessage("hi")]}, config)
            assert result["messages"][-1].content == "done"

            # AC: after graph.ainvoke the projection has >= 3 events
            # (user, ai, tool) in ~/.orya/sessions/{thread_id}.jsonl.
            appended = await project_thread(thread_id)
            assert appended >= 3
            path = session_jsonl_path(thread_id)
            events = [
                json.loads(line)
                for line in path.read_text(encoding="utf-8").splitlines()
            ]
            types = [e["type"] for e in events]
            assert "user" in types and "ai" in types and "tool" in types

            # AC: re-running the projection appends nothing (dedup by ts).
            assert await project_thread(thread_id) == 0
            assert len(path.read_text(encoding="utf-8").splitlines()) == len(events)

            # Thread is discoverable for the background worker.
            assert thread_id in await discover_thread_ids()

            # AC: after a checkpointer "restart" the last state is restored.
            await close_checkpointer()
            checkpointer2 = await get_checkpointer()
            graph2 = build_graph([echo], _tool_turn_model(), checkpointer2, None)
            state = await graph2.aget_state(config)
            assert state.values["messages"][-1].content == "done"
        finally:
            await close_checkpointer()
            await close_pool()

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


def test_log_message_roundtrip(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Typed messages rows: ensure_session + auto seq + tool_calls JSONB."""
    monkeypatch.setenv("ORYA_SESSIONS_DIR", str(tmp_path / "sessions"))
    clear_settings_cache()

    async def scenario() -> None:
        if not await _database_reachable():
            pytest.skip("PostgreSQL not reachable — run `make db-up` first")
        pool = await get_asyncpg_pool()
        session_id = f"m14-{uuid.uuid4().hex[:8]}"
        try:
            await apply_migrations(pool)
            await log_message(session_id, "user", "hello", pool=pool)
            await log_message(
                session_id,
                "assistant",
                "",
                tool_calls=[{"name": "echo", "args": {"text": "hi"}, "id": "c1"}],
                pool=pool,
            )
            await log_message(
                session_id, "tool", "echo: hi", tool_call_id="c1", pool=pool
            )
            rows = await pool.fetch(
                "SELECT seq, role, content, tool_calls FROM messages "
                "WHERE session_id = $1 ORDER BY seq",
                session_id,
            )
            assert [row["seq"] for row in rows] == [1, 2, 3]
            assert [row["role"] for row in rows] == ["user", "assistant", "tool"]
            assert json.loads(rows[1]["tool_calls"]) == [
                {"name": "echo", "args": {"text": "hi"}, "id": "c1"}
            ]
            session = await pool.fetchrow(
                "SELECT session_id FROM sessions WHERE session_id = $1", session_id
            )
            assert session is not None
        finally:
            await pool.execute("DELETE FROM sessions WHERE session_id = $1", session_id)
            await close_pool()

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
