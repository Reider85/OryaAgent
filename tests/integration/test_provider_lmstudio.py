"""LM Studio local test — runs only when the configured model is loaded."""

import pytest

from tests.integration._helpers import lmstudio_model_available, ping_llm

MODEL = "qwen2.5-coder-7b-instruct"  # models.yaml alias lmstudio-coder

pytestmark = pytest.mark.skipif(
    not lmstudio_model_available(MODEL),
    reason=(f"LM Studio not running on localhost:1234 or model {MODEL} not loaded"),
)


@pytest.mark.asyncio
async def test_lmstudio_ping():
    text = await ping_llm("lmstudio", "lmstudio-coder")
    assert text, "empty response from LM Studio"
