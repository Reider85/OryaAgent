# A-08 — Smoke-тесты v2 (auth, rate-limit, observability)

> Ticket: `analytics/PROMPT_ALPHA.md` §3.1 (A-08) | Estimate: 1 день | Status: executed

## Spec summary

«Smoke-тесты v2 (auth, rate-limit, observability) | 1 день | +5 сценариев» —
одна строка в таблице тикетов PROMPT_ALPHA.md:79 (детальной секции для A-08
в PROMPT_ALPHA/BACKLOG6 нет; BACKLOG6 §3 содержит только A-16/A-17).
Структура файлов §13 называет `smoke/test_smoke_v2.py`. Legacy A-08
«LLM circuit-breaker» из BACKLOG4/5 — устаревшая нумерация v4/v5, к
v6/v7 ALPHA отношения не имеет. Расшифровка: smoke-сюит получает пять
ALPHA-сценариев, закрывающих auth (A-00), rate-limit (A-01) и
observability-шов (A-02/A-03/A-04/A-06) на HTTP/graph-уровне.

## Deviations & decisions

1. **Баланс сценариев 2/2/1** (auth/rate-limit/observability), согласован
   перед реализацией: один сценарий observability плотный (turn → spans →
   health → kill-switch), два auth'овых — enforcement + operator-loop
   (CLI `orya auth token` → HTTP).
2. **Ноль новых env и ноль правок `app/`.** Сценариев достаточно того, что
   уже дала неделя 1 ALPHA: kill-switch'и читаются per-request, health
   эндпоинты уже публичны по умолчанию (`AUTH_PUBLIC_PATHS`).
3. **Детерминизм по канону M-18:** scripted `FakeMessagesListChatModel`,
   `MemoryRateLimiter` + замороженные часы (паттерн `test_rate_limit._enable`),
   токены минтятся in-process. Без Postgres/Redis/LLM-ключей.
4. **Observability-сценарий — сквозной, но graph-level** (не HTTP-turn):
   HTTP-turn инжектит модель через monkeypatch `build_session_graph`
   (как e2e SSE) и обошёл бы `get_llm()`-обёртку; для проверки
   TracedChatModel-шва честнее обернуть фейк через `wrap_with_tracing`
   напрямую. Health-эндпоинты проверяются тем же session-scoped `client`.
5. **Гигиена span-буфера обязательна** (реgression-прецедент A-06:
   smoke оставлял span'ы → `span_buffer_size == 0` падал в полном
   прогоне): autouse-фикстура чистит буфер и turn-trace до и после.
6. **Kill-switch в 5-м сценарии, не отдельным 6-м:** «+5 сценариев» —
   жёсткое число; `ORYA_LLM_TRACE_ENABLED=false` → raw adapter → ноль
   новых span'ов проверяется в конце пятого.

## Files

- `tests/smoke/test_smoke_v2.py` (new) — 5 сценариев:
  1. auth: 401 missing/garbage, 200 валидный JWT, `/health` публичен;
  2. operator-loop: CLI `orya auth token --user` → JWT работает по HTTP;
  3. per-user rate-limit: RPM=2 → 429 + `Retry-After`/`x-ratelimit-*`,
     второй пользователь не задет;
  4. `/learn` tight bucket (LEARN_RPM=2) → 429, пока общий бюджет не тронут;
  5. scripted turn → `llm.call` span + `agent.permission` span,
     `/health/observability` отражает буфер, `/health/sampler-proxy` 503,
     kill-switch off → raw adapter, новых span'ов нет.
- `.opencode/plans/A-08-smoke-tests-v2.md` (this file).

## Verification

`uv run pytest tests/smoke/test_smoke_v2.py -v` → 5 passed.
Затем `make format` → `make lint` → `uv run pytest` (полный прогон).

## DoD coverage

- ✅ Ровно +5 smoke-сценариев (auth, rate-limit, observability) в
  `tests/smoke/test_smoke_v2.py` — детерминированно, без инфры.
- ✅ Auth enforcement и operator-loop закрыты на HTTP-уровне.
- ✅ Per-user и per-endpoint (learn) rate-лимиты видны как 429 с
  корректными заголовками; бакеты изолированы.
- ✅ Сквозная observability-цепочка: traced-ход → span-буфер →
  `/health/observability`; fail-closed sampler-proxy; kill-switch.
- ✅ Span-буфер/limiter/turn-trace чистятся до и после каждого сценария
  (совместимость с полным прогоном).
- ✅ `make format` → `make lint` → `uv run pytest` pass.

## Follow-ups

- A-16/A-17 (OryaObservability SDK, sampler-proxy): когда spans уйдут в
  Langfuse, сценарий 5 расширяется проверкой экспорта (TODO в коде не
  оставлено — осознанно вне A-08).
- A-09 README v2: описать operator-loop (CLI token → curl с Bearer).

## Commit message

`A-08: smoke tests v2 (+5 scenarios: auth, rate-limit, observability)`
