"""Integration tests for M-20 — /sessions endpoints on real PostgreSQL.

Start infrastructure first::

    make db-up && make db-migrate

Exercises the HTTP layer end-to-end (``httpx.ASGITransport`` against the
FastAPI app) with the real ``sessions``/``messages`` tables: create →
list (pagination) → message turn (typed log round-trip) → resume (409,
nothing pending) → soft-delete. The LLM layer is fake (canned
``astream_events``) and the checkpointer is in-memory — this ticket is
about persistence + routing, not model behaviour.

Runs on its own SelectorEventLoop on win32 (asyncpg pool + parity with
the psycopg constraint documented in ``tests/integration/test_db_postgres.py``).
"""

from __future__ import annotations

import asyncio
import selectors
import sys
import uuid
from typing import Any

import asyncpg
import httpx
import pytest
from langchain_core.messages import AIMessageChunk

import app.api.sessions as api_sessions
from app.core.config import get_settings


class _FakeState:
    def __init__(self, next: tuple = (), values: dict[str, Any] | None = None) -> None:
        self.next = next
        self.values = values if values is not None else {"messages": []}
        self.tasks = ()


class _FakeGraph:
    """Minimal graph: streams one token chunk, state always finished."""

    async def astream_events(self, input, config=None, *, version=None):
        yield {
            "event": "on_chat_model_stream",
            "run_id": "run-1",
            "data": {"chunk": AIMessageChunk(content="api answer")},
        }

    async def aget_state(self, config):
        return _FakeState()


async def _database_reachable() -> bool:
    try:
        conn = await asyncio.wait_for(
            asyncpg.connect(get_settings().database_url), timeout=2.0
        )
    except (OSError, TimeoutError, asyncpg.PostgresError):
        return False
    await conn.close()
    return True


def test_api_sessions_roundtrip(monkeypatch: pytest.MonkeyPatch) -> None:
    """create → list → messages → get → resume → delete over real HTTP."""

    async def scenario() -> None:
        from app.db import apply_migrations, close_pool, get_asyncpg_pool
        from app.main import app

        if not await _database_reachable():
            pytest.skip("PostgreSQL not reachable — run `make db-up` first")
        pool = await get_asyncpg_pool()
        await apply_migrations(pool)

        # Fake LLM layer: in-memory checkpointer + canned turn.
        async def _memory_checkpointer():
            from langgraph.checkpoint.memory import MemorySaver

            return MemorySaver(), True

        monkeypatch.setattr(api_sessions, "resolve_checkpointer", _memory_checkpointer)
        monkeypatch.setattr(
            api_sessions,
            "build_session_graph",
            lambda *a, **k: _FakeGraph(),
        )
        monkeypatch.setattr(api_sessions, "_session_policies", {})

        transport = httpx.ASGITransport(app=app)
        session_id: str | None = None
        async with httpx.AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as client:
            # POST /sessions — server-side uuid
            response = await client.post("/sessions", json={"title": "m20 it"})
            assert response.status_code == 200
            data = response.json()
            session_id = data["session_id"]
            assert data["status"] == "active"

            # GET /sessions — pagination envelope, fresh session visible
            response = await client.get("/sessions?page=1&size=5")
            assert response.status_code == 200
            listing = response.json()
            assert listing["page"] == 1 and listing["size"] == 5
            assert listing["total"] >= 1
            assert session_id in {item["session_id"] for item in listing["items"]}

            # POST /messages — full turn, assistant reply logged (M-14)
            response = await client.post(
                f"/sessions/{session_id}/messages", json={"content": "ping"}
            )
            assert response.status_code == 200
            turn = response.json()
            assert turn["status"] == "ok"
            assert turn["reply"] == "api answer"
            assert turn["tool_steps"] == []

            # GET /sessions/{id} — metadata + typed messages round-trip
            response = await client.get(f"/sessions/{session_id}")
            assert response.status_code == 200
            detail = response.json()
            assert detail["title"] == "m20 it"
            roles = [m["role"] for m in detail["messages"]]
            contents = [m["content"] for m in detail["messages"]]
            assert roles == ["user", "assistant"]
            assert contents == ["ping", "api answer"]

            # POST /resume — no interrupt pending for a finished run
            response = await client.post(
                f"/sessions/{session_id}/resume", json={"decision": "allow"}
            )
            assert response.status_code == 409

            # DELETE — soft-delete keeps the row, flips status
            response = await client.delete(f"/sessions/{session_id}")
            assert response.status_code == 200
            assert response.json() == {"session_id": session_id, "status": "closed"}

            row = await pool.fetchrow(
                "SELECT status FROM sessions WHERE session_id = $1", session_id
            )
            assert row is not None and row["status"] == "closed"

            # History survives the soft-delete (audit)
            response = await client.get(f"/sessions/{session_id}")
            assert response.status_code == 200
            assert response.json()["status"] == "closed"

            # Unknown id — 404 across the read/write surface
            missing = f"m20-{uuid.uuid4().hex[:8]}"
            assert (await client.get(f"/sessions/{missing}")).status_code == 404
            assert (await client.delete(f"/sessions/{missing}")).status_code == 404

        # Cleanup (rows cascade to messages)
        await pool.execute("DELETE FROM sessions WHERE session_id = $1", session_id)
        await close_pool()

    if sys.platform == "win32":
        loop = asyncio.SelectorEventLoop(selectors.SelectSelector())
        try:
            loop.run_until_complete(scenario())
        finally:
            loop.close()
    else:
        asyncio.run(scenario())
