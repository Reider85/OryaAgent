"""Shared span infrastructure for OryaObservability (A-16) and permission audit (A-03).

Replaces llm/tracing.py's SpanRecord and buffer; supports llm.call (A-02)
and agent.permission (A-03) spans. Future: agent.plan, agent.execute,
agent.tool spans (A-16).

Design:
- SpanRecord: generic record with trace_id, span_id, name, span_type,
  provider, model, attributes, status, start/end_time.
- _span_buffer: process-local deque of SpanRecord (maxlen=1000).
- emit_span(): synchronous span emission (non-blocking, no raise).
- _finalize(): internal buffer append + optional stdout debug.
- Kill-switch control via settings (ORYA_*_TRACE_ENABLED for llm;
  ORYA_PERMISSION_AUDIT_ENABLED for permission spans).

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

import json
import logging
import secrets
import time
from collections import deque
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from app.core.config import get_settings

logger = logging.getLogger(__name__)

#: How many finished span records the in-process buffer keeps.
#: Shared across span types (llm.call, agent.permission, etc.).
SPAN_BUFFER_MAX = 1000

_span_buffer: deque[SpanRecord] = deque(maxlen=SPAN_BUFFER_MAX)


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


def _new_ids() -> tuple[str, str]:
    """Generate new random trace_id and span_id."""
    return secrets.token_hex(16), secrets.token_hex(16)


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


def emit_span(
    *,
    span_type: str,
    name: str,
    attributes: Mapping[str, Any],
    status: str = "ok",
    provider: str = "",
    model: str = "",
) -> None:
    """Emit a span record into the buffer.

    Args:
        span_type: Type of span ("llm.call", "agent.permission", etc.).
        name: Human-readable name (e.g. "llm.call:gpt-4", "agent.permission:write").
        attributes: Key-value attributes (e.g. permission.tool, permission.action).
        status: "ok", "error", or custom (e.g. "deny").
        provider: Provider name (e.g. "openai", "anthropic") — for llm.call spans.
        model: Model name (e.g. "gpt-4", "claude-3") — for llm.call spans.

    Never raises; emits to buffer and optionally stdout debug.
    """
    trace_id, span_id = _new_ids()
    record = SpanRecord(
        provider=provider,
        model=model,
        trace_id=trace_id,
        span_id=span_id,
        start_time=time.time(),
        name=name,
        span_type=span_type,
        status=status,
        attributes=dict(attributes),
    )
    _finalize(record)
