"""Unit tests for M-21 — cache seam: MemoryCache, Redis CacheWrapper, stats."""

from __future__ import annotations

import os
import time as time_module
import types
from pathlib import Path

import pytest
from langchain_core.messages import ToolMessage

from app.core import cache as cache_module
from app.core.cache import (
    CacheWrapper,
    MemoryCache,
    build_cache_key,
    close_cache,
    from_cache_result,
    get_cache,
    get_cache_stats,
    init_cache,
    set_cache,
)
from app.core.config import clear_settings_cache
from app.hooks.cache_invalidation import invalidate_cache_for_path

# Env vars that must never leak from the developer machine / CI into tests.
_MANAGED_ENV_VARS = frozenset(
    {
        "REDIS_URL",
        "CACHE_BACKEND",
        "CACHE_TTL_SECONDS",
        "ORYA_REDIS_URL",
        "ORYA_CACHE_BACKEND",
        "ORYA_CACHE_TTL_SECONDS",
    }
)


@pytest.fixture(autouse=True)
def isolated(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Sandbox: no inherited cache env, no repo .env, fresh settings/backend."""
    for name in list(os.environ):
        if name.startswith("ORYA_") or name in _MANAGED_ENV_VARS:
            monkeypatch.delenv(name, raising=False)
    monkeypatch.chdir(tmp_path)
    clear_settings_cache()
    set_cache(None)
    yield
    set_cache(None)
    clear_settings_cache()


class FakeRedis:
    """Minimal async Redis double: str values, TTL via ``time.monotonic``."""

    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.store: dict[str, tuple[str, float | None]] = {}
        self.sets: dict[str, set[str]] = {}
        self.hashes: dict[str, dict[str, int]] = {}
        self.expire_calls: list[str] = []

    def _check(self) -> None:
        if self.fail:
            raise ConnectionError("redis down")

    async def ping(self) -> bool:
        self._check()
        return True

    async def get(self, key: str) -> str | None:
        self._check()
        entry = self.store.get(key)
        if entry is None:
            return None
        value, expires_at = entry
        if expires_at is not None and time_module.monotonic() >= expires_at:
            del self.store[key]
            return None
        return value

    async def set(self, key: str, value: str, ex: int | None = None) -> bool:
        self._check()
        expires_at = time_module.monotonic() + ex if ex is not None and ex > 0 else None
        self.store[key] = (value, expires_at)
        return True

    async def sadd(self, key: str, *members: str) -> int:
        self._check()
        bucket = self.sets.setdefault(key, set())
        before = len(bucket)
        bucket.update(members)
        return len(bucket) - before

    async def smembers(self, key: str) -> set[str]:
        self._check()
        return set(self.sets.get(key, set()))

    async def expire(self, key: str, seconds: int) -> bool:
        self._check()
        self.expire_calls.append(key)
        if key in self.store:
            value, _ = self.store[key]
            self.store[key] = (value, time_module.monotonic() + seconds)
            return True
        return False

    async def delete(self, *keys: str) -> int:
        self._check()
        removed = 0
        for key in keys:
            removed += int(self.store.pop(key, None) is not None)
            removed += int(self.sets.pop(key, None) is not None)
            removed += int(self.hashes.pop(key, None) is not None)
        return removed

    async def hincrby(self, key: str, field: str, amount: int = 1) -> int:
        self._check()
        bucket = self.hashes.setdefault(key, {})
        bucket[field] = bucket.get(field, 0) + amount
        return bucket[field]


def _key(tool: str = "read", name: str = "a", mtime: int = 1) -> str:
    return build_cache_key(tool, {"path": name}, mtime)


# --- build_cache_key --------------------------------------------------------


def test_build_cache_key_is_stable_and_sensitive():
    base = _key("read", "a.py", 10)
    assert base.startswith("orya:tool_cache:read:")
    assert base == _key("read", "a.py", 10)
    assert base != _key("read", "a.py", 11)  # mtime invalidation
    assert base != _key("read", "b.py", 10)  # args change
    assert base != _key("grep", "a.py", 10)  # tool change


# --- MemoryCache ------------------------------------------------------------


async def test_memory_cache_miss_then_hit_counts():
    cache = MemoryCache()
    key = _key()
    assert await cache.get(key) is None
    assert await cache.set(key, "payload", path="/abs/a.py") is None
    assert await cache.get(key) == "payload"
    assert cache.hits == 1
    assert cache.misses == 1
    assert cache.stats() == {"read": {"hits": 1, "misses": 1}}


async def test_memory_cache_ttl_expiry(monkeypatch: pytest.MonkeyPatch):
    clock = types.SimpleNamespace(now=1000.0)
    monkeypatch.setattr(
        cache_module, "time", types.SimpleNamespace(monotonic=lambda: clock.now)
    )
    cache = MemoryCache(default_ttl=30)
    key = _key()
    await cache.set(key, "v")
    assert await cache.get(key) == "v"
    clock.now += 31
    assert await cache.get(key) is None


async def test_memory_cache_invalidate_drops_only_that_path():
    cache = MemoryCache()
    keep = _key(name="other")
    await cache.set(_key(name="a"), "gone", path="/abs/a")
    await cache.set(keep, "stays", path="/abs/b")
    await cache.set(_key(name="n"), "no-path")

    await cache.invalidate("/abs/a")

    assert await cache.get(_key(name="a")) is None
    assert await cache.get(keep) == "stays"
    assert await cache.get(_key(name="n")) == "no-path"


async def test_memory_cache_clear_resets_entries_and_counters():
    cache = MemoryCache()
    key = _key()
    await cache.get(key)
    await cache.set(key, "v", path="/abs/a")
    cache.clear()
    assert cache.hits == 0 and cache.misses == 0
    assert cache.stats() == {}
    assert await cache.get(key) is None


# --- CacheWrapper (Redis) ----------------------------------------------------


async def test_cache_wrapper_roundtrip_sets_ttl():
    fake = FakeRedis()
    wrapper = CacheWrapper(fake, ttl=120)
    key = _key()
    assert await wrapper.get(key) is None
    await wrapper.set(key, "payload", path="/abs/a.py")

    assert await wrapper.get(key) == "payload"
    _, expires_at = fake.store[key]
    assert expires_at is not None
    assert 0 < expires_at - time_module.monotonic() <= 120
    assert wrapper.stats() == {"read": {"hits": 1, "misses": 1}}


async def test_cache_wrapper_explicit_ttl_overrides_default():
    fake = FakeRedis()
    wrapper = CacheWrapper(fake, ttl=300)
    key = _key()
    await wrapper.set(key, "v", ttl=5)
    _, expires_at = fake.store[key]
    assert 0 < expires_at - time_module.monotonic() <= 5


async def test_cache_wrapper_invalidate_by_path():
    fake = FakeRedis()
    wrapper = CacheWrapper(fake)
    first, second, other = _key(name="a"), _key(name="b"), _key(name="c")
    await wrapper.set(first, "1", path="/abs/a")
    await wrapper.set(second, "2", path="/abs/a")
    await wrapper.set(other, "3", path="/abs/b")

    await wrapper.invalidate("/abs/a")

    assert await wrapper.get(first) is None
    assert await wrapper.get(second) is None
    assert await wrapper.get(other) == "3"
    assert "orya:tool_cache:idx:/abs/a" not in fake.sets
    assert "orya:tool_cache:idx:/abs/b" in fake.sets


async def test_cache_wrapper_mirrors_daily_stats_in_redis():
    fake = FakeRedis()
    wrapper = CacheWrapper(fake)
    key = _key("grep")
    await wrapper.get(key)
    await wrapper.set(key, "v")
    await wrapper.get(key)

    from datetime import date

    stats_key = f"orya:cache_stats:{date.today().isoformat()}:grep"
    assert fake.hashes[stats_key] == {"misses": 1, "hits": 1}


async def test_cache_wrapper_softfails_when_redis_down():
    wrapper = CacheWrapper(FakeRedis(fail=True))
    key = _key()
    assert await wrapper.get(key) is None  # degrade to a miss, no raise
    await wrapper.set(key, "v", path="/abs/a")  # skipped, no raise
    await wrapper.invalidate("/abs/a")  # skipped, no raise
    assert wrapper.stats() == {"read": {"hits": 0, "misses": 1}}


# --- from_cache_result -------------------------------------------------------


def test_from_cache_result_without_call_id_stays_plain_str():
    payload = "same bytes"
    result = from_cache_result(payload, name="read", tool_call_id=None)
    assert result == payload
    assert isinstance(result, str)


def test_from_cache_result_marks_tool_message():
    result = from_cache_result("cached", name="read", tool_call_id="call_1")
    assert isinstance(result, ToolMessage)
    assert result.content == "cached"
    assert result.tool_call_id == "call_1"
    assert getattr(result, "metadata", None) == {"from_cache": True}


# --- hooks -------------------------------------------------------------------


async def test_invalidate_hook_noop_for_backend_without_invalidate():
    class GetSetOnly:
        async def get(self, key: str) -> str | None:
            return None

        async def set(self, key: str, value: str, ttl: float | None = None) -> None:
            return None

    set_cache(GetSetOnly())  # type: ignore[arg-type]
    await invalidate_cache_for_path("/abs/a")  # must not raise


async def test_invalidate_hook_swallows_backend_errors():
    class Broken:
        async def get(self, key: str) -> str | None:
            return None

        async def set(self, key: str, value: str, ttl: float | None = None) -> None:
            return None

        async def invalidate(self, path: str) -> None:
            raise RuntimeError("boom")

    set_cache(Broken())  # type: ignore[arg-type]
    await invalidate_cache_for_path("/abs/a")  # must not raise


async def test_invalidate_hook_reaches_memory_cache():
    cache = MemoryCache()
    set_cache(cache)
    await cache.set(_key(), "v", path="/abs/a")
    await invalidate_cache_for_path("/abs/a")
    assert await cache.get(_key()) is None


# --- init/close + stats aggregation ------------------------------------------


async def test_init_cache_memory_backend_honours_ttl(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("ORYA_CACHE_BACKEND", "memory")
    monkeypatch.setenv("ORYA_CACHE_TTL_SECONDS", "42")
    clear_settings_cache()

    await init_cache(force=True)

    cache = get_cache()
    assert isinstance(cache, MemoryCache)
    assert cache.default_ttl == 42.0


async def test_init_cache_auto_falls_back_when_redis_unreachable(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("ORYA_CACHE_BACKEND", "auto")
    monkeypatch.setenv("ORYA_REDIS_URL", "redis://127.0.0.1:9")
    clear_settings_cache()

    await init_cache(force=True)

    assert isinstance(get_cache(), MemoryCache)


async def test_init_cache_strict_redis_fails_fast_when_unreachable(
    monkeypatch: pytest.MonkeyPatch,
):
    from redis.exceptions import RedisError

    monkeypatch.setenv("ORYA_CACHE_BACKEND", "redis")
    monkeypatch.setenv("ORYA_REDIS_URL", "redis://127.0.0.1:9")
    clear_settings_cache()

    with pytest.raises((RedisError, OSError, TimeoutError)):
        await init_cache(force=True)
    assert isinstance(get_cache(), MemoryCache)  # unchanged fallback state


async def test_init_cache_is_idempotent_until_set_cache_overrides(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("ORYA_CACHE_BACKEND", "auto")
    monkeypatch.setenv("ORYA_REDIS_URL", "redis://127.0.0.1:9")
    clear_settings_cache()

    await init_cache(force=True)  # auto: Redis unreachable in tests -> MemoryCache
    assert isinstance(get_cache(), MemoryCache)

    set_cache(CacheWrapper(FakeRedis()))  # manual override survives re-init
    await init_cache()
    assert isinstance(get_cache(), CacheWrapper)

    set_cache(None)  # manual override clears the init flag again
    await init_cache()
    assert isinstance(get_cache(), MemoryCache)


async def test_close_cache_restores_fresh_memory_backend():
    await init_cache(force=True)
    await close_cache()
    cache = get_cache()
    assert isinstance(cache, MemoryCache)
    assert cache.hits == 0 and cache.misses == 0


async def test_get_cache_stats_shape():
    cache = MemoryCache()
    set_cache(cache)
    key = _key("read")
    await cache.get(key)
    await cache.set(key, "v")
    await cache.get(key)

    stats = get_cache_stats()
    assert stats["backend"] == "MemoryCache"
    assert stats["ttl_seconds"] == cache.default_ttl
    assert stats["tools"]["read"] == {"hits": 1, "misses": 1, "hit_rate": 0.5}
