# A-18 — TieredModelRouter (extends CostAwareRouter v6)

> Ticket: `analytics/PROMPT_ALPHA.md` §4 (= `BACKLOG7.md` §3 A-18) | Estimate: 4 часа | Status: executed

## Spec summary

«TieredModelRouter (extends CostAwareRouter v6) | 4 часа | TRIZ #35 + #1»
(PROMPT_ALPHA.md:94-149): `select(tier, user_id) -> ModelSelection` —
`small` → Haiku/Qwen, `large` → Sonnet/Opus (default), `tournament` →
TournamentExecutor (заглушка в ALPHA → degrade на `large`); cost-aware
fallback `budget_ratio >= 0.9` понижает tier до `small` (не повышает);
span-атрибуты `agent.execute.tier` / `agent.execute.degraded` эмитятся
**до** возврата модели; конфиг `tiered_router.models.*` в
`~/.orya/config.yaml`; имена моделей только через settings/env; все v6
тесты CostAwareRouter проходят. Зависимости A-13/A-02 выполнены;
`ARCHITECT7.md` §3 #30 (скетч с composition).

## Deviations & decisions

Скоуп согласован с пользователем до старта (3 развилки) + уточнения:

1. **Wiring: tier-seam в `resolve_turn_model`** — keyword-only `tier`:
   `None` → точный v6-путь (kill-switch, пороги 70/90/100% — 0 изменений);
   задан → `TieredModelRouter.select`. Request body НЕ менялся (planner —
   BETA); новый kill-switch не нужен: в ALPHA никто не передаёт tier →
   ветка инертна. 429 при ≥100% сохраняется на обоих путях
   (`_resolve_turn_model_or_raise` не менялся).
2. **`tier=tournament` → `large` со `degraded=false`** — degraded остаётся
   *бюджетным* сигналом (скетч ARCHITECT7: `degraded = ratio >= 0.9`),
   чтобы SSE-кадр `budget` не врал с ratio=0.0; заглушка логируется
   warning'ом, фактический tier виден в span-атрибуте. Неизвестный tier →
   fail-safe `large` + warning (ход не падает).
3. **`ModelSelection.tier: str = ""` + условный `as_dict()`** — ключ
   `"tier"` добавляется только когда непустой: v6-тест
   `test_model_selection_as_dict_shape` (точное равенство dict) проходит
   без правок; tiered-выбор несёт tier в budget-кадр/payload.
4. **Cost-fallback в tiered-пути: downgrade-only по WARN/BLOCK** —
   `ratio >= 0.9` → tier=small + degraded + warning; `>= 1.0` → + blocked.
   Порог 0.7 на tiered-пути НЕ применяется (tier независим от budget до
   0.9 — смысл A-18); v6-путь порога 0.7 касается только при `tier=None`.
   Tiered-путь также стейджит A-17 `cost.over_budget="true"` при ≥0.9
   (консистентность обоих путей). При деградации инкрементируется тот же
   `orya_cost_aware_switch_total{from_model,to_model}`.
5. **Конфиг**: YAML-секция `tiered_router.models.{small,large,tournament}`
   (списки, `[0]` = модель хода) через `tiered_router_block()` (паттерн
   `llm_block()`); env-переопределения — 3 Settings-поля с дефолтами в
   `config.py` (санкционированное место, как `cost_router_fallback_model`).
   Precedence: явный env/.env (`model_fields_set`) → YAML → дефолт.
   Дефолты — реальные aliases (`claude-haiku-3.5`, `claude-sonnet-3.5`):
   в сэмплах спеки `qwen-3b`/`opus-3.5` не существуют в `models.yaml`
   (фиктивный alias уронил бы сборку graph); тест резолвит каждый alias.
6. **Identity — `str`** (`user:{sub}`/`session:{id}`), не `UUID` из скетча
   — композиция с `get_budget_ratio(identity: str)`.
7. **Стейджинг span-атрибутов** — `set_pending_span_attributes()` с гейтом
   `agent_obs_enabled` (паттерн A-17), значения `"true"/"false"` строками;
   потребляет существующий `_agent_loop_span` — новых span-типов нет.
   Ленивый import `tiered_router` внутри `resolve_turn_model` (иначе цикл
   модулей: tiered_router → cost_router).
8. **Раскладка**: `app/core/llm/tiered_router.py` (composition, не
   наследование — скетч ARCHITECT7), тесты в `tests/unit/test_tiered_router.py`
   (конвенция репо, не `tests/test_tiered_router.py` из спеки).

### Drive-by repairs (предсуществующая краснота на HEAD — согласовано)

Гейт на HEAD был красным ещё до A-18 (A-17 и коммит `86bc3c3 "README"`
шли без format→lint→test). Починено в этом же коммите:

- `app/core/security.py` — call-site `log_security_incident`: A-17
  переименовал параметры (`pattern_id`→`pattern`, `content_preview`→
  `preview`), старые kwargs давали `TypeError` на каждом injection-хите
  (5 тестов: smoke + test_tools).
- `app/core/graph.py` — в `_emit_tool_call_spans` проверка
  `agent_obs_enabled` оказалась после `return` внутри `if not tool_calls`
  (мёртвый код → kill-switch не работал, тест A-16 падал) + импорт
  `Mapping` (F821).
