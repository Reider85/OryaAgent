"""Context manager — sliding-window trimming of the conversation (M-06).

Every LLM provider has a finite context window. This module keeps the
message history within a configurable token budget before each model call:

1. ``truncate_tool_messages`` — long tool results are cut to head/tail
   lines with a truncation marker (token-efficient output, M-23);
2. ``trim_thinking`` — reasoning-model chain-of-thought leftovers
   (``reasoning_content``) are stripped (token-blowup risk, PROMPT_MVP §8);
3. ``trim_messages`` — LangChain ``trim_messages`` sliding window:
   strategy ``last`` (keep the most recent turns), ``start_on="human"``
   (never start mid-turn), ``include_system=True`` (a SystemMessage at
   index 0 always survives), ``allow_partial=False`` (no partial messages).

The public contract ``trim_messages(messages, max_tokens) ->
list[BaseMessage]`` is an architectural invariant (PROMPT_MVP §4 #4):
v7 BETA replaces the implementation with DFC (5 layers) but keeps this
signature.

Usage::

    from app.core.context import trim_messages

    history = trim_messages(state["messages"])          # budget from settings
    history = trim_messages(state["messages"], 10_000)  # explicit budget

The graph (M-04) does not import this module directly — it accepts an
optional ``trim_fn`` seam (same pattern as ``system_prompt_fn``) so the
agent-loop stays independent of M-06.

Design constraints (see ``analytics/PROMPT_MVP.md`` §4, §9):

* trimming is delegated to ``langchain_core.messages.trim_messages`` —
  no hand-rolled window algorithm;
* SystemMessages are never dropped;
* ``tiktoken.encoding_for_model`` is only consulted for known model
  names — unknown models (Claude, Gemini, DeepSeek, ...) fall back to a
  ``chars/4`` approximation (no KeyError at runtime);
* token counting is an approximation (±10% is acceptable for MVP).
"""

from __future__ import annotations

import json
import logging
from collections.abc import Sequence
from functools import lru_cache

import tiktoken
from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    ToolMessage,
)
from langchain_core.messages import (
    trim_messages as lc_trim_messages,
)

from app.core.config import get_settings

logger = logging.getLogger(__name__)

#: Tool results longer than this are truncated to head/tail lines (M-23).
TOOL_RESULT_MAX_CHARS = 5_000
TOOL_RESULT_HEAD_LINES = 100
TOOL_RESULT_TAIL_LINES = 50


def _message_text(message: BaseMessage) -> str:
    """Flatten a message to plain text for token counting.

    Handles both ``str`` content and Anthropic-style list-of-blocks
    content; tool-call payloads are appended so call-heavy turns are not
    undercounted.
    """
    content = message.content
    if isinstance(content, str):
        text = content
    elif isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict):
                parts.append(str(block.get("text", block)))
            else:
                parts.append(str(block))
        text = "\n".join(parts)
    else:
        text = "" if content is None else str(content)
    tool_calls = getattr(message, "tool_calls", None)
    if tool_calls:
        text += json.dumps(tool_calls, ensure_ascii=False)
    return text


@lru_cache(maxsize=32)
def _encoding_for(model: str | None) -> tiktoken.Encoding | None:
    """Return a tiktoken encoding for known OpenAI-family models only.

    ``encoding_for_model`` raises ``KeyError`` for every non-OpenAI model
    (Claude, Gemini, DeepSeek, Qwen, ...) — those must never crash token
    counting, so ``None`` (= approximation) is returned instead.
    """
    if not model:
        return None
    try:
        return tiktoken.encoding_for_model(model)
    except KeyError:
        return None


def count_tokens(
    messages: Sequence[BaseMessage],
    model: str | None = None,
) -> int:
    """Count tokens for a message list.

    Uses tiktoken for known OpenAI-family models; every other model falls
    back to a ``chars/4`` approximation (BACKLOG4 M-06 forbidden pattern:
    never call ``encoding_for_model`` for unknown models).
    """
    encoding = _encoding_for(model)
    total = 0
    for message in messages:
        text = _message_text(message)
        if encoding is not None:
            total += len(encoding.encode(text, disallowed_special=()))
        else:
            total += len(text) // 4
    return total


