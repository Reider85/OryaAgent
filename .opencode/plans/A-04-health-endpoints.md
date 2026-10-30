# A-04 — Health endpoints

> Ticket: `PROMPT_ALPHA.md` §3.1 (A-04) | Estimate: 4 часа | Status: executed

## Spec summary

«Health endpoints | 4 часа | /health, /health/observability, /health/sampler-proxy» — три эндпоинта для проверки здоровья системы: базовый liveness, observability SDK status, sampler-proxy доступность. Все exempt из auth/rate-limit middleware.

## Deviations & decisions

1. **Маппинг observability-статуса на A-02** — вместо отсутствующего OTLP/Langfuse SDK: `sdk_enabled=llm_trace_enabled`, `exporter_connected=llm_trace_exporter!="off"` (stdout считается подключённым), `guardrail_ready=permission_audit_enabled`. Честно отражает текущий in-process state.
2. **sampler-proxy URL field** — добавлено `sampler_proxy_url` в settings (env-only, default `http://sampler-proxy:4321`), пустая строка = не сконфигурирован → 503.
3. **HTTP probe pattern** — повторяет `app/api/llm.py:50-96` + `app/core/llm/adapters/local.py`, async httpx HEAD с 2s timeout, never raise, 200/503 как у provider health.
4. **Keep existing /health response** — без изменений для совместимости с `tests/unit/test_app_health.py`.
5. **Auth/rate-limit exempt** — `/health` префикс уже публичный в middleware (A-00/A-01), правок не требуется.

## Files

- `app/core/config.py` — добавить `sampler_proxy_url` field.
- `app/api/health.py` (new) — три эндпоинта с docstring A-04, APIRouter(tags=["health"]).
- `app/main.py` — импорт health_router, remove inline /health.
- `tests/unit/test_api_health.py` (new) — sandboxed tests, isolated fixture, все три эндпоинта + auth exemption.
- `.opencode/plans/A-04-health-endpoints.md` (this file).

## Verification

`make format` → `make lint` → `uv run pytest tests/unit/test_api_health.py` + `tests/unit/test_app_health.py`

## DoD coverage

- ✅ `/health` — 200 `{"status": "ok", "message": "OryaAgent API is running"}` (совместимость с существующим тестом).
- ✅ `/health/observability` — 200 с `{sdk_enabled, exporter_connected, guardrail_ready, span_buffer_size}`.
- ✅ `/health/sampler-proxy` — 200 при доступности, 503 при недоступности/не сконфигурированности, async probe с timeout.
- ✅ Auth exemption — все `/health*` endpoints работают без токена при `ORYA_AUTH_ENABLED=true`.
- ✅ Rate-limit exemption — health endpoints не потребляют quota.
- ✅ `make format` → `make lint` → `uv run pytest` pass.
- ✅ Sandbox тесты с переключением `ORYA_*` env vars.

## Follow-ups

- A-10/A-17: docker-compose sampler-proxy service integration.
- A-15/A-16: OTLP exporter health check (тогда `exporter_connected` станет динамическим).