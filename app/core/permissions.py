"""Permission policy (M-13) — the ask-before-destructive gate for tool calls.

Implements the decision layer between the agent-loop (M-04) and tool
execution: every pending tool call is checked against the deny-list, the
session allowlist, the allow-list and finally the mode-specific interrupt
rules. The graph's ``human`` node consumes :meth:`PermissionPolicy.check`
and turns ``ask`` decisions into LangGraph ``interrupt()`` pauses that the
UI (M-16) answers with ``resume_command("approve" | "deny" | "always")``.

Decision tree (ADR-004, `analytics/spec/ADR-004-permissions-default-ask.md`)::

    ToolCall -> deny-list          -> DENY   (always, wins over everything)
             -> session allowlist  -> ALLOW  ("don't ask again" this session)
             -> allow-list         -> ALLOW  (bypasses the mode)
             -> mode               -> strict:    ask on write/edit/bash
                                     permissive: ask on bash with rm/mv/sudo
                                     otherwise  ALLOW

Explicit user commands (``/learn``, ``/memory/*``) never interrupt — the
user asked for them on purpose (PROMPT_MVP M-13).

Batch semantics: if any call in one AI message is refused (by a rule or by
the user), the whole batch is refused — providers require exactly one
``ToolMessage`` per tool-call id, so a partially executed batch would
desync the conversation history.

Rules live in :class:`PermissionConfig` — built-in defaults from ADR-004,
optionally overridden per user in ``~/.orya/permissions.yml`` (see
``permissions_path`` in the settings). The file is never written by this
module; when it is absent the defaults apply.

Usage::

    from app.core.permissions import PermissionPolicy, get_policy

    policy = get_policy()  # mode + rules from the settings
    policy.should_interrupt("bash", {"command": "rm -rf build"})  # True (strict)
    policy.check({"name": "bash", "args": {"command": "ls"}}).action  # "allow"
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import yaml

from app.core.config import get_settings
from app.core.observability.spans import emit_span

logger = logging.getLogger(__name__)

#: Tools that require approval under the ``strict`` policy (PROMPT_MVP M-13).
STRICT_INTERRUPT_TOOLS = frozenset({"write", "edit", "bash"})

#: ``permissive`` only interrupts bash commands that look destructive.
PERMISSIVE_BASH_RE = re.compile(r"\b(rm|mv|sudo)\b")

#: Explicit user commands that never trigger an interrupt (PROMPT_MVP M-13).
TRUSTED_TOOLS = frozenset({"learn"})
TRUSTED_PREFIXES = ("memory/",)


@dataclass(frozen=True)
class Rule:
    """One allow/deny pattern (ADR-004 ``Rule``)."""

    tool: str
    pattern: str
    action: Literal["allow", "deny"]
    description: str = ""
    _regex: re.Pattern[str] | None = field(
        default=None, init=False, repr=False, compare=False
    )

    def __post_init__(self) -> None:
        try:
            object.__setattr__(self, "_regex", re.compile(self.pattern))
        except re.error as exc:
            logger.warning(
                "Invalid permission pattern %r (%s); rule disabled",
                self.pattern,
                exc,
            )
            object.__setattr__(self, "_regex", None)

    @property
    def disabled(self) -> bool:
        """True when the pattern failed to compile (rule never matches)."""
        return self._regex is None

    def matches(self, tool_name: str, text: str) -> bool:
        """True when the rule applies to ``tool_name`` and ``text`` matches."""
        if self._regex is None:
            return False
        if self.tool not in (tool_name, "*"):
            return False
        return self._regex.search(text) is not None


#: Built-in deny-list (ADR-004) — catastrophic patterns, matched anywhere
#: in the command and checked before everything else.
DEFAULT_DENY_RULES = (
    Rule(
        tool="bash",
        pattern=r"rm\s+-rf?\s+/(\s|$)",
        action="deny",
        description="rm -rf / — recursive root deletion",
    ),
    Rule(
        tool="bash",
        pattern=r":\(\)\s*\{\s*:\|:&\s*\}\s*;",
        action="deny",
        description="fork bomb",
    ),
    Rule(
        tool="bash",
        pattern=r"dd\s+if=.*of=/dev/(sd|nvme|hd)",
        action="deny",
        description="dd to disk device",
    ),
    Rule(
        tool="bash",
        pattern=r"mkfs\.",
        action="deny",
        description="filesystem format",
    ),
    Rule(
        tool="bash",
        pattern=r">\s*/dev/(sd|nvme|hd)",
        action="deny",
        description="redirect to disk device",
    ),
    Rule(
        tool="bash",
        pattern=r"chmod\s+(-R\s+)?777\s+/",
        action="deny",
        description="chmod 777 on root",
    ),
    Rule(
        tool="bash",
        pattern=r"curl\s+.*\|\s*(sh|bash|zsh)",
        action="deny",
        description="piped remote script execution",
    ),
    Rule(
        tool="bash",
        pattern=r"wget\s+.*\|\s*(sh|bash|zsh)",
        action="deny",
        description="piped remote script execution",
    ),
)

DEFAULT_ALLOW_RULES = (
    Rule(
        tool="bash",
        pattern=r"^ls(\s+|$).*",
        action="allow",
        description="ls and arguments",
    ),
    Rule(
        tool="bash",
        pattern=r"^cat\s+[^|;&]*",
        action="allow",
        description="cat files (no pipes/chains)",
    ),
    Rule(tool="bash", pattern=r"^pwd\s*$", action="allow"),
    Rule(
        tool="bash",
        pattern=r"^git\s+(status|diff|log|branch)(\s+|$).*",
        action="allow",
        description="git read commands",
    ),
    Rule(tool="bash", pattern=r"^grep(\s+|$).*", action="allow"),
    Rule(tool="bash", pattern=r"^find\s+[^|;&]*", action="allow"),
    Rule(tool="bash", pattern=r"^head\s+[^|;&]*", action="allow"),
    Rule(tool="bash", pattern=r"^tail\s+[^|;&]*", action="allow"),
    Rule(tool="bash", pattern=r"^wc\s+[^|;&]*", action="allow"),
    Rule(tool="read", pattern=r".*", action="allow"),
    Rule(tool="glob", pattern=r".*", action="allow"),
    Rule(tool="grep", pattern=r".*", action="allow"),
)


def _parse_rules(
    entries: Any,
    action: Literal["allow", "deny"],
    fallback: tuple[Rule, ...],
) -> list[Rule]:
    """Parse a YAML rule list; a missing/invalid list falls back to defaults."""
    if entries is None:
        return list(fallback)
    if not isinstance(entries, list):
        logger.warning(
            "permissions.yml: %s_rules must be a list; using defaults", action
        )
        return list(fallback)
    rules: list[Rule] = []
    for entry in entries:
        if not isinstance(entry, dict) or "pattern" not in entry:
            logger.warning(
                "permissions.yml: skipping invalid %s rule entry: %r", action, entry
            )
            continue
        rule = Rule(
            tool=str(entry.get("tool", "*")),
            pattern=str(entry["pattern"]),
            action=action,
            description=str(entry.get("description", "")),
        )
        if rule.disabled:
            continue  # invalid pattern already logged by Rule
        rules.append(rule)
    return rules


@dataclass
class PermissionConfig:
    """Allow/deny rule lists backing a :class:`PermissionPolicy`."""

    allow_rules: list[Rule] = field(default_factory=list)
    deny_rules: list[Rule] = field(default_factory=list)

    @classmethod
    def default(cls) -> PermissionConfig:
        return cls(
            allow_rules=list(DEFAULT_ALLOW_RULES),
            deny_rules=list(DEFAULT_DENY_RULES),
        )

    @classmethod
    def load(cls, path: Path | None = None) -> PermissionConfig:
        """Load rules from ``~/.orya/permissions.yml``; missing file -> defaults.

        A present key (even an empty list) replaces the built-in list for
        that section; an absent key keeps the default. Invalid files or
        entries log a warning and degrade to defaults instead of crashing.
        """
        if path is None or not path.exists():
            return cls.default()
        try:
            with path.open(encoding="utf-8") as fh:
                data = yaml.safe_load(fh) or {}
        except (OSError, yaml.YAMLError) as exc:
            logger.warning("Cannot read %s (%s); using default rules", path, exc)
            return cls.default()
        if not isinstance(data, dict):
            logger.warning("%s must contain a YAML mapping; using default rules", path)
            return cls.default()
        return cls(
            allow_rules=_parse_rules(
                data.get("allow_rules"), "allow", DEFAULT_ALLOW_RULES
            ),
            deny_rules=_parse_rules(data.get("deny_rules"), "deny", DEFAULT_DENY_RULES),
        )


@dataclass(frozen=True)
class Decision:
    """Outcome of a permission check (ADR-004 ``Decision``)."""

    action: Literal["allow", "deny", "ask"]
    reason: str = ""


def _rule_text(tool_name: str, args: Mapping[str, Any]) -> str:
    """Serialize tool args to the text rule patterns are matched against."""
    if tool_name == "bash":
        return str(args.get("command", ""))
    if tool_name in {"read", "write", "edit"}:
        return str(args.get("path", ""))
    if tool_name == "grep":
        return f"{args.get('pattern', '')} {args.get('path', args.get('glob_pattern', '*'))}"
    return json.dumps(args, sort_keys=True, default=str)


def _session_allowed_tools(session_state: Mapping[str, Any] | None) -> set[str]:
    """Extract the ``allowed_tools`` set from a session-state mapping."""
    if not session_state:
        return set()
    tools = session_state.get("allowed_tools") or ()
    return {str(name) for name in tools}


class PermissionPolicy:
    """M-13 permission policy: decide whether a tool call needs approval.

    Implements the ``PolicyLike`` contract of the agent graph (M-04):
    :meth:`check` returns a :class:`Decision`; the graph's ``human`` node
    pauses on ``ask`` via ``interrupt()``. :meth:`should_interrupt` is the
    single-call convenience wrapper from PROMPT_MVP M-13.

    Args:
        mode: ``"strict"`` or ``"permissive"``; defaults to the
            ``permission_policy`` setting.
        config: Rule lists; defaults to ``permissions_path`` on disk.
    """

    def __init__(
        self,
        mode: str | None = None,
        *,
        config: PermissionConfig | None = None,
    ) -> None:
        if mode is None:
            mode = get_settings().permission_policy
        if mode not in {"strict", "permissive"}:
            raise ValueError(
                f"Unknown permission mode {mode!r}; expected 'strict' or 'permissive'"
            )
        self.mode = mode
        if config is None:
            config = PermissionConfig.load(get_settings().permissions_path)
        self.config = config
        self._session_allowed: set[str] = set()

    def check(
        self,
        tool_call: Mapping[str, Any],
        session_state: Mapping[str, Any] | None = None,
    ) -> Decision:
        """Decide for one pending tool call: ``allow`` / ``deny`` / ``ask``.

        ``tool_call`` is the LangChain tool-call dict (``{"name", "args"}``).
        ``session_state`` may carry an ``allowed_tools`` collection (tools
        the user approved with "don't ask again" in this session).
        """
        name = str(tool_call.get("name", ""))
        args = tool_call.get("args") or {}

        # 1. Explicit user commands never interrupt (PROMPT_MVP M-13).
        if name in TRUSTED_TOOLS or name.startswith(TRUSTED_PREFIXES):
            decision = Decision("allow", "explicit user command")
            # A-03: Emit permission audit span for trusted tools
            self._emit_permission_span(name, decision, "")
            return decision

        text = _rule_text(name, args)

        # 2. Deny-list wins over everything, including the session allowlist.
        for rule in self.config.deny_rules:
            if rule.matches(name, text):
                logger.info("Permission deny: %s matched %r", name, rule.pattern)
                decision = Decision(
                    "deny", rule.description or f"denied by rule {rule.pattern}"
                )
                # A-03: Emit permission audit span for deny (with security incident)
                self._emit_permission_span(name, decision, text)
                return decision

        # 3. Session allowlist ("Approve & don't ask again for this tool").
        if name in self._session_allowed | _session_allowed_tools(session_state):
            decision = Decision("allow", "session allowlist")
            # A-03: Emit permission audit span for session allowlist
            self._emit_permission_span(name, decision, text)
            return decision

        # 4. Allow-list bypasses the mode (ADR-004: matches ask-mode).
        for rule in self.config.allow_rules:
            if rule.matches(name, text):
                decision = Decision("allow", rule.description or "allow-list")
                # A-03: Emit permission audit span for allow-list
                self._emit_permission_span(name, decision, text)
                return decision

        # 5. Mode-specific interrupt rules.
        if self.mode == "strict":
            if name in STRICT_INTERRUPT_TOOLS:
                decision = Decision("ask", f"{name} requires approval (strict mode)")
                # A-03: Emit permission audit span for ask
                self._emit_permission_span(name, decision, text)
                return decision
            decision = Decision("allow")
            # A-03: Emit permission audit span for allow in strict mode
            self._emit_permission_span(name, decision, text)
            return decision

        # permissive: only bash with rm/mv/sudo is worth a prompt.
        if name == "bash" and PERMISSIVE_BASH_RE.search(text):
            decision = Decision(
                "ask", "bash with rm/mv/sudo requires approval (permissive mode)"
            )
        else:
            decision = Decision("allow")

        # A-03: Emit permission audit span
        self._emit_permission_span(name, decision, text)
        return decision

    def should_interrupt(
        self,
        tool_name: str,
        args: Mapping[str, Any] | None = None,
        session_state: Mapping[str, Any] | None = None,
    ) -> bool:
        """PROMPT_MVP M-13 contract: does this call need user approval?"""
        decision = self.check({"name": tool_name, "args": args or {}}, session_state)
        return decision.action == "ask"

    def _emit_permission_span(
        self, tool_name: str, decision: Decision, text: str
    ) -> None:
        """Emit agent.permission span (A-03 audit-log spans)."""
        try:
            settings = get_settings()
            if not settings.permission_audit_enabled:
                return

            attributes = {
                "permission.tool": tool_name,
                "permission.action": decision.action,
                "permission.reason": decision.reason,
                "permission.mode": self.mode,
            }

            # A-03: security.incident=true on deny-rule matches
            if decision.action == "deny":
                # Check if deny came from a deny-rule (not just mode)
                for rule in self.config.deny_rules:
                    if rule.matches(tool_name, text):
                        attributes["security.incident"] = "true"
                        attributes["permission.rule"] = rule.pattern
                        break

            emit_span(
                span_type="agent.permission",
                name=f"agent.permission:{tool_name}",
                attributes=attributes,
                status=decision.action,
                provider="",  # Not applicable for permission spans
                model="",  # Not applicable for permission spans
            )
        except (
            Exception
        ):  # pragma: no cover - defensive: observability never breaks the agent
            logger.warning("Permission span emission failed", exc_info=True)

    def record_session_allow(self, tool_name: str) -> None:
        """Remember "Approve & don't ask again for this tool in session"."""
        if tool_name:
            self._session_allowed.add(tool_name)

    def session_allowed_tools(self) -> set[str]:
        """Tools approved through the session allowlist (M-13).

        Lets a caller move the allowlist onto a freshly built policy when
        the settings change (M-24 ``/sessions`` policy cache).
        """
        return set(self._session_allowed)


def get_policy(
    mode: str | None = None,
    *,
    config_path: Path | None = None,
) -> PermissionPolicy:
    """Build the permission policy from the settings (M-13 entry point)."""
    settings = get_settings()
    config = PermissionConfig.load(config_path or settings.permissions_path)
    return PermissionPolicy(mode or settings.permission_policy, config=config)


def build_policy(
    mode: str | None = None,
    *,
    allow_patterns: Sequence[str] = (),
    config_path: Path | None = None,
) -> PermissionPolicy:
    """Build a policy from settings plus per-client overrides (M-17/M-24).

    The API accepts the UI's settings panel state (model aside) with each
    request: ``mode`` selects ``strict``/``permissive`` (``None`` or an
    unknown value falls back to the configured default / ``strict``, the
    rule the M-17 panel applied) and ``allow_patterns`` adds extra
    ``tool="*"`` allow rules on top of ``~/.orya/permissions.yml`` — the
    «Allow List» textarea of the settings panel.

    Returns a full :class:`PermissionPolicy` (the ``PolicyLike`` the
    graph consumes).
    """
    settings = get_settings()
    resolved = mode or settings.permission_policy
    if resolved not in {"strict", "permissive"}:
        logger.warning("Unknown permission mode %r; using 'strict'", resolved)
        resolved = "strict"

    config = PermissionConfig.load(config_path or settings.permissions_path)
    extra = [
        Rule(
            tool="*",
            pattern=pattern.strip(),
            action="allow",
            description="UI allow-list rule",
        )
        for pattern in allow_patterns
        if pattern.strip()
    ]
    if extra:
        config = PermissionConfig(
            allow_rules=[*config.allow_rules, *extra],
            deny_rules=config.deny_rules,
        )
    return PermissionPolicy(resolved, config=config)
