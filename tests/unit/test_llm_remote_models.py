"""Remote model-list auto-fetch (fetch_remote_models + /llm/models/remote/*)."""

from __future__ import annotations

import os
from pathlib import Path

import httpx
import pytest
import yaml

from app.core.config import clear_settings_cache
from app.core.llm.remote import (
    MissingApiKeyError,
    RemoteModelsError,
    UnknownProviderError,
    fetch_remote_models,
)

_KEY_ENV_VARS = (
    "OPENCODE_ZEN_API_KEY",
    "OPENCODE_GO_API_KEY",
    "ZAI_API_KEY",
    "ORYA_LLM_API_KEY",
)


@pytest.fixture
def sandbox_config(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """No inherited ORYA_*/provider-key env, temp config.yaml, cleared caches."""
    for name in list(os.environ):
        if name.startswith("ORYA_") or name in _KEY_ENV_VARS:
            monkeypatch.delenv(name, raising=False)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ORYA_CONFIG_PATH", str(tmp_path / "config.yaml"))
    clear_settings_cache()
    yield tmp_path
    clear_settings_cache()


def _write_user_config(data: dict, tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


class _FakeResponse:
    def __init__(self, status_code: int = 200, payload=None, text: str = ""):
        self.status_code = status_code
        self._payload = payload
        self.text = text
        self.is_success = 200 <= status_code < 300

    def json(self):
        if self._payload is None:
            raise ValueError("not json")
        return self._payload


def _patch_client(
    monkeypatch: pytest.MonkeyPatch,
    *,
    response: _FakeResponse | None = None,
    exc: Exception | None = None,
    capture: dict | None = None,
) -> None:
    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def get(self, url, headers=None):
            if capture is not None:
                capture["url"] = url
                capture["headers"] = dict(headers or {})
            if exc is not None:
                raise exc
            return response or _FakeResponse()

    monkeypatch.setattr("app.core.llm.remote.httpx.AsyncClient", FakeAsyncClient)


async def test_fetch_remote_models_success(sandbox_config: Path, monkeypatch):
    _write_user_config(
        {"llm": {"providers": {"zai": {"api_key": "test-zai-key"}}}},
        sandbox_config,
    )
    capture: dict = {}
    _patch_client(
        monkeypatch,
        response=_FakeResponse(
            payload={
                "object": "list",
                "data": [
                    {"id": "glm-5.3-flash"},
                    {"id": "glm-4.5-flash"},
                    {"id": "glm-5.3-flash"},
                ],
            }
        ),
        capture=capture,
    )

    result = await fetch_remote_models("zai")

    assert capture["url"] == "https://api.z.ai/api/paas/v4/models"
    assert capture["headers"]["Authorization"] == "Bearer test-zai-key"
    assert result["provider"] == "zai"
    assert result["count"] == 2
    assert result["models"] == [{"id": "glm-4.5-flash"}, {"id": "glm-5.3-flash"}]
    assert result["fetched_at"]


async def test_fetch_remote_models_env_var_key(sandbox_config: Path, monkeypatch):
    monkeypatch.setenv("OPENCODE_ZEN_API_KEY", "env-zen-key")
    capture: dict = {}
    _patch_client(
        monkeypatch,
        response=_FakeResponse(payload={"data": [{"id": "glm-5.3-flash-free"}]}),
        capture=capture,
    )

    result = await fetch_remote_models("opencode-zen")

    assert capture["url"] == "https://opencode.ai/inference/v1/models"
    assert capture["headers"]["Authorization"] == "Bearer env-zen-key"
    assert result["models"] == [{"id": "glm-5.3-flash-free"}]


async def test_fetch_unknown_provider(sandbox_config: Path):
    with pytest.raises(UnknownProviderError):
        await fetch_remote_models("no-such-provider")


async def test_fetch_missing_key(sandbox_config: Path, monkeypatch):
    _write_user_config({}, sandbox_config)
    _patch_client(monkeypatch)

    with pytest.raises(MissingApiKeyError):
        await fetch_remote_models("zai")


async def test_fetch_http_error(sandbox_config: Path, monkeypatch):
    _write_user_config(
        {"llm": {"providers": {"zai": {"api_key": "k"}}}}, sandbox_config
    )
    _patch_client(
        monkeypatch,
        response=_FakeResponse(status_code=401, text="unauthorized"),
    )

    with pytest.raises(RemoteModelsError, match="HTTP 401"):
        await fetch_remote_models("zai")


async def test_fetch_network_error(sandbox_config: Path, monkeypatch):
    _write_user_config(
        {"llm": {"providers": {"zai": {"api_key": "k"}}}}, sandbox_config
    )
    _patch_client(monkeypatch, exc=httpx.ConnectError("boom"))

    with pytest.raises(RemoteModelsError, match="failed"):
        await fetch_remote_models("zai")


async def test_fetch_non_json(sandbox_config: Path, monkeypatch):
    _write_user_config(
        {"llm": {"providers": {"zai": {"api_key": "k"}}}}, sandbox_config
    )
    _patch_client(monkeypatch, response=_FakeResponse(payload=None))

    with pytest.raises(RemoteModelsError, match="non-JSON"):
        await fetch_remote_models("zai")


async def test_fetch_payload_missing_data(sandbox_config: Path, monkeypatch):
    _write_user_config(
        {"llm": {"providers": {"zai": {"api_key": "k"}}}}, sandbox_config
    )
    _patch_client(monkeypatch, response=_FakeResponse(payload={"object": "list"}))

    with pytest.raises(RemoteModelsError, match="data"):
        await fetch_remote_models("zai")


# --- API endpoint ---------------------------------------------------------


def test_remote_models_endpoint_unknown_provider_404(client):
    response = client.get("/llm/models/remote/no-such-provider")
    assert response.status_code == 404


def test_remote_models_endpoint_success(client, monkeypatch):
    payload = {
        "provider": "zai",
        "base_url": "https://api.z.ai/api/paas/v4",
        "count": 1,
        "models": [{"id": "glm-4.5-flash"}],
        "fetched_at": "2026-10-26T00:00:00+00:00",
    }

    async def fake_fetch(provider: str, *, timeout: float = 10.0):
        return payload

    monkeypatch.setattr("app.api.llm.fetch_remote_models", fake_fetch)
    response = client.get("/llm/models/remote/zai")
    assert response.status_code == 200
    assert response.json() == payload


def test_remote_models_endpoint_missing_key_400(client, monkeypatch):
    async def fake_fetch(provider: str, *, timeout: float = 10.0):
        raise MissingApiKeyError("no key")

    monkeypatch.setattr("app.api.llm.fetch_remote_models", fake_fetch)
    response = client.get("/llm/models/remote/zai")
    assert response.status_code == 400


def test_remote_models_endpoint_unreachable_503(client, monkeypatch):
    async def fake_fetch(provider: str, *, timeout: float = 10.0):
        raise RemoteModelsError("down")

    monkeypatch.setattr("app.api.llm.fetch_remote_models", fake_fetch)
    response = client.get("/llm/models/remote/zai")
    assert response.status_code == 503