- `tests/e2e/test_cost_router_roundtrip.py` — сид `budget-normal`:
  `_seed(id, 50.0)` ставил spend=50 при лимите 50 (ratio 1.0 → 429 вместо
  ожидаемого degrade), `add_spend` шёл без `session:`-префикса; плюс
  `json.loads` на уже распарсенном dict. Приведено к ratio 0.72
  (комментарий требовал «degraded, не warning» — 0.68 ниже порога 0.70).
- `tests/unit/test_api_health.py` — моки `.head` → `.get` (A-17 сменил
  HEAD→GET), синхронный `MagicMock` для `response.json()`, F821
  `settings`→`fallback_settings`, copy-paste URL в fallback-тесте.
- `tests/integration/test_sampler_proxy_integration.py` —
  `skipif(not "proxy_available")` (строка всегда truthy → никогда не
  скипал) заменён на условные runtime-скипы (конвенция репо): sibling
  checkout → probe endpoint → skip; health-тест переведён на compose
  healthcheck (`GET :9095/metrics`).
- `tests/unit/test_readme.py` — адаптация под рерайт README (коммит
  `86bc3c3`): якоря → новые секции (Roadmap/Configuration/Langfuse),
  phase-тест → бэктики `` `A-NN` `` в Roadmap-таблице, `range(19)` =
  A-00…A-18.
- lint: 22 ошибки (дубли/сортировка импортов из A-17, F841) — `ruff
  --fix` + ручные.

## Files

- `app/core/llm/tiered_router.py` (new): `TIERS`, `tier_models()`,
  `normalize_tier()`, `TieredModelRouter.select(tier, identity)`
  (composition над `CostAwareRouter`; `_count_switch` на деградации).
- `app/core/llm/cost_router.py`: поле `tier` + условный `as_dict()`;
  `resolve_turn_model(..., *, tier=None)` с tiered-веткой; докстринг A-18.
- `app/core/config.py`: `tiered_router_{small,large,tournament}_model`
  (AliasChoices `TIERED_ROUTER_*`/`ORYA_TIERED_ROUTER_*`) +
  `tiered_router_block()`.
- `app/core/llm/__init__.py`: re-export `TieredModelRouter`, `tier_models`.
- Drive-by: `app/core/security.py`, `app/core/graph.py`,
  `tests/e2e/test_cost_router_roundtrip.py`, `tests/unit/test_api_health.py`,
  `tests/integration/test_sampler_proxy_integration.py`,
  `tests/unit/test_cost_aware_router.py`, `tests/unit/test_observability_sdk.py`
  (только lint/F841).
- Тесты: `tests/unit/test_tiered_router.py` (new, 22: precedence,
  normalize, select по тирам, budget-гейты, span-attrs вкл/выкл,
  анти-фиктивные aliases, seam `resolve_turn_model`, `as_dict`, counter).
- Документация: README (intro `A-00…A-18`, feature-bullet, секция
  «Tiered model router» в Cost-aware Routing, env-таблица «Tiered router
  (A-18)» + YAML-пример, OTLP-путь в Langfuse-секции, Roadmap-строка
  A-18), `tests/unit/test_readme.py` (адаптация якорей), `.env.example`,
  `AGENTS.md` (header + Architecture-кlausula).
- `.opencode/plans/A-18-tiered-model-router.md` (this file).

## Verification

- `uv run pytest tests/unit/test_tiered_router.py -q` → 22 passed.
- `uv run pytest tests/unit/test_cost_aware_router.py tests/e2e/test_cost_router_roundtrip.py tests/unit/test_api_metrics.py tests/unit/test_readme.py -q` → все зелёные (v6-контракт цел).
- Полный гейт: `uv run ruff format .` → `uv run ruff check .` →
  `uv run pytest -q` → **1085 passed, 27 skipped** (инфра-скипы как раньше).

## DoD

- ✅ `select(tier="small")` → `claude-haiku-3.5`; `select("large")` →
  `claude-sonnet-3.5`; `select(None)` → large (ALPHA default).
- ✅ `budget_ratio >= 0.9` → tier=small + `degraded=true` (downgrade-only);
  `>= 1.0` → `blocked=true` → 429 через существующий роут.
- ✅ Span `agent.execute.tier` = `small|large`,
  `agent.execute.degraded` = `true|false` — стейджатся до возврата модели.
- ✅ `tier=tournament` → degrade на `large` (заглушка, degraded=false);
  неизвестный tier → large.
- ✅ Все v6-тесты CostAwareRouter без правок; `tier=None` ≙ v6.
- ✅ Config `tiered_router.models.*` (env > YAML > default), только
  реальные aliases; имена моделей в коде не захардкожены.
- ✅ README/env/AGENTS синхронизированы (env-sync тест + Roadmap A-18).
- ✅ Гейт format → lint → test зелёный (включая drive-by ремонты).

## Follow-ups

- A-19 PromptCacheLayout, A-20 ConnectionPool (оставшиеся ALPHA).
- BETA: planner эмитит `tier` → тело запроса/граф получает tier-сему
  (сейчас `tier=` только прямые вызовы); `tournament` → TournamentExecutor.
- Админка для `set_limit` (из A-13, не закрыта).
- Зарегистрировать маркер `integration` или перевести оставшиеся
  integration-тесты на runtime-скипы полностью.

## Commit message

`A-18: TieredModelRouter (tier-based model selection + cost-aware fallback, agent.execute.tier/degraded span attrs, tiered_router config)`
