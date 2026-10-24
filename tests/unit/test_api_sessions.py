"""Unit tests for M-20 — FastAPI /sessions endpoints (mocked pool + fake graph).

No infra: the CRUD handlers run against a FakePool (SQL contract), the
message/resume handlers against a fake graph emitting canned
``astream_events`` (the real ``run_turn``/``run_resume`` from
:mod:`app.core.agent` execute on top of it).
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage, AIMessageChunk
from langgraph.checkpoint.memory import MemorySaver

import app.api.sessions as api_sessions
import app.db.session_log as session_log
from app.core.config import clear_settings_cache

_SESSION_ROW = {
    "session_id": "s-1",
    "title": "M-20 test",
    "provider": "anthropic",
    "model": "claude-sonnet-3.5",
    "status": "active",
    "working_dir": None,
    "created_at": datetime(2026, 1, 1, tzinfo=UTC),
    "last_activity_at": datetime(2026, 1, 1, tzinfo=UTC),
    "metadata": {},
}

_MESSAGE_ROWS = [
    {
        "id": 1,
        "seq": 1,
        "role": "user",
        "content": "hello",
        "tool_calls": None,
        "tool_call_id": None,
        "created_at": datetime(2026, 1, 1, tzinfo=UTC),
    },
    {
        "id": 2,
        "seq": 2,
        "role": "assistant",
        "content": "hi!",
        "tool_calls": None,
        "tool_call_id": None,
        "created_at": datetime(2026, 1, 1, tzinfo=UTC),
    },
]


class FakePool:
    """asyncpg.Pool stand-in routing responses by SQL shape."""

    def __init__(self) -> None:
        self.executed: list[tuple[str, str, tuple]] = []
        self.session_row: dict | None = dict(_SESSION_ROW)
        self.message_rows: list[dict] = list(_MESSAGE_ROWS)
        self.total = 1
        self.fail = False

    def _check(self) -> None:
        if self.fail:
            raise OSError("connection refused")

    async def execute(self, query: str, *args: Any) -> str:
        self._check()
        self.executed.append(("execute", query, args))
        return "INSERT 0 1"

    async def fetchrow(self, query: str, *args: Any) -> dict | None:
        self._check()
        self.executed.append(("fetchrow", query, args))
        if "INSERT INTO sessions" in query and "RETURNING" in query:
            row = dict(self.session_row or _SESSION_ROW)
            row["session_id"] = args[0]
            return row
        if "SELECT * FROM sessions" in query:
            return self.session_row
        if "UPDATE sessions" in query:
            if self.session_row is None:
                return None
            row = dict(self.session_row)
            row["status"] = args[1]
            return row
        if "INSERT INTO messages" in query:
            return {"id": 42}
        return None

    async def fetch(self, query: str, *args: Any) -> list[dict]:
        self._check()
        self.executed.append(("fetch", query, args))
        if "FROM messages" in query:
            return list(self.message_rows)
        if "FROM sessions" in query:
            return [self.session_row] if self.session_row else []
        return []

    async def fetchval(self, query: str, *args: Any) -> int:
        self._check()
        self.executed.append(("fetchval", query, args))
        return self.total


def _ev(
    name: str,
    *,
    run_id: str = "run-1",
    tool: str | None = None,
    data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    event: dict[str, Any] = {"event": name, "run_id": run_id, "data": data or {}}
    if tool is not None:
        event["name"] = tool
    return event


class _FakeState:
    def __init__(
        self,
        next: tuple = (),
        values: dict[str, Any] | None = None,
        tasks: tuple = (),
    ) -> None:
        self.next = next
        self.values = values if values is not None else {"messages": []}
        self.tasks = tasks


class FakeGraph:
    """Canned astream_events + aget_state for the message/resume handlers.

    ``states`` is a sequence consumed per ``aget_state`` call (last entry
    repeats) so a resume flow can model "paused → resumed → finished".
    """

    def __init__(self, events: list[dict], states: list[_FakeState]) -> None:
        self._events = events
        self._states = states
        self._calls = 0

    async def astream_events(self, input, config=None, *, version=None):
        for event in self._events:
            yield event

    async def aget_state(self, config):
        state = self._states[min(self._calls, len(self._states) - 1)]
        self._calls += 1
        return state


def _ok_state() -> _FakeState:
    return _FakeState(next=())


def _interrupted_state(
    tool: str = "bash", args: dict | None = None, reason: str = "strict mode"
) -> _FakeState:
    return _FakeState(
        next=("human",),
        tasks=(
            SimpleNamespace(
                interrupts=(
                    SimpleNamespace(
                        value={"tool": tool, "args": args or {}, "reason": reason}
                    ),
                )
            ),
        ),
    )


def _tool_turn_events() -> list[dict]:
    return [
        _ev(
            "on_chat_model_stream",
            data={"chunk": AIMessageChunk(content="Let me check. ")},
        ),
        _ev(
            "on_tool_start",
            tool="read",
            data={"input": {"path": "app/main.py"}},
        ),
        _ev(
            "on_tool_end",
            tool="read",
            data={"output": "file contents"},
        ),
        _ev(
            "on_chat_model_stream",
            data={"chunk": AIMessageChunk(content="Done.")},
        ),
    ]


@pytest.fixture(autouse=True)
def isolated(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Sandbox env/config; clear the per-session policy cache."""
    for name in list(os.environ):
        if name.startswith("ORYA_") or name in {"DATABASE_URL", "LOG_LEVEL"}:
            monkeypatch.delenv(name, raising=False)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ORYA_CONFIG_PATH", str(tmp_path / "config.yaml"))
    monkeypatch.setenv("ORYA_SESSIONS_DIR", str(tmp_path / "sessions"))
    clear_settings_cache()
    api_sessions._session_policies.clear()
    yield
    api_sessions._session_policies.clear()
    clear_settings_cache()


