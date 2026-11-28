"""MCP client configuration for P-00 (B-02 oriahs_search tool).

``get_settings()`` is the single source of truth; the historical
``MCP_*`` / ``ORIAHS_*`` names remain working as validation aliases on
:class:`~app.core.config.Settings`.
"""

from __future__ import annotations

from typing import Any

from app.core.config import get_settings
from app.mcp.client import MCPClientConfig


def get_mcp_config() -> MCPClientConfig:
    """Build the oriahs-mcp facade client config from effective settings."""
    settings = get_settings()
    return MCPClientConfig(
        server_url=settings.mcp_server_url,
        auth_token=(
            settings.mcp_auth_token.get_secret_value()
            if settings.mcp_auth_token is not None
            else None
        ),
        timeout=settings.mcp_timeout_s,
        max_retries=settings.mcp_max_retries,
    )


def get_oriahs_config() -> dict[str, Any]:
    """OriaHS backend settings (backward-compatible dict form)."""
    settings = get_settings()
    return {
        "base_url": settings.oriahs_url,
        "token": (
            settings.oriahs_token.get_secret_value()
            if settings.oriahs_token is not None
            else None
        ),
        "timeout": settings.oriahs_timeout_s,
        "max_retries": settings.mcp_max_retries,
        "tenant_id": settings.oriahs_tenant_id,
    }


def get_fallback_config() -> dict[str, Any]:
    """Search fallback/cache knobs (import-time env reads kept for B-02)."""
    import os

    return {
        "enabled": os.getenv("ORIAHS_SEARCH_FALLBACK_ENABLED", "true").lower()
        == "true",
        "fallback_to_grep": os.getenv("ORIAHS_SEARCH_FALLBACK_TO_GREP", "true").lower()
        == "true",
        "max_cache_ttl": int(os.getenv("ORIAHS_SEARCH_CACHE_TTL", "3600")),
        "max_results": int(os.getenv("ORIAHS_SEARCH_MAX_RESULTS", "50")),
        "default_top_k": int(os.getenv("ORIAHS_SEARCH_DEFAULT_TOP_K", "10")),
    }


# Kept as a module attribute for callers written against the B-02 API.
FALLBACK_CONFIG = get_fallback_config()
