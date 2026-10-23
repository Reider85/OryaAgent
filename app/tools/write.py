"""Tool: write - atomic file writer (M-08).

Contract (PROMPT_MVP M-08)::

    write(path, content, create_dirs=True) -> str

Behaviour:

* **atomic-write**: content is written to a temporary file in the same
  directory (``tempfile.mkstemp`` - guaranteed unique, same filesystem),
  flushed + ``fsync``-ed, then moved over the target with ``os.replace``
  (atomic on POSIX and Windows). A crash mid-write never leaves a
  half-written file;
* when overwriting, the existing file's permission bits are preserved
  (``mkstemp`` creates ``0600``);
* ``create_dirs=True`` creates missing parent directories;
* path validation: only the workspace, ``~/.orya`` and the memory dir
  are writable (``app/tools/_validators.py``) - checked *before* any
  directory is created;
* writing to a directory path is rejected;
* failures raise ``ToolException`` and the temp file is cleaned up;
* results are **never cached** (side-effect tool - see
  ``app.core.cache``); a subsequent ``read`` sees the new content
  automatically because the cache key includes the file mtime.

Under the strict permission policy this tool is gated by
``interrupt_before`` (M-13): the graph pauses for user approval before
the tool node runs.

Usage::

    from app.tools import write

    await write.ainvoke({"path": "notes.txt", "content": "hello\\n"})
    await write.ainvoke({"path": "sub/dir/a.py", "content": "x = 1\\n"})
"""

from __future__ import annotations

import asyncio
import logging
import os
import stat
import tempfile
from pathlib import Path
from typing import Annotated

from langchain_core.tools import ToolException, tool

from app.tools._validators import validate_path

logger = logging.getLogger(__name__)


def _write_atomic(resolved: Path, content: str) -> int:
    """Write ``content`` to ``resolved`` atomically; return byte count.

    Runs in a worker thread (called via ``asyncio.to_thread``). On any
    failure the temp file is removed and the exception re-raised - the
    target file keeps its previous content.
    """
    data = content.encode("utf-8")
    fd, tmp_name = tempfile.mkstemp(
        dir=str(resolved.parent),
        prefix=f".{resolved.name}.",
        suffix=".tmp",
    )
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        if resolved.exists():
            # mkstemp creates 0600; keep the mode of the file we replace.
            os.chmod(tmp_name, stat.S_IMODE(os.stat(resolved).st_mode))
        os.replace(tmp_name, resolved)
    except BaseException:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)
        raise
    return len(data)


@tool
async def write(
    path: Annotated[
        str,
        "Path of the file to write (relative to the workspace, or inside ~/.orya).",
    ],
    content: Annotated[
        str,
        "Full new content of the file. Previous content is replaced entirely.",
    ],
    create_dirs: Annotated[
        bool,
        "Create missing parent directories (default: true).",
    ] = True,
) -> str:
    """Write content to a file, replacing any previous content.

    The write is atomic: content goes to a temporary file in the same
    directory, then the temp file is renamed over the target, so a
    crash mid-write never leaves a half-written file. Missing parent
    directories are created unless create_dirs is false. Under the
    strict permission policy this tool requires user approval.
    """
    resolved = validate_path(path)

    if await asyncio.to_thread(resolved.is_dir):
        raise ToolException(f"Not a file (path is a directory): {path}")

    if not resolved.parent.exists():
        if not create_dirs:
            raise ToolException(
                f"Parent directory does not exist: {resolved.parent} "
                "(pass create_dirs=true to create it)"
            )
        try:
            await asyncio.to_thread(resolved.parent.mkdir, parents=True, exist_ok=True)
        except OSError as exc:
            raise ToolException(
                f"Cannot create directory {resolved.parent}: {exc}"
            ) from exc

    try:
        written = await asyncio.to_thread(_write_atomic, resolved, content)
    except OSError as exc:
        raise ToolException(f"Cannot write {path}: {exc}") from exc

    logger.debug("write: %s bytes -> %s", written, resolved)
    return f"Wrote {written} bytes to {resolved}"
