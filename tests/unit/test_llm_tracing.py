"""A-02: get_llm() trace-wrapping — TracedChatModel + llm.call spans."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

import pytest
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from app.core.config import clear_settings_cache
from app.core.llm import get_llm
from app.core.llm.registry import clear_registry_cache
from app.core.llm.tracing import (
    TracedChatModel,
    clear_span_buffer,
    get_span_buffer,
    wrap_with_tracing,
)


class FakeChatModel(BaseChatModel):
    """Minimal inner model: returns one AIMessage with usage_metadata."""

    fail: bool = False
    input_tokens: int = 11
    output_tokens: int = 22

    @property
    def _llm_type(self) -> str:
        return "fake"

    def _generate(
        self, messages, stop=None, run_manager=None, **kwargs: Any
    ) -> ChatResult:
        if self.fail:
            raise RuntimeError("boom")
        message = AIMessage(
            content="pong",
            usage_metadata={
                "input_tokens": self.input_tokens,
                "output_tokens": self.output_tokens,
                "total_tokens": self.input_tokens + self.output_tokens,
            },
        )
        return ChatResult(generations=[ChatGeneration(message=message)])

    async def _agenerate(
        self, messages, stop=None, run_manager=None, **kwargs: Any
    ) -> ChatResult:
        return self._generate(messages, stop=stop, run_manager=run_manager, **kwargs)


@pytest.fixture(autouse=True)
def isolated_llm_config(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Sandbox config and start each test with an empty span buffer."""
    for name in list(os.environ):
        if name.startswith("ORYA_") or name in {
            "DEEPSEEK_API_KEY",
            "ANTHROPIC_API_KEY",
        }:
            monkeypatch.delenv(name, raising=False)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ORYA_CONFIG_PATH", str(tmp_path / "config.yaml"))
    clear_settings_cache()
    clear_registry_cache()
    clear_span_buffer()
    yield
    clear_span_buffer()
    clear_settings_cache()
    clear_registry_cache()


def test_disabled_returns_raw_adapter(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("ORYA_LLM_TRACE_ENABLED", "false")
    clear_settings_cache()
    llm = get_llm("deepseek", "deepseek-chat", api_key="sk-fake")
    assert not isinstance(llm, TracedChatModel)
    assert type(llm).__name__ == "ChatOpenAI"


def test_enabled_wraps_in_traced_model():
    llm = get_llm("deepseek", "deepseek-chat", api_key="sk-fake")
    assert isinstance(llm, TracedChatModel)
    assert isinstance(llm, BaseChatModel)
    # attribute forwarding keeps the seam's observable behaviour
    assert llm.model == "deepseek-chat"
    assert llm.openai_api_base == "https://api.deepseek.com/v1"
    assert llm.llm_provider == "deepseek"
    assert llm.llm_model == "deepseek-chat"


def test_wrap_with_tracing_disabled_passthrough(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("ORYA_LLM_TRACE_ENABLED", "false")
    clear_settings_cache()
    fake = FakeChatModel()
    wrapped = wrap_with_tracing(fake, provider="p", model_name="m")
    assert wrapped is fake


async def test_ainvoke_emits_span_with_usage():
    wrapped = wrap_with_tracing(
        FakeChatModel(), provider="fakeprov", model_name="fakemodel"
    )
    result = await wrapped.ainvoke([AIMessage(content="ping")])

    assert result.content == "pong"
    spans = list(get_span_buffer())
    assert len(spans) == 1
    span = spans[0]
    assert span.span_type == "llm.call"
    assert span.provider == "fakeprov"
    assert span.model == "fakemodel"
    assert span.status == "ok"
    assert span.attributes["tokens.input"] == 11
    assert span.attributes["tokens.output"] == 22
    assert span.end_time is not None


def test_invoke_sync_emits_span():
    wrapped = wrap_with_tracing(
        FakeChatModel(), provider="fakeprov", model_name="fakemodel"
    )
    result = wrapped.invoke([AIMessage(content="ping")])

    assert result.content == "pong"
    spans = list(get_span_buffer())
    assert len(spans) == 1
    assert spans[0].status == "ok"


async def test_ainvoke_error_sets_status_and_propagates():
    wrapped = wrap_with_tracing(
        FakeChatModel(fail=True), provider="fakeprov", model_name="fakemodel"
    )
    with pytest.raises(RuntimeError, match="boom"):
        await wrapped.ainvoke([AIMessage(content="ping")])

    spans = list(get_span_buffer())
    assert len(spans) == 1
    assert spans[0].status == "error"
    assert spans[0].attributes["error.type"] == "RuntimeError"


def test_bind_tools_keeps_wrapper_and_kwargs():
    llm = get_llm("deepseek", "deepseek-chat", api_key="sk-fake")
    tool_schema = {
        "type": "function",
        "function": {
            "name": "echo",
            "description": "echo the input",
            "parameters": {"type": "object", "properties": {}},
        },
    }
    bound = llm.bind_tools([tool_schema])

    assert isinstance(bound, TracedChatModel)
    assert bound is not llm
    assert bound.llm_provider == "deepseek"
    bound_names = [schema["function"]["name"] for schema in bound.kwargs["tools"]]
    assert bound_names == ["echo"]


async def test_bound_fake_span_still_emitted():
    """The wrapper emitted through bind_tools keeps tracing (fake inner)."""
    wrapped = wrap_with_tracing(
        FakeChatModel(), provider="fakeprov", model_name="fakemodel"
    )
    # FakeChatModel has no bind_tools override — BaseChatModel.bind_tools
    # raises NotImplementedError, mirroring graph._bind_tools' unbound path.
    with pytest.raises(NotImplementedError):
        wrapped.bind_tools([])
    result = await wrapped.ainvoke([AIMessage(content="ping")])
    assert result.content == "pong"
    assert len(list(get_span_buffer())) == 1


async def test_stdout_exporter_logs_span(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
):
    monkeypatch.setenv("ORYA_LLM_TRACE_EXPORTER", "stdout")
    clear_settings_cache()
    wrapped = wrap_with_tracing(
        FakeChatModel(), provider="fakeprov", model_name="fakemodel"
    )
    with caplog.at_level(logging.DEBUG, logger="app.core.llm.tracing"):
        await wrapped.ainvoke([AIMessage(content="ping")])
    assert any("llm_span" in record.getMessage() for record in caplog.records)


async def test_emitter_survives_broken_finalization(
    monkeypatch: pytest.MonkeyPatch,
):
    """A failing exporter/settings lookup must not break the agent-loop."""
    import app.core.llm.tracing as tracing_mod

    wrapped = wrap_with_tracing(
        FakeChatModel(), provider="fakeprov", model_name="fakemodel"
    )

    def _boom():
        raise RuntimeError("settings exploded")

    monkeypatch.setattr(tracing_mod, "get_settings", _boom)
    result = await wrapped.ainvoke([AIMessage(content="ping")])
    assert result.content == "pong"
    assert list(get_span_buffer()) == []
