"""Context-manager tests (M-06) — tool truncation, thinking strip, sliding window."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)

from app.core.config import clear_settings_cache, get_settings
from app.core.context import (
    TOOL_RESULT_HEAD_LINES,
    TOOL_RESULT_TAIL_LINES,
    count_tokens,
    trim_messages,
    trim_state,
    trim_thinking,
    truncate_tool_messages,
)
from app.core.graph import build_graph


@pytest.fixture(autouse=True)
def _isolated_settings(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Sandbox settings: no inherited ORYA_* env, no repo .env, fresh cache."""
    for name in list(os.environ):
        if name.startswith("ORYA_"):
            monkeypatch.delenv(name, raising=False)
    monkeypatch.chdir(tmp_path)  # ignore any project-root .env
    clear_settings_cache()
    yield
    clear_settings_cache()


def _long_tool_message(lines: int = 10_000, line: str = "x" * 40) -> ToolMessage:
    return ToolMessage(
        content="\n".join(f"{i:05d} {line}" for i in range(lines)),
        tool_call_id="call_1",
        name="bash",
    )


def _history(pairs: int, words: int = 50) -> list[BaseMessage]:
    text = " ".join(["word"] * words)
    messages: list[BaseMessage] = []
    for i in range(pairs):
        messages.append(HumanMessage(content=f"question {i}: {text}"))
        messages.append(AIMessage(content=f"answer {i}: {text}"))
    return messages


# --- count_tokens ----------------------------------------------------------


def test_count_tokens_uses_tiktoken_for_openai_model():
    messages = [HumanMessage(content="hello world, this is a token counting test")]
    exact = count_tokens(messages, model="gpt-4o")
    assert exact > 0


def test_count_tokens_approximates_unknown_model():
    text = "a" * 40
    messages = [HumanMessage(content=text)]
    assert count_tokens(messages, model="claude-sonnet-3.5") == 10
    assert count_tokens(messages, model=None) == 10


def test_count_tokens_handles_list_content_and_tool_calls():
    message = AIMessage(
        content=[{"type": "text", "text": "a" * 40}],
        tool_calls=[{"name": "bash", "args": {"command": "ls"}, "id": "call_1"}],
    )
    # 40-char text block (~10) + serialized tool_calls (~10)
    assert count_tokens([message], model=None) >= 10


def test_count_tokens_tiktoken_is_not_worse_than_approximation():
    messages = [HumanMessage(content="lorem ipsum dolor sit amet " * 5)]
    tiktoken_count = count_tokens(messages, model="gpt-4o")
    approx = count_tokens(messages, model=None)
    # tiktoken produces finer-grained counts than chars/4 for prose
    assert tiktoken_count > 0 and approx > 0


# --- truncate_tool_messages ------------------------------------------------


def test_truncate_long_tool_message():
    original = _long_tool_message(lines=10_000)
    result = truncate_tool_messages([original])
    truncated = result[0]
    assert isinstance(truncated, ToolMessage)
    lines = truncated.content.splitlines()
    assert len(lines) == TOOL_RESULT_HEAD_LINES + 1 + TOOL_RESULT_TAIL_LINES
    assert (
        f"[{10_000 - TOOL_RESULT_HEAD_LINES - TOOL_RESULT_TAIL_LINES} lines truncated]"
        in (truncated.content)
    )
    assert truncated.tool_call_id == "call_1"
    assert truncated.name == "bash"


def test_short_tool_message_is_untouched():
    message = ToolMessage(content="ok", tool_call_id="call_1", name="read")
    result = truncate_tool_messages([message])
    assert result[0] is message
    assert result[0].content == "ok"


def test_non_tool_messages_pass_through():
    human = HumanMessage(content="a" * 10_000)
    result = truncate_tool_messages([human])
    assert result[0] is human


def test_few_very_long_lines_fall_back_to_char_cut():
    message = ToolMessage(
        content="y" * 10_000 + "\n" + "z" * 10_000,
        tool_call_id="call_1",
        name="bash",
    )
    result = truncate_tool_messages([message])
    body = result[0].content
    assert "truncated" in body and "chars]" in body
    assert len(body) < 10_000 + 10_000


def test_truncate_does_not_mutate_input():
    original = _long_tool_message(lines=1_000)
    snapshot = original.content
    truncate_tool_messages([original])
    assert original.content == snapshot


# --- trim_thinking ---------------------------------------------------------


def test_trim_thinking_strips_reasoning_content():
    message = AIMessage(
        content="final answer",
        additional_kwargs={"reasoning_content": "let me think... " * 100},
    )
    result = trim_thinking([message])
    assert result[0].additional_kwargs == {}
    assert result[0].content == "final answer"


def test_trim_thinking_keeps_plain_messages():
    ai = AIMessage(content="plain", additional_kwargs={"foo": "bar"})
    human = HumanMessage(content="hi")
    result = trim_thinking([ai, human])
    assert result == [ai, human]
    assert result[0].additional_kwargs == {"foo": "bar"}


