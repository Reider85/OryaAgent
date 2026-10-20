"""Health-check helpers for local LLM servers (Ollama, LM Studio, vLLM, ...)."""

from __future__ import annotations

import time
from typing import Any

import httpx


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


async def check_ollama(base_url: str, timeout: float = 5.0) -> dict[str, Any]:
    """Ollama health: GET {host}/api/tags (not the OpenAI-compat /v1 path)."""
    host = base_url.rstrip("/").removesuffix("/v1")
    return await _get(f"{host}/api/tags", timeout=timeout)


async def check_lmstudio(base_url: str, timeout: float = 5.0) -> dict[str, Any]:
    """LM Studio health: GET {base_url}/models; warns if no model loaded."""
    result = await _get(f"{base_url.rstrip('/')}/models", timeout=timeout)
    return result


async def check_openai_compat(
    base_url: str,
    api_key: str | None = None,
    timeout: float = 5.0,
) -> dict[str, Any]:
    """Generic OpenAI-compatible health: GET {base_url}/models."""
    headers: dict[str, str] = {}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    return await _get(
        f"{base_url.rstrip('/')}/models", headers=headers, timeout=timeout
    )
