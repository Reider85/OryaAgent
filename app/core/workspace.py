"""Per-session workspace («open project») — the root the tools work in.

Before this seam every tool resolved relative paths and ran subprocesses
against the *process* cwd of the API server, so a session could only ever
work in one directory. ``open_workspace`` lets the API/UI layer open an
arbitrary project directory for a session:

* :func:`open_workspace` — validate a user-supplied path (must exist and
  be a directory) and return it resolved;
* :func:`set_workspace` / :func:`reset_workspace` / :func:`workspace_scope`
  — bind the workspace to the *current task* through a ``ContextVar`` so
  concurrent sessions never see each other's project (no ``os.chdir``);
* :func:`current_workspace` — the bound directory, falling back to
  ``Path.cwd()`` when a session opened no project.

The tools read it through :func:`current_workspace` only:
``app/tools/_validators.py`` resolves relative paths against it and adds
it to the allowed roots, ``bash`` uses it as the default subprocess cwd,
``grep``/``glob`` search in it, and ``project_context_block`` prints it
into the system prompt.

Security note: opening a directory is an explicit user action (same trust
level as letting the agent run ``bash``); the M-22 injection auditing and
the untrusted-content framing are unaffected.
"""

from __future__ import annotations

import contextvars
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

#: Workspace of the current task; ``None`` → process cwd.
_WORKSPACE: contextvars.ContextVar[Path | None] = contextvars.ContextVar(
    "orya_workspace", default=None
)


def current_workspace() -> Path:
    """Directory the tools of this task work in (process cwd when unset)."""
    workspace = _WORKSPACE.get()
    return workspace if workspace is not None else Path.cwd()


def set_workspace(path: Path | None) -> contextvars.Token:
    """Bind ``path`` as the workspace of the current task; returns a token."""
    return _WORKSPACE.set(path)


def reset_workspace(token: contextvars.Token) -> None:
    """Undo a :func:`set_workspace` call with its token."""
    _WORKSPACE.reset(token)


@contextmanager
def workspace_scope(path: Path | None) -> Iterator[None]:
    """Bind ``path`` for the duration of the ``with`` block (None = cwd)."""
    token = _WORKSPACE.set(path)
    try:
        yield
    finally:
        _WORKSPACE.reset(token)


def open_workspace(path: str | Path) -> Path:
    """Validate a project directory and return it fully resolved.

    Raises:
        ValueError: the path cannot be resolved, does not exist or is not
            a directory — the API layer turns this into an HTTP 400.
    """
    candidate = Path(path).expanduser()
    try:
        resolved = candidate.resolve()
    except OSError as exc:
        raise ValueError(f"Cannot resolve working directory {path!r}: {exc}") from exc
    if not resolved.exists():
        raise ValueError(f"Working directory does not exist: {resolved}")
    if not resolved.is_dir():
        raise ValueError(f"Working directory is not a directory: {resolved}")
    return resolved
