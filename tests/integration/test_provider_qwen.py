"""Live Qwen/DashScope test (skipped when DASHSCOPE_API_KEY is not set)."""

import os

import pytest

from tests.integration._helpers import ping_llm

_KEY = os.getenv("DASHSCOPE_API_KEY") or os.getenv("QWEN_API_KEY")

pytestmark = pytest.mark.skipif(
    not _KEY, reason="DASHSCOPE_API_KEY not set — skipping live provider test"
)


@pytest.mark.asyncio
async def test_qwen_ping():
    text = await ping_llm("qwen", "qwen-plus", api_key=_KEY)
    assert text, "empty response from Qwen"
