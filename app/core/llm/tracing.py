"""LLM-seam trace-wrapping (A-02): every seam call emits an ``llm.call`` span.

``get_llm()`` wraps the constructed chat model in :class:`TracedChatModel`,
so any ``ainvoke``/``invoke`` through the seam records a ``SpanRecord``
(``llm.provider``, ``llm.model``, ``tokens.input``/``tokens.output``,
``status``) in a bounded in-process buffer. The wrapper forwards unknown
attributes to the inner model (``model``, ``openai_api_base``, ``kwargs``
after ``bind_tools``, ...) — the seam's observable behaviour is unchanged.

A-06 (span cross-link): the result message is stamped with
``additional_kwargs["orya_span"] = {"trace_id", "span_id"}`` so the JSONL
projection can join the session-log line with the Langfuse trace/span.
Within a turn the ``trace_id`` comes from the turn-trace contextvar
(``app.core.observability.spans.set_turn_trace``).

A-13 (cost tracking): after ``usage_metadata`` is copied into the span,
``invoke``/``ainvoke`` also feed ``app.core.cost_tracker.record_usage``
— ``tokens x pricing.yaml`` into the current identity's daily counter
(no-op without a stamped cost identity; never raises).

A-14 (cost-tracking in spans): when both token counts are known the
span additionally carries ``cost.input_tokens`` / ``cost.output_tokens``
/ ``cost.usd`` (``tokens x pricing.yaml``, ``0.0`` for unpriced models)
and accumulates the ``orya_llm_cost_usd_total{model}`` metric counter.
Unlike the budget recording, the cost attributes are stamped on every
span — independent of the cost identity and the router kill-switch.

A-20 (connection pool): every span additionally carries the pool
acquisition staged by ``get_llm()`` — ``tcp.pool_hit`` (warm reuse vs
cold spawn) and ``tcp.connect_duration_ms`` — when the pool kill-switch
is on.

Design notes (A-02 scope):
- No message content is recorded — PII stays out of spans by omission
  (guardrail/content capture arrives with A-16/A-14).
- The emitter never raises into the agent-loop: finalization is wrapped
  in try/except and only logs.
- ``ORYA_LLM_TRACE_ENABLED=false`` disables wrapping entirely — the factory
  returns the raw provider adapter (zero overhead, stable concrete types).
- Streaming (``_stream``/``_astream``) is delegated without a span; the
  agent-loop uses ``ainvoke`` only (graph.py ``_ainvoke_with_retry``).
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncIterator, Iterator, Sequence
from contextlib import asynccontextmanager, contextmanager
from typing import Any

from langchain_core.callbacks import (
    AsyncCallbackManagerForLLMRun,
    CallbackManagerForLLMRun,
)
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from app.core.config import get_settings
from app.core.cost_tracker import add_cost_total, price_usd, record_usage
from app.core.llm.connection_pool import peek_tcp_attrs
from app.core.observability.spans import (
    ORYA_SPAN_KEY,
    SpanRecord,
    clear_span_buffer,
    get_span_buffer,
)

logger = logging.getLogger(__name__)

# SpanRecord and buffer now live in app/core/observability/spans.py
# Re-exported for backward compatibility (see module end)


def _attach_usage(record: SpanRecord, response: Any) -> None:
    """Copy token counts from a LangChain message/chunk ``usage_metadata``."""
    meta = getattr(response, "usage_metadata", None)
    if not isinstance(meta, dict):
        return
    input_tokens = meta.get("input_tokens")
    output_tokens = meta.get("output_tokens")
    if isinstance(input_tokens, int):
        record.attributes["tokens.input"] = input_tokens
    if isinstance(output_tokens, int):
        record.attributes["tokens.output"] = output_tokens


def _usage_tokens(record: SpanRecord) -> tuple[int, int] | None:
    """Token counts attached by :func:`_attach_usage`, if both present."""
    input_tokens = record.attributes.get("tokens.input")
    output_tokens = record.attributes.get("tokens.output")
    if isinstance(input_tokens, int) and isinstance(output_tokens, int):
        return input_tokens, output_tokens
    return None


def _schedule_record_usage(
    provider: str, model: str, input_tokens: int, output_tokens: int
) -> None:
    """Fire-and-forget cost recording on the running loop (A-13).

    Sync ``invoke`` has no await point; the coroutine is scheduled only
    when an event loop is running (a bare sync call in tests skips it —
    cost accounting must never block or fail the turn).
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    loop.create_task(record_usage(provider, model, input_tokens, output_tokens))


