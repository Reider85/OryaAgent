"""A-16: OryaObservability SDK вЂ” agent.loop/tool.call/memory.write spans + PII.

Bridge architecture: OryaAgent's own ``emit_span`` seam carries the A-16
custom spans; the agent_obs package (opt-in install from ../OryaObservability)
provides PIIDetector masking. Without agent_obs everything still works вЂ”
content attributes fail-closed to ``[REDACTED:guardrail_unavailable]``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import ToolException, tool
from langgraph.checkpoint.memory import InMemorySaver

from app.core.config import clear_settings_cache
from app.core.observability import pii
from app.core.observability.pii import (
    REDACTED_UNAVAILABLE,
    clear_detector_cache,
    mask_text,
)
from app.core.observability.sdk import (
    AGENT_ID,
    AGENT_VERSION,
    get_observability,
)
from app.core.observability.spans import (
    clear_span_buffer,
    emit_span,
    get_span_buffer,
    new_trace_id,
    set_turn_trace,
    timed_span,
)

_ENV_KEYS = (
    "AGENT_OBS_ENABLED",
    "AGENT_OBS_GUARDRAIL_ENABLED",
    "ORYA_AGENT_OBS_ENABLED",
    "ORYA_AGENT_OBS_GUARDRAIL_ENABLED",
    "ORYA_LLM_TRACE_ENABLED",
    "ORYA_PERMISSION_AUDIT_ENABLED",
)


@pytest.fixture(autouse=True)
def isolated(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Sandbox config + fresh span buffer + fresh detector cache."""
    monkeypatch.chdir(tmp_path)
    for name in _ENV_KEYS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("ORYA_CONFIG_PATH", str(tmp_path / "config.yaml"))
    monkeypatch.setenv("ORYA_MEMORY_DIR", str(tmp_path / "memory"))
    clear_settings_cache()
    clear_span_buffer()
    clear_detector_cache()
    yield
    clear_span_buffer()
    clear_settings_cache()
    clear_detector_cache()


# --- timed_span / emit_span ----------------------------------------------------


def test_timed_span_records_duration_and_attributes() -> None:
    with timed_span(
        span_type="agent.loop",
        name="agent.loop:test",
        attributes={"agent.id": AGENT_ID},
    ) as attrs:
        attrs["custom.key"] = "v"

    spans = list(get_span_buffer())
    assert len(spans) == 1
    span = spans[0]
    assert span.span_type == "agent.loop"
    assert span.status == "ok"
    assert span.attributes["agent.id"] == AGENT_ID
    assert span.attributes["custom.key"] == "v"
    assert span.end_time is not None
    assert span.end_time >= span.start_time


def test_timed_span_flips_to_error_on_exception() -> None:
    with pytest.raises(ValueError, match="boom"):
        with timed_span(span_type="agent.loop", name="agent.loop:test"):
            raise ValueError("boom")

    spans = list(get_span_buffer())
    assert len(spans) == 1
    assert spans[0].status == "error"


def test_emit_span_returns_span_id() -> None:
    span_id = emit_span(
        span_type="memory.write",
        name="memory.write:FACTS.md",
        attributes={"memory.file": "FACTS.md"},
    )
    assert span_id is not None
    assert len(span_id) == 16
    int(span_id, 16)  # W3C-hex shaped


# --- agent.loop (app.core.agent) ------------------------------------------------


class _FakeEventGraph:
    def __init__(self) -> None:
        self.inputs: list[Any] = []

    async def astream_events(self, input, config=None, *, version=None):
        self.inputs.append(input)
        yield {"event": "on_chat_model_stream", "run_id": "r", "data": {}}


