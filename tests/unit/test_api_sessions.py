"""Unit tests for M-20 — FastAPI /sessions endpoints (mocked pool + fake graph).

No infra: the CRUD handlers run against a FakePool (SQL contract), the
message/resume handlers against a fake graph emitting canned
``astream_events`` (the real ``run_turn``/``run_resume`` from
:mod:`app.core.agent` execute on top of it).
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage, AIMessageChunk, ToolMessage
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
            if "working_dir" in query:
                row["working_dir"] = args[1]
            else:
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
    before the HTTP call; ``built`` records every ``build_session_graph``
    call (thread, model, policy) for the M-24 override assertions.
    """
    holder = SimpleNamespace(
        events=_tool_turn_events(),
        states=[_ok_state()],
        built=[],
    )

    async def _resolve():
        return MemorySaver(), True

    def _build(thread_id, checkpointer, *, model=None, policy=None):
        holder.built.append({"thread_id": thread_id, "model": model, "policy": policy})
        return FakeGraph(holder.events, holder.states)

    monkeypatch.setattr(api_sessions, "resolve_checkpointer", _resolve)
    monkeypatch.setattr(api_sessions, "build_session_graph", _build)
    return holder


def _sse_frames(text: str) -> list[tuple[str, Any]]:
    """Parse an SSE body into ``(event, data)`` frames."""
    frames: list[tuple[str, Any]] = []
    event, data = "message", []
    for line in text.split("\n"):
        line = line.rstrip("\r")
        if line == "":
            if data:
                frames.append((event, json.loads("\n".join(data))))
            event, data = "message", []
            continue
        if line.startswith(":"):
            continue
        if line.startswith("event:"):
            event = line[6:].strip()
        elif line.startswith("data:"):
            data.append(line[5:].lstrip())
    if data:
        frames.append((event, json.loads("\n".join(data))))
    return frames


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
    api_sessions._policy_for("s-1")
    assert "s-1" in api_sessions._session_policies
    client.delete("/sessions/s-1")
    assert "s-1" not in api_sessions._session_policies


# --- SSE streaming (?stream=true, M-24) --------------------------------------