def _attach_cost(record: SpanRecord, model: str, tokens: tuple[int, int]) -> None:
    """Stamp ``cost.*`` attributes and feed the metric counter (A-14).

    Pricing failures degrade to "no cost on this span" — observability
    must never break the turn. The metric counter is updated even when
    the price is ``0.0`` (free/local or unpriced models), so the model
    stays visible in the exposition.
    """
    input_tokens, output_tokens = tokens
    try:
        usd = price_usd(model, input_tokens, output_tokens)
    except Exception:  # noqa: BLE001 - never raise into the agent-loop
        logger.warning("cost pricing failed (model=%s)", model, exc_info=True)
        return
    record.attributes["cost.input_tokens"] = input_tokens
    record.attributes["cost.output_tokens"] = output_tokens
    record.attributes["cost.usd"] = usd
    add_cost_total(model, usd)


def _attach_tcp(record: SpanRecord, provider: str) -> None:
    """Stamp the A-20 pool attributes staged by ``get_llm()`` (best-effort).

    ``tcp.pool_hit`` tells whether the construction reused a warm
    keepalive connection; ``tcp.connect_duration_ms`` is the acquire cost
    (sub-ms warm; a genuinely cold handshake shows up on the first
    request). Absent when the pool kill-switch is off or nothing was
    staged for this provider.
    """
    staged = peek_tcp_attrs(provider)
    if staged is None:
        return
    pool_hit, connect_ms = staged
    record.attributes["tcp.pool_hit"] = pool_hit
    record.attributes["tcp.connect_duration_ms"] = connect_ms


def _stamp_span(message: Any, record: SpanRecord) -> None:
    """Attach the span ids to a LangChain message (A-06), best-effort.

    ``additional_kwargs`` is checkpoint-serialized by LangGraph, so the
    ids survive persistence and the JSONL projection worker picks them
    up later. Never raises into the agent-loop.
    """
    kwargs = getattr(message, "additional_kwargs", None)
    if not isinstance(kwargs, dict):
        return
    try:
        kwargs[ORYA_SPAN_KEY] = {
            "trace_id": record.trace_id,
            "span_id": record.span_id,
        }
    except Exception:  # pragma: no cover - defensive
        logger.debug("span stamping failed", exc_info=True)


# _finalize moved to app/core/observability/spans.py
# The version in this module is kept for compatibility but delegates to the new one


@contextmanager
def _llm_span_sync(provider: str, model: str) -> Iterator[SpanRecord]:
    from app.core.observability.spans import _finalize, _new_ids

    trace_id, span_id = _new_ids()
    record = SpanRecord(
        span_type="llm.call",
        provider=provider,
        model=model,
        trace_id=trace_id,
        span_id=span_id,
        start_time=time.time(),
    )
    try:
        yield record
        record.status = "ok"
    except BaseException as exc:
        record.status = "error"
        record.attributes["error.type"] = type(exc).__name__
        raise
    finally:
        _finalize(record)


@asynccontextmanager
async def _llm_span_async(provider: str, model: str) -> AsyncIterator[SpanRecord]:
    from app.core.observability.spans import _finalize, _new_ids

    trace_id, span_id = _new_ids()
    record = SpanRecord(
        span_type="llm.call",
        provider=provider,
        model=model,
        trace_id=trace_id,
        span_id=span_id,
        start_time=time.time(),
    )
    try:
        yield record
        record.status = "ok"
    except BaseException as exc:
        record.status = "error"
        record.attributes["error.type"] = type(exc).__name__
        raise
    finally:
        _finalize(record)


