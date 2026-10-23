"""Tool: bash - execute shell commands with token-efficient output (M-10).

Contract (PROMPT_MVP M-10, BACKLOG5 M-10)::

    bash(command, timeout=30, cwd=None, env=None) -> str

Behaviour:

* **JSON output**: returns a JSON document with ``stdout``, ``stderr``,
  ``exit_code``, ``duration_ms`` and ``truncated``.
* **Token efficiency (M-23)**: streams longer than 5000 chars are cut to
  first 2500 chars + ``... [N chars truncated] ...`` + last 2500 chars
  (char-based, so a single 200 KB line is cut too); 100+ identical
  consecutive lines collapse to ``... [100 identical lines] ...`` (dedup
  runs before truncation). ``truncated`` reports whether the *raw* output
  exceeded the cap - it is true when dedup alone had to drop lines as well.
* **Injection detection**: if raw stdout/stderr contains an injection
  pattern, the JSON carries ``injection_warning`` (``WARNING: possible
  prompt injection detected in [pattern_id]``). Deviation from BACKLOG5's
  "warning prefix": the warning lives *inside* the JSON document so the
  tool result stays one parseable object - prefixing would break the JSON
  contract the token-efficient format is built on.
* **Platform shells**: POSIX uses ``/bin/bash -lc``; Windows prefers a
  Win32 bash (Git Bash - the WSL System32 shim is skipped because it
  cannot run Windows toolchains) with ``cmd.exe /d /s /c`` fallback.
* **Timeout handling**: the subprocess is killed (terminate -> wait 5s ->
  kill) and the tool raises ``ToolException("Command timed out after
  {timeout}s")`` - a timed-out command never returns a partial result.
* **Abort handling**: if the agent loop cancels the tool call, the running
  process is killed before ``CancelledError`` propagates (``_ProcHandle``
  publishes the Popen handle from the worker thread to the event loop).
* **Environment filtering**: subprocess env is an allowlist (PATH, HOME,
  USER, LANG, LC_ALL, TERM, COLUMNS, LINES + Windows essentials + the
  explicit ``env`` argument).
* **Permission gating**: under strict policy this tool is gated by
  ``interrupt_before`` (M-13) - the graph pauses for user approval.
* **Output framing**: the JSON payload is wrapped with untrusted-content
  markers (``app/core/security.py``) so command output is never mistaken
  for instructions.

The subprocess runs in ``asyncio.to_thread`` rather than
``asyncio.create_subprocess_exec`` because Windows only supports asyncio
subprocesses on a Proactor loop while uvicorn runs a Selector loop on
Windows (see README); ``_ProcHandle`` restores kill-on-timeout/cancel on
top of the thread.

Usage::

    from app.tools import bash

    await bash.ainvoke({"command": "echo hello"})
    await bash.ainvoke({"command": "ls -la", "timeout": 10, "cwd": "subdir"})
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import platform
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Annotated

from langchain_core.tools import ToolException, tool

from app.core.security import detect_injection, wrap_untrusted
from app.tools._validators import validate_path

logger = logging.getLogger(__name__)

#: Max chars per stream before truncation (BACKLOG5 M-10).
MAX_CHARS_PER_STREAM = 5_000
#: Chars kept at the start / end of an over-long stream.
TRUNCATE_HEAD_CHARS = 2_500
TRUNCATE_TAIL_CHARS = 2_500
#: Threshold for deduplication: >= 100 identical consecutive lines collapse.
DEDUP_THRESHOLD = 100


def _is_wsl_bash(path: str) -> bool:
    """True for the WSL shim (``%SystemRoot%\\System32\\bash.exe``).

    The shim runs commands inside WSL, where Windows toolchains
    (venv python, pytest, npm ...) are not addressable - so for a Windows
    agent it is not a usable shell.
    """
    try:
        resolved = Path(path).resolve()
        system32 = (
            Path(os.environ.get("SystemRoot", "C:\\Windows")) / "System32"
        ).resolve()
    except OSError:
        return False
    return resolved.parent == system32


def _find_windows_bash() -> str | None:
    """Locate a Win32 bash (Git Bash); the WSL shim is excluded.

    Order: next to ``git.exe``, under the standard Git install dirs, then
    whatever ``PATH`` offers. Returns ``None`` when only the WSL shim (or
    no bash at all) is available.
    """
    candidates: list[str] = []
    git = shutil.which("git")
    if git:
        git_dir = Path(git).parent
        candidates.append(str(git_dir / "bash.exe"))  # cmd\bash.exe (rare)
        candidates.append(str(git_dir.parent / "bin" / "bash.exe"))  # Git\bin\bash.exe
    for env_var in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA"):
        base = os.environ.get(env_var)
        if base:
            candidates.append(str(Path(base) / "Git" / "bin" / "bash.exe"))
    path_bash = shutil.which("bash")
    if path_bash:
        candidates.append(path_bash)

    for candidate in candidates:
        if Path(candidate).is_file() and not _is_wsl_bash(candidate):
            return candidate
    return None


def _resolve_shell() -> list[str]:
    """Return shell command and arguments for the current platform.

    POSIX: ``["/bin/bash", "-lc"]``
    Windows: a Win32 bash (Git Bash) as ``[<bash>, "-lc"]`` if found -
    the WSL System32 shim is skipped - else ``["cmd.exe", "/d", "/s", "/c"]``.
    """
    if platform.system() == "Windows":
        win_bash = _find_windows_bash()
        if win_bash:
            return [win_bash, "-lc"]
        return ["cmd.exe", "/d", "/s", "/c"]
    else:
        # POSIX systems: use bash with login shell
        return ["/bin/bash", "-lc"]


def _build_allowlist_env(
    explicit_env: dict[str, str] | None,
) -> dict[str, str]:
    """Build subprocess env from allowlist + explicit env.

    Allowlist: PATH, HOME, USER, LANG, LC_ALL, TERM, COLUMNS, LINES
    Windows additions: SystemRoot, TEMP, TMP, COMSPEC, PATHEXT, USERPROFILE,
                      APPDATA, LOCALAPPDATA, SYSTEMDRIVE, WINDIR
    """
    # Base allowlist (POSIX + Windows essentials)
    allowlist = {
        "PATH": os.environ.get("PATH", ""),
        "HOME": os.environ.get("HOME", os.environ.get("USERPROFILE", "")),
        "USER": os.environ.get("USER", os.environ.get("USERNAME", "")),
        "LANG": os.environ.get("LANG", "C"),
        "LC_ALL": os.environ.get("LC_ALL", ""),
        "TERM": os.environ.get("TERM", "dumb"),
        "COLUMNS": os.environ.get("COLUMNS", "80"),
        "LINES": os.environ.get("LINES", "24"),
        # Windows-specific essentials
        "SystemRoot": os.environ.get("SystemRoot", ""),
        "TEMP": os.environ.get("TEMP", ""),
        "TMP": os.environ.get("TMP", ""),
        "COMSPEC": os.environ.get("COMSPEC", ""),
        "PATHEXT": os.environ.get("PATHEXT", ""),
        "USERPROFILE": os.environ.get("USERPROFILE", ""),
        "APPDATA": os.environ.get("APPDATA", ""),
        "LOCALAPPDATA": os.environ.get("LOCALAPPDATA", ""),
        "SYSTEMDRIVE": os.environ.get("SYSTEMDRIVE", ""),
        "WINDIR": os.environ.get("WINDIR", ""),
    }

    # Remove empty values
    allowlist = {k: v for k, v in allowlist.items() if v}

    # Merge explicit env (takes precedence)
    if explicit_env:
        allowlist.update(explicit_env)

    return allowlist


def _dedup_lines(text: str) -> str:
    """Collapse runs of identical lines: >= 100 identical -> single marker."""
    lines = text.splitlines()
    if len(lines) < DEDUP_THRESHOLD:
        return text

    deduped = []
    i = 0
    while i < len(lines):
        j = i + 1
        while j < len(lines) and lines[j] == lines[i]:
            j += 1

        count = j - i
        if count >= DEDUP_THRESHOLD:
            deduped.append(f"... [{count} identical lines] ...")
        else:
            deduped.extend(lines[i:j])

        i = j

    return "\n".join(deduped)


def _truncate_stream(text: str) -> str:
    """Cut an over-long stream to head + marker + tail (char-based).

    Works on characters so a single huge line (e.g. minified JSON) is cut
    too; the head is trimmed back to the last line boundary when possible.
    """
    if len(text) <= MAX_CHARS_PER_STREAM:
        return text

    head = text[:TRUNCATE_HEAD_CHARS]
    line_break = head.rfind("\n")
    if line_break > 0:
        head = head[:line_break]
    tail = text[-TRUNCATE_TAIL_CHARS:]
    removed = len(text) - len(head) - len(tail)

    return f"{head}\n... [{removed} chars truncated] ...\n{tail}"


def _build_output(
    stdout: str,
    stderr: str,
    exit_code: int,
    duration_ms: float,
    truncated: bool,
    injection_warning: str | None,
) -> str:
    """Build the JSON response and frame it as untrusted content."""
    result: dict[str, object] = {
        "stdout": stdout,
        "stderr": stderr,
        "exit_code": exit_code,
        "duration_ms": duration_ms,
        "truncated": truncated,
    }

    if injection_warning:
        result["injection_warning"] = injection_warning

    return wrap_untrusted(json.dumps(result, ensure_ascii=False))


def _terminate_process(proc: subprocess.Popen[str] | None) -> None:
    """terminate -> wait(5s) -> kill. Safe to call from any thread."""
    if proc is None or proc.poll() is not None:
        return
    try:
        proc.terminate()
        proc.wait(timeout=5)
    except Exception:  # best-effort escalation to kill
        try:
            proc.kill()
            proc.wait(timeout=5)
        except Exception:  # process already gone
            pass


class _ProcHandle:
    """Thread-safe bridge from the worker thread to the event loop.

    The thread registers its ``Popen`` handle here; the event loop then
    terminates the process on timeout or task cancellation even though
    Windows cannot spawn subprocesses on the Selector event loop (see
    module docstring).
    """

    __slots__ = ("_lock", "_proc", "_cancelled")

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._proc: subprocess.Popen[str] | None = None
        self._cancelled = False

    @property
    def cancelled(self) -> bool:
        with self._lock:
            return self._cancelled

    def attach(self, proc: subprocess.Popen[str]) -> None:
        """Register the freshly spawned process, killing it if we lost a race."""
        with self._lock:
            self._proc = proc
            cancelled = self._cancelled
        if cancelled:
            _terminate_process(proc)

    def cancel(self) -> None:
        """Mark the handle cancelled and kill the process if it is running."""
        with self._lock:
            self._cancelled = True
            proc = self._proc
        _terminate_process(proc)


async def _execute_subprocess(
    command: str,
    shell: list[str],
    timeout: float,
    cwd: Path | None,
    env: dict[str, str],
    handle: _ProcHandle,
) -> tuple[str, str, int, float]:
    """Execute command in a worker thread; return stdout, stderr, exit_code, ms.

    Raises ``TimeoutError`` when the command exceeded ``timeout`` (the
    process is killed first); ``CancelledError`` from the awaiting task
    propagates untouched so ``bash()`` can kill the process.
    """
    start_time = time.monotonic()

    if shell[0] == "cmd.exe":
        cmd_args = shell + [f'"{command}"']
    else:
        cmd_args = shell + [command]

    try:
        # Run in worker thread to avoid blocking event loop
        stdout, stderr, returncode = await asyncio.to_thread(
            _run_sync_subprocess,
            cmd_args,
            timeout,
            cwd,
            env,
            handle,
        )
    except TimeoutError:
        raise
    except Exception as exc:  # e.g. executable not found -> JSON error result
        duration_ms = (time.monotonic() - start_time) * 1000
        return "", str(exc), 1, duration_ms

    duration_ms = (time.monotonic() - start_time) * 1000
    return stdout, stderr, returncode, duration_ms


def _run_sync_subprocess(
    cmd_args: list[str],
    timeout: float,
    cwd: Path | None,
    env: dict[str, str],
    handle: _ProcHandle,
) -> tuple[str, str, int]:
    """Synchronous subprocess execution (runs in a worker thread).

    Returns ``(stdout, stderr, returncode)``.
    """
    if handle.cancelled:
        # Cancelled before we spawned anything - the task never reads this.
        return "", "", -1

    proc = subprocess.Popen(
        cmd_args,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=str(cwd) if cwd else None,
        env=env,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    handle.attach(proc)

    try:
        stdout, stderr = proc.communicate(timeout=timeout)
        return stdout, stderr, proc.returncode or 0
    except subprocess.TimeoutExpired:
        _terminate_process(proc)
        raise TimeoutError(f"Command timed out after {timeout}s")


@tool
async def bash(
    command: Annotated[
        str,
        "Shell command to execute (POSIX syntax on POSIX, Windows cmd syntax on Windows).",
    ],
    timeout: Annotated[
        float,
        "Maximum execution time in seconds (default: 30, max: 600).",
    ] = 30.0,
    cwd: Annotated[
        str | None,
        "Working directory (relative to workspace, or inside ~/.orya). If None, uses current working directory.",
    ] = None,
    env: Annotated[
        dict[str, str] | None,
        "Additional environment variables to set (merged with allowlist).",
    ] = None,
) -> str:
    """Execute a shell command and return structured JSON output.

    Use timeout to prevent long-running commands (a timeout kills the
    process and raises an error instead of returning partial output).
    cwd changes the working directory for the command only. env adds
    extra variables to the subprocess environment (filtered by security
    policy). Output is JSON with stdout, stderr, exit code, duration and
    truncation flag; over-long output is truncated and repeated lines are
    deduplicated to keep the tool result token-efficient.
    """
    # Validate timeout
    if timeout <= 0:
        raise ToolException("timeout must be > 0")
    if timeout > 600:
        raise ToolException("timeout must be <= 600")

    # Validate and resolve cwd
    resolved_cwd = None
    if cwd:
        resolved_cwd = validate_path(cwd)

    # Build subprocess environment
    subprocess_env = _build_allowlist_env(env)

    # Resolve shell for platform
    shell = _resolve_shell()

    # Execute command; kill the process on timeout / task cancellation
    handle = _ProcHandle()
    try:
        stdout, stderr, exit_code, duration_ms = await _execute_subprocess(
            command,
            shell,
            timeout,
            resolved_cwd,
            subprocess_env,
            handle,
        )
    except TimeoutError:
        raise ToolException(f"Command timed out after {timeout}s")
    except asyncio.CancelledError:
        handle.cancel()
        raise

    # truncation flag reflects the raw output size (before dedup/truncate)
    truncated = len(stdout) > MAX_CHARS_PER_STREAM or len(stderr) > MAX_CHARS_PER_STREAM

    # Token-efficient processing: dedup repeated lines, then cut over-long text
    processed_stdout = _truncate_stream(_dedup_lines(stdout))
    processed_stderr = _truncate_stream(_dedup_lines(stderr))

    # Injection detection runs on the raw output so a pattern is never
    # lost inside a truncated region
    pattern = detect_injection(stdout) or detect_injection(stderr)
    injection_warning = (
        f"WARNING: possible prompt injection detected in [{pattern}]"
        if pattern
        else None
    )

    return _build_output(
        processed_stdout,
        processed_stderr,
        exit_code,
        duration_ms,
        truncated,
        injection_warning,
    )