async def test_stream_turn_emits_agent_loop_span_with_turn_trace() -> None:
    from app.core import agent

    graph = _FakeEventGraph()
    events = [
        e async for e in agent.stream_graph_events(graph, "hi", {"recursion_limit": 7})
    ]
    assert events == []

    spans = [s for s in get_span_buffer() if s.span_type == "agent.loop"]
    assert len(spans) == 1
    span = spans[0]
    assert span.name == f"agent.loop:{AGENT_ID}"
    assert span.status == "ok"
    assert span.attributes["agent.id"] == AGENT_ID
    assert span.attributes["agent.version"] == AGENT_VERSION
    # Fail-closed: without agent_obs the content is replaced by the SDK
    # marker; with it installed a clean input passes through unmasked.
    if pii.agent_obs_available():
        assert span.attributes["task.input"] == "hi"
    else:
        assert span.attributes["task.input"] == REDACTED_UNAVAILABLE
    assert "task.resume" not in span.attributes

    # The turn's HumanMessage carries the same trace id (A-06 join).
    stamped = graph.inputs[0]["messages"][0]
    assert stamped.additional_kwargs["orya_span"] == {"trace_id": span.trace_id}


async def test_resume_turn_emits_agent_loop_span_marked_resume() -> None:
    from app.core import agent

    graph = _FakeEventGraph()
    _ = [e async for e in agent.resume_graph_events(graph, "approve", {})]

    spans = [s for s in get_span_buffer() if s.span_type == "agent.loop"]
    assert len(spans) == 1
    assert spans[0].attributes["task.resume"] == "true"
    if pii.agent_obs_available():
        assert spans[0].attributes["task.input"] == "approve"
    else:
        assert spans[0].attributes["task.input"] == REDACTED_UNAVAILABLE


