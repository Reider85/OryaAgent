"""Sessions API (M-20/M-24): /sessions CRUD, JSON turns and SSE streaming.

REST endpoints for every client — the Chainlit UI (M-24), CI, batch jobs
and the future Next.js frontend. Both layers reuse the shared runtime in
:mod:`app.core.agent` (graph assembly, checkpointer resolution,
``stream_turn``/``run_turn``) so nothing is duplicated.

* ``POST   /sessions``               — create a session (server-side uuid);
* ``GET    /sessions``               — paginated list (``?page=1&size=20``);
* ``GET    /sessions/{id}``          — metadata + typed messages;
* ``POST   /sessions/{id}/messages`` — run one full turn. Default: JSON
  response (``status`` is ``ok`` or ``interrupted`` at the M-13
  permission gate); ``?stream=true``: ``text/event-stream`` with
  ``token`` / ``tool_start`` / ``tool_end`` / ``interrupt`` / ``done``
  (``error`` on a mid-run failure) — the transport the Chainlit UI uses;
* ``POST   /sessions/{id}/resume``   — answer a pending interrupt
  (``decision``: ``allow`` / ``deny`` / ``always``), JSON or SSE with
  the same flag;
* ``PATCH  /sessions/{id}``          — open/close the project directory
  (``working_dir``; the UI's «Open project» browser uses it);
* ``DELETE /sessions/{id}``          — soft-delete (``status='closed'``).

Settings overrides: ``messages``/``resume`` accept the UI settings-panel
state (``model``, ``permission_mode``, ``allow_list``, ``working_dir``)
so the server — not the client — assembles the graph with the chosen
model and policy. ``working_dir`` opens a project directory for the
session (app/core/workspace.py): it is validated (400 when unusable),
persisted on the ``sessions`` row and bound to the turn so every tool
resolves relative paths and runs subprocesses against it.

Graph-build failures are mapped instead of leaking: a ``ValueError`` from
the LLM seam (missing API key, unknown model) is a 400 with the reason —
before this mapping every misconfiguration surfaced as a bare 500.

Permission policy note: each session caches one :class:`PermissionPolicy`
process-wide so the M-13 session allowlist («Approve & don't ask again»)
survives across ``/messages`` and ``/resume`` calls — the same lifetime
the Chainlit UI gave it via ``cl.user_session``. Changing the settings
overrides rebuilds the policy and carries the allowlist over.

Database failures surface as 503 in JSON mode (soft-fail only in the UI
layer); the SSE mode mirrors the UI's best-effort logging and reports
``degraded: true`` in ``done`` instead. An unreachable Postgres
checkpointer degrades to in-memory state everywhere.
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.core.agent import (
    PendingInterrupt,
    TurnResult,
    build_session_graph,
    get_pending_interrupt,
    has_pending_interrupt,
    resolve_checkpointer,
    run_resume,
    run_turn,
    stream_resume,
    stream_turn,
)
from app.core.graph import default_run_config
from app.core.permissions import PermissionPolicy, build_policy
from app.core.workspace import open_workspace, set_workspace, workspace_scope
from app.db.session_log import (
    create_session,
    ensure_session,
    get_session,
    list_messages,
    list_sessions,
    log_message,
    set_session_status,
    set_session_working_dir,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/sessions", tags=["sessions"])

#: Process-wide per-session permission policies (M-13 session allowlist
#: lifetime). Keyed by session_id → ``(settings key, policy)``; recreated
#: on process restart. The settings key is ``(mode, allow_list)`` — a
#: change rebuilds the policy and carries the session allowlist over.
_session_policies: dict[str, tuple[tuple[Any, ...], PermissionPolicy]] = {}

#: SSE response headers: no buffering anywhere in the chain (M-24).
_SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}


class SessionCreate(BaseModel):
    """Request body for ``POST /sessions``."""

    title: str | None = None
    provider: str | None = None
    model: str | None = None
    working_dir: str | None = None
    metadata: dict[str, Any] | None = None


class TurnSettings(BaseModel):
    """UI settings-panel overrides applied to the graph of this request."""

    model: str | None = None
    permission_mode: Literal["strict", "permissive"] | None = None
    allow_list: list[str] = Field(default_factory=list)
    working_dir: str | None = Field(
        default=None,
        description=(
            "Project directory to open for this session (the tools' root). "
            "Persisted on the session; omit to keep the stored one."
        ),
    )


class MessageCreate(TurnSettings):
    """Request body for ``POST /sessions/{id}/messages``."""

    content: str = Field(min_length=1)


class ResumeRequest(TurnSettings):
    """Request body for ``POST /sessions/{id}/resume``."""

    decision: Literal["allow", "deny", "always"]


class SessionPatch(BaseModel):
    """Request body for ``PATCH /sessions/{id}`` (the «open project» seam).

    ``working_dir`` opens a project directory for the session (validated
    like the per-turn override, persisted on the row); ``None`` closes
    the project so the tools fall back to the server cwd.
    """

    working_dir: str | None = None


def _policy_for(
    session_id: str,
    mode: str | None = None,
    allow_list: list[str] | None = None,
) -> PermissionPolicy:
    """Return the cached per-session policy for the requested settings.

    Created on first use; rebuilt when the client changes the permission
    mode or allow-list, with the M-13 session allowlist carried over so
    «don't ask again» decisions survive a settings edit.
    """
    key: tuple[Any, ...] = (mode, tuple(allow_list or ()))
    cached = _session_policies.get(session_id)
    if cached is not None and cached[0] == key:
        return cached[1]

    policy = build_policy(mode, allow_patterns=allow_list or ())
    if cached is not None:
        for tool in cached[1].session_allowed_tools():
            policy.record_session_allow(tool)
    _session_policies[session_id] = (key, policy)
    return policy


async def _resolve_workspace(
    session_id: str,
    requested: str | None,
    stored: str | None,
    *,
    soft: bool,
) -> tuple[Path | None, bool]:
    """Resolve the project directory («open project») of this turn.

    ``requested`` (the request's ``working_dir`` override) wins and is
    persisted on the session row so later turns keep the project open;
    otherwise the value stored on the session is used. Returns
    ``(path_or_None, degraded)`` — ``None`` keeps the process cwd as the
    tools' root. An unusable path is a client error: HTTP 400.
    """
    candidate = requested if requested is not None else stored
    if not candidate:
        return None, False
    try:
        workspace = open_workspace(candidate)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    degraded = False
    if requested is not None and str(workspace) != (stored or ""):
        if soft:
            degraded = await _soft_db(
                set_session_working_dir(session_id, str(workspace))
            )
        else:
            await _db(set_session_working_dir(session_id, str(workspace)))
    return workspace, degraded


async def _stream_in_workspace(
    events: AsyncIterator[Any], workspace: Path | None
) -> AsyncIterator[Any]:
    """Bind ``workspace`` for the whole stream (tools read it per task).

    The SSE body is iterated *after* the endpoint returned, so the
    ``ContextVar`` is bound inside the stream, not around it. The reset
    writes ``None`` (the documented default) instead of a token, because
    a stream may be driven from more than one task context.
    """
    set_workspace(workspace)
    try:
        async for event in events:
            yield event
    finally:
        set_workspace(None)


def _pending_dict(pending: PendingInterrupt | None) -> dict[str, Any] | None:
    """Serialize a :class:`PendingInterrupt` for the JSON/SSE payload."""
    if pending is None:
        return None
    return {"tool": pending.tool, "args": pending.args, "reason": pending.reason}


def _result_dict(session_id: str, result: TurnResult, degraded: bool) -> dict[str, Any]:
    """Build the shared response shape of the JSON /messages and /resume."""
    return {
        "session_id": session_id,
        "status": result.status,
        "reply": result.reply,
        "tool_steps": result.tool_steps,
        "pending_interrupt": _pending_dict(result.pending),
        "degraded": degraded,
    }


def _sse(event: str, data: Any) -> str:
    """Serialize one Server-Sent Event frame (BACKLOG5 M-20/M-24 shape)."""
    payload = json.dumps(data, ensure_ascii=False, default=str)
    return f"event: {event}\ndata: {payload}\n\n"


async def _db(coro: Any) -> Any:
    """Await a session_log coroutine, mapping DB failures to HTTP 503."""
    try:
        return await coro
    except Exception as exc:
        logger.warning("sessions API database failure: %s", exc)
        raise HTTPException(status_code=503, detail="database unavailable") from exc


async def _soft_db(coro: Any) -> bool:
    """Best-effort session_log write for the SSE path (UI semantics).

    Returns ``True`` when the write failed — the caller reports the turn
    as ``degraded`` instead of aborting a chat the UI already started.
    """
    try:
        await coro
        return False
    except Exception as exc:
        logger.warning("stream session log skipped (database): %s", exc)
        return True


async def _sse_turn(
    session_id: str,
    events: AsyncIterator[Any],
    degraded: bool,
) -> AsyncIterator[str]:
    """Forward a turn stream as SSE frames and log the assistant reply.

    Events flow through unchanged; the terminal ``done`` carries the
    aggregated outcome (plus ``degraded``), and a pause additionally
    emits the ``interrupt`` frame the UI asks the user about (M-16).
    Failures after the response started surface as ``error`` + a final
    ``done`` with ``status="error"`` so the client always sees an end.
    """
    reply = ""
    status = "ok"
    finished = False
    try:
        async for kind, data in events:
            if kind != "done":
                yield _sse(kind, data)
                continue
            finished = True
            status = str(data.get("status", "ok"))
            reply = str(data.get("reply") or "")
            pending = _pending_dict(data.get("pending"))
            if status == "interrupted" and pending is not None:
                yield _sse("interrupt", pending)
            yield _sse(
                "done",
                {
                    "session_id": session_id,
                    "status": status,
                    "reply": reply,
                    "tool_steps": data.get("tool_steps") or [],
                    "pending_interrupt": pending,
                    "degraded": degraded,
                },
            )
    except Exception as exc:
        logger.exception("SSE run failed (session_id=%s)", session_id)
        yield _sse("error", {"detail": str(exc)})
        yield _sse(
            "done",
            {
                "session_id": session_id,
                "status": "error",
                "reply": reply,
                "tool_steps": [],
                "pending_interrupt": None,
                "degraded": degraded,
            },
        )
        return

    if not finished:
        yield _sse("error", {"detail": "turn stream ended without a done event"})
        return
    if status == "ok" and reply:
        await _soft_db(log_message(session_id, "assistant", reply))


def _require_session(session: dict | None, session_id: str) -> dict:
    """Return the session or raise 404."""
    if session is None:
        raise HTTPException(status_code=404, detail=f"Session {session_id!r} not found")
    return session


def _build_graph_or_raise(
    session_id: str,
    checkpointer: Any,
    *,
    model: Any = None,
    policy: Any | None = None,
) -> Any:
    """Assemble the session graph, mapping failures to HTTP errors.

    ``get_llm`` raises ``ValueError`` for the fixable configuration
    problems (missing API key, unknown provider/model alias) — those are
    reported as 400 so the client sees the reason instead of a bare 500;
    anything else is a 502, matching the run/resume failure contract.
    """
    try:
        return build_session_graph(
            session_id,
            checkpointer,
            model=model,
            policy=policy,
        )
    except ValueError as exc:
        logger.exception("graph configuration failed (session_id=%s)", session_id)
        raise HTTPException(
            status_code=400, detail=f"configuration error: {exc}"
        ) from exc
    except Exception as exc:
        logger.exception("graph build failed (session_id=%s)", session_id)
        raise HTTPException(
            status_code=502, detail=f"graph build failed: {exc}"
        ) from exc


@router.post("")
async def create_new_session(body: SessionCreate | None = None) -> dict:
    """Create a new session (M-20): server generates the ``session_id``."""
    body = body or SessionCreate()
    session = await _db(
        create_session(
            title=body.title,
            provider=body.provider,
            model=body.model,
            working_dir=body.working_dir,
            metadata=body.metadata,
        )
    )
    logger.info("session created: %s", session["session_id"])
    return session


@router.get("")
async def list_sessions_endpoint(
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
) -> dict:
    """List sessions newest-activity-first with pagination."""
    rows, total = await _db(list_sessions(limit=size, offset=(page - 1) * size))
    return {"items": rows, "total": total, "page": page, "size": size}


@router.get("/{session_id}")
async def get_session_endpoint(session_id: str) -> dict:
    """Session metadata plus its typed message log (M-14 ``messages``)."""
    session = _require_session(await _db(get_session(session_id)), session_id)
    messages = await _db(list_messages(session_id))
    return {**session, "messages": messages}


@router.post("/{session_id}/messages")
async def post_message(
    session_id: str,
    body: MessageCreate,
    stream: bool = Query(False),
) -> Any:
    """Run one full agent turn (M-20 JSON, M-24 SSE with ``?stream=true``).

    The turn is driven through the shared runtime: the user message is
    logged (M-14), the graph is assembled per session from the request's
    settings overrides, and the run is either aggregated into JSON or
    forwarded as an SSE stream (``token`` / ``tool_start`` / ``tool_end``
    / ``interrupt`` / ``done``). When the M-13 permission gate pauses the
    run the response reports ``status="interrupted"`` with the pending
    tool call; the client answers via ``POST /sessions/{id}/resume``.
    """
    degraded = False
    session_row: dict | None = None
    if stream:
        # UI semantics: the chat already started — report, don't abort.
        degraded |= await _soft_db(ensure_session(session_id))
        degraded |= await _soft_db(log_message(session_id, "user", body.content))
        try:
            session_row = await get_session(session_id)
        except Exception as exc:
            logger.warning("workspace lookup skipped (database): %s", exc)
            degraded = True
    else:
        # Lenient auto-create: CI/batch clients may write into a fresh id.
        await _db(ensure_session(session_id))
        await _db(log_message(session_id, "user", body.content))
        session_row = await _db(get_session(session_id))

    workspace, ws_degraded = await _resolve_workspace(
        session_id,
        body.working_dir,
        None if session_row is None else session_row.get("working_dir"),
        soft=stream,
    )
    degraded = bool(degraded or ws_degraded)

    checkpointer, ck_degraded = await resolve_checkpointer()
    degraded = bool(degraded or ck_degraded)
    graph = _build_graph_or_raise(
        session_id,
        checkpointer,
        model=body.model,
        policy=_policy_for(session_id, body.permission_mode, body.allow_list),
    )
    config = default_run_config(session_id)

    if stream:
        events = _stream_in_workspace(
            stream_turn(graph, body.content, config), workspace
        )
        return StreamingResponse(
            _sse_turn(session_id, events, degraded),
            media_type="text/event-stream",
            headers=_SSE_HEADERS,
        )

    try:
        with workspace_scope(workspace):
            result = await run_turn(graph, body.content, config)
    except Exception as exc:
        logger.exception("API run failed (session_id=%s)", session_id)
        raise HTTPException(status_code=502, detail=f"run failed: {exc}") from exc

    if result.status == "ok" and result.reply:
        await _db(log_message(session_id, "assistant", result.reply))

    return _result_dict(session_id, result, degraded)


@router.post("/{session_id}/resume")
async def post_resume(
    session_id: str,
    body: ResumeRequest,
    stream: bool = Query(False),
) -> Any:
    """Answer a pending permission interrupt (M-20, BACKLOG5 /resume).

    ``decision`` maps to the M-13/M-16 resume contract: ``allow`` →
    approve the tool call, ``deny`` → refuse it, ``always`` → approve and
    record the tool in the session allowlist. 409 when nothing is pending.
    ``?stream=true`` (M-24) forwards the continuation (tool execution +
    the agent's answer) as SSE instead of aggregating it.
    """
    session_row = _require_session(await _db(get_session(session_id)), session_id)
    workspace, ws_degraded = await _resolve_workspace(
        session_id,
        body.working_dir,
        session_row.get("working_dir"),
        soft=stream,
    )

    checkpointer, ck_degraded = await resolve_checkpointer()
    degraded = bool(ws_degraded or ck_degraded)
    graph = _build_graph_or_raise(
        session_id,
        checkpointer,
        model=body.model,
        policy=_policy_for(session_id, body.permission_mode, body.allow_list),
    )
    config = default_run_config(session_id)

    if not await has_pending_interrupt(graph, config):
        raise HTTPException(
            status_code=409, detail="no pending interrupt for this session"
        )
    state = await graph.aget_state(config)
    pending = get_pending_interrupt(state)

    answer = {"allow": "approve", "deny": "deny", "always": "always"}[body.decision]
    tool_name = pending.tool if pending else "batch"
    permission_log = f"permission {body.decision}: {tool_name}"

    if stream:
        degraded |= await _soft_db(log_message(session_id, "system", permission_log))
        events = _stream_in_workspace(stream_resume(graph, answer, config), workspace)
        return StreamingResponse(
            _sse_turn(session_id, events, degraded),
            media_type="text/event-stream",
            headers=_SSE_HEADERS,
        )

    try:
        with workspace_scope(workspace):
            result = await run_resume(graph, answer, config)
    except Exception as exc:
        logger.exception("API resume failed (session_id=%s)", session_id)
        raise HTTPException(status_code=502, detail=f"resume failed: {exc}") from exc

    await _db(log_message(session_id, "system", permission_log))
    if result.status == "ok" and result.reply:
        await _db(log_message(session_id, "assistant", result.reply))

    return _result_dict(session_id, result, degraded)


@router.patch("/{session_id}")
async def patch_session(session_id: str, body: SessionPatch) -> dict:
    """Open or close the session's project directory («open project»).

    ``working_dir`` is validated through ``open_workspace`` (400 on an
    unusable path) and persisted on the session row; ``None`` closes the
    project so the tools fall back to the server cwd. Returns the
    updated row — the UI's folder browser applies the pick with this
    endpoint before any turn runs.
    """
    _require_session(await _db(get_session(session_id)), session_id)
    if body.working_dir is None:
        row = await _db(set_session_working_dir(session_id, None))
        _require_session(row, session_id)
        logger.info("session project closed: %s", session_id)
        return row
    try:
        workspace = open_workspace(body.working_dir)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    row = await _db(set_session_working_dir(session_id, str(workspace)))
    _require_session(row, session_id)
    logger.info("session project opened: %s -> %s", session_id, workspace)
    return row


@router.delete("/{session_id}")
async def delete_session(session_id: str) -> dict:
    """Soft-delete a session (M-20): flip ``status`` to ``closed``."""
    row = await _db(set_session_status(session_id, "closed"))
    _require_session(row, session_id)
    _session_policies.pop(session_id, None)
    logger.info("session soft-deleted: %s", session_id)
    return {"session_id": session_id, "status": "closed"}
