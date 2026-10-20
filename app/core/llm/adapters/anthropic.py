"""Anthropic adapter — native LangChain ``ChatAnthropic`` via init_chat_model."""

from __future__ import annotations

from typing import Any

from langchain.chat_models import init_chat_model
from langchain_core.language_models import BaseChatModel


def build_anthropic(model_id: str, api_key: str, **kwargs: Any) -> BaseChatModel:
    """Build a ChatAnthropic instance (no network call at construction)."""
    return init_chat_model(
        model_id,
        model_provider="anthropic",
        anthropic_api_key=api_key,
        **kwargs,
    )
