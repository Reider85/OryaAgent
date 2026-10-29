# A-02 — LLM-seam extension (trace-wrapping)

> Ticket: `PROMPT_ALPHA.md` §3.1 (A-02) | Estimate: 1 день | Status: executed

## Spec summary

«Оборачивает `get_llm()` в span-emitter» — каждый вызов через LLM-шов
(M-01) эмитит span `llm.call`. Опора для A-16 (OryaObservability SDK:
`llm.call` входит в его span-типы) и A-14 (cost-tracking в span'ах).

## Deviations & decisions

1. **Внутренний emitter, без зависимости от `agent_obs`.** Пакет
   `../OryaObservability` не установлен в venv и тянет torch/spacy/
   transformers — формальное подключение оставлено A-16. Шов совместим:
   имена атрибутов (`llm.provider`, `llm.model`, `tokens.*`, `status`)
   и тип span (`llm.call`) совпадают с `agent_obs.SpanType.LLM_CALL`.
2. **Kill-switch `ORYA_LLM_TRACE_ENABLED` (default true).** При `false`
   фабрика возвращает сырой адаптер — нулевой оверхед и прежние
   concrete-type assertions в `tests/unit/test_llm_seam.py`.
3. **Без контента сообщений** (input/output text) — PII fail-closed
   умолчанием; guardrail/content-sampling добавит A-16.
4. `cost.usd` не считается — это A-14 (pricing.yaml уже в репо).
5. Стриминг (`_stream`/`_astream`) форвардится без span (agent-loop
   использует только `ainvoke` — `graph._ainvoke_with_retry`).

## Files

- `app/core/llm/tracing.py` (new): `SpanRecord`, bounded buffer
  (`deque maxlen=1000`), `TracedChatModel`, `wrap_with_tracing()`.
- `app/core/llm/factory.py`: единая точка выхода `get_llm()` →
  `wrap_with_tracing(instance, provider=..., model_name=resolved.model_id)`.
- `app/core/config.py`: `llm_trace_enabled`, `llm_trace_exporter`
  (`off|stdout`).
- `.env.example`, `app/core/llm/__init__.py` (exports), `AGENTS.md`.
- `tests/unit/test_llm_tracing.py` (new, 10 tests);
  `tests/unit/test_llm_seam.py` — sandbox `ORYA_LLM_TRACE_ENABLED=false`.

## Verification

`ruff format` → `ruff check` → `uv run pytest` (unit + e2e + smoke;
infra-тесты скипаются условно).
