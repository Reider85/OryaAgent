"""E2E smoke (M-15): chainlit handlers + a real streamed graph turn.

No Chainlit server, no PostgreSQL and no API key: the smoke imports the
UI module (handler registration) and runs one turn of a real compiled
graph through ``stream_graph_events`` with a scripted streaming model
and no checkpointer — asserting that tool step events and streamed
tokens arrive in the order the Chainlit handlers render them.
"""

from __future__ import annotations

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
from langchain_core.tools import tool

from app.core.graph import build_graph, default_run_config
from app.ui import chainlit_app as ui


def test_chainlit_handlers_registered() -> None:
    assert callable(ui.on_chat_start)
    assert callable(ui.on_message)


@tool
def _echo(text: str) -> str:
    """Echo the input text back in upper case."""
    return text.upper()


class _ScriptedModel(BaseChatModel):
    """Streams a tool call first, then the final answer."""

    calls: int = 0

    @property
    def _llm_type(self) -> str:
        return "orya-scripted-smoke"

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        self.calls += 1
        if self.calls == 1:
            message = AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "_echo",
                        "args": {"text": "orya"},
                        "id": "call-1",
                        "type": "tool_call",
                    }
                ],
            )
        else:
            message = AIMessage(content="echoed ORYA")
        return ChatResult(generations=[ChatGeneration(message=message)])

    def _stream(self, messages, stop=None, run_manager=None, **kwargs):
        self.calls += 1
        if self.calls == 1:
            yield ChatGenerationChunk(
                message=AIMessageChunk(
                    content="",
                    tool_call_chunks=[
                        {
                            "name": "_echo",
                            "args": '{"text": "orya"}',
                            "id": "call-1",
                            "index": 0,
                            "type": "tool_call_chunk",
                        }
                    ],
                )
            )
        else:
            for piece in ("echoed ", "ORYA"):
                yield ChatGenerationChunk(message=AIMessageChunk(content=piece))


async def test_stream_turn_renders_tokens_and_tool_steps() -> None:
    graph = build_graph([_echo], _ScriptedModel())
    config = default_run_config("smoke-m15")

    events = [
        event async for event in ui.stream_graph_events(graph, "echo orya", config)
    ]

    kinds = [kind for kind, _ in events]
    assert "tool_start" in kinds
    assert "tool_end" in kinds

    tool_start = next(data for kind, data in events if kind == "tool_start")
    assert tool_start["tool"] == "_echo"
    assert tool_start["args"] == {"text": "orya"}

    tool_end = next(data for kind, data in events if kind == "tool_end")
    assert tool_end["output"] == "ORYA"

    tokens = [data["content"] for kind, data in events if kind == "token"]
    assert tokens == ["echoed ", "ORYA"]

    # tool steps must precede the streamed final answer
    assert kinds.index("tool_start") < kinds.index("token")
