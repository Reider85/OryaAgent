# A-14 — Cost-tracking в spans (cost.* атрибуты + orya_llm_cost_usd_total)

> Ticket: `analytics/PROMPT_ALPHA.md:85` (A-14) | Estimate: 6 часов | Status: executed

## Spec summary

«Cost-tracking в spans | 6 часов | span attributes: cost.input_tokens,
cost.output_tokens, cost.usd» (PROMPT_ALPHA.md:85). Детального раздела в
BACKLOG6 §3 нет (там новые только A-16/A-17) — скоуп взят из таблицы
PROMPT_ALPHA + follow-up плана A-13 (`.opencode/plans/A-13-cost-aware-router.md:107-108`).
Pricing-источник — `app/core/llm/pricing.yaml`, созданный в M-01 как
«stub for cost-tracking (ALPHA A-14)» (PROMPT_MVP.md:141). Данные уже
 текли через `_attach_usage`/`record_usage` (A-02/A-13) — тикет их
соединяет и выводит наружу.

## Deviations & decisions

Скоуп согласован с пользователем до старта:

1. **+ Prometheus-метрика `orya_llm_cost_usd_total{model}`** на
   `/metrics` (вне буквальной спеки — по выбору пользователя):
   hand-rolled exposition (паттерн A-13, без prometheus-client),
   process-local суммы в `cost_tracker` под `threading.Lock`.
2. **Неизвестная модель → `cost.usd = 0.0`** (выбор пользователя): все
   три атрибута всегда при известных обоих счётчиках; бесплатные
   локальные модели (в pricing.yaml = 0.0) и промахи неразличимы.
   Серия метрики при этом создаётся с 0.0 — модель остаётся видимой.
3. **Cost-атрибуты и метрика не зависят от identity/kill-switch**:
   в отличие от `record_usage` (no-op без identity), спан-атрибуты
   пишутся при каждом наличии usage — это observability, не budget
   accounting. `ORYA_COST_ROUTER_ENABLED=false` ≠ без cost в спанах.
4. **Публичный `price_usd()`** в `app/core/cost_tracker.py` (rename
   `_price_usd`; прямых тестовых ссылок на приватное имя не было) —
   единый источник цены для спанов, метрики и бюджетного счётчика.
5. Цена считается дважды за вызов (спан-путь + `record_usage`) —
   lru_cached YAML, исключение; зато сигнатура `record_usage(provider,
   model, in, out)` стабильна (её зовут тесты напрямую).
6. **Fail-soft**: `_attach_cost` в try/except — поломка pricing-реестра
   не роняет turn (контракт шва A-02); `add_cost_total` никогда не
   поднимает исключение.
7. Стриминг (`_stream/_astream`) по-прежнему без usage (лаг A-02) —
   скоуп A-14 не расширяли.
8. Label метрики только `model` (model_id из pricing.yaml).

## Files

- `app/core/cost_tracker.py`: публичный `price_usd()` (rename
  `_price_usd`), `add_cost_total(model, usd)` / `get_cost_totals()` /
  `reset_cost_totals()` (process-local dict + `threading.Lock`,
  зеркало `get/reset_switch_stats`), `__all__` + докстрок A-14.
- `app/core/llm/tracing.py`: `_attach_cost(record, model, tokens)` →
  атрибуты `cost.input_tokens`/`cost.output_tokens`/`cost.usd` +
  `add_cost_total`; вызов в `invoke`/`ainvoke` внутри span-контекста
  до `_finalize`; абзац A-14 в докстроке.
- `app/api/metrics.py`: `_render_cost_totals()` → HELP/TYPE +
  `orya_llm_cost_usd_total{model="..."}` (label escaping через
  `_escape_label`); добавлен в `/metrics`.
- `tests/unit/test_llm_tracing.py` (+4): известная модель → точный
  `usd` (deepseek-chat: `11×0.00027/1000 + 22×0.0011/1000`), sync-инвок,
  unpriced → 0.0 + нулевая серия метрики, без `usage_metadata` → нет
  ни `tokens.*`, ни `cost.*`; `FakeChatModel.with_usage` флаг;
  `reset_cost_totals()` в autouse-фикстуре.
- `tests/unit/test_cost_tracker.py` (+3): `price_usd` математика,
  эквивалентность `record_usage`-спенду, `add_cost_total` accumulate/reset.
- `tests/unit/test_api_metrics.py` (+2): строка метрики после
  `add_cost_total` (0.75 + нулевая серия), пустое состояние → HELP/TYPE
  без строк; `reset_cost_totals()` в autouse-фикстуре.
- `tests/unit/test_readme.py`: `range(14)` → `range(15)`.
- Документация: README (intro, секция «LLM tracing & audit spans» —
  абзац про cost-атрибуты и метрику, Phase Progress A-14), AGENTS.md
  (статус-строка A-14 + уточнение в абзаце про `cost_tracker`).
- `.opencode/plans/A-14-cost-span-attributes.md` (this file).

## Verification

- `uv run pytest tests/unit/test_llm_tracing.py tests/unit/test_cost_tracker.py tests/unit/test_api_metrics.py tests/unit/test_readme.py -q` → 50 passed.
- Полный гейт: `uv run ruff format .` (1 file reformatted) → `uv run ruff check .` (all checks passed) → `uv run pytest -q` → **997 passed, 22 skipped** (базлайн 988 + 9 новых тестов; инфра-скипы как раньше).

## DoD

- ✅ Каждый `llm.call` span с известными токенами несёт
  `cost.input_tokens` / `cost.output_tokens` / `cost.usd`.
- ✅ `cost.usd` = `tokens × pricing.yaml`, 0.0 при промахе; та же
  математика, что у бюджетного счётчика (общий `price_usd`).
- ✅ Работает с выключенным роутером и без identity; эмит never raises.
- ✅ `orya_llm_cost_usd_total{model}` отдаёт `/metrics`; HELP/TYPE
  всегда, нулевые серии видимы.
- ✅ README/AGENTS синхронизированы; `range(15)` в README-тесте.

## Follow-ups

- A-15/A-16: экспорт cost-атрибутов в Langfuse + turn-роллап `cost.usd`
  на `agent.loop` (через `agent_obs.cost.compute_cost`).
- A-17: `cost.over_budget=true` (string `"true"` для sampler-proxy).
- Ловля usage из `_astream` (лаг A-02) — тогда и cost в стриминге.
- Опционально: label `provider` у метрики (сейчас только `model`).

## Commit message

`A-14: cost-tracking spans (cost.input_tokens/cost.output_tokens/cost.usd on llm.call + orya_llm_cost_usd_total metric)`