@pytest.fixture
def fake_pool(monkeypatch: pytest.MonkeyPatch) -> FakePool:
    pool = FakePool()

    async def _get_pool():
        return pool

    monkeypatch.setattr(session_log, "get_asyncpg_pool", _get_pool)
    return pool


@pytest.fixture
def fake_graph(monkeypatch: pytest.MonkeyPatch):
    """Install a fake graph runtime: ok-turn by default.

    Returns a holder whose ``events``/``state`` can be replaced per test
    before the HTTP call.
    """
    holder = SimpleNamespace(
        events=_tool_turn_events(),
        states=[_ok_state()],
    )

    async def _resolve():
        return MemorySaver(), True

    def _build(thread_id, checkpointer, *, model=None, policy=None):
        return FakeGraph(holder.events, holder.states)

    monkeypatch.setattr(api_sessions, "resolve_checkpointer", _resolve)
    monkeypatch.setattr(api_sessions, "build_session_graph", _build)
    return holder


# --- router registration ---------------------------------------------------


def test_sessions_router_registered(client: TestClient) -> None:
    paths = client.get("/openapi.json").json()["paths"]
    assert "/sessions" in paths
    assert {"post", "get"} <= set(paths["/sessions"])
    assert "/sessions/{session_id}" in paths
    assert "post" in paths["/sessions/{session_id}/messages"]
    assert "post" in paths["/sessions/{session_id}/resume"]
    assert "delete" in paths["/sessions/{session_id}"]


# --- POST /sessions --------------------------------------------------------


def test_create_session_generates_id(client: TestClient, fake_pool: FakePool) -> None:
    response = client.post("/sessions", json={"title": "M-20 test"})
    assert response.status_code == 200
    data = response.json()
    # server-side uuid4 (BACKLOG5: не хардкодить thread_id — генерировать)
    assert len(data["session_id"].split("-")) == 5
    assert data["status"] == "active"
    assert "created_at" in data

    inserts = [q for kind, q, _ in fake_pool.executed if "INSERT INTO sessions" in q]
    assert inserts, "expected an INSERT INTO sessions"
    assert "RETURNING *" in inserts[0]


def test_create_session_without_body(client: TestClient, fake_pool: FakePool) -> None:
    response = client.post("/sessions")
    assert response.status_code == 200
    assert response.json()["session_id"]


def test_create_session_db_down_503(client: TestClient, fake_pool: FakePool) -> None:
    fake_pool.fail = True
    response = client.post("/sessions", json={})
    assert response.status_code == 503
    assert response.json()["detail"] == "database unavailable"


# --- GET /sessions ---------------------------------------------------------


def test_list_sessions_pagination(client: TestClient, fake_pool: FakePool) -> None:
    response = client.get("/sessions?page=2&size=5")
    assert response.status_code == 200
    data = response.json()
    assert data["page"] == 2
    assert data["size"] == 5
    assert data["total"] == 1
    assert [item["session_id"] for item in data["items"]] == ["s-1"]

    select = next(q for kind, q, _ in fake_pool.executed if "FROM sessions" in q)
    assert "ORDER BY last_activity_at DESC" in select
    assert "LIMIT $1 OFFSET $2" in select
    limit_call = next(
        args for kind, _, args in fake_pool.executed if kind == "fetch" and "LIMIT" in _
    )
    assert limit_call == (5, 5)


