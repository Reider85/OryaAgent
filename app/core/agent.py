"""Shared session-agent runtime (M-20): one turn of the agent-loop for any client.

The FastAPI ``/sessions`` endpoints (M-20/M-24) own every consumer of
this runtime — the Chainlit UI reaches them over HTTP/SSE and no longer
assembles a graph itself (BACKLOG5 M-24). The pieces shared by the JSON
and SSE paths are: resolve a checkpointer, assemble the per-session
graph through the architectural seams, normalize LangGraph
``astream_events`` into UI-agnostic events, and detect the M-13
permission pause (PROMPT_MVP §9: «не дублировать logic между Chainlit
UI и FastAPI — общий app/core/ layer»).

* :func:`resolve_checkpointer` — Postgres first, in-memory fallback
  (``degraded=True`` when state will not survive a restart);
* :func:`build_session_graph` — ``build_graph`` wired with ``get_tools``
  / ``get_llm`` / ``get_policy`` / ``build_system_prompt`` /
  ``trim_messages`` (the UI and API never hardcode seams);
* :func:`stream_graph_events` / :func:`resume_graph_events` —
  ``astream_events(..., version="v2")`` normalized to
  ``token`` / ``tool_start`` / ``tool_end`` tuples;
* :func:`get_pending_interrupt` — extract the ``{"tool", "args",
  "reason"}`` payload a paused run carries (langgraph 1.2.x surfaces it
  on ``state.tasks[*].interrupts[*].value``);
* :func:`stream_turn` / :func:`stream_resume` — one full turn as an
  event stream (M-24): normalized events plus a terminal ``done``
  event holding the aggregated :class:`TurnResult` payload. The SSE
  endpoints forward the events as they arrive; :func:`run_turn` /
  :func:`run_resume` are thin wrappers that return only ``done``
  (JSON contract, M-20).

This module must stay free of Chainlit imports — it is imported by the
FastAPI layer.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, Literal

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph.state import CompiledStateGraph

from app.core.context import trim_messages
from app.core.graph import build_graph, resume_command
from app.core.llm import get_llm
from app.core.permissions import get_policy
from app.core.prompt import build_system_prompt
from app.core.security import check_injection, session_id_from_config
from app.core.tools import get_tools
from app.db.checkpoints import get_checkpointer

logger = logging.getLogger(__name__)

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

#: Normalized stream event emitted by :func:`stream_graph_events`.
StreamEvent = tuple[Literal["token", "tool_start", "tool_end"], dict[str, Any]]

#: One full turn as a stream (M-24): the normalized events followed by a
#: terminal ``done`` event carrying the aggregated :class:`TurnResult`
#: payload (``status`` / ``reply`` / ``tool_steps`` / ``pending``).
TurnStreamEvent = tuple[
    Literal["token", "tool_start", "tool_end", "done"], dict[str, Any]
]

#: Cap for tool input/output text rendered inside a step card.
STEP_PREVIEW_CHARS = 4000


def _from_cache(output: Any) -> bool:
    """True when a tool result came from the M-21 cache.

    ``ToolMessage.metadata`` carries ``{"from_cache": True}`` on a hit
    (``from_cache_result()``); non-ToolMessage outputs (plain strings,
    test doubles) are misses.
    """
    metadata = getattr(output, "metadata", None)
    if not isinstance(metadata, dict):
        return False
    return bool(metadata.get("from_cache"))


def content_text(content: Any) -> str:
    """Flatten message/tool content (str or content blocks) into plain text."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and isinstance(block.get("text"), str):
                parts.append(block["text"])
        return "".join(parts)
    if content is None:
        return ""
    return str(content)


def preview(value: Any, limit: int = STEP_PREVIEW_CHARS) -> str:
    """Render tool input/output as bounded text for a step card."""
    if isinstance(value, (dict, list)):
        try:
            text = json.dumps(value, ensure_ascii=False, default=str)
        except (TypeError, ValueError):
            text = str(value)
    else:
        text = content_text(value)
    if len(text) > limit:
        return f"{text[:limit]}... (+{len(text) - limit} chars)"
    return text


async def _stream_normalized(
    graph: Any, payload: Any, config: dict[str, Any]
) -> AsyncIterator[StreamEvent]:
    """Run ``graph.astream_events`` and normalize into UI events.

    Chat-model token chunks become ``token`` events, tool calls become
    ``tool_start`` / ``tool_end`` pairs keyed by LangGraph ``run_id``.
    Internal chain events are ignored. An interrupted run simply ends
    the iteration; the caller probes the checkpoint state afterwards
    (``state.next != ()``).
    """
    async for event in graph.astream_events(payload, config, version="v2"):
        kind = event.get("event")
        data = event.get("data") or {}
        run_id = str(event.get("run_id") or "")
        if kind == "on_chat_model_stream":
            text = content_text(getattr(data.get("chunk"), "content", None))
            if text:
                yield "token", {"content": text}
        elif kind == "on_tool_start":
            yield (
                "tool_start",
                {
                    "run_id": run_id,
                    "tool": event.get("name"),
                    "args": data.get("input"),
                },
            )
        elif kind == "on_tool_end":
            output = data.get("output")
            yield (
                "tool_end",
                {
                    "run_id": run_id,
                    "tool": event.get("name"),
                    "output": content_text(getattr(output, "content", output)),
                    "from_cache": _from_cache(output),
                },
            )


