"""Ollama local test — runs only when the server is up AND the model is pulled."""

import pytest

from tests.integration._helpers import ollama_model_available, ping_llm

MODEL = "qwen2.5-coder:14b"

pytestmark = pytest.mark.skipif(
    not ollama_model_available(MODEL),
    reason=f"Ollama not running or model {MODEL} not pulled (ollama pull {MODEL})",
)


@pytest.mark.asyncio
async def test_ollama_ping():
    text = await ping_llm("ollama", "ollama-coder")
    assert text, "empty response from Ollama"
