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
the server, which builds the model and the policy for the session. The
Model combobox depends on the Provider one — Chainlit has no dependent
selects, so the panel re-sends itself (``on_settings_edit`` while the
dialog is open, ``on_settings_update`` on Confirm) with the model list
re-filtered to the selected provider.

M-26 adds the ``/learn`` slash-command (BACKLOG6): a message starting
with ``/learn [name] [description]`` is *not* a chat turn — it calls
``POST /sessions/{id}/learn`` (capture the last successful tool-call
sequence into ``LEARNED.md``) and renders the
``✅ Learned: learn_001 → LEARNED.md (compacted: false)`` feedback.
Chainlit 2.x has no ``on_slash_command`` hook, so the command is parsed
at the top of ``on_message``.

M-27 adds the ``/memory*`` family the same way: ``/memory`` (cat the four
L0 files), ``/memory stats`` / ``/memory/stats`` and ``/memory compact`` /
``/memory/compact`` call the session-scoped endpoints and render a stats
table, a per-file compaction report or the markdown content — again never
a chat turn.

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
from chainlit.input_widget import Select, TextInput

from app.core.agent import PendingInterrupt, content_text, preview
from app.core.config import get_settings
from app.core.logging_setup import install_file_logger
from app.ui.interrupt import ask_permission
from app.ui.settings import (
    UISettings,
    load_settings,
    model_choices,
    provider_choices,
    save_settings,
)

logger = logging.getLogger(__name__)

