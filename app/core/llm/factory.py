"""LLM-provider seam — the single entry point for constructing chat models.

``get_llm(provider, model, **kwargs) -> BaseChatModel`` is the architectural
invariant of OryaAgent: no business logic may import ``langchain_anthropic``,
``langchain_openai`` or any other partner package directly — everything goes
through this factory.

Resolution order (config sources):
1. Explicit ``provider`` / ``model`` arguments.
2. Env vars ``ORYA_LLM_PROVIDER`` / ``ORYA_LLM_MODEL`` (and ``.env``).
3. ``~/.orya/config.yaml`` (``llm.default_provider`` / ``llm.default_model``).
4. ``models.yaml`` alias lookup / ``providers.yaml`` default_model.
5. MVP baseline defaults: anthropic / claude-sonnet-3.5.

API key resolution:
1. ``api_key`` kwarg -> 2. ``ORYA_LLM_API_KEY`` env -> 3. provider-specific
   env var from ``providers.yaml`` (e.g. ``DEEPSEEK_API_KEY``) -> 4. user
   config ``llm.providers.{name}.api_key`` (with ``${ENV_VAR}`` substitution)
   -> 5. ``api_key_placeholder`` for local servers -> fail-fast.
"""

from __future__ import annotations

import os
from typing import Any

from langchain_core.language_models import BaseChatModel

from app.core.llm import settings as llm_settings
from app.core.llm.registry import (
    ProviderSpec,
    load_models,
    load_pricing,
    load_providers,
    resolve_model,
)

DEFAULT_PROVIDER = "anthropic"
DEFAULT_MODEL = "claude-sonnet-3.5"


def _get_builder(adapter: str):
    from app.core.llm.adapters import (
        build_anthropic,
        build_gemini,
        build_openai_compat,
    )

    if adapter == "anthropic":
        return build_anthropic
    if adapter == "openai":
        # Native OpenAI is also ChatOpenAI; init path via openai_compat with
        # the provider base_url from providers.yaml.
        return build_openai_compat
    if adapter == "google_genai":
        return build_gemini
    if adapter == "openai_compat":
        return build_openai_compat
    raise ValueError(
        f"Unknown adapter '{adapter}' in providers.yaml — expected one of "
        f"anthropic | openai | google_genai | openai_compat"
    )


def _resolve_provider_name(provider: str | None) -> str:
    """Resolve provider: arg -> env -> user config -> alias hint -> default."""
    if provider:
        return provider
    settings = llm_settings.get_settings()
    if settings.llm_provider:
        return settings.llm_provider
    block = llm_settings.llm_block()
    if block.get("default_provider"):
        return str(block["default_provider"])
    return DEFAULT_PROVIDER


def _resolve_model_name(provider: str, model: str | None) -> str:
    """Resolve model: arg -> env -> user config -> provider default_model."""
    if model:
        return model
    settings = llm_settings.get_settings()
    if settings.llm_model:
        return settings.llm_model
    block = llm_settings.llm_block()
    if block.get("default_model"):
        return str(block["default_model"])
    providers = load_providers()
    if provider in providers:
        return providers[provider].default_model
    raise ValueError(
        f"Unknown provider '{provider}' and no model given. Known providers: "
        f"{', '.join(sorted(providers))}"
    )


def _resolve_base_url(
    spec: ProviderSpec,
    base_url: str | None,
    user_config: dict,
) -> str | None:
    """base_url: arg -> ORYA_LLM_BASE_URL -> user config -> providers.yaml."""
    if base_url:
        return base_url
    settings = llm_settings.get_settings()
    if settings.llm_base_url:
        return settings.llm_base_url
    entry = llm_settings.provider_block(spec.name, user_config)
    if entry.get("base_url"):
        return str(entry["base_url"])
    return spec.base_url


def _resolve_api_key(
    spec: ProviderSpec,
    api_key: str | None,
    user_config: dict,
) -> str:
    """api_key: arg -> ORYA_LLM_API_KEY -> provider env var -> user config
    -> placeholder (local servers). Fail-fast with candidate env vars."""
    if api_key:
        return api_key

    settings = llm_settings.get_settings()
    if settings.llm_api_key is not None:
        return settings.llm_api_key.get_secret_value()

    candidates: list[str] = []
    if spec.env_var:
        value = os.environ.get(spec.env_var)
        if value:
            return value
        candidates.append(spec.env_var)

    entry = llm_settings.provider_block(spec.name, user_config)
    configured = entry.get("api_key")
    if isinstance(configured, str) and not llm_settings.is_unresolved(configured):
        return configured

    if spec.api_key_placeholder:
        return spec.api_key_placeholder

    hint = f" Set one of: {', '.join(candidates)}." if candidates else ""
    raise ValueError(
        f"No API key found for provider '{spec.name}'.{hint} You can also set "
        f"ORYA_LLM_API_KEY or add llm.providers.{spec.name}.api_key to "
        f"~/.orya/config.yaml (use ${{ENV_VAR}} placeholders — never plaintext)."
    )


