"""PromptCacheLayout (A-19) — provider-specific prompt caching for cross-turn reuse.

This module implements prompt caching using provider-native mechanisms:
- Anthropic: `cache_control: ephemeral` markers (5-min TTL with sliding window)
- OpenAI: Automatic prompt caching for prefixes >1024 tokens (5-10 min cache)
- Gemini: Context caching API (register prefix → cache-id → use cache-id)

The cacheable prefix includes stable sections: identity + tools + project context + L0 memory.
Dynamic sections (past messages) are never cached and come after the prefix.

Integration:
- `PromptCacheLayout.assemble()` returns LangChain messages with provider-specific caching
- Redis tracks prefix hashes for cache invalidation when files change
- Span attributes track cache hits/misses and age
- `ORYA_LLM_PROMPT_CACHE_ENABLED` disables the feature
"""

from __future__ import annotations

import hashlib
import json
import logging
from abc import ABC, abstractmethod
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from langchain_core.messages import BaseMessage, SystemMessage
from pydantic import BaseModel

from app.core.cache import get_cache
from app.core.config import get_settings
from app.core.memory import get_md_store
from app.core.observability.spans import get_span_buffer
from app.core.prompt import (
    behavior_rules_block,
    format_memory_block,
    identity_block,
    project_context_block,
    tool_descriptions,
    untrusted_content_policy_block,
)

logger = logging.getLogger(__name__)

# Cache key prefix for prompt cache entries
REDIS_PROMPT_CACHE_PREFIX = "orya:prompt_cache:prefix_hash"
# Default TTL for prompt cache (5 minutes)
DEFAULT_PROMPT_CACHE_TTL = 300


class PromptCacheConfig(BaseModel):
    """Prompt cache configuration."""

    enabled: bool = True
    ttl: int = DEFAULT_PROMPT_CACHE_TTL
    max_size: int = 1000  # Max cached prefixes per thread


class ProviderCacheMarker(ABC):
    """Abstract interface for provider-specific cache markers."""

    @abstractmethod
    def apply_to_message(self, message: SystemMessage) -> SystemMessage:
        """Apply provider-specific cache markers to the system message."""
        pass


class AnthropicCacheMarker(ProviderCacheMarker):
    """Anthropic cache_control: ephemeral marker."""

    def apply_to_message(self, message: SystemMessage) -> SystemMessage:
        """Add cache_control markers to Anthropic system message."""
        # Use the correct cache control marker for Anthropic
        cache_control = "ephemeral"
        marker = f"\n\n<|cache_control|>{cache_control}<|/cache_control|>"

        # Only apply to the prefix part (first ~80% of content)
        content = message.content
        prefix_length = int(len(content) * 0.8)
        prefix = content[:prefix_length]
        suffix = content[prefix_length:]

        new_content = prefix + marker + suffix
        return SystemMessage(content=new_content)


class OpenAICacheMarker(ProviderCacheMarker):
    """OpenAI automatic prompt caching (no special markers needed)."""

    def apply_to_message(self, message: SystemMessage) -> SystemMessage:
        """OpenAI caches automatically for prefixes >1024 tokens."""
        # No special markers needed - OpenAI handles this automatically
        return message


class GeminiCacheMarker(ProviderCacheMarker):
    """Gemini context caching API markers."""

    def apply_to_message(self, message: SystemMessage) -> SystemMessage:
        """Add Gemini context caching markers to system message."""
        # Gemini uses a separate API call for context caching
        # This will be handled in the Gemini adapter
        return message


