"""Unit tests for M-15 — app.ui.chainlit_app (event mapping + wiring).

The Chainlit handlers themselves need a Chainlit runtime (websocket
context) and are covered by the manual acceptance run; everything they
delegate to — event normalization, graph assembly, checkpointer
fallback, state probes and best-effort logging — is tested here without
any infra (no Postgres, no API key, no Chainlit server).
"""

from __future__ import annotations

from typing import Any

import pytest
from langchain_core.messages import (
    AIMessage,
    AIMessageChunk,
    HumanMessage,
    ToolMessage,
)
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from app.core.context import trim_messages
from app.core.prompt import build_system_prompt
from app.ui import chainlit_app as ui


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


class _FakeEventGraph:
    """Canned ``astream_events`` source for the event-mapping tests."""

    def __init__(self, events: list[dict[str, Any]]) -> None:
        self._events = events
        self.calls: list[tuple[Any, Any, Any]] = []

    async def astream_events(self, input, config=None, *, version=None):
        self.calls.append((input, config, version))
        for event in self._events:
            yield event


class _FakeState:
    def __init__(self, next: tuple = (), values: dict[str, Any] | None = None) -> None:
        self.next = next
        self.values = values if values is not None else {"messages": []}


class _FakeStateGraph:
    def __init__(
        self,
        state: _FakeState | None = None,
        error: Exception | None = None,
    ) -> None:
        self._state = state
        self._error = error

    async def aget_state(self, config: dict[str, Any]) -> _FakeState:
        if self._error is not None:
            raise self._error
        return self._state


# --- stream_graph_events -------------------------------------------------


async def test_stream_graph_events_maps_token_and_tool_events() -> None:
    graph = _FakeEventGraph(
        [
            _ev("on_chain_start", data={"input": "x"}),
            _ev("on_chat_model_stream", data={"chunk": AIMessageChunk(content="Hel")}),
            _ev("on_chat_model_stream", data={"chunk": AIMessageChunk(content="lo")}),
            _ev("on_tool_start", tool="read", data={"input": {"path": "a.txt"}}),
            _ev(
                "on_tool_end",
                tool="read",
                data={
                    "output": ToolMessage(content="file body", tool_call_id="t1"),
                    "input": {"path": "a.txt"},
                },
            ),
            _ev("on_chain_end", data={"output": "x"}),
        ]
    )
    config = {"recursion_limit": 7}

    events = [event async for event in ui.stream_graph_events(graph, "hi", config)]

    assert [kind for kind, _ in events] == [
        "token",
        "token",
        "tool_start",
        "tool_end",
    ]
    assert events[0][1] == {"content": "Hel"}
    assert events[1][1] == {"content": "lo"}
    assert events[2][1] == {
        "run_id": "run-1",
        "tool": "read",
        "args": {"path": "a.txt"},
    }
    assert events[3][1]["run_id"] == "run-1"
    assert events[3][1]["output"] == "file body"

    payload, seen_config, version = graph.calls[0]
    assert version == "v2"
    assert seen_config is config
    assert isinstance(payload["messages"][0], HumanMessage)
    assert payload["messages"][0].content == "hi"


async def test_stream_graph_events_skips_empty_and_flattens_blocks() -> None:
    graph = _FakeEventGraph(
        [
            _ev("on_chat_model_stream", data={"chunk": AIMessageChunk(content="")}),
            _ev(
                "on_chat_model_stream",
                data={
                    "chunk": AIMessageChunk(
                        content=[{"type": "text", "text": "blocks"}]
                    )
                },
            ),
            _ev("on_chat_model_stream", data={}),
        ]
    )

    events = [event async for event in ui.stream_graph_events(graph, "hi", {})]

    assert events == [("token", {"content": "blocks"})]


async def test_stream_graph_events_yields_nothing_for_chain_only_events() -> None:
    graph = _FakeEventGraph(
        [
            _ev("on_chain_start", data={"input": "x"}),
            _ev("on_chain_end", data={"output": "x"}),
        ]
    )

    events = [event async for event in ui.stream_graph_events(graph, "hi", {})]

    assert events == []
    assert len(graph.calls) == 1


