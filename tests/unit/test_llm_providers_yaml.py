"""Validity of providers.yaml (M-01)."""

import pytest

from app.core.llm.registry import ProviderSpec, load_providers


def test_providers_yaml_loads():
    providers = load_providers()
    assert len(providers) >= 20, "MVP must support 20+ providers"


def test_required_western_providers_present():
    providers = load_providers()
    for name in ("anthropic", "openai", "google", "xai"):
        assert name in providers, f"missing western provider: {name}"


def test_required_chinese_providers_present():
    providers = load_providers()
    chinese = [
        "deepseek",
        "qwen",
        "glm",
        "mimo",
        "moonshot",
        "baichuan",
        "minimax",
        "stepfun",
        "yi",
        "iflytek",
        "sensenova",
        "doubao",
        "hunyuan",
        "ernie",
    ]
    for name in chinese:
        assert name in providers, f"missing chinese provider: {name}"


def test_aggregator_and_local_providers_present():
    providers = load_providers()
    for name in (
        "openrouter",
        "together",
        "groq",
        "fireworks",
        "siliconflow",
        "nvidia",
        "cerebras",
        "sambanova",
        "ollama",
        "lmstudio",
        "vllm",
        "llamacpp",
        "tgi",
        "localai",
        "jan",
        "gpt4all",
    ):
        assert name in providers, f"missing provider: {name}"


def test_every_provider_has_required_fields():
    for name, spec in load_providers().items():
        assert spec.default_model, f"{name}: default_model missing"
        assert spec.adapter in (
            "anthropic",
            "openai",
            "google_genai",
            "openai_compat",
        ), f"{name}: bad adapter {spec.adapter}"
        if spec.adapter == "openai_compat" or spec.tier != "western":
            assert spec.base_url, f"{name}: base_url required for openai_compat"


def test_cloud_providers_have_env_var():
    for name, spec in load_providers().items():
        if spec.tier == "local":
            assert spec.api_key_placeholder, (
                f"{name}: local provider needs placeholder key"
            )
        else:
            assert spec.env_var, f"{name}: cloud provider needs env_var"


def test_openrouter_has_attribution_headers():
    spec = load_providers()["openrouter"]
    assert "HTTP-Referer" in spec.extra_headers
    assert "X-Title" in spec.extra_headers


def test_provider_spec_validates_adapter_pattern():
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        ProviderSpec(name="bad", adapter="bogus", default_model="x", env_var="X")
