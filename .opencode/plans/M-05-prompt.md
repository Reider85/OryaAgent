# Plan: M-05 — System-prompt-builder + untrusted-content warning

**Status:** executed
**Commit message:** `M-05: system-prompt-builder + untrusted-content policy block`

## Deviations from spec (deliberate, documented)

| Spec says | Done | Why |
|---|---|---|
| `format_tool_to_openai_function` | `convert_to_openai_function` | Former removed in langchain_core 1.6.x; latter is the public API |
| BACKLOG4 AC `len == 1 + len(state["messages"])` | Return `[SystemMessage]` only | M-04 graph already prepends history; duplicating would break the loop |
| BACKLOG4 `ChatPromptTemplate` | Plain section functions + join | Matches v6 ARCHITECT6 §3.1.2 (inherited design); avoids `{}`-escaping hazards in file contents |

## Result

- `app/core/prompt.py` — six section functions (`identity_block`, `tool_descriptions`, `project_context_block`, `format_memory_block`, `behavior_rules_block`, `untrusted_content_policy_block`) + `build_system_prompt(state, tools) -> list[BaseMessage]`.
- `app/core/graph.py` — `SystemPromptFn` type widened to `Sequence[BaseMessage]` (runtime already supported it).
- `tests/unit/test_prompt.py` — 14 tests (sections, tool JSON, memory injection/truncation, cacheable-prefix ordering, missing-file placeholders).
- README: M-04/M-05 marked ✅ + «System Prompt (M-05)» section.
- Verified: 119 unit tests green, full suite 119 passed / 13 skipped (integration need infra), ruff check + format clean.
