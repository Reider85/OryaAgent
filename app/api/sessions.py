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

Cost-aware routing (A-13): while ``ORYA_COST_ROUTER_ENABLED`` is on,
each turn first asks :func:`~app.core.llm.cost_router.resolve_turn_model`
— the budget identity is the JWT user when auth stamped one, else the
session id; at >=70% of the daily budget the graph is built with the
fallback model (a ``budget`` SSE frame / ``budget`` payload field
reports ``degraded``/``warning``), at >=100% the request is refused
with 429. Selection happens before graph assembly, so switching is
between turns only; LLM calls during the turn feed the counter through
the cost-identity contextvar.

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
import uuid
from collections.abc import AsyncIterator
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query, Request
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
from app.core.branch_manager import get_branch_manager
from app.core.cost_tracker import set_cost_identity, with_cost_identity
from app.core.graph import default_run_config
from app.core.llm.cost_router import ModelSelection, resolve_turn_model
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

try:
    # Try to import langgraph 1.x+ error
    from langgraph.errors import GraphRecursionError
except ImportError:
    # Fallback for older langgraph versions
    GraphRecursionError = None

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

    provider: str | None = Field(
        default=None,
        description=(
            "Provider key from providers.yaml; omit for «Auto» (the "
            "config/env default, or the alias' own provider)."
        ),
    )
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


class ForkSessionRequest(BaseModel):
    """Request body for ``POST /sessions/{id}/fork``."""

    turn_id: str | None = Field(
        default=None,
        description="Specific turn to fork from (defaults to latest)"
    )
    branch_name: str | None = Field(
        default=None,
        description="Name for the new branch (auto-generated if None)"
    )


class BranchInfoResponse(BaseModel):
    """Response for branch information."""

    id: str
    name: str
    parent_session_id: str
    parent_turn_id: str
    created_at: str
    status: str
    metadata: dict[str, Any]


class BranchListResponse(BaseModel):
    """Response for listing branches."""

    branches: list[BranchInfoResponse]
    total: int


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


async def _stream_with_cost_identity(
    events: AsyncIterator[Any], identity: str
) -> AsyncIterator[Any]:
    """Bind the A-13 cost identity for the whole stream.

    Same reason and reset contract as :func:`_stream_in_workspace`: the
    SSE body is iterated *after* the endpoint returned, so the contextvar
    must be bound inside the stream. LLM calls during the turn then bill
    the identity's daily budget counter.
    """
    set_cost_identity(identity)
    try:
        async for event in events:
            yield event
    finally:
        set_cost_identity(None)


def _pending_dict(pending: PendingInterrupt | None) -> dict[str, Any] | None:
    """Serialize a :class:`PendingInterrupt` for the JSON/SSE payload."""
    if pending is None:
        return None
    return {"tool": pending.tool, "args": pending.args, "reason": pending.reason}


def _budget_payload(selection: ModelSelection | None) -> dict[str, Any] | None:
    """Serializable budget report — only when the degrade is active (A-13)."""
    if selection is None or not (selection.degraded or selection.warning):
        return None
    return selection.as_dict()


