"""Health endpoints (A-04)."""

from typing import Any

from fastapi import APIRouter, HTTPException
from httpx import AsyncClient, ConnectError, HTTPStatusError, TimeoutException

from app.core.config import get_settings
from app.core.observability.spans import get_span_buffer

router = APIRouter(tags=["health"])


@router.get("/health")
async def health_check() -> dict[str, str]:
    """Health check endpoint for M-00 bootstrap verification."""
    return {"status": "ok", "message": "OryaAgent API is running"}


@router.get("/health/observability")
async def health_observability() -> dict[str, Any]:
    """Check observability subsystem health."""
    settings = get_settings()
    span_buffer = get_span_buffer()

    return {
        "sdk_enabled": settings.llm_trace_enabled,
        "exporter_connected": settings.llm_trace_exporter != "off",
        "guardrail_ready": settings.permission_audit_enabled,
        "span_buffer_size": len(span_buffer),
    }


@router.get("/health/sampler-proxy")
async def health_sampler_proxy() -> dict[str, Any]:
    """Check sampler-proxy service health."""
    settings = get_settings()

    # Empty URL means not configured
    if not settings.sampler_proxy_url:
        raise HTTPException(
            status_code=503, detail="sampler_proxy_url is not configured"
        )

    status_url = f"{settings.sampler_proxy_url.rstrip('/')}/sampler/status"

    try:
        async with AsyncClient(timeout=2.0) as client:
            response = await client.head(status_url)

            # Check if the response is successful (200 OK)
            if response.status_code == 200:
                return {
                    "status": "ok",
                    "url": settings.sampler_proxy_url,
                    "latency_ms": None,  # HEAD doesn't have timing info
                    "status_code": response.status_code,
                }
            else:
                raise HTTPException(
                    status_code=503,
                    detail=f"Sampler-proxy returned {response.status_code}",
                )

    except (ConnectError, TimeoutException) as exc:
        raise HTTPException(
            status_code=503, detail=f"Sampler-proxy unreachable: {str(exc)}"
        )
    except HTTPStatusError as exc:
        raise HTTPException(
            status_code=503, detail=f"Sampler-proxy unreachable: {str(exc)}"
        )
    except Exception as exc:
        raise HTTPException(
            status_code=503, detail=f"Sampler-proxy unexpected error: {str(exc)}"
        )
