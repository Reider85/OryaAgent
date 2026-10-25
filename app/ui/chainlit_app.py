"""Chainlit UI (M-15/M-16/M-17, M-24): chat over the FastAPI SSE endpoints.

Chainlit is a pure HTTP client of the FastAPI server (BACKLOG5 M-24,
ARCHITECT5 §6.7) — it never assembles or drives a graph itself:

    Chainlit UI  →  FastAPI /sessions/{id}/messages (?stream=true)  →  LangGraph

``on_chat_start`` creates the session through ``POST /sessions`` and
keeps the ``thread_id`` in ``cl.user_session``; ``on_message`` posts the
turn and renders the SSE frames (``token`` / ``tool_start`` /
``tool_end`` / ``interrupt`` / ``done``) into ``cl.Message`` tokens and
``cl.Step`` tool cards. Moving the graph into the server removes the
streaming duplication between Chainlit and the future Next.js client —
the reason M-24 exists.

M-16 closes the permission gate (M-13): an ``interrupt`` frame (or an
``interrupted`` ``done``) carries the pending tool call, the handler
shows the Approve / Deny / don't-ask-again buttons
(:mod:`app.ui.interrupt`) and resumes through
``POST /sessions/{id}/resume?stream=true``, streaming the continuation
into the same reply. A batch may pause several times, so the handler
loops until the run reports a non-interrupted status.

M-17 keeps the session sidebar and the settings panel: the sidebar lists
sessions via ``GET /sessions`` and restores history from
``GET /sessions/{id}``; the panel persists model / permission mode /
allow-list to the settings file, and every request carries that state to
the server, which builds the model and the policy for the session.

M-26 adds the ``/learn`` slash-command (BACKLOG6): a message starting
with ``/learn [name] [description]`` is *not* a chat turn — it calls
``POST /sessions/{id}/learn`` (capture the last successful tool-call
sequence into ``LEARNED.md``) and renders the
``✅ Learned: learn_001 → LEARNED.md (compacted: false)`` feedback.
Chainlit 2.x has no ``on_slash_command`` hook, so the command is parsed
at the top of ``on_message``.

Failure modes: an unreachable API server (``ORYA_API_URL``) leaves the
chat with an explanatory message instead of a session; a database outage
degrades to a locally generated ``thread_id`` and ``degraded: true`` in
the ``done`` frame (the server logs best-effort in stream mode).
"""

from __future__ import annotations

import json
import logging
import shlex
import uuid
from collections.abc import AsyncIterator
from typing import Any

import chainlit as cl
import httpx

from app.core.agent import PendingInterrupt, content_text, preview
from app.core.config import get_settings
from app.ui.interrupt import ask_permission
from app.ui.settings import (
    UISettings,
    load_settings,
    model_choices,
    save_settings,
)

logger = logging.getLogger(__name__)

#: No connect/write deadline on reads — a turn may stream for minutes.
_API_TIMEOUT = httpx.Timeout(10.0, read=None)

#: Ask-prompt fallback when a pause carries no readable payload.
_INTERRUPT_HINT = (
    "Run paused at the permission gate, but the pending tool call could "
    "not be read — send the message again. Set "
    "`ORYA_PERMISSION_POLICY=permissive` or add allow rules in "
    "`~/.orya/permissions.yml` to let tools run without prompting."
)

#: Shown when the chat has no session yet (the API refused to start).
_SESSION_HINT = (
    "No active session — reload the page. If the FastAPI server is not "
    "running, start it with `make dev`."
)

#: ``ask_permission`` answer → ``decision`` of ``POST /sessions/{id}/resume``.
_DECISIONS = {"approve": "allow", "deny": "deny", "always": "always"}


class ApiError(Exception):
    """The FastAPI server answered with an error status."""


# --- API transport ---------------------------------------------------------


def api_url() -> str:
    """Base URL of the FastAPI server (``ORYA_API_URL`` setting)."""
    return get_settings().api_url.rstrip("/")


