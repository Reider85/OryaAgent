"""MCP client configuration for B-02 oriahs_search tool.

Provides configuration management for MCP server connection.
"""

from __future__ import annotations

import os
from typing import Any

from app.mcp.client import MCPClientConfig


def get_mcp_config() -> MCPClientConfig:
    """Get MCP client configuration from environment or defaults."""
    return MCPClientConfig(
        server_url=os.getenv("MCP_SERVER_URL", "http://localhost:8765"),
        auth_token=os.getenv("MCP_AUTH_TOKEN"),
        timeout=float(os.getenv("MCP_TIMEOUT", "10.0")),
        max_retries=int(os.getenv("MCP_MAX_RETRIES", "3")),
    )


def get_oriahs_config() -> dict[str, Any]:
    """Get OriaHS backend configuration."""
    return {
        "base_url": os.getenv("ORIAHS_BASE_URL", "http://localhost:8000"),
        "token": os.getenv("ORIAHS_TOKEN"),
        "timeout": float(os.getenv("ORIAHS_TIMEOUT", "10.0")),
        "max_retries": int(os.getenv("ORIAHS_MAX_RETRIES", "3")),
    }


# Configuration for fallback behavior
FALLBACK_CONFIG = {
    "enabled": os.getenv("ORIAHS_SEARCH_FALLBACK_ENABLED", "true").lower() == "true",
    "fallback_to_grep": os.getenv("ORIAHS_SEARCH_FALLBACK_TO_GREP", "true").lower()
    == "true",
    "max_cache_ttl": int(os.getenv("ORIAHS_SEARCH_CACHE_TTL", "3600")),  # 1 hour
    "max_results": int(os.getenv("ORIAHS_SEARCH_MAX_RESULTS", "50")),
    "default_top_k": int(os.getenv("ORIAHS_SEARCH_DEFAULT_TOP_K", "10")),
}
