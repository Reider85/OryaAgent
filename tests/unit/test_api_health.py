"""Unit tests for A-04 — Health endpoints (PROMPT_ALPHA §3 A-04).

Test all health endpoints: /health, /health/observability, /health/sampler-proxy.
No infra: settings are sandboxed per-request, HTTP goes through the shared
session-scoped ``client`` (autouse ``isolated`` fixture flips ORYA_* env vars safely).
"""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app.core.config import clear_settings_cache
from app.core.observability.spans import clear_span_buffer

_MANAGED_ENV_VARS = frozenset(
    {
        "DATABASE_URL",
        "LOG_LEVEL",
        "ORYA_LLM_TRACE_ENABLED",
        "ORYA_LLM_TRACE_EXPORTER",
        "ORYA_PERMISSION_AUDIT_ENABLED",
        "ORYA_SAMPLER_PROXY_URL",
        "ORYA_AUTH_ENABLED",
        "AUTH_SECRET_KEY",
        "AUTH_ALGORITHM",
        "AUTH_TOKEN_TTL_S",
        "AUTH_PUBLIC_PATHS",
        "CORS_ORIGINS",
    }
)


@pytest.fixture
def health_isolated(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Sandbox env/config, point the memory dir at tmp_path (A-04 health tests)."""
    # Only clear ORYA_ vars that are specific to health tests
    health_specific_vars = {
        "ORYA_LLM_TRACE_ENABLED",
        "ORYA_LLM_TRACE_EXPORTER",
        "ORYA_PERMISSION_AUDIT_ENABLED",
        "ORYA_SAMPLER_PROXY_URL",
        "ORYA_AUTH_ENABLED",
    }

    for name in list(os.environ):
        if name in health_specific_vars:
            monkeypatch.delenv(name, raising=False)

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ORYA_CONFIG_PATH", str(tmp_path / "config.yaml"))

    # Point all storage to tmp_path
    monkeypatch.setenv("ORYA_MEMORY_DIR", str(tmp_path / "memory"))
    monkeypatch.setenv("ORYA_SESSIONS_DIR", str(tmp_path / "sessions"))

    # Set minimal auth settings to avoid clearing them for other tests
    monkeypatch.setenv("AUTH_SECRET_KEY", "test-secret-key")
    monkeypatch.setenv("AUTH_ALGORITHM", "HS256")
    monkeypatch.setenv("AUTH_TOKEN_TTL_S", "3600")

    # Clear settings cache to ensure clean state
    clear_settings_cache()

    yield

    # Cleanup: restore the original environment
    for name in list(os.environ):
        if name in _MANAGED_ENV_VARS:
            monkeypatch.delenv(name, raising=False)

    clear_settings_cache()


@pytest.fixture(autouse=True)
def isolated_fixture(request: pytest.FixtureRequest):
    """Apply the isolated fixture to all health tests."""
    if "health_isolated" in request.fixturenames:
        request.getfixturevalue("health_isolated")


@pytest.fixture(autouse=True)
def _fresh_span_buffer():
    """Drop spans leaked by earlier suites — /health/observability counts the buffer.

    The span buffer is process-global; suites that run before this module
    (smoke, e2e) may leave records behind, which broke the
    ``span_buffer_size == 0`` assertion regardless of this module's own tests.
    """
    clear_span_buffer()
    yield
    clear_span_buffer()


# --- /health endpoint ---------------------------------------------------------


def test_health_endpoint(client: TestClient):
    """Test basic /health endpoint."""
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["message"] == "OryaAgent API is running"


# --- /health/observability endpoint --------------------------------------------


def test_health_observability_defaults(client: TestClient):
    """Test /health/observability with default settings."""
    response = client.get("/health/observability")
    assert response.status_code == 200
    data = response.json()
    assert data["sdk_enabled"] is True
    assert data["exporter_connected"] is False
    assert data["guardrail_ready"] is True
    assert data["span_buffer_size"] == 0


def test_health_observability_sdk_disabled(client: TestClient):
    """Test /health/observability with SDK disabled."""
    os.environ["ORYA_LLM_TRACE_ENABLED"] = "false"
    clear_settings_cache()

    response = client.get("/health/observability")
    assert response.status_code == 200
    data = response.json()
    assert data["sdk_enabled"] is False


def test_health_observability_stdout_exporter(client: TestClient):
    """Test /health/observability with stdout exporter."""
    os.environ["ORYA_LLM_TRACE_ENABLED"] = "true"
    os.environ["ORYA_LLM_TRACE_EXPORTER"] = "stdout"
    clear_settings_cache()

    response = client.get("/health/observability")
    assert response.status_code == 200
    data = response.json()
    assert data["sdk_enabled"] is True
    assert data["exporter_connected"] is True


def test_health_observability_permission_disabled(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
):
    """Test /health/observability with permissions disabled."""
    monkeypatch.setenv("ORYA_LLM_TRACE_ENABLED", "true")
    monkeypatch.setenv("ORYA_PERMISSION_AUDIT_ENABLED", "false")
    clear_settings_cache()

    try:
        response = client.get("/health/observability")
        assert response.status_code == 200
        data = response.json()
        assert data["sdk_enabled"] is True
        assert data["guardrail_ready"] is False
    finally:
        # Drop the poisoned lru_cache entry: monkeypatch restores the env
        # only after teardown, and a stale False would leak into later
        # modules (test_permission_audit reads it per check).
        clear_settings_cache()


# --- /health/sampler-proxy endpoint -------------------------------------------


def test_health_sampler_proxy_defaults(client: TestClient):
    """Test /health/sampler-proxy with default URL (reachable in tests)."""
    from app.core.config import Settings

    # Create a settings object that will trigger the "not configured" case
    # so we can test the mock behavior
    settings = Settings(sampler_proxy_url="http://sampler-proxy:4321")

    # Mock both get_settings and AsyncClient
    with (
        patch("app.api.health.get_settings", return_value=settings),
        patch("app.api.health.AsyncClient") as mock_client_class,
    ):
        mock_instance = AsyncMock()
        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_instance.head.return_value = mock_response
        mock_client_class.return_value.__aenter__.return_value = mock_instance

        response = client.get("/health/sampler-proxy")
        assert response.status_code == 200

        data = response.json()
        assert data["status"] == "ok"
        assert data["url"] == "http://sampler-proxy:4321"
        assert data["status_code"] == 200


def test_health_sampler_proxy_timeout(client: TestClient):
    """Test /health/sampler-proxy with timeout (unreachable)."""
    from app.core.config import Settings

    # Create a settings object with a non-default URL to avoid "not configured" case
    settings = Settings(sampler_proxy_url="http://test-sampler:4321")

    # Mock the httpx.AsyncClient.head to raise TimeoutException
    with (
        patch("app.api.health.get_settings", return_value=settings),
        patch("app.api.health.AsyncClient") as mock_client_class,
    ):
        mock_instance = AsyncMock()
        mock_instance.head.side_effect = Exception("Connection timeout")
        mock_client_class.return_value.__aenter__.return_value = mock_instance

        response = client.get("/health/sampler-proxy")
        assert response.status_code == 503


def test_health_sampler_proxy_not_configured(client: TestClient):
    """Test /health/sampler-proxy with empty URL (not configured)."""
    from app.core.config import Settings

    # Create a settings object with empty sampler_proxy_url
    settings = Settings(sampler_proxy_url="")

    # Mock get_settings to return our custom settings
    with patch("app.api.health.get_settings", return_value=settings):
        response = client.get("/health/sampler-proxy")
        assert response.status_code == 503

        data = response.json()
        assert "not configured" in str(data).lower()


def test_health_sampler_proxy_custom_url(client: TestClient):
    """Test /health/sampler-proxy with custom URL."""
    from app.core.config import Settings

    # Create a custom settings object with the custom URL
    custom_settings = Settings(sampler_proxy_url="http://custom-proxy:9999")

    # Mock both get_settings and AsyncClient
    with (
        patch("app.api.health.get_settings", return_value=custom_settings),
        patch("app.api.health.AsyncClient") as mock_client_class,
    ):
        mock_instance = AsyncMock()
        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_instance.head.return_value = mock_response
        mock_client_class.return_value.__aenter__.return_value = mock_instance

        response = client.get("/health/sampler-proxy")
        assert response.status_code == 200

        data = response.json()
        assert data["status"] == "ok"
        # The URL should be the custom one
        assert data["url"] == "http://custom-proxy:9999"
        assert data["status_code"] == 200


# --- Auth exemption tests -------------------------------------------------------


def test_health_endpoints_auth_exempt(client: TestClient):
    """Test that health endpoints are exempt from auth (no token required)."""
    # Set up minimal auth environment
    os.environ["AUTH_SECRET_KEY"] = "test-secret-key-for-auth-exemption-test"
    clear_settings_cache()

    # Test all health endpoints without token - should all return 200
    response = client.get("/health")
    assert response.status_code == 200

    response = client.get("/health/observability")
    assert response.status_code == 200

    # Mock sampler-proxy for this test
    from app.core.config import Settings

    settings = Settings(sampler_proxy_url="http://sampler-proxy:4321")

    with (
        patch("app.api.health.get_settings", return_value=settings),
        patch("app.api.health.AsyncClient") as mock_client_class,
    ):
        mock_instance = AsyncMock()
        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_instance.head.return_value = mock_response
        mock_client_class.return_value.__aenter__.return_value = mock_instance

        response = client.get("/health/sampler-proxy")
        assert response.status_code == 200
