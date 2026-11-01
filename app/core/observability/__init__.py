"""OryaObservability SDK foundation (A-16, A-03).

Contains shared span infrastructure for agent.permission (A-03) and the
A-16 custom spans (agent.loop, tool.call, memory.write). Replaces and extends
the llm/tracing.py buffer for multi-type spans.

Exports:
    SpanRecord
    get_span_buffer
    clear_span_buffer
    emit_span
    timed_span
"""

from app.core.observability.spans import (
    SpanRecord,
    clear_span_buffer,
    emit_span,
    get_span_buffer,
    timed_span,
)

__all__ = [
    "SpanRecord",
    "get_span_buffer",
    "clear_span_buffer",
    "emit_span",
    "timed_span",
]
