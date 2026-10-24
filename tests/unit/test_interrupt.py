"""Unit tests for M-16 — app.ui.interrupt (payload extraction + answer map).

No Chainlit runtime: the ask round-trip is injectable (``ask=``), so the
prompt formatting, button values and the fail-closed answer mapping are
covered without a websocket context.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.ui import interrupt as ui_interrupt


class _FakeInterrupt:
    def __init__(self, value: Any) -> None:
        self.value = value


class _FakeTask:
    def __init__(self, interrupts: tuple = ()) -> None:
        self.interrupts = interrupts


class _FakeState:
    def __init__(self, tasks: tuple = ()) -> None:
        self.tasks = tasks
        self.next = ("human",) if tasks else ()


# --- get_pending_interrupt ------------------------------------------------


def test_get_pending_interrupt_extracts_tool_args_reason() -> None:
    state = _FakeState(
        tasks=(
            _FakeTask(
                interrupts=(
                    _FakeInterrupt(
                        {
                            "tool": "bash",
                            "args": {"command": "rm x"},
                            "reason": "strict",
                        }
                    ),
                )
            ),
        )
    )

    pending = ui_interrupt.get_pending_interrupt(state)

    assert pending == ui_interrupt.PendingInterrupt(
        tool="bash", args={"command": "rm x"}, reason="strict"
    )


def test_get_pending_interrupt_none_without_tasks() -> None:
    assert ui_interrupt.get_pending_interrupt(_FakeState()) is None


def test_get_pending_interrupt_none_for_foreign_interrupt() -> None:
    state = _FakeState(tasks=(_FakeTask(interrupts=(_FakeInterrupt("other"),)),))

    assert ui_interrupt.get_pending_interrupt(state) is None


def test_get_pending_interrupt_none_on_garbage_state() -> None:
    assert ui_interrupt.get_pending_interrupt(object()) is None
    assert ui_interrupt.get_pending_interrupt(None) is None


def test_get_pending_interrupt_defaults_missing_fields() -> None:
    state = _FakeState(
        tasks=(_FakeTask(interrupts=(_FakeInterrupt({"tool": "read"}),)),)
    )

    pending = ui_interrupt.get_pending_interrupt(state)

    assert pending is not None
    assert pending.tool == "read"
    assert pending.args == {}
    assert pending.reason == ""


# --- format_prompt ---------------------------------------------------------


def test_format_prompt_matches_spec_wording() -> None:
    pending = ui_interrupt.PendingInterrupt(tool="bash", args={"command": "ls"})

    text = ui_interrupt.format_prompt(pending)

    assert text == 'Tool `bash` wants to run with args: `{"command": "ls"}`. Approve?'


def test_format_prompt_appends_reason() -> None:
    pending = ui_interrupt.PendingInterrupt(tool="write", args={}, reason="strict mode")

    text = ui_interrupt.format_prompt(pending)

    assert text.endswith("Reason: strict mode")


def test_format_prompt_caps_long_args() -> None:
    pending = ui_interrupt.PendingInterrupt(tool="bash", args={"command": "x" * 900})

    text = ui_interrupt.format_prompt(pending)

    assert "chars)" in text
    assert len(text) < 700


# --- normalize_answer ------------------------------------------------------


@pytest.mark.parametrize(
    ("answer", "expected"),
    [
        ("approve", "approve"),
        ("Deny", "deny"),
        (" ALWAYS ", "always"),
        (None, "deny"),
        ("", "deny"),
        ("maybe", "deny"),
        (True, "deny"),
        (42, "deny"),
    ],
)
def test_normalize_answer_fail_closed(answer: Any, expected: str) -> None:
    assert ui_interrupt.normalize_answer(answer) == expected


# --- ask_permission --------------------------------------------------------


async def test_ask_permission_maps_button_name() -> None:
    asked: list[tuple[str, list]] = []

    async def fake_ask(content: str, actions: list) -> dict:
        asked.append((content, actions))
        return {"name": "always", "payload": {"value": "always"}}

    pending = ui_interrupt.PendingInterrupt(tool="bash", args={"command": "ls"})
    answer = await ui_interrupt.ask_permission(pending, ask=fake_ask)

    assert answer == "always"
    content, actions = asked[0]
    assert "Tool `bash`" in content
    assert [a.name for a in actions] == ["approve", "deny", "always"]
    assert [a.label for a in actions] == [
        "Approve",
        "Deny",
        "Approve & don't ask again",
    ]


async def test_ask_permission_timeout_is_deny() -> None:
    async def fake_ask(content: str, actions: list) -> None:
        return None

    pending = ui_interrupt.PendingInterrupt(tool="bash", args={})

    assert await ui_interrupt.ask_permission(pending, ask=fake_ask) == "deny"


async def test_ask_permission_unknown_button_is_deny() -> None:
    async def fake_ask(content: str, actions: list) -> dict:
        return {"name": "wat", "payload": {}}

    pending = ui_interrupt.PendingInterrupt(tool="bash", args={})

    assert await ui_interrupt.ask_permission(pending, ask=fake_ask) == "deny"
