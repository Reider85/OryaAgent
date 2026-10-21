"""Tool: read tests (M-07) - pagination, validation, cache seam, graph e2e."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import ToolException

from app.core.cache import MemoryCache, get_cache, set_cache
from app.core.config import clear_settings_cache
from app.core.graph import build_graph
from app.core.security import (
    UNTRUSTED_CONTENT_END,
    UNTRUSTED_CONTENT_START,
)
from app.core.tools import get_tools
from app.tools import read
from app.tools.read import DEFAULT_MAX_LINES


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


def _write(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


def _numbered_file(path: Path, lines: int, prefix: str = "line") -> Path:
    return _write(path, "\n".join(f"{prefix}{i}" for i in range(1, lines + 1)))


# --- basic reading ----------------------------------------------------------


async def test_read_returns_line_numbered_content(tmp_path: Path):
    target = _write(tmp_path / "a.txt", "first\nsecond\nthird")

    result = await read.ainvoke({"path": str(target)})

    assert "1\tfirst" in result
    assert "2\tsecond" in result
    assert "3\tthird" in result


async def test_read_wraps_content_in_untrusted_markers(tmp_path: Path):
    target = _write(tmp_path / "a.txt", "hello")

    result = await read.ainvoke({"path": str(target)})

    assert result.startswith(UNTRUSTED_CONTENT_START)
    assert result.endswith(UNTRUSTED_CONTENT_END)


async def test_read_empty_file_returns_markers_only(tmp_path: Path):
    target = _write(tmp_path / "empty.txt", "")

    result = await read.ainvoke({"path": str(target)})

    assert UNTRUSTED_CONTENT_START in result
    assert UNTRUSTED_CONTENT_END in result


async def test_read_relative_path_resolves_from_cwd(tmp_path: Path):
    _write(tmp_path / "rel.txt", "relative content")

    result = await read.ainvoke({"path": "rel.txt"})

    assert "relative content" in result


# --- pagination --------------------------------------------------------------


async def test_read_pagination_window(tmp_path: Path):
    target = _numbered_file(tmp_path / "many.txt", 20)

    result = await read.ainvoke({"path": str(target), "start_line": 10, "end_line": 14})

    for line_no in range(10, 15):
        assert f"line{line_no}" in result
    assert "line9" not in result
    assert "line15" not in result
    # explicit end_line: the note tells the model more content exists
    assert "[truncated: lines 15-20 hidden" in result


async def test_read_default_window_truncates_with_note(tmp_path: Path):
    total = DEFAULT_MAX_LINES + 10
    target = _numbered_file(tmp_path / "big.txt", total)

    result = await read.ainvoke({"path": str(target)})

    assert f"line{DEFAULT_MAX_LINES}" in result
    assert f"line{total}" not in result
    assert f"[truncated: lines {DEFAULT_MAX_LINES + 1}-{total} hidden" in result
    assert f"start_line={DEFAULT_MAX_LINES + 1}" in result


async def test_read_start_line_beyond_eof_reports_total(tmp_path: Path):
    target = _numbered_file(tmp_path / "small.txt", 3)

    result = await read.ainvoke({"path": str(target), "start_line": 99})

    assert "beyond EOF" in result
    assert "3 lines" in result


@pytest.mark.parametrize(
    ("start_line", "end_line"),
    [(0, None), (-5, None), (10, 5)],
)
async def test_read_invalid_range_raises(
    tmp_path: Path, start_line: int, end_line: int | None
):
    target = _write(tmp_path / "a.txt", "x")
    args: dict = {"path": str(target), "start_line": start_line}
    if end_line is not None:
        args["end_line"] = end_line

    with pytest.raises(ToolException):
        await read.ainvoke(args)


# --- path validation ---------------------------------------------------------


async def test_read_path_outside_roots_raises(tmp_path: Path):
    outside = tmp_path.parent / "outside-secret.txt"
    outside.write_text("secret", encoding="utf-8")

    try:
        with pytest.raises(ToolException, match="outside allowed roots"):
            await read.ainvoke({"path": str(outside)})
    finally:
        outside.unlink(missing_ok=True)


async def test_read_path_traversal_escape_raises(tmp_path: Path):
    with pytest.raises(ToolException, match="outside allowed roots"):
        await read.ainvoke({"path": "../escape.txt"})


async def test_read_missing_file_raises(tmp_path: Path):
    with pytest.raises(ToolException, match="File not found"):
        await read.ainvoke({"path": "does-not-exist.txt"})


async def test_read_directory_raises(tmp_path: Path):
    (tmp_path / "adir").mkdir()

    with pytest.raises(ToolException, match="Not a file"):
        await read.ainvoke({"path": "adir"})


# --- binary / size limits ----------------------------------------------------


async def test_read_binary_file_returns_size_message(tmp_path: Path):
    target = tmp_path / "blob.bin"
    target.write_bytes(b"\x00\x01\x02binary")

    result = await read.ainvoke({"path": str(target)})

    assert result == "Binary file, 9 bytes"
    assert UNTRUSTED_CONTENT_START not in result


async def test_read_too_large_file_raises(tmp_path: Path, monkeypatch):
    import importlib

    read_module = importlib.import_module("app.tools.read")
    monkeypatch.setattr(read_module, "MAX_FILE_SIZE_BYTES", 10)
    target = _write(tmp_path / "huge.txt", "x" * 50)

    with pytest.raises(ToolException, match="File too large"):
        await read.ainvoke({"path": str(target)})


# --- cache seam (M-21 contract) ----------------------------------------------


async def test_read_caches_result_and_hits_on_second_call(tmp_path: Path):
    target = _write(tmp_path / "a.txt", "cached content")
    cache = get_cache()
    assert isinstance(cache, MemoryCache)

    first = await read.ainvoke({"path": str(target)})
    second = await read.ainvoke({"path": str(target)})

    assert first == second
    assert cache.hits == 1
    assert cache.misses == 1


async def test_read_cache_key_changes_on_mtime_change(tmp_path: Path):
    target = _write(tmp_path / "a.txt", "version one")
    cache = get_cache()
    assert isinstance(cache, MemoryCache)

    first = await read.ainvoke({"path": str(target)})
    _write(target, "version two")
    os.utime(target, ns=(2_000_000_000, 2_000_000_000))
    second = await read.ainvoke({"path": str(target)})

    assert "version one" in first
    assert "version two" in second
    assert cache.hits == 0
    assert cache.misses == 2


async def test_read_pagination_uses_separate_cache_entries(tmp_path: Path):
    target = _numbered_file(tmp_path / "many.txt", 10)
    cache = get_cache()
    assert isinstance(cache, MemoryCache)

    await read.ainvoke({"path": str(target), "start_line": 1, "end_line": 5})
    await read.ainvoke({"path": str(target), "start_line": 6, "end_line": 10})
    await read.ainvoke({"path": str(target), "start_line": 1, "end_line": 5})

    assert cache.hits == 1
    assert cache.misses == 2


# --- tool registry + graph wiring (partial M-12) -----------------------------


def test_get_tools_returns_read():
    tools = get_tools("session-1")

    assert len(tools) == 1
    assert tools[0].name == "read"


def test_build_graph_binds_tools_when_supported():
    class RecordingModel(FakeMessagesListChatModel):
        bound: list | None = None

        def bind_tools(self, tools, **kwargs):  # noqa: ANN001, ANN003
            self.bound = list(tools)
            return self

    model = RecordingModel(
        responses=[AIMessage(content="ok")],
    )

    build_graph(get_tools(), model)

    assert model.bound is not None
    assert [t.name for t in model.bound] == ["read"]


def test_build_graph_falls_back_without_bind_tools():
    model = FakeMessagesListChatModel(responses=[AIMessage(content="ok")])

    graph = build_graph(get_tools(), model)

    assert graph is not None


async def test_graph_executes_read_tool_end_to_end(tmp_path: Path):
    target = _write(tmp_path / "sample.txt", "hello from graph")
    model = FakeMessagesListChatModel(
        responses=[
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "read",
                        "args": {"path": str(target)},
                        "id": "call_1",
                    }
                ],
            ),
            AIMessage(content="done"),
        ]
    )
    graph = build_graph(get_tools(), model)

    result = await graph.ainvoke({"messages": [HumanMessage(content="read it")]})

    tool_messages = [m for m in result["messages"] if isinstance(m, ToolMessage)]
    assert len(tool_messages) == 1
    assert "hello from graph" in tool_messages[0].content
    assert UNTRUSTED_CONTENT_START in tool_messages[0].content