# logs/ui.log — the start scripts' stdout/stderr redirect loses the handles
# of the uv launcher on Windows, so the app writes its own file log.
install_file_logger(
    "ui.log",
    level=getattr(
        logging, str(get_settings().log_level or "INFO").upper(), logging.INFO
    ),
)

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
        "provider": settings.provider,
        "permission_mode": settings.permission_mode,
        "allow_list": list(settings.allow_list),
        "working_dir": settings.working_dir,
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

    The UI's saved project (``settings.working_dir``) ships with the
    create call so a new session opens the last opened folder right away.

    Returns ``(thread_id, degraded)``. A database outage (503) falls back
    to a locally generated id — the stream path logs best-effort and the
    chat keeps working without persistence, exactly like the pre-M-24
    UI did.
    """
    settings = load_settings()
    payload: dict[str, Any] = {}
    if settings.working_dir:
        payload["working_dir"] = settings.working_dir
    response = await client.post("/sessions", json=payload)
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


# --- /memory slash-commands (M-27) -------------------------------------------


#: Usage hint for an unrecognised ``/memory`` subcommand.
_MEMORY_USAGE = (
    "Usage: `/memory` (show the L0 files), `/memory stats`, "
    "`/memory compact` — the `/memory/…` spellings work too."
)

#: Accepted subcommands per spelling (defaults to ``cat``).
_MEMORY_ACTIONS = {
    "": "cat",
    "cat": "cat",
    "show": "cat",
    "view": "cat",
    "stats": "stats",
    "compact": "compact",
}


def _memory_action(text: str) -> str | None:
    """Classify a ``/memory*`` command (M-27) — ``None`` when it is not one.

    Returns ``cat`` / ``stats`` / ``compact`` for ``/memory [sub]`` and
    ``/memory/{stats,compact}``, ``help`` for an unknown subcommand, and
    ``None`` for anything else (so the message still reaches the model).
    """
    token = text.split(maxsplit=1)[0]
    if token == "/memory":
        rest = text.split(maxsplit=2)
        sub = rest[1] if len(rest) > 1 else ""
    elif token.startswith("/memory/"):
        sub = token.split("/", 2)[2]
    else:
        return None
    return _MEMORY_ACTIONS.get(sub.lower(), "help")


async def _handle_memory(thread_id: str, action: str) -> None:
    """Run a ``/memory*`` command against the session-scoped endpoints (M-27)."""
    if action == "help":
        await cl.Message(content=_MEMORY_USAGE).send()
        return

    path = f"/sessions/{thread_id}/memory"
    if action in {"stats", "compact"}:
        path = f"{path}/{action}"
    try:
        async with make_client() as client:
            if action == "compact":
                response = await client.post(path)
            else:
                response = await client.get(path)
    except httpx.HTTPError as exc:
        logger.exception("memory %s request failed (thread_id=%s)", action, thread_id)
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
        await cl.Message(content=f"/memory {action} failed: {detail}").send()
        return

    await cl.Message(content=_render_memory(action, response.json())).send()


def _render_memory(action: str, data: dict[str, Any]) -> str:
    """Render an endpoint payload as one Chainlit message."""
    if action == "stats":
        rows = [
            "| File | Size | Entries | Lines | Tokens | Last write |",
            "|---|---:|---:|---:|---:|---|",
        ]
        for entry in data.get("files") or []:
            rows.append(
                f"| `{entry.get('name')}` | {entry.get('size_bytes')} B "
                f"| {entry.get('entries_count')} | {entry.get('line_count')} "
                f"| {entry.get('token_count')} | {entry.get('last_write_ts')} |"
            )
        rows.append("")
        rows.append(
            f"Total: **{data.get('total_size_bytes')} B** · last compacted: "
            f"{data.get('last_compacted') or 'never'}"
        )
        return "\n".join(rows)

    if action == "compact":
        rows = []
        for result in data.get("results") or []:
            if result.get("changed"):
                rows.append(
                    f"- `{result.get('file')}`: {result.get('before_bytes')} → "
                    f"{result.get('after_bytes')} B (kept {result.get('kept')}, "
                    f"archived {result.get('archived')})"
                )
            else:
                rows.append(
                    f"- `{result.get('file')}`: nothing to archive "
                    f"({result.get('kept')} kept)"
                )
        return f"✅ Compacted {data.get('total_archived')} entries:\n" + "\n".join(rows)

    return str(data.get("markdown") or "")


# --- «Open project» folder browser --------------------------------------------


def _browser_actions(data: dict[str, Any]) -> list[cl.Action]:
    """Action buttons for one ``GET /workspace/browse`` listing."""
    actions = [
        cl.Action(
            name="open_project_nav",
            payload={"path": entry["path"]},
            label=str(entry["name"]),
        )
        for entry in data.get("dirs") or []
    ]
    parent = data.get("parent")
    if parent:
        actions.append(
            cl.Action(
                name="open_project_nav", payload={"path": parent}, label=".. (up)"
            )
        )
    actions.append(
        cl.Action(
            name="open_project_open",
            payload={"path": data.get("path")},
            label="Open this folder",
        )
    )
    actions.append(cl.Action(name="open_project_cancel", payload={}, label="Cancel"))
    return actions


def _browser_content(data: dict[str, Any]) -> str:
    """Message body above the folder buttons."""
    dirs = data.get("dirs") or []
    note = " (listing truncated)" if data.get("truncated") else ""
    empty = "\n\n_(no subfolders — open this folder or go up)_" if not dirs else ""
    return f"**Open project** — pick a folder{note}:\n\n`{data.get('path')}`{empty}"


async def _browse(path: str | None = None) -> dict[str, Any] | None:
    """Fetch one directory listing; ``None`` after an error message."""
    try:
        async with make_client() as client:
            params = {"path": path} if path else {}
            response = await client.get("/workspace/browse", params=params)
    except httpx.HTTPError as exc:
        logger.exception("browse request failed (path=%s)", path)
        await cl.Message(
            content=(
                f"FastAPI server unreachable at `{api_url()}` ({exc}) — "
                "start it with `make dev` and retry."
            )
        ).send()
        return None
    if response.status_code != 200:
        try:
            detail = str(response.json().get("detail") or response.text)
        except ValueError:
            detail = response.text
        await cl.Message(content=f"Cannot open `{path}`: {detail}").send()
        return None
    return response.json()


async def _show_browser(data: dict[str, Any]) -> None:
    """Send a fresh browser message and remember it for in-place updates."""
    message = cl.Message(content=_browser_content(data), actions=_browser_actions(data))
    await message.send()
    cl.user_session.set("project_browser", message)


async def _update_browser(content: str) -> None:
    """Replace the browser message with ``content`` (no buttons)."""
    message = cl.user_session.get("project_browser")
    if message is None:
        await cl.Message(content=content).send()
        return
    message.content = content
    message.actions = []
    await message.update()


async def _start_project_browser(path: str | None = None) -> None:
    """Open the folder browser at ``path`` (default: the current project)."""
    if path is None:
        path = load_settings().working_dir
    data = await _browse(path)
    if data is not None:
        await _show_browser(data)


async def _apply_project(path: str) -> None:
    """Open ``path``: persist it on the session row + save as UI default.

    The session patch is best-effort — the UI default is saved even when
    the database is down (the turn-level override still applies), and a
    400 (bad path) keeps both the old default and the old session row.
    """
    thread_id = cl.user_session.get("thread_id")
    resolved = path
    if thread_id:
        try:
            async with make_client() as client:
                response = await client.patch(
                    f"/sessions/{thread_id}", json={"working_dir": path}
                )
        except httpx.HTTPError as exc:
            logger.warning(
                "project open not persisted (thread_id=%s): %s", thread_id, exc
            )
        else:
            if response.status_code == 400:
                try:
                    detail = str(response.json().get("detail") or response.text)
                except ValueError:
                    detail = response.text
                await _update_browser(f"Cannot open `{path}`: {detail}")
                return
            if response.status_code == 200:
                resolved = str(response.json().get("working_dir") or path)
            else:
                logger.warning(
                    "project open: unexpected status %s (thread_id=%s)",
                    response.status_code,
                    thread_id,
                )
    settings = load_settings()
    settings.working_dir = resolved
    save_settings(settings)
    logger.info("project opened: %s (thread_id=%s)", resolved, thread_id)
    await _update_browser(f"✅ Project opened: `{resolved}`")


@cl.action_callback("open_project")
async def on_open_project(action: cl.Action) -> None:
    """Sidebar button: start the folder browser at the current project."""
    await _start_project_browser()


@cl.action_callback("open_project_nav")
async def on_open_project_nav(action: cl.Action) -> None:
    """Browser button: re-list at the clicked directory (in-place update)."""
    path = str(action.payload.get("path") or "")
    data = await _browse(path)
    if data is None:
        return
    message = cl.user_session.get("project_browser")
    if message is None:
        await _show_browser(data)
        return
    message.content = _browser_content(data)
    message.actions = _browser_actions(data)
    await message.update()


@cl.action_callback("open_project_open")
async def on_open_project_open(action: cl.Action) -> None:
    """Browser button: open the folder the listing is at."""
    path = str(action.payload.get("path") or "")
    if path:
        await _apply_project(path)


@cl.action_callback("open_project_cancel")
async def on_open_project_cancel(action: cl.Action) -> None:
    """Browser button: dismiss the picker."""
    await _update_browser("Open project cancelled.")


async def _handle_open(text: str) -> None:
    """``/open [path]`` — the slash-command twin of the browser button."""
    path = text[len("/open") :].strip()
    if path:
        await _apply_project(path)
        return
    await _start_project_browser()


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
    """Session switcher + «Open project» button (M-17, folder browser).

    Chainlit 2.x renders only ``InputWidget`` instances inside
    ``ChatSettings`` (dict-style panels were silently dropped and showed
    nothing), so the session list travels as a regular message with
    ``cl.Action`` buttons instead. The project line reports the folder
    the tools currently resolve against (blank = the server's cwd).
    """
    settings = load_settings()
    project = settings.working_dir or "(server cwd)"
    actions: list[cl.Action] = [
        cl.Action(name="new_session", payload={"thread_id": None}, label="New session"),
        cl.Action(name="open_project", payload={}, label="Open project"),
    ]
    sessions = await _list_sessions(make_client()) or []
    for session in sessions:
        session_id = str(session.get("session_id") or "")
        if not session_id:
            continue
        label = str(session.get("title") or session_id[:8])
        actions.append(
            cl.Action(
                name="switch_session",
                payload={"thread_id": session_id},
                label=label,
            )
        )
    await cl.Message(
        content=(
            f"**Sessions** — pick one or start a new session.\n\nProject: `{project}`"
        ),
        actions=actions,
    ).send()


def _settings_from_payload(settings_data: dict) -> UISettings:
    """Build a transient ``UISettings`` from a settings-panel payload.

    Keys are the widget ids created by :func:`_show_settings_panel`
    (``Provider`` / ``Model`` / ``Permission Mode`` / ``Allow List`` /
    ``Working directory``), exactly as the panel shows them — including
    edits the user has not confirmed yet. The result is *not* persisted:
    :func:`on_settings_edit` keeps it transient, :func:`on_settings_update`
    saves it.
    """
    raw_provider = settings_data.get("Provider")
    allow_list = str(settings_data.get("Allow List") or "")
    working_dir = str(settings_data.get("Working directory") or "").strip()
    return UISettings(
        provider=None if raw_provider in (None, "", "Auto") else str(raw_provider),
        model=settings_data.get("Model"),
        permission_mode=settings_data.get("Permission Mode"),
        allow_list=[line.strip() for line in allow_list.split("\n") if line.strip()],
        working_dir=working_dir or None,
    )


async def _show_settings_panel(settings: UISettings) -> None:
    """Settings panel: provider, model, permission mode, allow-list, workspace.

    Chainlit 2.x requires real ``InputWidget`` objects; a ``Select`` takes
    its default through ``initial_value`` (``initial`` is overwritten by
    the widget's own ``__post_init__``).

    The Model combobox depends on the Provider one: its values come from
    ``model_choices(provider)``. Chainlit has no dependent selects, so the
    panel re-sends itself whenever the provider changes — from
    :func:`on_settings_edit` (live, while the dialog is open) and from
    :func:`on_settings_update` (on Confirm). The provider the current panel
    was built with is remembered as ``panel_provider`` so the edit handler
    can tell a real provider change from an unrelated keystroke.
    """
    providers = provider_choices()
    provider = settings.provider if settings.provider in providers else None
    choices = model_choices(provider) or ["default"]
    if settings.model in choices:
        model_initial: str | None = settings.model
    elif provider is not None:
        model_initial = choices[0]  # align with the on_settings_update reset
    else:
        model_initial = None  # «Auto» — the config default may differ
    widgets: list[Any] = [
        Select(
            id="Provider",
            label="Provider («Auto» = config/env default)",
            values=providers,
            initial_value=provider or "Auto",
        ),
        Select(
            id="Model",
            label="Model",
            values=choices,
            initial_value=model_initial,
        ),
        Select(
            id="Permission Mode",
            label="Permission Mode",
            values=["strict", "permissive"],
            initial_value=settings.permission_mode or "strict",
        ),
        TextInput(
            id="Allow List",
            label="Allow List (newline-separated patterns)",
            initial="\n".join(settings.allow_list),
            multiline=True,
        ),
        TextInput(
            id="Working directory",
            label="Working directory (project to open; blank = server cwd)",
            initial=settings.working_dir or "",
        ),
    ]
    # Remember the provider this panel was built with: the edit handler
    # compares against it to decide whether the Model list must refresh.
    cl.user_session.set("panel_provider", provider)
    await cl.ChatSettings(widgets).send()


@cl.on_settings_update
async def on_settings_update(settings_data: dict) -> None:
    """Persist the settings panel (applied on the next request, M-24).

    Keys are the widget ids sent by :func:`_show_settings_panel`.
    A changed Provider re-sends the panel so the Model combobox only
    lists that provider's models; a model left over from another
    provider is reset to the first valid choice so the payload always
    matches what the dropdown shows.
    """
    settings = load_settings()
    previous_provider = settings.provider
    payload = _settings_from_payload(settings_data)
    settings.provider = payload.provider
    settings.model = payload.model
    if settings.provider is not None:
        choices = model_choices(settings.provider) or ["default"]
        if settings.model not in choices:
            settings.model = choices[0]
    settings.permission_mode = payload.permission_mode
    settings.allow_list = payload.allow_list
    settings.working_dir = payload.working_dir
    save_settings(settings)
    logger.info(
        "Settings updated: provider=%s model=%s mode=%s working_dir=%s",
        settings.provider,
        settings.model,
        settings.permission_mode,
        settings.working_dir,
    )
    provider_changed = settings.provider != previous_provider
    if provider_changed:
        # Refresh the panel: the Model combobox now lists this provider only.
        await _show_settings_panel(settings)
    workspace_note = (
        f"\nProject: `{settings.working_dir}`" if settings.working_dir else ""
    )
    provider_note = ""
    if provider_changed:
        provider_note = (
            f"\nProvider: `{settings.provider or 'Auto'}` — "
            "the model list was refreshed."
        )
    await cl.Message(
        content=(
            "Settings saved — they apply from the next message."
            f"{provider_note}{workspace_note}"
        )
    ).send()


@cl.on_settings_edit
async def on_settings_edit(settings_data: dict) -> None:
    """Live-refresh the Model combobox when Provider changes (open dialog).

    Chainlit has no dependent selects: the client only emits
    ``chat_settings_edit`` while the panel dialog is open, carrying the
    *whole* form (a TextInput fires it per keystroke). The panel is
    therefore re-sent only when the payload's provider differs from the
    one the currently displayed panel was built with
    (``panel_provider``) — otherwise a keystroke in the Allow List would
    reset the form and drop the focus.

    The re-send is transient: nothing is written to the settings file
    (the user may still press Cancel), and the widgets are built from
    the payload, so unsaved edits to the other fields survive the
    refresh. A model left over from another provider is simply not in
    the new list, so the Model select falls back to the first valid
    choice.
    """
    settings = _settings_from_payload(settings_data)
    if settings.provider == cl.user_session.get("panel_provider"):
        return  # not a provider change — leave the dialog alone
    logger.info(
        "Settings edit: provider=%s -> refreshing the model list",
        settings.provider or "Auto",
    )
    await _show_settings_panel(settings)


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
    if text == "/open" or text.startswith("/open "):
        # Folder browser — open a project, never a chat turn.
        await _handle_open(text)
        return
    memory_action = _memory_action(text)
    if memory_action is not None:
        # M-27: slash-command — reads/compacts L0, never a chat turn.
        await _handle_memory(str(thread_id), memory_action)
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
