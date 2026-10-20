"""Capability-detection: reasoning models without tool-calling fail fast (M-01)."""

import pytest

from app.core.llm import get_llm


def test_deepseek_reasoner_rejected_with_hint():
    with pytest.raises(ValueError) as exc_info:
        get_llm("deepseek", "deepseek-reasoner", api_key="sk-fake")
    message = str(exc_info.value)
    assert "tool-calling" in message
    assert "deepseek-chat" in message
    assert "require_tools=False" in message


def test_deepseek_reasoner_plain_chat_fallback():
    llm = get_llm(
        "deepseek", "deepseek-reasoner", api_key="sk-fake", require_tools=False
    )
    assert llm.model == "deepseek-reasoner"


def test_o1_rejected():
    with pytest.raises(ValueError, match="tool-calling"):
        get_llm("openai", "o1", api_key="sk-fake")


def test_glm_zero_rejected():
    with pytest.raises(ValueError, match="tool-calling"):
        get_llm("glm", "glm-zero-preview", api_key="sk-fake")


def test_mimo_rejected():
    with pytest.raises(ValueError, match="tool-calling"):
        get_llm("mimo", "mimo-7b-rl", api_key="sk-fake")


def test_chat_models_accepted_by_default():
    for provider, model, key in [
        ("deepseek", "deepseek-chat", "sk-fake"),
        ("qwen", "qwen-coder", "sk-fake"),
        ("glm", "glm-4.5", "sk-fake"),
        ("anthropic", "claude-sonnet-3.5", "sk-ant-fake"),
    ]:
        llm = get_llm(provider, model, api_key=key)
        assert llm is not None


def test_unknown_raw_model_assumed_supported():
    """Unregistered model_ids default to optimistic capabilities."""
    llm = get_llm("deepseek", "some-future-model", api_key="sk-fake")
    assert llm.model == "some-future-model"
