"""Google Gemini adapter — native LangChain via init_chat_model."""

from __future__ import annotations

from typing import Any

from langchain.chat_models import init_chat_model
from langchain_core.language_models import BaseChatModel


def build_gemini(model_id: str, api_key: str, **kwargs: Any) -> BaseChatModel:
    """Build a ChatGoogleGenerativeAI instance (no network call at construction)."""
    return init_chat_model(
        model_id,
        model_provider="google_genai",
        google_api_key=api_key,
        **kwargs,
    )
