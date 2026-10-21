"""Prompt-injection defense - untrusted-content markers (M-07, part of M-22).

File contents, command output and pasted user text are *data*, never
instructions. The system prompt (M-05) already carries the Untrusted
Content Policy; this module provides the marker vocabulary that tools
(M-07 ``read``, later M-10 ``bash`` and M-11 ``grep``) use to frame
untrusted payloads so the model can visually separate them from the
conversation::

    [UNTRUSTED_CONTENT_START]
       1    def foo():
    [UNTRUSTED_CONTENT_END]

MVP scope: markers + ``wrap_untrusted`` only. M-22 extends this module
with the full defense layer without touching the tool contract:

* ``sanitize_untrusted(content) -> str`` - strip/neutralize patterns;
* ``detect_injection(content) -> bool`` - regex heuristics
  ("ignore previous instructions", "system:", chat-template markers);
* audit logging of suspected injections into ``memory_audit_log``.

Design constraints (see ``analytics/PROMPT_MVP.md`` 4, 9):

* markers are stable strings - ALPHA/BETA phases must keep them
  (the model is taught about them in the system prompt);
* wrapping never mutates the payload, it only frames it;
* no provider-specific logic lives here.
"""

from __future__ import annotations

UNTRUSTED_CONTENT_START = "[UNTRUSTED_CONTENT_START]"
UNTRUSTED_CONTENT_END = "[UNTRUSTED_CONTENT_END]"


def wrap_untrusted(content: str) -> str:
    """Frame untrusted payload with the standard markers.

    Used by tools that return file content or command output so the
    model can distinguish data from instructions (TRIZ #9 preliminary
    anti-action). Content is returned verbatim between the markers.
    """
    return f"{UNTRUSTED_CONTENT_START}\n{content}\n{UNTRUSTED_CONTENT_END}"
