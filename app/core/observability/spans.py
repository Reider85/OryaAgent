"""Shared span infrastructure for OryaObservability (A-16) and permission audit (A-03).

Replaces llm/tracing.py's SpanRecord and buffer; supports llm.call (A-02),
agent.permission (A-03), and since A-16 the duration spans agent.loop,
tool.call and memory.write (via :func:`timed_span` / ``emit_span(start_time=)``).

A-17 adds pending span attributes (cost/security) and incident tracking for sampler-proxy.

Design:
- SpanRecord: generic record with trace_id, span_id, name, span_type,
  provider, model, attributes, status, start/end_time.
- _span_buffer: process-local deque of SpanRecord (maxlen=1000).
- emit_span(): synchronous span emission (non-blocking, no raise).
- _finalize(): internal buffer append + optional stdout debug.
- Kill-switch control via settings (ORYA_*_TRACE_ENABLED for llm;
  ORYA_PERMISSION_AUDIT_ENABLED for permission spans).

Turn-level trace correlation (A-06): ``set_turn_trace`` binds one
trace id for the whole agent turn; every span created inside the turn
(``llm.call``, ``agent.permission``, ...) reuses it as ``trace_id``
(``_new_ids``). The same id is stamped onto the turn's messages and
therefore lands in the JSONL projection — the cross-link to Langfuse.

A-15 (Langfuse export): ``_finalize`` additionally offers every record
to ``app.core.observability.langfuse`` — the queued OTLP/HTTP JSON
exporter that POSTs batches to Langfuse when configured (auto-on with
``LANGFUSE_HOST`` + keys, kill-switch ``ORYA_LANGFUSE_EXPORT_ENABLED``).
Span ids are W3C-width (16 hex; trace ids 32 hex) so the exported
Langfuse trace/span ids equal the A-06 cross-link ids.

A-17: Pending span attributes and incident tracking for sampler-proxy always-keep spans.
- _pending_span_attrs: ContextVar for cost/security attributes set in cost_router,
  consumed in agent._agent_loop_span to stamp on agent.loop spans.
- _incident_bag: ContextVar for security incidents set in tools_node incident_scope,
  consumed by _emit_tool_call_spans to stamp on tool.call spans.

Usage::

    from app.core.observability.spans import emit_span, get_span_buffer

    # Emit a permission span
    emit_span(
        span_type="agent.permission",
        name="agent.permission:write",
        attributes={
            "permission.tool": "write",
            "permission.action": "allow",
            "permission.reason": "allow-list rule",
            "permission.mode": "strict",
        },
        status="ok",
    )

    # Read spans for tests
    spans = list(get_span_buffer())
    assert spans[0].span_type == "agent.permission"
"""

from __future__ import annotations

import contextlib
import json
import logging
import secrets
import time
from collections import deque
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any

from app.core.config import get_settings
from app.core.observability.langfuse import export_span

logger = logging.getLogger(__name__)

#: How many finished span records the in-process buffer keeps.
#: Shared across span types (llm.call, agent.permission, etc.).
SPAN_BUFFER_MAX = 1000

#: Key in ``BaseMessage.additional_kwargs`` carrying the span cross-link
#: (A-06): ``{"trace_id": ..., "span_id": ...}``. The LLM seam stamps it
#: onto assistant messages (and the turn root onto user/tool messages);
#: the JSONL projection copies it into each event so a session-log line
#: can be joined with the matching Langfuse trace/span.
ORYA_SPAN_KEY = "orya_span"

_span_buffer: deque[SpanRecord] = deque(maxlen=SPAN_BUFFER_MAX)

#: Turn-level trace id (A-06): bound once per agent turn so every span
#: of the turn shares one Langfuse trace. ``None`` outside a turn.
_turn_trace_id: ContextVar[str | None] = ContextVar("orya_turn_trace_id", default=None)

# A-17: Pending span attributes for cost/security attributes
# Set in cost_router (before agent.loop span), consumed in agent._agent_loop_span
_pending_span_attrs: ContextVar[dict[str, Any] | None] = ContextVar(
    "orya_pending_span_attrs", default=None
)

# A-17: Incident bag for security incident tracking in tool.call spans
# Set in tools_node scope (before ainvoke), consumed by _emit_tool_call_spans
_incident_bag: ContextVar[dict[str, str] | None] = ContextVar(
    "orya_incident_bag", default=None
)


@dataclass
class SpanRecord:
    """One span record (generic, supports llm.call and agent.permission etc.)."""

    provider: str
    model: str
    trace_id: str
    span_id: str
    start_time: float
    name: str = ""
    span_type: str = "unset"
    status: str = "unset"
    end_time: float | None = None
    attributes: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.name:
            self.name = f"{self.span_type}:{self.model or self.provider}"

    def to_dict(self) -> dict[str, Any]:
        """Export as dict (for stdout debug, future exporters)."""
        return {
            "trace_id": self.trace_id,
            "span_id": self.span_id,
            "name": self.name,
            "span_type": self.span_type,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "status": self.status,
            "provider": self.provider,
            "model": self.model,
            "attributes": dict(self.attributes),
        }


def get_span_buffer() -> deque[SpanRecord]:
    """The process-local buffer of finished span records."""
    return _span_buffer


def clear_span_buffer() -> None:
    """Drop all buffered span records (tests)."""
    _span_buffer.clear()


def set_turn_trace(trace_id: str | None) -> None:
    """Bind (or clear with ``None``) the turn trace id of this task.

    Reset writes ``None`` instead of a token because a stream may be
    driven from more than one task context (same pattern as
    ``app/api/sessions.py::_stream_in_workspace``).
    """
    _turn_trace_id.set(trace_id)