def test_post_message_stream_returns_event_frames(
    client: TestClient, fake_pool: FakePool, fake_graph
) -> None:
    response = client.post(
        "/sessions/s-1/messages",
        params={"stream": "true"},
        json={"content": "read main"},
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers["cache-control"] == "no-cache"
    assert response.headers["x-accel-buffering"] == "no"

    frames = _sse_frames(response.text)
    assert [kind for kind, _ in frames] == [
        "token",
        "tool_start",
        "tool_end",
        "token",
        "done",
    ]
    assert frames[0][1] == {"content": "Let me check. "}
    assert frames[2][1]["tool"] == "read"
    assert frames[2][1]["from_cache"] is False

    done = frames[-1][1]
    assert done["status"] == "ok"
    assert done["reply"] == "Let me check. Done."
    assert done["tool_steps"][0]["output"] == "file contents"
    assert done["degraded"] is True
    assert done["pending_interrupt"] is None
    assert done["session_id"] == "s-1"

    # the assistant reply is still logged (M-14) in stream mode
    roles = [
        args[1]
        for kind, q, args in fake_pool.executed
        if kind == "fetchrow" and "INSERT INTO messages" in q
    ]
    assert "user" in roles and "assistant" in roles


def test_post_message_stream_emits_interrupt_and_done(
    client: TestClient, fake_pool: FakePool, fake_graph
) -> None:
    fake_graph.events = [
        _ev("on_chat_model_stream", data={"chunk": AIMessageChunk(content="Running ")})
    ]
    fake_graph.states = [
        _interrupted_state(tool="bash", args={"command": "rm x"}, reason="strict mode")
    ]

    response = client.post(
        "/sessions/s-1/messages",
        params={"stream": "true"},
        json={"content": "rm x"},
    )

    assert response.status_code == 200
    frames = _sse_frames(response.text)
    kinds = [kind for kind, _ in frames]
    assert kinds == ["token", "interrupt", "done"]

    interrupt = next(data for kind, data in frames if kind == "interrupt")
    assert interrupt == {
        "tool": "bash",
        "args": {"command": "rm x"},
        "reason": "strict mode",
    }
    done = frames[-1][1]
    assert done["status"] == "interrupted"
    assert done["reply"] == "Running "
    assert done["pending_interrupt"]["tool"] == "bash"

    # no assistant log on pause (same rule as the JSON path)
    roles = [
        args[1]
        for kind, q, args in fake_pool.executed
        if kind == "fetchrow" and "INSERT INTO messages" in q
    ]
    assert roles == ["user"]


def test_post_message_stream_soft_fails_when_the_db_is_down(
    client: TestClient, fake_pool: FakePool, fake_graph
) -> None:
    """Stream mode keeps the UI semantics: degrade, don't abort (M-24)."""
    fake_pool.fail = True

    response = client.post(
        "/sessions/s-1/messages",
        params={"stream": "true"},
        json={"content": "hi"},
    )

    assert response.status_code == 200
    frames = _sse_frames(response.text)
    assert frames[-1][0] == "done"
    assert frames[-1][1]["status"] == "ok"
    assert frames[-1][1]["degraded"] is True


def test_post_message_stream_marks_cache_hits(
    client: TestClient, fake_pool: FakePool, fake_graph
) -> None:
    """M-21 follow-up: ``from_cache`` reaches the ``tool_end`` frame."""
    fake_graph.events = [
        _ev(
            "on_tool_start",
            tool="read",
            data={"input": {"path": "app/main.py"}},
        ),
        _ev(
            "on_tool_end",
            tool="read",
            data={
                "output": ToolMessage(
                    content="cached body",
                    tool_call_id="t1",
                    metadata={"from_cache": True},
                )
            },
        ),
    ]

    response = client.post(
        "/sessions/s-1/messages",
        params={"stream": "true"},
        json={"content": "read main"},
    )

    frames = _sse_frames(response.text)
    tool_end = next(data for kind, data in frames if kind == "tool_end")
    assert tool_end["from_cache"] is True
    assert frames[-1][1]["tool_steps"][0]["from_cache"] is True


def test_post_message_json_reports_from_cache(
    client: TestClient, fake_pool: FakePool, fake_graph
) -> None:
    fake_graph.events = [
        _ev(
            "on_tool_end",
            tool="read",
            data={
                "output": ToolMessage(
                    content="cached body",
                    tool_call_id="t1",
                    metadata={"from_cache": True},
                )
            },
        ),
    ]

    response = client.post("/sessions/s-1/messages", json={"content": "read main"})

    assert response.status_code == 200
    assert response.json()["tool_steps"][0]["from_cache"] is True


def test_post_message_stream_passes_settings_overrides(
    client: TestClient, fake_pool: FakePool, fake_graph
) -> None:
    response = client.post(
        "/sessions/s-1/messages",
        params={"stream": "true"},
        json={
            "content": "hi",
            "model": "gpt-4o",
            "permission_mode": "permissive",
            "allow_list": ["read /tmp/*"],
        },
    )

    assert response.status_code == 200
    built = fake_graph.built[-1]
    assert built["model"] == "gpt-4o"
    policy = built["policy"]
    assert policy.mode == "permissive"
    assert any(r.pattern == "read /tmp/*" for r in policy.config.allow_rules)


def test_post_message_json_passes_settings_overrides(
    client: TestClient, fake_pool: FakePool, fake_graph
) -> None:
    response = client.post(
        "/sessions/s-1/messages",
        json={"content": "hi", "model": "claude-haiku"},
    )

    assert response.status_code == 200
    assert fake_graph.built[-1]["model"] == "claude-haiku"


def test_policy_cache_reuses_and_carries_the_session_allowlist(
    client: TestClient, fake_pool: FakePool, fake_graph
) -> None:
    """M-13 session allowlist survives a settings change (M-24 cache)."""
    body = {"content": "a", "permission_mode": "strict", "allow_list": []}
    client.post("/sessions/s-1/messages", json=body)
    first = fake_graph.built[-1]["policy"]
    first.record_session_allow("bash")

    # same settings key -> the same policy instance (allowlist intact)
    client.post("/sessions/s-1/messages", json=body)
    assert fake_graph.built[-1]["policy"] is first

    # changed settings -> rebuilt, but the session allowlist carries over
    client.post(
        "/sessions/s-1/messages",
        json={
            "content": "b",
            "permission_mode": "strict",
            "allow_list": ["read /tmp/*"],
        },
    )
    second = fake_graph.built[-1]["policy"]
    assert second is not first
    assert second.session_allowed_tools() == {"bash"}
    assert second.mode == "strict"


def test_resume_stream_returns_event_frames(
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

    response = client.post(
        "/sessions/s-1/resume",
        params={"stream": "true"},
        json={"decision": "always", "permission_mode": "permissive"},
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    frames = _sse_frames(response.text)
    assert [kind for kind, _ in frames] == ["token", "done"]
    assert frames[-1][1]["status"] == "ok"
    assert frames[-1][1]["reply"] == "Command ran."

    # the permission decision is still logged (soft-fail in stream mode)
    system_logs = [
        args[2]
        for kind, q, args in fake_pool.executed
        if kind == "fetchrow" and "INSERT INTO messages" in q and args[1] == "system"
    ]
    assert system_logs and system_logs[0].startswith("permission always: bash")

    # and the resume ran under the requested mode
    assert fake_graph.built[-1]["policy"].mode == "permissive"


def test_resume_stream_without_pending_is_409(
    client: TestClient, fake_pool: FakePool, fake_graph
) -> None:
    fake_graph.states = [_ok_state()]

    response = client.post(
        "/sessions/s-1/resume",
        params={"stream": "true"},
        json={"decision": "allow"},
    )

    assert response.status_code == 409


# --- graph-build failures (config errors must not surface as 500) -----------


def test_graph_build_value_error_maps_to_400(
    client: TestClient, fake_pool: FakePool, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A missing API key is a fixable config error — 400 with the reason."""

    def _explode(*args, **kwargs):
        raise ValueError("No API key found for provider 'anthropic'.")

    monkeypatch.setattr(api_sessions, "build_session_graph", _explode)

    response = client.post("/sessions/s-1/messages", json={"content": "hi"})

    assert response.status_code == 400
    detail = response.json()["detail"]
    assert detail.startswith("configuration error:")
    assert "No API key found for provider 'anthropic'" in detail


def test_graph_build_unexpected_error_maps_to_502(
    client: TestClient, fake_pool: FakePool, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _explode(*args, **kwargs):
        raise RuntimeError("graph assembly exploded")

    monkeypatch.setattr(api_sessions, "build_session_graph", _explode)

    response = client.post("/sessions/s-1/messages", json={"content": "hi"})

    assert response.status_code == 502
    assert "graph build failed" in response.json()["detail"]


def test_resume_graph_build_value_error_maps_to_400(
    client: TestClient, fake_pool: FakePool, fake_graph, monkeypatch
) -> None:
    fake_graph.states = [_interrupted_state()]

    def _explode(*args, **kwargs):
        raise ValueError("Model alias 'nope' is not registered.")

    monkeypatch.setattr(api_sessions, "build_session_graph", _explode)

    response = client.post("/sessions/s-1/resume", json={"decision": "allow"})

    assert response.status_code == 400
    assert "configuration error" in response.json()["detail"]


# --- working_dir («open project») --------------------------------------------


def test_post_message_working_dir_opens_and_persists(
    client: TestClient, fake_pool: FakePool, fake_graph, tmp_path: Path
) -> None:
    project = tmp_path / "project"
    project.mkdir()

    response = client.post(
        "/sessions/s-1/messages",
        json={"content": "hi", "working_dir": str(project)},
    )

    assert response.status_code == 200
    updates = [
        args
        for kind, q, args in fake_pool.executed
        if kind == "fetchrow" and "UPDATE sessions" in q and "working_dir" in q
    ]
    assert updates, "expected the workspace to be persisted on the session"
    assert updates[0] == ("s-1", str(project.resolve()))


def test_post_message_missing_working_dir_is_400(
    client: TestClient, fake_pool: FakePool, fake_graph, tmp_path: Path
) -> None:
    response = client.post(
        "/sessions/s-1/messages",
        json={"content": "hi", "working_dir": str(tmp_path / "does-not-exist")},
    )

    assert response.status_code == 400
    assert "does not exist" in response.json()["detail"]


def test_post_message_streaming_missing_working_dir_is_400(
    client: TestClient, fake_pool: FakePool, fake_graph, tmp_path: Path
) -> None:
    """The workspace is validated before the SSE stream starts."""
    response = client.post(
        "/sessions/s-1/messages",
        params={"stream": "true"},
        json={"content": "hi", "working_dir": str(tmp_path / "gone")},
    )

    assert response.status_code == 400


def test_post_message_uses_the_stored_workspace(
    client: TestClient, fake_pool: FakePool, fake_graph, tmp_path: Path
) -> None:
    """A turn without a working_dir override reuses the session's project."""
    project = tmp_path / "stored-project"
    project.mkdir()
    fake_pool.session_row["working_dir"] = str(project)

    response = client.post("/sessions/s-1/messages", json={"content": "hi"})

    assert response.status_code == 200
    # no override -> nothing to persist, the stored value is kept
    updates = [
        args
        for kind, q, args in fake_pool.executed
        if kind == "fetchrow" and "UPDATE sessions" in q and "working_dir" in q
    ]
    assert updates == []


def test_post_message_workspace_is_scoped_to_the_turn(
    client: TestClient,
    fake_pool: FakePool,
    fake_graph,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The ContextVar is bound while the run executes and cleared after."""
    from app.core.workspace import current_workspace

    project = tmp_path / "scoped"
    project.mkdir()
    seen: list[Path] = []

    async def _astream_events(input, config=None, *, version=None):
        seen.append(current_workspace())
        yield _ev("on_chat_model_stream", data={"chunk": AIMessageChunk(content="ok")})

    def _build(thread_id, checkpointer, *, model=None, policy=None):
        graph = FakeGraph([], [_ok_state()])
        graph.astream_events = _astream_events  # type: ignore[method-assign]
        return graph

    monkeypatch.setattr(api_sessions, "build_session_graph", _build)

    response = client.post(
        "/sessions/s-1/messages",
        json={"content": "hi", "working_dir": str(project)},
    )

    assert response.status_code == 200
    assert seen == [project.resolve()]
    assert current_workspace() == Path.cwd()  # released after the turn


# --- PATCH /sessions/{id} («open project») -----------------------------------


def test_patch_session_opens_and_persists_working_dir(
    client: TestClient, fake_pool: FakePool, tmp_path: Path
) -> None:
    project = tmp_path / "patched"
    project.mkdir()

    response = client.patch("/sessions/s-1", json={"working_dir": str(project)})

    assert response.status_code == 200
    assert response.json()["working_dir"] == str(project.resolve())
    updates = [
        args
        for kind, q, args in fake_pool.executed
        if kind == "fetchrow" and "UPDATE sessions" in q and "working_dir" in q
    ]
    assert updates == [("s-1", str(project.resolve()))]


def test_patch_session_missing_dir_is_400(
    client: TestClient, fake_pool: FakePool, tmp_path: Path
) -> None:
    response = client.patch(
        "/sessions/s-1", json={"working_dir": str(tmp_path / "gone")}
    )

    assert response.status_code == 400
    assert "does not exist" in response.json()["detail"]
    # nothing was written
    assert not any(
        "working_dir" in q for kind, q, _ in fake_pool.executed if kind == "fetchrow"
    )


def test_patch_session_closes_the_project_with_null(
    client: TestClient, fake_pool: FakePool, tmp_path: Path
) -> None:
    project = tmp_path / "was-open"
    project.mkdir()
    fake_pool.session_row["working_dir"] = str(project)

    response = client.patch("/sessions/s-1", json={"working_dir": None})

    assert response.status_code == 200
    assert response.json()["working_dir"] is None
    updates = [
        args
        for kind, q, args in fake_pool.executed
        if kind == "fetchrow" and "UPDATE sessions" in q and "working_dir" in q
    ]
    assert updates == [("s-1", None)]


def test_patch_session_unknown_is_404(
    client: TestClient, fake_pool: FakePool, tmp_path: Path
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    fake_pool.session_row = None

    response = client.patch("/sessions/nope", json={"working_dir": str(project)})

    assert response.status_code == 404


def test_patch_session_db_down_is_503(
    client: TestClient, fake_pool: FakePool, tmp_path: Path
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    fake_pool.fail = True

    response = client.patch("/sessions/s-1", json={"working_dir": str(project)})

    assert response.status_code == 503
