"""Tool-registry (M-12, started by M-07).

``get_tools(session_id)`` is the single source of the agent's tool
list (architectural invariant #3, PROMPT_MVP 4): the graph, the
system-prompt builder and the UI all consume it; nothing hardcodes a
tool list.

MVP progress:

* M-07 registers ``read`` - the first of the coding tools;
* M-08 registers ``write`` - the atomic file writer;
* M-09 registers ``edit`` - the targeted string replacement;
* M-10 registers ``bash`` - the shell command tool;
* M-11 registers ``grep``/``glob`` - the ripgrep-backed search tools;
* M-12 completes the ticket: the full six-tool list is covered by
  integration tests (``tests/integration/test_tools_integration.py``);
  v7 BETA wraps the list through ``CapabilityRegistry.filter`` without
  changing this signature.

Usage::

    from app.core.tools import get_tools

    tools = get_tools(session_id)   # list[BaseTool]
"""

from __future__ import annotations

from langchain_core.tools import BaseTool

from app.tools.bash import bash
from app.tools.edit import edit
from app.tools.glob import glob
from app.tools.grep import grep
from app.tools.lsp import (
    lsp_code_action,
    lsp_definition,
    lsp_diagnostics,
    lsp_hover,
    lsp_references,
    lsp_rename,
    lsp_symbol_search,
)
from app.tools.oriahs_index import oriahs_index
from app.tools.oriahs_search import oriahs_search
from app.tools.read import read
from app.tools.retrieval_orchestrate import retrieval_orchestrate
from app.tools.ukb import ukb_lookup
from app.tools.write import write


def get_tools(session_id: str | None = None) -> list[BaseTool]:
    """Return the tools available to the agent.

    Updated for BETA to include semantic search, indexing, LSP tools, and retrieval orchestration.
    ``session_id`` is reserved for per-session tool filtering (M-13+ /
    v7 BETA ``CapabilityRegistry``); the MVP list is global.
    """
    # Get all available tools
    all_tools = [
        read,
        write,
        edit,
        bash,
        grep,
        glob,
        oriahs_search,
        oriahs_index,
        lsp_hover,
        lsp_definition,
        lsp_references,
        lsp_symbol_search,
        lsp_rename,
        lsp_diagnostics,
        lsp_code_action,
        ukb_lookup,
        retrieval_orchestrate,
    ]

    # Apply CapabilityRegistry filtering if session_id is provided
    if session_id:
        from app.core.tools.capability_registry import get_capability_registry
        from app.core.tools.context import TurnContext

        registry = get_capability_registry()

        # Create context from session state
        # Note: This is a simplified context creation
        # In a real implementation, you'd extract context from the actual session state
        context = TurnContext()

        # Apply filtering
        filtered_tools = registry.filter_tools(all_tools, context)
        return filtered_tools

    return all_tools
