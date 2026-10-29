"""LLM registry endpoints: /llm/providers, /llm/models, /llm/health/{provider}."""

from __future__ import annotations

import os

from fastapi import APIRouter, HTTPException

from app.core.llm.adapters import check_health
from app.core.llm.factory import list_models, list_providers
from app.core.llm.registry import load_providers
from app.core.llm.remote import (
    MissingApiKeyError,
    RemoteModelsError,
    UnknownProviderError,
    fetch_remote_models,
)

router = APIRouter(prefix="/llm", tags=["llm"])


@router.get("/providers")
async def providers() -> dict:
    """Declarative provider registry from providers.yaml."""
    return {"providers": list_providers()}


@router.get("/models")
async def models() -> dict:
    """Declarative model alias registry from models.yaml."""
    return {"models": list_models()}


@router.get("/models/remote/{provider}")
async def remote_models(provider: str) -> dict:
    """Live model list from the provider's OpenAI-compatible /models endpoint.

    200 on success; 404 unknown provider; 400 no API key; 503 unreachable.
    """
    try:
        return await fetch_remote_models(provider)
    except UnknownProviderError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except MissingApiKeyError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RemoteModelsError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


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

    api_key = os.environ.get(spec.env_var) if spec.env_var else None
    if spec.adapter == "anthropic":
        headers = {"x-api-key": api_key or "", "anthropic-version": "2023-06-01"}
        result = await check_health(
            spec.base_url, health_path=spec.health_path, headers=headers
        )
    else:
        result = await check_health(
            spec.base_url, health_path=spec.health_path, api_key=api_key
        )

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