# --- resume_graph_events (M-16) --------------------------------------------


async def test_resume_graph_events_sends_resume_command_payload() -> None:
    graph = _FakeEventGraph(
        [
            _ev("on_chat_model_stream", data={"chunk": AIMessageChunk(content="ok")}),
        ]
    )
    config = {"recursion_limit": 7}

    events = [event async for event in ui.resume_graph_events(graph, "approve", config)]

    assert events == [("token", {"content": "ok"})]
    payload, seen_config, version = graph.calls[0]
    assert version == "v2"
    assert seen_config is config
    assert isinstance(payload, Command)
    assert payload.resume == "approve"


async def test_resume_graph_events_denies_and_always() -> None:
    for answer in ("deny", "always"):
        graph = _FakeEventGraph([])
        [event async for event in ui.resume_graph_events(graph, answer, {})]
        payload, _, _ = graph.calls[0]
        assert payload.resume == answer


# --- _render_run (M-16) ----------------------------------------------------


class _FakeReply:
    def __init__(self) -> None:
        self.tokens: list[str] = []

    async def stream_token(self, content: str) -> None:
        self.tokens.append(content)


class _FakeStep:
    def __init__(self, name: str = "tool", type: str = "tool") -> None:
        self.name = name
        self.type = type
        self.input: Any = None
        self.output: Any = None
        self.sent = 0
        self.updated = 0

    async def send(self) -> None:
        self.sent += 1

    async def update(self) -> None:
        self.updated += 1


