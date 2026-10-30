"""Unit tests for A-01 — rate-limiter seam + middleware (PROMPT_ALPHA §3.1 A-01).

No infra: the Redis backend is exercised through a fake client, the
middleware through the shared session-scoped ``client`` (settings are read
per request, so the autouse ``isolated`` fixture flips
``ORYA_RATE_LIMIT_ENABLED`` safely and a fresh limiter is registered per
test). The protected endpoints are the fs-backed ``GET /memory/stats``
(per-user bucket) and ``POST /sessions/{id}/learn`` (tighter /learn bucket).
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.auth import create_token
from app.core.auth.rate_limit import (
    MemoryRateLimiter,
    RedisRateLimiter,
    close_rate_limiter,
    get_rate_limiter,
    init_rate_limiter,
    set_rate_limiter,
)
from app.core.config import clear_settings_cache, get_settings

_SECRET = "unit-test-secret-0123456789abcdef0123456789abcdef"
_MANAGED_ENV_VARS = frozenset(
    {
        "DATABASE_URL",
        "LOG_LEVEL",
        "REDIS_URL",
        "AUTH_SECRET_KEY",
        "AUTH_ALGORITHM",
        "AUTH_ENABLED",
        "AUTH_TOKEN_TTL_S",
        "AUTH_PUBLIC_PATHS",
        "CORS_ORIGINS",
        "RATE_LIMIT_ENABLED",
        "RATE_LIMIT_RPM",
        "RATE_LIMIT_LEARN_RPM",
        "RATE_LIMIT_BACKEND",
        "RATE_LIMIT_TRUSTED_CLIENTS",
        "ORYA_TRUSTED_CLIENTS",
    }
)


@pytest.fixture(autouse=True)
def isolated(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Sandbox env/config, fresh limiter + settings (A-01 rate-limit tests)."""
    for name in list(os.environ):
        if name.startswith("ORYA_") or name in _MANAGED_ENV_VARS:
            monkeypatch.delenv(name, raising=False)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ORYA_CONFIG_PATH", str(tmp_path / "config.yaml"))
    monkeypatch.setenv("ORYA_MEMORY_DIR", str(tmp_path / "memory"))
    clear_settings_cache()
    set_rate_limiter(None)
    yield
    set_rate_limiter(None)
    clear_settings_cache()


def _enable(monkeypatch: pytest.MonkeyPatch, **env: str) -> None:
    """Turn on enforcement with optional overrides for the next request(s).

    Also freezes the limiter's wall clock (at the real current time, so
    JWT ``iat``/``exp`` still validate) so a test can never straddle a
    fixed-window boundary mid-assertion (counters key off
    ``time.time() // 60``).
    """
    import time as time_module

    import app.core.auth.rate_limit as rl

    real_now = time_module.time()
    monkeypatch.setattr(rl.time, "time", lambda: real_now)
    monkeypatch.setenv("ORYA_RATE_LIMIT_ENABLED", "true")
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    clear_settings_cache()
    set_rate_limiter(None)


class CountingRedis:
    """Minimal async Redis double for the limiter: INCR + EXPIRE."""

    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.values: dict[str, int] = {}
        self.expire_calls: list[str] = []

    def _check(self) -> None:
        if self.fail:
            raise ConnectionError("redis down")

    async def incr(self, key: str) -> int:
        self._check()
        self.values[key] = self.values.get(key, 0) + 1
        return self.values[key]

    async def expire(self, key: str, seconds: int) -> bool:
        self._check()
        self.expire_calls.append(key)
        return True


# --- config --------------------------------------------------------------------


def test_settings_defaults() -> None:
    settings = get_settings()
    assert settings.rate_limit_enabled is False
    assert settings.rate_limit_rpm == 60
    assert settings.rate_limit_learn_rpm == 10
    assert settings.rate_limit_backend == "auto"
    assert settings.rate_limit_trusted_list == []


