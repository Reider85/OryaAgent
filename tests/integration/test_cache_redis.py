"""Integration tests for M-21 — CacheWrapper on real Redis (skipped when unreachable).

Start infrastructure first::

    make redis-up
"""

from __future__ import annotations

import asyncio
import uuid
from contextlib import suppress
from datetime import date
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage, ToolMessage
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.prebuilt import ToolNode

from app.core.cache import (
    CacheWrapper,
    build_cache_key,
    get_cache_stats,
    set_cache,
)
from app.core.config import get_settings
from app.tools import read


def _uniq(prefix: str) -> str:
    """Collision-free cache args: the value keys of this suite live for TTL."""
    return f"{prefix}-{uuid.uuid4().hex}"


async def _redis_reachable() -> bool:
    from redis.asyncio import Redis

    client = Redis.from_url(get_settings().redis_url, decode_responses=True)
    try:
        await asyncio.wait_for(client.ping(), timeout=2.0)
        return True
    except Exception:
        return False
    finally:
        with suppress(Exception):
            await client.aclose()


@pytest.fixture
async def wrapper():
    if not await _redis_reachable():
        pytest.skip("Redis not reachable — run `make redis-up` first")
    from redis.asyncio import Redis

    client = Redis.from_url(get_settings().redis_url, decode_responses=True)
    yield CacheWrapper(client, ttl=300)
    with suppress(Exception):
        await client.aclose()


async def test_roundtrip_sets_ttl(wrapper: CacheWrapper):
    key = build_cache_key("read", {"path": _uniq("roundtrip")}, 1)

    assert await wrapper.get(key) is None
    await wrapper.set(key, "payload", path="/rt/file.txt")
    assert await wrapper.get(key) == "payload"

    ttl = await wrapper.redis.ttl(key)
    assert 0 < ttl <= 300
    await wrapper.invalidate("/rt/file.txt")
    assert await wrapper.get(key) is None


async def test_invalidate_drops_only_that_path(wrapper: CacheWrapper):
    keep = build_cache_key("read", {"path": _uniq("keep")}, 1)
    gone = build_cache_key("read", {"path": _uniq("gone")}, 1)
    await wrapper.set(keep, "stays", path="/abs/keep")
    await wrapper.set(gone, "drops", path="/abs/gone")

    await wrapper.invalidate("/abs/gone")

    assert await wrapper.get(gone) is None
    assert await wrapper.get(keep) == "stays"
    await wrapper.invalidate("/abs/keep")


async def test_stats_counters_and_daily_redis_hash(wrapper: CacheWrapper):
    key = build_cache_key("grep", {"pattern": _uniq("x")}, 1)
    stats_key = f"orya:cache_stats:{date.today().isoformat()}:grep"
    before = await wrapper.redis.hgetall(stats_key)

    await wrapper.get(key)  # miss
    await wrapper.set(key, "v")
    await wrapper.get(key)  # hit

    assert wrapper.stats() == {"grep": {"hits": 1, "misses": 1}}

    # The daily hash is shared across runs - assert deltas, not absolutes.
    mirrored = await wrapper.redis.hgetall(stats_key)
    hits = int(mirrored.get("hits", 0)) - int(before.get("hits", 0))
    misses = int(mirrored.get("misses", 0)) - int(before.get("misses", 0))
    assert (hits, misses) == (1, 1)
    assert await wrapper.redis.ttl(stats_key) > 0


async def test_read_tool_caches_through_redis(
    wrapper: CacheWrapper, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.chdir(tmp_path)
    set_cache(wrapper)
    try:
        (tmp_path / "a.txt").write_text("hello redis", encoding="utf-8")
        first = await read.ainvoke({"path": "a.txt"})
        second = await read.ainvoke({"path": "a.txt"})

        assert first == second
        stats = get_cache_stats()
        assert stats["backend"] == "CacheWrapper"
        assert stats["tools"]["read"] == {"hits": 1, "misses": 1, "hit_rate": 0.5}
    finally:
        set_cache(None)


async def test_graph_cache_hit_marks_from_cache_via_redis(
    wrapper: CacheWrapper, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "b.txt").write_text("graph via redis", encoding="utf-8")
    set_cache(wrapper)
    try:
        graph_state = StateGraph(MessagesState)
        graph_state.add_node("tools", ToolNode([read]))
        graph_state.add_edge(START, "tools")
        graph_state.add_edge("tools", END)
        app = graph_state.compile()

        def _turn(call_id: str) -> dict:
            return {
                "messages": [
                    AIMessage(
                        content="",
                        tool_calls=[
                            {
                                "name": "read",
                                "args": {"path": "b.txt"},
                                "id": call_id,
                                "type": "tool_call",
                            }
                        ],
                    ),
                ]
            }

        first = await app.ainvoke(_turn("r1"))
        second = await app.ainvoke(_turn("r2"))

        first_tool = first["messages"][-1]
        second_tool = second["messages"][-1]
        assert isinstance(first_tool, ToolMessage)
        assert not getattr(first_tool, "metadata", None)
        assert isinstance(second_tool, ToolMessage)
        assert getattr(second_tool, "metadata", None) == {"from_cache": True}
        assert second_tool.tool_call_id == "r2"
    finally:
        set_cache(None)
