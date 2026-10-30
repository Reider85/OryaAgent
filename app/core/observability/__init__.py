"""OryaObservability SDK foundation (A-16, A-03).

Contains shared span infrastructure for agent.permission (A-03) and future
agent.plan, agent.execute, agent.tool spans (A-16). Replaces and extends
the llm/tracing.py buffer for multi-type spans.

Exports:
    SpanRecord
    get_span_buffer
    clear_span_buffer
    emit_span
"""

from app.core.observability.spans import (
    SpanRecord,
    clear_span_buffer,
    emit_span,
    get_span_buffer,
)

__all__ = [
    "SpanRecord",
    "get_span_buffer",
    "clear_span_buffer",
    "emit_span",
]
