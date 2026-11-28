"""Unit tests for P-00 — OryaAgent ``GET /health/ready`` with OriaHS."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from app.core.oriahs_client import OriaHSHealth


def _backend(ok: bool, **overrides) -> AsyncMock:
    client = AsyncMock()
    client.health.return_value = OriaHSHealth(
        ok=ok,
        status="ready" if ok else "unavailable",
        checks={"postgres": "ok"} if ok else {},
        latency_ms=12.5,
        error=None if ok else "HTTP 503",
        **overrides,
    )
    return client


def test_ready_when_backend_and_facade_ok(client: TestClient):
    backend = _backend(True)
    with (
        patch("app.api.health.get_oriahs_client", return_value=backend),
        patch("app.api.health.get_mcp_client") as get_mcp,
    ):
        get_mcp.return_value.health_check = AsyncMock(return_value=True)
        response = client.get("/health/ready")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ready"
    assert body["fallback"] is None
    assert body["checks"]["oriahs"]["ok"] is True
    assert body["checks"]["oriahs_mcp"]["ok"] is True
    assert body["checks"]["oriahs"]["latency_ms"] == 12.5


def test_degraded_when_oriahs_down(client: TestClient):
    backend = _backend(False)
    with (
        patch("app.api.health.get_oriahs_client", return_value=backend),
        patch("app.api.health.get_mcp_client") as get_mcp,
    ):
        get_mcp.return_value.health_check = AsyncMock(return_value=True)
        response = client.get("/health/ready")

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "degraded"
    assert body["fallback"] == "service unavailable, use grep"
    assert body["checks"]["oriahs"]["error"] == "HTTP 503"


def test_degraded_when_facade_down(client: TestClient):
    backend = _backend(True)
    with (
        patch("app.api.health.get_oriahs_client", return_value=backend),
        patch("app.api.health.get_mcp_client") as get_mcp,
    ):
        get_mcp.return_value.health_check = AsyncMock(return_value=False)
        response = client.get("/health/ready")

    assert response.status_code == 503
    assert response.json()["checks"]["oriahs_mcp"]["ok"] is False


def test_disabled_backend_counts_as_ready(client: TestClient):
    from app.core.config import Settings

    settings = Settings(oriahs_enabled=False)
    with (
        patch("app.api.health.get_settings", return_value=settings),
        patch("app.api.health.get_mcp_client") as get_mcp,
    ):
        get_mcp.return_value.health_check = AsyncMock(return_value=True)
        response = client.get("/health/ready")

    assert response.status_code == 200
    assert response.json()["checks"]["oriahs"] == {
        "ok": True,
        "status": "disabled",
    }
