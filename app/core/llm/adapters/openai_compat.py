"""Universal OpenAI-compatible adapter.

~90% of supported providers (all Chinese vendors, aggregators, local
servers, xAI) expose an OpenAI-compatible ``/v1`` endpoint. They all share
this single code-path: ``ChatOpenAI(base_url=..., api_key=..., model=...)``.
"""

from __future__ import annotations

from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_openai import ChatOpenAI


def build_openai_compat(
    model_id: str,
    api_key: str,
    base_url: str,
    extra_headers: dict[str, str] | None = None,
    **kwargs: Any,
) -> BaseChatModel:
    """Build a ChatOpenAI pointed at an OpenAI-compatible endpoint."""
    if not base_url:
        raise ValueError(
            "openai_compat adapter requires base_url — set it in providers.yaml "
            "or pass base_url explicitly"
        )
    params: dict[str, Any] = {
        "model": model_id,
        "api_key": api_key,
        "base_url": base_url,
    }
    if extra_headers:
        params["default_headers"] = dict(extra_headers)
    params.update(kwargs)
    return ChatOpenAI(**params)