def _result_dict(
    session_id: str,
    result: TurnResult,
    degraded: bool,
    budget: ModelSelection | None = None,
) -> dict[str, Any]:
    """Build the shared response shape of the JSON /messages and /resume."""
    payload: dict[str, Any] = {
        "session_id": session_id,
        "status": result.status,
        "reply": result.reply,
        "tool_steps": result.tool_steps,
        "pending_interrupt": _pending_dict(result.pending),
        "degraded": degraded,
    }
    budget_report = _budget_payload(budget)
    if budget_report is not None:
        payload["budget"] = budget_report
    return payload


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
    budget: ModelSelection | None = None,
) -> AsyncIterator[str]:
    """Forward a turn stream as SSE frames and log the assistant reply.

    Events flow through unchanged; the terminal ``done`` carries the
    aggregated outcome (plus ``degraded``), and a pause additionally
    emits the ``interrupt`` frame the UI asks the user about (M-16).
    When the A-13 budget degraded the model, a ``budget`` frame goes
    out first and the ``done`` payload carries the same report.
    Failures after the response started surface as ``error`` + a final
    ``done`` with ``status="error"`` so the client always sees an end.
    """
    reply = ""
    status = "ok"
    finished = False
    budget_report = _budget_payload(budget)
    if budget_report is not None:
        yield _sse("budget", budget_report)

    def _done_payload(data: dict[str, Any], status_: str) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "session_id": session_id,
            "status": status_,
            "reply": reply,
            "tool_steps": data.get("tool_steps") or [],
            "pending_interrupt": _pending_dict(data.get("pending")),
            "degraded": degraded,
        }
        if budget_report is not None:
            payload["budget"] = budget_report
        return payload

    try:
        async for kind, data in events:
            if kind != "done":
                yield _sse(kind, data)
                continue
            finished = True
            status = str(data.get("status", "ok"))
            reply = str(data.get("reply") or "")
            if status == "interrupted":
                pending = _pending_dict(data.get("pending"))
                if pending is not None:
                    yield _sse("interrupt", pending)
            yield _sse("done", _done_payload(data, status))
    except Exception as exc:
        logger.exception("SSE run failed (session_id=%s)", session_id)

        # Friendly message for recursion limit errors
        if GraphRecursionError and isinstance(exc, GraphRecursionError):
            detail = (
                "The agent reached its step limit and stopped. "
                "Try increasing the recursion limit with ORYA_RECURSION_LIMIT=100, "
                "or break the task into smaller parts."
            )
        else:
            detail = str(exc)

        yield _sse("error", {"detail": detail})
        yield _sse("done", _done_payload({}, "error"))
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


def _cost_identity(request: Request, session_id: str) -> str:
    """Budget identity for the turn (A-13): JWT user or the session.

    AuthMiddleware (A-00) stamps ``user_id`` into the ASGI scope state;
    with auth off (the default) every session budgets independently,
    matching PROMPT_ALPHA's «budget tracking per session».
    """
    user_id = getattr(request.state, "user_id", None)
    if user_id:
        return f"user:{user_id}"
    return f"session:{session_id}"


async def _resolve_turn_model_or_raise(
    identity: str,
    requested_model: str | None,
    requested_provider: str | None,
) -> ModelSelection:
    """A-13 budget check for one turn; 429 when the daily budget is spent.

    The selection's ``model`` alias is what the graph is built with —
    switching therefore happens only between turns. With the
    ``ORYA_COST_ROUTER_ENABLED`` kill-switch off this is a pass-through
    (``model`` echoes the request, no counter reads).
    """
    selection = await resolve_turn_model(identity, requested_model, requested_provider)
    if selection.blocked:
        raise HTTPException(
            status_code=429,
            detail=(
                f"daily budget exhausted ({selection.ratio:.0%} of limit spent); "
                "retry after the counter resets or raise the limit"
            ),
        )
    return selection


