"""E2E (A-13): cost-aware routing over the real HTTP/SSE layer.

Same harness as ``test_sse_roundtrip``: real FastAPI routes, scripted
model, no LLM key / PostgreSQL. Acceptance: the ``budget`` frame and
payload report an active degrade, a spent budget answers 429, and the
default kill-switch keeps the old behaviour untouched.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
from langchain_core.tools import tool
from langgraph.checkpoint.memory import MemorySaver

from app.api import sessions as api_sessions
from app.core.config import clear_settings_cache
from app.core.cost_tracker import (
    get_cost_store,
    set_cost_identity,
    set_cost_store,
)
from app.core.graph import build_graph
from app.core.llm.cost_router import reset_switch_stats


@pytest.fixture(autouse=True)
def isolated(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """No inherited env, no repo .env, temp config — no DB/LLM touched."""
    for name in list(os.environ):
        if name.startswith("ORYA_") or name in {"DATABASE_URL", "LOG_LEVEL"}:
            monkeypatch.delenv(name, raising=False)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ORYA_CONFIG_PATH", str(tmp_path / "config.yaml"))
    clear_settings_cache()
    set_cost_store(None)
    set_cost_identity(None)
    reset_switch_stats()
    yield
    set_cost_store(None)
    set_cost_identity(None)
    reset_switch_stats()
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


@tool("_echo")
def _echo(text: str) -> str:
    """Echo the input text back in upper case."""
    return text.upper()


class _ScriptedModel(BaseChatModel):
    """Answers immediately — the model identity is irrelevant here."""

    @property
    def _llm_type(self) -> str:
        return "orya-scripted-budget"

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        message = AIMessage(content="ok")
        return ChatResult(generations=[ChatGeneration(message=message)])

    def _stream(self, messages, stop=None, run_manager=None, **kwargs):
        yield ChatGenerationChunk(message=AIMessageChunk(content="ok"))


@pytest.fixture
def scripted_api(monkeypatch: pytest.MonkeyPatch):
    """Install the API seams for a scripted run (no DB, memory checkpointer)."""
    state: dict[str, Any] = {"checkpointer": MemorySaver(), "tools": [_echo]}

    async def _resolve():
        return state["checkpointer"], True

    def _build(thread_id, _checkpointer, *, model=None, provider=None, policy=None):
        return build_graph(
            state["tools"], _ScriptedModel(), state["checkpointer"], policy
        )

    async def _noop(*args, **kwargs):
        return None

    async def _session(session_id, *args, **kwargs):
        return {"session_id": session_id, "status": "active"}

    monkeypatch.setattr(api_sessions, "resolve_checkpointer", _resolve)
    monkeypatch.setattr(api_sessions, "build_session_graph", _build)
    monkeypatch.setattr(api_sessions, "ensure_session", _noop)
    monkeypatch.setattr(api_sessions, "log_message", _noop)
    monkeypatch.setattr(api_sessions, "get_session", _session)


def _enable_router(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ORYA_COST_ROUTER_ENABLED", "true")
    clear_settings_cache()


async def _seed(session_id: str, spend: float, limit: float = 50.0) -> None:
    """Pre-spend ``spend`` USD on the session identity's daily counter."""
    store = get_cost_store()
    await store.set_limit(f"session:{session_id}", limit)
    await store.add_spend(f"session:{session_id}", spend)


def test_sse_budget_frame_emitted_on_degrade(client, scripted_api, monkeypatch) -> None:
    """A-13 AC: >=70% budget → degraded model + ``budget`` SSE frame."""
    _enable_router(monkeypatch)
    import asyncio

    asyncio.run(_seed("budget-1", 40.0))

    response = client.post(
        "/sessions/budget-1/messages",
        params={"stream": "true"},
        json={"content": "go"},
    )

    assert response.status_code == 200
    frames = _sse_frames(response.text)
    kinds = [kind for kind, _ in frames]
    assert "budget" in kinds
    budget = next(data for kind, data in frames if kind == "budget")
    assert budget["degraded"] is True
    assert budget["warning"] is False
    assert budget["model"] == "claude-haiku-3.5"
    assert budget["ratio"] == pytest.approx(0.8)

    done = frames[-1][1]
    assert frames[-1][0] == "done"
    assert done["status"] == "ok"
    assert done["budget"]["degraded"] is True


def test_json_turn_reports_budget_warning(client, scripted_api, monkeypatch) -> None:
    """A-13 AC: >=90% budget → warning in the JSON ``budget`` payload."""
    _enable_router(monkeypatch)
    import asyncio

    asyncio.run(_seed("budget-2", 45.0))

    response = client.post("/sessions/budget-2/messages", json={"content": "go"})

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["budget"]["degraded"] is True
    assert data["budget"]["warning"] is True
    assert data["budget"]["model"] == "claude-haiku-3.5"


def test_spent_budget_is_429(client, scripted_api, monkeypatch) -> None:
    """A-13 AC: >=100% budget → 429 before the turn starts."""
    _enable_router(monkeypatch)
    import asyncio

    asyncio.run(_seed("budget-3", 50.0))

    response = client.post("/sessions/budget-3/messages", json={"content": "go"})

    assert response.status_code == 429
    assert "budget exhausted" in response.json()["detail"]


def test_router_disabled_keeps_old_behaviour(client, scripted_api) -> None:
    """Kill-switch off: no budget frame, no budget payload, turn unaffected."""
    response = client.post(
        "/sessions/budget-4/messages",
        params={"stream": "true"},
        json={"content": "go"},
    )

    assert response.status_code == 200
    frames = _sse_frames(response.text)
    kinds = [kind for kind, _ in frames]
    assert "budget" not in kinds
    assert frames[-1][0] == "done"
    assert "budget" not in frames[-1][1]
