"""Prompt-injection defense (M-22): detect, sanitize, audit.

Regex heuristics for prompt-injection attempts in tool output, file
content and user input (PROMPT_MVP 3.4 M-22). Detection never blocks and
never calls an LLM — a suspected hit is *annotated* and *audited*
(BACKLOG5 M-22: «запретить чтение malicious-файлов нельзя — только warn»).

Pattern categories:

1. **Instruction override** — attempts to override the system prompt:
   "ignore previous instructions", "disregard all directions",
   "forget everything", "new instructions:", "end of message";
2. **Role override** — attempts to change the AI's role: a ``system:`` /
   ``assistant:`` / ``user:`` prefix (line start *or* mid-line),
   "You are now assistant:";
3. **Chat template markers** — ```` / ``</s>`` style tokens;
4. **Smuggled directives** — instructions hidden in an HTML comment
   (``<!-- override everything above -->``).

The three defense layers:

* :func:`sanitize_untrusted` — the spec API: frames content in the
  ``[UNTRUSTED_CONTENT_START/END]`` markers and appends the WARNING line;
* :func:`check_injection` — detect + report for callers with their own
  output shape (bash/grep keep the JSON ``injection_warning`` field);
* :func:`log_security_incident` — the audit trail: counter, process log
  and a row in ``memory_audit_log`` (``action='security.incident'``).
  The row is written when the asyncpg pool is up; if the write fails the
  incident falls back to ``{sessions_dir}/security_incidents.jsonl``.
  Nothing here ever raises into a tool.

Usage::

    from app.core.security import check_injection, sanitize_untrusted

    framed = sanitize_untrusted(text, source="read", session_id=sid)
    pattern = check_injection(output, source="bash")
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.core.config import get_settings

logger = logging.getLogger(__name__)

UNTRUSTED_CONTENT_START = "[UNTRUSTED_CONTENT_START]"
UNTRUSTED_CONTENT_END = "[UNTRUSTED_CONTENT_END]"

#: Shared warning wording (read brackets it, bash/grep expose it verbatim).
WARNING_PREFIX = "WARNING: possible prompt injection detected in"

#: Stored excerpt cap for ``memory_audit_log.content_preview``.
INCIDENT_PREVIEW_CHARS = 500

#: Local fallback trail when the ``memory_audit_log`` insert fails.
INCIDENTS_FILENAME = "security_incidents.jsonl"

# Injection patterns with compiled regexes.
# Each tuple is (pattern_id: str, compiled_regex: Pattern).
# Order matters: the first match wins, so the most specific pattern ids
# come first and existing callers/tests rely on these ids.
INJECTION_PATTERNS: list[tuple[str, re.Pattern]] = [
    # 1. Instruction override
    (
        "ignore_previous_instructions",
        re.compile(
            r"ignore\s+(all\s+)?(previous|prior|above)\s+instructions",
            re.IGNORECASE,
        ),
    ),
    (
        "disregard_directions",
        re.compile(
            r"disregard\s+(all\s+)?(directions|instructions)",
            re.IGNORECASE,
        ),
    ),
    (
        "forget_everything",
        re.compile(r"forget\s+(everything|all)\b", re.IGNORECASE),
    ),
    (
        "new_instructions",
        re.compile(r"new\s+instructions\s*:", re.IGNORECASE),
    ),
    (
        "end_of_message",
        re.compile(
            r"end\s+of\s+(message|instructions|prompt|response)",
            re.IGNORECASE,
        ),
    ),
    (
        "begin_of_instructions",
        re.compile(
            r"begin\s+of\s+instructions",
            re.IGNORECASE,
        ),
    ),
    # 2. Smuggled directives (HTML comment hiding an instruction)
    (
        "html_comment_override",
        re.compile(
            r"<!--[^<>]*(?:ignore|disregard|instructions|override)[^<>]*-->",
            re.IGNORECASE | re.DOTALL,
        ),
    ),
    # 3. Role override
    (
        "role_override",
        re.compile(
            r"^\s*(system|assistant|user)\s*:",
            re.IGNORECASE | re.MULTILINE,
        ),
    ),
    (
        "system_colon",
        re.compile(r"(?<![\w.])system\s*:", re.IGNORECASE),
    ),
    (
        "you_are_now",
        re.compile(
            r"you\s+are\s+now\s+(an\s+)?(assistant|chatbot|model|bot)",
            re.IGNORECASE,
        ),
    ),
    (
        "act_as",
        re.compile(
            r"act\s+as\s+(an\s+)?(assistant|chatbot|model|bot)",
            re.IGNORECASE,
        ),
    ),
    # 4. Chat template markers
    (
        "im_start_marker",
        re.compile(r"<\|im_start\|>", re.IGNORECASE),
    ),
    (
        "im_end_marker",
        re.compile(r"<\|im_end\|>", re.IGNORECASE),
    ),
    (
        "eos_marker",
        re.compile(r"</s>", re.IGNORECASE),
    ),
    (
        "chat_template",
        re.compile(
            r"<\s*im_start\s*>|<\s*im_end\s*>|<\s*\|im_start\|\s*>|<\s*\|im_end\|\s*>",
            re.IGNORECASE,
        ),
    ),
]

#: Process-local ``orya_prompt_injection_warnings_total`` counters,
#: keyed by ``(source, pattern)`` — mirrored into /metrics (M-22 AC).
_COUNTERS: Counter[tuple[str, str]] = Counter()

#: Audit writes scheduled but not awaited yet (see :func:`drain_incidents`).
_PENDING_TASKS: set[asyncio.Task] = set()


def wrap_untrusted(content: str) -> str:
    """Frame untrusted payload with the standard markers.

    Used by tools that return file content or command output so the
    model can distinguish data from instructions (TRIZ #9 preliminary
    anti-action). Content is returned verbatim between the markers.
    """
    return f"{UNTRUSTED_CONTENT_START}\n{content}\n{UNTRUSTED_CONTENT_END}"


def detect_injection(content: str) -> str | None:
    """Check if content contains a prompt-injection pattern.

    Args:
        content: Text to check for injection patterns.

    Returns:
        The pattern ID (str) of the first match, or None if no injection
        detected. Pattern IDs are defined in ``INJECTION_PATTERNS``.
    """
    for pattern_id, regex in INJECTION_PATTERNS:
        if regex.search(content):
            return pattern_id
    return None


def injection_warning(pattern: str) -> str:
    """Canonical warning text for a detected ``pattern`` id."""
    return f"{WARNING_PREFIX} [{pattern}]"


def session_id_from_config(config: Any) -> str | None:
    """Extract ``configurable.thread_id`` from a ``RunnableConfig`` mapping."""
    if not isinstance(config, dict):
        return None
    configurable = config.get("configurable")
    if not isinstance(configurable, dict):
        return None
    thread_id = configurable.get("thread_id")
    return str(thread_id) if thread_id else None


def get_injection_stats() -> dict[str, Any]:
    """Counter snapshot for ``/metrics``: ``total`` + ``by_source``."""
    by_source: dict[str, dict[str, int]] = {}
    for (source, pattern), count in sorted(_COUNTERS.items()):
        by_source.setdefault(source, {})[pattern] = count
    return {"total": sum(_COUNTERS.values()), "by_source": by_source}


def reset_injection_stats() -> None:
    """Drop all counters (tests)."""
    _COUNTERS.clear()


async def drain_incidents() -> None:
    """Await every scheduled audit write (tests / graceful shutdown)."""
    while _PENDING_TASKS:
        await asyncio.gather(*list(_PENDING_TASKS), return_exceptions=True)


def _append_incident_jsonl(record: dict[str, Any]) -> None:
    """Append one incident to the local JSONL trail; never raises."""
    path = Path(get_settings().sessions_dir) / INCIDENTS_FILENAME
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError as exc:
        logger.warning("cannot append the security incident trail: %s", exc)


async def _persist_incident(record: dict[str, Any]) -> None:
    """Write the ``memory_audit_log`` row; fall back to the JSONL trail."""
    from app.db import get_pool_if_created  # local: keep import time light

    pool = get_pool_if_created()
    if pool is None:
        logger.debug("no asyncpg pool; the incident goes to the JSONL trail")
        _append_incident_jsonl(record)
        return
    try:
        await pool.execute(
            "INSERT INTO memory_audit_log "
            "(actor, action, file, content_preview, reason, session_id) "
            "VALUES ($1, $2, $3, $4, $5, $6)",
            "agent",
            "security.incident",
            record["source"],
            record["preview"],
            record["pattern"],
            record["session_id"],
        )
    except Exception as exc:  # noqa: BLE001 - the audit trail must never break a tool
        logger.warning(
            "memory_audit_log write failed (%s); falling back to the JSONL trail",
            exc,
        )
        _append_incident_jsonl(record)


def log_security_incident(
    pattern: str,
    *,
    source: str,
    preview: str,
    session_id: str | None = None,
) -> None:
    """Record a suspected injection: counter + process log + audit trail.

    Args:
        pattern: Matched id from ``INJECTION_PATTERNS``.
        source: Where the payload came from (``read`` / ``bash`` /
            ``grep`` / ``user_input`` / ...).
        preview: Raw payload; stored truncated to
            ``INCIDENT_PREVIEW_CHARS`` characters.
        session_id: Owning session/thread id, when known.

    Never raises: persistence is scheduled as a background task when a
    loop is running (the process log line is emitted synchronously).
    """
    _COUNTERS[(source, pattern)] += 1
    logger.warning(
        "prompt injection detected [%s] (source=%s session=%s)",
        pattern,
        source,
        session_id,
    )
    record = {
        "ts": datetime.now(UTC).isoformat(timespec="seconds"),
        "pattern": pattern,
        "source": source,
        "session_id": session_id,
        "preview": preview[:INCIDENT_PREVIEW_CHARS],
    }
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        _append_incident_jsonl(record)
        return
    task = loop.create_task(_persist_incident(record))
    _PENDING_TASKS.add(task)
    task.add_done_callback(_PENDING_TASKS.discard)


def check_injection(
    content: str,
    *,
    source: str,
    session_id: str | None = None,
) -> str | None:
    """Detect an injection in ``content`` and report it when found.

    Report = counter bump + process-log warning + ``memory_audit_log``
    audit row. Returns the matched pattern id, or ``None``.
    """
    pattern = detect_injection(content)
    if pattern is not None:
        log_security_incident(
            pattern, source=source, preview=content, session_id=session_id
        )
    return pattern


def sanitize_untrusted(
    content: str,
    *,
    source: str = "unknown",
    session_id: str | None = None,
    scan: str | None = None,
) -> str:
    """Frame ``content`` as untrusted and annotate a suspected injection.

    The spec API (PROMPT_MVP M-22): detect → wrap with the
    ``[UNTRUSTED_CONTENT_START/END]`` markers → append the
    ``[WARNING: possible prompt injection detected in [pattern]]`` line
    after the block (the warning itself stays outside the markers, so it
    reads as the tool speaking, not as data).

    Args:
        content: Text to frame (verbatim).
        source: Audit ``file`` column for a detected incident.
        session_id: Owning session/thread id, when known.
        scan: Text the detector runs on — defaults to ``content``.
            ``read`` scans the whole file but frames only the visible
            window, so it passes ``scan=raw_text``.
    """
    pattern = check_injection(
        content if scan is None else scan,
        source=source,
        session_id=session_id,
    )
    framed = wrap_untrusted(content)
    if pattern:
        framed += f"\n[{injection_warning(pattern)}]"
    return framed
