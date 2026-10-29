"""Declarative LLM provider/model registries (YAML-backed).

Loads and validates ``providers.yaml``, ``models.yaml``, ``capabilities.yaml``
and ``pricing.yaml``. This is the single source of truth for provider-specific
settings — no provider base URLs or model ids are hardcoded in Python code.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import BaseModel, Field

REGISTRY_DIR = Path(__file__).parent


class ProviderSpec(BaseModel):
    """One entry from ``providers.yaml``."""

    name: str
    adapter: str = Field(
        pattern="^(anthropic|openai|google_genai|openai_compat)$",
        description="Which code-path builds the chat model",
    )
    base_url: str | None = None
    env_var: str | None = None
    default_model: str
    api_key_placeholder: str | None = None
    health_path: str | None = Field(
        default=None,
        pattern="^/",
        description=(
            "Health-check path joined to the server root (base_url minus its "
            "/v1 suffix); defaults to /v1/models"
        ),
    )
    tier: str = "western"
    extra_headers: dict[str, str] = Field(default_factory=dict)
    description: str = ""


class ModelSpec(BaseModel):
    """One entry from ``models.yaml`` (alias registry)."""

    alias: str
    provider: str
    model_id: str
    context_window: int | None = None
    supports_tools: bool = True
    supports_streaming: bool = True
    supports_system_prompt: bool = True
    suggests: str | None = None
    pricing_ref: str | None = None
    description: str = ""


class CapabilitySpec(BaseModel):
    """Per-model capability flags from ``capabilities.yaml``."""

    supports_tools: bool = True
    supports_streaming: bool = True
    supports_system_prompt: bool = True
    context_window: int | None = None
    suggests: str | None = None


class PricingSpec(BaseModel):
    """One entry from ``pricing.yaml`` (USD per 1K tokens)."""

    input_per_1k: float
    output_per_1k: float


def _load_yaml(filename: str) -> dict:
    path = REGISTRY_DIR / filename
    if not path.exists():
        raise FileNotFoundError(f"LLM registry file not found: {path}")
    with path.open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Registry file {filename} must contain a mapping")
    return data


@lru_cache(maxsize=1)
def load_providers() -> dict[str, ProviderSpec]:
    """Load and validate ``providers.yaml`` (cached)."""
    raw = _load_yaml("providers.yaml").get("providers")
    if not isinstance(raw, dict):
        raise ValueError("providers.yaml must contain a top-level 'providers' mapping")
    specs: dict[str, ProviderSpec] = {}
    for name, entry in raw.items():
        if not isinstance(entry, dict):
            raise ValueError(f"Provider '{name}' entry must be a mapping")
        spec = ProviderSpec(name=name, **entry)
        specs[name] = spec
    return specs


@lru_cache(maxsize=1)
def load_models() -> dict[str, ModelSpec]:
    """Load and validate ``models.yaml`` (cached). Keyed by alias."""
    raw = _load_yaml("models.yaml").get("models")
    if not isinstance(raw, list):
        raise ValueError("models.yaml must contain a top-level 'models' list")
    providers = load_providers()
    specs: dict[str, ModelSpec] = {}
    for entry in raw:
        if not isinstance(entry, dict):
            raise ValueError("Each models.yaml entry must be a mapping")
        spec = ModelSpec(**entry)
        if spec.provider not in providers:
            raise ValueError(
                f"Model alias '{spec.alias}' references unknown provider "
                f"'{spec.provider}' — add it to providers.yaml first"
            )
        if spec.alias in specs:
            raise ValueError(f"Duplicate model alias '{spec.alias}' in models.yaml")
        specs[spec.alias] = spec
    return specs


@lru_cache(maxsize=1)
def load_capabilities() -> dict[str, dict[str, CapabilitySpec]]:
    """Load ``capabilities.yaml``. Shape: {provider: {model_id: CapabilitySpec}}."""
    raw = _load_yaml("capabilities.yaml").get("capabilities")
    if not isinstance(raw, dict):
        raise ValueError(
            "capabilities.yaml must contain a top-level 'capabilities' mapping"
        )
    result: dict[str, dict[str, CapabilitySpec]] = {}
    for provider, models in raw.items():
        if not isinstance(models, dict):
            raise ValueError(f"capabilities['{provider}'] must be a mapping")
        result[provider] = {
            model_id: CapabilitySpec(**flags) for model_id, flags in models.items()
        }
    return result


@lru_cache(maxsize=1)
def load_pricing() -> dict[str, PricingSpec]:
    """Load ``pricing.yaml``. Keyed by model_id."""
    raw = _load_yaml("pricing.yaml").get("pricing")
    if not isinstance(raw, dict):
        raise ValueError("pricing.yaml must contain a top-level 'pricing' mapping")
    return {model_id: PricingSpec(**entry) for model_id, entry in raw.items()}


def resolve_model(provider: str | None, model: str) -> ModelSpec:
    """Resolve ``model`` (alias or raw model_id) for ``provider`` into a ModelSpec.

    Lookup order:
    1. ``models.yaml`` alias (global). If a provider was also passed and it
       conflicts with the alias's provider, raise ValueError.
    2. ``capabilities.yaml`` entry for (provider, model_id).
    3. Optimistic default (assume tools + streaming supported).
    """
    models = load_models()
    providers = load_providers()

    if model in models:
        spec = models[model]
        if provider is not None and provider != spec.provider:
            raise ValueError(
                f"Model alias '{model}' belongs to provider '{spec.provider}', "
                f"not '{provider}'"
            )
        return spec

    if provider is None:
        raise ValueError(
            f"Model '{model}' is not a known alias and no provider was given. "
            f"Known aliases: {', '.join(sorted(models)[:10])}, ..."
        )
    if provider not in providers:
        raise ValueError(
            f"Unknown provider '{provider}'. Known providers: "
            f"{', '.join(sorted(providers))}"
        )

    caps = load_capabilities().get(provider, {}).get(model)
    if caps is not None:
        return ModelSpec(
            alias=model,
            provider=provider,
            model_id=model,
            context_window=caps.context_window,
            supports_tools=caps.supports_tools,
            supports_streaming=caps.supports_streaming,
            supports_system_prompt=caps.supports_system_prompt,
            suggests=caps.suggests,
        )

    return ModelSpec(alias=model, provider=provider, model_id=model)


def clear_registry_cache() -> None:
    """Drop cached registries (used by tests that rewrite YAML fixtures)."""
    load_providers.cache_clear()
    load_models.cache_clear()
    load_capabilities.cache_clear()
    load_pricing.cache_clear()
