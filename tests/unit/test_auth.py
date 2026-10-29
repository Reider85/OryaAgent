"""Unit tests for A-00 — JWT auth, middleware, request-id, CORS (PROMPT_ALPHA §3 A-00).

No infra: tokens are minted in-process, HTTP goes through the shared
session-scoped ``client`` (settings are read per request, so the autouse
``isolated`` fixture flips ``ORYA_AUTH_ENABLED`` on/off safely), and the
protected endpoint is the fs-backed ``GET /memory/stats``.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import jwt as pyjwt
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from starlette.types import Message, Receive, Scope, Send

from app.api.middleware import AuthMiddleware, RequestIdMiddleware, _is_public
from app.core.auth import AuthError, create_token, decode_token
from app.core.config import clear_settings_cache, get_settings, parse_env_list

_SECRET = "unit-test-secret-0123456789abcdef0123456789abcdef"
_MANAGED_ENV_VARS = frozenset(
    {
        "DATABASE_URL",
        "LOG_LEVEL",
        "AUTH_SECRET_KEY",
        "AUTH_ALGORITHM",
        "AUTH_ENABLED",
        "AUTH_TOKEN_TTL_S",
        "AUTH_PUBLIC_PATHS",
        "CORS_ORIGINS",
    }
)


@pytest.fixture(autouse=True)
def isolated(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Sandbox env/config, point the memory dir at tmp_path (A-00 auth tests)."""
    for name in list(os.environ):
        if name.startswith("ORYA_") or name in _MANAGED_ENV_VARS:
            monkeypatch.delenv(name, raising=False)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ORYA_CONFIG_PATH", str(tmp_path / "config.yaml"))
    monkeypatch.setenv("ORYA_MEMORY_DIR", str(tmp_path / "memory"))
    clear_settings_cache()
    yield
    clear_settings_cache()


def _enable_auth(
    monkeypatch: pytest.MonkeyPatch, *, secret: str | None = _SECRET
) -> None:
    """Turn on enforcement for the next request(s)."""
    if secret is not None:
        monkeypatch.setenv("AUTH_SECRET_KEY", secret)
    monkeypatch.setenv("AUTH_ENABLED", "true")
    clear_settings_cache()


# --- config --------------------------------------------------------------------


def test_settings_defaults_auth_off() -> None:
    settings = get_settings()
    assert settings.auth_enabled is False
    assert settings.auth_algorithm == "HS256"
    assert settings.auth_secret_key is None


def test_settings_reject_weak_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AUTH_SECRET_KEY", "short")
    clear_settings_cache()
    with pytest.raises(ValidationError, match="at least 32 characters"):
        get_settings()


def test_settings_auth_requires_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AUTH_ENABLED", "true")
    clear_settings_cache()
    with pytest.raises(ValidationError, match="AUTH_SECRET_KEY"):
        get_settings()


def test_parse_env_list_csv_and_json() -> None:
    assert parse_env_list("/health, /docs ,/metrics") == [
        "/health",
        "/docs",
        "/metrics",
    ]
    assert parse_env_list('["/a", "/b"]') == ["/a", "/b"]
    assert parse_env_list("  ") == []


