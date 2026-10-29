"""Shared rg subprocess seam for grep/glob (M-11, split MVP-POLISH-8).

Contracts (PROMPT_MVP M-11, BACKLOG4/5 M-11)::

    grep(pattern, glob=None, path=".", type=None, max_matches=500) -> str
    glob(pattern, path=".", max_matches=500) -> str

Behaviour shared by both tools:

* **ripgrep only** (Forbidden pattern): no ``re``-based scanning, no
  ``glob.glob`` - both tools shell out to ``rg`` (fast, .gitignore-aware).
  ``--no-config`` keeps output deterministic regardless of ~/.ripgreprc.
* **Untrusted framing (M-22)**: the JSON payload is wrapped with
  ``[UNTRUSTED_CONTENT_START/END]`` markers; matched line content is data,
  never instructions.
* **Cache seam (M-21)**: results with at least one match are cached via
  ``app.core.cache`` keyed by ``sha256(args + max-mtime-of-matched-files)``
  - editing any matched file changes the key; empty results are not cached.
  The rg search itself always runs (its result feeds the invalidation key);
  pre-search caching needs a different key design and stays out of M-21
  scope. A hit is marked ``from_cache`` (ToolMessage metadata) when the
  call comes through the ToolNode. Grep/glob entries span many files, so
  they rely on the mtime key + TTL for invalidation (the eager per-path
  idx hook covers single-file ``read`` results).
* **Timeout / abort**: a watchdog kills rg after ``RG_TIMEOUT`` seconds; a
  truncated search kills rg early and still returns the collected matches.
* **rg exit codes**: 0 = matches, 1 = no matches (empty result, not an
  error), 2 = error (bad regex / bad --type) -> ToolException with stderr.

Subprocess runs in ``asyncio.to_thread`` so the agent-loop's event loop is
never blocked (PROMPT_MVP 9).

Usage::

    from app.tools import grep, glob

    await grep.ainvoke({"pattern": "def main", "glob": "*.py"})
    await glob.ainvoke({"pattern": "*.py", "path": "app"})
"""

from __future__ import annotations

import asyncio
import json
import logging
import shutil
import subprocess
import threading
from pathlib import Path

from langchain_core.tools import ToolException

from app.core.security import wrap_untrusted

logger = logging.getLogger(__name__)

#: Hard wall-clock limit for one rg invocation.
RG_TIMEOUT = 30.0

#: Matches/files per call (BACKLOG5 M-11; PROMPT_MVP's 50 superseded).
DEFAULT_MAX_MATCHES = 500


def _run_rg_sync(
    argv: list[str],
    timeout: float,
    max_events: int,
    mode: str,
) -> tuple[list[str], bool, int, str]:
    """Run rg; collect up to ``max_events`` output lines (worker thread).

    ``mode="match"`` keeps only ``{"type": "match"}`` JSON events (grep);
    ``mode="line"`` keeps every stdout line (glob --files). Returns
    ``(lines, truncated, exit_code, stderr)``.
    """
    if shutil.which("rg") is None:
        raise ToolException(
            "ripgrep (rg) not found in PATH - install ripgrep "
            "(https://github.com/BurntSushi/ripgrep) or add it to PATH"
        )

    proc = subprocess.Popen(  # noqa: S603 - argv list, no shell
        argv,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )

    timed_out = threading.Event()
    timer = threading.Timer(timeout, lambda: (timed_out.set(), proc.kill()))
    timer.daemon = True
    timer.start()

    collected: list[str] = []
    truncated = False
    try:
        assert proc.stdout is not None
        for raw in proc.stdout:
            line = raw.strip()
            if not line:
                continue
            if mode == "match":
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if event.get("type") != "match":
                    continue
            collected.append(line)
            if len(collected) > max_events:
                truncated = True
                proc.kill()
                break
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)
        stderr = proc.stderr.read() if proc.stderr is not None else ""
        if timed_out.is_set():
            raise ToolException(f"rg timed out after {timeout}s")
        return collected, truncated, proc.returncode, stderr
    finally:
        timer.cancel()
        if proc.poll() is None:
            proc.kill()


async def _run_rg(
    argv: list[str],
    timeout: float,
    max_events: int,
    mode: str,
) -> tuple[list[str], bool, int, str]:
    """Async seam over :func:`_run_rg_sync` (mocked in unit tests)."""
    return await asyncio.to_thread(_run_rg_sync, argv, timeout, max_events, mode)


async def _max_mtime_ns(files: list[str]) -> int:
    """Latest mtime over ``files`` - the cache invalidation hook (M-21)."""

    def _scan() -> int:
        latest = 0
        for name in files:
            try:
                latest = max(latest, Path(name).stat().st_mtime_ns)
            except OSError:
                continue
        return latest

    return await asyncio.to_thread(_scan)


def _render(payload: dict) -> str:
    """Serialize + frame the JSON payload with untrusted markers (M-22)."""
    return wrap_untrusted(json.dumps(payload, ensure_ascii=False))
