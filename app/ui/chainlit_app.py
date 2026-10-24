"""Chainlit UI (M-15/M-16/M-17): streaming chat + permission ask-prompt + sidebar/settings.

Chainlit drives LangGraph directly (BACKLOG4 M-15 shape; FastAPI/SSE
routing is a follow-up ticket): every chat session owns one compiled
graph and one generated ``thread_id`` stored in ``cl.user_session``.
``stream_graph_events`` normalizes ``graph.astream_events(...,
version="v2")`` into three UI events (``token`` / ``tool_start`` /
``tool_end``) so the Chainlit handlers stay free of LangGraph event
details and the event mapping stays unit-testable without a Chainlit
runtime.

M-16 closes the permission gate (M-13): when a run pauses at the
``human`` node the handler extracts the pending tool call
(:mod:`app.ui.interrupt`), shows the Approve / Deny / don't-ask-again
buttons and resumes the graph with ``resume_command(...)``, streaming
the continuation (tool execution + the agent's next answer) into the
same reply. A batch may pause several times, so the handler loops until
the checkpoint state holds no pending interrupt.

M-17 adds session sidebar and settings: session list from JSONL files,
settings panel for model/permission mode, session switching with history
restoration. Settings persisted to ~/.orya/settings.json.

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

from app.core.config import get_settings
from app.core.context import trim_messages
from app.core.graph import build_graph, default_run_config, resume_command
from app.core.llm import get_llm
from app.core.permissions import get_policy
from app.core.prompt import build_system_prompt
from app.core.tools import get_tools
from app.db.checkpoints import get_checkpointer
from app.db.session_log import ensure_session, log_message
from app.ui.interrupt import ask_permission, get_pending_interrupt
from app.ui.sessions import enrich_titles_from_db, list_sessions
from app.ui.settings import (
    load_settings,
    model_choices,
    policy_from_settings,
    save_settings,
)

logger = logging.getLogger(__name__)

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

#: Normalized UI event emitted by :func:`stream_graph_events`.
StreamEvent = tuple[Literal["token", "tool_start", "tool_end"], dict[str, Any]]

#: Cap for tool input/output text rendered inside a step card.
_STEP_PREVIEW_CHARS = 4000

#: Shown when a run pauses but the interrupt payload cannot be read
#: (M-16 normally resolves the pause with the ask-prompt buttons).
_INTERRUPT_HINT = (
    "Run paused at the permission gate, but the pending tool call could "
    "not be read — reload the page to start a new session. Set "
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


async def stream_graph_events(
    graph: Any, user_input: str, config: dict[str, Any]
) -> AsyncIterator[StreamEvent]:
    """Run one user turn through the graph, yielding normalized UI events."""
    payload = {"messages": [HumanMessage(user_input)]}
    async for event in _stream_normalized(graph, payload, config):
        yield event


async def resume_graph_events(
    graph: Any, answer: str, config: dict[str, Any]
) -> AsyncIterator[StreamEvent]:
    """Resume an interrupted run (M-16), yielding normalized UI events.

    The payload is ``resume_command(answer)`` — the same contract the
    ``human`` node (M-13) interprets (``approve`` / ``deny`` /
    ``always``). The resumed run streams tool execution and the agent's
    follow-up answer exactly like a normal turn.
    """
    async for event in _stream_normalized(graph, resume_command(answer), config):
        yield event


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


async def _load_session_history(graph: Any, thread_id: str) -> None:
    """Load and display session history from checkpoint state.

    Called when switching to an existing session to show previous messages.
    """
    try:
        config = default_run_config(thread_id)
        state = await graph.aget_state(config)
        messages = (state.values or {}).get("messages") or []

        # Display user and assistant messages
        for msg in messages:
            if isinstance(msg, HumanMessage):
                await cl.Message(content=_content_text(msg.content)).send()
            elif isinstance(msg, AIMessage):
                await cl.Message(content=_content_text(msg.content)).send()
    except Exception as exc:
        logger.warning("Cannot load session history for %s: %s", thread_id, exc)


def build_session_graph(
    thread_id: str,
    checkpointer: Any,
    *,
    model: str | None = None,
    policy: Any | None = None,
) -> CompiledStateGraph:
    """Assemble the per-session graph through the architectural seams.

    Tools (M-12), model (M-01), policy (M-13), system prompt (M-05) and
    context trimming (M-06) are all injected — the UI never hardcodes a
    tool list or a prompt.
    """
    return build_graph(
        get_tools(thread_id),
        model if model else get_llm(),
        checkpointer,
        policy if policy else get_policy(),
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


async def _render_run(
    reply: cl.Message,
    steps: dict[str, cl.Step],
    events: AsyncIterator[StreamEvent],
) -> bool:
    """Render one streaming pass into ``reply``/``steps``.

    Returns ``True`` when at least one token was streamed (the caller
    sends the reply only in that case — non-streaming models fall back
    to the checkpoint text instead).
    """
    streamed = False
    async for kind, data in events:
        if kind == "token":
            await reply.stream_token(data["content"])
            streamed = True
        elif kind == "tool_start":
            steps[data["run_id"]] = await _start_step(data)
        else:
            await _end_step(steps, data)
    return streamed


@cl.on_chat_start
async def on_chat_start() -> None:
    """Create the session thread and compile its graph (M-15/M-17)."""
    thread_id = str(uuid.uuid4())
    checkpointer, degraded = await resolve_checkpointer()

    # Load settings and build graph with overrides
    settings = load_settings()
    graph = build_session_graph(
        thread_id,
        checkpointer,
        model=settings.model,
        policy=policy_from_settings(settings),
    )

    cl.user_session.set("thread_id", thread_id)
    cl.user_session.set("graph", graph)
    cl.user_session.set("checkpointer", checkpointer)  # Store for session switching
    await _safe_ensure_session(thread_id)

    logger.info(
        "Chainlit session started: thread_id=%s checkpointer=%s settings=%s",
        thread_id,
        "memory" if degraded else "postgres",
        settings.model or "default",
    )

    if degraded:
        await cl.Message(
            content=(
                "PostgreSQL is unavailable — this session is kept in memory "
                "only (no resume after a restart)."
            )
        ).send()

    # Show sidebar with sessions and settings panel
    await _show_sidebar(thread_id)
    await _show_settings_panel(settings)


async def _show_sidebar(thread_id: str) -> None:
    """Show sidebar with session list and new session button."""
    sessions_dir = get_settings().sessions_dir
    sessions = await list_sessions(sessions_dir, limit=10)
    enriched = await enrich_titles_from_db(sessions)

    # Create sidebar elements
    elements = []

    # New session button
    new_session_action = cl.Action(
        name="new_session", payload={"thread_id": None}, label="New session"
    )
    elements.append(new_session_action)

    # Session list
    for session in enriched:
        session_action = cl.Action(
            name="switch_session",
            payload={"thread_id": session.session_id},
            label=session.display_name,
        )
        elements.append(session_action)

    # Show sidebar
    await cl.ChatSettings(title="Sessions", elements=elements).send()


async def _show_settings_panel(settings: Any) -> None:
    """Show settings panel with model, permission mode, and allow list."""
    # Model choices
    model_options = model_choices()
    current_model = settings.model or "default"

    # Permission mode options
    mode_options = [("strict", "Strict"), ("permissive", "Permissive")]
    current_mode = settings.permission_mode or "strict"

    # Create settings form
    settings_elements = []

    # Model selection
    settings_elements.append(
        {
            "label": "Model",
            "type": "select",
            "options": model_options,
            "default": current_model,
        }
    )

    # Permission mode selection
    settings_elements.append(
        {
            "label": "Permission Mode",
            "type": "select",
            "options": mode_options,
            "default": current_mode,
        }
    )

    # Allow list textarea
    settings_elements.append(
        {
            "label": "Allow List (newline-separated patterns)",
            "type": "textarea",
            "default": "\n".join(settings.allow_list),
        }
    )

    await cl.ChatSettings(title="Settings", elements=settings_elements).send()


@cl.on_settings_update
async def on_settings_update(settings_data: dict) -> None:
    """Handle settings changes and rebuild graph."""
    thread_id = cl.user_session.get("thread_id")
    graph = cl.user_session.get("graph")
    checkpointer = cl.user_session.get("checkpointer")

    if not thread_id or not graph or not checkpointer:
        await cl.Message(content="Session not initialized — reload the page.").send()
        return

    # Parse settings data
    settings = load_settings()
    settings.model = settings_data.get("Model")
    settings.permission_mode = settings_data.get("Permission Mode")

    # Parse allow list (newline-separated)
    allow_list_text = settings_data.get("Allow List (newline-separated patterns)", "")
    settings.allow_list = [
        line.strip() for line in allow_list_text.split("\n") if line.strip()
    ]

    # Save settings
    save_settings(settings)

    # Rebuild graph with new settings
    new_graph = build_session_graph(
        thread_id,
        checkpointer,
        model=settings.model,
        policy=policy_from_settings(settings),
    )
    cl.user_session.set("graph", new_graph)

    logger.info(
        "Settings updated: model=%s mode=%s", settings.model, settings.permission_mode
    )
    await cl.Message(content="Settings saved and graph updated.").send()


@cl.action_callback("new_session")
async def on_new_session(action: cl.Action) -> None:
    """Handle new session action."""
    thread_id = str(uuid.uuid4())
    checkpointer, degraded = await resolve_checkpointer()

    # Load settings and build new graph
    settings = load_settings()
    graph = build_session_graph(
        thread_id,
        checkpointer,
        model=settings.model,
        policy=policy_from_settings(settings),
    )

    # Update user session
    cl.user_session.set("thread_id", thread_id)
    cl.user_session.set("graph", graph)
    cl.user_session.set("checkpointer", checkpointer)

    await _safe_ensure_session(thread_id)

    logger.info("New session started: thread_id=%s", thread_id)
    await cl.Message(content=f"New session started: {thread_id[:8]}").send()

    # Update sidebar
    await _show_sidebar(thread_id)


@cl.action_callback("switch_session")
async def on_switch_session(action: cl.Action) -> None:
    """Handle session switch action."""
    thread_id = action.payload.get("thread_id")
    if not thread_id:
        await cl.Message(content="Invalid session ID").send()
        return

    # Get current checkpointer and build new graph for existing thread
    checkpointer = cl.user_session.get("checkpointer")
    if not checkpointer:
        await cl.Message(
            content="Cannot switch sessions: checkpointer not available"
        ).send()
        return

    try:
        # Build graph for existing thread_id
        settings = load_settings()
        graph = build_session_graph(
            thread_id,
            checkpointer,
            model=settings.model,
            policy=policy_from_settings(settings),
        )

        # Update user session
        cl.user_session.set("thread_id", thread_id)
        cl.user_session.set("graph", graph)

        await _safe_ensure_session(thread_id)

        # Load and display session history
        await _load_session_history(graph, thread_id)

        logger.info("Switched to session: thread_id=%s", thread_id)
        await cl.Message(content=f"Switched to session: {thread_id[:8]}").send()

        # Update sidebar
        await _show_sidebar(thread_id)

    except Exception as exc:
        logger.exception("Failed to switch session: %s", thread_id)
        await cl.Message(content=f"Failed to switch session: {exc}").send()


@cl.on_message
async def on_message(message: cl.Message) -> None:
    """Stream one user turn through the graph into the chat (M-15/M-16)."""
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
        streamed = await _render_run(
            reply, steps, stream_graph_events(graph, text, config)
        )
        # M-16: resolve permission pauses — ask, resume, re-check. A
        # batch may pause once per tool call, so this is a loop.
        while await _has_pending_interrupt(graph, config):
            state = await graph.aget_state(config)
            pending = get_pending_interrupt(state)
            if pending is None:
                await cl.Message(content=_INTERRUPT_HINT).send()
                break
            answer = await ask_permission(pending)
            logger.info(
                "Permission %s: tool=%s thread_id=%s",
                answer,
                pending.tool,
                thread_id,
            )
            await _safe_log(
                thread_id,
                "system",
                f"permission {answer}: {pending.tool} {_preview(pending.args)}",
            )
            streamed |= await _render_run(
                reply, steps, resume_graph_events(graph, answer, config)
            )
    except Exception as exc:
        logger.exception("UI run failed (thread_id=%s)", thread_id)
        await _close_steps(steps)
        await cl.Message(content=f"Run failed: {exc}").send()
        return

    await _close_steps(steps)

    if not streamed and not await _has_pending_interrupt(graph, config):
        fallback = await _final_answer_text(graph, config)
        if fallback:
            await reply.stream_token(fallback)
            streamed = True
    if streamed:
        await reply.send()
        await _safe_log(thread_id, "assistant", reply.content)
