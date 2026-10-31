"""Smoke tests v2 (A-08): +5 scenarios over auth, rate-limit, observability.

PROMPT_ALPHA §3.1 A-08 extends the M-18 canonical-task suite with five
ALPHA-readiness scenarios — each crosses the middleware stack end to end
(HTTP through the shared ``client``) or the observability seam end to end
(graph turn -> span buffer -> ``/health/observability``), still with no
infra: tokens are minted in-process, the rate limiter is the memory
backend with a frozen wall clock, and the model is a scripted fake behind
``wrap_with_tracing`` (Forbidden pattern: no real LLM, no Redis, no
Postgres, no API keys).

1. auth gates the protected endpoints; ``/health`` stays public;
2. the ``orya auth token`` CLI loop mints a JWT that works over HTTP;
3. the per-user rate-limit trips to 429 and never starves another user;
4. ``/learn``'s tighter endpoint bucket trips before the user budget;
5. a scripted turn emits ``llm.call`` + ``agent.permission`` spans and
   the health endpoints reflect the observability state (including the
   unconfigured sampler-proxy and the trace kill-switch).
"""

from __future__ import annotations

import os
import sys
import time as time_module
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage, HumanMessage

import app.core.auth.rate_limit as rl
from app.core.auth import create_token
from app.core.auth.rate_limit import set_rate_limiter
from app.core.config import clear_settings_cache
from app.core.graph import build_graph, default_run_config
from app.core.llm.tracing import wrap_with_tracing
from app.core.observability.spans import (
    clear_span_buffer,
    get_span_buffer,
    set_turn_trace,
)
from app.core.permissions import get_policy
from app.core.tools import get_tools

_SECRET = "smoke-a08-secret-0123456789abcdef0123456789abcdef"
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
def _isolated_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Sandbox: no inherited ORYA_*/auth/rate-limit env, fresh seams, cwd in tmp."""
    for name in list(os.environ):
        if name.startswith("ORYA_") or name in _MANAGED_ENV_VARS:
            monkeypatch.delenv(name, raising=False)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ORYA_CONFIG_PATH", str(tmp_path / "config.yaml"))
    monkeypatch.setenv("ORYA_MEMORY_DIR", str(tmp_path / "memory"))
    clear_settings_cache()
    set_rate_limiter(None)
    clear_span_buffer()
    set_turn_trace(None)
    yield
    set_rate_limiter(None)
    clear_span_buffer()
    set_turn_trace(None)
    clear_settings_cache()


def _enable_auth(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AUTH_SECRET_KEY", _SECRET)
    monkeypatch.setenv("AUTH_ENABLED", "true")
    clear_settings_cache()


def _enable_rate_limit(monkeypatch: pytest.MonkeyPatch, **env: str) -> None:
    """Turn on enforcement and freeze the limiter's wall clock (A-01 pattern)."""
    real_now = time_module.time()
    monkeypatch.setattr(rl.time, "time", lambda: real_now)
    monkeypatch.setenv("ORYA_RATE_LIMIT_ENABLED", "true")
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    clear_settings_cache()
    set_rate_limiter(None)


# --- scenario 1: auth gates protected endpoints, /health stays public -----------


