"""Chainlit UI (M-15/M-16/M-17): streaming chat + permission ask-prompt + sidebar/settings.

Chainlit drives LangGraph directly (BACKLOG4 M-15 shape; FastAPI/SSE
routing is a follow-up ticket): every chat session owns one compiled
graph and one generated ``thread_id`` stored in ``cl.user_session``.
The shared runtime lives in :mod:`app.core.agent` (M-20) — graph
assembly, checkpointer resolution, normalized stream events and
interrupt extraction are imported from there so the FastAPI layer
reuses them without pulling in Chainlit; this module keeps only the
rendering and the Chainlit handlers.

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
loop (see ``app/tools/bash.py``). :mod:`app.core.agent` sets the
WindowsSelectorEventLoopPolicy at import; Chainlit imports this module
(and thus the agent runtime) *before* it creates its event loop, so
the policy applies to the whole server process.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import AsyncIterator
from typing import Any

import chainlit as cl
from langchain_core.messages import AIMessage, HumanMessage

from app.core.agent import (
    StreamEvent,
    build_session_graph,
    get_pending_interrupt,
    resolve_checkpointer,
    resume_graph_events,
    stream_graph_events,
)
from app.core.agent import (
    content_text as _content_text,
)
from app.core.agent import (
    final_answer_text as _final_answer_text,
)
from app.core.agent import (
    has_pending_interrupt as _has_pending_interrupt,
)
from app.core.agent import (
    preview as _preview,
)
from app.core.cache import init_cache
from app.core.config import get_settings
from app.core.graph import default_run_config
from app.db.session_log import ensure_session, log_message
from app.ui.interrupt import ask_permission
from app.ui.sessions import enrich_titles_from_db, list_sessions
from app.ui.settings import (
    load_settings,
    model_choices,
    policy_from_settings,
    save_settings,
)

logger = logging.getLogger(__name__)

#: Shown when a run pauses but the interrupt payload cannot be read
#: (M-16 normally resolves the pause with the ask-prompt buttons).
_INTERRUPT_HINT = (
    "Run paused at the permission gate, but the pending tool call could "
    "not be read — reload the page to start a new session. Set "
    "`ORYA_PERMISSION_POLICY=permissive` or add allow rules in "
    "`~/.orya/permissions.yml` to let tools run without prompting."
)


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
    await init_cache()  # M-21: idempotent; probes Redis once per process
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
