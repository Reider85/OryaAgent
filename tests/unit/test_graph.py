"""Agent-loop tests (M-04) + permission gate (M-13).

Mock model, mock tools, in-memory checkpointer; the real
``PermissionPolicy`` is exercised end-to-end for the ask/deny flows.
"""

from __future__ import annotations

from typing import Any

import pytest
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import tool
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Command

from app.core.config import clear_settings_cache
from app.core.graph import (
    build_graph,
    build_human_node,
    default_run_config,
    resume_command,
    route_after_agent,
)
from app.core.permissions import Decision, PermissionConfig, PermissionPolicy


@tool
def echo(text: str) -> str:
    """Echo the given text back to the caller."""
    return f"echo: {text}"


@tool
def write(path: str, content: str) -> str:
    """Fake write tool: records nothing, returns a marker (permission tests)."""
    return f"written:{path}"


@tool
def read(path: str) -> str:
    """Fake read tool: returns a marker (permission tests)."""
    return f"read:{path}"


class MockPolicy:
    """Duck-typed stand-in for the M-13 ``PermissionPolicy``."""

    def __init__(self, decision: str = "allow") -> None:
        self.decision = decision
        self.checked: list[dict] = []
        self.allowed: list[str] = []

    def check(self, tool_call: Any) -> Decision:
        self.checked.append(dict(tool_call))
        return Decision(action=self.decision, reason="mock")  # type: ignore[arg-type]

    def record_session_allow(self, tool_name: str) -> None:
        self.allowed.append(tool_name)


def _model(*messages: AIMessage) -> FakeMessagesListChatModel:
    return FakeMessagesListChatModel(responses=list(messages))


def _ai_with_tool_call(name: str = "echo", args: dict | None = None) -> AIMessage:
    return AIMessage(
        content="",
        tool_calls=[{"name": name, "args": args or {"text": "hi"}, "id": "call_1"}],
    )


def _ai_with_calls(*calls: tuple[str, dict, str]) -> AIMessage:
    """Build an AIMessage with several tool calls: (name, args, id) tuples."""
    return AIMessage(
        content="",
        tool_calls=[
            {"name": name, "args": args, "id": call_id} for name, args, call_id in calls
        ],
    )


def _strict_policy() -> PermissionPolicy:
    return PermissionPolicy("strict", config=PermissionConfig.default())


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


async def test_ask_decision_interrupts_in_human_node():
    graph = build_graph(
        [echo],
        _model(
            _ai_with_tool_call(),
            AIMessage(content="done"),
        ),
        InMemorySaver(),
        MockPolicy(decision="ask"),
    )
    config = default_run_config("thread-ask")

    await graph.ainvoke({"messages": [HumanMessage("hi")]}, config)

    state = await graph.aget_state(config)
    assert state.next == ("human",)
    assert not any(isinstance(m, ToolMessage) for m in state.values["messages"])


async def test_ask_mode_resume_runs_the_tool():
    graph = build_graph(
        [echo],
        _model(
            _ai_with_tool_call(),
            AIMessage(content="done"),
        ),
        InMemorySaver(),
        MockPolicy(decision="ask"),
    )
    config = default_run_config("thread-resume")

    await graph.ainvoke({"messages": [HumanMessage("hi")]}, config)
    result = await graph.ainvoke(resume_command("approve"), config)

    messages = result["messages"]
    assert any(isinstance(m, ToolMessage) and "echo: hi" in m.content for m in messages)
    assert messages[-1].content == "done"


