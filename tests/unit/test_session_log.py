"""Unit tests for M-14 — session log + JSONL projection (mocked pools/savers)."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import asyncpg
import pytest
from langchain_core.messages import (
    AIMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)

import app.db.session_log as session_log
from app.core.config import clear_settings_cache
from app.db.session_log import (
    discover_thread_ids,
    ensure_session,
    log_message,
    project_thread,
    projection_worker,
    session_jsonl_path,
)

# --- fakes -----------------------------------------------------------------


class FakePool:
    """Minimal asyncpg.Pool stand-in recording executed SQL."""

    def __init__(self, returning_id: int = 42):
        self.executed: list[tuple[str, tuple]] = []
        self.returning_id = returning_id

    async def execute(self, query: str, *args: Any) -> str:
        self.executed.append((query, args))
        return "INSERT 0 1"

    async def fetch(self, query: str, *args: Any) -> list[dict]:
        self.executed.append((query, args))
        return getattr(self, "fetch_rows", [])

    async def fetchrow(self, query: str, *args: Any) -> dict:
        self.executed.append((query, args))
        return {"id": self.returning_id}


class FakeSaver:
    """AsyncPostgresSaver stand-in yielding CheckpointTuple-like objects.

    ``alist`` yields newest-first (matching the real saver's ordering).
    """

    def __init__(self, snapshots: list[dict]):
        # snapshots: [{"ts": ..., "messages": [BaseMessage, ...]}, ...]
        self._snapshots = snapshots

    async def alist(self, config: dict):
        for snap in reversed(self._snapshots):
            yield SimpleNamespace(
                checkpoint={
                    "ts": snap["ts"],
                    "channel_values": {"messages": snap["messages"]},
                },
                metadata={},
                config=config,
            )


@pytest.fixture(autouse=True)
def isolated(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Sandbox env/config and point sessions_dir at a temp directory."""
    for name in list(os.environ):
        if name.startswith("ORYA_") or name in {"DATABASE_URL", "LOG_LEVEL"}:
            monkeypatch.delenv(name, raising=False)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ORYA_CONFIG_PATH", str(tmp_path / "config.yaml"))
    monkeypatch.setenv("ORYA_SESSIONS_DIR", str(tmp_path / "sessions"))
    clear_settings_cache()
    yield
    clear_settings_cache()


# --- log_message / ensure_session (mocked pool) ----------------------------


async def test_ensure_session_inserts_parent_row():
    pool = FakePool()
    await ensure_session("s1", title="t", provider="anthropic", model="m", pool=pool)
    query, args = pool.executed[0]
    assert "INSERT INTO sessions" in query
    assert "ON CONFLICT (session_id) DO NOTHING" in query
    assert args == ("s1", "t", "anthropic", "m", None)


async def test_log_message_uses_auto_seq_and_returns_id():
    pool = FakePool(returning_id=7)
    message_id = await log_message("s1", "user", "hello", pool=pool)
    assert message_id == 7
    ensure_query, _ = pool.executed[0]
    assert "INSERT INTO sessions" in ensure_query
    insert_query, args = pool.executed[1]
    assert "INSERT INTO messages" in insert_query
    assert "COALESCE(MAX(seq), 0) + 1" in insert_query
    assert args == ("s1", "user", "hello", None, None)


async def test_log_message_serializes_tool_calls_and_links_call_id():
    pool = FakePool()
    calls = [{"name": "read", "args": {"path": "a.py"}, "id": "c1"}]
    await log_message("s1", "assistant", "", tool_calls=calls, pool=pool)
    _, args = pool.executed[1]
    assert json.loads(args[3]) == calls


async def test_log_message_rejects_invalid_role():
    pool = FakePool()
    with pytest.raises(ValueError, match="invalid role"):
        await log_message("s1", "narrator", "hi", pool=pool)
    assert pool.executed == []


# --- discover_thread_ids ----------------------------------------------------


async def test_discover_thread_ids_returns_rows():
    pool = FakePool()
    pool.fetch_rows = [{"thread_id": "a"}, {"thread_id": "b"}]  # type: ignore[attr-defined]
    assert await discover_thread_ids(pool=pool) == ["a", "b"]
    assert "FROM checkpoints" in pool.executed[0][0]


async def test_discover_thread_ids_missing_table_is_empty(monkeypatch):
    class TableMissingPool:
        async def fetch(self, query: str, *args: Any) -> list[dict]:
            raise asyncpg.UndefinedTableError('relation "checkpoints" does not exist')

    assert await discover_thread_ids(pool=TableMissingPool()) == []  # type: ignore[arg-type]


# --- JSONL projection -------------------------------------------------------


def _run_tool_turn_snapshots() -> list[dict]:
    """Four snapshots: user, ai(tool_call), tool result, final ai."""
    m_user = HumanMessage(content="hi", id="m1")
    m_ai_call = AIMessage(
        content="",
        id="m2",
        tool_calls=[{"name": "echo", "args": {"text": "hi"}, "id": "call_1"}],
    )
    m_tool = ToolMessage(content="echo: hi", tool_call_id="call_1", id="m3")
    m_ai_final = AIMessage(content="done", id="m4")
    return [
        {"ts": "2026-01-01T00:00:00+00:00", "messages": [m_user]},
        {"ts": "2026-01-01T00:00:01+00:00", "messages": [m_user, m_ai_call]},
        {"ts": "2026-01-01T00:00:02+00:00", "messages": [m_user, m_ai_call, m_tool]},
        {
            "ts": "2026-01-01T00:00:03+00:00",
            "messages": [m_user, m_ai_call, m_tool, m_ai_final],
        },
    ]


def _read_events(session_id: str) -> list[dict]:
    path = session_jsonl_path(session_id)
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


async def test_projection_emits_user_ai_tool_events():
    saver = FakeSaver(_run_tool_turn_snapshots())
    appended = await project_thread("s1", checkpointer=saver)
    assert appended >= 3
    events = _read_events("s1")
    types = [e["type"] for e in events]
    assert types == ["user", "ai", "tool", "ai"]
    assert all({"ts", "type", "payload"} <= set(e) for e in events)
    assert events[0]["payload"]["message_id"] == "m1"
    assert events[1]["payload"]["tool_calls"][0]["name"] == "echo"
    assert events[2]["payload"]["tool_call_id"] == "call_1"


async def test_projection_writes_meta_with_last_ts():
    saver = FakeSaver(_run_tool_turn_snapshots())
    await project_thread("s1", checkpointer=saver)
    meta = json.loads(
        (session_jsonl_path("s1").parent / "s1.meta.json").read_text(encoding="utf-8")
    )
    assert meta == {"last_processed_ts": "2026-01-01T00:00:03+00:00"}


async def test_projection_rerun_is_idempotent():
    snapshots = _run_tool_turn_snapshots()
    saver = FakeSaver(snapshots)
    first = await project_thread("s1", checkpointer=saver)
    second = await project_thread("s1", checkpointer=saver)
    assert first == 4
    assert second == 0
    assert len(_read_events("s1")) == 4


async def test_projection_appends_only_new_messages():
    snapshots = _run_tool_turn_snapshots()
    await project_thread("s1", checkpointer=FakeSaver(snapshots))
    before = len(_read_events("s1"))

    m_extra = SystemMessage(content="later", id="m5")
    snapshots.append(
        {
            "ts": "2026-01-01T00:00:04+00:00",
            "messages": [*snapshots[-1]["messages"], m_extra],
        }
    )
    appended = await project_thread("s1", checkpointer=FakeSaver(snapshots))
    assert appended == 1
    events = _read_events("s1")
    assert len(events) == before + 1
    assert events[-1]["type"] == "system"
    assert events[-1]["payload"]["message_id"] == "m5"


async def test_projection_empty_history_is_noop(tmp_path: Path):
    appended = await project_thread("s1", checkpointer=FakeSaver([]))
    assert appended == 0
    assert not session_jsonl_path("s1").exists()


async def test_projection_corrupt_meta_reprojects_from_scratch():
    snapshots = _run_tool_turn_snapshots()
    await project_thread("s1", checkpointer=FakeSaver(snapshots))
    meta_path = session_jsonl_path("s1").parent / "s1.meta.json"
    meta_path.write_text("{not json", encoding="utf-8")

    # Corrupt meta -> treated as first run: full history re-emitted (append-only).
    appended = await project_thread("s1", checkpointer=FakeSaver(snapshots))
    assert appended == 4


async def test_session_jsonl_path_uses_configured_dir():
    assert session_jsonl_path("abc").name == "abc.jsonl"
    assert session_jsonl_path("abc").parent == Path(os.environ["ORYA_SESSIONS_DIR"])


# --- projection worker ------------------------------------------------------


async def test_projection_worker_runs_pass_then_stops(monkeypatch):
    passes: list[int] = []

    async def fake_pass() -> int:
        passes.append(1)
        return 0

    monkeypatch.setattr(session_log, "projection_pass", fake_pass)
    stop = asyncio.Event()
    stop.set()
    await projection_worker(stop=stop, interval_s=0.01)
    assert passes == [1]
    # Worker creates the sessions directory on start.
    assert Path(os.environ["ORYA_SESSIONS_DIR"]).is_dir()


async def test_projection_worker_survives_pass_failure(monkeypatch):
    calls: list[int] = []

    async def flaky_pass() -> int:
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("db down")
        return 0

    monkeypatch.setattr(session_log, "projection_pass", flaky_pass)
    stop = asyncio.Event()

    async def set_stop_soon() -> None:
        await asyncio.sleep(0.05)
        stop.set()

    setter = asyncio.create_task(set_stop_soon())
    await projection_worker(stop=stop, interval_s=0.01)
    await setter
    assert len(calls) >= 2  # first pass failed, later pass(s) still ran
