"""Chainlit UI (M-15): on_chat_start / on_message with graph streaming.

Chainlit drives LangGraph directly (BACKLOG4 M-15 shape; FastAPI/SSE
routing is a follow-up ticket): every chat session owns one compiled
graph and one generated ``thread_id`` stored in ``cl.user_session``.
``stream_graph_events`` normalizes ``graph.astream_events(...,
version="v2")`` into three UI events (``token`` / ``tool_start`` /
``tool_end``) so the Chainlit handlers stay free of LangGraph event
details and the event mapping stays unit-testable without a Chainlit
runtime.

Deferred to follow-up tickets: permission ask-prompt (M-16), session
sidebar and settings (M-17), FastAPI/SSE routing (M-24).

Windows note: psycopg (``AsyncPostgresSaver``) cannot run on the
ProactorEventLoop, and the bash tool relies on running under a Selector
loop (see ``app/tools/bash.py``). Chainlit imports this module *before*
it creates its event loop, so the policy set below applies to the whole
server process.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
import uuid
from collections.abc import AsyncIterator
from typing import Any, Literal

import chainlit as cl
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph.state import CompiledStateGraph

from app.core.context import trim_messages
from app.core.graph import build_graph, default_run_config
from app.core.llm import get_llm
from app.core.permissions import get_policy
from app.core.prompt import build_system_prompt
from app.core.tools import get_tools
from app.db.checkpoints import get_checkpointer
from app.db.session_log import ensure_session, log_message

logger = logging.getLogger(__name__)

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

#: Normalized UI event emitted by :func:`stream_graph_events`.
StreamEvent = tuple[Literal["token", "tool_start", "tool_end"], dict[str, Any]]

#: Cap for tool input/output text rendered inside a step card.
_STEP_PREVIEW_CHARS = 4000

#: Shown when a run pauses at the permission gate (M-16 owns the UI).
_INTERRUPT_HINT = (
    "Run paused at the permission gate: the agent is waiting for tool "
    "approval. Approval buttons are not wired up yet (M-16). Set "
    "`ORYA_PERMISSION_POLICY=permissive` or add allow rules in "
    "`~/.orya/permissions.yml` to let tools run without prompting."
)


def _content_text(content: Any) -> str:
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


def _preview(value: Any, limit: int = _STEP_PREVIEW_CHARS) -> str:
    """Render tool input/output as bounded text for a step card."""
    if isinstance(value, (dict, list)):
        try:
            text = json.dumps(value, ensure_ascii=False, default=str)
        except (TypeError, ValueError):
            text = str(value)
    else:
        text = _content_text(value)
    if len(text) > limit:
        return f"{text[:limit]}... (+{len(text) - limit} chars)"
    return text


async def stream_graph_events(
    graph: Any, user_input: str, config: dict[str, Any]
) -> AsyncIterator[StreamEvent]:
    """Run one user turn through the graph, yielding normalized UI events.

    Wraps ``graph.astream_events(..., version="v2")``: chat-model token
    chunks become ``token`` events, tool calls become ``tool_start`` /
    ``tool_end`` pairs keyed by LangGraph ``run_id``. Internal chain
    events are ignored — the handlers render exactly three event kinds.
    An interrupted run simply ends the iteration; the caller probes the
    checkpoint state afterwards (``state.next != ()``).
    """
    payload = {"messages": [HumanMessage(user_input)]}
    async for event in graph.astream_events(payload, config, version="v2"):
        kind = event.get("event")
        data = event.get("data") or {}
        run_id = str(event.get("run_id") or "")
        if kind == "on_chat_model_stream":
            text = _content_text(getattr(data.get("chunk"), "content", None))
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
                    "output": _content_text(getattr(output, "content", output)),
                },
            )


async def resolve_checkpointer() -> tuple[Any, bool]:
    """Return ``(checkpointer, degraded)`` for a new UI session.

    PostgreSQL first (M-03/M-14 persistence); on any failure — no
    database, incompatible event loop — fall back to the in-memory
    ``MemorySaver`` so the UI still runs. ``degraded=True`` means state
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


