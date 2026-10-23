"""Coding tools (M-07..M-11).

MVP ships five tools; ``read`` (M-07), ``write`` (M-08), ``edit`` (M-09)
and ``bash`` (M-10) exist so far. The tool registry (``app/core.tools.get_tools``)
is the single source of the full list - never hardcode tools elsewhere
(PROMPT_MVP 9).
"""

from __future__ import annotations

from app.tools.bash import bash
from app.tools.edit import edit
from app.tools.read import read
from app.tools.write import write

__all__ = ["bash", "edit", "read", "write"]