async def stream_graph_events(
    graph: Any, user_input: str, config: dict[str, Any]
) -> AsyncIterator[StreamEvent]:
    """Run one user turn through the graph, yielding normalized UI events.

    The user text is scanned for prompt-injection patterns first (M-22):
    a suspected hit is audited into ``memory_audit_log`` and counted, but
    the message itself is never blocked or rewritten (BACKLOG5 M-22:
    «запретить нельзя — только warn»).
    """
    check_injection(
        user_input,
        source="user_input",
        session_id=session_id_from_config(config),
    )
    payload = {"messages": [HumanMessage(user_input)]}
    async for event in _stream_normalized(graph, payload, config):
        yield event


async def resume_graph_events(
    graph: Any, answer: str, config: dict[str, Any]
) -> AsyncIterator[StreamEvent]:
    """Resume an interrupted run (M-16), yielding normalized UI events.

    The payload is ``resume_command(answer)`` — the same contract the
    ``human`` node (M-13) interprets (``approve`` / ``deny`` /
    ``always``).
    """
    async for event in _stream_normalized(graph, resume_command(answer), config):
        yield event


async def resolve_checkpointer() -> tuple[Any, bool]:
    """Return ``(checkpointer, degraded)`` for a session.

    PostgreSQL first (M-03/M-14 persistence); on any failure — no
    database, incompatible event loop — fall back to the in-memory
    ``MemorySaver`` so clients still run. ``degraded=True`` means state
    will not survive a restart.
    """
    try:
        return await get_checkpointer(), False
    except Exception as exc:
        logger.warning(
            "Postgres checkpointer unavailable (%s); using in-memory MemorySaver",
            exc,
        )
        return MemorySaver(), True


async def has_pending_interrupt(graph: Any, config: dict[str, Any]) -> bool:
    """True when the run paused at the permission gate (M-13 ``human``)."""
    try:
        state = await graph.aget_state(config)
    except Exception:
        return False
    return bool(getattr(state, "next", None))


async def final_answer_text(graph: Any, config: dict[str, Any]) -> str:
    """Latest assistant text from checkpoint state (non-streaming fallback).

    Skips tool-call messages: their content is empty and would shadow
    the real answer. Only used when the run did not pause and the model
    emitted no token chunks.
    """
    try:
        state = await graph.aget_state(config)
    except Exception:
        return ""
    messages = (state.values or {}).get("messages") or []
    for msg in reversed(messages):
        if isinstance(msg, AIMessage) and not msg.tool_calls:
            return content_text(msg.content)
    return ""


def build_session_graph(
    thread_id: str,
    checkpointer: Any,
    *,
    model: Any = None,
    provider: str | None = None,
    policy: Any | None = None,
) -> CompiledStateGraph:
    """Assemble the per-session graph through the architectural seams.

    Tools (M-12), model (M-01), policy (M-13), system prompt (M-05) and
    context trimming (M-06) are all injected — callers never hardcode a
    tool list or a prompt.

    ``model`` is a model alias from ``models.yaml`` (resolved through
    the ``get_llm`` seam) or an already-built chat-model instance;
    ``provider`` optionally pins the providers.yaml provider (None =
    «Auto» — the alias' own provider or the config/env default);
    ``policy`` is a :class:`~app.core.permissions.PermissionPolicy`.
    """
    if model is None:
        llm = get_llm(provider=provider)
    elif isinstance(model, str):
        llm = get_llm(provider=provider, model=model)
    else:
        llm = model
    return build_graph(
        get_tools(thread_id),
        llm,
        checkpointer,
        policy if policy else get_policy(),
        system_prompt_fn=build_system_prompt,
        trim_fn=trim_messages,
    )


@dataclass(frozen=True)
class PendingInterrupt:
    """One permission pause extracted from a checkpoint state snapshot."""

    tool: str
    args: dict[str, Any] = field(default_factory=dict)
    reason: str = ""


def get_pending_interrupt(state: Any) -> PendingInterrupt | None:
    """Extract the permission payload from ``graph.aget_state`` output.

    The human node (M-13) pauses via
    ``interrupt({"tool", "args", "reason"})``; the paused task carries
    that payload on ``state.tasks[*].interrupts[*].value``. Returns
    ``None`` when no task holds a permission interrupt (finished run, a
    pause raised elsewhere, or an unreadable state object).
    """
    for task in getattr(state, "tasks", None) or ():
        for pending in getattr(task, "interrupts", None) or ():
            value = getattr(pending, "value", None)
            if isinstance(value, dict) and "tool" in value:
                return PendingInterrupt(
                    tool=str(value.get("tool", "")),
                    args=dict(value.get("args") or {}),
                    reason=str(value.get("reason") or ""),
                )
    return None


