"""Shared helpers for provider integration tests."""

from __future__ import annotations

import os

import httpx
import pytest
from langchain_core.messages import HumanMessage


def require_env(name: str) -> pytest.MarkDecorator:
    return pytest.mark.skipif(
        not os.getenv(name),
        reason=f"{name} not set — skipping live provider test",
    )


async def ping_llm(provider: str, model: str, api_key: str | None = None) -> str:
    """One live chat round-trip; returns assistant text."""
    from app.core.llm import get_llm

    llm = get_llm(provider, model, api_key=api_key, require_tools=False)
    result = await llm.ainvoke(
        [HumanMessage(content="Reply with the single word: pong")]
    )
    text = result.content
    if isinstance(text, list):
        text = "".join(
            block if isinstance(block, str) else block.get("text", "") for block in text
        )
    return text.strip()


def local_server_up(url: str) -> bool:
    try:
        resp = httpx.get(url, timeout=2.0)
        return resp.status_code < 500
    except httpx.HTTPError:
        return False


def ollama_model_available(model: str) -> bool:
    """True if Ollama is running AND the model is pulled."""
    try:
        resp = httpx.get("http://localhost:11434/api/tags", timeout=2.0)
        resp.raise_for_status()
        names = [m.get("name", "") for m in resp.json().get("models", [])]
        return any(n == model or n.startswith(f"{model}-") for n in names)
    except (httpx.HTTPError, KeyError, ValueError):
        return False


def lmstudio_model_available(model: str) -> bool:
    """True if LM Studio server is running AND the given model id is loaded."""
    if not model:
        return False
    try:
        resp = httpx.get("http://localhost:1234/v1/models", timeout=2.0)
        resp.raise_for_status()
        ids = [m.get("id", "") for m in resp.json().get("data", [])]
        return model in ids
    except (httpx.HTTPError, KeyError, ValueError):
        return False
