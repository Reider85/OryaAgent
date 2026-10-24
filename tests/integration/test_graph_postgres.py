"""Integration tests for M-04 — agent-loop on the real PostgresSaver checkpointer.

Requires infrastructure::

    make db-up && make db-migrate
"""

from __future__ import annotations

import asyncio
import selectors
import sys
import uuid

import asyncpg
import pytest
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.tools import tool

from app.core.config import get_settings
from app.core.graph import build_graph, default_run_config, resume_command
from app.core.permissions import Decision
from app.db import apply_migrations, close_pool, get_asyncpg_pool
from app.db.checkpoints import close_checkpointer, get_checkpointer


@tool
def echo(text: str) -> str:
    """Echo the given text back to the caller."""
    return f"echo: {text}"


class AskPolicy:
    """Ask-mode policy: the human node interrupts before the tools node."""

    def check(self, tool_call) -> Decision:
        return Decision("ask", "test policy")

    def record_session_allow(self, tool_name: str) -> None:
        return None


async def _database_reachable() -> bool:
    try:
        conn = await asyncio.wait_for(
            asyncpg.connect(get_settings().database_url), timeout=2.0
        )
    except (OSError, TimeoutError, asyncpg.PostgresError):
        return False
    await conn.close()
    return True


def test_graph_checkpoints_in_postgres():
    """The agent-loop persists its state in Postgres and can resume there."""

    async def scenario() -> None:
        if not await _database_reachable():
            pytest.skip("PostgreSQL not reachable — run `make db-up` first")
        pool = await get_asyncpg_pool()
        thread_id = f"m04-{uuid.uuid4().hex[:8]}"
        try:
            await apply_migrations(pool)
            checkpointer = await get_checkpointer()
            model = FakeMessagesListChatModel(
                responses=[
                    AIMessage(
                        content="",
                        tool_calls=[
                            {
                                "name": "echo",
                                "args": {"text": "hi"},
                                "id": "call_1",
                            }
                        ],
                    ),
                    AIMessage(content="done"),
                ]
            )
            graph = build_graph([echo], model, checkpointer, AskPolicy())
            config = default_run_config(thread_id)

            await graph.ainvoke({"messages": [HumanMessage("hi")]}, config)

            state = await graph.aget_state(config)
            assert state.next == ("human",)

            result = await graph.ainvoke(resume_command("approve"), config)
            assert result["messages"][-1].content == "done"

            rows = await pool.fetch(
                "SELECT thread_id FROM checkpoints WHERE thread_id = $1", thread_id
            )
            assert rows, "no checkpoint written to postgres"
        finally:
            await close_checkpointer()
            await close_pool()

    if sys.platform == "win32":
        # psycopg cannot use the ProactorEventLoop of pytest-asyncio.
        loop = asyncio.SelectorEventLoop(selectors.SelectSelector())
        try:
            loop.run_until_complete(scenario())
        finally:
            loop.close()
    else:
        asyncio.run(scenario())
