"""Session listing and info (M-17): list sessions from JSONL files, enrich with DB.

Provides functions to list available sessions from the filesystem (JSONL
projections) and optionally enrich with metadata from the PostgreSQL
sessions table when available.

Usage::

    from app.ui.sessions import list_sessions, enrich_titles_from_db

    sessions = list_sessions(get_settings().sessions_dir, limit=10)
    enriched = enrich_titles_from_db(sessions)
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

import asyncpg

from app.db import get_asyncpg_pool

logger = logging.getLogger(__name__)


@dataclass
class SessionInfo:
    """Info about one session for display in sidebar."""

    session_id: str
    title: str | None = None
    last_modified: float | None = None
    message_count: int = 0

    @property
    def display_name(self) -> str:
        """Name to show in sidebar (title or session_id prefix)."""
        if self.title:
            return self.title
        # Shorten session_id for display
        return f"Session {self.session_id[:8]}"


async def list_sessions(
    sessions_dir: Path,
    *,
    limit: int = 10,
    pool: asyncpg.Pool | None = None,
) -> list[SessionInfo]:
    """List available sessions from JSONL files, sorted by mtime.

    Scans the sessions directory for *.jsonl files, extracts metadata,
    and returns up to `limit` sessions sorted by modification time
    (newest first).

    Args:
        sessions_dir: Directory containing session JSONL files.
        limit: Maximum number of sessions to return.
        pool: Database pool for title enrichment (optional, can be None).

    Returns:
        List of SessionInfo objects, newest first.
    """
    if not sessions_dir.exists():
        logger.info("Sessions directory %s does not exist", sessions_dir)
        return []

    # Find all JSONL files
    jsonl_files = list(sessions_dir.glob("*.jsonl"))
    if not jsonl_files:
        logger.info("No JSONL files found in %s", sessions_dir)
        return []

    # Extract session info from each file
    sessions: list[SessionInfo] = []
    for jsonl_file in jsonl_files:
        try:
            info = _extract_session_info(jsonl_file)
            if info:
                sessions.append(info)
        except Exception as exc:
            logger.warning("Failed to read session info from %s: %s", jsonl_file, exc)

    # Sort by last_modified (newest first)
    sessions.sort(key=lambda s: s.last_modified or 0.0, reverse=True)

    # Limit results
    return sessions[:limit]


def _extract_session_info(jsonl_file: Path) -> SessionInfo | None:
    """Extract session metadata from a JSONL file.

    Reads the first few lines to get:
    - session_id from filename
    - title from first user message
    - last_modified from file mtime
    - message_count from line count

    Args:
        jsonl_file: Path to the session JSONL file.

    Returns:
        SessionInfo or None if file is empty/corrupt.
    """
    session_id = jsonl_file.stem

    # Get file modification time
    last_modified = jsonl_file.stat().st_mtime

    # Try to read title from first user message
    title = None
    message_count = 0

    try:
        with jsonl_file.open("r", encoding="utf-8") as fh:
            for line in fh:
                message_count += 1
                if title is not None:
                    continue
                try:
                    event = json.loads(line.strip())
                    if event.get("type") == "user":
                        content = event.get("payload", {}).get("message_id", "")
                        if content:
                            # Use first 50 chars of first user message as title
                            title = content[:50]
                            if len(content) > 50:
                                title += "..."
                except json.JSONDecodeError:
                    # Skip corrupt lines
                    continue
    except OSError:
        # File not readable or empty
        return None

    return SessionInfo(
        session_id=session_id,
        title=title,
        last_modified=last_modified,
        message_count=message_count,
    )


async def enrich_titles_from_db(
    sessions: list[SessionInfo],
    pool: asyncpg.Pool | None = None,
) -> list[SessionInfo]:
    """Enrich session titles from PostgreSQL sessions table.

    Attempts to load titles from the sessions table for sessions that
    don't have titles extracted from JSONL. Best-effort: if DB is
    unavailable or query fails, returns original list unchanged.

    Args:
        sessions: List of SessionInfo to enrich.
        pool: Database pool; if None, will try to get one.

    Returns:
        List of SessionInfo with enriched titles where available.
    """
    if not sessions:
        return sessions

    if pool is None:
        try:
            pool = await get_asyncpg_pool()
        except Exception as exc:
            logger.warning("Cannot get database pool: %s", exc)
            return sessions

    # Build map of session_id -> SessionInfo for lookup
    session_map = {s.session_id: s for s in sessions}
    session_ids = list(session_map.keys())

    try:
        # Query for titles of sessions that don't have them
        query = """
            SELECT session_id, title
            FROM sessions
            WHERE session_id = ANY($1)
            AND title IS NOT NULL
        """
        rows = await pool.fetch(query, session_ids)

        # Update titles in session_map
        for row in rows:
            session_id = row["session_id"]
            title = row["title"]
            if session_id in session_map and not session_map[session_id].title:
                session_map[session_id].title = title

        logger.debug(
            "Enriched %d/%d session titles from database", len(rows), len(sessions)
        )

    except Exception as exc:
        logger.warning("Cannot query session titles from DB: %s", exc)
        # Return original sessions on error
        return sessions

    return list(session_map.values())


async def get_session_count(
    sessions_dir: Path,
    *,
    pool: asyncpg.Pool | None = None,
) -> int:
    """Get total count of available sessions (JSONL files + DB entries).

    Args:
        sessions_dir: Directory containing session JSONL files.
        pool: Database pool for counting DB sessions (optional).

    Returns:
        Total count of sessions (filesystem + DB, no duplicates).
    """
    # Count from filesystem
    fs_sessions = 0
    if sessions_dir.exists():
        fs_sessions = len(list(sessions_dir.glob("*.jsonl")))

    # Count from database (if available)
    db_sessions = 0
    if pool is not None:
        try:
            count = await pool.fetchval("SELECT COUNT(*) FROM sessions")
            db_sessions = count or 0
        except Exception as exc:
            logger.warning("Cannot count sessions from DB: %s", exc)

    # Return max (filesystem sessions may not be in DB yet)
    return max(fs_sessions, db_sessions)