async def test_allow_decision_does_not_interrupt():
    graph = build_graph(
        [echo],
        _model(
            _ai_with_tool_call(),
            AIMessage(content="done"),
        ),
        InMemorySaver(),
        MockPolicy(decision="allow"),
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


def test_route_after_agent_with_policy_goes_to_human():
    assert (
        route_after_agent({"messages": [_ai_with_tool_call()]}, MockPolicy()) == "human"
    )
    assert (
        route_after_agent({"messages": [AIMessage(content="x")]}, MockPolicy()) == END
    )


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


@pytest.mark.parametrize("decision", ["allow", "ask"])
async def test_graph_without_checkpointer_runs(decision: str):
    """No checkpointer -> single-shot run; ask decisions fail closed (deny)."""
    graph = build_graph(
        [echo],
        _model(_ai_with_tool_call(), AIMessage(content="hello")),
        None,
        MockPolicy(decision=decision),
    )
    result = await graph.ainvoke({"messages": [HumanMessage("hi")]})
    assert result["messages"][-1].content == "hello"
    if decision == "ask":
        refusals = [
            m
            for m in result["messages"]
            if isinstance(m, ToolMessage) and "prompting unavailable" in m.content
        ]
        assert refusals
    else:
        assert any(
            isinstance(m, ToolMessage) and "echo: hi" in m.content
            for m in result["messages"]
        )


# --- human node unit tests --------------------------------------------------


async def test_human_node_denies_tool_calls():
    """A deny decision refuses every pending call and routes to agent."""
    policy = MockPolicy(decision="deny")
    node = build_human_node(policy)

    result = await node({"messages": [_ai_with_tool_call()]})

    assert isinstance(result, Command)
    assert result.goto == "agent"
    messages = result.update["messages"]
    assert [m.content for m in messages] == ["Denied by policy: mock"]
    assert messages[0].tool_call_id == "call_1"
    assert len(policy.checked) == 1
    assert policy.checked[0]["name"] == "echo"
    assert policy.checked[0]["args"] == {"text": "hi"}


async def test_human_node_allows_tool_calls():
    policy = MockPolicy(decision="allow")
    node = build_human_node(policy)

    result = await node({"messages": [_ai_with_tool_call()]})

    assert isinstance(result, Command)
    assert result.goto == "tools"
    assert result.update is None
    assert policy.checked


async def test_human_node_without_policy_routes_to_tools():
    node = build_human_node(None)
    result = await node({"messages": [_ai_with_tool_call()]})
    assert isinstance(result, Command)
    assert result.goto == "tools"


async def test_human_node_without_tool_calls_routes_to_tools():
    node = build_human_node(MockPolicy(decision="deny"))
    result = await node({"messages": [AIMessage(content="plain")]})
    assert isinstance(result, Command)
    assert result.goto == "tools"


# --- end-to-end with the real PermissionPolicy ------------------------------


async def test_strict_write_interrupts_and_approve_executes():
    graph = build_graph(
        [write],
        _model(
            _ai_with_tool_call("write", {"path": "a.txt", "content": "x"}),
            AIMessage(content="done"),
        ),
        InMemorySaver(),
        _strict_policy(),
    )
    config = default_run_config("thread-e2e-approve")

    await graph.ainvoke({"messages": [HumanMessage("hi")]}, config)
    state = await graph.aget_state(config)
    assert state.next == ("human",)
    assert not any(isinstance(m, ToolMessage) for m in state.values["messages"])

    result = await graph.ainvoke(resume_command("approve"), config)
    messages = result["messages"]
    assert any(
        isinstance(m, ToolMessage) and m.content == "written:a.txt" for m in messages
    )
    assert messages[-1].content == "done"


async def test_strict_write_deny_refuses_without_execution():
    graph = build_graph(
        [write],
        _model(
            _ai_with_tool_call("write", {"path": "a.txt", "content": "x"}),
            AIMessage(content="done"),
        ),
        InMemorySaver(),
        _strict_policy(),
    )
    config = default_run_config("thread-e2e-deny")

    await graph.ainvoke({"messages": [HumanMessage("hi")]}, config)
    result = await graph.ainvoke(resume_command("deny"), config)

    messages = result["messages"]
    refusals = [
        m
        for m in messages
        if isinstance(m, ToolMessage) and m.content == "Denied by user"
    ]
    assert len(refusals) == 1
    assert not any(
        isinstance(m, ToolMessage) and m.content.startswith("written:")
        for m in messages
    )
    assert messages[-1].content == "done"


async def test_strict_read_does_not_interrupt():
    graph = build_graph(
        [read],
        _model(
            _ai_with_tool_call("read", {"path": "a.txt"}),
            AIMessage(content="done"),
        ),
        InMemorySaver(),
        _strict_policy(),
    )
    config = default_run_config("thread-e2e-read")

    result = await graph.ainvoke({"messages": [HumanMessage("hi")]}, config)

    state = await graph.aget_state(config)
    assert state.next == ()
    assert any(
        isinstance(m, ToolMessage) and m.content == "read:a.txt"
        for m in result["messages"]
    )


async def test_deny_rule_refuses_without_interrupt():
    @tool
    def bash(command: str) -> str:
        """Fake bash tool (permission tests)."""
        return f"ran:{command}"

    graph = build_graph(
        [bash],
        _model(
            _ai_with_tool_call("bash", {"command": "rm -rf /"}),
            AIMessage(content="done"),
        ),
        InMemorySaver(),
        _strict_policy(),
    )
    config = default_run_config("thread-e2e-deny-rule")

    result = await graph.ainvoke({"messages": [HumanMessage("hi")]}, config)

    state = await graph.aget_state(config)
    assert state.next == ()  # no interrupt: the deny rule answered immediately
    refusals = [
        m
        for m in result["messages"]
        if isinstance(m, ToolMessage) and m.content.startswith("Denied by policy:")
    ]
    assert len(refusals) == 1
    assert "root" in refusals[0].content
    assert not any(
        isinstance(m, ToolMessage) and m.content.startswith("ran:")
        for m in result["messages"]
    )


async def test_always_records_session_allowlist():
    policy = _strict_policy()
    graph = build_graph(
        [write],
        _model(
            _ai_with_tool_call("write", {"path": "a.txt", "content": "x"}),
            AIMessage(content="done"),
        ),
        InMemorySaver(),
        policy,
    )
    config = default_run_config("thread-e2e-always")

    await graph.ainvoke({"messages": [HumanMessage("hi")]}, config)
    await graph.ainvoke(resume_command("always"), config)

    assert not policy.should_interrupt("write", {"path": "b.txt", "content": "y"})


async def test_batch_of_two_asks_approve_then_deny_refuses_all():
    """Per-call prompts; one denial refuses the whole batch (provider contract)."""
    graph = build_graph(
        [write],
        _model(
            _ai_with_calls(
                ("write", {"path": "a.txt", "content": "x"}, "call_1"),
                ("write", {"path": "b.txt", "content": "y"}, "call_2"),
            ),
            AIMessage(content="done"),
        ),
        InMemorySaver(),
        _strict_policy(),
    )
    config = default_run_config("thread-e2e-batch")

    await graph.ainvoke({"messages": [HumanMessage("hi")]}, config)
    result = await graph.ainvoke(resume_command("approve"), config)
    state = await graph.aget_state(config)
    assert state.next == ("human",)  # second prompt

    result = await graph.ainvoke(resume_command("deny"), config)

    refusals = [
        m
        for m in result["messages"]
        if isinstance(m, ToolMessage) and m.content.startswith("Denied")
    ]
    assert len(refusals) == 2
    assert not any(
        isinstance(m, ToolMessage) and m.content.startswith("written:")
        for m in result["messages"]
    )
    assert result["messages"][-1].content == "done"


async def test_legacy_empty_resume_still_approves():
    graph = build_graph(
        [echo],
        _model(
            _ai_with_tool_call(),
            AIMessage(content="done"),
        ),
        InMemorySaver(),
        MockPolicy(decision="ask"),
    )
    config = default_run_config("thread-legacy-resume")

    await graph.ainvoke({"messages": [HumanMessage("hi")]}, config)
    result = await graph.ainvoke(resume_command(), config)  # "" == approve

    assert any(
        isinstance(m, ToolMessage) and "echo: hi" in m.content
        for m in result["messages"]
    )


async def test_unknown_resume_value_fails_closed():
    graph = build_graph(
        [echo],
        _model(
            _ai_with_tool_call(),
            AIMessage(content="done"),
        ),
        InMemorySaver(),
        MockPolicy(decision="ask"),
    )
    config = default_run_config("thread-unknown-resume")

    await graph.ainvoke({"messages": [HumanMessage("hi")]}, config)
    result = await graph.ainvoke(resume_command("maybe"), config)

    refusals = [
        m
        for m in result["messages"]
        if isinstance(m, ToolMessage) and m.content == "Denied by user"
    ]
    assert len(refusals) == 1
    assert not any(
        isinstance(m, ToolMessage) and "echo: hi" in m.content
        for m in result["messages"]
    )
