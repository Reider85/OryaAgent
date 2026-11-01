# A-15 — Langfuse OTLP/HTTP JSON span export

> Ticket: `analytics/PROMPT_ALPHA.md:86` (A-15) | Estimate: 6 часов | Status: executed

## Spec summary

«Langfuse integration | 6 часов | OTEL exporter → Langfuse»
(PROMPT_ALPHA.md:86). Детального раздела в BACKLOG6 §3 нет (там новые
только A-16/A-17) — скоуп взят из таблицы PROMPT_ALPHA §3.1, env-контракта
README (A-09 forward-looking) и follow-up заметок A-04/A-06/A-10/A-14
(`.opencode/plans/A-*.md`), которые явно откладывали «export wiring» на
A-15. Референс маппинга — sibling `../OryaObservability`
`agent_obs/exporters/langfuse_exporter.py` (ARCHITECT6: «Langfuse exporter,
OTLP-mapping — готовы»).

## Deviations & decisions

Скоуп согласован с пользователем до старта:

1. **Hand-rolled OTLP/HTTP JSON exporter** (не opentelemetry-sdk, не
   sibling `agent_obs`) — тот же repo-конвеншн, что hand-rolled
   Prometheus exposition в `metrics.py`; ноль новых зависимостей, полный
   контроль над trace/span id (A-06 cross-link обязан совпадать с тем,
   что уходит в Langfuse и в JSONL).
2. **Auto-on when configured** (выбор пользователя): экспорт активен, когда
   `LANGFUSE_HOST` + оба ключа заданы AND `ORYA_LANGFUSE_EXPORT_ENABLED`
   (default true). Compose-api получает креды в `x-orya-app-env` → full
   stack экспортирует «из коробки»; host-dev и тесты без LANGFUSE_*
   остаются exporter-free.
3. **Полный скоуп** (выбор пользователя): `LANGFUSE_DIRECT_URL` fail-open
   fallback, `/metrics` счётчики, additive health-ключи, README/env/compose
   flip planned→wired.
4. **URL-семантика**: `{LANGFUSE_HOST}/api/public/otel/v1/traces` — тот же
   путь работает и напрямую против Langfuse, и через A-10 sampler-proxy
   (тот принимает POST на любой path и сам рерайтит downstream;
   `sampler_proxy.py:do_POST` не проверяет `self.path`). Если задан
   `OTEL_EXPORTER_OTLP_ENDPOINT` — он выигрывает и трактуется как generic
   collector base (`{endpoint}/v1/traces`). `LANGFUSE_DIRECT_URL`
   резолвится тем же Langfuse-путём.
5. **W3C id-ширины**: `_new_ids` теперь даёт span_id 16 hex (was 32) —
   OTLP/Langfuse требуют 8-байтовый span id; trace_id остаётся 32 hex.
   Стабильность сохраняется: тесты полагались только на «свежесть/различие»
   id, не на ширину. Валидация на стороне экспортера: не-hex id (например,
   тестовые `turn-trace-1`) хешируются sha256-слайсом.
6. **`gen_ai.*` enrichment** по мотивам sibling P23: `llm.call` span'ы
   получают `gen_ai.operation.name=chat`, `gen_ai.request.model`,
   `gen_ai.usage.*`, `gen_ai.usage.cost` — Langfuse v3 классифицирует их
   как GENERATION и рендерит tokens/cost/model нативно. `agent.permission`
   остаётся INTERNAL.
7. **Fail-soft-контракт A-02 сохранён**: `export_span` никогда не
   поднимает исключение и не блокирует agent-loop — bounded queue
   (drop-on-full) + daemon worker thread; ретраи с коротким backoff,
   cooldown после повторных падений, одноразовый direct-fallback,
   best-effort flush на shutdown через lifespan (`asyncio.to_thread`).
8. **`_finalize` хук вне buffer-try**: предложение в экспортер идёт отдельным
   try/except — поломка экспортера не может повредить append в буфер.