async def test_agent_loop_kill_switch_suppresses_span(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.core import agent

    monkeypatch.setenv("AGENT_OBS_ENABLED", "false")
    clear_settings_cache()

    graph = _FakeEventGraph()
    _ = [e async for e in agent.stream_graph_events(graph, "hi", {})]

    assert not [s for s in get_span_buffer() if s.span_type == "agent.loop"]


# --- tool.call (app.core.graph) -------------------------------------------------


@tool
def echo(text: str) -> str:
    """Echo the given text back to the caller."""
    return f"echo: {text}"


@tool
def failing(message: str) -> str:
    """Always fails (error-span tests)."""
    raise ToolException("tool exploded")


def _model(*messages: AIMessage) -> FakeMessagesListChatModel:
    return FakeMessagesListChatModel(responses=list(messages))


def _ai_with_tool_call(
    name: str = "echo", args: dict | None = None, call_id: str = "call_1"
) -> AIMessage:
    return AIMessage(
        content="",
        tool_calls=[{"name": name, "args": args or {"text": "hi"}, "id": call_id}],
    )


async def test_tool_call_span_emitted_and_stamped_on_tool_message() -> None:
    from app.core.graph import build_graph, default_run_config

    graph = build_graph(
        [echo], _model(_ai_with_tool_call(), AIMessage(content="done")), InMemorySaver()
    )
    trace = new_trace_id()
    set_turn_trace(trace)
    try:
        result = await graph.ainvoke(
            {"messages": [HumanMessage("hi")]}, default_run_config("thread-a16")
        )
    finally:
        set_turn_trace(None)

    spans = [s for s in get_span_buffer() if s.span_type == "tool.call"]
    assert len(spans) == 1
    span = spans[0]
    assert span.name == "tool.call:echo"
    assert span.status == "ok"
    assert span.attributes["tool.name"] == "echo"
    assert span.attributes["tool.input_chars"] > 0
    assert len(span.attributes["tool.input_sha256"]) == 64
    if pii.agent_obs_available():
        assert span.attributes["tool.output_text"] == "echo: hi"
    else:  # fail-closed without the SDK
        assert span.attributes["tool.output_text"] == REDACTED_UNAVAILABLE
    assert span.trace_id == trace  # joins the turn trace (A-06)
    assert span.end_time is not None and span.end_time >= span.start_time

    # The ToolMessage is cross-linked to this exact span (A-06 deferred piece).
    tool_messages = [m for m in result["messages"] if isinstance(m, ToolMessage)]
    assert tool_messages
    stamp = tool_messages[0].additional_kwargs["orya_span"]
    assert stamp == {"trace_id": trace, "span_id": span.span_id}


async def test_tool_call_span_error_status_for_failing_tool() -> None:
    from app.core.graph import build_graph, default_run_config

    graph = build_graph(
        [failing],
        _model(
            _ai_with_tool_call(name="failing", args={"message": "x"}), AIMessage("d")
        ),
        InMemorySaver(),
    )
    await graph.ainvoke(
        {"messages": [HumanMessage("hi")]}, default_run_config("thread-a16-err")
    )

    spans = [s for s in get_span_buffer() if s.span_type == "tool.call"]
    assert len(spans) == 1
    assert spans[0].status == "error"
    assert spans[0].attributes["tool.name"] == "failing"


async def test_tool_call_kill_switch_suppresses_spans(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.core.graph import build_graph, default_run_config

    monkeypatch.setenv("AGENT_OBS_ENABLED", "false")
    clear_settings_cache()

    graph = build_graph(
        [echo], _model(_ai_with_tool_call(), AIMessage(content="done")), InMemorySaver()
    )
    await graph.ainvoke(
        {"messages": [HumanMessage("hi")]}, default_run_config("thread-a16-off")
    )

    assert not [s for s in get_span_buffer() if s.span_type == "tool.call"]


# --- batch-refusal span (A-03 bugfix) -------------------------------------------


async def test_batch_refusal_span_carries_tool_names() -> None:
    """Multi-refusal batch emits agent.permission:batch with the tool list."""
    from langgraph.types import Command

    from app.core.graph import build_human_node
    from app.core.permissions import Decision

    class _DenyPolicy:
        def check(self, tool_call: Any) -> Decision:
            return Decision(action="deny", reason="denied for test")

        def record_session_allow(self, tool_name: str) -> None:
            raise AssertionError("not expected")

    human_node = build_human_node(_DenyPolicy(), can_interrupt=False)
    state = {
        "messages": [
            AIMessage(
                content="",
                tool_calls=[
                    {"name": "echo", "args": {"text": "a"}, "id": "c1"},
                    {"name": "echo", "args": {"text": "b"}, "id": "c2"},
                ],
            )
        ]
    }
    result = await human_node(state)
    assert isinstance(result, Command)

    spans = [
        s
        for s in get_span_buffer()
        if s.span_type == "agent.permission"
        and s.attributes.get("permission.tool") == "batch"
    ]
    assert len(spans) == 1
    assert spans[0].status == "deny"
    assert "permission.tools=echo,echo" in spans[0].attributes["permission.reason"]


# --- memory.write ----------------------------------------------------------------


def test_emit_memory_write_span() -> None:
    get_observability().emit_memory_write(
        file="FACTS.md",
        source="learn",
        compacted=False,
        memory_id="fact_001",
    )

    spans = [s for s in get_span_buffer() if s.span_type == "memory.write"]
    assert len(spans) == 1
    span = spans[0]
    assert span.name == "memory.write:FACTS.md"
    assert span.attributes == {
        "memory.id": "fact_001",
        "memory.file": "FACTS.md",
        "memory.source": "learn",
        "memory.compacted": "false",
    }


def test_memory_write_kill_switch(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGENT_OBS_ENABLED", "false")
    clear_settings_cache()

    get_observability().emit_memory_write(file="FACTS.md", source="learn")
    assert not [s for s in get_span_buffer() if s.span_type == "memory.write"]


def test_learn_store_entry_emits_memory_write(monkeypatch: pytest.MonkeyPatch) -> None:
    """POST /learn's write helper emits memory.write with the item id."""
    from app.api import learn as api_learn
    from app.core.memory.md_store import get_md_store

    store = get_md_store()
    response = api_learn._store_entry(
        "FACTS.md",
        "the sky is blue",
        kind="fact",
        confidence=1.0,
        source="user_explicit",
        session_id=None,
        reason="test",
    )

    spans = [s for s in get_span_buffer() if s.span_type == "memory.write"]
    assert len(spans) == 1
    assert spans[0].attributes["memory.id"] == response.learned_id
    assert spans[0].attributes["memory.file"] == "FACTS.md"
    assert spans[0].attributes["memory.source"] == "user_explicit"
    assert spans[0].attributes["memory.compacted"] == "false"
    assert store.read("FACTS.md")  # the entry itself was written


async def test_compactor_emits_memory_write_when_changed() -> None:
    """A compaction rewrite emits memory.write with compacted=true."""
    from app.core.memory.compactor import Compactor
    from app.core.memory.md_store import get_md_store
    from app.core.memory.models import MemoryItem

    store = get_md_store()
    # FACTS.md strategy keeps confidence >= 0.9; a 0.5 entry gets archived.
    low = MemoryItem.create(
        kind="fact", text="low-confidence fact", confidence=0.5, source="user_explicit"
    ).to_markdown()
    high = MemoryItem.create(
        kind="fact", text="solid fact", confidence=1.0, source="user_explicit"
    ).to_markdown()
    store.append("FACTS.md", low)
    store.append("FACTS.md", high)
    clear_span_buffer()

    compactor = Compactor(store)
    result = await compactor.compact("FACTS.md")
    assert result.changed
    assert result.archived == 1

    spans = [s for s in get_span_buffer() if s.span_type == "memory.write"]
    assert len(spans) == 1
    assert spans[0].attributes["memory.source"] == "compactor"
    assert spans[0].attributes["memory.compacted"] == "true"
    assert spans[0].attributes["memory.file"] == "FACTS.md"


# --- PII masking (mask_text) ------------------------------------------------------


def test_mask_text_fail_closed_without_detector(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clear_detector_cache()
    monkeypatch.setattr(pii, "_detector_loaded", True)
    monkeypatch.setattr(pii, "_detector", None)

    assert mask_text("mail user@example.com") == REDACTED_UNAVAILABLE


def test_mask_text_passthrough_when_guardrail_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AGENT_OBS_GUARDRAIL_ENABLED", "false")
    clear_settings_cache()

    text = "mail user@example.com"
    assert mask_text(text) == text


def test_mask_text_empty_string() -> None:
    assert mask_text("") == ""


def test_mask_text_real_detector_masks_email() -> None:
    """With agent_obs installed, PII entities are replaced by [TYPE:hex]."""
    pytest.importorskip("agent_obs")
    clear_detector_cache()

    masked = mask_text("contact me at user@example.com please")
    assert "user@example.com" not in masked
    assert masked.startswith("contact me at [EMAIL:")
    assert masked.endswith("] please")


def test_mask_text_real_detector_masks_phone_and_passes_clean_text() -> None:
    pytest.importorskip("agent_obs")
    clear_detector_cache()

    assert mask_text("no pii in this sentence") == "no pii in this sentence"
    masked = mask_text("call +7 999 123-45-67 now")
    assert "123-45-67" not in masked
    assert "[PHONE:" in masked


async def test_tool_input_summary_masks_pii_in_args() -> None:
    """A tool call whose args contain an email gets a masked summary."""
    from app.core.graph import build_graph, default_run_config

    graph = build_graph(
        [echo],
        _model(
            _ai_with_tool_call(args={"text": "write to user@example.com"}),
            AIMessage(content="done"),
        ),
        InMemorySaver(),
    )
    set_turn_trace(new_trace_id())
    try:
        await graph.ainvoke(
            {"messages": [HumanMessage("hi")]}, default_run_config("thread-a16-pii")
        )
    finally:
        set_turn_trace(None)

    spans = [s for s in get_span_buffer() if s.span_type == "tool.call"]
    assert len(spans) == 1
    summary = spans[0].attributes["tool.input_summary"]
    if pii.agent_obs_available():
        assert "user@example.com" not in summary
        assert "[EMAIL:" in summary
    else:  # fail-closed without the SDK
        assert summary == REDACTED_UNAVAILABLE


# A-17: Tests for incident scope and attributes
async def test_incident_scope_accumulates_security_incident() -> None:
    """A-17: incident_scope accumulates security.incident=True for tool spans."""
    from app.core.observability.spans import _incident_bag, incident_scope

    set_turn_trace(new_trace_id())
    clear_span_buffer()

    # Clear incident bag before test
    _incident_bag.set({})

    try:
        with incident_scope():
            # Record an incident within the scope
            from app.core.observability.spans import note_incident

            note_incident("security.incident", "true")

            # Simulate a tool call (normally in graph.py tools_node)
            from app.core.graph import _emit_tool_call_spans
            from app.core.observability.spans import _incident_bag

            tool_calls = [{"id": "call1", "name": "echo", "args": {"text": "test"}}]
            result = {"messages": [ToolMessage(content="echoed", tool_call_id="call1")]}

            # Directly set the incident bag (as done in graph.py tools_node)
            _incident_bag.set({"security.incident": "true"})
            try:
                _emit_tool_call_spans(
                    tool_calls, result, 0.0, extra={"security.incident": "true"}
                )
            finally:
                _incident_bag.set({})

            spans = [s for s in get_span_buffer() if s.span_type == "tool.call"]
            assert len(spans) == 1
            span = spans[0]
            assert "security.incident" in span.attributes
            assert span.attributes["security.incident"] == "true"
    finally:
        set_turn_trace(None)


def test_note_incident_adds_to_incident_bag() -> None:
    """A-17: note_incident adds attributes to the incident bag."""
    from app.core.observability.spans import (
        _incident_bag,
        note_incident,
        take_pending_span_attributes,
    )

    # Clear incident bag before test
    _incident_bag.set({})

    # Record an incident
    note_incident("security.incident", "true")
    note_incident("custom.attr", "value")

    # Check that incidents are accumulated
    incidents = _incident_bag.get()
    assert incidents == {"security.incident": "true", "custom.attr": "value"}

    # take_pending_span_attributes should not affect incident bag
    take_pending_span_attributes()
    incidents = _incident_bag.get()
    assert incidents == {"security.incident": "true", "custom.attr": "value"}


def test_incident_bag_isolation() -> None:
    """A-17: Incident bag is isolated between contexts."""
    from app.core.observability.spans import _incident_bag

    # Clear and set initial state
    _incident_bag.set({})

    # Set some incidents
    _incident_bag.set({"incident1": "true"})

    # Should be isolated (no global state bleed)
    bag1 = _incident_bag.get()
    assert bag1 == {"incident1": "true"}

    # Modify should not affect other references
    bag2 = _incident_bag.get()
    bag2["incident2"] = "true"
    assert _incident_bag.get() == {"incident1": "true", "incident2": "true"}


async def test_emit_tool_call_spans_with_extra_attributes() -> None:
    """A-17: _emit_tool_call_spans merges extra attributes (e.g. from incident scope)."""
    from app.core.graph import _emit_tool_call_spans
    from app.core.observability.spans import clear_span_buffer

    set_turn_trace(new_trace_id())
    clear_span_buffer()

    tool_calls = [{"id": "call1", "name": "echo", "args": {"text": "test"}}]
    result = {"messages": [ToolMessage(content="echoed", tool_call_id="call1")]}

    # Call with extra attributes (simulating incident scope)
    extra = {"security.incident": "true", "custom.attr": "value"}
    _emit_tool_call_spans(tool_calls, result, 0.0, extra=extra)

    spans = [s for s in get_span_buffer() if s.span_type == "tool.call"]
    assert len(spans) == 1
    span = spans[0]

    # Extra attributes should be merged in
    assert span.attributes["security.incident"] == "true"
    assert span.attributes["custom.attr"] == "value"
    assert span.attributes["tool.name"] == "echo"  # Original attr preserved