def make_client() -> httpx.AsyncClient:
    """HTTP client bound to the API server (one per handler call)."""
    return httpx.AsyncClient(base_url=api_url(), timeout=_API_TIMEOUT)


def settings_payload(settings: UISettings) -> dict[str, Any]:
    """Settings-panel state sent with every turn/resume (M-24 overrides)."""
    return {
        "model": settings.model,
        "permission_mode": settings.permission_mode,
        "allow_list": list(settings.allow_list),
    }


async def iter_sse(lines: AsyncIterator[str]) -> AsyncIterator[tuple[str, Any]]:
    """Parse a Server-Sent-Events line stream into ``(event, data)`` pairs.

    Implements the SSE framing rules the API emits: events are separated
    by a blank line, fields are ``event:`` / ``data:`` (a single space
    after the colon is optional), ``data`` lines join with ``\\n``,
    comment lines start with ``:`` and a missing event name means
    ``message``. Data is JSON-decoded; a non-JSON payload is passed
    through as text.
    """
    event = "message"
    data_lines: list[str] = []
    async for line in lines:
        line = line.rstrip("\r")
        if line == "":
            if data_lines:
                yield event, _decode_sse("\n".join(data_lines))
            event, data_lines = "message", []
            continue
        if line.startswith(":"):
            continue
        field, sep, value = line.partition(":")
        if not sep:
            continue
        if value.startswith(" "):
            value = value[1:]
        if field == "event":
            event = value
        elif field == "data":
            data_lines.append(value)
    if data_lines:
        yield event, _decode_sse("\n".join(data_lines))


def _decode_sse(payload: str) -> Any:
    """JSON-decode an SSE data field; non-JSON payloads pass through."""
    try:
        return json.loads(payload)
    except ValueError:
        return payload


# --- rendering --------------------------------------------------------------


async def _start_step(data: dict[str, Any]) -> cl.Step:
    """Send the tool step stub for a ``tool_start`` frame."""
    step = cl.Step(name=str(data.get("tool") or "tool"), type="tool")
    step.input = preview(data.get("args"))
    await step.send()
    return step


async def _end_step(steps: dict[str, cl.Step], data: dict[str, Any]) -> None:
    """Close the matching tool step for a ``tool_end`` frame (M-21 marker)."""
    step = steps.pop(str(data.get("run_id")), None)
    if step is None:
        step = await _start_step(data)
    step.output = preview(data.get("output"))
    if data.get("from_cache"):
        step.name = f"{step.name} (cached)"  # M-21 cache-hit indicator
    await step.update()


async def _close_steps(steps: dict[str, cl.Step]) -> None:
    """Terminate tool steps left open when a run ends or fails."""
    while steps:
        _, step = steps.popitem()
        if not step.output:
            step.output = "(no output — run ended)"
        await step.update()


async def _render_events(
    reply: cl.Message,
    steps: dict[str, cl.Step],
    lines: AsyncIterator[str],
) -> tuple[dict[str, Any], PendingInterrupt | None, str]:
    """Render one SSE stream into ``reply``/``steps``.

    Returns ``(done_payload, pending_interrupt, error_detail)`` — the
    ``interrupt`` frame (or the ``pending_interrupt`` field of ``done``)
    supplies the payload for the M-16 ask-prompt, ``error`` frames
    accumulate into ``error_detail``.
    """
    done: dict[str, Any] = {}
    pending: PendingInterrupt | None = None
    error = ""
    streamed = False

    async for kind, data in iter_sse(lines):
        if kind == "token":
            text = (
                str(data.get("content") or "") if isinstance(data, dict) else str(data)
            )
            if text:
                await reply.stream_token(text)
                streamed = True
        elif kind == "tool_start":
            steps[str(data.get("run_id"))] = await _start_step(data)
        elif kind == "tool_end":
            await _end_step(steps, data)
        elif kind == "interrupt" and isinstance(data, dict):
            pending = _pending_from(data)
        elif kind == "error":
            error = str(data.get("detail") if isinstance(data, dict) else data)
        elif kind == "done" and isinstance(data, dict):
            done = data

    if not done:
        return {}, pending, error or "stream ended without a done event"
    if pending is None and done.get("status") == "interrupted":
        pending = _pending_from(done.get("pending_interrupt"))
    if done.get("status") == "ok" and not streamed:
        # Non-streaming models: the server falls back to the checkpointed
        # answer, so nothing is lost when no token frames arrived.
        fallback = str(done.get("reply") or "")
        if fallback:
            await reply.stream_token(fallback)
    if done.get("status") == "error" and not error:
        error = "run failed"
    return done, pending, error


