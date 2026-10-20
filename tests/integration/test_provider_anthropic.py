"""Live Anthropic test (skipped when ANTHROPIC_API_KEY is not set)."""

import pytest

from tests.integration._helpers import ping_llm, require_env

pytestmark = require_env("ANTHROPIC_API_KEY")


@pytest.mark.asyncio
async def test_anthropic_ping():
    text = await ping_llm("anthropic", "claude-sonnet-3.5")
    assert text, "empty response from Anthropic"
