"""Coding tools (M-07..M-11).

MVP ships five tools; only ``read`` exists as of M-07. The tool
registry (``app/core.tools.get_tools``) is the single source of the
full list - never hardcode tools elsewhere (PROMPT_MVP 9).
"""

from __future__ import annotations

from app.tools.read import read

__all__ = ["read"]
