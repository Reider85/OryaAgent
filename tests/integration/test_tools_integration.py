"""Integration tests for M-12 — tool-registry integration.

Cross-module contract: ``get_tools()`` (app/core/tools.py) x the
agent-loop (``build_graph``, M-04) x the LLM seam (``get_llm``, M-01).
No infrastructure required:

* the full-cycle test drives every registered tool through the graph
  with a scripted fake model (BACKLOG4 M-12 AC: agent -> tools -> agent);
* the bind test constructs a real chat model via the ``get_llm`` seam
  (construction is network-free) and binds the whole registry, verifying
  the OpenAI function schemas the model would receive.
"""

from __future__ import annotations

import importlib
import json
import os
from pathlib import Path

import pytest
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import BaseTool
from langchain_core.utils.function_calling import convert_to_openai_function

from app.core.cache import MemoryCache, set_cache
from app.core.config import clear_settings_cache
from app.core.graph import build_graph
from app.core.llm import get_llm
from app.core.security import (
    UNTRUSTED_CONTENT_END,
    UNTRUSTED_CONTENT_START,
)
from app.core.tools import get_tools

# The package re-exports the tool objects under the same names, so the
# modules themselves are loaded via importlib (MVP-POLISH-8 split).
glob_module = importlib.import_module("app.tools.glob")
grep_module = importlib.import_module("app.tools.grep")

EXPECTED_NAMES = ["read", "write", "edit", "bash", "grep", "glob"]

EXPECTED_REQUIRED_ARGS = {
    "read": {"path"},
    "write": {"path", "content"},
    "edit": {"path", "old_string", "new_string"},
    "bash": {"command"},
    "grep": {"pattern"},
    "glob": {"pattern"},
}


@pytest.fixture(autouse=True)
def _isolated_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Sandbox: no inherited ORYA_* env, fresh settings/cache, cwd in tmp."""
    for name in list(os.environ):
        if name.startswith("ORYA_"):
            monkeypatch.delenv(name, raising=False)
    monkeypatch.chdir(tmp_path)
    clear_settings_cache()
    set_cache(MemoryCache())
    yield
    set_cache(None)
    clear_settings_cache()


def _unwrap(result: str) -> str:
    """Strip the untrusted-content markers every tool wraps its output in."""
    content = result.strip()
    if content.startswith(UNTRUSTED_CONTENT_START):
        content = content[len(UNTRUSTED_CONTENT_START) :].strip()
    if content.endswith(UNTRUSTED_CONTENT_END):
        content = content[: -len(UNTRUSTED_CONTENT_END)].strip()
    return content


def _tool_call(name: str, args: dict, call_id: str) -> AIMessage:
    return AIMessage(
        content="",
        tool_calls=[{"name": name, "args": args, "id": call_id}],
    )


# --- registry contract -------------------------------------------------------


def test_get_tools_returns_full_registry_in_order():
    tools = get_tools("session-1")

    assert [t.name for t in tools] == EXPECTED_NAMES
    assert all(isinstance(t, BaseTool) for t in tools)


def test_registry_tools_have_descriptions_and_input_schemas():
    for tool in get_tools():
        assert tool.description and tool.description.strip(), tool.name
        args = tool.args
        assert args, f"{tool.name} exposes no input schema"
        assert all(isinstance(spec, dict) for spec in args.values()), tool.name


def test_every_registered_tool_declares_required_args():
    """Each tool serializes to a valid OpenAI function schema (M-23/M-12)."""
    for tool in get_tools():
        fn = convert_to_openai_function(tool)
        assert fn["name"] == tool.name
        assert fn["description"]
        required = set(fn["parameters"].get("required") or [])
        assert required == EXPECTED_REQUIRED_ARGS[tool.name], tool.name
        assert fn["parameters"]["properties"]


# --- full agent -> tools -> agent cycle (BACKLOG4 M-12 AC) -------------------


def _rg_match_event(file: str, line: int, text: str) -> str:
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


def _fake_rg(match_events: list[str], files: list[str]):
    """Replace the rg subprocess seam; mode-aware (grep vs glob)."""

    async def fake(argv, timeout, max_events, mode):  # noqa: ANN001
        if mode == "match":
            return list(match_events), False, 0, ""
        return list(files), False, 0, ""

    return fake


async def test_graph_runs_full_cycle_over_registered_tools(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """One conversation exercising write -> read -> edit -> bash -> grep -> glob."""
    fake_seam = _fake_rg(
        [_rg_match_event("cycle.txt", 2, "gamma")],
        ["cycle.txt"],
    )
    monkeypatch.setattr(grep_module, "_run_rg", fake_seam)
    monkeypatch.setattr(glob_module, "_run_rg", fake_seam)
    model = FakeMessagesListChatModel(
        responses=[
            _tool_call(
                "write", {"path": "cycle.txt", "content": "alpha\nbeta\n"}, "c1"
            ),
            _tool_call("read", {"path": "cycle.txt"}, "c2"),
            _tool_call(
                "edit",
                {
                    "path": "cycle.txt",
                    "old_string": "beta",
                    "new_string": "gamma",
                },
                "c3",
            ),
            _tool_call("bash", {"command": "echo 'from graph'"}, "c4"),
            _tool_call("grep", {"pattern": "gamma"}, "c5"),
            _tool_call("glob", {"pattern": "*.txt"}, "c6"),
            AIMessage(content="done"),
        ]
    )
    graph = build_graph(get_tools(), model)

    result = await graph.ainvoke({"messages": [HumanMessage(content="do the cycle")]})

    messages = result["messages"]
    tool_messages = [m for m in messages if isinstance(m, ToolMessage)]
    assert [m.name for m in tool_messages] == [
        "write",
        "read",
        "edit",
        "bash",
        "grep",
        "glob",
    ]
    assert messages[-1].content == "done"

    # write created the file; read saw the pre-edit content
    assert (tmp_path / "cycle.txt").read_text(encoding="utf-8") == "alpha\ngamma\n"
    read_output = _unwrap(tool_messages[1].content)
    assert "1\talpha" in read_output
    assert "2\tbeta" in read_output

    # bash returned structured JSON output
    bash_output = json.loads(_unwrap(tool_messages[3].content))
    assert bash_output["stdout"] == "from graph\n"
    assert bash_output["exit_code"] == 0

    # grep/glob returned structured JSON payloads
    grep_payload = json.loads(_unwrap(tool_messages[4].content))
    assert grep_payload["matches"][0]["content"] == "gamma"
    glob_payload = json.loads(_unwrap(tool_messages[5].content))
    assert glob_payload["files"] == ["cycle.txt"]


# --- real model bound to the registry (offline) ------------------------------


def test_real_llm_seam_binds_full_registry_offline():
    """``get_llm()`` construction is network-free; bind carries all 6 tools."""
    model = get_llm("deepseek", "deepseek-chat", api_key="sk-offline-test")
    tools = get_tools()

    bound = model.bind_tools(tools)

    assert bound is not model
    bound_names = [schema["function"]["name"] for schema in bound.kwargs["tools"]]
    assert bound_names == EXPECTED_NAMES

    # the graph builds with the real bound model (never invoked here)
    graph = build_graph(tools, model)
    assert graph is not None