def build_session_graph(thread_id: str, checkpointer: Any) -> CompiledStateGraph:
    """Assemble the per-session graph through the architectural seams.

    Tools (M-12), model (M-01), policy (M-13), system prompt (M-05) and
    context trimming (M-06) are all injected — the UI never hardcodes a
    tool list or a prompt.
    """
    return build_graph(
        get_tools(thread_id),
        get_llm(),
        checkpointer,
        get_policy(),
        system_prompt_fn=build_system_prompt,
        trim_fn=trim_messages,
    )


async def _has_pending_interrupt(graph: Any, config: dict[str, Any]) -> bool:
    """True when the run paused at the permission gate (M-13 ``human``)."""
    try:
        state = await graph.aget_state(config)
    except Exception:
        return False
    return bool(getattr(state, "next", None))


async def _final_answer_text(graph: Any, config: dict[str, Any]) -> str:
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
            return _content_text(msg.content)
    return ""


async def _safe_ensure_session(thread_id: str) -> None:
    """Create the ``sessions`` row if the database is reachable."""
    try:
        await ensure_session(thread_id)
    except Exception as exc:
        logger.warning("session row not persisted (PostgreSQL?): %s", exc)


async def _safe_log(session_id: str, role: str, content: str) -> None:
    """Best-effort typed session log (M-14) — never crashes the UI."""
    try:
        await log_message(session_id, role, content)
    except Exception as exc:
        logger.warning("message log skipped for %s/%s: %s", session_id, role, exc)


async def _start_step(data: dict[str, Any]) -> cl.Step:
    """Send the tool step stub for an ``on_tool_start`` event."""
    step = cl.Step(name=str(data.get("tool") or "tool"), type="tool")
    step.input = _preview(data.get("args"))
    await step.send()
    return step


async def _end_step(steps: dict[str, cl.Step], data: dict[str, Any]) -> None:
    """Close the matching tool step for an ``on_tool_end`` event."""
    step = steps.pop(str(data.get("run_id")), None)
    if step is None:
        step = await _start_step(data)
    step.output = _preview(data.get("output"))
    await step.update()


async def _close_steps(steps: dict[str, cl.Step]) -> None:
    """Terminate tool steps left open when a run ends or fails."""
    while steps:
        _, step = steps.popitem()
        if not step.output:
            step.output = "(no output — run ended)"
        await step.update()


@cl.on_chat_start
async def on_chat_start() -> None:
    """Create the session thread and compile its graph (M-15)."""
    thread_id = str(uuid.uuid4())
    checkpointer, degraded = await resolve_checkpointer()
    cl.user_session.set("thread_id", thread_id)
    cl.user_session.set("graph", build_session_graph(thread_id, checkpointer))
    await _safe_ensure_session(thread_id)
    logger.info(
        "Chainlit session started: thread_id=%s checkpointer=%s",
        thread_id,
        "memory" if degraded else "postgres",
    )
    if degraded:
        await cl.Message(
            content=(
                "PostgreSQL is unavailable — this session is kept in memory "
                "only (no resume after a restart)."
            )
        ).send()


@cl.on_message
async def on_message(message: cl.Message) -> None:
    """Stream one user turn through the graph into the chat (M-15)."""
    thread_id = cl.user_session.get("thread_id")
    graph = cl.user_session.get("graph")
    text = (message.content or "").strip()
    if graph is None or thread_id is None:
        await cl.Message(content="Session is not initialized — reload the page.").send()
        return
    if not text:
        return

    await _safe_log(thread_id, "user", text)
    config = default_run_config(thread_id)
    reply = cl.Message(content="")
    steps: dict[str, cl.Step] = {}
    streamed = False

    try:
        async for kind, data in stream_graph_events(graph, text, config):
            if kind == "token":
                await reply.stream_token(data["content"])
                streamed = True
            elif kind == "tool_start":
                steps[data["run_id"]] = await _start_step(data)
            else:
                await _end_step(steps, data)
    except Exception as exc:
        logger.exception("UI run failed (thread_id=%s)", thread_id)
        await _close_steps(steps)
        await cl.Message(content=f"Run failed: {exc}").send()
        return

    await _close_steps(steps)

    pending = await _has_pending_interrupt(graph, config)
    if not streamed and not pending:
        fallback = await _final_answer_text(graph, config)
        if fallback:
            await reply.stream_token(fallback)
            streamed = True
    if streamed:
        await reply.send()
        await _safe_log(thread_id, "assistant", reply.content)
    if pending:
        await cl.Message(content=_INTERRUPT_HINT).send()
