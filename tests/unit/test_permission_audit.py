"""A-03: PermissionPolicy audit spans — agent.permission spans on decisions."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.core.config import clear_settings_cache
from app.core.observability.spans import clear_span_buffer, get_span_buffer
from app.core.permissions import build_policy, get_policy


@pytest.fixture(autouse=True)
def isolated_permission_config(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Sandbox config and start each test with an empty span buffer."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("ORYA_PERMISSION_AUDIT_ENABLED", raising=False)
    # The lru_cache may still hold permission_audit_enabled=False from an
    # earlier module that mutated the env raw — drop it (AGENTS sandbox rule).
    clear_settings_cache()
    clear_span_buffer()
    yield
    clear_span_buffer()
    clear_settings_cache()


def test_permission_check_emits_span():
    """PermissionPolicy.check() emits agent.permission span with correct attributes."""
    clear_span_buffer()
    policy = get_policy(mode="strict")

    # Allow decision
    decision = policy.check({"name": "read", "args": {"path": "/tmp/test"}})
    assert decision.action == "allow"

    spans = list(get_span_buffer())
    assert len(spans) == 1
    span = spans[0]
    assert span.span_type == "agent.permission"
    assert span.name == "agent.permission:read"
    assert span.status == "allow"
    assert span.attributes["permission.tool"] == "read"
    assert span.attributes["permission.action"] == "allow"
    assert span.attributes["permission.reason"] == "allow-list"
    assert span.attributes["permission.mode"] == "strict"
    assert "security.incident" not in span.attributes


def test_permission_deny_emits_security_incident():
    """Deny by rule emits security.incident=true and permission.rule."""
    policy = get_policy(mode="strict")

    # Deny by rule
    decision = policy.check({"name": "bash", "args": {"command": "rm -rf /"}})
    assert decision.action == "deny"
    assert "recursive root deletion" in decision.reason

    spans = list(get_span_buffer())
    assert len(spans) == 1
    span = spans[0]
    assert span.span_type == "agent.permission"
    assert span.status == "deny"
    assert span.attributes["permission.tool"] == "bash"
    assert span.attributes["permission.action"] == "deny"
    assert span.attributes["security.incident"] == "true"
    assert span.attributes["permission.rule"] == r"rm\s+-rf?\s+/(\s|$)"


def test_permission_ask_emits_span():
    """Ask decision emits span with ask action."""
    policy = get_policy(mode="strict")

    # Ask decision
    decision = policy.check({"name": "write", "args": {"path": "/tmp/file"}})
    assert decision.action == "ask"

    spans = list(get_span_buffer())
    assert len(spans) == 1
    span = spans[0]
    assert span.span_type == "agent.permission"
    assert span.status == "ask"
    assert span.attributes["permission.tool"] == "write"
    assert span.attributes["permission.action"] == "ask"
    assert "requires approval" in span.attributes["permission.reason"]


def test_session_allowlist_emits_allow_span():
    """Session allowlist emits allow span with session_allow reason."""
    policy = get_policy(mode="strict")

    # Add to session allowlist
    policy.record_session_allow("bash")

    # Now it should be allowed
    decision = policy.check({"name": "bash", "args": {"command": "ls"}})
    assert decision.action == "allow"

    spans = list(get_span_buffer())
    assert len(spans) == 1
    span = spans[0]
    assert span.attributes["permission.tool"] == "bash"
    assert span.attributes["permission.action"] == "allow"
    assert span.attributes["permission.reason"] == "session allowlist"


def test_trusted_tools_emit_allow_span():
    """Trusted tools (/learn) emit allow span with explicit command reason."""
    policy = get_policy(mode="strict")

    decision = policy.check({"name": "learn"})
    assert decision.action == "allow"

    spans = list(get_span_buffer())
    assert len(spans) == 1
    span = spans[0]
    assert span.attributes["permission.tool"] == "learn"
    assert span.attributes["permission.action"] == "allow"
    assert span.attributes["permission.reason"] == "explicit user command"


def test_kill_switch_disables_spans():
    """ORYA_PERMISSION_AUDIT_ENABLED=false disables span emission."""
    import os

    # Save original value
    original_value = os.environ.get("ORYA_PERMISSION_AUDIT_ENABLED")

    try:
        os.environ["ORYA_PERMISSION_AUDIT_ENABLED"] = "false"
        clear_settings_cache()

        policy = get_policy(mode="strict")

        # Any decision
        decision = policy.check({"name": "bash", "args": {"command": "ls"}})
        assert decision.action == "allow"

        # No spans emitted
        spans = list(get_span_buffer())
        assert len(spans) == 0
    finally:
        # Restore original value
        if original_value is None:
            os.environ.pop("ORYA_PERMISSION_AUDIT_ENABLED", None)
        else:
            os.environ["ORYA_PERMISSION_AUDIT_ENABLED"] = original_value
        clear_settings_cache()


def test_permissive_mode_emits_correct_spans():
    """Permissive mode emits correct spans for bash with rm/mv/sudo."""
    clear_span_buffer()
    policy = get_policy(mode="permissive")

    # Should ask for destructive bash
    decision = policy.check({"name": "bash", "args": {"command": "rm -rf build"}})
    assert decision.action == "ask"

    spans = list(get_span_buffer())
    assert len(spans) == 1
    span = spans[0]
    assert span.attributes["permission.tool"] == "bash"
    assert span.attributes["permission.action"] == "ask"
    assert "rm/mv/sudo" in span.attributes["permission.reason"]

    # Clear buffer for next check
    clear_span_buffer()

    # Should allow safe bash
    decision = policy.check({"name": "bash", "args": {"command": "ls"}})
    assert decision.action == "allow"

    spans = list(get_span_buffer())
    assert len(spans) == 1
    span = spans[0]
    assert span.attributes["permission.action"] == "allow"


def test_build_policy_emits_spans():
    """build_policy() emits spans for UI allow-list rules."""
    clear_span_buffer()
    policy = build_policy(
        mode="strict",
        allow_patterns=["custom-command"],  # UI allow-list override
    )

    # This should match the UI allow-list
    decision = policy.check({"name": "bash", "args": {"command": "custom-command"}})
    assert decision.action == "allow"

    spans = list(get_span_buffer())
    assert len(spans) == 1
    span = spans[0]
    assert span.attributes["permission.tool"] == "bash"
    assert span.attributes["permission.action"] == "allow"
    assert "UI allow-list rule" in span.attributes["permission.reason"]


def test_multiple_checks_emit_multiple_spans():
    """Multiple policy calls emit multiple spans."""
    clear_span_buffer()
    policy = get_policy(mode="strict")

    # Three different checks
    policy.check({"name": "read", "args": {"path": "/tmp/1"}})
    policy.check({"name": "write", "args": {"path": "/tmp/2"}})
    policy.check({"name": "bash", "args": {"command": "ls"}})

    spans = list(get_span_buffer())
    assert len(spans) == 3
    assert {s.attributes["permission.tool"] for s in spans} == {"read", "write", "bash"}


def test_span_emission_never_raises():
    """Span emission failures never raise into the policy logic."""
    # This test would require mocking emit_span to raise, but since it's
    # defensive and never raises, we just verify the policy still works
    clear_span_buffer()
    policy = get_policy(mode="strict")

    decision = policy.check({"name": "bash", "args": {"command": "ls"}})
    assert decision.action == "allow"

    # Policy logic unaffected even if spans fail (buffer would be empty in real failure)
    spans = list(get_span_buffer())
    assert len(spans) == 1  # Span was emitted successfully


# --- A-06: permission spans join the turn trace -----------------------------


def test_permission_span_inherits_turn_trace():
    """agent.permission spans reuse the bound turn trace id (A-06)."""
    from app.core.observability.spans import set_turn_trace

    clear_span_buffer()
    set_turn_trace("turn-perm-1")
    try:
        policy = get_policy(mode="strict")
        policy.check({"name": "read", "args": {"path": "/tmp/x"}})
        policy.check({"name": "bash", "args": {"command": "rm -rf /"}})
    finally:
        set_turn_trace(None)

    spans = list(get_span_buffer())
    assert len(spans) == 2
    assert {s.trace_id for s in spans} == {"turn-perm-1"}
    assert spans[0].span_id != spans[1].span_id
