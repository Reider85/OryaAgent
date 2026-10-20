"""Live OpenRouter test (skipped when OPENROUTER_API_KEY is not set)."""

import pytest

from tests.integration._helpers import ping_llm, require_env

pytestmark = require_env("OPENROUTER_API_KEY")


@pytest.mark.asyncio
async def test_openrouter_ping():
    text = await ping_llm("openrouter", "openrouter-claude")
    assert text, "empty response from OpenRouter"