async def test_render_run_streams_tokens_and_manages_steps(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created: list[_FakeStep] = []

    async def fake_start(data: dict[str, Any]) -> _FakeStep:
        step = _FakeStep(name=str(data.get("tool")))
        created.append(step)
        return step

    async def fake_end(steps: dict[str, Any], data: dict[str, Any]) -> None:
        steps.pop(str(data.get("run_id")), None)

    monkeypatch.setattr(ui, "_start_step", fake_start)
    monkeypatch.setattr(ui, "_end_step", fake_end)

    async def events():
        yield "token", {"content": "a"}
        yield "tool_start", {"run_id": "r1", "tool": "bash", "args": {"command": "ls"}}
        yield "tool_end", {"run_id": "r1", "tool": "bash", "output": "ok"}
        yield "token", {"content": "b"}

    reply = _FakeReply()
    steps: dict[str, Any] = {}

    streamed = await ui._render_run(reply, steps, events())  # type: ignore[arg-type]

    assert streamed is True
    assert reply.tokens == ["a", "b"]
    assert [s.name for s in created] == ["bash"]
    assert steps == {}


async def test_render_run_returns_false_without_tokens(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created: list[_FakeStep] = []

    async def fake_start(data: dict[str, Any]) -> _FakeStep:
        step = _FakeStep(name=str(data.get("tool")))
        created.append(step)
        return step

    monkeypatch.setattr(ui, "_start_step", fake_start)

    async def events():
        yield "tool_start", {"run_id": "r1", "tool": "bash", "args": {}}

    reply = _FakeReply()
    steps: dict[str, Any] = {}

    streamed = await ui._render_run(reply, steps, events())  # type: ignore[arg-type]

    assert streamed is False
    assert reply.tokens == []
    assert "r1" in steps


# --- build_session_graph wiring ------------------------------------------


def test_build_session_graph_wiring(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def fake_build_graph(tools, model, checkpointer, policy, **kwargs):
        captured.update(
            tools=tools,
            model=model,
            checkpointer=checkpointer,
            policy=policy,
            **kwargs,
        )
        return "GRAPH"

    monkeypatch.setattr(ui, "build_graph", fake_build_graph)
    monkeypatch.setattr(ui, "get_llm", lambda *a, **k: "MODEL")
    monkeypatch.setattr(ui, "get_tools", lambda session_id: ["t-read"])
    monkeypatch.setattr(ui, "get_policy", lambda mode=None, **k: "POLICY")

    graph = ui.build_session_graph("tid-1", "CP")

    assert graph == "GRAPH"
    assert captured["tools"] == ["t-read"]
    assert captured["model"] == "MODEL"
    assert captured["checkpointer"] == "CP"
    assert captured["policy"] == "POLICY"
    assert captured["system_prompt_fn"] is build_system_prompt
    assert captured["trim_fn"] is trim_messages


# --- checkpointer fallback ------------------------------------------------


async def test_resolve_checkpointer_prefers_postgres(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sentinel = object()

    async def fake_get_checkpointer():
        return sentinel

    monkeypatch.setattr(ui, "get_checkpointer", fake_get_checkpointer)

    checkpointer, degraded = await ui.resolve_checkpointer()

    assert checkpointer is sentinel
    assert degraded is False


async def test_resolve_checkpointer_falls_back_to_memory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def boom():
        raise RuntimeError("psycopg cannot run on ProactorEventLoop")

    monkeypatch.setattr(ui, "get_checkpointer", boom)

    checkpointer, degraded = await ui.resolve_checkpointer()

    assert degraded is True
    assert isinstance(checkpointer, MemorySaver)


# --- state probes ---------------------------------------------------------


async def test_has_pending_interrupt_true_for_human_pause() -> None:
    graph = _FakeStateGraph(state=_FakeState(next=("human",)))

    assert await ui._has_pending_interrupt(graph, {}) is True


async def test_has_pending_interrupt_false_when_finished() -> None:
    graph = _FakeStateGraph(state=_FakeState(next=()))

    assert await ui._has_pending_interrupt(graph, {}) is False


async def test_has_pending_interrupt_false_on_state_error() -> None:
    graph = _FakeStateGraph(error=RuntimeError("no state"))

    assert await ui._has_pending_interrupt(graph, {}) is False


async def test_final_answer_text_returns_latest_plain_answer() -> None:
    messages = [
        AIMessage(content="first reply"),
        AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "bash",
                    "args": {"command": "ls"},
                    "id": "c1",
                    "type": "tool_call",
                }
            ],
        ),
        AIMessage(content="second reply"),
    ]
    graph = _FakeStateGraph(state=_FakeState(values={"messages": messages}))

    assert await ui._final_answer_text(graph, {}) == "second reply"


async def test_final_answer_text_empty_on_state_error() -> None:
    graph = _FakeStateGraph(error=RuntimeError("no state"))

    assert await ui._final_answer_text(graph, {}) == ""


# --- best-effort session log ----------------------------------------------


async def test_safe_log_swallows_database_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def boom(*args, **kwargs):
        raise OSError("no postgres")

    monkeypatch.setattr(ui, "log_message", boom)

    await ui._safe_log("sid", "user", "hi")  # must not raise


async def test_safe_ensure_session_swallows_database_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def boom(*args, **kwargs):
        raise OSError("no postgres")

    monkeypatch.setattr(ui, "ensure_session", boom)

    await ui._safe_ensure_session("sid")  # must not raise


# --- content / preview helpers --------------------------------------------


@pytest.mark.parametrize(
    ("content", "expected"),
    [
        ("plain", "plain"),
        (None, ""),
        ([{"type": "text", "text": "a"}, {"type": "text", "text": "b"}], "ab"),
        (["x", "y"], "xy"),
        (42, "42"),
    ],
)
def test_content_text(content: Any, expected: str) -> None:
    assert ui._content_text(content) == expected


def test_preview_renders_json_for_tool_args() -> None:
    assert ui._preview({"command": "ls"}) == '{"command": "ls"}'


def test_preview_caps_length() -> None:
    text = ui._preview("z" * 5000, limit=10)

    assert text.startswith("z" * 10)
    assert "+4990 chars" in text
