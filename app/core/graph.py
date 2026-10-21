"""LangGraph agent-loop (M-04).

The core cycle of OryaAgent: user input -> LLM call -> tool calls ->
tool results -> LLM call, until the model answers without tool calls.

``build_graph(tools, model, checkpointer, policy)`` returns a compiled
``StateGraph`` with three nodes:

* ``agent``  — calls the chat model (the only place where the LLM is invoked);
* ``tools``  — ``langgraph.prebuilt.ToolNode`` executing the requested tools
  (parallel tool calls of a single AI message are executed concurrently by
  LangGraph itself);
* ``human``  — permission review hook. It is the scaffolding for M-13
  (``app/core/policy.py``): the node asks the policy to review the pending
  tool calls and, on a deny decision, returns ``ToolMessage("Denied by user")``
  instead of executing anything.

Edges: ``START -> agent``, ``agent -> tools | END`` (conditional on the
presence of tool calls), ``tools -> agent``, ``human -> tools``.

The ask-mode pause is implemented with LangGraph's native
``interrupt_before=["tools"]``: the graph is checkpointed right before the
tool node, the UI confirms the call and the run is resumed with
``Command(resume=...)``.

Design constraints (see ``analytics/PROMPT_MVP.md`` §4, §9):

* the LLM is never called directly — the model instance is injected (built by
  the ``get_llm()`` seam of M-01);
* the tool list is never hardcoded here — it is injected by the caller
  (M-12 tool-registry);
* no ``langchain.agents.AgentExecutor`` — LangGraph only;
* ``recursion_limit`` is never hardcoded — it comes from the settings;
* no partner packages (``langchain_anthropic`` / ``langchain_openai`` / ...)
  are imported by this module.

Usage::

    from app.core.graph import build_graph, default_run_config
    from app.db.checkpoints import get_checkpointer

    checkpointer = await get_checkpointer()
    graph = build_graph(tools, model, checkpointer, policy)
    result = await graph.ainvoke(
        {"messages": [HumanMessage("hi")]},
        default_run_config(session_id),
    )
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Sequence
from typing import Any, Protocol

from langchain_core.messages import BaseMessage, SystemMessage, ToolMessage
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.prebuilt import ToolNode
from langgraph.types import Command

from app.core.config import get_settings

logger = logging.getLogger(__name__)

#: Signature of the optional system-prompt builder injected into the graph.
#: M-05 (``app/core/prompt.py``) plugs its ``build_system_prompt`` in here —
#: the agent-loop itself must not import the prompt module (M-05 depends on
#: M-04, not the other way round).
SystemPromptFn = Callable[
    [Any, Sequence[Any]],
    "str | BaseMessage | Sequence[BaseMessage] | None",
]

#: Signature of the optional context trimmer injected into the graph.
#: M-06 (``app/core/context.py``) plugs its ``trim_messages`` in here —
#: the agent-loop itself must not import the context module (M-04 depends
#: on neither M-05 nor M-06; both are injected as seams).
TrimFn = Callable[[list[BaseMessage]], list[BaseMessage]]


class PolicyLike(Protocol):
    """Minimal permission-policy contract used by the graph (M-13).

    The real implementation lives in ``app/core/policy.py`` (M-13); M-04
    only depends on the shape, so the graph stays testable with plain mocks.
    """

    ask_mode: bool

    async def review(self, tool_calls: Sequence[dict]) -> str:
        """Review pending tool calls; returns ``"allow"`` or ``"deny"``."""
        ...


def route_after_agent(state: MessagesState) -> str:
    """Route the agent node: to ``tools`` when tool calls are pending."""
    messages = state.get("messages") or []
    if not messages:
        return END
    last = messages[-1]
    if getattr(last, "tool_calls", None):
        return "tools"
    return END


def _deny_messages(tool_calls: Sequence[dict]) -> list[ToolMessage]:
    """Build ``ToolMessage`` placeholders for denied tool calls."""
    denied: list[ToolMessage] = []
    for call in tool_calls:
        denied.append(
            ToolMessage(
                content="Denied by user",
                tool_call_id=call.get("id", ""),
                name=call.get("name", ""),
            )
        )
    return denied


def build_human_node(
    policy: PolicyLike | None,
) -> Callable[[MessagesState], Awaitable[dict[str, list[BaseMessage]] | None]]:
    """Build the ``human`` node — the permission-review hook (M-13).

    The node asks the policy to review the tool calls requested by the last
    AI message. On a ``"deny"`` decision it returns ``ToolMessage("Denied
    by user")`` for every pending call, so the model learns that the call
    was not executed; on ``"allow"`` it returns ``None`` and the graph
    continues to the tool node.
    """

    async def human_node(state: MessagesState) -> dict[str, list[BaseMessage]] | None:
        if policy is None:
            return None
        messages = state.get("messages") or []
        last = messages[-1] if messages else None
        tool_calls = list(getattr(last, "tool_calls", None) or [])
        if not tool_calls:
            return None
        decision = await policy.review(tool_calls)
        if decision == "deny":
            return {"messages": _deny_messages(tool_calls)}
        return None

    return human_node


def build_graph(
    tools: Sequence[Any],
    model: Any,
    checkpointer: Any = None,
    policy: PolicyLike | None = None,
    *,
    system_prompt_fn: SystemPromptFn | None = None,
    trim_fn: TrimFn | None = None,
) -> CompiledStateGraph:
    """Build the agent-loop graph.

    Args:
        tools: LangChain tools bound to the model (M-12 tool-registry).
        model: Chat model instance created via the ``get_llm()`` seam (M-01).
        checkpointer: LangGraph checkpointer (e.g. ``AsyncPostgresSaver``).
            ``None`` disables checkpointing (unit tests, one-shot runs).
        policy: Permission policy (M-13). When omitted, the graph runs in
            auto mode (no interrupts) and never denies a tool call.
        system_prompt_fn: Optional callable ``(state, tools) -> str |
            BaseMessage | Sequence[BaseMessage] | None`` used to prepend a
            system prompt. M-05 injects ``build_system_prompt`` here.
        trim_fn: Optional callable ``(messages) -> messages`` used to trim
            the history to the context-window budget before the model
            call. M-06 injects ``trim_messages`` here; the system prompt
            is built after trimming and never enters the state.

    Returns:
        The compiled LangGraph state graph.
    """
    graph = StateGraph(MessagesState)
    tool_node = ToolNode(list(tools))

    async def agent_node(state: MessagesState) -> dict[str, list[BaseMessage]]:
        """Call the model with the current conversation."""
        messages: list[BaseMessage] = list(state.get("messages") or [])
        if trim_fn is not None:
            messages = list(trim_fn(messages))
        if system_prompt_fn is not None:
            prompt = system_prompt_fn(state, tools)
            if isinstance(prompt, str):
                messages = [SystemMessage(content=prompt), *messages]
            elif isinstance(prompt, BaseMessage):
                messages = [prompt, *messages]
            elif prompt:
                messages = [*prompt, *messages]
        response = await model.ainvoke(messages)
        return {"messages": [response]}

    human_node = build_human_node(policy)

    graph.add_node("agent", agent_node)
    graph.add_node("tools", tool_node)
    graph.add_node("human", human_node)

    graph.add_edge(START, "agent")
    graph.add_conditional_edges("agent", route_after_agent)
    graph.add_edge("tools", "agent")
    graph.add_edge("human", "tools")

    ask_mode = bool(getattr(policy, "ask_mode", False))
    compiled = graph.compile(
        checkpointer=checkpointer,
        interrupt_before=["tools"] if ask_mode else [],
    )
    logger.debug(
        "Agent graph built: nodes=agent,tools,human ask_mode=%s checkpointer=%s",
        ask_mode,
        type(checkpointer).__name__ if checkpointer is not None else "none",
    )
    return compiled


def default_run_config(
    thread_id: str,
    *,
    recursion_limit: int | None = None,
    **extra: Any,
) -> dict[str, Any]:
    """Build the LangGraph run config for a session/thread.

    The ``thread_id`` ties the run to the checkpoint history (LangGraph
    resumes the same thread). ``recursion_limit`` caps the agent-loop
    iterations and is never hardcoded — it comes from the settings.
    """
    limit = (
        recursion_limit
        if recursion_limit is not None
        else get_settings().recursion_limit
    )
    config: dict[str, Any] = {
        "configurable": {"thread_id": thread_id},
        "recursion_limit": limit,
    }
    config.update(extra)
    return config


def resume_command(value: Any = "") -> Command:
    """Build the ``Command`` that resumes an interrupted run.

    Used by the UI (M-16) after the user approved a paused tool call.
    The resume value must not be ``None``: langgraph 1.2.x fails with an
    ``UnboundLocalError`` when a ``Command`` carries ``resume=None``, so the
    empty string is used as the "approved, no extra data" marker.
    """
    return Command(resume="" if value is None else value)
