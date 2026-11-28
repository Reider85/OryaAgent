"""Unit tests for P-00 — config unification, client bootstrap and health tool."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from app.core.config import clear_settings_cache, get_settings
from app.core.mcp_config import get_mcp_config, get_oriahs_config
from app.core.oriahs_client import OriaHSHealth
from app.mcp.client import (
    MCPClientConfig,
    close_mcp_client,
    get_mcp_client,
    set_mcp_config,
)
from app.tools.oriahs import oriahs_health


@pytest.fixture
def isolated_config(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    for name in list(os.environ):
        if (
            name.startswith("ORYA_")
            or name.startswith("ORIAHS_")
            or name.startswith("MCP_")
        ):
            monkeypatch.delenv(name, raising=False)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ORYA_CONFIG_PATH", str(tmp_path / "config.yaml"))
    clear_settings_cache()
    yield
    clear_settings_cache()


def test_settings_accept_legacy_env_names(
    isolated_config, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv("ORIAHS_BASE_URL", "http://fresh:8000")
    monkeypatch.setenv("ORIAHS_TIMEOUT", "7.5")
    monkeypatch.setenv("MCP_SERVER_URL", "http://facade:8765")
    monkeypatch.setenv("MCP_AUTH_TOKEN", "facade-secret")
    monkeypatch.setenv("MCP_TIMEOUT", "2.0")
    monkeypatch.setenv("ORYA_ORIAHS_TENANT_ID", "tenant-x")
    clear_settings_cache()

    settings = get_settings()
    assert settings.oriahs_url == "http://fresh:8000"
    assert settings.oriahs_timeout_s == 7.5
    assert settings.oriahs_tenant_id == "tenant-x"
    assert settings.mcp_server_url == "http://facade:8765"
    assert settings.mcp_auth_token is not None
    assert settings.mcp_auth_token.get_secret_value() == "facade-secret"
    assert settings.mcp_timeout_s == 2.0


def test_get_mcp_config_reads_effective_settings(
    isolated_config, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv("MCP_SERVER_URL", "http://facade:9999")
    monkeypatch.setenv("MCP_AUTH_TOKEN", "token-1")
    monkeypatch.setenv("MCP_MAX_RETRIES", "5")
    clear_settings_cache()

    config = get_mcp_config()
    assert config.server_url == "http://facade:9999"
    assert config.auth_token == "token-1"
    assert config.max_retries == 5

    backend = get_oriahs_config()
    assert backend["base_url"] == "http://localhost:8000"
    assert backend["tenant_id"] == get_settings().oriahs_tenant_id


async def test_get_mcp_client_honours_the_facade_config(
    isolated_config, monkeypatch: pytest.MonkeyPatch
):
    await close_mcp_client()
    monkeypatch.setattr("app.mcp.client._mcp_config", None)
    config = MCPClientConfig(server_url="http://facade:1234", auth_token="tok")
    monkeypatch.setattr("app.core.mcp_config.get_mcp_config", lambda: config)

    client = get_mcp_client()
    assert str(client._http_client.base_url) == "http://facade:1234"
    assert client._http_client.headers["Authorization"] == "Bearer tok"
    await close_mcp_client()


async def test_set_mcp_config_outside_a_loop_does_not_schedule_tasks(
    isolated_config,
):
    config = MCPClientConfig(server_url="http://new-facade:8765")
    set_mcp_config(config)
    assert get_mcp_client().config is config
    await close_mcp_client()


async def test_oriahs_health_tool_reports_both_seams():
    backend = AsyncMock()
    backend.health.return_value = OriaHSHealth(
        ok=True, status="ready", checks={"postgres": "ok"}, latency_ms=4.0
    )
    facade = AsyncMock()
    facade.health_check.return_value = True

    with (
        patch("app.tools.oriahs.get_oriahs_client", return_value=backend),
        patch("app.tools.oriahs.get_mcp_client", return_value=facade),
    ):
        result = await oriahs_health.ainvoke({"detail": False})

    assert "ready" in result
    assert "ok" in result
    assert "Checks:" not in result


async def test_oriahs_health_tool_shows_fallback_on_degradation():
    backend = AsyncMock()
    backend.health.return_value = OriaHSHealth(
        ok=False, status="unavailable", error="HTTP 503", latency_ms=1.0
    )
    facade = AsyncMock()
    facade.health_check.return_value = False

    with (
        patch("app.tools.oriahs.get_oriahs_client", return_value=backend),
        patch("app.tools.oriahs.get_mcp_client", return_value=facade),
    ):
        result = await oriahs_health.ainvoke({"detail": True})

    assert "service unavailable, use grep" in result
    assert "unavailable" in result
