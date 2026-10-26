"""Validity of models.yaml, capabilities.yaml and pricing.yaml (M-01)."""

from app.core.llm.registry import (
    load_capabilities,
    load_models,
    load_pricing,
    load_providers,
)


def test_models_yaml_loads():
    models = load_models()
    assert len(models) >= 10


def test_default_mvp_model_registered():
    models = load_models()
    assert "claude-sonnet-3.5" in models
    spec = models["claude-sonnet-3.5"]
    assert spec.provider == "anthropic"
    assert spec.supports_tools is True


def test_all_model_providers_exist():
    providers = load_providers()
    for alias, spec in load_models().items():
        assert spec.provider in providers, (
            f"alias '{alias}' references unknown provider '{spec.provider}'"
        )


def test_aliases_are_unique():
    models = load_models()
    aliases = [spec.alias for spec in models.values()]
    assert len(aliases) == len(set(aliases))


def test_reasoning_models_flagged_without_tools():
    models = load_models()
    for alias in ("deepseek-reasoner", "o1", "glm-zero-preview"):
        assert alias in models, f"reasoning model '{alias}' must be registered"
        spec = models[alias]
        assert spec.supports_tools is False, f"{alias} must have supports_tools=false"
        assert spec.suggests, f"{alias} must suggest a replacement model"


def test_reasoning_suggestions_are_valid_aliases():
    models = load_models()
    for alias, spec in models.items():
        if spec.supports_tools is False and spec.suggests:
            assert spec.suggests in models or "/" in spec.suggests, (
                f"{alias}: suggests '{spec.suggests}' is not a known alias"
            )


def test_capabilities_yaml_shape():
    caps = load_capabilities()
    assert "deepseek" in caps
    assert "deepseek-reasoner" in caps["deepseek"]
    entry = caps["deepseek"]["deepseek-reasoner"]
    assert entry.supports_tools is False
    assert entry.suggests == "deepseek-chat"


def test_zai_glm_flash_aliases_registered():
    models = load_models()
    flash = models["glm-4.5-flash"]
    assert flash.provider == "zai"
    assert flash.model_id == "glm-4.5-flash"
    assert flash.supports_tools is True

    successor = models["glm-5.3-flash"]
    assert successor.provider == "zai"
    assert successor.model_id == "glm-5.3-flash"

    caps = load_capabilities()["zai"]
    assert caps["glm-4.5-flash"].supports_tools is True
    assert caps["glm-5.3-flash"].supports_tools is True

    pricing = load_pricing()
    assert pricing["glm-4.5-flash"].input_per_1k == 0.0
    assert pricing["glm-5.3-flash"].output_per_1k == 0.0


def test_pricing_yaml_covers_default_models():
    pricing = load_pricing()
    models = load_models()
    default = models["claude-sonnet-3.5"]
    assert default.model_id in pricing or default.alias in pricing