def _pending_from(payload: Any) -> PendingInterrupt | None:
    """Build a :class:`PendingInterrupt` from an ``interrupt`` payload."""
    if not isinstance(payload, dict) or not payload.get("tool"):
        return None
    return PendingInterrupt(
        tool=str(payload.get("tool")),
        args=dict(payload.get("args") or {}),
        reason=str(payload.get("reason") or ""),
    )


async def _stream(
    client: httpx.AsyncClient,
    path: str,
    body: dict[str, Any],
    reply: cl.Message,
    steps: dict[str, cl.Step],
) -> tuple[dict[str, Any], PendingInterrupt | None, str]:
    """POST one turn/resume and render its SSE stream (``?stream=true``)."""
    async with client.stream(
        "POST", path, params={"stream": "true"}, json=body
    ) as response:
        if response.status_code != 200:
            await response.aread()
            raise ApiError(f"{response.status_code}: {response.text}")
        return await _render_events(reply, steps, response.aiter_lines())


# --- session lifecycle ------------------------------------------------------


async def _create_session(client: httpx.AsyncClient) -> tuple[str, bool]:
    """Create a session through ``POST /sessions`` (M-24).

    Returns ``(thread_id, degraded)``. A database outage (503) falls back
    to a locally generated id — the stream path logs best-effort and the
    chat keeps working without persistence, exactly like the pre-M-24
    UI did.
    """
    response = await client.post("/sessions", json={})
    if response.status_code == 200:
        return str(response.json().get("session_id") or uuid.uuid4()), False
    if response.status_code == 503:
        logger.warning("session row not persisted (PostgreSQL?): using local id")
        return str(uuid.uuid4()), True
    raise ApiError(f"{response.status_code}: {response.text}")


async def _list_sessions(
    client: httpx.AsyncClient,
) -> list[dict[str, Any]] | None:
    """Session rows for the sidebar (``GET /sessions``); ``None`` on error."""
    try:
        response = await client.get("/sessions", params={"page": 1, "size": 10})
        response.raise_for_status()
        return list(response.json().get("items") or [])
    except (httpx.HTTPError, ValueError, KeyError) as exc:
        logger.warning("session list unavailable: %s", exc)
        return None


async def _load_history(client: httpx.AsyncClient, thread_id: str) -> bool:
    """Replay a session's messages into the chat from ``GET /sessions/{id}``."""
    response = await client.get(f"/sessions/{thread_id}")
    if response.status_code == 404:
        return False
    response.raise_for_status()
    session = response.json()
    for entry in session.get("messages") or []:
        if entry.get("role") not in {"user", "assistant"}:
            continue
        text = entry.get("content")
        if text:
            await cl.Message(content=content_text(text)).send()
    return True


# --- /learn slash-command (M-26) ----------------------------------------------


def _learn_args(text: str) -> dict[str, Any]:
    """Parse ``/learn [name] [description]`` into a POST body (M-26).

    ``shlex`` honours quotes — ``/learn refactor_extract "Extract the
    function"`` yields ``pattern_name=refactor_extract`` and the quoted
    description; unbalanced quotes fall back to a plain split.
    """
    rest = text[len("/learn") :].strip()
    try:
        tokens = shlex.split(rest)
    except ValueError:
        tokens = rest.split()
    body: dict[str, Any] = {}
    if tokens:
        body["pattern_name"] = tokens[0]
    if len(tokens) > 1:
        body["description"] = " ".join(tokens[1:])
    return body


