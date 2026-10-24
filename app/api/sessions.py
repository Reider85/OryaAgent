"""Sessions API (M-20): /sessions CRUD + full-turn messages + resume.

REST endpoints for non-UI clients (CI, batch jobs, future Next.js/HTTP
frontends). Chainlit keeps driving the graph directly (M-15 decision;
the SSE migration is the separate M-24 ticket) — this router reuses the
shared runtime in :mod:`app.core.agent` (graph assembly, checkpointer
resolution, ``run_turn``/``run_resume``) so nothing is duplicated.

Endpoints:

* ``POST   /sessions``               — create a session (server-side uuid);
* ``GET    /sessions``               — paginated list (``?page=1&size=20``);
* ``GET    /sessions/{id}``          — metadata + typed messages;
* ``POST   /sessions/{id}/messages`` — run one full turn, JSON response
  (``status`` is ``ok`` or ``interrupted`` at the M-13 permission gate);
* ``POST   /sessions/{id}/resume``   — answer a pending interrupt
  (``decision``: ``allow`` / ``deny`` / ``always``);
* ``DELETE /sessions/{id}``          — soft-delete (``status='closed'``).

Permission policy note: each session caches one :class:`PermissionPolicy`
process-wide so the M-13 session allowlist («Approve & don't ask again»)
survives across ``/messages`` and ``/resume`` calls — the same lifetime
the Chainlit UI gives it via ``cl.user_session``.

Database failures surface as 503 (soft-fail only in the UI layer); an
unreachable Postgres checkpointer degrades to in-memory state with
``"degraded": true`` in the response (mirrors the UI fallback).
"""

from __future__ import annotations

import logging
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query
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
)
from app.core.graph import default_run_config
from app.core.permissions import PermissionPolicy, get_policy
from app.db.session_log import (
    create_session,
    ensure_session,
    get_session,
    list_messages,
    list_sessions,
    log_message,
    set_session_status,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/sessions", tags=["sessions"])

#: Process-wide per-session permission policies (M-13 session allowlist
#: lifetime). Keyed by session_id; recreated on process restart.
_session_policies: dict[str, PermissionPolicy] = {}


class SessionCreate(BaseModel):
    """Request body for ``POST /sessions``."""

    title: str | None = None
    provider: str | None = None
    model: str | None = None
    working_dir: str | None = None
    metadata: dict[str, Any] | None = None


class MessageCreate(BaseModel):
    """Request body for ``POST /sessions/{id}/messages``."""

    content: str = Field(min_length=1)


class ResumeRequest(BaseModel):
    """Request body for ``POST /sessions/{id}/resume``."""

    decision: Literal["allow", "deny", "always"]


def _policy_for(session_id: str) -> PermissionPolicy:
    """Return the cached per-session policy (created on first use)."""
    policy = _session_policies.get(session_id)
    if policy is None:
        policy = get_policy()
        _session_policies[session_id] = policy
    return policy


def _pending_dict(pending: PendingInterrupt | None) -> dict[str, Any] | None:
    """Serialize a :class:`PendingInterrupt` for the JSON response."""
    if pending is None:
        return None
    return {"tool": pending.tool, "args": pending.args, "reason": pending.reason}


def _result_dict(session_id: str, result: TurnResult, degraded: bool) -> dict[str, Any]:
    """Build the shared response shape of /messages and /resume."""
    return {
        "session_id": session_id,
        "status": result.status,
        "reply": result.reply,
        "tool_steps": result.tool_steps,
        "pending_interrupt": _pending_dict(result.pending),
        "degraded": degraded,
    }


async def _db(coro: Any) -> Any:
    """Await a session_log coroutine, mapping DB failures to HTTP 503."""
    try:
        return await coro
    except Exception as exc:
        logger.warning("sessions API database failure: %s", exc)
        raise HTTPException(status_code=503, detail="database unavailable") from exc


def _require_session(session: dict | None, session_id: str) -> dict:
    """Return the session or raise 404."""
    if session is None:
        raise HTTPException(status_code=404, detail=f"Session {session_id!r} not found")
    return session


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
async def post_message(session_id: str, body: MessageCreate) -> dict:
    """Run one full agent turn for a non-UI client (M-20).

    The turn is driven through the shared runtime: the user message is
    logged (M-14), the graph is assembled per session, and the run is
    aggregated into JSON. When the M-13 permission gate pauses the run
    the response is ``status="interrupted"`` with the pending tool call;
    the client answers via ``POST /sessions/{id}/resume``.
    """
    # Lenient auto-create: CI/batch clients may write into a fresh id.
    await _db(ensure_session(session_id))
    await _db(log_message(session_id, "user", body.content))

    checkpointer, degraded = await resolve_checkpointer()
    graph = build_session_graph(
        session_id, checkpointer, policy=_policy_for(session_id)
    )
    config = default_run_config(session_id)

    try:
        result = await run_turn(graph, body.content, config)
    except Exception as exc:
        logger.exception("API run failed (session_id=%s)", session_id)
        raise HTTPException(status_code=502, detail=f"run failed: {exc}") from exc

    if result.status == "ok" and result.reply:
        await _db(log_message(session_id, "assistant", result.reply))

    return _result_dict(session_id, result, degraded)


@router.post("/{session_id}/resume")
async def post_resume(session_id: str, body: ResumeRequest) -> dict:
    """Answer a pending permission interrupt (M-20, BACKLOG5 /resume).

    ``decision`` maps to the M-13/M-16 resume contract: ``allow`` →
    approve the tool call, ``deny`` → refuse it, ``always`` → approve and
    record the tool in the session allowlist. 409 when nothing is pending.
    """
    _require_session(await _db(get_session(session_id)), session_id)

    checkpointer, degraded = await resolve_checkpointer()
    graph = build_session_graph(
        session_id, checkpointer, policy=_policy_for(session_id)
    )
    config = default_run_config(session_id)

    if not await has_pending_interrupt(graph, config):
        raise HTTPException(
            status_code=409, detail="no pending interrupt for this session"
        )
    state = await graph.aget_state(config)
    pending = get_pending_interrupt(state)

    answer = {"allow": "approve", "deny": "deny", "always": "always"}[body.decision]
    try:
        result = await run_resume(graph, answer, config)
    except Exception as exc:
        logger.exception("API resume failed (session_id=%s)", session_id)
        raise HTTPException(status_code=502, detail=f"resume failed: {exc}") from exc

    tool_name = pending.tool if pending else "batch"
    await _db(
        log_message(session_id, "system", f"permission {body.decision}: {tool_name}")
    )
    if result.status == "ok" and result.reply:
        await _db(log_message(session_id, "assistant", result.reply))

    return _result_dict(session_id, result, degraded)


@router.delete("/{session_id}")
async def delete_session(session_id: str) -> dict:
    """Soft-delete a session (M-20): flip ``status`` to ``closed``."""
    row = await _db(set_session_status(session_id, "closed"))
    _require_session(row, session_id)
    _session_policies.pop(session_id, None)
    logger.info("session soft-deleted: %s", session_id)
    return {"session_id": session_id, "status": "closed"}