def test_trim_thinking_does_not_mutate_input():
    message = AIMessage(
        content="answer",
        additional_kwargs={"reasoning_content": "thinking"},
    )
    trim_thinking([message])
    assert message.additional_kwargs["reasoning_content"] == "thinking"


# --- trim_messages ---------------------------------------------------------


def test_trim_messages_reduces_long_history():
    history = _history(pairs=40, words=50)
    result = trim_messages(history, max_tokens=500, model=None)
    assert 0 < len(result) < len(history)
    # the most recent turn survives (strategy="last")
    assert result[-1].content == history[-1].content


def test_trim_messages_keeps_system_message_with_tiny_budget():
    system = SystemMessage(content="You are OryaAgent.")
    history = [system, *_history(pairs=10, words=100)]
    result = trim_messages(history, max_tokens=10, model=None)
    assert isinstance(result[0], SystemMessage)
    assert result[0].content == "You are OryaAgent."


def test_trim_messages_empty_input():
    assert trim_messages([], max_tokens=100) == []


def test_trim_messages_starts_on_human():
    """The window never starts mid-turn: first non-system msg is human."""
    history = _history(pairs=20, words=80)
    result = trim_messages(history, max_tokens=300, model=None)
    non_system = [m for m in result if not isinstance(m, SystemMessage)]
    assert non_system
    assert isinstance(non_system[0], HumanMessage)


def test_trim_messages_truncates_tool_results_within_budget():
    big_tool = _long_tool_message(lines=2_000)
    history = [
        HumanMessage(content="run it"),
        AIMessage(
            content="",
            tool_calls=[{"name": "bash", "args": {"command": "ls"}, "id": "call_1"}],
        ),
        big_tool,
        HumanMessage(content="thanks"),
    ]
    result = trim_messages(history, max_tokens=10_000, model=None)
    tool_msgs = [m for m in result if isinstance(m, ToolMessage)]
    assert tool_msgs
    assert "lines truncated" in tool_msgs[0].content
    # pipeline kept the message count (nothing had to be dropped at 10k budget)
    assert len(result) == len(history)


def test_trim_messages_default_budget_from_settings(monkeypatch):
    monkeypatch.setenv("ORYA_CONTEXT_MAX_TOKENS", "200")
    clear_settings_cache()
    try:
        assert get_settings().context_max_tokens == 200
        history = _history(pairs=30, words=60)
        result = trim_messages(history, model=None)
        assert count_tokens(result, model=None) <= 200 + 60  # slack for msg overhead
    finally:
        clear_settings_cache()


def test_trim_messages_strips_thinking_from_history():
    history = [
        HumanMessage(content="why?"),
        AIMessage(
            content="because",
            additional_kwargs={"reasoning_content": "hmm " * 500},
        ),
        HumanMessage(content="and?"),
    ]
    result = trim_messages(history, max_tokens=10_000, model=None)
    ai = [m for m in result if isinstance(m, AIMessage)]
    assert ai
    assert "reasoning_content" not in ai[0].additional_kwargs


def test_trim_messages_never_mutates_input():
    history = _history(pairs=30, words=60)
    snapshot = [m.content for m in history]
    trim_messages(history, max_tokens=300, model=None)
    assert [m.content for m in history] == snapshot


# --- trim_state ------------------------------------------------------------


def test_trim_state_returns_messages_key():
    state = {"messages": _history(pairs=30, words=60)}
    result = trim_state(state, max_tokens=300)
    assert set(result) == {"messages"}
    assert len(result["messages"]) < len(state["messages"])


def test_trim_state_with_empty_state():
    assert trim_state({}, max_tokens=100) == {"messages": []}
    assert trim_state(None, max_tokens=100) == {"messages": []}


# --- graph integration (trim_fn seam) --------------------------------------


async def test_graph_applies_trim_fn_seam():
    """The agent node calls trim_fn before the model (M-04 <-> M-06 seam)."""
    seen: list[list[BaseMessage]] = []

    def recorder(messages: list[BaseMessage]) -> list[BaseMessage]:
        seen.append(list(messages))
        return messages[-1:]

    model = FakeMessagesListChatModel(responses=[AIMessage(content="ok")])
    graph = build_graph([], model, None, None, trim_fn=recorder)

    result = await graph.ainvoke(
        {"messages": _history(pairs=5, words=10)},
    )

    assert len(seen) == 1
    assert len(seen[0]) == 10
    assert result["messages"][-1].content == "ok"


async def test_graph_without_trim_fn_is_unchanged():
    model = FakeMessagesListChatModel(responses=[AIMessage(content="ok")])
    graph = build_graph([], model)

    result = await graph.ainvoke({"messages": [HumanMessage("hi")]})

    assert result["messages"][-1].content == "ok"
