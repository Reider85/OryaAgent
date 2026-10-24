"""Tool: edit - targeted string replacement in a file (M-09).

Contract (PROMPT_MVP M-09)::

    edit(path, old_string, new_string, replace_all=False) -> str

Behaviour:

* **exact match only** - no regex, no fuzzy matching: the replacement
  is safe precisely because ``old_string`` must appear verbatim;
* uniqueness guard: if ``old_string`` occurs more than once and
  ``replace_all`` is false, the tool fails and asks for more context -
  a blind replace could corrupt an unrelated call-site;
* path validation: only the workspace, ``~/.orya`` and the memory
  dir are editable (``app/tools/_validators.py``);
* the file is read as **bytes** and decoded as UTF-8 (strict) so
  CRLF line endings survive the round-trip (``Path.read_text`` would
  silently normalize ``\\r\\n`` -> ``\\n``);
* size cap: files above ``MAX_FILE_SIZE_BYTES`` are rejected (same
  limit as ``read`` - M-23 token/memory-blowup protection);
* **atomic rewrite**: the modified content goes through the same
  temp-file + ``os.replace`` helper as ``write`` (M-08) - a crash
  mid-edit never leaves a half-written file;
* results are **never cached** (side-effect tool); after the edit the
  M-21 hook drops every tool-result cached for this path
  (``app.hooks.cache_invalidation``), and a subsequent ``read`` sees
  the new content anyway because the read cache key includes the file
  mtime.

Under the strict permission policy this tool is gated by
``interrupt_before`` (M-13): the graph pauses for user approval before
the tool node runs.

Usage::

    from app.tools import edit

    await edit.ainvoke({
        "path": "app/main.py",
        "old_string": "def main():",
        "new_string": "def main(argv: list[str] | None = None):",
    })
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Annotated

from langchain_core.tools import ToolException, tool

from app.hooks.cache_invalidation import invalidate_cache_for_path
from app.tools._validators import validate_path
from app.tools.read import MAX_FILE_SIZE_BYTES
from app.tools.write import _write_atomic

logger = logging.getLogger(__name__)


def _edit_sync(
    resolved: Path,
    display_path: str,
    old_string: str,
    new_string: str,
    replace_all: bool,
) -> int:
    """Read -> modify in memory -> atomic write; return replacement count.

    Runs in a worker thread (called via ``asyncio.to_thread``). The
    read-modify-write sequence happens inside one thread, so no other
    ``edit`` call can interleave; the final write is atomic (temp file
    + ``os.replace``, see ``app.tools.write._write_atomic``).
    """
    try:
        size = resolved.stat().st_size
    except FileNotFoundError as exc:
        raise ToolException(f"File not found: {display_path}") from exc
    except OSError as exc:
        raise ToolException(f"Cannot stat {display_path}: {exc}") from exc
    if size > MAX_FILE_SIZE_BYTES:
        raise ToolException(
            f"File too large ({size / (1024 * 1024):.1f} MB, limit "
            f"{MAX_FILE_SIZE_BYTES // (1024 * 1024)} MB): split the file "
            "or use bash for surgical changes"
        )

    try:
        text = resolved.read_bytes().decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ToolException(f"Not a UTF-8 text file: {display_path}") from exc

    count = text.count(old_string)
    if count == 0:
        raise ToolException(f"old_string not found in {display_path}")
    if count > 1 and not replace_all:
        raise ToolException(
            f"old_string is not unique ({count} occurrences) in {display_path}; "
            "provide more surrounding context or set replace_all=true"
        )

    edited = (
        text.replace(old_string, new_string)
        if replace_all
        else text.replace(old_string, new_string, 1)
    )
    try:
        _write_atomic(resolved, edited)
    except OSError as exc:
        raise ToolException(f"Cannot write {display_path}: {exc}") from exc
    return count


@tool
async def edit(
    path: Annotated[
        str,
        "Path of the file to edit (relative to the workspace, or inside ~/.orya).",
    ],
    old_string: Annotated[
        str,
        "Exact text to replace (must appear in the file; unique unless replace_all).",
    ],
    new_string: Annotated[
        str,
        "Replacement text.",
    ],
    replace_all: Annotated[
        bool,
        "Replace every occurrence instead of requiring a unique match (default: false).",
    ] = False,
) -> str:
    """Replace an exact string in a file and report how many times it matched.

    old_string must match the file content verbatim (no regex). If it
    appears more than once the tool fails unless replace_all is true -
    pass more surrounding context to target a single occurrence. The
    rewrite is atomic. Under the strict permission policy this tool
    requires user approval.
    """
    if not old_string:
        raise ToolException("old_string must not be empty")

    resolved = validate_path(path)

    if await asyncio.to_thread(resolved.is_dir):
        raise ToolException(f"Not a file (path is a directory): {path}")

    count = await asyncio.to_thread(
        _edit_sync, resolved, path, old_string, new_string, replace_all
    )

    logger.debug("edit: %s occurrence(s) -> %s", count, resolved)
    await invalidate_cache_for_path(str(resolved))
    return f"Edited {resolved}: replaced {count} occurrence(s)"
