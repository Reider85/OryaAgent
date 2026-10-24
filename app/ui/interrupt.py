"""Permission ask-prompt (M-16): Chainlit buttons for the M-13 gate.

The graph's ``human`` node (M-13) pauses an ``ask`` decision with
LangGraph's dynamic ``interrupt()`` and waits for the UI to resume the
run with ``resume_command("approve" | "deny" | "always")``. This module
owns the Chainlit half of that contract:

* :func:`get_pending_interrupt` — extract the ``{"tool", "args",
  "reason"}`` payload a paused run carries (langgraph 1.2.x surfaces it
  on ``state.tasks[*].interrupts[*].value``; ``state.values`` does not
  contain ``__interrupt__`` after ``agraph.aget_state``);
* :func:`format_prompt` — the ask text (PROMPT_MVP M-16 wording);
* :func:`ask_permission` — show ``cl.AskActionMessage`` with three
  buttons (Approve / Deny / Approve & don't ask again) and map the
  answer to the resume value. Fail-closed: a timeout or an unrecognised
  answer resolves to ``deny`` — the same rule the human node applies to
  unknown resume values.

The Chainlit round-trip is injectable (``ask=``) so the mapping is unit
testable without a Chainlit websocket context.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

import chainlit as cl

#: Resume answers understood by ``resume_command`` (M-13 ``app.core.graph``).
APPROVE = "approve"
DENY = "deny"
ALWAYS = "always"

#: The three button values of the ask-prompt, in render order.
ANSWERS = (APPROVE, DENY, ALWAYS)

#: Cap for the args preview inside the prompt text.
_ARGS_PREVIEW_CHARS = 500


@dataclass(frozen=True)
class PendingInterrupt:
    """One permission pause extracted from a checkpoint state snapshot."""

    tool: str
    args: dict[str, Any] = field(default_factory=dict)
    reason: str = ""


def get_pending_interrupt(state: Any) -> PendingInterrupt | None:
    """Extract the permission payload from ``graph.aget_state`` output.

    The human node (M-13) pauses via
    ``interrupt({"tool", "args", "reason"})``; the paused task carries
    that payload on ``state.tasks[*].interrupts[*].value``. Returns
    ``None`` when no task holds a permission interrupt (finished run, a
    pause raised elsewhere, or an unreadable state object).
    """
    for task in getattr(state, "tasks", None) or ():
        for pending in getattr(task, "interrupts", None) or ():
            value = getattr(pending, "value", None)
            if isinstance(value, dict) and "tool" in value:
                return PendingInterrupt(
                    tool=str(value.get("tool", "")),
                    args=dict(value.get("args") or {}),
                    reason=str(value.get("reason") or ""),
                )
    return None


def _args_text(args: dict[str, Any]) -> str:
    """Render tool args as bounded single-line JSON."""
    try:
        text = json.dumps(args, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        text = str(args)
    if len(text) > _ARGS_PREVIEW_CHARS:
        return f"{text[:_ARGS_PREVIEW_CHARS]}... (+{len(text) - _ARGS_PREVIEW_CHARS} chars)"
    return text


def format_prompt(pending: PendingInterrupt) -> str:
    """Render the ask-prompt text (PROMPT_MVP M-16 wording)."""
    text = (
        f"Tool `{pending.tool}` wants to run with args: "
        f"`{_args_text(pending.args)}`. Approve?"
    )
    if pending.reason:
        text += f"\n\nReason: {pending.reason}"
    return text


def permission_actions() -> list[cl.Action]:
    """Build the three Approve / Deny / don't-ask-again buttons."""
    return [
        cl.Action(name=APPROVE, payload={"value": APPROVE}, label="Approve"),
        cl.Action(name=DENY, payload={"value": DENY}, label="Deny"),
        cl.Action(
            name=ALWAYS,
            payload={"value": ALWAYS},
            label="Approve & don't ask again",
            tooltip="Allow this tool for the rest of the session",
        ),
    ]


def normalize_answer(answer: Any) -> str:
    """Map an ask response to a resume value — fail-closed to ``deny``."""
    if not isinstance(answer, str):
        return DENY
    value = answer.strip().lower()
    return value if value in ANSWERS else DENY


async def ask_permission(
    pending: PendingInterrupt,
    *,
    ask: Callable[[str, list[cl.Action]], Awaitable[Any]] | None = None,
) -> str:
    """Ask the user; return the ``resume_command`` answer for the run.

    Buttons: ``Approve`` (run the call), ``Deny`` (refuse — the agent
    continues with a "Denied by user" tool result), ``Approve & don't
    ask again`` (approve and record the tool in the policy's session
    allowlist via the ``always`` resume value, M-13).

    The Chainlit round-trip is injectable (``ask=``) so the mapping is
    unit-testable without a Chainlit websocket context; the injected
    callable receives and returns the same shapes as
    ``cl.AskActionMessage`` (``content``, ``actions`` → response dict
    or ``None``).
    """
    content = format_prompt(pending)
    actions = permission_actions()
    if ask is not None:
        response = await ask(content, actions)
    else:
        response = await cl.AskActionMessage(content=content, actions=actions).send()
    if response is None:
        return DENY
    if isinstance(response, dict):
        return normalize_answer(response.get("name"))
    return normalize_answer(response)
