"""Integration tests for A-01 — RedisRateLimiter on real Redis (skipped when unreachable).

Start infrastructure first::

    make redis-up
"""

from __future__ import annotations

import asyncio
import uuid
from contextlib import suppress

import pytest

from app.core.auth.rate_limit import KEY_PREFIX, REDIS_KEY_TTL_SECONDS, RedisRateLimiter
from app.core.config import get_settings


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
async def limiter():
    if not await _redis_reachable():
        pytest.skip("Redis not reachable — run `make redis-up` first")
    from redis.asyncio import Redis

    client = Redis.from_url(get_settings().redis_url, decode_responses=True)
    yield RedisRateLimiter(client)
    with suppress(Exception):
        await client.aclose()


async def test_hit_counts_and_blocks(limiter: RedisRateLimiter):
    key = f"user:{uuid.uuid4().hex}"

    assert (await limiter.hit(key, 2)).allowed is True
    assert (await limiter.hit(key, 2)).allowed is True
    blocked = await limiter.hit(key, 2)

    assert blocked.allowed is False
    assert blocked.remaining == 0
    assert blocked.retry_after >= 1


async def test_redis_key_shape_and_ttl(limiter: RedisRateLimiter):
    subject = uuid.uuid4().hex
    key = f"user:{subject}"

    await limiter.hit(key, 5)

    redis_keys = [
        k async for k in limiter.redis.scan_iter(match=f"{KEY_PREFIX}:{key}:*")
    ]
    assert len(redis_keys) == 1
    ttl = await limiter.redis.ttl(redis_keys[0])
    assert 0 < ttl <= REDIS_KEY_TTL_SECONDS
    await limiter.redis.delete(*redis_keys)


async def test_buckets_are_isolated(limiter: RedisRateLimiter):
    alice = f"user:{uuid.uuid4().hex}"
    bob = f"user:{uuid.uuid4().hex}"

    assert (await limiter.hit(alice, 1)).allowed is True
    assert (await limiter.hit(alice, 1)).allowed is False
    assert (await limiter.hit(bob, 1)).allowed is True
