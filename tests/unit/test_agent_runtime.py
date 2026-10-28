"""Unit tests for M-20/M-24 — app.core.agent (shared session runtime).

The runtime every client shares: event normalization, one turn as a
stream (``stream_turn``/``stream_resume`` + terminal ``done``), the JSON
wrappers (``run_turn``/``run_resume``), graph assembly through the seams
and the M-13 state probes. No infra — canned ``astream_events`` and
``aget_state`` doubles, no Postgres, no API key, no Chainlit server.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest
from langchain_core.messages import (
    AIMessage,
    AIMessageChunk,
    HumanMessage,
    ToolMessage,
)
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from app.core import agent
from app.core.context import trim_messages
from app.core.prompt import build_system_prompt


def _ev(
    name: str,
    *,
    run_id: str = "run-1",
    tool: str | None = None,
    data: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    event: dict[str, Any] = {"event": name, "run_id": run_id, "data": data or {}}
    if tool is not None:
        event["name"] = tool
    if metadata is not None:
        event["metadata"] = metadata
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
    """State probe double: also serves as the stream source for turns."""

    def __init__(
        self,
        state: _FakeState | None = None,
        error: Exception | None = None,
        events: list[dict[str, Any]] | None = None,
    ) -> None:
        self._state = state if state is not None else _FakeState()
        self._error = error
        self._events = events or []

    async def astream_events(self, input, config=None, *, version=None):
        for event in self._events:
            yield event

    async def aget_state(self, config: dict[str, Any]) -> _FakeState:
        if self._error is not None:
            raise self._error
        return self._state


# --- stream_graph_events -----------------------------------------------------


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

    events = [event async for event in agent.stream_graph_events(graph, "hi", config)]

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
    assert events[3][1]["from_cache"] is False

    payload, seen_config, version = graph.calls[0]
    assert version == "v2"
    assert seen_config is config
    assert isinstance(payload["messages"][0], HumanMessage)
    assert payload["messages"][0].content == "hi"


async def test_stream_graph_events_marks_cache_hits() -> None:
    """M-21 follow-up (M-24): ``from_cache`` reaches the ``tool_end`` event."""
    cached = ToolMessage(
        content="cached body",
        tool_call_id="t1",
        metadata={"from_cache": True},
    )
    graph = _FakeEventGraph(
        [
            _ev("on_tool_end", tool="read", data={"output": cached}),
            _ev(
                "on_tool_end",
                tool="grep",
                data={
                    "output": ToolMessage(content="fresh", tool_call_id="t2"),
                },
            ),
        ]
    )

    events = [event async for event in agent.stream_graph_events(graph, "hi", {})]

    assert [data["from_cache"] for _, data in events] == [True, False]


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

    events = [event async for event in agent.stream_graph_events(graph, "hi", {})]

    assert events == [("token", {"content": "blocks"})]


async def test_stream_graph_events_yields_nothing_for_chain_only_events() -> None:
    graph = _FakeEventGraph(
        [
            _ev("on_chain_start", data={"input": "x"}),
            _ev("on_chain_end", data={"output": "x"}),
        ]
    )

    events = [event async for event in agent.stream_graph_events(graph, "hi", {})]

    assert events == []
    assert len(graph.calls) == 1


# --- M-28: failure recovery in the stream ------------------------------------


async def test_stream_graph_events_drops_recover_node_tokens() -> None:
    """The recover node's alternatives chatter never reaches the reply."""
    graph = _FakeEventGraph(
        [
            _ev(
                "on_chat_model_stream",
                data={"chunk": AIMessageChunk(content="Alternatives: 1) ...")},
                metadata={"langgraph_node": "recover"},
            ),
            _ev(
                "on_chat_model_stream",
                data={"chunk": AIMessageChunk(content="final answer")},
                metadata={"langgraph_node": "agent"},
            ),
            _ev("on_chat_model_stream", data={"chunk": AIMessageChunk(content="ok")}),
        ]
    )

    events = [event async for event in agent.stream_graph_events(graph, "hi", {})]

    assert events == [
        ("token", {"content": "final answer"}),
        ("token", {"content": "ok"}),
    ]


