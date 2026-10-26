"""Remote model-list auto-fetch for OpenAI-compatible providers.

Hits the provider's ``GET {base_url}/models`` endpoint (OpenAI list format)
and returns a serializable model catalog. Used by ``GET /llm/models/remote/
{provider}`` so UI pickers can show live model ids instead of the static
``models.yaml`` aliases only.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx

from app.core import config as app_config
from app.core.llm.factory import _resolve_api_key
from app.core.llm.registry import load_providers

DEFAULT_TIMEOUT_S = 10.0


class RemoteModelsError(Exception):
    """Remote model-list fetch failed (network, HTTP or payload error)."""


class UnknownProviderError(RemoteModelsError):
    """Provider key is not present in providers.yaml."""


class MissingApiKeyError(RemoteModelsError):
    """No API key could be resolved for the provider (no fail-fast placeholder)."""


def _try_api_key(spec: Any) -> str | None:
    """Best-effort key resolution via the factory chain; None when missing."""
    user_config = app_config.load_expanded_user_config()
    try:
        return _resolve_api_key(spec, None, user_config)
    except ValueError:
        return None


async def fetch_remote_models(
    provider: str, *, timeout: float = DEFAULT_TIMEOUT_S
) -> dict[str, Any]:
    """Fetch the live model list for ``provider`` (OpenAI-compatible /models).

    Returns:
        ``{provider, base_url, count, models: [{id}, ...], fetched_at}``.

    Raises:
        UnknownProviderError: ``provider`` is not in providers.yaml.
        MissingApiKeyError: no API key resolvable for the provider.
        RemoteModelsError: network failure, non-2xx response or bad payload.
    """
    providers = load_providers()
    spec = providers.get(provider)
    if spec is None:
        raise UnknownProviderError(
            f"Unknown provider '{provider}'. Known: {', '.join(sorted(providers))}"
        )
    if not spec.base_url:
        raise RemoteModelsError(f"Provider '{provider}' has no base_url")

    key = _try_api_key(spec)
    if not key:
        raise MissingApiKeyError(
            f"No API key found for provider '{provider}'. Set "
            f"{spec.env_var or 'the provider env var'} or add "
            f"llm.providers.{provider}.api_key to ~/.orya/config.yaml."
        )

    url = f"{spec.base_url.rstrip('/')}/models"
    headers = {"Authorization": f"Bearer {key}", **spec.extra_headers}
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.get(url, headers=headers)
    except httpx.HTTPError as exc:
        raise RemoteModelsError(f"GET {url} failed: {exc}") from exc
    if not resp.is_success:
        raise RemoteModelsError(
            f"GET {url} -> HTTP {resp.status_code}: {resp.text[:200]}"
        )

    try:
        payload = resp.json()
    except ValueError as exc:
        raise RemoteModelsError(f"GET {url} returned non-JSON body") from exc
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, list):
        raise RemoteModelsError(f"GET {url} payload missing 'data' list")

    ids = sorted(
        {
            entry["id"]
            for entry in data
            if isinstance(entry, dict) and isinstance(entry.get("id"), str)
        }
    )
    return {
        "provider": provider,
        "base_url": spec.base_url,
        "count": len(ids),
        "models": [{"id": model_id} for model_id in ids],
        "fetched_at": datetime.now(UTC).isoformat(),
    }
