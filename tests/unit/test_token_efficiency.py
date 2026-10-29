"""M-23 token-efficient output: compact-output contract + >=30% token savings.

BACKLOG5 M-23 acceptance criteria:

1. every tool returns compact structured output (six-tool contract);
2. token-count comparison before/after saves >= 30% on typical tool-results.

"Before" = the output without the M-23 mechanisms (raw bash streams, raw
``rg --json`` match events per BACKLOG4 M-11, uncapped path listings,
full-file reads); "after" = the shipped tool result (JSON + dedup +
truncation + caps + untrusted framing). Token counts go through
``count_tokens(..., model=None)`` - deterministic chars/4, no network.
"""

from __future__ import annotations

import importlib
import json
import os
import re
from pathlib import Path

import pytest
from langchain_core.messages import HumanMessage

from app.core.cache import MemoryCache, set_cache
from app.core.config import clear_settings_cache
from app.core.context import count_tokens
from app.core.security import UNTRUSTED_CONTENT_END, UNTRUSTED_CONTENT_START
from app.tools import bash, edit, glob, grep, read, write

#: BACKLOG5 M-23: typical tool-results must save at least 30% of tokens.
MIN_SAVINGS = 0.30


@pytest.fixture(autouse=True)
def _isolated_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Sandbox: no inherited ORYA_* env, fresh settings, cwd in tmp_path."""
    for name in list(os.environ):
        if name.startswith("ORYA_"):
            monkeypatch.delenv(name, raising=False)
    monkeypatch.chdir(tmp_path)
    clear_settings_cache()
    set_cache(MemoryCache())
    yield
    set_cache(None)
    clear_settings_cache()


# --- helpers ----------------------------------------------------------------


def _tokens(text: str) -> int:
    """Token count via the project counter (model=None -> chars/4 approx)."""
    return count_tokens([HumanMessage(content=text)], model=None)


def _assert_savings(before: str, after: str, label: str) -> float:
    """Assert ``after`` saves >= MIN_SAVINGS of ``before`` tokens; return %."""
    before_tokens = _tokens(before)
    after_tokens = _tokens(after)
    savings = 1 - after_tokens / before_tokens
    assert savings >= MIN_SAVINGS, (
        f"{label}: {before_tokens} -> {after_tokens} tokens saves "
        f"{savings:.1%} (< {MIN_SAVINGS:.0%})"
    )
    return savings


def _strip_untrusted(result: str) -> str:
    """Drop the M-22 markers around a tool result and return the payload."""
    content = result.strip()
    if content.startswith(UNTRUSTED_CONTENT_START):
        content = content[len(UNTRUSTED_CONTENT_START) :].strip()
    if content.endswith(UNTRUSTED_CONTENT_END):
        content = content[: -len(UNTRUSTED_CONTENT_END)].strip()
    return content


def _mock_bash_output(
    monkeypatch: pytest.MonkeyPatch, stdout: str, stderr: str = ""
) -> None:
    """Replace the subprocess seam; the command itself never runs."""
    module = importlib.import_module("app.tools.bash")

    async def fake(*args):  # noqa: ANN001, ANN202
        return stdout, stderr, 0, 1.0

    monkeypatch.setattr(module, "_execute_subprocess", fake)


def _mock_rg(
    monkeypatch: pytest.MonkeyPatch,
    *,
    matches: list[str] | None = None,
    files: list[str] | None = None,
) -> None:
    """Replace the rg subprocess seam (mode-aware: grep vs glob)."""

    async def fake(argv, timeout, max_events, mode):  # noqa: ANN001, ANN202
        if mode == "match":
            return list(matches or []), False, 0, ""
        return list(files or []), False, 0, ""

    for name in ("app.tools.grep", "app.tools.glob"):
        monkeypatch.setattr(importlib.import_module(name), "_run_rg", fake)


def _rg_event(file: str, line: int, text: str) -> str:
    """Raw ``rg --json`` match event - the pre-M-23 grep baseline."""
    return json.dumps(
        {
            "type": "match",
            "data": {
                "path": {"text": file},
                "line_number": line,
                "lines": {"text": text + "\n"},
            },
        }
    )


# Typical fixtures (deterministic, cross-platform) ---------------------------


def _repetitive_stdout() -> str:
    return "\n".join(["ERROR: disk usage at 97% on /dev/sda1"] * 500)


def _long_stdout() -> str:
    return "\n".join(
        f"step {i:04d}: compiling module_{i:04d} ............... ok" for i in range(400)
    )


def _grep_match_events(count: int) -> list[str]:
    return [
        _rg_event(
            f"src/package_{i // 100:02d}/module_{i:04d}.py",
            i % 500 + 1,
            f"def handler_{i:04d}(payload): return process(payload, {i})",
        )
        for i in range(count)
    ]


def _glob_paths(count: int) -> list[str]:
    return [f"src/package_{i // 100:02d}/module_{i:04d}.py" for i in range(count)]


def _big_file(path: Path, lines: int = 5_000) -> Path:
    path.write_text(
        "\n".join(
            f"def function_{i:04d}(value): return value + {i}" for i in range(lines)
        ),
        encoding="utf-8",
    )
    return path


# --- AC1: every tool returns compact structured output ----------------------


async def test_write_returns_compact_byte_confirmation(tmp_path: Path):
    result = await write.ainvoke(
        {"path": str(tmp_path / "note.txt"), "content": "hello"}
    )

    assert re.fullmatch(r"Wrote \d+ bytes to .+", result), result


async def test_edit_returns_compact_replacement_confirmation(tmp_path: Path):
    target = tmp_path / "note.txt"
    target.write_text("hello world", encoding="utf-8")

    result = await edit.ainvoke(
        {"path": str(target), "old_string": "world", "new_string": "there"}
    )

    assert re.fullmatch(r"Edited .+: replaced \d+ occurrence\(s\)", result), result


async def test_read_returns_line_numbered_untrusted_window(tmp_path: Path):
    target = tmp_path / "small.txt"
    target.write_text("first\nsecond\nthird", encoding="utf-8")

    result = await read.ainvoke({"path": str(target)})

    assert result.startswith(UNTRUSTED_CONTENT_START)
    assert result.endswith(UNTRUSTED_CONTENT_END)
    assert "1\tfirst" in result
    assert "3\tthird" in result


async def test_bash_returns_exact_structured_document(
    monkeypatch: pytest.MonkeyPatch,
):
    _mock_bash_output(monkeypatch, "hello\n", "warn\n")

    payload = json.loads(_strip_untrusted(await bash.ainvoke({"command": "echo hi"})))

    assert set(payload) == {
        "stdout",
        "stderr",
        "exit_code",
        "duration_ms",
        "truncated",
    }
    assert payload["stdout"] == "hello\n"
    assert payload["stderr"] == "warn\n"
    assert payload["exit_code"] == 0
    assert payload["truncated"] is False
    assert isinstance(payload["duration_ms"], float)


async def test_grep_returns_compact_match_objects(
    monkeypatch: pytest.MonkeyPatch,
):
    _mock_rg(monkeypatch, matches=[_rg_event("src/main.py", 42, "def foo():")])

    payload = json.loads(_strip_untrusted(await grep.ainvoke({"pattern": "def foo"})))

    assert set(payload) == {"matches", "count", "truncated"}
    assert set(payload["matches"][0]) == {"file", "line", "content"}
    assert payload["count"] == 1
    assert payload["truncated"] is False


async def test_glob_returns_compact_file_list(monkeypatch: pytest.MonkeyPatch):
    _mock_rg(monkeypatch, files=["a.py", "b.py"])

    payload = json.loads(_strip_untrusted(await glob.ainvoke({"pattern": "*.py"})))

    assert set(payload) == {"files", "count", "truncated"}
    assert payload["files"] == ["a.py", "b.py"]
    assert payload["count"] == 2
    assert payload["truncated"] is False


# --- AC2: token-count before/after saves >= 30% -----------------------------


async def test_bash_repetitive_output_saves_tokens(
    monkeypatch: pytest.MonkeyPatch,
):
    raw = _repetitive_stdout()
    _mock_bash_output(monkeypatch, raw)

    result = await bash.ainvoke({"command": "ignored"})

    _assert_savings(raw, result, "bash repetitive log")
    payload = json.loads(_strip_untrusted(result))
    assert payload["truncated"] is True  # raw stream exceeded the char cap
    assert "... [500 identical lines] ..." in payload["stdout"]


async def test_bash_long_output_saves_tokens(monkeypatch: pytest.MonkeyPatch):
    raw = _long_stdout()
    _mock_bash_output(monkeypatch, raw)

    result = await bash.ainvoke({"command": "ignored"})

    _assert_savings(raw, result, "bash long log")
    payload = json.loads(_strip_untrusted(result))
    assert payload["truncated"] is True
    assert "chars truncated" in payload["stdout"]


async def test_grep_over_cap_saves_tokens(monkeypatch: pytest.MonkeyPatch):
    events = _grep_match_events(2_000)
    _mock_rg(monkeypatch, matches=events)

    result = await grep.ainvoke({"pattern": "def handler"})

    _assert_savings("\n".join(events), result, "grep 2000 matches")
    payload = json.loads(_strip_untrusted(result))
    assert payload["count"] == 500
    assert payload["truncated"] is True


async def test_glob_over_cap_saves_tokens(monkeypatch: pytest.MonkeyPatch):
    paths = _glob_paths(2_000)
    _mock_rg(monkeypatch, files=paths)

    result = await glob.ainvoke({"pattern": "*.py"})

    _assert_savings("\n".join(paths), result, "glob 2000 paths")
    payload = json.loads(_strip_untrusted(result))
    assert payload["count"] == 500
    assert payload["truncated"] is True


async def test_read_large_file_saves_tokens(tmp_path: Path):
    target = _big_file(tmp_path / "big.py")
    raw = target.read_text(encoding="utf-8")

    result = await read.ainvoke({"path": str(target)})

    _assert_savings(raw, result, "read 5000-line file")
    assert "[truncated: lines 2001-5000 hidden" in result


async def test_aggregate_typical_results_save_at_least_30_percent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    pairs: list[tuple[str, str]] = []

    raw = _repetitive_stdout()
    _mock_bash_output(monkeypatch, raw)
    pairs.append((raw, await bash.ainvoke({"command": "ignored"})))

    raw = _long_stdout()
    _mock_bash_output(monkeypatch, raw)
    pairs.append((raw, await bash.ainvoke({"command": "ignored"})))

    events = _grep_match_events(2_000)
    _mock_rg(monkeypatch, matches=events)
    pairs.append(("\n".join(events), await grep.ainvoke({"pattern": "def handler"})))

    paths = _glob_paths(2_000)
    _mock_rg(monkeypatch, files=paths)
    pairs.append(("\n".join(paths), await glob.ainvoke({"pattern": "*.py"})))

    target = _big_file(tmp_path / "big.py")
    raw = target.read_text(encoding="utf-8")
    pairs.append((raw, await read.ainvoke({"path": str(target)})))

    before = sum(_tokens(b) for b, _ in pairs)
    after = sum(_tokens(a) for _, a in pairs)
    savings = 1 - after / before
    assert savings >= MIN_SAVINGS, (
        f"aggregate: {before} -> {after} tokens saves {savings:.1%} "
        f"(< {MIN_SAVINGS:.0%})"
    )
