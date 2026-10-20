"""LLM-provider seam (M-01).

Public interface (architectural invariant — stable across phases):

    from app.core.llm import get_llm
    llm = get_llm("deepseek", "deepseek-chat")

New providers are added declaratively in ``providers.yaml`` — no code
changes required for OpenAI-compatible endpoints.
"""

from app.core.llm.factory import get_llm, list_models, list_providers
from app.core.llm.registry import (
    clear_registry_cache,
    load_capabilities,
    load_models,
    load_pricing,
    load_providers,
    resolve_model,
)

__all__ = [
    "get_llm",
    "list_models",
    "list_providers",
    "load_providers",
    "load_models",
    "load_capabilities",
    "load_pricing",
    "resolve_model",
    "clear_registry_cache",
]