def test_list_settings_expose_parsed_properties(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CORS_ORIGINS", "http://a.example,http://b.example")
    monkeypatch.setenv("AUTH_PUBLIC_PATHS", "/health,/openapi.json")
    clear_settings_cache()
    settings = get_settings()
    assert settings.cors_origin_list == ["http://a.example", "http://b.example"]
    assert settings.auth_public_path_list == ["/health", "/openapi.json"]


# --- tokens ---------------------------------------------------------------------


def test_token_roundtrip(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AUTH_SECRET_KEY", _SECRET)
    clear_settings_cache()
    token = create_token("alice")
    assert decode_token(token) == "alice"


def test_token_ttl_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AUTH_SECRET_KEY", _SECRET)
    monkeypatch.setenv("AUTH_TOKEN_TTL_S", "60")
    clear_settings_cache()
    claims = pyjwt.decode(create_token("alice"), _SECRET, algorithms=["HS256"])
    assert claims["exp"] - claims["iat"] == 60


def test_create_token_without_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    clear_settings_cache()
    with pytest.raises(AuthError, match="AUTH_SECRET_KEY"):
        create_token("alice")


def test_expired_token_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AUTH_SECRET_KEY", _SECRET)
    clear_settings_cache()
    stale = create_token("alice", ttl_s=-10)
    with pytest.raises(AuthError):
        decode_token(stale)


def test_wrong_secret_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AUTH_SECRET_KEY", _SECRET)
    clear_settings_cache()
    forged = pyjwt.encode(
        {"sub": "alice", "iat": 0, "exp": 4_000_000_000},
        "another-secret-another-secret-abc",
        algorithm="HS256",
    )
    with pytest.raises(AuthError):
        decode_token(forged)


def test_token_without_sub_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AUTH_SECRET_KEY", _SECRET)
    clear_settings_cache()
    no_sub = pyjwt.encode({"iat": 0, "exp": 4_000_000_000}, _SECRET, algorithm="HS256")
    with pytest.raises(AuthError, match="sub"):
        decode_token(no_sub)


# --- AuthMiddleware (ASGI unit) ---------------------------------------------------


async def _drain(_message: Message) -> None:
    return None


async def _receive() -> Message:
    return {"type": "http.request", "body": b"", "more_body": False}


async def test_auth_middleware_sets_state_user_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AUTH_SECRET_KEY", _SECRET)
    monkeypatch.setenv("AUTH_ENABLED", "true")
    clear_settings_cache()
    token = create_token("alice")
    seen: dict[str, object] = {}

    async def inner(scope: Scope, receive: Receive, send: Send) -> None:
        seen.update(scope.get("state", {}))
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    scope: Scope = {
        "type": "http",
        "path": "/sessions",
        "method": "GET",
        "headers": [(b"authorization", b"Bearer " + token.encode("ascii"))],
    }
    await AuthMiddleware(inner)(scope, _receive, _drain)
    assert seen["user_id"] == "alice"


async def test_auth_middleware_bypasses_public_paths(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AUTH_SECRET_KEY", _SECRET)
    monkeypatch.setenv("AUTH_ENABLED", "true")
    clear_settings_cache()
    called = False

    async def inner(scope: Scope, receive: Receive, send: Send) -> None:
        nonlocal called
        called = True

    scope: Scope = {"type": "http", "path": "/health", "method": "GET"}
    await AuthMiddleware(inner)(scope, _receive, _drain)
    assert called

    assert _is_public("/health", ["/health"])
    assert _is_public("/health/observability", ["/health"])
    assert not _is_public("/healthz", ["/health"])


# --- HTTP: enforcement -------------------------------------------------------------


def test_auth_off_by_default(client: TestClient) -> None:
    response = client.get("/memory/stats")
    assert response.status_code == 200


def test_protected_endpoint_rejects_missing_token(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _enable_auth(monkeypatch)
    response = client.get("/memory/stats")
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert "missing bearer token" in response.json()["detail"]


def test_protected_endpoint_rejects_garbage_token(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _enable_auth(monkeypatch)
    response = client.get(
        "/memory/stats", headers={"Authorization": "Bearer not-a-jwt"}
    )
    assert response.status_code == 401
    assert "invalid or expired" in response.json()["detail"]


def test_protected_endpoint_rejects_expired_token(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _enable_auth(monkeypatch)
    stale = create_token("alice", ttl_s=-10)
    response = client.get("/memory/stats", headers={"Authorization": f"Bearer {stale}"})
    assert response.status_code == 401


def test_protected_endpoint_accepts_valid_token(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _enable_auth(monkeypatch)
    token = create_token("alice")
    response = client.get("/memory/stats", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200


def test_health_stays_public_when_auth_on(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _enable_auth(monkeypatch)
    assert client.get("/health").status_code == 200
    assert client.get("/openapi.json").status_code == 200


def test_malformed_authorization_header_rejected(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _enable_auth(monkeypatch)
    response = client.get("/memory/stats", headers={"Authorization": "Token abc"})
    assert response.status_code == 401
    assert "missing bearer token" in response.json()["detail"]


# --- HTTP: request-id ---------------------------------------------------------------


def test_request_id_generated(client: TestClient) -> None:
    request_id = client.get("/health").headers["x-request-id"]
    assert len(request_id) == 32  # uuid4().hex


def test_request_id_echoed(client: TestClient) -> None:
    response = client.get("/health", headers={"X-Request-ID": "trace-42"})
    assert response.headers["x-request-id"] == "trace-42"


def test_request_id_present_on_auth_rejection(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _enable_auth(monkeypatch)
    response = client.get("/memory/stats", headers={"X-Request-ID": "trace-401"})
    assert response.status_code == 401
    assert response.headers["x-request-id"] == "trace-401"


async def test_request_id_state_reachable() -> None:
    seen: dict[str, object] = {}

    async def inner(scope: Scope, receive: Receive, send: Send) -> None:
        seen.update(scope.get("state", {}))
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    scope: Scope = {"type": "http", "path": "/x", "method": "GET", "headers": []}
    await RequestIdMiddleware(inner)(scope, _receive, _drain)
    assert seen["request_id"]


# --- HTTP: CORS ---------------------------------------------------------------------


def test_cors_preflight_allowed_any_origin_by_default(client: TestClient) -> None:
    response = client.options(
        "/memory/stats",
        headers={
            "Origin": "http://localhost:8001",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:8001"


def test_cors_restricted_origins(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CORS_ORIGINS", "http://allowed.example")
    clear_settings_cache()
    ok = client.options(
        "/memory/stats",
        headers={
            "Origin": "http://allowed.example",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert ok.status_code == 200
    assert ok.headers["access-control-allow-origin"] == "http://allowed.example"

    denied = client.options(
        "/memory/stats",
        headers={
            "Origin": "http://evil.example",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert denied.status_code == 400
    assert "access-control-allow-origin" not in denied.headers


def test_cors_rebuilds_when_settings_change(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # default (wildcard) first ...
    assert (
        client.options(
            "/memory/stats",
            headers={
                "Origin": "http://any.example",
                "Access-Control-Request-Method": "GET",
            },
        ).status_code
        == 200
    )
    # ... then a restricted list picked up without restarting the app
    monkeypatch.setenv("CORS_ORIGINS", "http://only.example")
    clear_settings_cache()
    assert (
        client.options(
            "/memory/stats",
            headers={
                "Origin": "http://only.example",
                "Access-Control-Request-Method": "GET",
            },
        ).status_code
        == 200
    )
    assert (
        client.options(
            "/memory/stats",
            headers={
                "Origin": "http://any.example",
                "Access-Control-Request-Method": "GET",
            },
        ).status_code
        == 400
    )


# --- CLI: orya auth token -------------------------------------------------------------


def test_cli_mints_token(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("AUTH_SECRET_KEY", _SECRET)
    clear_settings_cache()
    from app.main import main

    monkeypatch.setattr(sys, "argv", ["orya", "auth", "token", "--user", "cli"])
    main()
    out = capsys.readouterr().out.strip()
    assert decode_token(out) == "cli"


def test_cli_without_secret_exits_nonzero(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    clear_settings_cache()
    from app.main import main

    monkeypatch.setattr(sys, "argv", ["orya", "auth", "token"])
    with pytest.raises(SystemExit) as excinfo:
        main()
    assert excinfo.value.code == 1