@dataclass
class TurnResult:
    """Aggregated outcome of one non-interactive (API) turn or resume."""

    status: Literal["ok", "interrupted"]
    reply: str = ""
    tool_steps: list[dict[str, Any]] = field(default_factory=list)
    pending: PendingInterrupt | None = None


async def _aggregate_turn(
    events: AsyncIterator[StreamEvent],
    graph: Any,
    config: dict[str, Any],
) -> AsyncIterator[TurnStreamEvent]:
    """Forward one turn's events and finish with a terminal ``done``.

    Accumulates token text into ``reply`` and tool calls into
    ``tool_steps`` (``{run_id, tool, args, output, from_cache}``) on the
    way, so the JSON (M-20) and SSE (M-24) paths share a single
    aggregation. The checkpoint state then decides the status: a pending
    permission interrupt yields ``interrupted`` plus the extracted
    payload (answered via ``/sessions/{id}/resume``); otherwise ``ok``,
    falling back to the latest checkpointed assistant text when the
    model emitted no token chunks.
    """
    reply_parts: list[str] = []
    tool_steps: list[dict[str, Any]] = []
    steps_by_run: dict[str, dict[str, Any]] = {}

    async for kind, data in events:
        if kind == "token":
            reply_parts.append(data["content"])
        elif kind == "tool_start":
            step = {
                "run_id": data["run_id"],
                "tool": data.get("tool"),
                "args": data.get("args"),
                "output": "",
                "from_cache": False,
            }
            tool_steps.append(step)
            steps_by_run[data["run_id"]] = step
        else:  # tool_end
            step = steps_by_run.get(str(data.get("run_id")))
            if step is None:
                step = {
                    "run_id": data.get("run_id"),
                    "tool": data.get("tool"),
                    "args": None,
                    "output": "",
                    "from_cache": False,
                }
                tool_steps.append(step)
            step["output"] = data.get("output") or ""
            step["from_cache"] = bool(data.get("from_cache"))
        yield kind, data

    if await has_pending_interrupt(graph, config):
        state = await graph.aget_state(config)
        yield (
            "done",
            {
                "status": "interrupted",
                "reply": "".join(reply_parts),
                "tool_steps": tool_steps,
                "pending": get_pending_interrupt(state),
            },
        )
        return

    reply = "".join(reply_parts)
    if not reply:
        reply = await final_answer_text(graph, config)
    yield (
        "done",
        {
            "status": "ok",
            "reply": reply,
            "tool_steps": tool_steps,
            "pending": None,
        },
    )


async def stream_turn(
    graph: Any, user_input: str, config: dict[str, Any]
) -> AsyncIterator[TurnStreamEvent]:
    """One user turn as an event stream (M-24): tokens, tool steps, ``done``.

    The SSE endpoint forwards every event as it arrives; the terminal
    ``done`` event carries the aggregated outcome (``status``, ``reply``,
    ``tool_steps``, ``pending``).
    """
    stream = stream_graph_events(graph, user_input, config)
    async for event in _aggregate_turn(stream, graph, config):
        yield event


async def stream_resume(
    graph: Any, answer: str, config: dict[str, Any]
) -> AsyncIterator[TurnStreamEvent]:
    """Resume an interrupted run as an event stream (M-24 ``/resume``).

    Same contract as :func:`stream_turn`, starting from
    ``resume_command(answer)``; a batch may pause again, so the caller
    must handle another ``interrupted`` ``done``.
    """
    stream = resume_graph_events(graph, answer, config)
    async for event in _aggregate_turn(stream, graph, config):
        yield event


async def _final_done(events: AsyncIterator[TurnStreamEvent]) -> TurnResult:
    """Consume a turn stream and return only its ``done`` payload."""
    async for kind, data in events:
        if kind == "done":
            return TurnResult(
                status=data["status"],
                reply=data["reply"],
                tool_steps=data["tool_steps"],
                pending=data["pending"],
            )
    raise RuntimeError("turn stream ended without a 'done' event")


async def run_turn(graph: Any, user_input: str, config: dict[str, Any]) -> TurnResult:
    """Drive one user turn to completion (or permission pause) for API clients.

    Thin wrapper over :func:`stream_turn`: same aggregation, no event
    forwarding ? the JSON contract of ``POST /sessions/{id}/messages``
    (M-20). ``status="interrupted"`` carries the pending tool call the
    client answers via ``POST /sessions/{id}/resume``.
    """
    return await _final_done(stream_turn(graph, user_input, config))


async def run_resume(graph: Any, answer: str, config: dict[str, Any]) -> TurnResult:
    """Resume an interrupted run for API clients (M-20 ``/resume``).

    Same aggregation as :func:`run_turn` but starting from
    ``resume_command(answer)``; a batch may pause again (one tool call
    per interrupt), so the result may be ``interrupted`` once more.
    """
    return await _final_done(stream_resume(graph, answer, config))