def truncate_tool_messages(
    messages: Sequence[BaseMessage],
    max_chars: int = TOOL_RESULT_MAX_CHARS,
    head: int = TOOL_RESULT_HEAD_LINES,
    tail: int = TOOL_RESULT_TAIL_LINES,
) -> list[BaseMessage]:
    """Cut over-long tool results to head/tail lines with a marker.

    A ``ToolMessage`` whose content exceeds ``max_chars`` keeps the first
    ``head`` and last ``tail`` lines with ``... [N lines truncated] ...``
    in between. Content made of a few very long lines falls back to a
    character cut so the result is still bounded. Messages are copied,
    never mutated.
    """
    result: list[BaseMessage] = []
    for message in messages:
        if not isinstance(message, ToolMessage):
            result.append(message)
            continue
        content = message.content
        if not isinstance(content, str) or len(content) <= max_chars:
            result.append(message)
            continue
        lines = content.splitlines()
        if len(lines) > head + tail:
            removed = len(lines) - head - tail
            body = "\n".join(
                [
                    *lines[:head],
                    f"... [{removed} lines truncated] ...",
                    *lines[-tail:],
                ]
            )
        else:
            body = (
                content[:max_chars]
                + f"\n... [truncated {len(content) - max_chars} chars] ..."
            )
        result.append(message.model_copy(update={"content": body}))
        logger.debug(
            "Tool result truncated: %d -> %d chars (%s)",
            len(content),
            len(body),
            message.name or message.tool_call_id,
        )
    return result


def trim_thinking(messages: Sequence[BaseMessage]) -> list[BaseMessage]:
    """Strip reasoning-model chain-of-thought from ``AIMessage`` history.

    Reasoning models (DeepSeek-R1, o1, Qwen-QwQ, GLM-Zero) emit their
    thinking into ``additional_kwargs["reasoning_content"]``. Keeping it
    in the history blows up the token budget with no benefit for the next
    turn — the final answer in ``content`` is what matters. Messages are
    copied, never mutated.
    """
    result: list[BaseMessage] = []
    for message in messages:
        if isinstance(message, AIMessage) and message.additional_kwargs.get(
            "reasoning_content"
        ):
            cleaned = {
                key: value
                for key, value in message.additional_kwargs.items()
                if key != "reasoning_content"
            }
            result.append(message.model_copy(update={"additional_kwargs": cleaned}))
        else:
            result.append(message)
    return result


def trim_messages(
    messages: Sequence[BaseMessage],
    max_tokens: int | None = None,
    *,
    model: str | None = None,
) -> list[BaseMessage]:
    """Trim conversation history to the context-window budget.

    Pipeline: tool-result truncation -> thinking strip -> LangChain
    sliding window (``strategy="last"``, ``start_on="human"``,
    ``include_system=True``, ``allow_partial=False``).

    This is the M-06 architectural invariant: the signature
    ``trim_messages(messages, max_tokens) -> list[BaseMessage]`` stays
    stable when v7 BETA swaps the implementation for DFC.

    Args:
        messages: Conversation history (BaseMessage list).
        max_tokens: Token budget; ``None`` takes
            ``settings.context_max_tokens`` (default 120_000).
        model: Model name for tiktoken selection; ``None`` takes
            ``settings.llm_model``. Unknown models use the chars/4
            approximation.

    Returns:
        Trimmed message list (input is never mutated).
    """
    history = list(messages)
    if not history:
        return []
    settings = get_settings()
    budget = max_tokens if max_tokens is not None else settings.context_max_tokens
    model_name = model if model is not None else settings.llm_model
    pipeline = trim_thinking(truncate_tool_messages(history))
    trimmed = lc_trim_messages(
        pipeline,
        max_tokens=budget,
        token_counter=lambda msgs: count_tokens(msgs, model=model_name),
        strategy="last",
        start_on="human",
        allow_partial=False,
        include_system=True,
    )
    if len(trimmed) != len(pipeline):
        logger.debug(
            "Context trimmed: %d -> %d messages (budget=%d tokens)",
            len(pipeline),
            len(trimmed),
            budget,
        )
    return trimmed


def trim_state(
    state: dict | None,
    max_tokens: int | None = None,
) -> dict[str, list[BaseMessage]]:
    """Trim ``state["messages"]``; returns a LangGraph state-update dict.

    Convenience wrapper around :func:`trim_messages` for use as a graph
    node or a pre-pass over ``MessagesState``.
    """
    raw = (state or {}).get("messages") or []
    return {"messages": trim_messages(list(raw), max_tokens=max_tokens)}
