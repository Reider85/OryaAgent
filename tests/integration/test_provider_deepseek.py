"""Live DeepSeek test (skipped when DEEPSEEK_API_KEY is not set)."""

import pytest

from tests.integration._helpers import ping_llm, require_env

pytestmark = require_env("DEEPSEEK_API_KEY")


@pytest.mark.asyncio
async def test_deepseek_ping():
    text = await ping_llm("deepseek", "deepseek-chat")
    assert text, "empty response from DeepSeek"
