"""Unit tests for M-15/M-24 — app.ui.chainlit_app (SSE client, no graph).

Chainlit no longer touches the graph: these tests cover the HTTP half of
the UI — the SSE parser, the event → ``cl.Message``/``cl.Step`` renderer,
the settings overrides shipped with every request and the handlers driven
against an ``httpx.MockTransport`` (no server, no Chainlit websocket, no
Postgres). The runtime they call lives in ``app.core.agent`` and is
covered by ``test_agent_runtime.py``.
"""

from __future__ import annotations

import json
import os
from collections.abc import AsyncIterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest

from app.core.config import clear_settings_cache
from app.ui import chainlit_app as ui

# --- sandbox -----------------------------------------------------------------


@pytest.fixture(autouse=True)
def isolated(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """No inherited env, no repo .env, temp config + settings files."""
    for name in list(os.environ):
        if name.startswith("ORYA_") or name in {"DATABASE_URL", "LOG_LEVEL"}:
            monkeypatch.delenv(name, raising=False)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ORYA_CONFIG_PATH", str(tmp_path / "config.yaml"))
    monkeypatch.setenv("ORYA_UI_SETTINGS_PATH", str(tmp_path / "settings.json"))
    clear_settings_cache()
    yield
    clear_settings_cache()


class _SessionStore:
    """Stand-in for ``cl.user_session`` (a plain dict of values)."""

    def __init__(self) -> None:
        self.data: dict[str, Any] = {}

    def set(self, key: str, value: Any) -> None:
        self.data[key] = value

    def get(self, key: str, default: Any = None) -> Any:
        return self.data.get(key, default)


class _FakeMessage:
    def __init__(self, content: str = "", actions: Any = None) -> None:
        self.content = content
        self.actions = actions or []
        self.tokens: list[str] = []
        self.sent = 0

    async def stream_token(self, token: str) -> None:
        self.tokens.append(token)
        self.content += token

    async def send(self) -> None:
        self.sent += 1


class _FakeCl:
    """Minimal Chainlit namespace: messages, session store, panels."""

    def __init__(self) -> None:
        self.user_session = _SessionStore()
        self.messages: list[_FakeMessage] = []
        self.panels: list[Any] = []

    def Message(self, content: str = "", **kwargs: Any) -> _FakeMessage:  # noqa: N802
        message = _FakeMessage(content, actions=kwargs.get("actions"))
        self.messages.append(message)
        return message

    def ChatSettings(self, inputs: Any = None, **_: Any) -> Any:  # noqa: N802
        panel = SimpleNamespace(inputs=inputs or [], elements=inputs or [])

        async def _send() -> None:
            self.panels.append(panel)

        panel.send = _send
        return panel

    def Action(self, **kwargs: Any) -> Any:  # noqa: N802
        return SimpleNamespace(**kwargs)

    def Step(self, **kwargs: Any) -> Any:  # noqa: N802
        raise AssertionError("cl.Step must not be reached in unit tests")


@pytest.fixture
def fake_cl(monkeypatch: pytest.MonkeyPatch) -> _FakeCl:
    fake = _FakeCl()
    monkeypatch.setattr(ui, "cl", fake)
    return fake


# --- SSE parser ---------------------------------------------------------------


async def _lines(text: str) -> AsyncIterator[str]:
    for line in text.split("\n"):
        yield line


async def _collect(text: str) -> list[tuple[str, Any]]:
    return [frame async for frame in ui.iter_sse(_lines(text))]


def _sse(*frames: tuple[str, Any]) -> str:
    return "".join(
        f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
        for event, data in frames
    )


async def test_iter_sse_parses_frames_in_order() -> None:
    text = _sse(
        ("token", {"content": "Hel"}),
        ("token", {"content": "lo"}),
        ("done", {"status": "ok"}),
    )

    frames = await _collect(text)

    assert [kind for kind, _ in frames] == ["token", "token", "done"]
    assert frames[0][1] == {"content": "Hel"}
    assert frames[2][1] == {"status": "ok"}


async def test_iter_sse_handles_comments_multiline_and_no_space() -> None:
    text = (
        ": keep-alive\n"
        "\n"
        "event: token\n"
        'data:{"content": "a\\nb"}\n'
        "\n"
        "event: done\n"
        'data: {"status":\n'
        'data: "ok"}\n'
        "\n"
    )

    frames = await _collect(text)

    assert frames == [
        ("token", {"content": "a\nb"}),
        ("done", {"status": "ok"}),
    ]


async def test_iter_sse_defaults_to_message_and_keeps_raw_text() -> None:
    text = "data: plain text\n\n"

    assert await _collect(text) == [("message", "plain text")]


async def test_iter_sse_yields_the_last_frame_without_trailing_blank_line() -> None:
    text = 'event: done\ndata: {"status": "ok"}'

    assert await _collect(text) == [("done", {"status": "ok"})]


async def test_iter_sse_ignores_field_lines_without_a_colon() -> None:
    text = "garbage\nevent: done\ndata: {}\n\n"

    assert await _collect(text) == [("done", {})]


# --- settings payload ----------------------------------------------------------


def test_settings_payload_ships_panel_overrides() -> None:
    settings = ui.UISettings(
        model="gpt-4o",
        permission_mode="permissive",
        allow_list=["read /tmp/*", "write *.py"],
        working_dir="C:/projects/OryaAgent",
    )

    payload = ui.settings_payload(settings)

    assert payload == {
        "model": "gpt-4o",
        "permission_mode": "permissive",
        "allow_list": ["read /tmp/*", "write *.py"],
        "working_dir": "C:/projects/OryaAgent",
    }


def test_api_url_reads_the_config(monkeypatch: pytest.MonkeyPatch) -> None:
    assert ui.api_url() == "http://127.0.0.1:8000"
    monkeypatch.setenv("ORYA_API_URL", "http://api.internal:9000/")
    clear_settings_cache()
    # trailing slash is stripped so paths join cleanly
    assert ui.api_url() == "http://api.internal:9000"


# --- rendering ------------------------------------------------------------------


class _FakeReply:
    def __init__(self) -> None:
        self.tokens: list[str] = []
        self.content = ""

    async def stream_token(self, content: str) -> None:
        self.tokens.append(content)
        self.content += content


class _FakeStep:
    def __init__(self, name: str = "tool") -> None:
        self.name = name
        self.type = "tool"
        self.input: Any = None
        self.output: Any = None
        self.updated = 0

    async def update(self) -> None:
        self.updated += 1


async def test_render_events_streams_tokens_and_manages_steps(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created: list[_FakeStep] = []

    async def fake_start(data: dict[str, Any]) -> _FakeStep:
        step = _FakeStep(name=str(data.get("tool")))
        created.append(step)
        return step

    async def fake_end(steps: dict[str, Any], data: dict[str, Any]) -> None:
        step = steps.pop(str(data.get("run_id")), None)
        assert step is not None
        step.output = data.get("output")

    monkeypatch.setattr(ui, "_start_step", fake_start)
    monkeypatch.setattr(ui, "_end_step", fake_end)

    text = _sse(
        ("token", {"content": "Let me "}),
        ("tool_start", {"run_id": "r1", "tool": "bash", "args": {"command": "ls"}}),
        ("tool_end", {"run_id": "r1", "tool": "bash", "output": "ok"}),
        ("token", {"content": "check."}),
        ("done", {"status": "ok", "reply": "Let me check.", "tool_steps": []}),
    )
    reply = _FakeReply()
    steps: dict[str, Any] = {}

    done, pending, error = await ui._render_events(reply, steps, _lines(text))

    assert reply.tokens == ["Let me ", "check."]
    assert [s.name for s in created] == ["bash"]
    assert steps == {}
    assert done["status"] == "ok"
    assert pending is None
    assert error == ""


async def test_render_events_falls_back_to_done_reply() -> None:
    text = _sse(("done", {"status": "ok", "reply": "no tokens"}))
    reply = _FakeReply()

    done, _, error = await ui._render_events(reply, {}, _lines(text))

    assert reply.tokens == ["no tokens"]
    assert done["status"] == "ok"
    assert error == ""


async def test_render_events_captures_the_interrupt_frame() -> None:
    text = _sse(
        (
            "interrupt",
            {"tool": "bash", "args": {"command": "rm x"}, "reason": "strict"},
        ),
        ("done", {"status": "interrupted", "reply": "", "tool_steps": []}),
    )
    reply = _FakeReply()

    done, pending, error = await ui._render_events(reply, {}, _lines(text))

    assert done["status"] == "interrupted"
    assert pending is not None
    assert pending.tool == "bash"
    assert pending.args == {"command": "rm x"}
    assert pending.reason == "strict"
    assert error == ""


async def test_render_events_takes_pending_from_done_when_interrupt_is_missing() -> (
    None
):
    text = _sse(
        ("done", {"status": "interrupted", "reply": "", "pending_interrupt": None})
    )
    reply = _FakeReply()

    _, pending, error = await ui._render_events(reply, {}, _lines(text))

    # unreadable payload: the handler shows the hint instead of asking
    assert pending is None
    assert error == ""


async def test_render_events_reports_error_frames() -> None:
    text = _sse(("error", {"detail": "boom"}))
    reply = _FakeReply()

    done, _, error = await ui._render_events(reply, {}, _lines(text))

    assert done == {}
    assert error == "boom"


async def test_render_events_flags_a_missing_done() -> None:
    text = _sse(("token", {"content": "half"}))
    reply = _FakeReply()

    done, _, error = await ui._render_events(reply, {}, _lines(text))

    assert done == {}
    assert "without a done event" in error


async def test_end_step_marks_cache_hits() -> None:
    """M-21 AC: a ``tool_end`` with ``from_cache`` tags the step card."""
    step = _FakeStep(name="read")
    steps = {"r1": step}

    await ui._end_step(
        steps,
        {"run_id": "r1", "tool": "read", "output": "cached body", "from_cache": True},
    )

    assert steps == {}
    assert step.name == "read (cached)"
    assert step.output == "cached body"
    assert step.updated == 1


def test_pending_from_requires_a_tool_name() -> None:
    assert ui._pending_from({"tool": ""}) is None
    assert ui._pending_from(None) is None
    assert ui._pending_from("nope") is None
    pending = ui._pending_from({"tool": "edit", "args": {"path": "x"}})
    assert pending is not None and pending.tool == "edit"


# --- handlers over httpx.MockTransport ------------------------------------------


def _transport(handler: Any) -> httpx.MockTransport:
    return httpx.MockTransport(handler)


def _client_for(handler: Any) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=_transport(handler), base_url="http://test")


@pytest.fixture
def patch_client(monkeypatch: pytest.MonkeyPatch):
    """Replace the UI's client factory; feed a MockTransport handler."""

    def install(handler: Any) -> list[httpx.Request]:
        requests: list[httpx.Request] = []

        def recording(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            return handler(request)

        def factory() -> httpx.AsyncClient:
            return httpx.AsyncClient(
                transport=_transport(recording), base_url="http://test"
            )

        monkeypatch.setattr(ui, "make_client", factory)
        return requests

    return install


def _patch_panels(monkeypatch: pytest.MonkeyPatch) -> list[Any]:
    calls: list[Any] = []

    async def sidebar() -> None:
        calls.append("sidebar")

    async def panel(settings: Any) -> None:
        calls.append(("panel", settings))

    monkeypatch.setattr(ui, "_show_sidebar", sidebar)
    monkeypatch.setattr(ui, "_show_settings_panel", panel)
    return calls


def test_handlers_registered() -> None:
    assert callable(ui.on_chat_start)
    assert callable(ui.on_message)
    assert callable(ui.on_settings_update)
    assert callable(ui.on_new_session)
    assert callable(ui.on_switch_session)


async def test_on_chat_start_creates_session_via_api(
    fake_cl: _FakeCl, monkeypatch: pytest.MonkeyPatch, patch_client
) -> None:
    calls = _patch_panels(monkeypatch)
    patch_client(
        lambda request: httpx.Response(
            200, json={"session_id": "sess-1", "status": "active"}
        )
    )

    await ui.on_chat_start()

    assert fake_cl.user_session.get("thread_id") == "sess-1"
    assert calls == ["sidebar", ("panel", ui.UISettings.default())]
    assert fake_cl.messages == []


async def test_on_chat_start_warns_when_the_database_is_down(
    fake_cl: _FakeCl, monkeypatch: pytest.MonkeyPatch, patch_client
) -> None:
    _patch_panels(monkeypatch)
    patch_client(lambda request: httpx.Response(503, json={"detail": "down"}))

    await ui.on_chat_start()

    thread_id = fake_cl.user_session.get("thread_id")
    assert thread_id and len(thread_id.split("-")) == 5  # local uuid fallback
    assert "PostgreSQL is unavailable" in fake_cl.messages[0].content


async def test_on_chat_start_fails_closed_without_the_api(
    fake_cl: _FakeCl, monkeypatch: pytest.MonkeyPatch, patch_client
) -> None:
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    patch_client(refuse)

    await ui.on_chat_start()

    assert fake_cl.user_session.get("thread_id") is None
    assert "FastAPI server unreachable" in fake_cl.messages[0].content
    assert "make dev" in fake_cl.messages[0].content


async def test_on_message_streams_a_turn_over_sse(
    fake_cl: _FakeCl, monkeypatch: pytest.MonkeyPatch, patch_client
) -> None:
    fake_cl.user_session.set("thread_id", "sess-1")
    requests = patch_client(
        lambda request: httpx.Response(
            200,
            content=_sse(
                ("token", {"content": "Hel"}),
                ("tool_start", {"run_id": "r1", "tool": "read", "args": {"path": "a"}}),
                (
                    "tool_end",
                    {
                        "run_id": "r1",
                        "tool": "read",
                        "output": "body",
                        "from_cache": True,
                    },
                ),
                ("token", {"content": "lo"}),
                (
                    "done",
                    {
                        "status": "ok",
                        "reply": "Hello",
                        "tool_steps": [],
                        "pending_interrupt": None,
                        "degraded": True,
                    },
                ),
            ).encode(),
        )
    )
    started: list[dict[str, Any]] = []
    ended: list[dict[str, Any]] = []

    async def fake_start(data: dict[str, Any]) -> _FakeStep:
        started.append(data)
        return _FakeStep(name=str(data.get("tool")))

    async def fake_end(steps: dict[str, Any], data: dict[str, Any]) -> None:
        steps.pop(str(data.get("run_id")), None)
        ended.append(data)

    monkeypatch.setattr(ui, "_start_step", fake_start)
    monkeypatch.setattr(ui, "_end_step", fake_end)

    await ui.on_message(ui.cl.Message(content="hello"))  # type: ignore[arg-type]

    assert len(requests) == 1
    request = requests[0]
    assert request.url.path == "/sessions/sess-1/messages"
    assert b"stream=true" in request.url.query
    body = json.loads(request.content)
    assert body["content"] == "hello"
    assert {"model", "permission_mode", "allow_list"} <= set(body)

    assert started and started[0]["tool"] == "read"
    assert ended and ended[0]["from_cache"] is True
    final = fake_cl.messages[-1]
    assert final.tokens == ["Hel", "lo"]
    assert final.sent == 1


async def test_on_message_asks_and_resumes_on_interrupt(
    fake_cl: _FakeCl, monkeypatch: pytest.MonkeyPatch, patch_client
) -> None:
    fake_cl.user_session.set("thread_id", "sess-1")
    interrupted = _sse(
        ("token", {"content": "Running "}),
        (
            "interrupt",
            {"tool": "bash", "args": {"command": "rm x"}, "reason": "strict"},
        ),
        (
            "done",
            {"status": "interrupted", "reply": "Running ", "pending_interrupt": None},
        ),
    )
    resumed = _sse(
        ("token", {"content": "done"}),
        ("done", {"status": "ok", "reply": "done", "pending_interrupt": None}),
    )
    requests = patch_client(
        lambda request: httpx.Response(
            200,
            content=interrupted.encode()
            if request.url.path.endswith("/messages")
            else resumed.encode(),
        )
    )

    answers: list[str] = []

    async def fake_ask(pending, **kwargs):
        answers.append(pending.tool)
        return "approve"

    monkeypatch.setattr(ui, "ask_permission", fake_ask)
    monkeypatch.setattr(ui, "_start_step", _no_step)
    monkeypatch.setattr(ui, "_end_step", _no_step_end)

    await ui.on_message(ui.cl.Message(content="rm x"))  # type: ignore[arg-type]

    assert answers == ["bash"]
    assert len(requests) == 2
    resume = requests[1]
    assert resume.url.path == "/sessions/sess-1/resume"
    assert b"stream=true" in resume.url.query
    assert json.loads(resume.content)["decision"] == "allow"
    # both passes rendered into the same reply
    final = fake_cl.messages[-1]
    assert final.tokens == ["Running ", "done"]


async def _no_step(data: dict[str, Any]) -> _FakeStep:
    return _FakeStep(name=str(data.get("tool")))


async def _no_step_end(steps: dict[str, Any], data: dict[str, Any]) -> None:
    steps.pop(str(data.get("run_id")), None)


async def test_on_message_shows_the_hint_when_the_payload_is_unreadable(
    fake_cl: _FakeCl, monkeypatch: pytest.MonkeyPatch, patch_client
) -> None:
    fake_cl.user_session.set("thread_id", "sess-1")
    patch_client(
        lambda request: httpx.Response(
            200,
            content=_sse(
                (
                    "done",
                    {"status": "interrupted", "reply": "", "pending_interrupt": None},
                )
            ).encode(),
        )
    )

    await ui.on_message(ui.cl.Message(content="go"))  # type: ignore[arg-type]

    assert any("permission gate" in m.content for m in fake_cl.messages)


async def test_on_message_reports_server_errors(fake_cl: _FakeCl, patch_client) -> None:
    fake_cl.user_session.set("thread_id", "sess-1")
    patch_client(lambda request: httpx.Response(500, json={"detail": "boom"}))

    await ui.on_message(ui.cl.Message(content="go"))  # type: ignore[arg-type]

    assert fake_cl.messages[-1].content.startswith("Run failed: 500")


async def test_on_message_reports_an_unreachable_api(
    fake_cl: _FakeCl, patch_client
) -> None:
    fake_cl.user_session.set("thread_id", "sess-1")

    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    patch_client(refuse)

    await ui.on_message(ui.cl.Message(content="go"))  # type: ignore[arg-type]

    assert "FastAPI server unreachable" in fake_cl.messages[-1].content


async def test_on_message_without_a_session_explains(
    fake_cl: _FakeCl, patch_client
) -> None:
    requests = patch_client(lambda request: httpx.Response(200, json={}))

    await ui.on_message(ui.cl.Message(content="go"))  # type: ignore[arg-type]

    assert requests == []
    assert "No active session" in fake_cl.messages[-1].content


async def test_on_message_ignores_blank_input(fake_cl: _FakeCl, patch_client) -> None:
    fake_cl.user_session.set("thread_id", "sess-1")
    requests = patch_client(lambda request: httpx.Response(200, json={}))

    await ui.on_message(ui.cl.Message(content="   "))  # type: ignore[arg-type]

    assert requests == []
    # only the (empty) input message exists ? no reply was even created
    assert len(fake_cl.messages) == 1


# --- /learn slash-command (M-26) ----------------------------------------------


def test_learn_args_parses_name_and_quoted_description() -> None:
    assert ui._learn_args('/learn refactor_extract "Refactor: extract function"') == {
        "pattern_name": "refactor_extract",
        "description": "Refactor: extract function",
    }
    assert ui._learn_args("/learn") == {}
    assert ui._learn_args("/learn remember_rg") == {"pattern_name": "remember_rg"}
    # unbalanced quotes fall back to a plain split instead of raising
    assert ui._learn_args('/learn "oops') == {"pattern_name": '"oops'}


async def test_on_message_learn_captures_and_reports(
    fake_cl: _FakeCl, patch_client
) -> None:
    fake_cl.user_session.set("thread_id", "sess-1")
    requests = patch_client(
        lambda request: httpx.Response(
            200,
            json={
                "status": "ok",
                "learned_id": "learn_001",
                "file": "LEARNED.md",
                "compacted": False,
                "line_count": 4,
            },
        )
    )

    await ui.on_message(
        ui.cl.Message(  # type: ignore[arg-type]
            content='/learn refactor_extract "Refactor: extract function"'
        )
    )

    assert len(requests) == 1  # a memory write, never a chat turn
    assert requests[0].url.path == "/sessions/sess-1/learn"
    assert json.loads(requests[0].content) == {
        "pattern_name": "refactor_extract",
        "description": "Refactor: extract function",
    }
    assert (
        fake_cl.messages[-1].content
        == "✅ Learned: `learn_001` → LEARNED.md (compacted: false)"
    )


async def test_on_message_learn_without_args_sends_an_empty_body(
    fake_cl: _FakeCl, patch_client
) -> None:
    fake_cl.user_session.set("thread_id", "sess-1")
    requests = patch_client(
        lambda request: httpx.Response(
            200,
            json={
                "learned_id": "learn_001",
                "file": "LEARNED.md",
                "compacted": True,
                "line_count": 9,
            },
        )
    )

    await ui.on_message(ui.cl.Message(content="/learn"))  # type: ignore[arg-type]

    assert len(requests) == 1
    assert json.loads(requests[0].content) == {}
    assert "(compacted: true)" in fake_cl.messages[-1].content


async def test_on_message_learn_shows_the_400_detail(
    fake_cl: _FakeCl, patch_client
) -> None:
    fake_cl.user_session.set("thread_id", "sess-1")
    requests = patch_client(
        lambda request: httpx.Response(
            400, json={"detail": "No successful tool-call sequence to learn"}
        )
    )

    await ui.on_message(ui.cl.Message(content="/learn"))  # type: ignore[arg-type]

    assert len(requests) == 1
    assert fake_cl.messages[-1].content.startswith("/learn failed:")
    assert "No successful tool-call sequence to learn" in (fake_cl.messages[-1].content)


async def test_on_message_learn_reports_an_unreachable_api(
    fake_cl: _FakeCl, patch_client
) -> None:
    fake_cl.user_session.set("thread_id", "sess-1")

    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    patch_client(refuse)

    await ui.on_message(ui.cl.Message(content="/learn"))  # type: ignore[arg-type]

    assert "FastAPI server unreachable" in fake_cl.messages[-1].content


async def test_on_message_learn_without_a_session_explains(
    fake_cl: _FakeCl, patch_client
) -> None:
    requests = patch_client(lambda request: httpx.Response(200, json={}))

    await ui.on_message(ui.cl.Message(content="/learn"))  # type: ignore[arg-type]

    assert requests == []
    assert "No active session" in fake_cl.messages[-1].content


# --- /memory slash-commands (M-27) ----------------------------------------------


def test_memory_action_classifies_every_spelling() -> None:
    assert ui._memory_action("/memory") == "cat"
    assert ui._memory_action("/memory cat") == "cat"
    assert ui._memory_action("/memory show") == "cat"
    assert ui._memory_action("/memory stats") == "stats"
    assert ui._memory_action("/memory compact") == "compact"
    assert ui._memory_action("/memory/stats") == "stats"
    assert ui._memory_action("/memory/compact") == "compact"
    assert ui._memory_action("/memory list") == "help"
    # not a memory command — the text still reaches the model
    assert ui._memory_action("/learn") is None
    assert ui._memory_action("what is /memory?") is None
    assert ui._memory_action("/memoryless chatter") is None


async def test_on_message_memory_stats_renders_the_table(
    fake_cl: _FakeCl, patch_client
) -> None:
    fake_cl.user_session.set("thread_id", "sess-1")
    requests = patch_client(
        lambda request: httpx.Response(
            200,
            json={
                "files": [
                    {
                        "name": "LEARNED.md",
                        "size_bytes": 120,
                        "entries_count": 2,
                        "line_count": 5,
                        "token_count": 30,
                        "last_write_ts": "2026-10-26T10:00:00Z",
                        "max_bytes": 4096,
                        "over_limit": False,
                    }
                ],
                "total_size_bytes": 120,
                "line_counts": {"LEARNED.md": 5},
                "token_counts": {"LEARNED.md": 30},
                "last_compacted": None,
            },
        )
    )

    await ui.on_message(ui.cl.Message(content="/memory stats"))  # type: ignore[arg-type]

    assert len(requests) == 1  # a read, never a chat turn
    assert requests[0].method == "GET"
    assert requests[0].url.path == "/sessions/sess-1/memory/stats"
    body = fake_cl.messages[-1].content
    assert "| `LEARNED.md` | 120 B | 2 | 5 | 30 |" in body
    assert "last compacted: never" in body


async def test_on_message_memory_compact_posts_and_reports(
    fake_cl: _FakeCl, patch_client
) -> None:
    fake_cl.user_session.set("thread_id", "sess-1")
    requests = patch_client(
        lambda request: httpx.Response(
            200,
            json={
                "status": "ok",
                "results": [
                    {
                        "file": "LEARNED.md",
                        "changed": True,
                        "before_bytes": 5120,
                        "after_bytes": 3840,
                        "kept": 9,
                        "archived": 3,
                        "archive_path": "/tmp/archive/LEARNED_20261026.md",
                        "over_limit": False,
                    },
                    {
                        "file": "FACTS.md",
                        "changed": False,
                        "before_bytes": 200,
                        "after_bytes": 200,
                        "kept": 4,
                        "archived": 0,
                        "archive_path": None,
                        "over_limit": False,
                    },
                ],
                "total_archived": 3,
            },
        )
    )

    await ui.on_message(ui.cl.Message(content="/memory compact"))  # type: ignore[arg-type]

    assert len(requests) == 1
    assert requests[0].method == "POST"
    assert requests[0].url.path == "/sessions/sess-1/memory/compact"
    body = fake_cl.messages[-1].content
    assert "✅ Compacted 3 entries:" in body
    assert "`LEARNED.md`: 5120 → 3840 B (kept 9, archived 3)" in body
    assert "nothing to archive (4 kept)" in body


async def test_on_message_memory_cat_renders_the_markdown(
    fake_cl: _FakeCl, patch_client
) -> None:
    fake_cl.user_session.set("thread_id", "sess-1")
    requests = patch_client(
        lambda request: httpx.Response(
            200,
            json={
                "files": {"LEARNED.md": "- [learned] id=learn_001"},
                "markdown": "# Long-term Memory\n\n## LEARNED.md\n- [learned]",
            },
        )
    )

    await ui.on_message(ui.cl.Message(content="/memory"))  # type: ignore[arg-type]

    assert requests[0].url.path == "/sessions/sess-1/memory"
    assert fake_cl.messages[-1].content.startswith("# Long-term Memory")


async def test_on_message_memory_unknown_subcommand_shows_the_usage(
    fake_cl: _FakeCl, patch_client
) -> None:
    fake_cl.user_session.set("thread_id", "sess-1")
    requests = patch_client(lambda request: httpx.Response(200, json={}))

    await ui.on_message(ui.cl.Message(content="/memory list"))  # type: ignore[arg-type]

    assert requests == [], "an unknown subcommand never reaches the API"
    assert fake_cl.messages[-1].content.startswith("Usage:")


async def test_on_message_memory_reports_an_unreachable_api(
    fake_cl: _FakeCl, patch_client
) -> None:
    fake_cl.user_session.set("thread_id", "sess-1")

    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    patch_client(refuse)

    await ui.on_message(ui.cl.Message(content="/memory stats"))  # type: ignore[arg-type]

    assert "FastAPI server unreachable" in fake_cl.messages[-1].content


# --- settings / sidebar ----------------------------------------------------------


async def test_on_settings_update_persists_the_panel(
    fake_cl: _FakeCl, tmp_path: Path
) -> None:
    await ui.on_settings_update(
        {
            "Model": "gpt-4o",
            "Permission Mode": "permissive",
            "Allow List": "read /tmp/*\n\nwrite *.py",
            "Working directory": str(tmp_path / "project"),
        }
    )

    saved = json.loads((tmp_path / "settings.json").read_text(encoding="utf-8"))
    assert saved == {
        "model": "gpt-4o",
        "permission_mode": "permissive",
        "allow_list": ["read /tmp/*", "write *.py"],
        "working_dir": str(tmp_path / "project"),
    }
    assert "apply from the next message" in fake_cl.messages[-1].content
    assert str(tmp_path / "project") in fake_cl.messages[-1].content


async def test_on_settings_update_blank_working_dir_clears_it(
    fake_cl: _FakeCl, tmp_path: Path
) -> None:
    settings_file = tmp_path / "settings.json"
    settings_file.write_text(
        json.dumps({"working_dir": str(tmp_path)}), encoding="utf-8"
    )

    await ui.on_settings_update({"Working directory": "   "})

    saved = json.loads(settings_file.read_text(encoding="utf-8"))
    assert saved["working_dir"] is None


async def test_show_settings_panel_uses_real_input_widgets(
    fake_cl: _FakeCl, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Chainlit 2.x renders InputWidget instances only (dicts were dropped)."""
    from chainlit.input_widget import Select, TextInput

    monkeypatch.setattr(ui, "model_choices", lambda: ["glm-4.5-flash", "gpt-4o"])

    await ui._show_settings_panel(
        ui.UISettings(model="gpt-4o", working_dir="C:/projects/OryaAgent")
    )

    panel = fake_cl.panels[-1]
    widgets = panel.inputs
    by_id = {widget.id: widget for widget in widgets}
    assert set(by_id) == {
        "Model",
        "Permission Mode",
        "Allow List",
        "Working directory",
    }
    assert isinstance(by_id["Model"], Select)
    assert by_id["Model"].values == ["glm-4.5-flash", "gpt-4o"]
    assert by_id["Model"].initial == "gpt-4o"
    assert isinstance(by_id["Working directory"], TextInput)
    assert by_id["Working directory"].initial == "C:/projects/OryaAgent"


async def test_show_sidebar_lists_server_sessions(
    fake_cl: _FakeCl, patch_client
) -> None:
    patch_client(
        lambda request: httpx.Response(
            200,
            json={
                "items": [
                    {"session_id": "aaa-111", "title": None},
                    {"session_id": "bbb-222", "title": "My session"},
                ],
                "total": 2,
                "page": 1,
                "size": 10,
            },
        )
    )

    await ui._show_sidebar()

    message = fake_cl.messages[-1]
    labels = [action.label for action in message.actions]
    assert labels == ["New session", "aaa-111", "My session"]
    assert message.actions[1].payload == {"thread_id": "aaa-111"}


async def test_show_sidebar_survives_an_api_failure(
    fake_cl: _FakeCl, patch_client
) -> None:
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    patch_client(refuse)

    await ui._show_sidebar()

    message = fake_cl.messages[-1]
    assert [action.label for action in message.actions] == ["New session"]


async def test_load_history_replays_user_and_assistant(fake_cl: _FakeCl) -> None:
    client = _client_for(
        lambda request: httpx.Response(
            200,
            json={
                "session_id": "sess-9",
                "messages": [
                    {"role": "user", "content": "hello"},
                    {"role": "system", "content": "permission allow: bash"},
                    {"role": "assistant", "content": "hi!"},
                ],
            },
        )
    )

    found = await ui._load_history(client, "sess-9")

    assert found is True
    # system/permission lines are not chat history
    assert [m.content for m in fake_cl.messages] == ["hello", "hi!"]


async def test_load_history_returns_false_for_unknown_session() -> None:
    client = _client_for(lambda request: httpx.Response(404, json={"detail": "nope"}))

    assert await ui._load_history(client, "missing") is False