async def test_stream_graph_events_maps_tool_error_to_tool_end() -> None:
    """A failed call closes its step card: on_tool_error -> tool_end (M-28)."""
    graph = _FakeEventGraph(
        [
            _ev("on_tool_start", tool="boom", data={"input": {"text": "x"}}),
            _ev(
                "on_tool_error",
                run_id="run-9",
                tool="boom",
                data={"error": ValueError("kaboom"), "tool_call_id": "c1"},
            ),
        ]
    )

    events = [event async for event in agent.stream_graph_events(graph, "hi", {})]

    assert events == [
        ("tool_start", {"run_id": "run-1", "tool": "boom", "args": {"text": "x"}}),
        (
            "tool_end",
            {
                "run_id": "run-9",
                "tool": "boom",
                "output": "kaboom",
                "from_cache": False,
            },
        ),
    ]


# --- resume_graph_events (M-16) ----------------------------------------------


async def test_resume_graph_events_sends_resume_command_payload() -> None:
    graph = _FakeEventGraph(
        [
            _ev("on_chat_model_stream", data={"chunk": AIMessageChunk(content="ok")}),
        ]
    )
    config = {"recursion_limit": 7}

    events = [
        event async for event in agent.resume_graph_events(graph, "approve", config)
    ]

    assert events == [("token", {"content": "ok"})]
    payload, seen_config, version = graph.calls[0]
    assert version == "v2"
    assert seen_config is config
    assert isinstance(payload, Command)
    assert payload.resume == "approve"


async def test_resume_graph_events_denies_and_always() -> None:
    for answer in ("deny", "always"):
        graph = _FakeEventGraph([])
        [event async for event in agent.resume_graph_events(graph, answer, {})]
        payload, _, _ = graph.calls[0]
        assert payload.resume == answer


# --- stream_turn / stream_resume (M-24) ---------------------------------------


def _turn_events() -> list[dict[str, Any]]:
    return [
        _ev(
            "on_chat_model_stream",
            data={"chunk": AIMessageChunk(content="Let me ")},
        ),
        _ev("on_tool_start", tool="read", data={"input": {"path": "a.py"}}),
        _ev("on_tool_end", tool="read", data={"output": "file body"}),
        _ev("on_chat_model_stream", data={"chunk": AIMessageChunk(content="check.")}),
    ]


async def test_stream_turn_forwards_events_and_ends_with_done() -> None:
    graph = _FakeStateGraph(state=_FakeState(next=()), events=_turn_events())

    events = [event async for event in agent.stream_turn(graph, "go", {})]

    assert [kind for kind, _ in events] == [
        "token",
        "tool_start",
        "tool_end",
        "token",
        "done",
    ]
    done = events[-1][1]
    assert done["status"] == "ok"
    assert done["reply"] == "Let me check."
    assert done["pending"] is None
    assert done["tool_steps"][0]["tool"] == "read"
    assert done["tool_steps"][0]["from_cache"] is False


async def test_stream_turn_reports_interrupt_with_pending() -> None:
    state = _FakeState(next=("human",))
    # emulate langgraph's interrupt payload on the paused task
    state.tasks = (
        SimpleNamespace(
            interrupts=(
                SimpleNamespace(
                    value={
                        "tool": "bash",
                        "args": {"command": "rm x"},
                        "reason": "strict mode",
                    },
                ),
            )
        ),
    )
    graph = _FakeStateGraph(
        state=state,
        events=[
            _ev(
                "on_chat_model_stream",
                data={"chunk": AIMessageChunk(content="Running")},
            )
        ],
    )

    events = [event async for event in agent.stream_turn(graph, "go", {})]

    done = events[-1][1]
    assert events[-1][0] == "done"
    assert done["status"] == "interrupted"
    assert done["reply"] == "Running"
    assert done["pending"].tool == "bash"
    assert done["pending"].args == {"command": "rm x"}


async def test_stream_turn_falls_back_to_checkpoint_reply() -> None:
    graph = _FakeStateGraph(
        state=_FakeState(values={"messages": [AIMessage(content="checkpoint answer")]}),
        events=[],  # model did not stream
    )

    events = [event async for event in agent.stream_turn(graph, "hi", {})]

    assert events[-1][1]["reply"] == "checkpoint answer"
    assert events[-1][1]["status"] == "ok"


