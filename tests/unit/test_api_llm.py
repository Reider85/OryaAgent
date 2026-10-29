"""FastAPI LLM registry endpoints (M-01 DoD: /llm/providers, /llm/models, /llm/health)."""

from app.core.llm.adapters import local as local_adapter


def test_llm_providers_endpoint(client):
    response = client.get("/llm/providers")
    assert response.status_code == 200
    data = response.json()
    names = {p["name"] for p in data["providers"]}
    assert len(names) >= 20
    assert {"anthropic", "deepseek", "qwen", "ollama", "openrouter"} <= names


def test_llm_models_endpoint(client):
    response = client.get("/llm/models")
    assert response.status_code == 200
    data = response.json()
    aliases = {m["alias"] for m in data["models"]}
    assert "claude-sonnet-3.5" in aliases
    reasoner = next(m for m in data["models"] if m["alias"] == "deepseek-reasoner")
    assert reasoner["supports_tools"] is False
    assert reasoner["suggests"] == "deepseek-chat"


def test_llm_health_unknown_provider_404(client):
    response = client.get("/llm/health/no-such-provider")
    assert response.status_code == 404


def test_llm_health_local_provider_unreachable_503(client):
    # gpt4all on :4891 is not running in CI — expect 503 with structured detail
    response = client.get("/llm/health/gpt4all")
    assert response.status_code == 503
    detail = response.json()["detail"]
    assert detail["provider"] == "gpt4all"
    assert detail["status"] == "unreachable"
    assert "hint" in detail


def test_build_health_url():
    """health_path is joined to the server root (base_url minus /v1)."""
    assert (
        local_adapter.build_health_url("http://localhost:11434/v1", "/api/tags")
        == "http://localhost:11434/api/tags"
    )
    assert (
        local_adapter.build_health_url("http://localhost:1234/v1", "/v1/models")
        == "http://localhost:1234/v1/models"
    )
    # default health path when none is configured
    assert (
        local_adapter.build_health_url("https://api.deepseek.com/v1")
        == "https://api.deepseek.com/v1/models"
    )
    # base_url without a /v1 suffix is used as-is (e.g. anthropic)
    assert (
        local_adapter.build_health_url("https://api.anthropic.com")
        == "https://api.anthropic.com/v1/models"
    )


def _patch_health(monkeypatch, calls):
    async def fake_get(url, headers=None, timeout=5.0):
        calls.append((url, headers))
        return {"ok": True, "status_code": 200, "latency_ms": 1.0, "detail": ""}

    monkeypatch.setattr(local_adapter, "_get", fake_get)


def test_llm_health_dispatch_ollama_uses_yaml_health_path(client, monkeypatch):
    """MVP-POLISH-5: /llm/health/ollama probes /api/tags from providers.yaml."""
    calls = []
    _patch_health(monkeypatch, calls)
    response = client.get("/llm/health/ollama")
    assert response.status_code == 200
    assert calls == [("http://localhost:11434/api/tags", None)]
    assert response.json()["status"] == "ok"


def test_llm_health_dispatch_lmstudio_uses_yaml_health_path(client, monkeypatch):
    calls = []
    _patch_health(monkeypatch, calls)
    response = client.get("/llm/health/lmstudio")
    assert response.status_code == 200
    assert calls == [("http://localhost:1234/v1/models", None)]


def test_llm_health_dispatch_cloud_sends_bearer_key(client, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
    calls = []
    _patch_health(monkeypatch, calls)
    response = client.get("/llm/health/deepseek")
    assert response.status_code == 200
    url, headers = calls[0]
    assert url == "https://api.deepseek.com/v1/models"
    assert headers == {"Authorization": "Bearer sk-test"}


def test_llm_health_dispatch_anthropic_sends_x_api_key(client, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    calls = []
    _patch_health(monkeypatch, calls)
    response = client.get("/llm/health/anthropic")
    assert response.status_code == 200
    url, headers = calls[0]
    assert url == "https://api.anthropic.com/v1/models"
    assert headers["x-api-key"] == "sk-ant-test"
    assert headers["anthropic-version"] == "2023-06-01"
