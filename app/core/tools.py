"""Tool-registry (M-12, started by M-07).

``get_tools(session_id)`` is the single source of the agent's tool
list (architectural invariant #3, PROMPT_MVP 4): the graph, the
system-prompt builder and the UI all consume it; nothing hardcodes a
tool list.

MVP progress:

* M-07 registers ``read`` - the first of the five coding tools;
* M-08 registers ``write`` - the atomic file writer;
* M-09 registers ``edit`` - the targeted string replacement;
* M-10..M-11 add ``bash``, ``grep``/``glob`` here;
* M-12 completes the ticket (registration of all five + integration
  tests); v7 BETA wraps the list through ``CapabilityRegistry.filter``
  without changing this signature.

Usage::

    from app.core.tools import get_tools

    tools = get_tools(session_id)   # list[BaseTool]
"""

from __future__ import annotations

from langchain_core.tools import BaseTool

from app.tools.edit import edit
from app.tools.read import read
from app.tools.write import write


def get_tools(session_id: str | None = None) -> list[BaseTool]:
    """Return the tools available to the agent.

    ``session_id`` is reserved for per-session tool filtering (M-12+);
    the MVP list is global.
    """
    del session_id  # reserved for M-12 per-session filtering
    return [read, write, edit]