async def test_stream_resume_streams_the_continuation() -> None:
    graph = _FakeStateGraph(
        state=_FakeState(next=()),
        events=[
            _ev("on_chat_model_stream", data={"chunk": AIMessageChunk(content="done:")})
        ],
    )

    events = [event async for event in agent.stream_resume(graph, "approve", {})]

    assert [kind for kind, _ in events] == ["token", "done"]
    assert events[-1][1]["reply"] == "done:"


async def test_run_turn_returns_the_done_payload() -> None:
    graph = _FakeStateGraph(state=_FakeState(next=()), events=_turn_events())

    result = await agent.run_turn(graph, "go", {})

    assert result.status == "ok"
    assert result.reply == "Let me check."
    assert len(result.tool_steps) == 1
    assert result.pending is None


async def test_run_resume_returns_the_done_payload() -> None:
    graph = _FakeStateGraph(state=_FakeState(next=()), events=_turn_events())

    result = await agent.run_resume(graph, "approve", {})

    assert result.status == "ok"
    assert result.reply == "Let me check."


async def test_run_turn_propagates_from_cache_into_tool_steps() -> None:
    cached = ToolMessage(
        content="cached body", tool_call_id="t1", metadata={"from_cache": True}
    )
    graph = _FakeStateGraph(
        state=_FakeState(next=()),
        events=[
            _ev("on_tool_start", tool="read", data={"input": {"path": "a.py"}}),
            _ev("on_tool_end", tool="read", data={"output": cached}),
            _ev("on_chat_model_stream", data={"chunk": AIMessageChunk(content="ok")}),
        ],
    )

    result = await agent.run_turn(graph, "read a.py", {})

    assert result.tool_steps[0]["from_cache"] is True
    assert result.reply == "ok"


async def test_run_turn_completes_when_state_probe_fails() -> None:
    graph = _FakeStateGraph(
        state=_FakeState(next=()),
        error=RuntimeError("no state"),
        events=_turn_events(),
    )

    result = await agent.run_turn(graph, "go", {})

    # aget_state raising makes has_pending_interrupt False -> the run completes
    assert result.status == "ok"
    assert result.reply == "Let me check."


# --- build_session_graph wiring ----------------------------------------------


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

    monkeypatch.setattr(agent, "build_graph", fake_build_graph)
    monkeypatch.setattr(agent, "get_llm", lambda *a, **k: "MODEL")
    monkeypatch.setattr(agent, "get_tools", lambda session_id: ["t-read"])
    monkeypatch.setattr(agent, "get_policy", lambda mode=None, **k: "POLICY")

    graph = agent.build_session_graph("tid-1", "CP")

    assert graph == "GRAPH"
    assert captured["tools"] == ["t-read"]
    assert captured["model"] == "MODEL"
    assert captured["checkpointer"] == "CP"
    assert captured["policy"] == "POLICY"
    assert captured["system_prompt_fn"] is build_system_prompt
    assert captured["trim_fn"] is trim_messages


