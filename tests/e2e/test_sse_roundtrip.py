"""E2E (M-24): FastAPI SSE round trip — stream, interrupt, resume.

Drives the real HTTP layer (``?stream=true``) against a real compiled
graph with a scripted model: no LLM key, no PostgreSQL, no Chainlit
server. This is the acceptance run for BACKLOG5 M-24 — the UI reaches
FastAPI over SSE and the server alone drives LangGraph.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
from langchain_core.tools import tool
from langgraph.checkpoint.memory import MemorySaver

from app.api import sessions as api_sessions
from app.core.config import clear_settings_cache
from app.core.graph import build_graph


@pytest.fixture(autouse=True)
def isolated(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """No inherited env, no repo .env, temp config — no DB/LLM touched."""
    for name in list(os.environ):
        if name.startswith("ORYA_") or name in {"DATABASE_URL", "LOG_LEVEL"}:
            monkeypatch.delenv(name, raising=False)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ORYA_CONFIG_PATH", str(tmp_path / "config.yaml"))
    clear_settings_cache()
    yield
    clear_settings_cache()


def _sse_frames(text: str) -> list[tuple[str, Any]]:
    """Parse an SSE body into ``(event, data)`` frames."""
    frames: list[tuple[str, Any]] = []
    event, data = "message", []
    for line in text.split("\n"):
        line = line.rstrip("\r")
        if line == "":
            if data:
                frames.append((event, json.loads("\n".join(data))))
            event, data = "message", []
            continue
        if line.startswith(":"):
            continue
        if line.startswith("event:"):
            event = line[6:].strip()
        elif line.startswith("data:"):
            data.append(line[5:].lstrip())
    if data:
        frames.append((event, json.loads("\n".join(data))))
    return frames


@tool("bash")
def _fake_bash(command: str) -> str:
    """Scripted stand-in for the real bash tool (no shell involved)."""
    return f"ran: {command}"


@tool("_echo")
def _echo(text: str) -> str:
    """Echo the input text back in upper case."""
    return text.upper()


class _ScriptedModel(BaseChatModel):
    """Requests one tool call, then answers with the tool result."""

    tool_name: str = "_echo"
    tool_args: dict[str, Any] = {}
    calls: int = 0

    @property
    def _llm_type(self) -> str:
        return "orya-scripted-sse"

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        self.calls += 1
        if self.calls == 1:
            message = AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": self.tool_name,
                        "args": dict(self.tool_args),
                        "id": "call-1",
                        "type": "tool_call",
                    }
                ],
            )
        else:
            tool_result = next(
                (
                    str(m.content)
                    for m in reversed(messages)
                    if isinstance(m, ToolMessage)
                ),
                "",
            )
            message = AIMessage(content=f"done: {tool_result}")
        return ChatResult(generations=[ChatGeneration(message=message)])

    def _stream(self, messages, stop=None, run_manager=None, **kwargs):
        result = self._generate(messages, stop=stop, run_manager=run_manager)
        message = result.generations[0].message
        if message.tool_calls:
            call = message.tool_calls[0]
            yield ChatGenerationChunk(
                message=AIMessageChunk(
                    content="",
                    tool_call_chunks=[
                        {
                            "name": call["name"],
                            "args": json.dumps(call["args"]),
                            "id": call["id"],
                            "index": 0,
                            "type": "tool_call_chunk",
                        }
                    ],
                )
            )
        else:
            yield ChatGenerationChunk(message=AIMessageChunk(content=message.content))


class _FailingModel(_ScriptedModel):
    """Raises on every call — exercises the SSE ``error`` frame."""

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        raise RuntimeError("provider exploded")

    def _stream(self, messages, stop=None, run_manager=None, **kwargs):
        if True:  # pragma: no cover - generator body, always raises
            raise RuntimeError("provider exploded")
        yield  # pragma: no cover


@pytest.fixture
def scripted_api(monkeypatch: pytest.MonkeyPatch):
    """Install the API seams for a scripted run; returns the graph builder.

    Usage: ``builder = scripted_api(tools, model)`` — the builder is then
    wired as ``build_session_graph``. One shared ``MemorySaver`` per
    install keeps the interrupt state visible to ``/resume``, and the
    session-log helpers become no-ops so no PostgreSQL is needed.
    """
    state: dict[str, Any] = {"checkpointer": MemorySaver(), "tools": [_echo]}

    async def _resolve():
        return state["checkpointer"], True

    def _build_default(thread_id, _checkpointer, *, model=None, policy=None):
        scripted = _ScriptedModel(tool_name="_echo", tool_args={"text": "orya"})
        return build_graph(state["tools"], scripted, state["checkpointer"], policy)

    async def _noop(*args, **kwargs):
        return None

    async def _session(session_id, *args, **kwargs):
        return {"session_id": session_id, "status": "active"}

    monkeypatch.setattr(api_sessions, "resolve_checkpointer", _resolve)
    monkeypatch.setattr(api_sessions, "build_session_graph", _build_default)
    monkeypatch.setattr(api_sessions, "ensure_session", _noop)
    monkeypatch.setattr(api_sessions, "log_message", _noop)
    monkeypatch.setattr(api_sessions, "get_session", _session)

    def install(tools: list, model_instance: BaseChatModel) -> None:
        """Switch the builder to ``tools`` + ``model_instance`` for this test."""
        state["tools"] = tools

        def _build(thread_id, _checkpointer, *, model=None, policy=None):
            return build_graph(tools, model_instance, state["checkpointer"], policy)

        monkeypatch.setattr(api_sessions, "build_session_graph", _build)

    return install


def test_sse_turn_streams_tokens_and_tool_steps(client, scripted_api) -> None:
    """BACKLOG5 M-24: ``?stream=true`` returns the event sequence."""
    scripted_api([_echo], _ScriptedModel(tool_name="_echo", tool_args={"text": "orya"}))

    response = client.post(
        "/sessions/sse-1/messages",
        params={"stream": "true"},
        json={"content": "echo orya"},
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    frames = _sse_frames(response.text)
    kinds = [kind for kind, _ in frames]
    assert kinds.index("tool_start") < kinds.index("tool_end") < kinds.index("done")

    done = frames[-1][1]
    assert frames[-1][0] == "done"
    assert done["status"] == "ok"
    assert done["reply"] == "done: ORYA"
    assert done["tool_steps"][0]["tool"] == "_echo"
    assert done["tool_steps"][0]["args"] == {"text": "orya"}
    assert done["tool_steps"][0]["output"] == "ORYA"
    assert done["tool_steps"][0]["from_cache"] is False
    assert done["degraded"] is True  # in-memory checkpointer fallback
    assert done["pending_interrupt"] is None


def test_sse_turn_interrupts_then_resumes(client, scripted_api) -> None:
    """M-13 gate over SSE: ``interrupt`` frame → ``/resume`` continuation."""
    scripted_api(
        [_fake_bash],
        _ScriptedModel(tool_name="bash", tool_args={"command": "echo approved"}),
    )

    response = client.post(
        "/sessions/sse-2/messages",
        params={"stream": "true"},
        json={"content": "run it"},
    )

    assert response.status_code == 200
    frames = _sse_frames(response.text)
    kinds = [kind for kind, _ in frames]
    assert "interrupt" in kinds and frames[-1][0] == "done"

    interrupt = next(data for kind, data in frames if kind == "interrupt")
    assert interrupt == {
        "tool": "bash",
        "args": {"command": "echo approved"},
        "reason": interrupt["reason"],
    }
    assert "strict mode" in interrupt["reason"]

    done = frames[-1][1]
    assert done["status"] == "interrupted"
    assert done["pending_interrupt"]["tool"] == "bash"

    # --- answer the gate over the same transport (M-16 via API) -------------
    resumed = client.post(
        "/sessions/sse-2/resume",
        params={"stream": "true"},
        json={"decision": "allow"},
    )

    assert resumed.status_code == 200
    resume_frames = _sse_frames(resumed.text)
    assert resume_frames[-1][0] == "done"
    assert resume_frames[-1][1]["status"] == "ok"
    assert resume_frames[-1][1]["reply"] == "done: ran: echo approved"
    assert any(
        kind == "tool_end" and data["output"] == "ran: echo approved"
        for kind, data in resume_frames
    )


def test_sse_resume_without_pending_is_409(client, scripted_api) -> None:
    scripted_api([_echo], _ScriptedModel(tool_name="_echo", tool_args={"text": "x"}))

    response = client.post(
        "/sessions/sse-3/resume", params={"stream": "true"}, json={"decision": "deny"}
    )

    assert response.status_code == 409


def test_sse_stream_reports_run_failures(client, scripted_api) -> None:
    """A failure after the response started ends with error + done."""
    scripted_api([_echo], _FailingModel(tool_name="_echo", tool_args={"text": "x"}))

    response = client.post(
        "/sessions/sse-4/messages",
        params={"stream": "true"},
        json={"content": "go"},
    )

    assert response.status_code == 200
    frames = _sse_frames(response.text)
    kinds = [kind for kind, _ in frames]
    assert "error" in kinds
    assert frames[-1][0] == "done"
    assert frames[-1][1]["status"] == "error"
    error = next(data for kind, data in frames if kind == "error")
    assert "provider exploded" in error["detail"]


def test_json_turn_still_aggregates(client, scripted_api) -> None:
    """M-20 contract: without the flag the same path answers JSON."""
    scripted_api([_echo], _ScriptedModel(tool_name="_echo", tool_args={"text": "orya"}))

    response = client.post("/sessions/sse-5/messages", json={"content": "echo"})

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["reply"] == "done: ORYA"
    assert data["tool_steps"][0]["from_cache"] is False
    assert data["degraded"] is True