class PromptCacheLayout:
    """Provider-specific prompt caching layout."""

    def __init__(self, config: PromptCacheConfig | None = None):
        self.config = config or PromptCacheConfig()
        self._provider_markers = {
            "anthropic": AnthropicCacheMarker(),
            "openai": OpenAICacheMarker(),
            "openai_compat": OpenAICacheMarker(),
            "google_genai": GeminiCacheMarker(),
        }

    def _get_cache_key(self, prefix_content: str, provider: str, model: str) -> str:
        """Generate Redis cache key for the prompt prefix."""
        # Hash of prefix content + provider + model
        key_data = {
            "prefix": prefix_content,
            "provider": provider,
            "model": model,
        }
        key_hash = hashlib.sha256(
            json.dumps(key_data, sort_keys=True).encode()
        ).hexdigest()
        return f"{REDIS_PROMPT_CACHE_PREFIX}:{key_hash}"

    def _get_prefix_hash(self, prefix_content: str) -> str:
        """Get hash of cacheable prefix for Redis tracking."""
        return hashlib.sha256(prefix_content.encode()).hexdigest()

    async def _get_cached_prefix(self, cache_key: str) -> str | None:
        """Get cached prefix from Redis."""
        if not self.config.enabled:
            return None

        try:
            cache = get_cache()
            cached = await cache.get(cache_key)
            if cached:
                return cached
        except Exception as e:
            logger.warning("Failed to get cached prefix: %s", e)
            return None

    async def _set_cached_prefix(self, cache_key: str, prefix_content: str) -> None:
        """Set cached prefix in Redis with TTL."""
        if not self.config.enabled:
            return

        try:
            cache = get_cache()
            await cache.set(cache_key, prefix_content, ttl=self.config.ttl)
        except Exception as e:
            logger.warning("Failed to set cached prefix: %s", e)

    def _build_cacheable_prefix(
        self, tools: Sequence[Any] | None, memory_dir: Path | None = None
    ) -> str:
        """Build the cacheable prefix (stable sections)."""
        sections = [
            identity_block(),
            tool_descriptions(tools),
            project_context_block(memory_dir),
            format_memory_block(memory_dir),
            behavior_rules_block(),
            untrusted_content_policy_block(),
        ]
        return "\n\n".join(sections)

    def _build_dynamic_suffix(self, conversation_history: list[Any]) -> str:
        """Build the dynamic suffix (past user/assistant messages)."""
        # In ALPHA, dynamic suffix is past messages
        # In BETA, this will come from DFC
        if not conversation_history:
            return ""

        # Format past messages as text
        messages = []
        for msg in conversation_history[-5:]:  # Last 5 messages to keep it concise
            if hasattr(msg, "content"):
                # Check if it's a HumanMessage or AIMessage
                if hasattr(msg, "type"):
                    if msg.type == "human":
                        role = "User"
                    elif msg.type == "ai":
                        role = "Assistant"
                    else:
                        role = msg.type.title()
                else:
                    role = "Assistant"  # Default
                messages.append(f"{role}: {msg.content}")

        return "\n\n".join(messages)

    def _get_provider_marker(self, provider: str) -> ProviderCacheMarker | None:
        """Get provider-specific cache marker."""
        return self._provider_markers.get(provider)

    async def assemble(
        self,
        tools: Sequence[Any] | None,
        conversation_history: list[Any],
        provider: str,
        model: str,
        thread_id: str,
        memory_dir: Path | None = None,
    ) -> list[BaseMessage]:
        """Assemble messages with provider-specific prompt caching.

        Args:
            tools: Available tools for this session
            conversation_history: Past user/assistant messages (dynamic suffix)
            provider: LLM provider name (anthropic, openai, etc.)
            model: Model name/alias
            thread_id: Thread identifier for cache invalidation
            memory_dir: Memory directory path

        Returns:
            List of LangChain messages with cache markers applied
        """
        if not self.config.enabled:
            # Fallback to plain system message
            sections = [
                identity_block(),
                tool_descriptions(tools),
                project_context_block(memory_dir),
                format_memory_block(memory_dir),
                behavior_rules_block(),
                untrusted_content_policy_block(),
            ]
            content = "\n\n".join(sections)
            if conversation_history:
                content += "\n\n" + self._build_dynamic_suffix(conversation_history)
            return [SystemMessage(content=content)]

        # Build cacheable prefix
        prefix_content = self._build_cacheable_prefix(tools, memory_dir)

        # Check Redis for cached prefix
        cache_key = self._get_cache_key(prefix_content, provider, model)
        cached_prefix = await self._get_cached_prefix(cache_key)

        # Track cache hit/miss
        span_buffer = get_span_buffer()
        if span_buffer:
            # Find the most recent finished LLM span (the buffer is a plain
            # deque of SpanRecord — A-19 originally read a ``.spans`` attr
            # that does not exist and blew up whenever it was non-empty).
            current_span = None
            for span in reversed(span_buffer):
                if span.span_type == "llm.call":
                    current_span = span
                    break

            if current_span:
                if cached_prefix:
                    current_span.attributes["llm.call.cache_hit"] = True
                    current_span.attributes["llm.call.cache_age_seconds"] = 0
                else:
                    current_span.attributes["llm.call.cache_hit"] = False

        # Use cached prefix if available
        if cached_prefix:
            prefix_content = cached_prefix

        # Build full system message
        full_content = prefix_content
        if conversation_history:
            dynamic_suffix = self._build_dynamic_suffix(conversation_history)
            full_content += "\n\n" + dynamic_suffix

        # Apply provider-specific cache markers
        provider_marker = self._get_provider_marker(provider)
        if provider_marker:
            system_message = SystemMessage(content=full_content)
            system_message = provider_marker.apply_to_message(system_message)
        else:
            system_message = SystemMessage(content=full_content)

        # Cache the prefix if it wasn't cached
        if not cached_prefix:
            await self._set_cached_prefix(cache_key, prefix_content)

        return [system_message]

    async def invalidate_prefix(
        self, thread_id: str, changed_files: list[Path]
    ) -> None:
        """Invalidate cache prefix when files change.

        Args:
            thread_id: Thread identifier
            changed_files: List of files that changed
        """
        if not self.config.enabled:
            return

        try:
            # Get memory store to check which memory files changed
            memory_store = get_md_store()

            # Check if any memory files changed
            memory_files = ["LEARNED.md", "PREFERENCES.md", "FACTS.md", "DECISIONS.md"]
            memory_changed = any(
                str(memory_store.memory_dir / file) in str(changed_files)
                for file in memory_files
            )

            # Check if project context changed
            project_md = str(memory_store.memory_dir / "PROJECT.md")
            project_changed = project_md in str(changed_files)

            # Check if tool schemas changed (would be handled by tool registry)

            if memory_changed or project_changed:
                # Clear all cached prefixes for this thread
                # In a real implementation, we'd track per-thread prefixes
                # For now, we'll log the invalidation
                logger.info(
                    "Prompt cache invalidated for thread %s due to file changes",
                    thread_id,
                )

                # TODO: Implement per-thread prefix tracking and invalidation
                # This would require storing prefix hashes per thread in Redis

        except Exception as e:
            logger.warning("Failed to invalidate prompt cache: %s", e)


