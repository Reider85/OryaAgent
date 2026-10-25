"""Learn API (M-26): capture a learned entry into the L0 memory files.

Two endpoints over one write helper (PROMPT_MVP §3.7 M-26 + BACKLOG6 M-26):

* ``POST /sessions/{session_id}/learn`` (ARCHITECT6 §4.3.1) — extracts the
  *last successful tool-call sequence* from the session log (the M-14 JSONL
  projection), renders it as a ``[learned]`` entry in the ARCHITECT6 §3.1.1
  format and atomic-appends it to ``LEARNED.md``. Body:
  ``{"pattern_name": ..., "description": ..., "scope": ...}`` — an omitted
  ``pattern_name`` is auto-named ``tool1_tool2_...`` (e.g. ``grep_read_edit``).
* ``POST /learn`` (PROMPT_MVP) — appends caller-supplied content:
  ``{"content": ..., "category": "fact|preference|project"}`` maps to
  ``FACTS.md`` / ``PREFERENCES.md`` / ``LEARNED.md``.

Both return ``{"status", "learned_id", "file", "compacted", "line_count"}`` —
the union of the two spec response shapes.

Sequence extraction (BACKLOG6 «successful» definition): walking the
projection backwards, ``ai``/``system`` events are skipped, ``tool`` events
are collected until the first ``user`` event (turn boundary) or the first
*unsuccessful* tool call. A tool call is unsuccessful when its
``ToolMessage.status`` is ``error``, when its result is a permission
refusal (``Denied...``), or when a ``bash`` result carries
``exit_code != 0``. An empty result is a 400
«No successful tool-call sequence to learn».

Notes (deliberate deviations, see the M-26 plan):

* the session log is read from the JSONL projection, not PostgreSQL — the
  endpoint therefore works in degraded mode and is unit-testable without
  infra; a best-effort ``project_thread()`` refresh runs first;
* ``scope`` is accepted (422 outside ``session|project|global``) but only
  the project store (``settings.memory_dir``) exists in the MVP —
  ``session``/``global`` are TODOs for B-21/E-11;
* compaction is never awaited: ``MDStore.append`` already schedules
  ``compact_if_needed`` asynchronously (M-25), the response only reports
  whether the file is over budget;
* each call also writes an ``action="learn"`` audit record carrying
  ``memory_id`` / ``source`` / ``trace_id`` (M-26 AC) on top of the
  ``memory.append`` row the store records itself.
"""

from __future__ import annotations

import json
import logging
import re
import threading
import uuid
from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.core.memory.audit import record_memory_op
from app.core.memory.md_store import get_md_store
from app.core.memory.models import MemoryItem, kind_for, next_id
from app.db.session_log import project_thread, session_jsonl_path

logger = logging.getLogger(__name__)

router = APIRouter(tags=["learn"])

#: Serializes ``next_id`` + ``append`` so two concurrent ``/learn`` calls
#: never mint the same ``learn_001`` id (the per-file MDStore lock alone
#: would only protect the writes against each other).
_learn_lock = threading.Lock()

#: Confidence per entry kind (ARCHITECT6 §3.1.1 examples).
_CONFIDENCE: dict[str, float] = {
    "fact": 1.0,
    "preference": 0.95,
    "learned": 0.90,
}

#: ``category`` (PROMPT_MVP) -> L0 file (ARCHITECT6 §3.1.1 file table).
_CATEGORY_FILES: dict[str, str] = {
    "fact": "FACTS.md",
    "preference": "PREFERENCES.md",
    "project": "LEARNED.md",
}


class LearnRequest(BaseModel):
    """Request body for ``POST /sessions/{id}/learn`` (ARCHITECT6 §4.3.1)."""

    pattern_name: str | None = None
    description: str | None = None
    scope: Literal["session", "project", "global"] = "session"


class LearnContentRequest(BaseModel):
    """Request body for ``POST /learn`` (PROMPT_MVP M-26)."""

    content: str = Field(min_length=1)
    category: Literal["fact", "preference", "project"] = "fact"


class LearnResponse(BaseModel):
    """Union of both spec response shapes (PROMPT_MVP + BACKLOG6)."""

    status: str = "ok"
    learned_id: str
    file: str
    compacted: bool
    line_count: int


# --- session-log extraction ---------------------------------------------------


def _flatten(content: Any) -> str:
    """Message content (str or content blocks) as plain text."""
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
    return "" if content is None else str(content)


def load_events(session_id: str) -> list[dict]:
    """Parse the M-14 JSONL projection of ``session_id`` (tolerant to bad lines)."""
    path = session_jsonl_path(session_id)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return []
    events: list[dict] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            logger.warning("skipping corrupt session-log line for %s", session_id)
            continue
        if isinstance(event, dict):
            events.append(event)
    return events


def _tool_calls_by_id(events: list[dict]) -> dict[str, dict]:
    """Map ``tool_call_id`` -> the assistant's tool call (name + args)."""
    calls: dict[str, dict] = {}
    for event in events:
        if event.get("type") != "ai":
            continue
        for call in (event.get("payload") or {}).get("tool_calls") or []:
            call_id = call.get("id")
            if isinstance(call, dict) and call_id:
                calls[str(call_id)] = call
    return calls


def _bash_exit_code(text: str) -> int | None:
    """Best-effort ``exit_code`` from a bash tool result (JSON in markers)."""
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        data = json.loads(text[start : end + 1])
    except ValueError:
        return None
    if isinstance(data, dict) and isinstance(data.get("exit_code"), int):
        return int(data["exit_code"])
    return None