def test_trusted_clients_csv_and_json(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ORYA_TRUSTED_CLIENTS", "alice, 10.0.0.1")
    clear_settings_cache()
    assert get_settings().rate_limit_trusted_list == ["alice", "10.0.0.1"]

    monkeypatch.setenv("ORYA_TRUSTED_CLIENTS", '["bob", "10.0.0.2"]')
    clear_settings_cache()
    assert get_settings().rate_limit_trusted_list == ["bob", "10.0.0.2"]


# --- MemoryRateLimiter ----------------------------------------------------------


async def test_memory_limiter_allows_up_to_limit() -> None:
    limiter = MemoryRateLimiter()
    for expected_remaining in (1, 0):
        decision = await limiter.hit("user:alice", 2)
        assert decision.allowed is True
        assert decision.remaining == expected_remaining
        assert decision.retry_after == 0


async def test_memory_limiter_blocks_over_limit() -> None:
    limiter = MemoryRateLimiter()
    await limiter.hit("user:alice", 1)
    decision = await limiter.hit("user:alice", 1)
    assert decision.allowed is False
    assert decision.remaining == 0
    assert decision.retry_after >= 1


async def test_memory_limiter_buckets_are_independent() -> None:
    limiter = MemoryRateLimiter()
    assert (await limiter.hit("user:alice", 1)).allowed is True
    assert (await limiter.hit("user:bob", 1)).allowed is True
    assert (await limiter.hit("user:alice", 1)).allowed is False


async def test_memory_limiter_window_rollover(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.core.auth.rate_limit as rl

    clock = {"now": 1_000_000.0}
    monkeypatch.setattr(rl.time, "time", lambda: clock["now"])
    limiter = MemoryRateLimiter()
    assert (await limiter.hit("user:alice", 1)).allowed is True
    assert (await limiter.hit("user:alice", 1)).allowed is False

    clock["now"] += 60.0  # next fixed window
    decision = await limiter.hit("user:alice", 1)
    assert decision.allowed is True
    assert decision.remaining == 0


# --- RedisRateLimiter -----------------------------------------------------------


async def test_redis_limiter_increments_and_stamps_ttl() -> None:
    redis = CountingRedis()
    limiter = RedisRateLimiter(redis)
    first = await limiter.hit("user:alice", 2)
    second = await limiter.hit("user:alice", 2)
    third = await limiter.hit("user:alice", 2)

    assert [first.allowed, second.allowed, third.allowed] == [True, True, False]
    assert third.retry_after >= 1
    assert len(redis.expire_calls) == 1  # TTL stamped on first touch only
    assert all(key.startswith("orya:rate:user:alice:") for key in redis.values)


async def test_redis_limiter_fails_open_on_error() -> None:
    limiter = RedisRateLimiter(CountingRedis(fail=True))
    decision = await limiter.hit("user:alice", 1)
    assert decision.allowed is True


# --- init/close seam ------------------------------------------------------------


async def test_init_disabled_keeps_memory_and_skips_probe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # backend=redis would probe (and fail) if the kill-switch were ignored.
    monkeypatch.setenv("ORYA_RATE_LIMIT_BACKEND", "redis")
    clear_settings_cache()
    await init_rate_limiter(force=True)
    assert isinstance(get_rate_limiter(), MemoryRateLimiter)
    await close_rate_limiter()


async def test_init_memory_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ORYA_RATE_LIMIT_ENABLED", "true")
    monkeypatch.setenv("ORYA_RATE_LIMIT_BACKEND", "memory")
    clear_settings_cache()
    await init_rate_limiter(force=True)
    assert isinstance(get_rate_limiter(), MemoryRateLimiter)
    await close_rate_limiter()


async def test_init_redis_backend_fail_fast(monkeypatch: pytest.MonkeyPatch) -> None:
    from redis.exceptions import RedisError

    monkeypatch.setenv("ORYA_RATE_LIMIT_ENABLED", "true")
    monkeypatch.setenv("ORYA_RATE_LIMIT_BACKEND", "redis")
    monkeypatch.setenv("ORYA_REDIS_URL", "redis://127.0.0.1:1/0")
    clear_settings_cache()
    with pytest.raises((RedisError, OSError, TimeoutError)):
        await init_rate_limiter(force=True)
    await close_rate_limiter()


async def test_init_auto_falls_back_to_memory(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ORYA_RATE_LIMIT_ENABLED", "true")
    monkeypatch.setenv("ORYA_RATE_LIMIT_BACKEND", "auto")
    monkeypatch.setenv("ORYA_REDIS_URL", "redis://127.0.0.1:1/0")
    clear_settings_cache()
    await init_rate_limiter(force=True)
    assert isinstance(get_rate_limiter(), MemoryRateLimiter)
    await close_rate_limiter()


# --- middleware (HTTP) -----------------------------------------------------------


def test_disabled_by_default_never_limits(client: TestClient) -> None:
    # Even rpm=1 would block the 2nd request if the kill-switch were on.
    for _ in range(5):
        assert client.get("/memory/stats").status_code == 200


def test_per_user_429_with_retry_after(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _enable(monkeypatch, ORYA_RATE_LIMIT_RPM="3")
    statuses = [client.get("/memory/stats").status_code for _ in range(4)]
    assert statuses == [200, 200, 200, 429]

    blocked = client.get("/memory/stats")
    assert blocked.headers["retry-after"]
    assert int(blocked.headers["retry-after"]) >= 1
    assert blocked.headers["x-ratelimit-limit"] == "3"
    assert blocked.headers["x-ratelimit-remaining"] == "0"
    assert blocked.json() == {"detail": "rate limit exceeded"}


def test_429_keeps_request_id_header(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Request-id stays outermost: rejections still carry the trace header."""
    _enable(monkeypatch, ORYA_RATE_LIMIT_RPM="0")
    blocked = client.get("/memory/stats")
    assert blocked.status_code == 429
    assert blocked.headers.get("x-request-id")


def test_trusted_clients_bypass(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # TestClient's default scope client host is "testclient".
    _enable(monkeypatch, ORYA_RATE_LIMIT_RPM="1", ORYA_TRUSTED_CLIENTS="testclient")
    for _ in range(4):
        assert client.get("/memory/stats").status_code == 200


def test_public_paths_and_options_exempt(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _enable(monkeypatch, ORYA_RATE_LIMIT_RPM="0")
    assert client.get("/health").status_code == 200
    preflight = client.options(
        "/memory/stats",
        headers={
            "origin": "http://localhost",
            "access-control-request-method": "GET",
        },
    )
    assert preflight.status_code == 200  # CORS layer answers before the limiter
    # Plain OPTIONS is exempt inside the limiter too (405 from the router, not 429).
    assert client.options("/memory/stats").status_code != 429


def test_learn_path_regex_covers_both_routes() -> None:
    from app.api.middleware import _LEARN_PATH

    assert _LEARN_PATH.match("/learn")
    assert _LEARN_PATH.match("/sessions/abc123/learn")
    assert not _LEARN_PATH.match("/memory/stats")
    assert not _LEARN_PATH.match("/sessions/abc123/learn/extra")


def test_learn_endpoints_have_tighter_limit(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _enable(monkeypatch, ORYA_RATE_LIMIT_RPM="60", ORYA_RATE_LIMIT_LEARN_RPM="2")
    body = {"content": "rate-limit learn entry", "category": "fact"}
    statuses = [client.post("/learn", json=body).status_code for _ in range(3)]
    assert statuses == [200, 200, 429]
    # The tight bucket did not consume the general per-user budget.
    assert client.get("/memory/stats").status_code == 200


def test_learn_429_reports_learn_limit(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _enable(monkeypatch, ORYA_RATE_LIMIT_RPM="60", ORYA_RATE_LIMIT_LEARN_RPM="1")
    body = {"content": "rate-limit learn entry", "category": "fact"}
    assert client.post("/learn", json=body).status_code == 200
    blocked = client.post("/learn", json=body)
    assert blocked.status_code == 429
    assert blocked.headers["x-ratelimit-limit"] == "1"


def test_per_user_buckets_via_jwt(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """DoD: per-user — one subject's 429 never starves another (A-01)."""
    monkeypatch.setenv("AUTH_SECRET_KEY", _SECRET)
    _enable(monkeypatch, ORYA_RATE_LIMIT_RPM="2")
    monkeypatch.setenv("AUTH_ENABLED", "true")
    clear_settings_cache()

    alice = {"Authorization": f"Bearer {create_token('alice')}"}
    bob = {"Authorization": f"Bearer {create_token('bob')}"}

    assert [
        client.get("/memory/stats", headers=alice).status_code for _ in range(3)
    ] == [
        200,
        200,
        429,
    ]
    assert client.get("/memory/stats", headers=bob).status_code == 200


def test_dod_60_rpm_per_user(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """DoD: 60 rpm per-user — the 61st request within a minute is rejected."""
    _enable(monkeypatch)  # defaults: rpm=60, learn=10
    statuses = [client.get("/memory/stats").status_code for _ in range(61)]
    assert statuses[:60] == [200] * 60
    assert statuses[60] == 429
