"""A-06: turn-trace contextvar — one trace id per agent turn."""

from __future__ import annotations

import pytest

from app.core.llm.tracing import clear_span_buffer
from app.core.observability.spans import (
    current_turn_trace_id,
    emit_span,
    get_span_buffer,
    new_trace_id,
    set_turn_trace,
)


@pytest.fixture(autouse=True)
def _reset_turn_trace():
    set_turn_trace(None)
    clear_span_buffer()
    yield
    set_turn_trace(None)
    clear_span_buffer()


def _cleanup() -> None:
    set_turn_trace(None)
    clear_span_buffer()


def test_no_turn_trace_by_default():
    _cleanup()
    assert current_turn_trace_id() is None


def test_set_and_clear_turn_trace():
    _cleanup()
    set_turn_trace("abc123")
    assert current_turn_trace_id() == "abc123"
    set_turn_trace(None)
    assert current_turn_trace_id() is None


def test_spans_share_turn_trace_inside_turn():
    """Every span of one turn reuses the bound trace id (A-06)."""
    _cleanup()
    set_turn_trace("turn-trace-1")
    try:
        emit_span(
            span_type="llm.call",
            name="llm.call:m1",
            attributes={},
            provider="p",
            model="m1",
        )
        emit_span(
            span_type="agent.permission",
            name="agent.permission:write",
            attributes={"permission.tool": "write"},
        )
        spans = list(get_span_buffer())
    finally:
        _cleanup()

    assert len(spans) == 2
    assert {s.trace_id for s in spans} == {"turn-trace-1"}
    assert spans[0].span_id != spans[1].span_id


def test_spans_get_fresh_trace_outside_turn():
    _cleanup()
    emit_span(span_type="llm.call", name="a", attributes={})
    emit_span(span_type="llm.call", name="b", attributes={})
    spans = list(get_span_buffer())
    assert spans[0].trace_id != spans[1].trace_id
    _cleanup()


def test_clear_by_none_does_not_raise_for_new_set():
    """Reset pattern: write None, then bind again — no token required."""
    _cleanup()
    set_turn_trace("t1")
    set_turn_trace(None)
    set_turn_trace(new_trace_id())
    assert current_turn_trace_id() is not None
    _cleanup()


def test_new_trace_id_is_hex():
    value = new_trace_id()
    assert len(value) == 32
    int(value, 16)
