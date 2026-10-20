"""Agent-loop tests (M-04) — mock model, mock tools, in-memory checkpointer."""

from __future__ import annotations

from typing import Any

import pytest
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import tool
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END
from langgraph.graph.state import CompiledStateGraph

from app.core.config import clear_settings_cache
from app.core.graph import (
    build_graph,
    build_human_node,
    default_run_config,
    resume_command,
    route_after_agent,
)


@tool
def echo(text: str) -> str:
    """Echo the given text back to the caller."""
    return f"echo: {text}"


class MockPolicy:
    """Duck-typed stand-in for the M-13 ``PermissionPolicy``."""

    def __init__(self, ask_mode: bool = False, decision: str = "allow") -> None:
        self.ask_mode = ask_mode
        self.decision = decision
        self.reviewed: list[list[dict]] = []

    async def review(self, tool_calls: Any) -> str:
        self.reviewed.append(list(tool_calls))
        return self.decision


def _model(*messages: AIMessage) -> FakeMessagesListChatModel:
    return FakeMessagesListChatModel(responses=list(messages))


def _ai_with_tool_call(name: str = "echo", args: dict | None = None) -> AIMessage:
    return AIMessage(
        content="",
        tool_calls=[{"name": name, "args": args or {"text": "hi"}, "id": "call_1"}],
    )


async def test_build_graph_returns_compiled_graph():
    graph = build_graph(
        [echo], _model(AIMessage(content="hello")), InMemorySaver(), MockPolicy()
    )
    assert isinstance(graph, CompiledStateGraph)


async def test_agent_without_tool_calls_goes_to_end():
    graph = build_graph(
        [echo],
        _model(AIMessage(content="final answer")),
        InMemorySaver(),
        MockPolicy(),
    )
    config = default_run_config("thread-end")

    result = await graph.ainvoke({"messages": [HumanMessage("hi")]}, config)

    assert result["messages"][-1].content == "final answer"
    assert isinstance(result["messages"][-1], AIMessage)
    state = await graph.aget_state(config)
    assert state.next == ()


async def test_agent_with_tool_calls_loops_through_tools():
    graph = build_graph(
        [echo],
        _model(
            _ai_with_tool_call(),
            AIMessage(content="done"),
        ),
        InMemorySaver(),
        MockPolicy(),
    )
    config = default_run_config("thread-tools")

    result = await graph.ainvoke({"messages": [HumanMessage("hi")]}, config)

    messages = result["messages"]
    assert any(isinstance(m, ToolMessage) and "echo: hi" in m.content for m in messages)
    assert messages[-1].content == "done"
    assert isinstance(messages[-1], AIMessage)


async def test_ask_mode_interrupts_before_tools():
    graph = build_graph(
        [echo],
        _model(
            _ai_with_tool_call(),
            AIMessage(content="done"),
        ),
        InMemorySaver(),
        MockPolicy(ask_mode=True),
    )
    config = default_run_config("thread-ask")

    await graph.ainvoke({"messages": [HumanMessage("hi")]}, config)

    state = await graph.aget_state(config)
    assert state.next == ("tools",)
    assert not any(isinstance(m, ToolMessage) for m in state.values["messages"])


async def test_ask_mode_resume_runs_the_tool():
    graph = build_graph(
        [echo],
        _model(
            _ai_with_tool_call(),
            AIMessage(content="done"),
        ),
        InMemorySaver(),
        MockPolicy(ask_mode=True),
    )
    config = default_run_config("thread-resume")

    await graph.ainvoke({"messages": [HumanMessage("hi")]}, config)
    result = await graph.ainvoke(resume_command(), config)

    messages = result["messages"]
    assert any(isinstance(m, ToolMessage) and "echo: hi" in m.content for m in messages)
    assert messages[-1].content == "done"


async def test_auto_mode_does_not_interrupt():
    graph = build_graph(
        [echo],
        _model(
            _ai_with_tool_call(),
            AIMessage(content="done"),
        ),
        InMemorySaver(),
        MockPolicy(ask_mode=False),
    )
    config = default_run_config("thread-auto")

    result = await graph.ainvoke({"messages": [HumanMessage("hi")]}, config)

    assert any(isinstance(m, ToolMessage) for m in result["messages"])
    state = await graph.aget_state(config)
    assert state.next == ()


def test_route_after_agent():
    assert route_after_agent({"messages": [AIMessage(content="plain")]}) == END
    assert route_after_agent({"messages": [_ai_with_tool_call()]}) == "tools"
    assert route_after_agent({"messages": []}) == END


def test_default_run_config_uses_configured_recursion_limit(monkeypatch):
    monkeypatch.setenv("ORYA_RECURSION_LIMIT", "42")
    clear_settings_cache()
    try:
        config = default_run_config("thread-1")
        assert config["configurable"]["thread_id"] == "thread-1"
        assert config["recursion_limit"] == 42
    finally:
        clear_settings_cache()

    config = default_run_config("thread-2", recursion_limit=7)
    assert config["recursion_limit"] == 7


@pytest.mark.parametrize("ask_mode", [True, False])
async def test_graph_without_checkpointer_runs(ask_mode: bool):
    """No checkpointer -> single-shot run, no interrupts to resume from."""
    graph = build_graph(
        [echo],
        _model(AIMessage(content="hello")),
        None,
        MockPolicy(ask_mode=ask_mode),
    )
    result = await graph.ainvoke({"messages": [HumanMessage("hi")]})
    assert result["messages"][-1].content == "hello"


async def test_human_node_denies_tool_calls():
    """The human node returns 'Denied by user' for every pending call."""
    policy = MockPolicy(decision="deny")
    node = build_human_node(policy)

    result = await node({"messages": [_ai_with_tool_call()]})

    assert result is not None
    assert [m.content for m in result["messages"]] == ["Denied by user"]
    assert result["messages"][0].tool_call_id == "call_1"
    assert len(policy.reviewed) == 1
    assert policy.reviewed[0][0]["name"] == "echo"
    assert policy.reviewed[0][0]["args"] == {"text": "hi"}


async def test_human_node_allows_tool_calls():
    policy = MockPolicy(decision="allow")
    node = build_human_node(policy)

    assert await node({"messages": [_ai_with_tool_call()]}) is None
    assert policy.reviewed


async def test_human_node_without_policy_is_a_noop():
    node = build_human_node(None)
    assert await node({"messages": [_ai_with_tool_call()]}) is None
