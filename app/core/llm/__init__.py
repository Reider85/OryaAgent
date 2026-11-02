"""LLM-provider seam (M-01 + A-02).

Public interface (architectural invariant — stable across phases):

    from app.core.llm import get_llm
    llm = get_llm("deepseek", "deepseek-chat")

New providers are added declaratively in ``providers.yaml`` — no code
changes required for OpenAI-compatible endpoints.

A-02 adds span-wrapping: the factory returns a ``TracedChatModel`` that
emits an ``llm.call`` span per invocation (disable with
``ORYA_LLM_TRACE_ENABLED=false`` to get the raw provider adapter).
Since A-20 the factory also draws per-provider keepalive clients from
``ConnectionPool`` (``app.core.llm.connection_pool``; kill-switch
``CONNECTION_POOL_ENABLED=false``).
"""

from app.core.llm.connection_pool import (
    ConnectionPool,
    get_connection_pool,
    get_pool_stats,
    pool_health_worker,
    reset_connection_pool,
)
from app.core.llm.factory import get_llm, list_models, list_providers
from app.core.llm.registry import (
    clear_registry_cache,
    load_capabilities,
    load_models,
    load_pricing,
    load_providers,
    resolve_model,
)
from app.core.llm.remote import fetch_remote_models
from app.core.llm.tiered_router import TieredModelRouter, tier_models
from app.core.llm.tracing import (
    SpanRecord,
    TracedChatModel,
    clear_span_buffer,
    get_span_buffer,
    wrap_with_tracing,
)

__all__ = [
    "get_llm",
    "list_models",
    "list_providers",
    "fetch_remote_models",
    "load_providers",
    "load_models",
    "load_capabilities",
    "load_pricing",
    "resolve_model",
    "clear_registry_cache",
    "SpanRecord",
    "TracedChatModel",
    "clear_span_buffer",
    "get_span_buffer",
    "wrap_with_tracing",
    "TieredModelRouter",
    "tier_models",
    "ConnectionPool",
    "get_connection_pool",
    "get_pool_stats",
    "pool_health_worker",
    "reset_connection_pool",
]
