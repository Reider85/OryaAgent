"""Agent-loop tests (M-04) + permission gate (M-13) + recovery (M-28).

Mock model, mock tools, in-memory checkpointer; the real
``PermissionPolicy`` is exercised end-to-end for the ask/deny flows.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import ToolException, tool
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Command

from app.core.config import clear_settings_cache
from app.core.graph import (
    _failed_tool_messages,
    build_graph,
    build_human_node,
    default_run_config,
    recovery_nudge,
    resume_command,
    route_after_agent,
    tool_error_text,
)
from app.core.permissions import Decision, PermissionConfig, PermissionPolicy


@pytest.fixture(autouse=True)
def _cold_settings_cache():
    """Every test runs against a cold settings cache (AGENTS.md)."""
    clear_settings_cache()
    yield
    clear_settings_cache()


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


# --- M-28: failure recovery -------------------------------------------------


@tool
def boom(text: str) -> str:
    """Always fails — the M-28 recovery fixture."""
    raise ToolException("kaboom: no such file")


class _ScriptedModel:
    """Duck-typed chat model: scripted responses, records every prompt.

    An entry may be an ``Exception`` — it is raised instead of returned,
    which is how the provider-failure (M-28 retry) tests drive the seam
    without a real API. Instances also record the exact prompt list of
    each call so tests can assert on the recovery nudge.
    """

    def __init__(self, *responses: AIMessage | Exception) -> None:
        self._responses: list[AIMessage | Exception] = list(responses)
        self.prompts: list[list[Any]] = []

    async def ainvoke(self, messages: Any, **kwargs: Any) -> AIMessage:
        self.prompts.append(list(messages))
        if not self._responses:
            raise AssertionError("model called more often than scripted")
        response = self._responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def _recovery_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, **env: str) -> None:
    """Sandbox the M-28 settings for one test (AGENTS.md config rules)."""
    monkeypatch.chdir(tmp_path)  # ignore the repo-root .env
    for name in list(os.environ):
        if name.startswith("ORYA_"):
            monkeypatch.delenv(name, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    clear_settings_cache()


async def test_failed_tool_is_error_message_not_a_crashed_run(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    """A ToolException must not kill the turn: it becomes data (M-28)."""
    _recovery_env(monkeypatch, tmp_path, ORYA_RECOVERY_MAX_ROUNDS="0")
    model = _ScriptedModel(
        _ai_with_calls(("boom", {"text": "x"}, "c1")),
        AIMessage(content="handled"),
    )
    graph = build_graph([boom, echo], model, None, MockPolicy("allow"))

    result = await graph.ainvoke({"messages": [HumanMessage("hi")]})

    errors = [
        m
        for m in result["messages"]
        if isinstance(m, ToolMessage) and m.status == "error"
    ]
    assert len(errors) == 1
    assert "kaboom: no such file" in errors[0].content
    assert result["messages"][-1].content == "handled"
    # the budget key is only written once recovery actually ran (it didn't)
    assert not result.get("recovery_rounds")


async def test_failed_action_asks_for_alternatives_and_retries():
    """The recover node demands alternatives and the loop tries one (M-28)."""
    model = _ScriptedModel(
        _ai_with_calls(("boom", {"text": "x"}, "c1")),
        _ai_with_calls(("echo", {"text": "second try"}, "c2")),
        AIMessage(content="done"),
    )
    graph = build_graph([boom, echo], model, None, MockPolicy("allow"))

    result = await graph.ainvoke({"messages": [HumanMessage("hi")]})

    errors = [m for m in result["messages"] if getattr(m, "status", None) == "error"]
    assert len(errors) == 1
    assert any(
        isinstance(m, ToolMessage) and "echo: second try" in m.content
        for m in result["messages"]
    )
    assert result["messages"][-1].content == "done"
    assert result["recovery_rounds"] == 0  # success reset the budget

    # The 2nd model call is the recover nudge: invoke-local, error framed
    # as untrusted data, exactly one tool call demanded, 5 variants asked.
    assert len(model.prompts) == 3
    nudge = model.prompts[1][-1]
    assert isinstance(nudge, HumanMessage)
    assert nudge.content.startswith("# Recovery: the previous action failed")
    assert "kaboom: no such file" in nudge.content
    assert "up to 5 alternative" in nudge.content
    assert "EXACTLY ONE tool" in nudge.content
    assert "[UNTRUSTED_CONTENT_START]" in nudge.content
    # ...and it never leaked into the persisted conversation history.
    assert not any(
        isinstance(m, HumanMessage) and "# Recovery" in str(m.content)
        for m in result["messages"]
    )


async def test_recovery_budget_exhausted_returns_to_plain_agent(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    """After ``recovery_max_rounds`` failures no further recover calls (M-28)."""
    _recovery_env(monkeypatch, tmp_path, ORYA_RECOVERY_MAX_ROUNDS="2")
    model = _ScriptedModel(
        _ai_with_calls(("boom", {"text": "x"}, "c1")),
        _ai_with_calls(("boom", {"text": "x"}, "c2")),
        _ai_with_calls(("boom", {"text": "x"}, "c3")),
        AIMessage(content="cannot do it"),
    )
    graph = build_graph([boom], model, None, MockPolicy("allow"))

    result = await graph.ainvoke({"messages": [HumanMessage("hi")]})

    # agent -> recover -> recover -> agent: exactly 4 calls, then give-up.
    assert len(model.prompts) == 4
    errors = [m for m in result["messages"] if getattr(m, "status", None) == "error"]
    assert len(errors) == 3
    assert result["messages"][-1].content == "cannot do it"
    assert result["recovery_rounds"] == 2  # kept, only a success/turn resets it


async def test_unexpected_tool_bug_does_not_kill_the_run():
    """A plain exception inside a tool is converted too, with its class (M-28)."""

    @tool
    def buggy(text: str) -> str:
        """Raises a non-ToolException (a real bug)."""
        raise ValueError("unexpected")

    model = _ScriptedModel(
        _ai_with_calls(("buggy", {"text": "x"}, "c1")),
        AIMessage(content="noted"),
    )
    graph = build_graph([buggy], model, None, MockPolicy("allow"))

    result = await graph.ainvoke({"messages": [HumanMessage("hi")]})

    errors = [m for m in result["messages"] if getattr(m, "status", None) == "error"]
    assert len(errors) == 1
    assert errors[0].content == "ValueError: unexpected"
    assert result["messages"][-1].content == "noted"  # the run kept going


async def test_permission_denial_does_not_trigger_recovery():
    """Refusals are not errors: the deny path never enters recover (M-28)."""
    model = _ScriptedModel(
        _ai_with_calls(("echo", {"text": "x"}, "c1")),
        AIMessage(content="understood"),
    )
    graph = build_graph([echo], model, None, MockPolicy("deny"))

    result = await graph.ainvoke({"messages": [HumanMessage("hi")]})

    assert len(model.prompts) == 2  # plain agent twice — no recover round
    assert any(
        isinstance(m, ToolMessage) and m.content.startswith("Denied by policy")
        for m in result["messages"]
    )
    second_call_last = model.prompts[1][-1]
    assert not isinstance(second_call_last, HumanMessage)
    assert not result.get("recovery_rounds")  # refusals never touch the budget


async def test_recover_batch_is_permission_gated():
    """Retries never bypass the human node: every round asks again (M-28)."""
    model = _ScriptedModel(
        _ai_with_calls(("boom", {"text": "x"}, "c1")),
        _ai_with_calls(("echo", {"text": "second try"}, "c2")),
        AIMessage(content="done"),
    )
    policy = MockPolicy(decision="ask")
    graph = build_graph([boom, echo], model, InMemorySaver(), policy)
    config = default_run_config("thread-recover-gate")

    first = await graph.ainvoke({"messages": [HumanMessage("hi")]}, config)
    assert isinstance(first["messages"][-1], AIMessage)
    state = await graph.aget_state(config)
    assert state.next == ("human",)  # paused on the original call

    second = await graph.ainvoke(resume_command("approve"), config)
    assert second["messages"][-1].content == ""  # recover's tool-call answer
    state = await graph.aget_state(config)
    assert state.next == ("human",)  # the *alternative* asks again
    names = [call["name"] for call in policy.checked]
    assert names[0] == "boom"
    assert names.count("echo") == 1  # the alternative went through the gate too

    final = await graph.ainvoke(resume_command("approve"), config)
    assert final["messages"][-1].content == "done"
    assert any(
        isinstance(m, ToolMessage) and "echo: second try" in m.content
        for m in final["messages"]
    )
    assert final["recovery_rounds"] == 0
    state = await graph.aget_state(config)
    assert state.next == ()


async def test_llm_provider_failure_is_retried_then_succeeds(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    """Transient provider errors are retried, not surfaced (M-28)."""
    _recovery_env(
        monkeypatch,
        tmp_path,
        ORYA_LLM_RETRY_ATTEMPTS="3",
        ORYA_LLM_RETRY_BACKOFF_SECONDS="0",
    )
    model = _ScriptedModel(
        ValueError("rate limited"),
        ValueError("connection reset"),
        AIMessage(content="ok after retries"),
    )
    graph = build_graph([echo], model, None, MockPolicy("allow"))

    result = await graph.ainvoke({"messages": [HumanMessage("hi")]})

    assert result["messages"][-1].content == "ok after retries"
    assert len(model.prompts) == 3  # two failures + the successful call


async def test_llm_provider_failure_raises_after_the_budget_is_spent(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    """When every attempt fails the original error still reaches the API."""
    _recovery_env(
        monkeypatch,
        tmp_path,
        ORYA_LLM_RETRY_ATTEMPTS="2",
        ORYA_LLM_RETRY_BACKOFF_SECONDS="0",
    )
    model = _ScriptedModel(RuntimeError("boom down"), RuntimeError("boom down"))
    graph = build_graph([echo], model, None, MockPolicy("allow"))

    with pytest.raises(RuntimeError, match="boom down"):
        await graph.ainvoke({"messages": [HumanMessage("hi")]})

    assert len(model.prompts) == 2


async def test_llm_auth_error_is_not_retried(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    """Non-retryable provider failures fail fast — one attempt only (M-28)."""

    class AuthenticationError(Exception):
        """Name-matched by ``_is_retryable`` (providers raise their own)."""

    _recovery_env(
        monkeypatch,
        tmp_path,
        ORYA_LLM_RETRY_ATTEMPTS="3",
        ORYA_LLM_RETRY_BACKOFF_SECONDS="0",
    )
    model = _ScriptedModel(AuthenticationError("bad api key"))
    graph = build_graph([echo], model, None, MockPolicy("allow"))

    with pytest.raises(AuthenticationError, match="bad api key"):
        await graph.ainvoke({"messages": [HumanMessage("hi")]})

    assert len(model.prompts) == 1


def test_tool_error_text_keeps_tool_exceptions_clean():
    """ToolException -> verbatim message; anything else keeps its class."""
    assert tool_error_text(ToolException("file not found")) == "file not found"
    assert tool_error_text(ValueError("bad value")) == "ValueError: bad value"


def test_failed_tool_messages_only_reads_the_trailing_error_batch():
    batch = [
        HumanMessage("hi"),
        _ai_with_calls(("boom", {"text": "x"}, "c1")),
        ToolMessage(content="first worked", tool_call_id="c0", status="success"),
        ToolMessage(content="kaboom", tool_call_id="c1", status="error"),
    ]
    previous = ToolMessage(content="old error", tool_call_id="old", status="error")

    failed = _failed_tool_messages([previous, *batch])

    assert [m.content for m in failed] == ["kaboom"]  # stops at the AI message


def test_recovery_nudge_frames_errors_as_untrusted_and_counts_variants():
    messages = [
        HumanMessage("hi"),
        _ai_with_calls(("boom", {"text": "x"}, "c1")),
        ToolMessage(
            content="kaboom: no such file",
            tool_call_id="c1",
            name="boom",
            status="error",
        ),
    ]

    nudge = recovery_nudge(messages, variants=4)

    assert isinstance(nudge, HumanMessage)
    assert "up to 4 alternative" in nudge.content
    assert "EXACTLY ONE tool" in nudge.content
    assert '{"text": "x"}' in nudge.content  # the failing args, for context
    start = nudge.content.index("[UNTRUSTED_CONTENT_START]")
    end = nudge.content.index("[UNTRUSTED_CONTENT_END]")
    assert start < nudge.content.index("kaboom: no such file") < end
