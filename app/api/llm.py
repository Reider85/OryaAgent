"""LLM registry endpoints: /llm/providers, /llm/models, /llm/health/{provider}."""

from __future__ import annotations

import os
import time

import httpx
from fastapi import APIRouter, HTTPException

from app.core.llm.adapters import check_lmstudio, check_ollama, check_openai_compat
from app.core.llm.factory import list_models, list_providers
from app.core.llm.registry import load_providers

router = APIRouter(prefix="/llm", tags=["llm"])


@router.get("/providers")
async def providers() -> dict:
    """Declarative provider registry from providers.yaml."""
    return {"providers": list_providers()}


@router.get("/models")
async def models() -> dict:
    """Declarative model alias registry from models.yaml."""
    return {"models": list_models()}


@router.get("/health/{provider}")
async def health(provider: str) -> dict:
    """Check that a provider endpoint is reachable (5s timeout).

    Returns 200 when reachable, 503 otherwise (DoD: status 200 iff available).
    """
    registry = load_providers()
    spec = registry.get(provider)
    if spec is None:
        raise HTTPException(
            status_code=404,
            detail=f"Unknown provider '{provider}'. Known: {', '.join(sorted(registry))}",
        )

    if spec.base_url is None:
        raise HTTPException(
            status_code=400, detail=f"Provider '{provider}' has no base_url"
        )

    if provider == "ollama":
        result = await check_ollama(spec.base_url)
    elif provider == "lmstudio":
        result = await check_lmstudio(spec.base_url)
    elif spec.adapter in ("openai", "openai_compat"):
        api_key = os.environ.get(spec.env_var) if spec.env_var else None
        result = await check_openai_compat(spec.base_url, api_key=api_key)
    elif spec.adapter == "anthropic":
        api_key = os.environ.get(spec.env_var) if spec.env_var else None
        headers = {"x-api-key": api_key or "", "anthropic-version": "2023-06-01"}
        started = time.monotonic()
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(
                    f"{spec.base_url.rstrip('/')}/v1/models", headers=headers
                )
            result = {
                "ok": resp.is_success,
                "status_code": resp.status_code,
                "latency_ms": round((time.monotonic() - started) * 1000, 1),
                "detail": "" if resp.is_success else resp.text[:200],
            }
        except httpx.HTTPError as exc:
            result = {
                "ok": False,
                "status_code": None,
                "latency_ms": round((time.monotonic() - started) * 1000, 1),
                "detail": str(exc),
            }
    else:
        result = await check_openai_compat(spec.base_url)

    body = {
        "provider": provider,
        "status": "ok" if result["ok"] else "unreachable",
        "latency_ms": result["latency_ms"],
        "base_url": spec.base_url,
    }
    if not result["ok"]:
        body["detail"] = result["detail"]
        body["status_code"] = result["status_code"]
        # Hint for local servers
        if spec.tier == "local":
            body["hint"] = (
                "Local server is not running — start it first "
                "(e.g. `ollama serve` for Ollama)."
            )
        raise HTTPException(status_code=503, detail=body)
    return body