9. Приватные seam-функции (`resolve_traces_url`, `_is_configured`,
   `span_to_otlp`, `build_otlp_payload`) вынесены публично-тестируемыми; post
   инжектится в конструктор для детерминированных тестов без сети.
10. PII-masking НЕ в скоупе A-15 (это A-16/A-17 guardrail); спаны и так не
    несут message content (инвариант A-02).

## Files

- `app/core/observability/langfuse.py` (новый): маппинг `SpanRecord →
  OTLP Span` (id-санитизация, timestamps, status code, gen_ai.*),
  `build_otlp_payload`, `LangfuseOtlpExporter` (queue + worker thread +
  httpx POST + ретраи/cooldown/direct-fail-open), синглтон
  `get_exporter/init_exporter/shutdown_exporter/reset_exporter`,
  `export_span` (никогда не raise), `get_export_stats/reset_export_stats`.
- `app/core/observability/spans.py`: `_finalize` вызывает `export_span`;
  `_new_ids` → `secrets.token_hex(8)` (W3C span id); докстрок A-15.
- `app/core/config.py`: `langfuse_host/langfuse_public_key/
  langfuse_secret_key/langfuse_direct_url/langfuse_export_enabled` поля
  (`LANGFUSE_*` + `ORYA_*` алиасы).
- `app/main.py`: lifespan `init_exporter()` (start) +
  `await asyncio.to_thread(shutdown_exporter)` (flush+stop).
- `app/api/health.py`: additive ключи `langfuse_export_enabled/queued/
  exported_total/failed_total` в `/health/observability`.
- `app/api/metrics.py`: `orya_langfuse_export_spans_total` /
  `orya_langfuse_export_errors_total` счётчики.
- `docker-compose.yml`: `x-orya-app-env` получает `LANGFUSE_PUBLIC_KEY` /
  `LANGFUSE_SECRET_KEY` / `LANGFUSE_DIRECT_URL` (дев-дефолты совпадают с
  `LANGFUSE_INIT_PROJECT_*`).
- `README.md`: секция Langfuse flip planned→wired (заголовок «A-15 export;
  A-16/A-17 planned», новый anchor), env-таблица + kill-switch, health-ключи,
  Phase Progress + **A-15**.
- `.env.example`: `ORYA_LANGFUSE_EXPORT_ENABLED`, уточнения OTLP-путей.
- `tests/unit/test_langfuse_exporter.py` (новый, ~17 тестов): маппинг,
  URL/enablement, delivery (auth/retry/direct/permanent/cooldown/drop),
  `_finalize` интеграция, shutdown idempotent.
- `tests/unit/test_turn_trace.py`: W3C span-id width тест.
- `tests/unit/test_api_health.py`: default + configured ключи.
- `tests/unit/test_config.py`: `LANGFUSE_*` env-алиасы + дефолты;
  `_MANAGED_ENV_VARS` += LANGFUSE_*.
- `tests/unit/test_api_metrics.py`: presence новых счётчиков.
- `tests/unit/test_docker_compose.py`: `test_api_env_wires_langfuse_export`.
- `tests/unit/test_readme.py`: заголовок, wiring-факты, Phase Progress range(16).

## Acceptance

- ✅ Экспорт включается auto-on при `LANGFUSE_HOST`+keys, гасится kill-switch.
- ✅ OTLP JSON уходит на `{host}/api/public/otel/v1/traces` c Basic auth.
- ✅ trace_id/span_id экспортируются как есть (A-06 cross-link сохраняется).
- ✅ `llm.call` → GENERATION (gen_ai.*), `agent.permission` → INTERNAL.
- ✅ Fail-soft: drop-on-full, ретраи+cooldown, direct-fallback, shutdown flush.
- ✅ `/health/observability` + `/metrics` показывают состояние экспортера.
- ✅ `uv run pytest` зелёный; `make lint`/`make format` чистые.
