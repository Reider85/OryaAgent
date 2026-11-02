"""Anthropic adapter — native LangChain ``ChatAnthropic`` via init_chat_model."""

from __future__ import annotations

import logging
from typing import Any

import anthropic
from langchain.chat_models import init_chat_model
from langchain_core.language_models import BaseChatModel

logger = logging.getLogger(__name__)


def build_anthropic(
    model_id: str,
    api_key: str,
    pool_client: Any = None,
    **kwargs: Any,
) -> BaseChatModel:
    """Build a ChatAnthropic instance (no network call at construction).

    ``pool_client`` (A-20): ``ChatAnthropic`` has no public http-client
    parameter, so the pooled transport is injected through the SDK's own
    ``_client_params`` (langchain-anthropic builds ``anthropic.AsyncClient``
    from exactly those params — replicating them here cannot drift). The
    pooled client must be an ``httpx2.AsyncClient`` — anthropic>=1.15
    rejects plain ``httpx`` objects. Any failure degrades to the stock
    client (fail-open, never breaks the factory).
    """
    # Enable cache_control for prompt caching
    kwargs.setdefault("cache_control", "ephemeral")
    instance = init_chat_model(
        model_id,
        model_provider="anthropic",
        anthropic_api_key=api_key,
        **kwargs,
    )
    if pool_client is None:
        return instance
    try:
        params = dict(instance._client_params)
        params["http_client"] = pool_client
        # Pre-seed the cached property so the model reuses our keepalive
        # transport for every subsequent ainvoke (bind_tools keeps it).
        instance.__dict__["_async_client"] = anthropic.AsyncClient(**params)
    except Exception:  # noqa: BLE001 - fail-open wiring
        logger.warning(
            "anthropic pool_client injection failed; using the stock client",
            exc_info=True,
        )
    return instance
