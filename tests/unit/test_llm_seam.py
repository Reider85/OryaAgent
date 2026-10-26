"""get_llm() seam tests for all providers (mocked — construction only, no network)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from langchain_core.language_models import BaseChatModel

from app.core.config import clear_settings_cache
from app.core.llm import get_llm, list_models, list_providers
from app.core.llm.registry import clear_registry_cache, load_providers


@pytest.fixture(autouse=True)
def isolated_llm_config(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Sandbox config: no inherited env, no repo .env, no user config.yaml.

    A developer's ``.env`` / ``~/.orya/config.yaml`` may set
    ``ORYA_LLM_MODEL`` (or a yaml ``llm.default_model``) — without this
    sandbox those leak into ``get_llm(provider)`` calls and break the
    provider-resolution assertions below.
    """
    for name in list(os.environ):
        if name.startswith("ORYA_") or name in {
            "DEEPSEEK_API_KEY",
            "ANTHROPIC_API_KEY",
        }:
            monkeypatch.delenv(name, raising=False)
    monkeypatch.chdir(tmp_path)  # ignore any project-root .env
    monkeypatch.setenv("ORYA_CONFIG_PATH", str(tmp_path / "config.yaml"))
    clear_settings_cache()
    clear_registry_cache()
    yield
    clear_settings_cache()
    clear_registry_cache()


def test_get_llm_returns_base_chat_model():
    llm = get_llm("deepseek", "deepseek-chat", api_key="sk-fake")
    assert isinstance(llm, BaseChatModel)


@pytest.mark.parametrize(
    ("provider", "adapter", "attr", "expected"),
    [
        ("deepseek", "openai_compat", "openai_api_base", "https://api.deepseek.com/v1"),
        (
            "qwen",
            "openai_compat",
            "openai_api_base",
            "https://dashscope.aliyuncs.com/compatible-mode/v1",
        ),
        (
            "glm",
            "openai_compat",
            "openai_api_base",
            "https://open.bigmodel.cn/api/paas/v4",
        ),
        (
            "openrouter",
            "openai_compat",
            "openai_api_base",
            "https://openrouter.ai/api/v1",
        ),
    ],
)
def test_openai_compat_providers_get_base_url(provider, adapter, attr, expected):
    llm = get_llm(provider, api_key="sk-fake")
    assert getattr(llm, attr) == expected
    assert llm.model


def test_every_openai_compat_provider_constructs():
    """All openai_compat providers must build a ChatOpenAI with a fake key."""
    for name, spec in sorted(load_providers().items()):
        if spec.adapter != "openai_compat":
            continue
        llm = get_llm(name, api_key="sk-fake", require_tools=False)
        assert isinstance(llm, BaseChatModel), name
        assert llm.openai_api_base == spec.base_url, name


def test_anthropic_native_adapter():
    llm = get_llm("anthropic", "claude-sonnet-3.5", api_key="sk-ant-fake")
    assert type(llm).__name__ == "ChatAnthropic"
    assert llm.model == "claude-3-5-sonnet-latest"


def test_openai_native_adapter():
    llm = get_llm("openai", "gpt-4o", api_key="sk-fake")
    assert type(llm).__name__ == "ChatOpenAI"
    assert llm.model == "gpt-4o"
    assert llm.openai_api_base == "https://api.openai.com/v1"


def test_google_native_adapter():
    llm = get_llm("google", "gemini-2.0-flash", api_key="fake-key")
    assert type(llm).__name__ == "ChatGoogleGenerativeAI"


def test_local_provider_uses_placeholder_key():
    llm = get_llm("ollama", "ollama-coder")
    assert isinstance(llm, BaseChatModel)
    assert llm.openai_api_base == "http://localhost:11434/v1"


def test_openrouter_extra_headers():
    llm = get_llm("openrouter", api_key="sk-or-fake")
    headers = llm.default_headers
    assert headers.get("HTTP-Referer") == "https://github.com/Reider85/OryaAgent"
    assert headers.get("X-Title") == "OryaAgent"


def test_unknown_provider_raises():
    with pytest.raises(ValueError, match="Unknown provider"):
        get_llm("no-such-provider", api_key="x")


def test_missing_api_key_raises_with_candidates():
    import os

    os.environ.pop("DEEPSEEK_API_KEY", None)
    os.environ.pop("ORYA_LLM_API_KEY", None)
    with pytest.raises(ValueError, match="DEEPSEEK_API_KEY"):
        get_llm("deepseek", "deepseek-chat")


def test_api_key_kwarg_wins():
    llm = get_llm("deepseek", "deepseek-chat", api_key="sk-explicit")
    # SecretStr repr must not leak the key
    assert "sk-explicit" not in repr(llm)


def test_alias_provider_conflict_raises():
    with pytest.raises(ValueError, match="belongs to provider"):
        get_llm("qwen", "deepseek-chat", api_key="sk-fake")


def test_kwargs_passthrough_temperature():
    llm = get_llm("deepseek", "deepseek-chat", api_key="sk-fake", temperature=0.7)
    assert llm.temperature == pytest.approx(0.7)


def test_list_providers_serializable():
    providers = list_providers()
    assert len(providers) >= 20
    names = {p["name"] for p in providers}
    assert {"anthropic", "deepseek", "ollama", "openrouter"} <= names
    for p in providers:
        assert set(p) >= {"name", "adapter", "base_url", "tier", "has_api_key"}


def test_list_models_serializable():
    models = list_models()
    assert len(models) >= 10
    aliases = {m["alias"] for m in models}
    assert "claude-sonnet-3.5" in aliases
    for m in models:
        assert set(m) >= {"alias", "provider", "model_id", "supports_tools"}