def test_list_sessions_caps_size(client: TestClient, fake_pool: FakePool) -> None:
    response = client.get("/sessions?size=500")
    assert response.status_code == 422  # le=100


def test_list_sessions_db_down_503(client: TestClient, fake_pool: FakePool) -> None:
    fake_pool.fail = True
    assert client.get("/sessions").status_code == 503


# --- GET /sessions/{id} ----------------------------------------------------


def test_get_session_404(client: TestClient, fake_pool: FakePool) -> None:
    fake_pool.session_row = None
    response = client.get("/sessions/nope")
    assert response.status_code == 404
    assert "nope" in response.json()["detail"]


def test_get_session_returns_metadata_and_messages(
    client: TestClient, fake_pool: FakePool
) -> None:
    response = client.get("/sessions/s-1")
    assert response.status_code == 200
    data = response.json()
    assert data["session_id"] == "s-1"
    assert data["title"] == "M-20 test"
    assert [m["seq"] for m in data["messages"]] == [1, 2]
    assert data["messages"][0]["role"] == "user"
    assert data["messages"][1]["content"] == "hi!"

    msg_query = next(q for kind, q, _ in fake_pool.executed if "FROM messages" in q)
    assert "ORDER BY seq" in msg_query


def test_get_session_db_down_503(client: TestClient, fake_pool: FakePool) -> None:
    fake_pool.fail = True
    assert client.get("/sessions/s-1").status_code == 503


# --- POST /sessions/{id}/messages ------------------------------------------


def test_post_message_ok_accumulates_turn(
    client: TestClient, fake_pool: FakePool, fake_graph
) -> None:
    response = client.post("/sessions/s-1/messages", json={"content": "read main"})
    assert response.status_code == 200
    data = response.json()
    assert data["session_id"] == "s-1"
    assert data["status"] == "ok"
    assert data["reply"] == "Let me check. Done."
    assert data["pending_interrupt"] is None
    assert data["degraded"] is True
    assert len(data["tool_steps"]) == 1
    step = data["tool_steps"][0]
    assert step["tool"] == "read"
    assert step["args"] == {"path": "app/main.py"}
    assert step["output"] == "file contents"

    logged = [
        args
        for kind, q, args in fake_pool.executed
        if kind == "fetchrow" and "INSERT INTO messages" in q
    ]
    assert [("s-1", "user", "read main", None, None)] == [
        (a[0], a[1], a[2], a[3], a[4]) for a in logged[:1]
    ]
    roles = [a[1] for a in logged]
    assert "user" in roles and "assistant" in roles


def test_post_message_interrupted_returns_pending(
    client: TestClient, fake_pool: FakePool, fake_graph
) -> None:
    fake_graph.events = [
        _ev("on_chat_model_stream", data={"chunk": AIMessageChunk(content="Running ")})
    ]
    fake_graph.states = [
        _interrupted_state(tool="bash", args={"command": "rm x"}, reason="strict mode")
    ]

    response = client.post("/sessions/s-1/messages", json={"content": "rm x"})
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "interrupted"
    assert data["reply"] == "Running "
    assert data["pending_interrupt"] == {
        "tool": "bash",
        "args": {"command": "rm x"},
        "reason": "strict mode",
    }

    logged_roles = [
        args[1]
        for kind, q, args in fake_pool.executed
        if kind == "fetchrow" and "INSERT INTO messages" in q
    ]
    assert logged_roles == ["user"]  # no assistant log on pause


def test_post_message_fallback_reply_from_checkpoint(
    client: TestClient, fake_pool: FakePool, fake_graph
) -> None:
    fake_graph.events = []  # model did not stream tokens
    fake_graph.states = [
        _FakeState(
            next=(), values={"messages": [AIMessage(content="checkpoint answer")]}
        )
    ]

    response = client.post("/sessions/s-1/messages", json={"content": "hi"})
    assert response.status_code == 200
    assert response.json()["reply"] == "checkpoint answer"
    assert response.json()["tool_steps"] == []


def test_post_message_empty_content_422(
    client: TestClient, fake_pool: FakePool
) -> None:
    assert (
        client.post("/sessions/s-1/messages", json={"content": ""}).status_code == 422
    )
    assert client.post("/sessions/s-1/messages", json={}).status_code == 422


