# A-03 — PermissionPolicy v2 (audit-log spans)

> Ticket: `PROMPT_ALPHA.md` §3.1 (A-03) | Estimate: 4 часа | Status: executed

## Spec summary

«PermissionPolicy v2 (audit-log spans) | 4 часа | security.span attributes» — каждый вызов `PermissionPolicy.check()` и исходы user-resume эмитят span `agent.permission` в in-process buffer (A-02 seam) с атрибутами `permission.*` и `security.incident=true` на deny-rule. Задел под A-16 Observability SDK (app/core/observability/spans.py).

## Deviations & decisions

1. **Вынос общего span-шова в `app/core/observability/spans.py`** — `SpanRecord`/buffer/emit_span() для повторного использования (A-16), backward-compat через re-export из `llm/tracing.py`.
2. **Эмиссия в `check()`** — allow/deny/ask решения с атрибутами tool/action/reason/mode; deny-rule → `security.incident=true` + `permission.rule`.
3. **Эмиссия в `human_node`** — user approve/deny/always/batch-refusal спаны (полный audit-trail).
4. **PII fail-closed** — no tool args content в атрибутах (только tool name, reason, rule pattern).
5. **Kill-switch default ON** (`ORYA_PERMISSION_AUDIT_ENABLED=true`) — поведение не меняется, observability не влияет на логику.
6. **Exporter reuse** — `ORYA_LLM_TRACE_EXPORTER` stdout для debug-лога всех спанов (A-02 контракт).

## Files

- `app/core/observability/__init__.py` (new): exports.
- `app/core/observability/spans.py` (new): `SpanRecord`, `_span_buffer`, `SPAN_BUFFER_MAX`, `get_span_buffer()`, `clear_span_buffer()`, `_finalize()`, `_new_ids()`, `emit_span()`.
- `app/core/llm/tracing.py`: import from observability.spans, re-export `SpanRecord`/`get_span_buffer`/`clear_span_buffer`.
- `app/core/llm/__init__.py`: unchanged (re-exports still work).
- `app/core/permissions.py`: emit `agent.permission` spans in `check()`; `security.incident=true` on deny-rule.
- `app/core/graph.py` human_node: emit user decision spans (approve/deny/always, batch refusal, fail-closed).
- `app/core/config.py`: `permission_audit_enabled` setting.
- `.env.example`: A-03 block.
- `tests/unit/test_permission_audit.py` (new): buffer assertions, deny→security.incident, kill-switch, user-decision spans via human_node, no-raise on emitter failure.
- `AGENTS.md`: update ALPHA status line (A-00…A-03) + permission audit seam.

## Verification

`make format` → `make lint` → `uv run pytest` (unit + e2e + smoke; infra скипаются условно).

## DoD coverage

- ✅ `PermissionPolicy.check()` эмитит `agent.permission` span с permission.* атрибутами.
- ✅ Deny-rule → `security.incident=true` + `permission.rule` атрибут.
- ✅ Kill-switch `ORYA_PERMISSION_AUDIT_ENABLED=false` отключает эмиссию спанов.
- ✅ Graph human_node эмитит user approve/deny/always/batch-refusal spans.
- ✅ Session-allowlist и trusted tools → `action=allow` в спане.
- ✅ PII fail-closed: нет tool args в атрибутах.
- ✅ Buffer очищается между тестами, no-raise при ошибках эмиссии.
- ✅ Backward-compat: A-02 tests и re-exports работают.
- ✅ `make format` → `make lint` → `uv run pytest` pass.

## Follow-ups

- A-16/A-17: replace buffer with agent_obs SDK (span correlation, real OTLP).
- A-16: `agent_obs.SpanType.AGENT_PERMISSION` (переименование span_type).