async def _handle_learn(thread_id: str, text: str) -> None:
    """Run ``/learn`` against ``POST /sessions/{id}/learn`` (M-26).

    No confirmation prompt (BACKLOG6: ``/learn`` is an explicit user
    action) — the endpoint answer is rendered as the feedback line.
    """
    try:
        async with make_client() as client:
            response = await client.post(
                f"/sessions/{thread_id}/learn", json=_learn_args(text)
            )
    except httpx.HTTPError as exc:
        logger.exception("learn request failed (thread_id=%s)", thread_id)
        await cl.Message(
            content=(
                f"FastAPI server unreachable at `{api_url()}` ({exc}) — "
                "start it with `make dev` and retry."
            )
        ).send()
        return

    if response.status_code != 200:
        try:
            detail = str(response.json().get("detail") or response.text)
        except ValueError:
            detail = response.text
        await cl.Message(content=f"/learn failed: {detail}").send()
        return

    data = response.json()
    compacted = str(bool(data.get("compacted"))).lower()
    logger.info(
        "/learn captured %s -> %s (thread_id=%s)",
        data.get("learned_id"),
        data.get("file"),
        thread_id,
    )
    await cl.Message(
        content=(
            f"✅ Learned: `{data.get('learned_id')}` → {data.get('file')} "
            f"(compacted: {compacted})"
        )
    ).send()


# --- handlers ----------------------------------------------------------------


@cl.on_chat_start
async def on_chat_start() -> None:
    """Create the session through FastAPI and render the M-17 panels."""
    try:
        async with make_client() as client:
            thread_id, degraded = await _create_session(client)
    except (httpx.HTTPError, ApiError) as exc:
        logger.error("cannot start a session: %s", exc)
        await cl.Message(
            content=(
                f"FastAPI server unreachable at `{api_url()}` — the chat "
                "cannot start. Run the API (`make dev`) and reload, or set "
                "`ORYA_API_URL` to its address."
            )
        ).send()
        return

    cl.user_session.set("thread_id", thread_id)
    logger.info(
        "Chainlit session started: thread_id=%s degraded=%s", thread_id, degraded
    )

    if degraded:
        await cl.Message(
            content=(
                "PostgreSQL is unavailable — this session is kept in memory "
                "only (no resume after a restart)."
            )
        ).send()

    settings = load_settings()
    await _show_sidebar()
    await _show_settings_panel(settings)


async def _show_sidebar() -> None:
    """Sidebar: new-session button plus the server's session list (M-17)."""
    elements: list[cl.Action] = [
        cl.Action(name="new_session", payload={"thread_id": None}, label="New session")
    ]
    sessions = await _list_sessions(make_client()) or []
    for session in sessions:
        session_id = str(session.get("session_id") or "")
        if not session_id:
            continue
        label = str(session.get("title") or session_id[:8])
        elements.append(
            cl.Action(
                name="switch_session",
                payload={"thread_id": session_id},
                label=label,
            )
        )
    await cl.ChatSettings(title="Sessions", elements=elements).send()


async def _show_settings_panel(settings: UISettings) -> None:
    """Settings panel: model, permission mode and allow-list (M-17)."""
    current_model = settings.model or "default"
    current_mode = settings.permission_mode or "strict"
    elements: list[dict[str, Any]] = [
        {
            "label": "Model",
            "type": "select",
            "options": model_choices(),
            "default": current_model,
        },
        {
            "label": "Permission Mode",
            "type": "select",
            "options": [("strict", "Strict"), ("permissive", "Permissive")],
            "default": current_mode,
        },
        {
            "label": "Allow List (newline-separated patterns)",
            "type": "textarea",
            "default": "\n".join(settings.allow_list),
        },
    ]
    await cl.ChatSettings(title="Settings", elements=elements).send()