def _check_capabilities(
    provider: str,
    model_alias: str,
    supports_tools: bool,
    suggests: str | None,
    require_tools: bool,
) -> None:
    """Fail fast when a reasoning model without tool-calling is requested."""
    if require_tools and not supports_tools:
        hint = f" Use '{suggests}' instead" if suggests else " Pick a chat/coding model"
        raise ValueError(
            f"Model '{model_alias}' (provider: {provider}) does not support "
            f"tool-calling (supports_tools=false).{hint}, or call "
            f"get_llm(..., require_tools=False) for plain chat without tools."
        )


def get_llm(
    provider: str | None = None,
    model: str | None = None,
    *,
    api_key: str | None = None,
    base_url: str | None = None,
    require_tools: bool = True,
    **kwargs: Any,
) -> BaseChatModel:
    """Construct a chat model for the given provider/model (the LLM seam).

    Args:
        provider: Provider key from providers.yaml (e.g. "deepseek").
            Resolved via env/config when omitted.
        model: Model alias from models.yaml or raw model_id.
        api_key: Explicit API key override.
        base_url: Explicit endpoint override (OpenAI-compatible providers).
        require_tools: When True (default), fail fast if the model does not
            support tool-calling. Pass False for plain-chat fallback with
            reasoning models (DeepSeek-R1, o1, GLM-Zero, ...).
        **kwargs: Passed through to the underlying chat model constructor
            (temperature, max_tokens, timeout, ...).

    Returns:
        A ``BaseChatModel`` instance (construction does not hit the network).

    Raises:
        ValueError: Unknown provider/model, missing API key, or a
            tool-calling capability mismatch.
    """
    providers = load_providers()

    provider_name = _resolve_provider_name(provider)
    model_name = _resolve_model_name(provider_name, model)

    # Alias-first resolution: a registered alias determines the provider.
    models = load_models()
    if model_name in models:
        alias_spec = models[model_name]
        if provider and provider != alias_spec.provider:
            raise ValueError(
                f"Model alias '{model_name}' belongs to provider "
                f"'{alias_spec.provider}', not '{provider}'"
            )
        provider_name = alias_spec.provider

    if provider_name not in providers:
        raise ValueError(
            f"Unknown provider '{provider_name}'. Known providers: "
            f"{', '.join(sorted(providers))}"
        )
    spec = providers[provider_name]

    resolved = resolve_model(provider_name, model_name)
    _check_capabilities(
        provider=provider_name,
        model_alias=model_name,
        supports_tools=resolved.supports_tools,
        suggests=resolved.suggests,
        require_tools=require_tools,
    )

    user_config = llm_settings.load_expanded_user_config()
    key = _resolve_api_key(spec, api_key, user_config)
    url = _resolve_base_url(spec, base_url, user_config)

    builder = _get_builder(spec.adapter)
    build_kwargs: dict[str, Any] = dict(kwargs)

    if spec.adapter in ("openai", "openai_compat"):
        extra = dict(spec.extra_headers)
        entry = llm_settings.provider_block(spec.name, user_config)
        if isinstance(entry.get("extra_headers"), dict):
            extra.update(entry["extra_headers"])
        return builder(
            model_id=resolved.model_id,
            api_key=key,
            base_url=url or "",
            extra_headers=extra or None,
            **build_kwargs,
        )

    if spec.adapter == "anthropic":
        return builder(model_id=resolved.model_id, api_key=key, **build_kwargs)

    # google_genai
    return builder(model_id=resolved.model_id, api_key=key, **build_kwargs)


def list_providers() -> list[dict[str, Any]]:
    """Serializable provider registry (for /llm/providers and UI pickers)."""
    settings = llm_settings.get_settings()
    user_config = llm_settings.load_expanded_user_config()
    result = []
    for name, spec in sorted(load_providers().items()):
        entry = llm_settings.provider_block(name, user_config)
        has_key = bool(api_key_available(spec, settings, entry))
        result.append(
            {
                "name": name,
                "adapter": spec.adapter,
                "base_url": spec.base_url,
                "env_var": spec.env_var,
                "default_model": spec.default_model,
                "tier": spec.tier,
                "description": spec.description,
                "has_api_key": has_key,
            }
        )
    return result


def api_key_available(spec: ProviderSpec, settings: Any, entry: dict) -> bool:
    """Whether an API key can be resolved for this provider (no fail)."""
    if settings.llm_api_key is not None:
        return True
    if spec.env_var and os.environ.get(spec.env_var):
        return True
    configured = entry.get("api_key")
    if isinstance(configured, str) and not llm_settings.is_unresolved(configured):
        return True
    if spec.api_key_placeholder:
        return True
    return False


def list_models() -> list[dict[str, Any]]:
    """Serializable model alias registry (for /llm/models and UI pickers)."""
    pricing = load_pricing()
    result = []
    for alias, spec in sorted(load_models().items()):
        price = pricing.get(spec.model_id) or pricing.get(alias)
        result.append(
            {
                "alias": spec.alias,
                "provider": spec.provider,
                "model_id": spec.model_id,
                "context_window": spec.context_window,
                "supports_tools": spec.supports_tools,
                "supports_streaming": spec.supports_streaming,
                "suggests": spec.suggests,
                "description": spec.description,
                "pricing": (
                    {
                        "input_per_1k": price.input_per_1k,
                        "output_per_1k": price.output_per_1k,
                    }
                    if price
                    else None
                ),
            }
        )
    return result