class TracedChatModel(BaseChatModel):
    """Delegating chat-model wrapper that emits an ``llm.call`` span.

    ``ainvoke``/``invoke`` are delegated to the inner model inside a span;
    every other attribute (including provider config fields and the
    ``kwargs`` of a ``bind_tools`` result) is forwarded via ``__getattr__``.
    """

    inner: Any
    llm_provider: str = ""
    llm_model: str = ""

    @property
    def _llm_type(self) -> str:
        try:
            return str(self.inner._llm_type)
        except AttributeError:
            return "traced"

    def __getattr__(self, name: str) -> Any:
        # Only reached when normal lookup fails; keep pydantic internals out.
        if name.startswith("__"):
            raise AttributeError(name)
        inner = self.__dict__.get("inner")
        if inner is None:
            raise AttributeError(name)
        return getattr(inner, name)

    def bind_tools(self, tools: Sequence[Any], **kwargs: Any) -> TracedChatModel:
        """Delegate ``bind_tools`` and keep the tracing wrapper on top."""
        bound = self.inner.bind_tools(list(tools), **kwargs)
        return TracedChatModel(
            inner=bound, llm_provider=self.llm_provider, llm_model=self.llm_model
        )

    def invoke(
        self,
        input: Any,
        config: Any = None,
        *,
        stop: list[str] | None = None,
        **kwargs: Any,
    ) -> Any:
        with _llm_span_sync(self.llm_provider, self.llm_model) as record:
            result = self.inner.invoke(input, config=config, stop=stop, **kwargs)
            _attach_usage(record, result)
            tokens = _usage_tokens(record)
            if tokens is not None:
                _attach_cost(record, self.llm_model, tokens)
                _schedule_record_usage(self.llm_provider, self.llm_model, *tokens)
            _attach_tcp(record, self.llm_provider)
            _stamp_span(result, record)
            return result

    async def ainvoke(
        self,
        input: Any,
        config: Any = None,
        *,
        stop: list[str] | None = None,
        **kwargs: Any,
    ) -> Any:
        async with _llm_span_async(self.llm_provider, self.llm_model) as record:
            result = await self.inner.ainvoke(input, config=config, stop=stop, **kwargs)
            _attach_usage(record, result)
            tokens = _usage_tokens(record)
            if tokens is not None:
                _attach_cost(record, self.llm_model, tokens)
                await record_usage(
                    self.llm_provider, self.llm_model, tokens[0], tokens[1]
                )
            _attach_tcp(record, self.llm_provider)
            _stamp_span(result, record)
            return result

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        return self.inner._generate(
            messages, stop=stop, run_manager=run_manager, **kwargs
        )

    async def _agenerate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: AsyncCallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        result = await self.inner._agenerate(
            messages, stop=stop, run_manager=run_manager, **kwargs
        )
        return result

    def _stream(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> Iterator[ChatGeneration]:
        yield from self.inner._stream(
            messages, stop=stop, run_manager=run_manager, **kwargs
        )

    async def _astream(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: AsyncCallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[ChatGeneration]:
        async for chunk in self.inner._astream(
            messages, stop=stop, run_manager=run_manager, **kwargs
        ):
            yield chunk


def wrap_with_tracing(
    model: BaseChatModel, *, provider: str, model_name: str
) -> BaseChatModel:
    """Wrap *model* for span emission; passthrough when tracing is off.

    Reads the kill-switch at call time (``get_settings()`` is lru_cached —
    tests sandbox the env and call ``clear_settings_cache()``).
    """
    settings = get_settings()
    if not settings.llm_trace_enabled:
        return model
    return TracedChatModel(inner=model, llm_provider=provider, llm_model=model_name)


# Backward compatibility: re-export observability.spans symbols
# (A-02 tests and app/core/llm/__init__.py depend on these)
__all__ = [
    "TracedChatModel",
    "wrap_with_tracing",
    "SpanRecord",
    "get_span_buffer",
    "clear_span_buffer",
]
