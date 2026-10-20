"""FastAPI LLM registry endpoints (M-01 DoD: /llm/providers, /llm/models, /llm/health)."""


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
