"""Prompt-injection detection (M-22, first piece).

Regex heuristics for detecting prompt-injection attempts in tool output,
user input, and file content. M-22 extends this module with full defense
layers (sanitization + audit logging); this module provides the detection
foundation.

Pattern categories (from PROMPT_MVP M-22):

1. **Instruction override** — attempts to override the system prompt:
   - "ignore previous instructions", "prior instructions", "above instructions"
   - "disregard all prior directions"
2. **Role override** — attempts to change the AI's role:
   - "You are now assistant:", "System:", "Role:"
3. **Chat template markers** — attempts to inject chat format tokens:
   - `<|im_start|>`, `<|im_end|>`, `</s>`, `<|im_start|>assistant`
4. **Context escape** — attempts to break out of the untrusted context:
   - "End of message", "End of instructions", "Begin of instructions"

Detection returns the matched pattern category name on match, None otherwise.

Usage::

    from app.core.security import detect_injection

    if detect_injection("ignore previous instructions"):
        # Handle injection attempt
        ...

    if detect_injection("You are now assistant:"):
        # Handle role override attempt
        ...
"""

from __future__ import annotations

import re

UNTRUSTED_CONTENT_START = "[UNTRUSTED_CONTENT_START]"
UNTRUSTED_CONTENT_END = "[UNTRUSTED_CONTENT_END]"

# Injection patterns with compiled regexes.
# Each tuple is (pattern_id: str, compiled_regex: Pattern).
INJECTION_PATTERNS: list[tuple[str, re.Pattern]] = [
    # 1. Instruction override
    (
        "ignore_previous_instructions",
        re.compile(
            r"ignore\s+(all\s+)?(previous|prior|above)\s+instructions",
            re.IGNORECASE,
        ),
    ),
    (
        "disregard_directions",
        re.compile(
            r"disregard\s+(all\s+)?(directions|instructions)",
            re.IGNORECASE,
        ),
    ),
    (
        "end_of_message",
        re.compile(
            r"end\s+of\s+(message|instructions|prompt|response)",
            re.IGNORECASE,
        ),
    ),
    (
        "begin_of_instructions",
        re.compile(
            r"begin\s+of\s+instructions",
            re.IGNORECASE,
        ),
    ),
    # 2. Role override
    (
        "role_override",
        re.compile(
            r"^\s*(system|assistant|user)\s*:",
            re.IGNORECASE | re.MULTILINE,
        ),
    ),
    (
        "you_are_now",
        re.compile(
            r"you\s+are\s+now\s+(an\s+)?(assistant|chatbot|model|bot)",
            re.IGNORECASE,
        ),
    ),
    (
        "act_as",
        re.compile(
            r"act\s+as\s+(an\s+)?(assistant|chatbot|model|bot)",
            re.IGNORECASE,
        ),
    ),
    # 3. Chat template markers
    (
        "im_start_marker",
        re.compile(r"<\|im_start\|>", re.IGNORECASE),
    ),
    (
        "im_end_marker",
        re.compile(r"<\|im_end\|>", re.IGNORECASE),
    ),
    (
        "eos_marker",
        re.compile(r"</s>", re.IGNORECASE),
    ),
    (
        "chat_template",
        re.compile(
            r"<\s*im_start\s*>|<\s*im_end\s*>|<\s*\|im_start\|\s*>|<\s*\|im_end\|\s*>",
            re.IGNORECASE,
        ),
    ),
]


def wrap_untrusted(content: str) -> str:
    """Frame untrusted payload with the standard markers.

    Used by tools that return file content or command output so the
    model can distinguish data from instructions (TRIZ #9 preliminary
    anti-action). Content is returned verbatim between the markers.
    """
    return f"{UNTRUSTED_CONTENT_START}\n{content}\n{UNTRUSTED_CONTENT_END}"


def detect_injection(content: str) -> str | None:
    """Check if content contains a prompt-injection pattern.

    Args:
        content: Text to check for injection patterns.

    Returns:
        The pattern ID (str) of the first match, or None if no injection
        detected. Pattern IDs are defined in ``INJECTION_PATTERNS``.
    """
    for pattern_id, regex in INJECTION_PATTERNS:
        if regex.search(content):
            return pattern_id
    return None
