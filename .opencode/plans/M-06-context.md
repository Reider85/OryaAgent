# Plan: M-06 — Context-manager (trim_messages)

**Status:** executed
**Commit message:** `M-06: context-manager (trim_messages + tool-result truncation + trim_thinking)`

## Deviations from spec (deliberate, documented)

| Spec says | Done | Why |
|---|---|---|
| BACKLOG4: `trim_state(state, max_tokens=128_000)` | Both: `trim_messages(messages, max_tokens)` (invariant, PROMPT_MVP §4) + thin `trim_state(state)` wrapper | Two authoritative docs; wrapper is ~3 lines |
| Default window 128_000 (BACKLOG4) vs 120_000 (PROMPT_MVP) | 120_000 via new `Settings.context_max_tokens` | PROMPT_MVP is the phase document being executed |
| `trim_thinking()` in `llm.py` (risk table) vs `context.py` (file tree §10) | `context.py` | File tree is more specific; LLM-seam untouched |
| Graph integration unspecified | `trim_fn` seam on `build_graph(..., trim_fn=None)`, applied in `agent_node` before system-prompt prepend | Same injection pattern as M-05 `system_prompt_fn`; M-04 stays independent of M-06 |

## Result

- `app/core/context.py` — `count_tokens()` (tiktoken for known models, chars/4 fallback — never `encoding_for_model` for unknown), `truncate_tool_messages()` (>5000 chars → 100 head + marker + 50 tail), `trim_thinking()` (strips `additional_kwargs["reasoning_content"]`), `trim_messages()` pipeline (truncate → strip → LangChain `trim_messages` with `strategy="last"`, `start_on="human"`, `include_system=True`, `allow_partial=False`), `trim_state()` wrapper.
- `app/core/graph.py` — `TrimFn` type + `trim_fn` kwarg on `build_graph()`; `agent_node` trims history before prepending the per-call system prompt.
- `app/core/config.py` — `context_max_tokens: int = 120_000` (`ORYA_CONTEXT_MAX_TOKENS` / yaml `context_max_tokens`) + `_YAML_FALLBACKS` entry.
- `pyproject.toml` — explicit `tiktoken>=0.7.0` dependency (was transitive only).
- `tests/unit/test_context.py` — 19 tests: token counting (tiktool vs approximation, list content, tool-calls), tool truncation (line-based + char fallback, no mutation), thinking strip, sliding window (budget, system survival, starts-on-human, settings default, no mutation), `trim_state`, graph `trim_fn` seam.
- `tests/unit/test_config.py` — defaults + yaml-fallback assertions for `context_max_tokens`.
- README: M-06 ✅ in checklist + «Context Manager (M-06)» section; `.env.example`: `ORYA_CONTEXT_MAX_TOKENS`.
- Verified: 143 unit tests green, ruff check + format clean.
