"""Live Zhipu GLM test (skipped when ZHIPUAI_API_KEY is not set)."""

import os

import pytest

from tests.integration._helpers import ping_llm

_KEY = os.getenv("ZHIPUAI_API_KEY") or os.getenv("GLM_API_KEY")

pytestmark = pytest.mark.skipif(
    not _KEY, reason="ZHIPUAI_API_KEY not set — skipping live provider test"
)


@pytest.mark.asyncio
async def test_glm_ping():
    text = await ping_llm("glm", "glm-4-flash", api_key=_KEY)
    assert text, "empty response from GLM"
