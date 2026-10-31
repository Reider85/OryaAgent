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
