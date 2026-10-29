"""Health-check helpers for local LLM servers (Ollama, LM Studio, vLLM, ...).

The URL to probe is declarative: ``ProviderSpec.health_path`` from
``providers.yaml`` joined to the server root (``base_url`` minus its
OpenAI-compat ``/v1`` suffix). No provider names are hardcoded here (MVP-POLISH-5).
"""

from __future__ import annotations

import time
from typing import Any

import httpx

DEFAULT_HEALTH_PATH = "/v1/models"


def build_health_url(base_url: str, health_path: str | None = None) -> str:
    """Join the server root with ``health_path`` (default: ``/v1/models``).

    The server root is ``base_url`` without a trailing OpenAI-compat ``/v1``
    suffix, so ``health_path`` may address any endpoint on the server
    (e.g. Ollama's native ``/api/tags``).
    """
    root = base_url.rstrip("/").removesuffix("/v1")
    return f"{root}{health_path or DEFAULT_HEALTH_PATH}"


async def _get(
    url: str, headers: dict[str, str] | None = None, timeout: float = 5.0
) -> dict[str, Any]:
    started = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.get(url, headers=headers)
        latency_ms = round((time.monotonic() - started) * 1000, 1)
        return {
            "ok": resp.is_success,
            "status_code": resp.status_code,
            "latency_ms": latency_ms,
            "detail": "" if resp.is_success else resp.text[:200],
        }
    except httpx.HTTPError as exc:
        latency_ms = round((time.monotonic() - started) * 1000, 1)
        return {
            "ok": False,
            "status_code": None,
            "latency_ms": latency_ms,
            "detail": str(exc),
        }


async def check_health(
    base_url: str,
    *,
    health_path: str | None = None,
    api_key: str | None = None,
    headers: dict[str, str] | None = None,
    timeout: float = 5.0,
) -> dict[str, Any]:
    """GET the provider health URL (``build_health_url``) and report reachability.

    ``headers`` takes precedence (e.g. Anthropic's ``x-api-key``); otherwise a
    ``Bearer`` auth header is added when ``api_key`` is given.
    """
    final_headers = dict(headers or {})
    if api_key and "Authorization" not in final_headers:
        final_headers["Authorization"] = f"Bearer {api_key}"
    return await _get(
        build_health_url(base_url, health_path),
        headers=final_headers or None,
        timeout=timeout,
    )
