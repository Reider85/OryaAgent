"""Provider adapters for the LLM seam.

Each adapter builds a ``BaseChatModel`` for one code-path:
- ``anthropic`` / ``openai`` / ``google_genai`` -> langchain ``init_chat_model``
  with the native partner package.
- ``openai_compat`` -> ``ChatOpenAI(base_url=...)`` — universal path used by
  all Chinese providers, aggregators and local servers.

Business logic must never import partner packages directly — only via
``app.core.llm.get_llm()``.
"""

from __future__ import annotations

from app.core.llm.adapters.anthropic import build_anthropic
from app.core.llm.adapters.gemini import build_gemini
from app.core.llm.adapters.local import build_health_url, check_health
from app.core.llm.adapters.openai_compat import build_openai_compat

__all__ = [
    "build_anthropic",
    "build_gemini",
    "build_health_url",
    "build_openai_compat",
    "check_health",
]
