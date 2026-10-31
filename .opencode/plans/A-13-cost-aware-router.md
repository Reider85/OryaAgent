# A-13 — CostAwareRouter (budget tracking per session/user)

> Ticket: `analytics/PROMPT_ALPHA.md` §3.1 (A-13) | Estimate: 1 день | Status: executed

## Spec summary

«CostAwareRouter (budget tracking per session) | 1 день | degrade на Haiku
при 70-90% budget» (PROMPT_ALPHA.md:84) + полный тикет в BACKLOG5.md:581-637
(скетч `CostAwareRouter`, Redis-ключи `orya:cost:{user}:{date}` /
`orya:limit:{user}`, пороги 0.7/0.9/1.0, 429 на 100%, метрика
`orya_cost_aware_switch_total{from_model,to_model}`, «переключение только
между turns») + ARCHITECT5 §6.1. Зависимости A-02/A-03 выполнены; частичной
работы в git не было.

## Deviations & decisions

Скоуп согласован с пользователем до старта:

1. **Identity — гибрид** (PROMPT_ALPHA «per session» + BACKLOG5 per-user):
   `user:{jwt sub}` когда AuthMiddleware (A-00) пробил user_id в scope state,
   иначе `session:{session_id}`. В дефолтном dev-режиме (auth off) — каждая
   сессия бюджетируется независимо.
2. **Kill-switch `ORYA_COST_ROUTER_ENABLED=false`** — конвенция ALPHA
   (auth/rate-limit так же); выключенный роутер = чистый pass-through.
3. **Budget всегда побеждает explicit model** — cost-guardrail; escape hatch
   только kill-switch.
4. **SSE-поверхность: новый кадр `budget`** `{degraded, warning, ratio,
   model, primary, fallback}` первым кадром стрима + объект `budget` в
   `done`/JSON-результате (только при активном degrade) — без коллизии с
   существующим `degraded` (DB/checkpointer) в `done`.
5. **Раскладка:** спека писала `app/core/llm.py` (v5) — репо сейчас пакет
   `app/core/llm/`, поэтому роутер в `app/core/llm/cost_router.py`
   (prep-место для A-18 TieredModelRouter), стор — `app/core/cost_tracker.py`.
6. **Hard-block — HTTP 429 в роуте** перед сборкой graph (спека: «через
   A-02», но A-02 — span-wrapping, не reject-механизм).
7. **`cost.over_budget` span-attribute — НЕ делаем** (это A-17); A-13
   ограничивается счётчиком переключений + budget-кадром.
8. **Стоимость:** `tokens × pricing.yaml` (ключ model_id; TracedChatModel
   знает resolved model_id) в `record_usage`, вызываемом из
   `TracedChatModel.invoke/ainvoke` после `_attach_usage`; identity —
   contextvar, поэтому graph и seam не менялись. Неизвестная модель → $0.
   Прямой `_astream` usage сегодня не捕获 (лаг A-02, вне скоупа).
9. **`MemoryCostStore` на `threading.Lock`** — тесты сеют стор в
   `asyncio.run`, запросы идут в другом loop TestClient'а; `asyncio.Lock`
   binding сломался бы跨-loop.

## Files

- `app/core/cost_tracker.py` (new): `MemoryCostStore`/`RedisCostStore`
  (`add_spend`/`get_spend`/`get_limit`/`set_limit`), `record_usage`,
  contextvar `with_cost_identity`, `init/close/get/set_cost_store`
  (паттерн A-01 rate-limiter: auto/memory/redis, probe 2s, fail-soft).
- `app/core/llm/cost_router.py` (new): `CostAwareRouter`,
  `ModelSelection`, `resolve_turn_model` (route entry), switch-counter
  `get/reset_switch_stats`, пороги DEGRADE/WARN/BLOCK = 0.7/0.9/1.0.
- `app/core/config.py`: `cost_router_enabled`, `cost_router_fallback_model`,
  `cost_budget_default_usd`, `cost_backend`.
- `app/core/llm/tracing.py`: `_usage_tokens`/`_schedule_record_usage` +
  хук в `invoke`/`ainvoke`.
- `app/api/sessions.py`: `_cost_identity`, `_resolve_turn_model_or_raise`
  (429), `_budget_payload`, `budget`-кадр в `_sse_turn`, `budget` в
  `done`/`_result_dict`, `_stream_with_cost_identity`, `request: Request`
  в `post_message`/`post_resume`.
- `app/api/metrics.py`: `_render_switch_counters` →
  `orya_cost_aware_switch_total{from_model,to_model}`.
- `app/main.py`: `init_cost_store`/`close_cost_store` в lifespan.
- `app/ui/chainlit_app.py`: `_budget_step` + ветка `budget` в
  `_render_events`.
- Тесты: `tests/unit/test_cost_tracker.py` (15), `tests/unit/
  test_cost_aware_router.py` (16), `tests/e2e/test_cost_router_roundtrip.py`
  (4: budget-кадр, warning-payload, 429, kill-switch off), `tests/unit/
  test_api_metrics.py` (+2), `tests/unit/test_readme.py` (`range(14)`).
- Документация: README (intro, «Cost router (A-13)» env-таблица, секция
  «Cost-aware routing (A-13)», Phase Progress A-13), `.env.example`,
  `AGENTS.md`.
- `.opencode/plans/A-13-cost-aware-router.md` (this file).

## Verification

- `uv run pytest tests/unit/test_cost_tracker.py
  tests/unit/test_cost_aware_router.py tests/unit/test_api_metrics.py
  tests/e2e/test_cost_router_roundtrip.py tests/unit/test_readme.py -q` →
  47 passed.
- Полный гейт: `uv run ruff format .` → `uv run ruff check .` →
  `uv run pytest -q` → **988 passed, 22 skipped** (инфра-скипы как раньше).

## DoD

- ✅ <70% budget → primary; 70-90% → fallback (`claude-haiku-3.5`),
  `degraded: true` в SSE-кадре `budget`/payload; 90-100% → + `warning`;
  ≥100% → 429 до сборки graph.
- ✅ Переключение только между turns (selection до `build_session_graph`;
  graph пересобирается per-request).
- ✅ Метрика `orya_cost_aware_switch_total{from_model,to_model}` на
  `/metrics` (инкремент только при фактическом переключении).
- ✅ Счётчик обновляется после каждого LLM-вызова (invoke/ainvoke seam'а,
  включая recover-node), fail-soft (Redis down → warning, turn живёт).
- ✅ Лимиты не hardcoded: `orya:limit:{identity}` (admin/test seam
  `set_limit`) → fallback `ORYA_COST_BUDGET_DEFAULT_USD=50`.
- ✅ Kill-switch off = ноль поведенческих изменений (все прежние тесты
  зелёные без правок).
- ✅ README/env/AGENTS синхронизированы (env-sync тест + Phase Progress
  A-13).

## Follow-ups

- A-14 (cost-tracking в spans): `cost.input_tokens`/`cost.output_tokens`/
  `cost.usd` атрибуты — данные уже текут через `_attach_usage`.
- A-17: `cost.over_budget=true` span-attribute при ratio ≥ 0.9
  (BACKLOG6: emit до возврата model).
- A-18: `TieredModelRouter extends CostAwareRouter` — держать
  `get_budget_ratio`/`ModelSelection` стабильными (composition-friendly).
- Админка для `set_limit` (сейчас только store-метод, эндпоинта нет).
- Ловля usage из `_astream` (когда seam начнёт стримить со span'ами).

## Commit message

`A-13: CostAwareRouter (budget tracking per session/user, degrade at 70%, warning at 90%, 429 at 100%)`
