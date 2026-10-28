"""LangGraph agent-loop (M-04) + permission gate (M-13) + failure recovery (M-28).

The core cycle of OryaAgent: user input -> LLM call -> tool calls ->
tool results -> LLM call, until the model answers without tool calls.

``build_graph(tools, model, checkpointer, policy)`` returns a compiled
``StateGraph`` with five nodes:

* ``agent``  — calls the chat model (the only place where the LLM is invoked);
* ``tools``  — ``langgraph.prebuilt.ToolNode`` executing the requested tools
  (parallel tool calls of a single AI message are executed concurrently by
  LangGraph itself). Its ``handle_tool_errors`` is wired to
  :func:`tool_error_text` (M-28): a failed call becomes a
  ``ToolMessage(status="error")`` instead of killing the run — langgraph
  1.2.x re-raises tool exceptions by default;
* ``human``  — permission review hook (M-13 ``app/core/permissions.py``).
  The node asks the policy to ``check()`` every pending tool call: an
  ``allow`` proceeds to the tool node, a ``deny`` returns refusal
  ``ToolMessage``s instead of executing anything, and an ``ask`` pauses the
  run with LangGraph's dynamic ``interrupt()`` so the UI (M-16) can collect
  the user's answer;
* ``assess`` — failure triage (M-28): looks at the tool results the ``tools``
  node just appended. No ``status="error"`` → back to ``agent`` (and the
  recovery budget resets). Errors and budget left → ``recover`` with
  ``recovery_rounds + 1``; budget exhausted → plain ``agent`` (no loop);
* ``recover`` — asks the model for alternative ways to perform the failed
  action (one tool call attempted per round) and feeds the answer through
  the same ``human`` permission gate. Its prompt nudge is invoke-local and
  is never written to the conversation history.

Edges: ``START -> agent``, ``agent -> human | tools | END`` (conditional:
tool calls pending and a policy present -> ``human``; otherwise ``tools``),
``tools -> assess``, ``recover -> human | tools | END`` (same conditional as
``agent``). The ``human`` node routes itself with ``Command(goto=...)`` — to
``tools`` when every call is allowed, to ``agent`` when any call was
refused; ``assess`` routes itself the same way.

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
* neither are the M-28 recovery budgets — ``recovery_max_rounds`` /
  ``recovery_variants`` / ``llm_retry_attempts`` /
  ``llm_retry_backoff_seconds`` all come from the settings;
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

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable, Sequence
from typing import Any, Protocol

from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_core.tools import ToolException
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.prebuilt import ToolNode
from langgraph.types import Command, interrupt

from app.core.config import get_settings
from app.core.security import sanitize_untrusted

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


class RecoveryState(MessagesState):
    """Graph state: the message list plus the M-28 recovery budget.

    ``recovery_rounds`` counts the consecutive failed tool batches the
    ``assess`` node has forwarded to ``recover``. It resets to ``0`` on a
    clean batch and at the start of a fresh user turn, and it never grows
    past ``settings.recovery_max_rounds`` — so a persistently failing tool
    cannot loop: after the budget is spent the run stays on the plain
    ``agent -> tools`` path until the model gives up (or the LangGraph
    ``recursion_limit`` stops it).

    ``int`` (not ``Annotated``) on purpose: the key is written whole, never
    incremented by a reducer, and checkpoints predating M-28 simply lack it
    (``state.get("recovery_rounds") or 0``).
    """

    recovery_rounds: int


#: Name of the M-28 alternatives node — also used by the runtime to keep
#: its intermediate prose out of the streamed assistant reply.
RECOVER_NODE_NAME = "recover"


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


# --- M-28: failure recovery -------------------------------------------------

#: Upper bound for one exponential backoff step of an LLM call (M-28).
_MAX_BACKOFF_SECONDS = 30.0

#: HTTP statuses where retrying an LLM call cannot help (M-28).
_NON_RETRYABLE_STATUS = frozenset({400, 401, 403, 404, 422})

#: Exception class names providers use for the same "don't retry" cases.
_NON_RETRYABLE_ERRORS = frozenset(
    {
        "AuthenticationError",
        "PermissionDeniedError",
        "BadRequestError",
        "NotFoundError",
        "UnprocessableEntityError",
        "InvalidRequestError",
        "ValidationError",
    }
)

#: Per-failure error text cap inside the recovery nudge (chars).
NUDGE_ERROR_CHARS = 500

#: How many failed calls a single nudge lists (the batch may be wider).
NUDGE_MAX_FAILURES = 5


def _is_retryable(exc: Exception) -> bool:
    """True when a failed LLM provider call is worth retrying (M-28).

    Network hiccups, timeouts, 429/5xx — yes. Authentication, permission
    and malformed-request failures repeat identically forever, so they are
    surfaced immediately. ``asyncio.CancelledError`` and friends are
    ``BaseException``s and never reach this check.
    """
    status = getattr(exc, "status_code", None)
    if isinstance(status, int) and status in _NON_RETRYABLE_STATUS:
        return False
    return type(exc).__name__ not in _NON_RETRYABLE_ERRORS


async def _ainvoke_with_retry(
    model: Any,
    messages: Sequence[BaseMessage],
    *,
    attempts: int,
    base_delay: float,
) -> Any:
    """Call ``model.ainvoke`` with retries and exponential backoff (M-28).

    A provider failure currently aborts the whole turn (the API layer
    surfaces it as ``status="error"``). Retrying here makes transient
    rate-limits and network blips invisible to the user.

    Args:
        model: The bound chat model (``bind_tools`` result).
        messages: Full prompt for this call.
        attempts: Total attempts — ``1`` disables retries.
        base_delay: First delay in seconds (``1, 2, 4, ...`` capped at
            ``_MAX_BACKOFF_SECONDS``). ``0`` retries instantly (tests).

    Returns: the model's response. Re-raises the last (or a
    non-retryable) exception once the budget is spent.
    """
    tries = max(1, attempts)
    delay = max(0.0, base_delay)
    for attempt in range(1, tries + 1):
        try:
            return await model.ainvoke(messages)
        except Exception as exc:
            if attempt >= tries or not _is_retryable(exc):
                raise
            logger.warning(
                "LLM call failed (attempt %d/%d): %s — retrying in %.2fs",
                attempt,
                tries,
                exc,
                delay,
            )
            if delay > 0:
                await asyncio.sleep(delay)
            delay = min(delay * 2, _MAX_BACKOFF_SECONDS)
    raise AssertionError("unreachable: the retry loop always returns or raises")


def tool_error_text(exc: Exception) -> str:
    """Render a failed tool call as its ``ToolMessage(status="error")`` body (M-28).

    Passed to ``ToolNode(handle_tool_errors=...)``: since langgraph 1.2.x the
    node **re-raises** tool failures by default (only argument-validation
    ``ToolInvocationError`` is converted), which aborts the whole turn — that
    is exactly the "an unsuccessful action stops the agent" symptom this
    ticket fixes. With this handler the failure becomes data the model (and
    the ``assess``/``recover`` pair) can act on.

    Our tools raise ``ToolException`` with a clean, model-actionable message;
    anything else is a bug in the tool — it keeps its class name and is
    logged with a traceback, but still reaches the model so the run survives.

    The ``Exception`` annotation is load-bearing: langgraph's
    ``_infer_handled_types()`` reads it to decide which failures are
    converted (``GraphBubbleUp`` interrupts and invalid resume values are
    re-raised by the tool node before this handler is ever consulted).
    """
    if isinstance(exc, ToolException):
        return str(exc)
    logger.error("tool call raised %s", type(exc).__name__, exc_info=exc)
    return f"{type(exc).__name__}: {exc}"


def _failed_tool_messages(messages: Sequence[BaseMessage]) -> list[ToolMessage]:
    """Errors of the batch the tool node just appended (M-28 triage input).

    Walks back over the trailing run of ``ToolMessage``s and stops at the
    AI message that requested them, collecting only ``status="error"``
    results — permission refusals carry no status, so a denied call never
    triggers recovery.
    """
    failed: list[ToolMessage] = []
    for message in reversed(list(messages)):
        if isinstance(message, ToolMessage):
            if message.status == "error":
                failed.append(message)
            continue
        break
    failed.reverse()
    return failed


def recovery_nudge(messages: Sequence[BaseMessage], *, variants: int) -> HumanMessage:
    """Build the invoke-local "propose alternatives" nudge (M-28).

    The recover node appends this to the prompt **without** persisting it:
    history stays free of repeated recovery chatter, and each round frames
    the fresh failures itself.

    Error payloads are tool output — untrusted model-facing data — so every
    error body is framed with :func:`sanitize_untrusted` (M-22), which also
    audits a suspected injection and never raises.

    Args:
        messages: Current conversation (the failed batch is at its tail).
        variants: How many alternative approaches to ask for
            (``settings.recovery_variants``).
    """
    failed = _failed_tool_messages(messages)[:NUDGE_MAX_FAILURES]
    calls_by_id: dict[str, dict] = {}
    for message in reversed(list(messages)):
        if isinstance(message, AIMessage) and getattr(message, "tool_calls", None):
            calls_by_id = {str(call.get("id")): call for call in message.tool_calls}
            break

    lines = ["# Recovery: the previous action failed", ""]
    for message in failed:
        call = calls_by_id.get(str(message.tool_call_id)) or {}
        args = call.get("args") or {}
        try:
            args_text = json.dumps(args, ensure_ascii=False, default=str)
        except (TypeError, ValueError):
            args_text = str(args)
        name = message.name or str(call.get("name") or "unknown")
        body = message.content
        if not isinstance(body, str):
            body = json.dumps(body, ensure_ascii=False, default=str)
        lines.append(f"- tool `{name}` with args {args_text}:")
        lines.append(sanitize_untrusted(body[:NUDGE_ERROR_CHARS], source="tool_error"))
        lines.append("")
    lines.append(
        f"Do not end the turn on this failure. First enumerate up to {variants} "
        "alternative ways to reach the same goal (another tool, different "
        "arguments, a different strategy), then act on the best one: call "
        "EXACTLY ONE tool. If no alternative can work, reply with a short "
        "explanation and no tool call."
    )
    return HumanMessage(content="\n".join(lines))


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

    Failure recovery (M-28): a tool batch containing an error result is
    routed by ``assess`` to ``recover``, which asks the model (up to
    ``settings.recovery_max_rounds`` consecutive times) for alternative
    ways to perform the failed action and tries one of them — always
    through the ``human`` permission gate. Transient provider failures
    are retried with exponential backoff (``settings.llm_retry_attempts``)
    before they surface to the API layer. Denials (policy or user) are
    not errors: they never trigger recovery.

    Returns:
        The compiled LangGraph state graph. ``tools`` are bound to the
        model via ``bind_tools`` when the model supports it (M-12);
        models without ``bind_tools`` (test doubles) run unbound.
    """
    graph = StateGraph(RecoveryState)
    tool_list = list(tools)
    # M-28: convert tool failures into error ToolMessages (langgraph 1.2.x
    # re-raises them by default, which kills the run on a failed action).
    tool_node = ToolNode(tool_list, handle_tool_errors=tool_error_text)
    bound_model = _bind_tools(model, tool_list)

    async def call_model(
        state: RecoveryState,
        *,
        extra: Sequence[BaseMessage] = (),
    ) -> dict[str, Any]:
        """Invoke the model for ``state`` (shared by ``agent`` and ``recover``).

        Trim (M-06) → system prompt (M-05) → invoke-local ``extra`` messages
        → the provider call itself, which retries transient failures
        (M-28 ``_ainvoke_with_retry``). The ``extra`` messages (the recovery
        nudge) ride along only for this call and are never stored, so the
        conversation history stays clean.
        """
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
        if extra:
            messages = [*messages, *extra]
        settings = get_settings()
        response = await _ainvoke_with_retry(
            bound_model,
            messages,
            attempts=settings.llm_retry_attempts,
            base_delay=settings.llm_retry_backoff_seconds,
        )
        return {"messages": [response]}

    async def agent_node(state: RecoveryState) -> dict[str, Any]:
        """Call the model with the current conversation."""
        update = await call_model(state)
        # A fresh user turn re-arms the M-28 recovery budget: the run starts
        # at ``agent`` with the new HumanMessage last, so an exhausted
        # ``recovery_rounds`` from a previous turn never leaks into this one.
        rounds = int(state.get("recovery_rounds") or 0)
        messages = state.get("messages") or []
        if rounds and messages and isinstance(messages[-1], HumanMessage):
            logger.debug("New user turn: resetting recovery budget %d -> 0", rounds)
            update["recovery_rounds"] = 0
        return update

    async def recover_node(state: RecoveryState) -> dict[str, Any]:
        """Ask the model for alternative actions after a failed batch (M-28).

        One round = one nudge listing up to ``settings.recovery_variants``
        alternative approaches and demanding exactly one tool call, so side
        effects (write/edit/bash) are attempted sequentially — never in
        parallel — and the model picks a different variant each round. The
        answer flows through the very same routing as an ``agent`` answer:
        ``human`` (permission gate, M-13) → ``tools`` → ``assess``.
        """
        settings = get_settings()
        nudge = recovery_nudge(
            state.get("messages") or [], variants=settings.recovery_variants
        )
        logger.info(
            "Recovery round %d/%d: asking the model for alternatives",
            int(state.get("recovery_rounds") or 0),
            settings.recovery_max_rounds,
        )
        return await call_model(state, extra=[nudge])

    async def assess_node(state: RecoveryState) -> Command:
        """Triage the tool batch just executed (M-28); routes itself.

        * clean batch → ``agent`` and the recovery budget resets;
        * errors with budget left → ``recover`` (``recovery_rounds + 1``);
        * errors with an exhausted budget → ``agent`` without a reset, so
          further failures keep going down the plain path instead of
          looping recovery forever.
        """
        failed = _failed_tool_messages(state.get("messages") or [])
        rounds = int(state.get("recovery_rounds") or 0)
        max_rounds = get_settings().recovery_max_rounds
        if not failed:
            if rounds:
                logger.debug(
                    "Action succeeded: resetting recovery budget %d -> 0", rounds
                )
                return Command(goto="agent", update={"recovery_rounds": 0})
            return Command(goto="agent")
        if rounds >= max_rounds:
            logger.warning(
                "Recovery budget exhausted after %d round(s); %d error(s) left "
                "to the plain agent loop",
                rounds,
                len(failed),
            )
            return Command(goto="agent")
        logger.info(
            "Failed action (%d error(s)): recovery round %d/%d",
            len(failed),
            rounds + 1,
            max_rounds,
        )
        return Command(goto=RECOVER_NODE_NAME, update={"recovery_rounds": rounds + 1})

    human_node = build_human_node(policy, can_interrupt=checkpointer is not None)

    graph.add_node("agent", agent_node)
    graph.add_node("tools", tool_node)
    graph.add_node("human", human_node)
    graph.add_node("assess", assess_node)
    graph.add_node(RECOVER_NODE_NAME, recover_node)

    graph.add_edge(START, "agent")
    graph.add_conditional_edges(
        "agent",
        lambda state: route_after_agent(state, policy),
    )
    graph.add_edge("tools", "assess")
    # ``recover`` reuses the agent's routing: tool calls pending go through
    # the ``human`` permission gate (M-13 — retries are never exempt),
    # no tool calls means the model gave up on the alternatives -> END.
    graph.add_conditional_edges(
        "recover",
        lambda state: route_after_agent(state, policy),
    )
    # The ``human`` and ``assess`` nodes route themselves with
    # Command(goto=...): ``human`` to ``tools``/``agent``, ``assess`` to
    # ``recover``/``agent``.

    compiled = graph.compile(checkpointer=checkpointer)
    logger.debug(
        "Agent graph built: nodes=agent,tools,human,assess,recover policy=%s "
        "checkpointer=%s tools_bound=%s",
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