def test_smoke_auth_gates_protected_endpoints(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _enable_auth(monkeypatch)

    missing = client.get("/memory/stats")
    assert missing.status_code == 401
    assert missing.headers["www-authenticate"] == "Bearer"
    assert "missing bearer token" in missing.json()["detail"]

    garbage = client.get("/sessions", headers={"Authorization": "Bearer not-a-jwt"})
    assert garbage.status_code == 401
    assert "invalid or expired" in garbage.json()["detail"]

    authorized = client.get(
        "/memory/stats", headers={"Authorization": f"Bearer {create_token('smoke')}"}
    )
    assert authorized.status_code == 200

    assert client.get("/health").status_code == 200, (
        "health probes must stay public while auth is enforced"
    )


# --- scenario 2: orya auth token CLI -> HTTP -------------------------------------


def test_smoke_cli_token_round_trips_over_http(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("AUTH_SECRET_KEY", _SECRET)
    clear_settings_cache()
    from app.main import main

    monkeypatch.setattr(sys, "argv", ["orya", "auth", "token", "--user", "smoke-cli"])
    main()
    token = capsys.readouterr().out.strip()
    assert token, "the CLI must print exactly the minted JWT"

    _enable_auth(monkeypatch)
    response = client.get("/memory/stats", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200, (
        "an operator-minted CLI token must unlock the protected API"
    )


# --- scenario 3: per-user 429 never starves another user -------------------------


def test_smoke_per_user_rate_limit_spares_other_users(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _enable_auth(monkeypatch)
    _enable_rate_limit(monkeypatch, ORYA_RATE_LIMIT_RPM="2")

    alice = {"Authorization": f"Bearer {create_token('alice')}"}
    bob = {"Authorization": f"Bearer {create_token('bob')}"}

    assert [
        client.get("/memory/stats", headers=alice).status_code for _ in range(3)
    ] == [200, 200, 429]

    blocked = client.get("/memory/stats", headers=alice)
    assert blocked.json() == {"detail": "rate limit exceeded"}
    assert int(blocked.headers["retry-after"]) >= 1
    assert blocked.headers["x-ratelimit-limit"] == "2"
    assert blocked.headers["x-ratelimit-remaining"] == "0"

    assert client.get("/memory/stats", headers=bob).status_code == 200, (
        "one subject's exhausted bucket must not consume another's quota"
    )


# --- scenario 4: /learn tight bucket trips before the user budget -----------------


def test_smoke_learn_bucket_trips_before_user_budget(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _enable_rate_limit(
        monkeypatch, ORYA_RATE_LIMIT_RPM="60", ORYA_RATE_LIMIT_LEARN_RPM="2"
    )
    body = {"content": "smoke-a08 learn entry", "category": "fact"}

    assert [client.post("/learn", json=body).status_code for _ in range(3)] == [
        200,
        200,
        429,
    ]
    assert client.get("/memory/stats").status_code == 200, (
        "the /learn bucket is separate from the general per-user budget"
    )


# --- scenario 5: spans flow buffer -> health, kill-switch cuts the wrap ----------


async def test_smoke_turn_spans_reach_health_endpoints(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    (tmp_path / "README.md").write_text("# smoke\n", encoding="utf-8")
    model = FakeMessagesListChatModel(
        responses=[
            AIMessage(
                content="",
                tool_calls=[
                    {"name": "read", "args": {"path": "README.md"}, "id": "c1"}
                ],
            ),
            AIMessage(content="the README greets the smoke suite"),
        ]
    )
    traced = wrap_with_tracing(model, provider="smoke", model_name="fake-model")
    graph = build_graph(get_tools(), traced)
    result = await graph.ainvoke(
        {"messages": [HumanMessage(content="Read README.md")]},
        default_run_config("smoke-a08-obs"),
    )
    assert result["messages"][-1].content == "the README greets the smoke suite"

    spans = list(get_span_buffer())
    llm_spans = [s for s in spans if s.span_type == "llm.call"]
    assert llm_spans, "the traced seam must record an llm.call span per turn"
    assert llm_spans[0].status == "ok"
    assert llm_spans[0].provider == "smoke"
    assert llm_spans[0].model == "fake-model"

    decision = get_policy(mode="strict").check(
        {"name": "read", "args": {"path": "README.md"}}
    )
    assert decision.action == "allow"
    permission_spans = [
        s for s in get_span_buffer() if s.span_type == "agent.permission"
    ]
    assert permission_spans and permission_spans[0].status == "allow"

    health = client.get("/health/observability")
    assert health.status_code == 200
    payload = health.json()
    assert payload["sdk_enabled"] is True
    assert payload["guardrail_ready"] is True
    assert payload["span_buffer_size"] == len(get_span_buffer()) >= 2

    unconfigured = client.get("/health/sampler-proxy")
    assert unconfigured.status_code == 503, (
        "an unconfigured sampler-proxy must report fail-closed"
    )

    before = len(get_span_buffer())
    monkeypatch.setenv("ORYA_LLM_TRACE_ENABLED", "false")
    clear_settings_cache()
    raw = wrap_with_tracing(model, provider="smoke", model_name="fake-model")
    assert raw is model, "the kill-switch must return the raw adapter"
    await raw.ainvoke([HumanMessage(content="ping")])
    assert len(get_span_buffer()) == before, (
        "with the kill-switch off no new llm.call span may appear"
    )
