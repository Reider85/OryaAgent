"""E2E (M-16): permission ask-prompt — approve / deny / allow-list skip.

Drives the real seams end to end without a Chainlit server or API key:
a scripted model asks for a ``bash`` call, the compiled graph pauses at
the M-13 ``human`` node, the UI helpers (:mod:`app.ui.interrupt`)
extract the payload and the run is resumed with
``resume_graph_events`` — the same path ``on_message`` takes after the
user clicks a button.

Three acceptance scenarios (BACKLOG4 M-16):

1. approve  — the tool executes and the agent finishes;
2. deny     — nothing executes; the agent continues on "Denied by user";
3. allow-list — an allow rule short-circuits the gate: no pause at all.
"""

from __future__ import annotations

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
from langchain_core.tools import tool
from langgraph.checkpoint.memory import MemorySaver

from app.core.agent import resume_graph_events, stream_graph_events
from app.core.graph import build_graph, default_run_config
from app.core.permissions import PermissionConfig, PermissionPolicy, Rule
from app.ui.interrupt import ask_permission, get_pending_interrupt


@tool("bash")
def _fake_bash(command: str) -> str:
    """Scripted stand-in for the real bash tool (no shell involved)."""
    return f"ran: {command}"


class _ScriptedModel(BaseChatModel):
    """Requests one ``bash`` call, then answers with the tool result."""

    command: str = "echo approved"

    calls: int = 0

    @property
    def _llm_type(self) -> str:
        return "orya-scripted-ask"

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        self.calls += 1
        if self.calls == 1:
            message = AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "bash",
                        "args": {"command": self.command},
                        "id": "call-1",
                        "type": "tool_call",
                    }
                ],
            )
        else:
            tool_result = next(
                (m.content for m in reversed(messages) if isinstance(m, ToolMessage)),
                "",
            )
            message = AIMessage(content=f"done: {tool_result}")
        return ChatResult(generations=[ChatGeneration(message=message)])

    def _stream(self, messages, stop=None, run_manager=None, **kwargs):
        result = self._generate(messages, stop=stop, run_manager=run_manager)
        message = result.generations[0].message
        if message.tool_calls:
            call = message.tool_calls[0]
            yield ChatGenerationChunk(
                message=AIMessageChunk(
                    content="",
                    tool_call_chunks=[
                        {
                            "name": call["name"],
                            "args": f'{{"command": "{self.command}"}}',
                            "id": call["id"],
                            "index": 0,
                            "type": "tool_call_chunk",
                        }
                    ],
                )
            )
        else:
            yield ChatGenerationChunk(message=AIMessageChunk(content=message.content))


def _ask_policy() -> PermissionPolicy:
    """Strict policy with neutral rule lists (no user YAML leakage)."""
    return PermissionPolicy(
        mode="strict", config=PermissionConfig(allow_rules=[], deny_rules=[])
    )


async def _run_until_interrupt(graph, config):
    """Stream one turn; return ``(events, pending)`` like on_message does."""
    events = [event async for event in stream_graph_events(graph, "run it", config)]
    state = await graph.aget_state(config)
    return events, get_pending_interrupt(state)


async def test_approve_runs_the_tool_and_finishes() -> None:
    graph = build_graph([_fake_bash], _ScriptedModel(), MemorySaver(), _ask_policy())
    config = default_run_config("m16-approve")

    _, pending = await _run_until_interrupt(graph, config)
    assert pending is not None
    assert pending.tool == "bash"
    assert pending.args == {"command": "echo approved"}
    assert "strict mode" in pending.reason

    async def fake_ask(content, actions):
        return {"name": "approve", "payload": {"value": "approve"}}

    answer = await ask_permission(pending, ask=fake_ask)
    resume_events = [
        event async for event in resume_graph_events(graph, answer, config)
    ]

    assert answer == "approve"
    outputs = [data["output"] for kind, data in resume_events if kind == "tool_end"]
    assert any("ran: echo approved" in out for out in outputs)
    tokens = [data["content"] for kind, data in resume_events if kind == "token"]
    assert any("done:" in token for token in tokens)

    state = await graph.aget_state(config)
    assert state.next == ()


async def test_deny_refuses_and_agent_continues() -> None:
    graph = build_graph([_fake_bash], _ScriptedModel(), MemorySaver(), _ask_policy())
    config = default_run_config("m16-deny")

    _, pending = await _run_until_interrupt(graph, config)
    assert pending is not None

    async def fake_ask(content, actions):
        return {"name": "deny", "payload": {"value": "deny"}}

    answer = await ask_permission(pending, ask=fake_ask)
    resume_events = [
        event async for event in resume_graph_events(graph, answer, config)
    ]

    assert answer == "deny"
    # nothing executed: no tool_end for the refused call
    assert not [data for kind, data in resume_events if kind == "tool_end"]

    state = await graph.aget_state(config)
    assert state.next == ()
    refusals = [m for m in state.values["messages"] if isinstance(m, ToolMessage)]
    assert any("Denied by user" in m.content for m in refusals)
    tokens = [data["content"] for kind, data in resume_events if kind == "token"]
    assert any("done:" in token for token in tokens)


async def test_allow_list_skips_the_prompt() -> None:
    policy = PermissionPolicy(
        mode="strict",
        config=PermissionConfig(
            allow_rules=[
                Rule(
                    tool="bash",
                    pattern=r"^echo approved$",
                    action="allow",
                    description="scripted echo",
                )
            ],
            deny_rules=[],
        ),
    )
    graph = build_graph([_fake_bash], _ScriptedModel(), MemorySaver(), policy)
    config = default_run_config("m16-allowlist")

    events, pending = await _run_until_interrupt(graph, config)

    assert pending is None
    outputs = [data["output"] for kind, data in events if kind == "tool_end"]
    assert any("ran: echo approved" in out for out in outputs)

    state = await graph.aget_state(config)
    assert state.next == ()