def current_turn_trace_id() -> str | None:
    """The trace id bound for the current turn, or ``None`` outside one."""
    return _turn_trace_id.get()


def new_trace_id() -> str:
    """A fresh random trace id (same shape as the span ids)."""
    return secrets.token_hex(16)


def _new_ids() -> tuple[str, str]:
    """Generate span ids; reuse the turn trace when one is active (A-06).

    ``span_id`` is always fresh and W3C-width (16 hex = 8 bytes) so the
    A-15 OTLP exporter can send it to Langfuse unchanged. ``trace_id``
    comes from :func:`set_turn_trace` when a turn is in progress (every
    span of the turn then joins one Langfuse trace), otherwise a fresh
    random id — behaviour outside a turn is unchanged.
    """
    trace_id = _turn_trace_id.get() or new_trace_id()
    return trace_id, secrets.token_hex(8)


def _finalize(record: SpanRecord) -> None:
    """Close the span and hand it to the buffer/exporter — never raises."""
    try:
        record.end_time = time.time()
        settings = get_settings()
        _span_buffer.append(record)
        # Debug stdout export (shared setting for all span types)
        if (
            hasattr(settings, "llm_trace_exporter")
            and settings.llm_trace_exporter == "stdout"
        ):
            logger.debug("span %s", json.dumps(record.to_dict(), default=str))
    except (
        Exception
    ):  # pragma: no cover - defensive: observability never breaks the agent
        logger.warning("span finalization failed", exc_info=True)
    # A-15 Langfuse export: outside the buffer try/except so an exporter
    # fault can never corrupt buffering; export_span itself never raises.
    try:
        export_span(record)
    except Exception:  # pragma: no cover - defensive
        logger.debug("langfuse export offer failed", exc_info=True)


def emit_span(
    *,
    span_type: str,
    name: str,
    attributes: Mapping[str, Any],
    status: str = "ok",
    provider: str = "",
    model: str = "",
    start_time: float | None = None,
) -> str | None:
    """Emit a span record into the buffer (never raises).

    Args:
        span_type: Type of span ("llm.call", "agent.permission", etc.).
        name: Human-readable name (e.g. "llm.call:gpt-4", "agent.permission:write").
        attributes: Key-value attributes (e.g. permission.tool, permission.action).
        status: "ok", "error", or custom (e.g. "deny").
        provider: Provider name (e.g. "openai", "anthropic") — for llm.call spans.
        model: Model name (e.g. "gpt-4", "claude-3") — for llm.call spans.
        start_time: Optional earlier start (POSIX seconds) for duration spans;
            defaults to now. End time is always set at emission.

    Returns:
        The emitted span's id (for cross-linking, e.g. A-16 tool.call →
        ToolMessage stamp) — or ``None`` if emission failed (never raises).
    """
    trace_id, span_id = _new_ids()
    record = SpanRecord(
        provider=provider,
        model=model,
        trace_id=trace_id,
        span_id=span_id,
        start_time=start_time if start_time is not None else time.time(),
        name=name,
        span_type=span_type,
        status=status,
        attributes=dict(attributes),
    )
    _finalize(record)
    return span_id


@contextmanager
def timed_span(
    *,
    span_type: str,
    name: str,
    attributes: Mapping[str, Any] | None = None,
    status: str = "ok",
    provider: str = "",
    model: str = "",
):
    """Duration span (A-16): yields a mutable attributes dict.

    Start is captured on entry; the span is emitted on exit (also on
    exception — status flips to ``error``, caller-set attributes survive).
    Joins the active turn trace like every other span (A-06). Never raises.
    """
    start = time.time()
    attrs: dict[str, Any] = dict(attributes or {})
    final_status = status
    try:
        yield attrs
    except BaseException:
        final_status = "error"
        raise
    finally:
        emit_span(
            span_type=span_type,
            name=name,
            attributes=attrs,
            status=final_status,
            provider=provider,
            model=model,
            start_time=start,
        )


# A-17: Pending span attributes and incident tracking functions
def set_pending_span_attributes(attrs: Mapping[str, Any]) -> None:
    """Stage attributes for the next timed_span (A-17).

    Merges with existing pending attrs (if any). Consumed by _agent_loop_span.
    """
    merged = dict(_pending_span_attrs.get() or {})
    merged.update(attrs)
    _pending_span_attrs.set(merged)


def take_pending_span_attributes() -> dict[str, Any]:
    """Take and clear pending span attributes (A-17).

    Returns empty dict if none set. Safe to call multiple times.
    """
    pending = _pending_span_attrs.get() or {}
    if pending:
        _pending_span_attrs.set(None)
    return dict(pending)


def note_incident(key: str = "security.incident", value: str = "true") -> None:
    """Record an incident for the current tool batch (A-17).

    Only effective inside incident_scope(). Called from check_injection when
    injection patterns are detected during tool execution.
    """
    bag = _incident_bag.get()
    if bag is not None:
        bag[key] = value


@contextlib.contextmanager
def incident_scope() -> Iterator[dict[str, str]]:
    """Context manager for incident tracking during tool batch execution (A-17).

    Yields a mutable bag; note_incident() calls populate it. _emit_tool_call_spans
    reads the bag and stamps attributes on all tool.call spans in the batch.
    """
    bag: dict[str, str] = {}
    token = _incident_bag.set(bag)
    try:
        yield bag
    finally:
        _incident_bag.reset(token)
