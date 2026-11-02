"""Google Gemini adapter — native LangChain via init_chat_model."""

from __future__ import annotations

import logging
from typing import Any

import httpx
from langchain.chat_models import init_chat_model
from langchain_core.language_models import BaseChatModel

logger = logging.getLogger(__name__)


def build_gemini(
    model_id: str,
    api_key: str,
    pool_client: httpx.AsyncClient | None = None,
    **kwargs: Any,
) -> BaseChatModel:
    """Build a ChatGoogleGenerativeAI instance (no network call at construction).

    ``pool_client`` (A-20): the google-genai SDK takes a ready
    ``httpx.AsyncClient`` via ``HttpOptions(httpx_async_client=...)``.
    The stock client langchain built is replaced with an equivalent one
    that shares the pooled transport; any failure degrades to the stock
    client (fail-open, never breaks the factory).
    """
    instance = init_chat_model(
        model_id,
        model_provider="google_genai",
        google_api_key=api_key,
        **kwargs,
    )
    if pool_client is None:
        return instance
    try:
        from google.genai import Client as GenAIClient
        from google.genai.types import HttpOptions

        stock = instance.client
        if stock is None:
            return instance
        http_options = HttpOptions(httpx_async_client=pool_client)
        instance.client = GenAIClient(
            api_key=api_key,
            http_options=http_options,
        )
    except Exception:  # noqa: BLE001 - fail-open wiring
        logger.warning(
            "google pool_client injection failed; using the stock client",
            exc_info=True,
        )
    return instance