def test_build_session_graph_resolves_model_alias(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """M-24: a settings-panel alias goes through the ``get_llm`` seam.

    Before M-24 the raw string reached ``build_graph`` (no ``ainvoke``).
    """
    captured: dict[str, Any] = {}
    calls: list[dict[str, Any]] = []

    def fake_build_graph(tools, model, checkpointer, policy, **kwargs):
        captured["model"] = model
        return "GRAPH"

    def fake_get_llm(*args, **kwargs):
        calls.append({"args": args, "kwargs": kwargs})
        return "RESOLVED_MODEL"

    monkeypatch.setattr(agent, "build_graph", fake_build_graph)
    monkeypatch.setattr(agent, "get_llm", fake_get_llm)

    agent.build_session_graph("tid-1", "CP", model="gpt-4o")

    assert captured["model"] == "RESOLVED_MODEL"
    assert calls == [{"args": (), "kwargs": {"provider": None, "model": "gpt-4o"}}]


def test_build_session_graph_pins_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The UI provider combobox travels through the ``get_llm`` seam."""
    calls: list[dict[str, Any]] = []

    def fake_build_graph(tools, model, checkpointer, policy, **kwargs):
        return "GRAPH"

    def fake_get_llm(*args, **kwargs):
        calls.append({"args": args, "kwargs": kwargs})
        return "RESOLVED_MODEL"

    monkeypatch.setattr(agent, "build_graph", fake_build_graph)
    monkeypatch.setattr(agent, "get_llm", fake_get_llm)

    agent.build_session_graph("tid-1", "CP", model="deepseek-chat", provider="deepseek")

    assert calls == [
        {"args": (), "kwargs": {"provider": "deepseek", "model": "deepseek-chat"}}
    ]


def test_build_session_graph_keeps_model_instance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    def fake_build_graph(tools, model, checkpointer, policy, **kwargs):
        captured["model"] = model
        return "GRAPH"

    monkeypatch.setattr(agent, "build_graph", fake_build_graph)
    monkeypatch.setattr(
        agent, "get_llm", lambda *a, **k: pytest.fail("get_llm must not be called")
    )

    instance = object()
    agent.build_session_graph("tid-1", "CP", model=instance)

    assert captured["model"] is instance


def test_build_session_graph_with_policy_override() -> None:
    with (
        patch.object(agent, "build_graph") as mock_build_graph,
        patch.object(agent, "get_llm") as mock_get_llm,
        patch.object(agent, "get_policy") as mock_get_policy,
    ):
        mock_policy = type("MockPolicy", (), {})()
        mock_get_llm.return_value = type("MockLLM", (), {})()

        agent.build_session_graph("test123", MemorySaver(), policy=mock_policy)

        mock_build_graph.assert_called_once()
        # policy is the 4th positional arg of build_graph
        assert mock_build_graph.call_args[0][3] is mock_policy
        mock_get_policy.assert_not_called()


def test_build_session_graph_defaults() -> None:
    with (
        patch.object(agent, "build_graph") as mock_build_graph,
        patch.object(agent, "get_llm") as mock_get_llm,
        patch.object(agent, "get_policy") as mock_get_policy,
    ):
        mock_llm = type("MockLLM", (), {})()
        mock_policy = type("MockPolicy", (), {})()
        mock_get_llm.return_value = mock_llm
        mock_get_policy.return_value = mock_policy

        agent.build_session_graph("test123", MemorySaver())

        mock_build_graph.assert_called_once()
        assert mock_build_graph.call_args[0][1] is mock_llm
        assert mock_build_graph.call_args[0][3] is mock_policy
        mock_get_llm.assert_called_once()
        mock_get_policy.assert_called_once()


# --- checkpointer fallback -----------------------------------------------------


async def test_resolve_checkpointer_prefers_postgres(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sentinel = object()

    async def fake_get_checkpointer():
        return sentinel

    monkeypatch.setattr(agent, "get_checkpointer", fake_get_checkpointer)

    checkpointer, degraded = await agent.resolve_checkpointer()

    assert checkpointer is sentinel
    assert degraded is False


async def test_resolve_checkpointer_falls_back_to_memory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def boom():
        raise RuntimeError("psycopg cannot run on ProactorEventLoop")

    monkeypatch.setattr(agent, "get_checkpointer", boom)

    checkpointer, degraded = await agent.resolve_checkpointer()

    assert degraded is True
    assert isinstance(checkpointer, MemorySaver)


# --- state probes ----------------------------------------------------------------


async def test_has_pending_interrupt_true_for_human_pause() -> None:
    graph = _FakeStateGraph(state=_FakeState(next=("human",)))

    assert await agent.has_pending_interrupt(graph, {}) is True


async def test_has_pending_interrupt_false_when_finished() -> None:
    graph = _FakeStateGraph(state=_FakeState(next=()))

    assert await agent.has_pending_interrupt(graph, {}) is False


async def test_has_pending_interrupt_false_on_state_error() -> None:
    graph = _FakeStateGraph(error=RuntimeError("no state"))

    assert await agent.has_pending_interrupt(graph, {}) is False


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

    assert await agent.final_answer_text(graph, {}) == "second reply"


async def test_final_answer_text_empty_on_state_error() -> None:
    graph = _FakeStateGraph(error=RuntimeError("no state"))

    assert await agent.final_answer_text(graph, {}) == ""


# --- content / preview helpers ---------------------------------------------------


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
    assert agent.content_text(content) == expected


def test_preview_renders_json_for_tool_args() -> None:
    assert agent.preview({"command": "ls"}) == '{"command": "ls"}'


def test_preview_caps_length() -> None:
    text = agent.preview("z" * 5000, limit=10)

    assert text.startswith("z" * 10)
    assert "+4990 chars" in text