def test_post_message_auto_creates_session_row(
    client: TestClient, fake_pool: FakePool, fake_graph
) -> None:
    response = client.post("/sessions/fresh-id/messages", json={"content": "hi"})
    assert response.status_code == 200
    ensure_queries = [
        q for kind, q, _ in fake_pool.executed if "INSERT INTO sessions" in q
    ]
    assert ensure_queries, "expected lenient ensure_session insert"
    assert "ON CONFLICT (session_id) DO NOTHING" in ensure_queries[0]


def test_post_message_db_down_503(
    client: TestClient, fake_pool: FakePool, fake_graph
) -> None:
    fake_pool.fail = True
    response = client.post("/sessions/s-1/messages", json={"content": "hi"})
    assert response.status_code == 503


# --- POST /sessions/{id}/resume --------------------------------------------


def test_resume_allow_maps_to_approve(
    client: TestClient, fake_pool: FakePool, fake_graph
) -> None:
    fake_graph.states = [
        _interrupted_state(tool="bash"),
        _interrupted_state(tool="bash"),
        _ok_state(),
    ]
    fake_graph.events = [
        _ev(
            "on_chat_model_stream",
            data={"chunk": AIMessageChunk(content="Command ran.")},
        )
    ]

    response = client.post("/sessions/s-1/resume", json={"decision": "allow"})
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["reply"] == "Command ran."

    system_logs = [
        args[2]
        for kind, q, args in fake_pool.executed
        if kind == "fetchrow" and "INSERT INTO messages" in q and args[1] == "system"
    ]
    assert system_logs and system_logs[0].startswith("permission allow: bash")


@pytest.mark.parametrize("decision", ["allow", "deny", "always"])
def test_resume_accepts_all_decisions(
    client: TestClient, fake_pool: FakePool, fake_graph, decision: str
) -> None:
    fake_graph.states = [_interrupted_state()]
    response = client.post("/sessions/s-1/resume", json={"decision": decision})
    assert response.status_code == 200


def test_resume_invalid_decision_422(client: TestClient, fake_pool: FakePool) -> None:
    response = client.post("/sessions/s-1/resume", json={"decision": "maybe"})
    assert response.status_code == 422


def test_resume_unknown_session_404(client: TestClient, fake_pool: FakePool) -> None:
    fake_pool.session_row = None
    response = client.post("/sessions/nope/resume", json={"decision": "allow"})
    assert response.status_code == 404


def test_resume_no_pending_409(
    client: TestClient, fake_pool: FakePool, fake_graph
) -> None:
    fake_graph.states = [_ok_state()]  # nothing paused
    response = client.post("/sessions/s-1/resume", json={"decision": "allow"})
    assert response.status_code == 409
    assert "no pending interrupt" in response.json()["detail"]


def test_resume_interrupted_again_reports_new_pending(
    client: TestClient, fake_pool: FakePool, fake_graph
) -> None:
    fake_graph.states = [_interrupted_state(tool="edit", args={"path": "x.py"})]
    fake_graph.events = []  # resume immediately hits the next ask
    response = client.post("/sessions/s-1/resume", json={"decision": "always"})
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "interrupted"
    assert data["pending_interrupt"]["tool"] == "edit"


# --- DELETE /sessions/{id} -------------------------------------------------


def test_delete_session_soft_deletes(client: TestClient, fake_pool: FakePool) -> None:
    response = client.delete("/sessions/s-1")
    assert response.status_code == 200
    assert response.json() == {"session_id": "s-1", "status": "closed"}

    update = next(
        args
        for kind, q, args in fake_pool.executed
        if kind == "fetchrow" and "UPDATE sessions" in q
    )
    assert update == ("s-1", "closed")


def test_delete_session_404(client: TestClient, fake_pool: FakePool) -> None:
    fake_pool.session_row = None
    assert client.delete("/sessions/nope").status_code == 404


def test_delete_session_db_down_503(client: TestClient, fake_pool: FakePool) -> None:
    fake_pool.fail = True
    assert client.delete("/sessions/s-1").status_code == 503


def test_delete_clears_cached_policy(client: TestClient, fake_pool: FakePool) -> None:
    api_sessions._session_policies["s-1"] = api_sessions.get_policy()
    assert "s-1" in api_sessions._session_policies
    client.delete("/sessions/s-1")
    assert "s-1" not in api_sessions._session_policies