@cl.on_settings_update
async def on_settings_update(settings_data: dict) -> None:
    """Persist the settings panel (applied on the next request, M-24)."""
    settings = load_settings()
    settings.model = settings_data.get("Model")
    settings.permission_mode = settings_data.get("Permission Mode")
    allow_list = settings_data.get("Allow List (newline-separated patterns)", "")
    settings.allow_list = [
        line.strip() for line in allow_list.split("\n") if line.strip()
    ]
    save_settings(settings)
    logger.info(
        "Settings updated: model=%s mode=%s", settings.model, settings.permission_mode
    )
    await cl.Message(
        content="Settings saved — they apply from the next message."
    ).send()


@cl.action_callback("new_session")
async def on_new_session(action: cl.Action) -> None:
    """Start a fresh session through ``POST /sessions``."""
    try:
        async with make_client() as client:
            thread_id, _ = await _create_session(client)
    except (httpx.HTTPError, ApiError) as exc:
        await cl.Message(content=f"Cannot start a new session: {exc}").send()
        return

    cl.user_session.set("thread_id", thread_id)
    logger.info("New session started: thread_id=%s", thread_id)
    await cl.Message(content=f"New session started: {thread_id[:8]}").send()
    await _show_sidebar()


@cl.action_callback("switch_session")
async def on_switch_session(action: cl.Action) -> None:
    """Switch to an existing session and replay its history."""
    thread_id = action.payload.get("thread_id")
    if not thread_id:
        await cl.Message(content="Invalid session ID").send()
        return

    try:
        async with make_client() as client:
            found = await _load_history(client, str(thread_id))
    except httpx.HTTPError as exc:
        await cl.Message(content=f"Failed to switch session: {exc}").send()
        return

    if not found:
        await cl.Message(
            content=f"Session {str(thread_id)[:8]} not found on the server."
        ).send()
        return

    cl.user_session.set("thread_id", str(thread_id))
    logger.info("Switched to session: thread_id=%s", thread_id)
    await cl.Message(content=f"Switched to session: {str(thread_id)[:8]}").send()
    await _show_sidebar()


@cl.on_message
async def on_message(message: cl.Message) -> None:
    """Stream one user turn through the FastAPI SSE endpoint (M-15/M-24)."""
    thread_id = cl.user_session.get("thread_id")
    text = (message.content or "").strip()
    if not thread_id:
        await cl.Message(content=_SESSION_HINT).send()
        return
    if not text:
        return
    if text == "/learn" or text.startswith("/learn "):
        # M-26: slash-command — a memory write, never a chat turn.
        await _handle_learn(str(thread_id), text)
        return

    settings = load_settings()
    overrides = settings_payload(settings)
    reply = cl.Message(content="")
    steps: dict[str, cl.Step] = {}

    try:
        async with make_client() as client:
            done, pending, error = await _stream(
                client,
                f"/sessions/{thread_id}/messages",
                {**overrides, "content": text},
                reply,
                steps,
            )
            # M-16: resolve permission pauses — ask, resume, re-check.
            # A batch pauses once per tool call, so this is a loop.
            while True:
                if error or done.get("status") == "error":
                    break
                if done.get("status") != "interrupted":
                    break
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
                done, pending, error = await _stream(
                    client,
                    f"/sessions/{thread_id}/resume",
                    {**overrides, "decision": _DECISIONS.get(answer, "deny")},
                    reply,
                    steps,
                )
    except ApiError as exc:
        logger.exception("UI run failed (thread_id=%s)", thread_id)
        await _close_steps(steps)
        await cl.Message(content=f"Run failed: {exc}").send()
        return
    except httpx.HTTPError as exc:
        logger.exception("API request failed (thread_id=%s)", thread_id)
        await _close_steps(steps)
        await cl.Message(
            content=(
                f"FastAPI server unreachable at `{api_url()}` ({exc}) — "
                "start it with `make dev` and retry."
            )
        ).send()
        return

    await _close_steps(steps)
    if error or done.get("status") == "error":
        await cl.Message(content=f"Run failed: {error or 'unknown error'}").send()
        return
    if reply.content:
        await reply.send()
