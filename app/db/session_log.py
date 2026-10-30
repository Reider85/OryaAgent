"""Session log (M-14): typed ``messages`` rows + JSONL checkpoint projection.

Two complementary stores for the session event stream:

* ``messages`` table (asyncpg) — query-friendly typed log written by
  :func:`log_message`. The UI/API layers (M-15/M-20) call it directly;
  the table itself was created in M-03.
* JSONL projection — an append-only
  ``{settings.sessions_dir}/{session_id}.jsonl`` file derived from the
  LangGraph ``AsyncPostgresSaver`` checkpoints (``app/db/checkpoints.py``,
  M-03). One line per event: ``{"ts": ..., "type": ..., "payload": {...}}``
  with ``type`` in ``user`` / ``ai`` / ``tool`` / ``system``. Used for
  replay/debug/audit (ARCHITECT4 §6.5).

Encryption at rest (A-05): when ``ORYA_SESSION_LOG_ENCRYPTION_ENABLED=true``
and a ``ORYA_SESSION_LOG_ENCRYPTION_KEY`` is configured, the payload columns
``messages.content`` (TEXT) and ``messages.tool_calls`` (JSONB) are stored
encrypted via PostgreSQL ``pgcrypto`` (``pgp_sym_encrypt``, armored). Reads
transparently decrypt; the armor-prefix ``CASE`` guard means pre-existing
plaintext rows remain readable (tolerant decrypt). The kill-switch is off by
default so dev/tests keep working unchanged.

Projection idempotency: every projection run reads
``{session_id}.meta.json`` (``last_processed_ts``), processes only
checkpoints with a newer ``ts``, and emits only messages that appeared
since the previously processed snapshot (checkpoint snapshots contain the
*full* message history, so emission is delta-based). Re-running the worker
therefore appends nothing.

A background worker (:func:`projection_worker`, started from the FastAPI
lifespan in ``app/main.py``) periodically discovers threads from the
``checkpoints`` table and projects them. All failures are logged and never
crash the process — the app must stay up without PostgreSQL.

Usage::

    await log_message(session_id, "user", "hello")
    appended = await project_thread(session_id)
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from pathlib import Path
from typing import Any

import asyncpg
from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)

from app.core.config import get_settings
from app.db import get_asyncpg_pool
from app.db.checkpoints import get_checkpointer

logger = logging.getLogger(__name__)

#: Allowed ``messages.role`` values (mirrors the CHECK constraint in schema.sql).
ROLES = frozenset({"system", "user", "assistant", "tool"})

#: Allowed ``sessions.status`` values (mirrors the CHECK constraint in schema.sql).
SESSION_STATUSES = frozenset({"active", "closed", "aborted"})

#: Seconds between projection passes in :func:`projection_worker`.
PROJECTION_INTERVAL_S = 30.0

#: Leading marker of pgcrypto ASCII-armored output (A-05 tolerant decrypt).
_ARMOR_PREFIX = "-----BEGIN PGP MESSAGE-----"


def _encryption_enabled() -> bool:
    """True when session-log encryption at rest is switched on (A-05)."""
    return get_settings().session_log_encryption_enabled


def _encryption_key() -> str:
    """Return the raw pgp passphrase (A-05).

    Settings validation already fails fast when encryption is enabled
    without a key; this is a defensive re-check so the seam never emits a
    ``pgp_sym_encrypt`` call with an empty passphrase.
    """
    secret = get_settings().session_log_encryption_key
    if secret is None or not secret.get_secret_value():
        raise RuntimeError(
            "session-log encryption enabled but SESSION_LOG_ENCRYPTION_KEY is empty"
        )
    return secret.get_secret_value()


def _decrypt_content_sql(column: str, key_param: str) -> str:
    """SQL fragment decrypting a TEXT content column in place (A-05).

    Only values carrying the pgcrypto armor prefix are decrypted; plaintext
    rows (written before encryption was enabled, or while the kill-switch
    was off) pass through unchanged.
    """
    return (
        f"CASE WHEN {column} LIKE '{_ARMOR_PREFIX}%' "
        f"THEN convert_from(pgp_sym_decrypt({column}::bytea, ${key_param}), 'UTF8') "
        f"ELSE {column} END"
    )


def _decrypt_tool_calls_sql(column: str, key_param: str) -> str:
    """SQL fragment decrypting a JSONB ``tool_calls`` column back to jsonb (A-05).

    The encrypted form stores the armored ciphertext as a JSON string
    (``to_jsonb(armor(...))``); the ``#>> '{}'`` extraction unwraps it to
    text before ``pgp_sym_decrypt``, and the result is cast back to ``jsonb``
    so asyncpg returns a decoded Python object (identical shape to the
    plaintext path).
    """
    return (
        f"CASE WHEN {column} IS NULL THEN NULL "
        f"WHEN {column} #>> '{{}}' LIKE '{_ARMOR_PREFIX}%' "
        f"THEN convert_from(pgp_sym_decrypt(({column} #>> '{{}}')::bytea, "
        f"${key_param}), 'UTF8')::jsonb "
        f"ELSE {column} END"
    )


def session_jsonl_path(session_id: str) -> Path:
    """Path of the JSONL projection file for a session/thread."""
    return get_settings().sessions_dir / f"{session_id}.jsonl"


def _meta_path(session_id: str) -> Path:
    """Path of the projection dedup marker (``last_processed_ts``)."""
    return get_settings().sessions_dir / f"{session_id}.meta.json"


async def ensure_session(
    session_id: str,
    *,
    title: str | None = None,
    provider: str | None = None,
    model: str | None = None,
    working_dir: str | None = None,
    pool: asyncpg.Pool | None = None,
) -> None:
    """Insert the parent ``sessions`` row if it does not exist yet.

    Required before writing ``messages`` rows (foreign key). Existing rows
    are left untouched (``ON CONFLICT DO NOTHING``).
    """
    if pool is None:
        pool = await get_asyncpg_pool()
    await pool.execute(
        "INSERT INTO sessions (session_id, title, provider, model, working_dir) "
        "VALUES ($1, $2, $3, $4, $5) "
        "ON CONFLICT (session_id) DO NOTHING",
        session_id,
        title,
        provider,
        model,
        working_dir,
    )


def _session_row(row: asyncpg.Record | None) -> dict | None:
    """Convert a ``sessions`` row to a plain JSON-safe dict."""
    if row is None:
        return None
    data = dict(row)
    for key in ("created_at", "last_activity_at"):
        value = data.get(key)
        if value is not None:
            data[key] = value.isoformat()
    return data


async def create_session(
    *,
    session_id: str | None = None,
    title: str | None = None,
    provider: str | None = None,
    model: str | None = None,
    working_dir: str | None = None,
    metadata: dict | None = None,
    pool: asyncpg.Pool | None = None,
) -> dict:
    """Insert a new ``sessions`` row (M-20) and return it.

    ``session_id`` is generated (uuid4) when not provided. The row is
    inserted with ``status='active'``; ``metadata`` is stored as JSONB.
    """
    if pool is None:
        pool = await get_asyncpg_pool()
    sid = session_id or str(uuid.uuid4())
    payload = json.dumps(metadata) if metadata is not None else None
    row = await pool.fetchrow(
        "INSERT INTO sessions (session_id, title, provider, model, working_dir, metadata) "
        "VALUES ($1, $2, $3, $4, $5, COALESCE($6::jsonb, '{}'::jsonb)) "
        "RETURNING *",
        sid,
        title,
        provider,
        model,
        working_dir,
        payload,
    )
    result = _session_row(row)
    if result is None:  # pragma: no cover - INSERT..RETURNING always returns a row
        raise RuntimeError(f"failed to create session {sid!r}")
    return result


async def get_session(
    session_id: str,
    *,
    pool: asyncpg.Pool | None = None,
) -> dict | None:
    """Return one ``sessions`` row as a dict, or ``None`` when unknown."""
    if pool is None:
        pool = await get_asyncpg_pool()
    row = await pool.fetchrow(
        "SELECT * FROM sessions WHERE session_id = $1",
        session_id,
    )
    return _session_row(row)


async def list_sessions(
    *,
    limit: int = 20,
    offset: int = 0,
    pool: asyncpg.Pool | None = None,
) -> tuple[list[dict], int]:
    """List ``sessions`` rows (newest activity first) with a total count.

    Returns ``(rows, total)`` — the total is the unpaginated row count so
    clients can compute page counts.
    """
    if pool is None:
        pool = await get_asyncpg_pool()
    rows = await pool.fetch(
        "SELECT * FROM sessions "
        "ORDER BY last_activity_at DESC, created_at DESC "
        "LIMIT $1 OFFSET $2",
        limit,
        offset,
    )
    total = await pool.fetchval("SELECT COUNT(*) FROM sessions")
    return [_session_row(row) for row in rows], int(total or 0)


async def set_session_status(
    session_id: str,
    status: str,
    *,
    pool: asyncpg.Pool | None = None,
) -> dict | None:
    """Update ``sessions.status`` (soft-delete: ``active`` → ``closed``).

    Returns the updated row, or ``None`` when the session does not exist.
    Raises ``ValueError`` for a status outside the schema CHECK constraint.
    """
    if status not in SESSION_STATUSES:
        raise ValueError(
            f"invalid status {status!r}; expected one of {sorted(SESSION_STATUSES)}"
        )
    if pool is None:
        pool = await get_asyncpg_pool()
    row = await pool.fetchrow(
        "UPDATE sessions SET status = $2, last_activity_at = now() "
        "WHERE session_id = $1 "
        "RETURNING *",
        session_id,
        status,
    )
    return _session_row(row)


async def set_session_working_dir(
    session_id: str,
    working_dir: str | None,
    *,
    pool: asyncpg.Pool | None = None,
) -> dict | None:
    """Update ``sessions.working_dir`` (the project the session has open).

    Returns the updated row, or ``None`` when the session does not exist.
    """
    if pool is None:
        pool = await get_asyncpg_pool()
    row = await pool.fetchrow(
        "UPDATE sessions SET working_dir = $2, last_activity_at = now() "
        "WHERE session_id = $1 "
        "RETURNING *",
        session_id,
        working_dir,
    )
    return _session_row(row)


async def list_messages(
    session_id: str,
    *,
    limit: int = 1000,
    offset: int = 0,
    pool: asyncpg.Pool | None = None,
) -> list[dict]:
    """Return typed ``messages`` rows for a session in ``seq`` order.

    When session-log encryption is enabled (A-05), ``content`` and
    ``tool_calls`` are decrypted in-place by the query; plaintext rows are
    returned unchanged (tolerant decrypt).
    """
    if pool is None:
        pool = await get_asyncpg_pool()
    if _encryption_enabled():
        key = _encryption_key()
        query = (
            "SELECT id, seq, role, "
            f"{_decrypt_content_sql('content', '4')}, "
            f"{_decrypt_tool_calls_sql('tool_calls', '4')}, "
            "tool_call_id, created_at "
            "FROM messages WHERE session_id = $1 "
            "ORDER BY seq "
            "LIMIT $2 OFFSET $3"
        )
        rows = await pool.fetch(query, session_id, limit, offset, key)
    else:
        rows = await pool.fetch(
            "SELECT id, seq, role, content, tool_calls, tool_call_id, created_at "
            "FROM messages WHERE session_id = $1 "
            "ORDER BY seq "
            "LIMIT $2 OFFSET $3",
            session_id,
            limit,
            offset,
        )
    messages: list[dict] = []
    for row in rows:
        item = dict(row)
        created = item.get("created_at")
        if created is not None:
            item["created_at"] = created.isoformat()
        messages.append(item)
    return messages


async def log_message(
    session_id: str,
    role: str,
    content: str,
    tool_calls: list[dict] | None = None,
    tool_call_id: str | None = None,
    *,
    pool: asyncpg.Pool | None = None,
) -> int:
    """Append one typed message to the ``messages`` table (M-14).

    ``seq`` is assigned automatically as ``MAX(seq) + 1`` within the
    session. ``tool_calls`` is stored as JSONB (assistant tool-call
    requests); ``tool_call_id`` links tool results back to their request.

    When session-log encryption is enabled (A-05), ``content`` (TEXT) is
    stored as pgcrypto armored ciphertext and ``tool_calls`` (JSONB) as
    ``to_jsonb(armor(...))``; both are decrypted transparently on read.

    Returns the inserted row id.
    """
    if role not in ROLES:
        raise ValueError(f"invalid role {role!r}; expected one of {sorted(ROLES)}")
    if pool is None:
        pool = await get_asyncpg_pool()
    await ensure_session(session_id, pool=pool)
    payload = json.dumps(tool_calls) if tool_calls is not None else None
    if _encryption_enabled():
        key = _encryption_key()
        row = await pool.fetchrow(
            "INSERT INTO messages (session_id, seq, role, content, tool_calls, tool_call_id) "
            "SELECT $1, COALESCE(MAX(seq), 0) + 1, $2, "
            "armor(pgp_sym_encrypt(convert_to($3, 'UTF8'), $6)), "
            "CASE WHEN $4::text IS NULL THEN NULL "
            "ELSE to_jsonb(armor(pgp_sym_encrypt(convert_to($4, 'UTF8'), $6))) END, "
            "$5 "
            "FROM messages WHERE session_id = $1 "
            "RETURNING id",
            session_id,
            role,
            content,
            payload,
            tool_call_id,
            key,
        )
    else:
        row = await pool.fetchrow(
            "INSERT INTO messages (session_id, seq, role, content, tool_calls, tool_call_id) "
            "SELECT $1, COALESCE(MAX(seq), 0) + 1, $2, $3, $4, $5 "
            "FROM messages WHERE session_id = $1 "
            "RETURNING id",
            session_id,
            role,
            content,
            payload,
            tool_call_id,
        )
    if row is None:  # pragma: no cover - INSERT..SELECT always returns a row
        raise RuntimeError(f"failed to insert message for session {session_id!r}")
    return int(row["id"])


async def discover_thread_ids(*, pool: asyncpg.Pool | None = None) -> list[str]:
    """Return every thread id that has at least one checkpoint.

    Reads LangGraph's own ``checkpoints`` table (created by
    ``AsyncPostgresSaver.setup()``). An empty list is returned when the
    table does not exist yet (checkpointer never set up).
    """
    if pool is None:
        pool = await get_asyncpg_pool()
    try:
        rows = await pool.fetch("SELECT DISTINCT thread_id FROM checkpoints")
    except asyncpg.UndefinedTableError:
        return []
    return [str(row["thread_id"]) for row in rows]


def _jsonable(value: Any) -> Any:
    """Best-effort JSON-safe conversion for message content blocks."""
    if isinstance(value, str):
        return value
    try:
        json.dumps(value)
    except (TypeError, ValueError):
        return str(value)
    return value


def _message_id(message: BaseMessage, position: int) -> str:
    """Stable id for delta tracking (LangGraph assigns uuid ids in state)."""
    return str(message.id) if message.id else f"msg-{position}"


def _message_type(message: BaseMessage) -> str:
    """Map a LangChain message class to the JSONL event ``type``."""
    if isinstance(message, ToolMessage):
        return "tool"
    if isinstance(message, AIMessage):
        return "ai"
    if isinstance(message, HumanMessage):
        return "user"
    if isinstance(message, SystemMessage):
        return "system"
    return type(message).__name__.removesuffix("Message").lower()


def _message_event(message: BaseMessage, message_id: str, ts: str) -> dict:
    """Build one JSONL event ``{"ts", "type", "payload"}`` (BACKLOG4 format)."""
    payload: dict[str, Any] = {
        "message_id": message_id,
        "content": _jsonable(message.content),
    }
    tool_calls = getattr(message, "tool_calls", None)
    if tool_calls:
        payload["tool_calls"] = list(tool_calls)
    tool_call_id = getattr(message, "tool_call_id", None)
    if tool_call_id:
        payload["tool_call_id"] = tool_call_id
    status = getattr(message, "status", None)
    if status:
        # M-26: ``/learn`` needs the tool outcome (success/error) — the
        # projection is where the endpoint reads the session log from.
        payload["status"] = status
    name = getattr(message, "name", None)
    if name:
        payload["name"] = name
    return {"ts": ts, "type": _message_type(message), "payload": payload}


def _load_meta(session_id: str) -> dict:
    path = _meta_path(session_id)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        logger.warning(
            "corrupt projection meta for %s; restarting from scratch", session_id
        )
        return {}
    return data if isinstance(data, dict) else {}


def _save_meta(session_id: str, last_processed_ts: str) -> None:
    path = _meta_path(session_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"last_processed_ts": last_processed_ts}, ensure_ascii=False),
        encoding="utf-8",
    )


def _snapshot_messages(checkpoint: dict) -> list[BaseMessage]:
    values = checkpoint.get("channel_values") or {}
    return list(values.get("messages") or [])


async def project_thread(
    session_id: str,
    *,
    checkpointer: Any = None,
) -> int:
    """Project one thread's checkpoints into its JSONL file.

    Processes checkpoints whose ``ts`` is newer than the ``last_processed_ts``
    recorded in the meta file, and emits only messages that are new relative
    to the previous snapshot (checkpoint snapshots hold the full history).

    Returns the number of appended events (0 when nothing is new).
    """
    if checkpointer is None:
        checkpointer = await get_checkpointer()
    config = {"configurable": {"thread_id": session_id}}
    tuples = [t async for t in checkpointer.alist(config)]
    snapshots = sorted(tuples, key=lambda t: t.checkpoint["ts"])
    if not snapshots:
        return 0

    meta = _load_meta(session_id)
    last_ts = meta.get("last_processed_ts")
    if last_ts:
        timestamps = [t.checkpoint["ts"] for t in snapshots]
        if last_ts in timestamps:
            baseline = {
                _message_id(m, i)
                for i, m in enumerate(
                    _snapshot_messages(snapshots[timestamps.index(last_ts)].checkpoint)
                )
            }
        else:
            logger.warning(
                "projection meta ts %s missing for %s (pruned checkpoints?); "
                "re-emitting visible history",
                last_ts,
                session_id,
            )
            baseline = set()
        new_snapshots = [t for t in snapshots if t.checkpoint["ts"] > last_ts]
    else:
        baseline = set()
        new_snapshots = snapshots
    if not new_snapshots:
        return 0

    events: list[dict] = []
    seen = set(baseline)
    for item in new_snapshots:
        ts = item.checkpoint["ts"]
        for position, message in enumerate(_snapshot_messages(item.checkpoint)):
            message_id = _message_id(message, position)
            if message_id in seen:
                continue
            seen.add(message_id)
            events.append(_message_event(message, message_id, ts))

    if events:
        path = session_jsonl_path(session_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            for event in events:
                fh.write(json.dumps(event, ensure_ascii=False, default=str) + "\n")
    _save_meta(session_id, new_snapshots[-1].checkpoint["ts"])
    logger.debug(
        "projected %s: %d events from %d checkpoints",
        session_id,
        len(events),
        len(new_snapshots),
    )
    return len(events)


async def projection_pass() -> int:
    """Discover all threads and project each once. Returns total events."""
    thread_ids = await discover_thread_ids()
    total = 0
    for thread_id in thread_ids:
        total += await project_thread(thread_id)
    return total


async def projection_worker(
    *,
    stop: asyncio.Event | None = None,
    interval_s: float = PROJECTION_INTERVAL_S,
) -> None:
    """Background worker: project every known thread, then poll.

    Started from the FastAPI lifespan. Never raises: database failures are
    logged and retried on the next pass. When ``stop`` is set the worker
    returns after the current pass (used by tests; shutdown in ``main.py``
    cancels the task instead).
    """
    get_settings().sessions_dir.mkdir(parents=True, exist_ok=True)
    while True:
        try:
            await projection_pass()
        except Exception as exc:  # noqa: BLE001 - worker must never crash the app
            logger.warning("session-log projection pass failed: %s", exc)
        if stop is not None:
            try:
                await asyncio.wait_for(stop.wait(), timeout=interval_s)
            except TimeoutError:
                continue
            return
        await asyncio.sleep(interval_s)