def _is_success(event: dict, call: dict | None) -> bool:
    """BACKLOG6 definition of a successful tool call."""
    payload = event.get("payload") or {}
    if payload.get("status") == "error":
        return False
    text = _flatten(payload.get("content")).strip()
    if text.startswith("Denied by policy:") or text.startswith("Denied: "):
        return False
    name = str((call or {}).get("name") or payload.get("name") or "")
    if name == "bash":
        exit_code = _bash_exit_code(text)
        if exit_code is not None and exit_code != 0:
            return False
    return True


def extract_sequence(events: list[dict]) -> list[dict]:
    """Last successful tool-call sequence of the log (oldest first).

    Walks backwards: ``ai``/``system`` events are transparent, tool events
    are collected while successful, and the walk stops at the first
    ``user`` event (turn boundary) or the first unsuccessful tool call —
    so an error as the *last* call yields an empty sequence (400 upstream).
    """
    calls = _tool_calls_by_id(events)
    sequence: list[dict] = []
    for event in reversed(events):
        kind = event.get("type")
        if kind == "user":
            break
        if kind != "tool":
            continue
        payload = event.get("payload") or {}
        call = calls.get(str(payload.get("tool_call_id") or ""))
        if not _is_success(event, call):
            break
        sequence.append(
            {
                "name": str((call or {}).get("name") or payload.get("name") or "tool"),
                "args": dict((call or {}).get("args") or {}),
                "content": _flatten(payload.get("content")),
            }
        )
    sequence.reverse()
    return sequence


def auto_name(sequence: list[dict]) -> str:
    """``grep_read_edit``-style fallback pattern name (BACKLOG6 constraint)."""
    names: list[str] = []
    for step in sequence:
        name = re.sub(r"[^a-z0-9]+", "_", str(step["name"]).lower()).strip("_")
        if name and name not in names:
            names.append(name)
    return "_".join(names)[:60].strip("_") or "learn"


def _render_step(step: dict) -> str:
    """``grep(query=foo)`` — one bounded step of the pattern line."""
    name = step["name"]
    args = step.get("args") or {}
    if not args:
        return f"`{name}`"
    rendered = ", ".join(f"{key}={value}" for key, value in list(args.items())[:3])
    if len(rendered) > 60:
        rendered = rendered[:57] + "..."
    return f"`{name}({rendered})`"


def format_entry(
    sequence: list[dict],
    *,
    pattern_name: str,
    description: str,
    session_id: str,
) -> str:
    """Entry body in the ARCHITECT6 §3.1.1 ``[learned]`` shape."""
    pattern = " → ".join(_render_step(step) for step in sequence)
    scenario = description or pattern_name
    return (
        f"Сценарий: «{scenario}».\n"
        f"Паттерн: {pattern}.\n"
        f"Контекст: session {session_id[:8]}, tool-calls: {len(sequence)}, "
        f"name: {pattern_name}.\n"
        "Условие успеха: последовательность выполнилась без ошибок."
    )


# --- write helper --------------------------------------------------------------


def _store_entry(
    file: str,
    text: str,
    *,
    kind: str,
    confidence: float,
    source: str,
    session_id: str | None,
    reason: str,
) -> LearnResponse:
    """Append one entry and record the ``learn`` audit row (never blocks)."""
    store = get_md_store()
    with _learn_lock:
        item = MemoryItem.create(
            kind=kind,
            text=text,
            id=next_id(store.read(file), kind),
            confidence=confidence,
            source=source,
        )
        store.append(file, item.to_markdown(), session_id=session_id)
        compacted = store.needs_compaction(file)
        line_count = len(store.read(file).splitlines())
    record_memory_op(
        "learn",
        file,
        item.to_markdown(),
        reason=reason,
        session_id=session_id,
        memory_id=item.id,
        source=source,
        trace_id=uuid.uuid4().hex[:16],
    )
    return LearnResponse(
        learned_id=str(item.id),
        file=file,
        compacted=compacted,
        line_count=line_count,
    )


# --- endpoints -----------------------------------------------------------------


@router.post("/sessions/{session_id}/learn", response_model=LearnResponse)
async def learn_session(session_id: str, req: LearnRequest) -> LearnResponse:
    """Capture the session's last successful tool sequence (ARCHITECT6 §4.3.1).

    400 when the last turn has no successful tool-call sequence (no tools,
    only errors, or only permission refusals).
    """
    try:
        await project_thread(session_id)
    except Exception as exc:  # noqa: BLE001 - degraded mode must still learn
        logger.debug("session-log refresh skipped for %s: %s", session_id, exc)

    sequence = extract_sequence(load_events(session_id))
    if not sequence:
        raise HTTPException(
            status_code=400, detail="No successful tool-call sequence to learn"
        )

    pattern_name = (req.pattern_name or "").strip() or auto_name(sequence)
    description = (req.description or "").strip()
    return _store_entry(
        "LEARNED.md",
        format_entry(
            sequence,
            pattern_name=pattern_name,
            description=description,
            session_id=session_id,
        ),
        kind="learned",
        confidence=_CONFIDENCE["learned"],
        source="/learn",
        session_id=session_id,
        reason=f"/learn scope={req.scope}",
    )


@router.post("/learn", response_model=LearnResponse)
async def learn_content(req: LearnContentRequest) -> LearnResponse:
    """Append caller-supplied content to the category's L0 file (PROMPT_MVP)."""
    file = _CATEGORY_FILES[req.category]
    kind = kind_for(file)
    return _store_entry(
        file,
        req.content.strip(),
        kind=kind,
        confidence=_CONFIDENCE.get(kind, 1.0),
        source="/learn",
        session_id=None,
        reason=f"/learn category={req.category}",
    )
