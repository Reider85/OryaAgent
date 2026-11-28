"""Tool: OriaHS readiness probe (P-00).

Reports both the direct OriaHS backend (``GET /health/ready``) and the
``oriahs-mcp`` facade. Degradation is returned as plain text — never as a
ToolException — so the agent stream stays normal per the PROD priority
postulate.
"""

from __future__ import annotations

from typing import Annotated

from langchain_core.tools import tool

from app.core.oriahs_client import ORIAHS_FALLBACK_MESSAGE, get_oriahs_client
from app.mcp.client import get_mcp_client


@tool
async def oriahs_health(
    detail: Annotated[bool, "Include per-dependency readiness checks"] = False,
) -> str:
    """Check whether the OriaHS backend and its MCP facade are reachable."""
    backend = await get_oriahs_client().health()
    facade_ok = await get_mcp_client().health_check()

    lines = [
        f"OriaHS backend: {backend.status} ({backend.latency_ms:.0f} ms)",
        f"oriahs-mcp facade: {'ok' if facade_ok else 'unavailable'}",
    ]
    if detail and backend.checks:
        checks = ", ".join(f"{name}={value}" for name, value in backend.checks.items())
        lines.append(f"Checks: {checks}")
    if not backend.ok or not facade_ok:
        lines.append(f"Fallback: {ORIAHS_FALLBACK_MESSAGE}")
    return "\n".join(lines)
