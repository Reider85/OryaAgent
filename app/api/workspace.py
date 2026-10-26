"""Workspace API: GET /workspace/browse — the UI's folder picker backend.

Answers the Chainlit «Open project» browser with an immediate listing of
one directory: only subdirectories (no files), sorted by name, capped at
:data:`MAX_DIRS` with a ``truncated`` flag. ``path`` is optional — the
default is the API server's process cwd, the same fallback the tools use
when a session has no project open (``app.core.workspace``).

Trust model: opening a directory is already an explicit user action with
the same trust level as letting the agent run ``bash`` (see
``app.core.workspace``); listing subdirectories is strictly weaker than
``open_workspace`` + a write tool, so this endpoint applies the same
validation (HTTP 400 on a missing path / a file / an unreadable
directory) and adds no extra restriction. The API listens on localhost.

The UI drives navigation through this endpoint only — Chainlit action
buttons carry the target path, and the FastAPI layer (not the Chainlit
process) touches the filesystem.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.core.workspace import open_workspace

router = APIRouter(tags=["workspace"])

#: Listing cap — a huge directory would otherwise flood the chat with
#: action buttons; the response carries ``truncated: true`` instead.
MAX_DIRS = 200


def _list_dirs(path: Path) -> tuple[list[dict[str, str]], bool]:
    """Immediate subdirectories of ``path``, sorted by name (case-folded).

    Returns ``(dirs, truncated)`` where each entry is
    ``{"name": …, "path": …}`` (``path`` as ``str(Path)`` so the UI can
    round-trip it back into ``?path=``). Raises ``OSError`` when the
    directory cannot be listed (permission denied, vanished).
    """
    entries: list[Path] = []
    with os.scandir(path) as it:
        for entry in it:
            try:
                if entry.is_dir():
                    entries.append(Path(entry.path))
            except OSError:
                continue  # vanished/reparse races — skip, never fail the listing
    entries.sort(key=lambda p: p.name.casefold())
    truncated = len(entries) > MAX_DIRS
    if truncated:
        entries = entries[:MAX_DIRS]
    return [{"name": p.name, "path": str(p)} for p in entries], truncated


@router.get("/workspace/browse")
async def browse_workspace(path: str | None = Query(None)) -> dict[str, Any]:
    """List the subdirectories of ``path`` (default: the server's cwd).

    Response: ``{"path": …, "parent": …|null, "dirs": [{"name","path"}],
    "truncated": bool}``. ``parent`` is ``null`` at a filesystem root
    (drive root on Windows) so the UI hides the «Up» button there.
    """
    try:
        target = open_workspace(path) if path else Path.cwd()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    try:
        dirs, truncated = await asyncio.to_thread(_list_dirs, target)
    except OSError as exc:
        raise HTTPException(
            status_code=400, detail=f"Cannot list directory {target}: {exc}"
        ) from exc

    parent = target.parent
    return {
        "path": str(target),
        "parent": str(parent) if parent != target else None,
        "dirs": dirs,
        "truncated": truncated,
    }
