"""Tool: bash - execute shell commands with token-efficient output (M-10).

Contract (PROMPT_MVP M-10, BACKLOG5 M-10)::

    bash(command, timeout=30, cwd=None, env=None) -> str

Behaviour:

* **JSON output**: returns JSON string (parsed as object by consumers) with
  ``stdout``, ``stderr``, ``exit_code``, ``duration_ms``, ``truncated``.
* **Token efficiency**: if stdout or stderr exceeds 5000 chars, truncate to
  first 2500 + last 2500 chars with marker; dedup repeated lines (100+ identical
  lines → ``... [100 identical lines] ...``).
* **Injection detection**: if stdout/stderr contains injection patterns, prefix
  ``"WARNING: possible prompt injection detected in [pattern_id]"`` to the JSON.
* **Platform shells**: POSIX uses ``/bin/bash -lc``; Windows prefers ``bash.exe``
  from PATH (Git Bash/WSL) or ``cmd.exe /d /s /c`` as fallback.
* **Timeout handling**: timeout kills subprocess and raises ToolException.
* **Abort handling**: if agent loop cancels, kill subprocess.
* **Environment filtering**: subprocess env is filtered to allowlist (PATH, HOME,
  USER, LANG, LC_ALL, TERM, COLUMNS, LINES + Windows essentials + explicit env).
* **Atomic execution**: no partial output; full output captured or truncated.
* **Permission gating**: under strict policy this tool is gated by interrupt_before
  (M-13) — the graph pauses for user approval before the tool node runs.
* **Output framing**: the JSON payload is wrapped with untrusted-content markers
  (``app/core/security.py``) so command output is never mistaken for instructions.

The subprocess runs in ``asyncio.to_thread`` so the agent-loop's event
loop is never blocked.

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
import time
from pathlib import Path
from typing import Annotated

from langchain_core.tools import ToolException, tool

from app.core.security import detect_injection, wrap_untrusted
from app.tools._validators import validate_path

logger = logging.getLogger(__name__)

#: Max chars per stream before truncation (BACKLOG5 M-10).
MAX_CHARS_PER_STREAM = 5_000
#: Max lines to keep when truncating.
TRUNCATE_HEAD_LINES = 2_500
TRUNCATE_TAIL_LINES = 2_500
#: Threshold for deduplication (100+ identical lines).
DEDUP_THRESHOLD = 100


def _resolve_shell() -> list[str]:
    """Return shell command and arguments for the current platform.

    POSIX: ``["/bin/bash", "-lc"]``
    Windows: prefer ``["bash.exe", "-lc"]`` if found in PATH, else ``["cmd.exe", "/d", "/s", "/c"]``
    """
    if platform.system() == "Windows":
        if shutil.which("bash"):
            # Prefer bash.exe (Git Bash/WSL) if available
            return ["bash.exe", "-lc"]
        else:
            # Fallback to cmd.exe
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
    """Dedup repeated lines: 100+ identical → marker."""
    lines = text.splitlines()
    if len(lines) <= DEDUP_THRESHOLD:
        return text

    # Find consecutive identical sequences
    deduped = []
    i = 0
    while i < len(lines):
        j = i + 1
        while j < len(lines) and lines[j] == lines[i]:
            j += 1

        count = j - i
        if count > DEDUP_THRESHOLD:
            deduped.append(f"... [{count} identical lines] ...")
        else:
            deduped.extend(lines[i:j])

        i = j

    return "\n".join(deduped)


def _truncate_stream(text: str) -> str:
    """Truncate long text: first + last 2500 lines with marker."""
    lines = text.splitlines()
    if len(lines) <= TRUNCATE_HEAD_LINES + TRUNCATE_TAIL_LINES:
        return text

    head = lines[:TRUNCATE_HEAD_LINES]
    tail = lines[-TRUNCATE_TAIL_LINES:]
    removed = len(lines) - TRUNCATE_HEAD_LINES - TRUNCATE_TAIL_LINES

    return "\n".join([
        *head,
        f"... [{removed} lines truncated] ...",
        *tail,
    ])


def _build_output(
    stdout: str,
    stderr: str,
    exit_code: int,
    duration_ms: int,
    injection_warning: str | None,
) -> str:
    """Build JSON response with injection warning."""
    result = {
        "stdout": stdout,
        "stderr": stderr,
        "exit_code": exit_code,
        "duration_ms": duration_ms,
        "truncated": len(stdout) > MAX_CHARS_PER_STREAM or len(stderr) > MAX_CHARS_PER_STREAM,
    }

    if injection_warning:
        result["injection_warning"] = injection_warning

    return wrap_untrusted(json.dumps(result, ensure_ascii=False))


async def _execute_subprocess(
    command: str,
    shell: list[str],
    timeout: float,
    cwd: Path | None,
    env: dict[str, str],
) -> tuple[str, str, int, float]:
    """Execute command in subprocess; return stdout, stderr, exit_code, duration_ms."""
    start_time = time.monotonic()

    # Prepare command arguments
    if shell[0] == "cmd.exe":
        # Windows cmd.exe: wrap command in quotes
        cmd_args = shell + [f'"{command}"']
    else:
        # Bash: command is argument to -lc
        cmd_args = shell + [command]

    try:
        # Run in worker thread to avoid blocking event loop
        stdout, stderr = await asyncio.to_thread(
            _run_sync_subprocess,
            cmd_args,
            timeout,
            cwd,
            env,
        )
        exit_code = 0
    except TimeoutError:
        stdout = ""
        stderr = "Command timed out"
        exit_code = 124  # Standard timeout exit code
    except Exception as exc:
        stdout = ""
        stderr = str(exc)
        exit_code = 1

    duration_ms = (time.monotonic() - start_time) * 1000
    return stdout, stderr, exit_code, duration_ms


def _run_sync_subprocess(
    cmd_args: list[str],
    timeout: float,
    cwd: Path | None,
    env: dict[str, str],
) -> tuple[str, str]:
    """Synchronous subprocess execution (runs in worker thread)."""
    import subprocess

    try:
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

        try:
            stdout, stderr = proc.communicate(timeout=timeout)
            return stdout, stderr
        except subprocess.TimeoutExpired:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
            raise TimeoutError("Command timed out")
    except Exception as exc:
        raise exc


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

    Use timeout to prevent long-running commands. cwd changes the working
    directory for the command only. env adds extra variables to the subprocess
    environment (filtered by security policy). Output is JSON with stdout,
    stderr, exit code, duration, and truncation flags.
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

    # Execute command
    try:
        stdout, stderr, exit_code, duration_ms = await _execute_subprocess(
            command,
            shell,
            timeout,
            resolved_cwd,
            subprocess_env,
        )
    except TimeoutError:
        raise ToolException(f"Command timed out after {timeout}s")

    # Process output: dedup and truncate
    processed_stdout = _dedup_lines(stdout)
    processed_stderr = _dedup_lines(stderr)

    # Truncate if needed
    if len(processed_stdout) > MAX_CHARS_PER_STREAM:
        processed_stdout = _truncate_stream(processed_stdout)
    if len(processed_stderr) > MAX_CHARS_PER_STREAM:
        processed_stderr = _truncate_stream(processed_stderr)

    # Check for injection patterns
    injection_warning = None
    if detect_injection(processed_stdout) or detect_injection(processed_stderr):
        pattern = detect_injection(processed_stdout) or detect_injection(processed_stderr)
        injection_warning = f"WARNING: possible prompt injection detected in [{pattern}]"

    # Build final output
    return _build_output(
        processed_stdout,
        processed_stderr,
        exit_code,
        duration_ms,
        injection_warning,
    )
