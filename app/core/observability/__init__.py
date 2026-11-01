"""OryaObservability SDK foundation (A-16, A-03, A-17).

Contains shared span infrastructure for agent.permission (A-03) and the
A-16 custom spans (agent.loop, tool.call, memory.write). A-17 adds pending
span attributes and incident tracking for sampler-proxy always-keep spans.

Exports:
    SpanRecord
    get_span_buffer
    clear_span_buffer
    emit_span
    timed_span
    set_pending_span_attributes, take_pending_span_attributes (A-17)
    incident_scope, note_incident (A-17)
"""

from app.core.observability.spans import (
    SpanRecord,
    clear_span_buffer,
    emit_span,
    get_span_buffer,
    incident_scope,
    note_incident,
    set_pending_span_attributes,
    take_pending_span_attributes,
    timed_span,
)

__all__ = [
    "SpanRecord",
    "get_span_buffer",
    "clear_span_buffer",
    "emit_span",
    "incident_scope",
    "note_incident",
    "set_pending_span_attributes",
    "take_pending_span_attributes",
    "timed_span",
]
