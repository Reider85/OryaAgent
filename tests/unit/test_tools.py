"""Tool tests: read (M-07) and write (M-08) - pagination, validation, cache seam, atomic write, graph e2e."""

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
from app.tools import read, write
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


def test_get_tools_returns_read_and_write():
    tools = get_tools("session-1")

    assert [t.name for t in tools] == ["read", "write"]


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
    assert [t.name for t in model.bound] == ["read", "write"]


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


# --- write (M-08) ------------------------------------------------------------


async def test_write_creates_new_file(tmp_path: Path):
    result = await write.ainvoke({"path": "new.txt", "content": "hello"})

    assert (tmp_path / "new.txt").read_text(encoding="utf-8") == "hello"
    assert result.startswith("Wrote 5 bytes to ")
    assert str(tmp_path / "new.txt") in result


async def test_write_overwrites_existing_file(tmp_path: Path):
    target = _write(tmp_path / "a.txt", "old content")

    result = await write.ainvoke({"path": str(target), "content": "new"})

    assert target.read_text(encoding="utf-8") == "new"
    assert result.startswith("Wrote 3 bytes to ")


async def test_write_empty_content(tmp_path: Path):
    result = await write.ainvoke({"path": "empty.txt", "content": ""})

    assert (tmp_path / "empty.txt").read_text(encoding="utf-8") == ""
    assert result.startswith("Wrote 0 bytes to ")


async def test_write_counts_utf8_bytes(tmp_path: Path):
    result = await write.ainvoke({"path": "u.txt", "content": "привет"})

    assert result.startswith("Wrote 12 bytes to ")


async def test_write_creates_parent_dirs_by_default(tmp_path: Path):
    await write.ainvoke({"path": "sub/dir/file.txt", "content": "nested"})

    assert (tmp_path / "sub" / "dir" / "file.txt").read_text(encoding="utf-8") == (
        "nested"
    )


async def test_write_create_dirs_false_missing_parent_raises(tmp_path: Path):
    with pytest.raises(ToolException, match="Parent directory does not exist"):
        await write.ainvoke(
            {"path": "missing/file.txt", "content": "x", "create_dirs": False}
        )

    assert not (tmp_path / "missing").exists()


async def test_write_path_outside_roots_raises(tmp_path: Path):
    outside = tmp_path.parent / "outside-write.txt"

    try:
        with pytest.raises(ToolException, match="outside allowed roots"):
            await write.ainvoke({"path": str(outside), "content": "x"})
    finally:
        outside.unlink(missing_ok=True)

    assert not outside.exists()


async def test_write_path_traversal_escape_raises():
    with pytest.raises(ToolException, match="outside allowed roots"):
        await write.ainvoke({"path": "../escape.txt", "content": "x"})


async def test_write_directory_target_raises(tmp_path: Path):
    (tmp_path / "adir").mkdir()

    with pytest.raises(ToolException, match="is a directory"):
        await write.ainvoke({"path": "adir", "content": "x"})


async def test_write_is_atomic_via_replace(tmp_path: Path, monkeypatch):
    import os as os_module

    calls: list[tuple[Path, Path]] = []
    real_replace = os_module.replace

    def spy(src, dst):  # noqa: ANN001, ANN202
        calls.append((Path(src), Path(dst)))
        return real_replace(src, dst)

    monkeypatch.setattr(os_module, "replace", spy)
    target = tmp_path / "atomic.txt"

    result = await write.ainvoke({"path": str(target), "content": "atomic"})

    assert "Wrote 6 bytes to " in result
    assert len(calls) == 1
    tmp_src, dst = calls[0]
    assert dst == target
    assert tmp_src.parent == target.parent  # same directory -> same filesystem
    assert not tmp_src.exists()  # replaced, no leftover temp file
    assert target.read_text(encoding="utf-8") == "atomic"


async def test_write_cleans_up_temp_on_failure(tmp_path: Path, monkeypatch):
    import os as os_module

    def boom(src, dst):  # noqa: ANN001, ANN202
        raise OSError("disk full")

    monkeypatch.setattr(os_module, "replace", boom)

    with pytest.raises(ToolException, match="Cannot write"):
        await write.ainvoke({"path": "f.txt", "content": "x"})

    assert not any(tmp_path.iterdir())


async def test_write_result_is_not_cached(tmp_path: Path):
    cache = get_cache()
    assert isinstance(cache, MemoryCache)

    await write.ainvoke({"path": "nocache.txt", "content": "x"})

    assert cache.hits == 0
    assert cache.misses == 0


async def test_write_then_read_returns_new_content(tmp_path: Path):
    target = _write(tmp_path / "cached.txt", "old version")

    first = await read.ainvoke({"path": str(target)})
    await write.ainvoke({"path": str(target), "content": "new version"})
    second = await read.ainvoke({"path": str(target)})

    assert "old version" in first
    assert "new version" in second


async def test_graph_executes_write_tool_end_to_end(tmp_path: Path):
    model = FakeMessagesListChatModel(
        responses=[
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "write",
                        "args": {"path": "graph-out.txt", "content": "from graph"},
                        "id": "call_w1",
                    }
                ],
            ),
            AIMessage(content="done"),
        ]
    )
    graph = build_graph(get_tools(), model)

    result = await graph.ainvoke({"messages": [HumanMessage(content="write it")]})

    tool_messages = [m for m in result["messages"] if isinstance(m, ToolMessage)]
    assert len(tool_messages) == 1
    assert "Wrote 10 bytes to " in tool_messages[0].content
    assert (tmp_path / "graph-out.txt").read_text(encoding="utf-8") == "from graph"
