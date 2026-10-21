"""Path validation for file tools (M-07).

Every filesystem-touching tool (``read``, later ``write``/``edit``/
``grep``) must refuse paths outside the workspace. Allowed roots:

1. the current working directory (the project workspace);
2. the Orya config directory (``~/.orya`` by default, or the parent of
   ``ORYA_CONFIG_PATH``) - covers L0 memory and session logs;
3. ``settings.memory_dir`` - covers an overridden memory location.

Symlinks are resolved *before* the check so a link inside the workspace
cannot smuggle reads of ``/etc/passwd``.

Design constraints (see ``analytics/PROMPT_MVP.md`` 9):

* failures raise ``ToolException`` so LangGraph turns them into an
  error ``ToolMessage`` instead of crashing the agent-loop;
* comparisons are case-normalized (Windows);
* no shell involvement - pure ``pathlib``.
"""

from __future__ import annotations

import os
from pathlib import Path

from langchain_core.tools import ToolException

from app.core.config import get_settings, user_config_path


def allowed_roots() -> list[Path]:
    """Resolved directories the tools may touch."""
    roots = [Path.cwd(), user_config_path().parent, get_settings().memory_dir]
    resolved: list[Path] = []
    for root in roots:
        try:
            resolved.append(_normalize(root))
        except OSError:
            continue
    return resolved


def _normalize(path: Path) -> Path:
    """Resolve symlinks and case-normalize for comparison."""
    return Path(os.path.normcase(str(path.expanduser().resolve())))


def validate_path(path: str | Path) -> Path:
    """Resolve ``path`` and ensure it lies inside an allowed root.

    Returns the fully resolved path. Raises ``ToolException`` when the
    path escapes the allowed roots or cannot be resolved.
    """
    candidate = Path(path).expanduser()
    try:
        resolved = candidate.resolve()
    except OSError as exc:
        raise ToolException(f"Cannot resolve path {path}: {exc}") from exc

    normalized = _normalize(resolved)
    for root in allowed_roots():
        if normalized == root or root in normalized.parents:
            return resolved

    raise ToolException(
        f"Path outside allowed roots: {path} "
        f"(allowed: {', '.join(str(r) for r in allowed_roots())})"
    )