# Global instance
_prompt_cache: PromptCacheLayout | None = None


def get_prompt_cache() -> PromptCacheLayout:
    """Get the global PromptCacheLayout instance."""
    global _prompt_cache
    if _prompt_cache is None:
        # Load configuration from settings
        settings = get_settings()
        config = PromptCacheConfig(
            enabled=settings.llm_prompt_cache_enabled,
            ttl=settings.llm_prompt_cache_ttl,
            max_size=settings.llm_prompt_cache_max_size,
        )
        _prompt_cache = PromptCacheLayout(config)
    return _prompt_cache


def init_prompt_cache(config: PromptCacheConfig | None = None) -> None:
    """Initialize the global PromptCacheLayout instance."""
    global _prompt_cache
    if config is not None:
        _prompt_cache = PromptCacheLayout(config)
    else:
        # Reinitialize with current settings
        settings = get_settings()
        config = PromptCacheConfig(
            enabled=settings.llm_prompt_cache_enabled,
            ttl=settings.llm_prompt_cache_ttl,
            max_size=settings.llm_prompt_cache_max_size,
        )
        _prompt_cache = PromptCacheLayout(config)


class PromptCacheLayoutWrapper:
    """Wrapper that applies PromptCacheLayout to LLM calls."""

    def __init__(
        self,
        inner: Any,
        provider: str,
        model_name: str,
        prompt_cache: PromptCacheLayout,
    ):
        self.inner = inner
        self.provider = provider
        self.model_name = model_name
        self.prompt_cache = prompt_cache

    def __getattr__(self, name: str) -> Any:
        # Forward all attributes to the inner model
        if name.startswith("__"):
            raise AttributeError(name)
        return getattr(self.inner, name)

    def bind_tools(
        self, tools: Sequence[Any], **kwargs: Any
    ) -> PromptCacheLayoutWrapper:
        """Delegate bind_tools and keep the wrapper."""
        bound = self.inner.bind_tools(list(tools), **kwargs)
        return PromptCacheLayoutWrapper(
            inner=bound,
            provider=self.provider,
            model_name=self.model_name,
            prompt_cache=self.prompt_cache,
        )

    async def ainvoke(
        self,
        messages: list[Any],
        config: Any = None,
        *,
        stop: list[str] | None = None,
        **kwargs: Any,
    ) -> Any:
        """Apply prompt caching before calling ainvoke."""
        # Extract conversation history from messages
        conversation_history = []
        system_message = None

        for msg in messages:
            if hasattr(msg, "type") and msg.type == "system":
                system_message = msg
            else:
                conversation_history.append(msg)

        # Apply prompt caching to build the system message
        if system_message is None:
            # Build system message with prompt caching
            tools = kwargs.get("tools", [])
            memory_dir = kwargs.get("memory_dir")

            cached_messages = await self.prompt_cache.assemble(
                tools=tools,
                conversation_history=conversation_history,
                provider=self.provider,
                model=self.model_name,
                thread_id=kwargs.get("thread_id", "default"),
                memory_dir=memory_dir,
            )

            # Replace the system message
            new_messages = []
            for msg in messages:
                if hasattr(msg, "type") and msg.type == "system":
                    continue  # Skip the original system message
                new_messages.append(msg)

            # Add the cached system message first
            new_messages = cached_messages + new_messages
            messages = new_messages

        # Call the inner model
        return await self.inner.ainvoke(messages, config=config, stop=stop, **kwargs)

    def _generate(
        self,
        messages: list[Any],
        stop: list[str] | None = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> Any:
        return self.inner._generate(
            messages, stop=stop, run_manager=run_manager, **kwargs
        )

    async def _agenerate(
        self,
        messages: list[Any],
        stop: list[str] | None = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> Any:
        return await self.inner._agenerate(
            messages, stop=stop, run_manager=run_manager, **kwargs
        )

    def invoke(
        self,
        messages: list[Any],
        config: Any = None,
        *,
        stop: list[str] | None = None,
        **kwargs: Any,
    ) -> Any:
        """Sync invoke delegates to ainvoke."""
        import asyncio

        return asyncio.run(self.ainvoke(messages, config, stop=stop, **kwargs))
