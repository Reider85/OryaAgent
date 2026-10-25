"""Best-effort audit trail for L0 memory operations (M-25/M-26).

Every ``MDStore.append`` is recorded as a ``memory_audit_log`` row (the table
already exists — see ``app/db/schema.sql``); the ``/learn`` endpoint (M-26)
additionally records its own ``action="learn"`` row carrying ``memory_id`` /
``source`` / ``trace_id``. When no asyncpg pool is up the
record lands in ``{memory_dir}/audit/memory_audit.jsonl`` instead
(ARCHITECT6 §13.2). Persistence mirrors ``app.core.security``: with a running
event loop the write is scheduled as a background task, without one (plain
sync code, early tests) it goes straight to the JSONL trail.

Nothing in here ever raises — an audit failure must not break a memory write.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import UTC, datetime
from pathlib import Path

from app.core.config import get_settings

logger = logging.getLogger(__name__)

#: Local JSONL trail written when PostgreSQL is unreachable.
MEMORY_AUDIT_FILENAME = "memory_audit.jsonl"

#: Stored excerpt cap for ``memory_audit_log.content_preview``.
AUDIT_PREVIEW_CHARS = 200

#: In-flight persistence tasks (drained by :func:`drain_memory_audits`).
_PENDING: set[asyncio.Task] = set()


def _audit_path(memory_dir: Path | None) -> Path:
    memory_dir = memory_dir or Path(get_settings().memory_dir)
    return memory_dir / "audit" / MEMORY_AUDIT_FILENAME


def _append_jsonl(record: dict, memory_dir: Path | None) -> None:
    """Append one record to the local trail; never raises."""
    path = _audit_path(memory_dir)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError as exc:
        logger.warning("cannot append the memory audit trail: %s", exc)


async def _persist(record: dict, memory_dir: Path | None) -> None:
    """Write the ``memory_audit_log`` row; fall back to the JSONL trail."""
    from app.db import get_pool_if_created  # local: keep import time light

    pool = get_pool_if_created()
    if pool is None:
        logger.debug("no asyncpg pool; the memory op goes to the JSONL trail")
        _append_jsonl(record, memory_dir)
        return
    try:
        await pool.execute(
            "INSERT INTO memory_audit_log "
            "(actor, action, file, content_preview, reason, session_id) "
            "VALUES ($1, $2, $3, $4, $5, $6)",
            record["actor"],
            record["action"],
            record["file"],
            record["preview"],
            record["reason"],
            record["session_id"],
        )
    except Exception as exc:  # noqa: BLE001 - the audit trail must never break a write
        logger.warning(
            "memory_audit_log write failed (%s); falling back to the JSONL trail",
            exc,
        )
        _append_jsonl(record, memory_dir)


def record_memory_op(
    action: str,
    file: str,
    preview: str = "",
    *,
    reason: str | None = None,
    session_id: str | None = None,
    actor: str = "user",
    memory_dir: Path | None = None,
    memory_id: str | None = None,
    source: str | None = None,
    trace_id: str | None = None,
) -> None:
    """Record one L0 operation (``memory.append``, ``learn``, ...).

    Never raises: with a running loop the INSERT is scheduled as a background
    task, otherwise the record goes to the JSONL trail immediately.

    ``memory_id`` / ``source`` / ``trace_id`` (M-26 ``op=learn`` AC,
    ARCHITECT6 §13.2) are carried as their own JSONL fields; the
    ``memory_audit_log`` table has no such columns, so they are folded
    into ``reason`` (``memory_id=... source=... trace_id=...``) — no
    migration, M-25 column set untouched.
    """
    extras = " ".join(
        f"{key}={value}"
        for key, value in (
            ("memory_id", memory_id),
            ("source", source),
            ("trace_id", trace_id),
        )
        if value
    )
    if extras:
        reason = f"{reason}; {extras}" if reason else extras
    record = {
        "ts": datetime.now(UTC).isoformat(timespec="seconds"),
        "actor": actor,
        "action": action,
        "file": file,
        "preview": preview[:AUDIT_PREVIEW_CHARS],
        "reason": reason,
        "session_id": session_id,
        "memory_id": memory_id,
        "source": source,
        "trace_id": trace_id,
    }
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        _append_jsonl(record, memory_dir)
        return
    task = loop.create_task(_persist(record, memory_dir))
    _PENDING.add(task)
    task.add_done_callback(_PENDING.discard)


async def drain_memory_audits() -> None:
    """Await every scheduled audit write (tests / graceful shutdown)."""
    while _PENDING:
        await asyncio.gather(*list(_PENDING), return_exceptions=True)
