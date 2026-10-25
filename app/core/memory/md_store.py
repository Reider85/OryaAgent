"""L0 memory store: six MD files + atomic append (M-25).

``MDStore`` is the memory seam of PROMPT_MVP §4.5 — the interface
``append(file, content)`` / ``read(file)`` / ``mtime(file)`` stays stable while
BETA adds ``SQLiteStore`` (L1) and a Qdrant store (L2) behind it.

Files (ARCHITECT6 §3.1.1 + PROMPT_MVP §3.7) live in ``settings.memory_dir``
(default ``~/.orya/memory``, ``ORYA_MEMORY_DIR``) and are created empty on
first use:

===================  ========  ==================================
File                 Max bytes Purpose
===================  ========  ==================================
``PROJECT.md``       8192      project context (mission/stack)
``LEARNED.md``       4096      facts learned through ``/learn``
``PREFERENCES.md``   2048      user/project preferences
``FACTS.md``         2048      critical project facts
``DECISIONS.md``     2048      short ADR-style decisions
``MEMORY_INDEX.md``  8192      L1/L2 index (empty placeholder in MVP)
===================  ========  ==================================

Write path (BACKLOG6 §M-25 constraints): one ``os.write`` of the whole entry
into an ``O_APPEND`` descriptor + ``fsync`` — POSIX guarantees atomicity for
single writes under 4096 bytes, and a crash can never interleave two entries.
Concurrency inside the process is serialized by a per-file
``threading.Lock``; cross-process writers take an advisory ``fcntl.flock``
where available (POSIX only — Windows relies on the atomic append itself).
Full-file rewrites (compaction, M-27) use ``tmp`` + ``os.replace``.

Every append is recorded best-effort in ``memory_audit_log`` (M-25 audit),
and files over their size budget get ``compact_if_needed`` scheduled — the
real compaction lands with M-27.
"""

from __future__ import annotations

import asyncio
import logging
import os
import threading
from datetime import UTC, datetime
from pathlib import Path

from app.core.memory.audit import record_memory_op
from app.core.memory.models import kind_for, parse_entries

try:  # POSIX advisory locking; absent on Windows
    import fcntl
except ImportError:  # pragma: no cover - exercised on Windows only
    fcntl = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

#: The six L0 files, in prompt-section order.
FILES: tuple[str, ...] = (
    "PROJECT.md",
    "LEARNED.md",
    "PREFERENCES.md",
    "FACTS.md",
    "DECISIONS.md",
    "MEMORY_INDEX.md",
)

#: Per-file compaction budget (ARCHITECT6 §3.1.1); default below applies.
MAX_BYTES: dict[str, int] = {
    "LEARNED.md": 4096,
    "PREFERENCES.md": 2048,
    "FACTS.md": 2048,
    "DECISIONS.md": 2048,
}

#: Budget for files without an explicit one (``PROJECT.md``, index).
DEFAULT_MAX_BYTES = 8192

#: POSIX atomicity of a single O_APPEND write holds below the pipe buffer.
PIPE_BUF = 4096

_locks_guard = threading.Lock()
_STORES: dict[str, MDStore] = {}


def get_md_store(memory_dir: Path | str | None = None) -> MDStore:
    """Cached :class:`MDStore` for ``memory_dir`` (default ``settings.memory_dir``).

    Idempotent per resolved path — the same pattern as ``get_cache``; the
    store itself is stateless (locks only), so caching is safe across turns.
    """
    if memory_dir is None:
        from app.core.config import get_settings

        memory_dir = get_settings().memory_dir
    path = Path(memory_dir)
    key = str(path)
    with _locks_guard:
        store = _STORES.get(key)
        if store is None:
            store = _STORES[key] = MDStore(path)
        return store


