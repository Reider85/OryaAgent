"""LangGraph agent-loop (M-04) + permission gate (M-13).

The core cycle of OryaAgent: user input -> LLM call -> tool calls ->
tool results -> LLM call, until the model answers without tool calls.

``build_graph(tools, model, checkpointer, policy)`` returns a compiled
``StateGraph`` with three nodes:

* ``agent``  — calls the chat model (the only place where the LLM is invoked);
* ``tools``  — ``langgraph.prebuilt.ToolNode`` executing the requested tools
  (parallel tool calls of a single AI message are executed concurrently by
  LangGraph itself);
* ``human``  — permission review hook (M-13 ``app/core/permissions.py``).
  The node asks the policy to ``check()`` every pending tool call: an
  ``allow`` proceeds to the tool node, a ``deny`` returns refusal
  ``ToolMessage``s instead of executing anything, and an ``ask`` pauses the
  run with LangGraph's dynamic ``interrupt()`` so the UI (M-16) can collect
  the user's answer.

Edges: ``START -> agent``, ``agent -> human | tools | END`` (conditional:
tool calls pending and a policy present -> ``human``; otherwise ``tools``),
``tools -> agent``. The ``human`` node routes itself with
``Command(goto=...)`` — to ``tools`` when every call is allowed, to
``agent`` when any call was refused.

The ask-pause is LangGraph's dynamic ``interrupt()`` inside the human node:
the run is checkpointed, the UI confirms the call and resumes with
``Command(resume=...)`` — see ``resume_command("approve" | "deny" |
"always")``. Refusals are batch-level: if any call in one AI message is
refused, the whole batch is refused (providers require exactly one
``ToolMessage`` per tool-call id).

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
    from app.core.permissions import get_policy
    from app.db.checkpoints import get_checkpointer

    checkpointer = await get_checkpointer()
    graph = build_graph(tools, model, checkpointer, get_policy())
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
from langgraph.types import Command, interrupt

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


class DecisionLike(Protocol):
    """Minimal decision shape returned by ``PolicyLike.check`` (M-13)."""

    action: str
    reason: str


class PolicyLike(Protocol):
    """Minimal permission-policy contract used by the graph (M-13).

    The real implementation lives in ``app/core/permissions.py`` (M-13);
    M-04 only depends on the shape, so the graph stays testable with plain
    mocks.
    """

    def check(self, tool_call: dict) -> DecisionLike:
        """Decide for one pending tool call: ``allow`` / ``deny`` / ``ask``."""
        ...

    def record_session_allow(self, tool_name: str) -> None:
        """Remember "Approve & don't ask again for this tool in session"."""
        ...


#: Resume answers that approve a paused tool call (M-16 UI buttons).
#: The empty string is the legacy "approved, no extra data" marker of
#: ``resume_command()`` from M-04.
_APPROVE_STRINGS = frozenset({"", "approve", "approved", "yes", "y", "always"})


def _is_approved(answer: Any) -> bool:
    """Interpret a ``Command(resume=...)`` answer as approve/deny.

    Unknown values are denied (fail-closed): a resumed run must never
    execute a destructive call on an ambiguous answer.
    """
    if answer is True:
        return True
    return isinstance(answer, str) and answer.strip().lower() in _APPROVE_STRINGS


def _is_always(answer: Any) -> bool:
    """True when the answer is the "don't ask again this session" variant."""
    return isinstance(answer, str) and answer.strip().lower() == "always"


def route_after_agent(
    state: MessagesState,
    policy: PolicyLike | None = None,
) -> str:
    """Route the agent node: ``human`` with a policy, else ``tools``.

    Both destinations are only taken when tool calls are pending; without
    tool calls the run ends. With a policy present the batch goes through
    the ``human`` permission-review node first (M-13).
    """
    messages = state.get("messages") or []
    if not messages:
        return END
    last = messages[-1]
    if not getattr(last, "tool_calls", None):
        return END
    if policy is not None:
        return "human"
    return "tools"


def _bind_tools(model: Any, tools: Sequence[Any]) -> Any:
    """Bind tools to the chat model (PROMPT_MVP M-12: ``graph.bind_tools``).

    Real providers (ChatAnthropic, ChatOpenAI, ...) implement
    ``bind_tools()``; test doubles and minimal fake models may raise
    ``NotImplementedError`` or lack the method entirely. The agent-loop
    must keep working either way - LangGraph's ``ToolNode`` executes
    whatever tool calls the model emits - so binding failures degrade
    to an unbound model with a debug log instead of crashing.
    """
    bind = getattr(model, "bind_tools", None)
    if bind is None or not tools:
        return model
    try:
        return bind(list(tools))
    except NotImplementedError:
        logger.debug(
            "Model %s does not support bind_tools; running unbound",
            type(model).__name__,
        )
        return model


def _refusal_messages(refusals: Sequence[tuple[dict, str]]) -> list[ToolMessage]:
    """Build the refusal ``ToolMessage`` for each refused tool call."""
    return [
        ToolMessage(
            content=reason,
            tool_call_id=call.get("id", ""),
            name=call.get("name", ""),
        )
        for call, reason in refusals
    ]


def build_human_node(
    policy: PolicyLike | None,
    *,
    can_interrupt: bool = True,
) -> Callable[[MessagesState], Awaitable[Command]]:
    """Build the ``human`` node — the permission-review hook (M-13).

    The node reviews every tool call requested by the last AI message with
    ``policy.check()``:

    * ``allow`` — the call proceeds to the tool node;
    * ``deny``  — every call in the batch gets a refusal ``ToolMessage`` and
      the loop continues at ``agent`` (nothing is executed);
    * ``ask``   — the run pauses via ``interrupt()``; the UI (M-16) resumes
      with ``resume_command("approve" | "deny" | "always")``. ``always``
      records the tool in the policy's session allowlist. When interruption
      is unavailable (no checkpointer) the call is denied (fail-closed).

    Batch semantics: once any call is refused, the whole batch is refused
    and no further prompts are shown — providers require exactly one
    ``ToolMessage`` per tool-call id, so a partially executed batch would
    desync the conversation history.

    The node routes itself with ``Command(goto=...)``: ``tools`` when every
    call is allowed, ``agent`` when any call was refused.
    """

    async def human_node(state: MessagesState) -> Command:
        messages = state.get("messages") or []
        last = messages[-1] if messages else None
        tool_calls = list(getattr(last, "tool_calls", None) or [])
        if policy is None or not tool_calls:
            return Command(goto="tools")

        refusals: list[tuple[dict, str]] = []
        for call in tool_calls:
            name = str(call.get("name", ""))
            decision = policy.check(call)
            if decision.action == "deny":
                logger.info("Permission denied by policy: %s", decision.reason)
                refusals.append((call, f"Denied by policy: {decision.reason}"))
                continue
            if decision.action != "ask":
                continue
            if not can_interrupt:
                refusals.append((call, "Denied: permission prompting unavailable"))
                continue
            if refusals:
                refusals.append(
                    (call, "Denied: another call in this batch was refused")
                )
                continue
            answer = interrupt(
                {
                    "tool": name,
                    "args": call.get("args") or {},
                    "reason": decision.reason,
                }
            )
            if not _is_approved(answer):
                logger.info("User denied tool call: %s", name)
                refusals.append((call, "Denied by user"))
                continue
            if _is_always(answer):
                policy.record_session_allow(name)

        if not refusals:
            return Command(goto="tools")
        # Batch semantics: one refusal refuses the whole batch — every
        # tool-call id must receive exactly one ToolMessage, so calls that
        # were approved (or allowed) still need a refusal placeholder.
        explicit = {call.get("id"): reason for call, reason in refusals}
        batch_refusals = [
            (
                call,
                explicit.get(call.get("id"))
                or "Denied: another call in this batch was refused",
            )
            for call in tool_calls
        ]
        return Command(
            goto="agent",
            update={"messages": _refusal_messages(batch_refusals)},
        )

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
        policy: Permission policy (M-13). When omitted, tool calls are not
            gated — they go straight to the tool node. When present, the
            batch passes the ``human`` review node (deny / ask via
            ``interrupt()``). Note: ``interrupt()`` requires a checkpointer;
            without one, ``ask`` decisions are denied (fail-closed).
        system_prompt_fn: Optional callable ``(state, tools) -> str |
            BaseMessage | Sequence[BaseMessage] | None`` used to prepend a
            system prompt. M-05 injects ``build_system_prompt`` here.
        trim_fn: Optional callable ``(messages) -> messages`` used to trim
            the history to the context-window budget before the model
            call. M-06 injects ``trim_messages`` here; the system prompt
            is built after trimming and never enters the state.

    Returns:
        The compiled LangGraph state graph. ``tools`` are bound to the
        model via ``bind_tools`` when the model supports it (M-12);
        models without ``bind_tools`` (test doubles) run unbound.
    """
    graph = StateGraph(MessagesState)
    tool_list = list(tools)
    tool_node = ToolNode(tool_list)
    bound_model = _bind_tools(model, tool_list)

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
        response = await bound_model.ainvoke(messages)
        return {"messages": [response]}

    human_node = build_human_node(policy, can_interrupt=checkpointer is not None)

    graph.add_node("agent", agent_node)
    graph.add_node("tools", tool_node)
    graph.add_node("human", human_node)

    graph.add_edge(START, "agent")
    graph.add_conditional_edges(
        "agent",
        lambda state: route_after_agent(state, policy),
    )
    graph.add_edge("tools", "agent")
    # The ``human`` node routes itself with Command(goto=...): to ``tools``
    # when every call is allowed, to ``agent`` when any call was refused.

    compiled = graph.compile(checkpointer=checkpointer)
    logger.debug(
        "Agent graph built: nodes=agent,tools,human policy=%s checkpointer=%s "
        "tools_bound=%s",
        type(policy).__name__ if policy is not None else "none",
        type(checkpointer).__name__ if checkpointer is not None else "none",
        bound_model is not model,
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
    """Build the ``Command`` that resumes an interrupted run (M-13/M-16).

    The human node (M-13) pauses on ``ask`` via ``interrupt()``; the UI
    answers with this command. Recognized answers: ``"approve"`` (or the
    legacy empty string) to run the call, ``"deny"`` to refuse it, and
    ``"always"`` to approve and stop asking about this tool for the rest
    of the session. Unknown values are treated as a denial (fail-closed).

    The resume value must not be ``None``: langgraph 1.2.x fails with an
    ``UnboundLocalError`` when a ``Command`` carries ``resume=None``, so the
    empty string is used as the "approved, no extra data" marker.
    """
    return Command(resume="" if value is None else value)