def _build_graph_or_raise(
    session_id: str,
    checkpointer: Any,
    *,
    model: Any = None,
    provider: str | None = None,
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
            provider=provider,
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
    request: Request,
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

    A-13: while the cost router is enabled the budget check runs first
    (429 when spent), the graph is built with the selected alias, and a
    ``budget`` frame / payload field reports an active degrade.
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
    identity = _cost_identity(request, session_id)
    selection = await _resolve_turn_model_or_raise(identity, body.model, body.provider)
    graph = _build_graph_or_raise(
        session_id,
        checkpointer,
        model=selection.model,
        provider=body.provider,
        policy=_policy_for(session_id, body.permission_mode, body.allow_list),
    )
    config = default_run_config(session_id)

    if stream:
        events = _stream_with_cost_identity(
            _stream_in_workspace(stream_turn(graph, body.content, config), workspace),
            identity,
        )
        return StreamingResponse(
            _sse_turn(session_id, events, degraded, budget=selection),
            media_type="text/event-stream",
            headers=_SSE_HEADERS,
        )

    try:
        with workspace_scope(workspace), with_cost_identity(identity):
            result = await run_turn(graph, body.content, config)
    except Exception as exc:
        logger.exception("API run failed (session_id=%s)", session_id)
        raise HTTPException(status_code=502, detail=f"run failed: {exc}") from exc

    if result.status == "ok" and result.reply:
        await _db(log_message(session_id, "assistant", result.reply))

    return _result_dict(session_id, result, degraded, budget=selection)


@router.post("/{session_id}/resume")
async def post_resume(
    request: Request,
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
    identity = _cost_identity(request, session_id)
    selection = await _resolve_turn_model_or_raise(identity, body.model, body.provider)
    graph = _build_graph_or_raise(
        session_id,
        checkpointer,
        model=selection.model,
        provider=body.provider,
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
        events = _stream_with_cost_identity(
            _stream_in_workspace(stream_resume(graph, answer, config), workspace),
            identity,
        )
        return StreamingResponse(
            _sse_turn(session_id, events, degraded, budget=selection),
            media_type="text/event-stream",
            headers=_SSE_HEADERS,
        )

    try:
        with workspace_scope(workspace), with_cost_identity(identity):
            result = await run_resume(graph, answer, config)
    except Exception as exc:
        logger.exception("API resume failed (session_id=%s)", session_id)
        raise HTTPException(status_code=502, detail=f"resume failed: {exc}") from exc

    await _db(log_message(session_id, "system", permission_log))
    if result.status == "ok" and result.reply:
        await _db(log_message(session_id, "assistant", result.reply))

    return _result_dict(session_id, result, degraded, budget=selection)


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


@router.post("/{session_id}/fork")
async def fork_session(
    session_id: str,
    body: ForkSessionRequest | None = None,
) -> dict:
    """Create a new branch from any session turn (B-09).
    
    Creates a new session that inherits state from the parent session
    up to the specified turn. Returns the new branch session ID.
    """
    body = body or ForkSessionRequest()
    branch_manager = get_branch_manager()
    
    try:
        branch_session_id = await branch_manager.fork_session(
            session_id=session_id,
            turn_id=body.turn_id,
            branch_name=body.branch_name,
        )
        
        logger.info("session forked: %s -> %s", session_id, branch_session_id)
        return {
            "session_id": session_id,
            "branch_session_id": branch_session_id,
            "turn_id": body.turn_id,
            "branch_name": body.branch_name,
        }
    except Exception as exc:
        logger.exception("session fork failed (session_id=%s)", session_id)
        raise HTTPException(status_code=400, detail=f"fork failed: {exc}") from exc


@router.get("/{session_id}/branches")
async def list_branches(session_id: str) -> BranchListResponse:
    """List all branches for a session (B-09)."""
    branch_manager = get_branch_manager()
    branches = await branch_manager.list_branches(session_id)
    
    branch_responses = []
    for branch in branches:
        branch_responses.append(BranchInfoResponse(
            id=branch["id"],
            name=branch["name"],
            parent_session_id=branch["parent_session_id"],
            parent_turn_id=branch["parent_turn_id"],
            created_at=branch["created_at"].isoformat(),
            status=branch["status"],
            metadata=branch["metadata"],
        ))
    
    return BranchListResponse(
        branches=branch_responses,
        total=len(branch_responses)
    )


@router.get("/{session_id}/branches/{branch_id}")
async def get_branch_info(session_id: str, branch_id: str) -> BranchInfoResponse:
    """Get information about a specific branch (B-09)."""
    branch_manager = get_branch_manager()
    branch_info = await branch_manager.get_branch_info(branch_id)
    
    if branch_info is None:
        raise HTTPException(status_code=404, detail=f"Branch {branch_id} not found")
    
    return BranchInfoResponse(
        id=branch_info["id"],
        name=branch_info["name"],
        parent_session_id=branch_info["parent_session_id"],
        parent_turn_id=branch_info["parent_turn_id"],
        created_at=branch_info["created_at"].isoformat(),
        status=branch_info["status"],
        metadata=branch_info["metadata"],
    )


@router.delete("/{session_id}/branches/{branch_id}")
async def delete_branch(session_id: str, branch_id: str) -> dict:
    """Delete a branch session (B-09)."""
    branch_manager = get_branch_manager()
    success = await branch_manager.delete_branch(branch_id)
    
    if not success:
        raise HTTPException(status_code=404, detail=f"Branch {branch_id} not found")
    
    logger.info("branch deleted: %s", branch_id)
    return {"branch_id": branch_id, "status": "deleted"}


class MergeBranchRequest(BaseModel):
    """Request for merging a branch into the current session."""
    source_session_id: str = Field(..., description="ID of the branch session to merge")
    merge_strategy: str = Field("append", description="Merge strategy: 'append', 'interleave', 'replace'")
    conflict_resolution: str = Field("manual", description="Conflict resolution: 'manual', 'auto', 'source'")


class MergeBranchResponse(BaseModel):
    """Response for branch merge operation."""
    success: bool
    source_session: str
    target_session: str
    merge_strategy: str
    merged_turns: int
    merge_results: List[Dict[str, Any]]
    conflicts_resolved: int
    merge_id: str


@router.post("/{session_id}/merge", response_model=MergeBranchResponse)
async def merge_branch(session_id: str, body: MergeBranchRequest) -> MergeBranchResponse:
    """Merge a branch into the current session (B-10).
    
    Merges tool-call sequences from a branch session into the current session.
    Supports multiple merge strategies and conflict resolution options.
    """
    from app.core.observability.spans import emit_span
    
    @emit_span(name="branch.merge", attributes={
        "branch.source_session": body.source_session_id,
        "branch.target_session": session_id,
        "branch.merge_strategy": body.merge_strategy,
        "branch.conflict_resolution": body.conflict_resolution
    })
    async def _merge_branch():
        branch_manager = get_branch_manager()
        
        # Validate merge strategy
        valid_strategies = ["append", "interleave", "replace"]
        if body.merge_strategy not in valid_strategies:
            raise HTTPException(
                status_code=400, 
                detail=f"Invalid merge strategy. Must be one of: {valid_strategies}"
            )
        
        # Validate conflict resolution
        valid_resolutions = ["manual", "auto", "source"]
        if body.conflict_resolution not in valid_resolutions:
            raise HTTPException(
                status_code=400, 
                detail=f"Invalid conflict resolution. Must be one of: {valid_resolutions}"
            )
        
        # Perform the merge
        merge_result = await branch_manager.merge_branches(
            source_session_id=body.source_session_id,
            target_session_id=session_id,
            merge_strategy=body.merge_strategy,
            conflict_resolution=body.conflict_resolution,
        )
        
        # Generate merge ID for tracking
        merge_id = f"merge-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}"
        
        # Update merge result with tracking ID
        merge_result["merge_id"] = merge_id
        
        logger.info(
            "Branch merged: %s -> %s using strategy '%s' (merge_id: %s)",
            body.source_session_id, session_id, body.merge_strategy, merge_id
        )
        
        return merge_result
    
    try:
        merge_result = await _merge_branch()
        return MergeBranchResponse(
            success=merge_result["success"],
            source_session=merge_result["source_session"],
            target_session=merge_result["target_session"],
            merge_strategy=merge_result["merge_strategy"],
            merged_turns=merge_result["merged_turns"],
            merge_results=merge_result["merge_results"],
            conflicts_resolved=merge_result["conflicts_resolved"],
            merge_id=merge_result["merge_id"]
        )
    except Exception as e:
        logger.error(f"Failed to merge branch: {e}")
        raise HTTPException(status_code=400, detail=f"Failed to merge branch: {str(e)}")