class MDStore:
    """L0 storage: six MD files, atomic append, compaction hooks."""

    FILES = FILES
    MAX_BYTES = MAX_BYTES
    DEFAULT_MAX_BYTES = DEFAULT_MAX_BYTES

    def __init__(self, memory_dir: Path | str) -> None:
        self.memory_dir = Path(memory_dir)
        self._locks: dict[str, threading.Lock] = {}
        self._pending: set[asyncio.Task] = set()
        self.memory_dir.mkdir(parents=True, exist_ok=True)
        for name in FILES:
            # Created empty: prompt placeholders ("(empty)", "(no PROJECT.md")
            # key off blank content, and existing files are never truncated.
            (self.memory_dir / name).touch()

    # -- reads ---------------------------------------------------------------

    def read(self, file: str) -> str:
        """Return the file body; ``""`` when missing or unreadable."""
        path = self._resolve(file)
        try:
            return path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return ""
        except OSError as exc:
            logger.warning("cannot read memory file %s: %s", path, exc)
            return ""

    def read_all(self) -> dict[str, str]:
        """All six files keyed by name — the system-prompt injection input."""
        return {name: self.read(name) for name in FILES}

    def mtime(self, file: str) -> float:
        """Last modification time (cache invalidation); ``0.0`` if missing."""
        try:
            return self._resolve(file).stat().st_mtime
        except OSError:
            return 0.0

    def stats(self) -> dict[str, dict]:
        """Per-file ``bytes`` / ``entries`` / ``last_write`` / budget flags."""
        out: dict[str, dict] = {}
        for name in FILES:
            path = self.memory_dir / name
            try:
                stat = path.stat()
            except OSError:
                continue
            content = self.read(name)
            limit = self.max_bytes(name)
            out[name] = {
                "bytes": stat.st_size,
                "entries": len(parse_entries(content, default_kind=kind_for(name))),
                "last_write": datetime.fromtimestamp(stat.st_mtime, UTC)
                .isoformat(timespec="seconds")
                .replace("+00:00", "Z"),
                "max_bytes": limit,
                "over_limit": stat.st_size > limit,
            }
        return out

    # -- writes --------------------------------------------------------------

    def append(self, file: str, content: str, **kwargs) -> None:
        """Atomically append one entry; durable (``fsync``) and thread-safe.

        ``content`` is normalised to a self-contained block (blank line
        before the next entry). Keyword args (``actor`` / ``session_id``)
        are forwarded to the audit record — the two-argument memory-seam
        contract of PROMPT_MVP §4.5 stays intact.
        """
        path = self._resolve(file)
        payload = (content.rstrip("\n") + "\n\n").encode("utf-8")
        if len(payload) >= PIPE_BUF:
            logger.warning(
                "memory entry for %s is %d bytes — single-write atomicity "
                "only holds below %d bytes",
                file,
                len(payload),
                PIPE_BUF,
            )
        with self._lock(file):
            self._write_append(path, payload)
        record_memory_op(
            "memory.append",
            file,
            payload.decode("utf-8", errors="replace"),
            memory_dir=self.memory_dir,
            **kwargs,
        )
        self._maybe_compact(file)

    @staticmethod
    def _write_append(path: Path, payload: bytes) -> None:
        """One O_APPEND descriptor: write (retrying only a short write) + fsync."""
        fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
        try:
            if fcntl is not None:
                fcntl.flock(fd, fcntl.LOCK_EX)
            try:
                written = 0
                while written < len(payload):
                    written += os.write(fd, payload[written:])
                os.fsync(fd)
            finally:
                if fcntl is not None:
                    fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)

    # -- compaction (M-25 hook, real work in M-27) ----------------------------

    def max_bytes(self, file: str) -> int:
        """Compaction budget for ``file``."""
        return MAX_BYTES.get(file, DEFAULT_MAX_BYTES)

    def needs_compaction(self, file: str) -> bool:
        """``True`` when ``file`` exceeds its size budget."""
        try:
            return self._resolve(file).stat().st_size > self.max_bytes(file)
        except OSError:
            return False

    async def compact_if_needed(self, file: str) -> bool:
        """Compaction stub (M-27 owns the real L0 -> L1 move).

        Returns ``True`` when ``file`` is over budget, ``False`` otherwise.
        """
        if not self.needs_compaction(file):
            return False
        logger.info(
            "compaction deferred to M-27: %s is %d bytes (budget %d)",
            file,
            self._resolve(file).stat().st_size,
            self.max_bytes(file),
        )
        return True

    def _maybe_compact(self, file: str) -> None:
        """Schedule ``compact_if_needed`` after an append that broke the budget."""
        if not self.needs_compaction(file):
            return
        logger.warning(
            "L0 memory file %s exceeds %d bytes — compaction scheduled",
            file,
            self.max_bytes(file),
        )
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return  # sync context (tests, CLI): M-27's cron will pick it up
        task = loop.create_task(self.compact_if_needed(file))
        self._pending.add(task)
        task.add_done_callback(self._pending.discard)

    # -- helpers -------------------------------------------------------------

    def _resolve(self, file: str) -> Path:
        if file not in FILES:
            raise ValueError(f"unknown memory file {file!r}; expected one of {FILES}")
        return self.memory_dir / file

    def _lock(self, file: str) -> threading.Lock:
        with _locks_guard:
            lock = self._locks.get(file)
            if lock is None:
                lock = self._locks[file] = threading.Lock()
            return lock
