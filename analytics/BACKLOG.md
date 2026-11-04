# BACKLOG7 — Бэклог задач OryaAgent v7 (speed + memory + self-verification synthesis)

> **Версия документа:** 7.0
> **Дата:** 20 октября 2026
> **Источники:** `ARCHITECT7.md` v7.0, `ROADMAP7.md` v7.0, `BACKLOG6.md` v6.0 (baseline)
> **Стек:** Python 3.11+, LangChain 0.3+, LangGraph 0.2+, FastAPI, PostgreSQL 16, Redis 7, Chainlit, OriaHS, OryaObservability SDK, LSP-серверы (pyright, typescript-language-server, rust-analyzer, gopls, jdtls, lua-language-server)
> **Формат:** spec-driven тикеты (Context / Goal / Constraints / Acceptance Criteria / Forbidden patterns / Suggested files)
> **Гранулярность:** 1 тикет = 1 задача (~2 часа – 5 дней работы)
> **Статус:** бэклог готов к реализации; v7 — надстройка над v6, не замена

---

## Содержание

0. Что изменилось относительно v6 (executive summary)
1. Как пользоваться этим документом
2. Фаза MVP (M-00 … M-27) — 28 тикетов (= v6 MVP, без изменений)
3. Фаза ALPHA (A-00 … A-20) — 21 тикет (18 v6 + 3 новых)
4. Фаза BETA (B-00 … B-29) — 30 тикетов (24 v6 + 6 новых)
5. Фаза PROD (P-00 … P-26) — 27 тикетов (20 v6 + 7 новых)
6. Фаза EXTENSION-PROD (E-00 … E-14) — 15 тикетов (12 v6 + 3 новых опц.)
7. Фаза FUTURE (F-00 … F-11) — 12 тикетов (10 v6 + 2 новых)
8. Meta-тикеты (R-01 … R-07) — 7 тикетов (5 v6 + 2 новых)
9. Сводная матрица тикетов × фаз
10. Карта зависимостей между тикетами
11. Соответствие тикетов ТРИЗ-принципам и 20/80

---

## 0. Что изменилось относительно v6 (executive summary)

`BACKLOG7.md` сохраняет структуру `BACKLOG6.md`, но добавляет **21 новый тикет** для реализации 14 улучшений v7 (см. `ARCHITECT7 §0`):

### Новые тикеты в v7

| ID | Title | Фаза | Улучшение v7 | Принцип | Estimate |
|---|---|---|---|---|---|
| **A-18** | TieredModelRouter (extends CostAwareRouter v6) | ALPHA | #30 | #35 Parameter changes | 4 часа |
| **A-19** | PromptCacheLayout (Anthropic ephemeral + OpenAI prompt caching) | ALPHA | #32 | #11 Beforehand + #19 | 6 часов |
| **A-20** | ConnectionPool (keepalive + hot adapters) | ALPHA | #14 | #11 Beforehand + #15 Dynamicity | 6 часов |
| **B-24** | DFC: 5 слоёв (HEAT/HOT/WARM/COLD/ICE) + BackgroundCompactor | BETA | #18 | #17 Another dimension + #15 Dynamicity | 5 дней |
| **B-25** | Tri-Model Pipeline (plan → execute → test) | BETA | #19 | #40 Composite + #9 Preliminary anti-action | 4 дня |
| **B-26** | LSP-bus + 6 LSP-servers + 7 LSP-tools | BETA | #20 | #28 Mechanics substitution + #24 Intermediary | 7 дней |
| **B-27** | UKB Router (partial: lsp + memory) | BETA | #22 | #5 Merging + #12 Equipotentiality | 3 дня |
| **B-28** | RetrievalOrchestrator (7 strategies) | BETA | #27 | #24 Intermediary + #10 Preliminary | 4 дня |
| **B-29** | CapabilityRegistry (dynamic tool-filter per turn) | BETA | #28 | #15 Dynamicity + #25 Self-service | 2 дня |
| **P-20** | BatchRunner + BenchmarkComparator + CLI | PROD | #21 | #19 Periodic + #25 Self-service | 3 дня |
| **P-21** | SymbolicClassifier (LLM bypass для rename/format) | PROD | #23 | #16 Partial effect + #21 Rushing | 2 дня |
| **P-22** | PredictivePlanner + Heat Cache integration | PROD | #24 | #10 Preliminary + #11 Beforehand | 5 дней |
| **P-23** | TournamentExecutor + judge-mcp | PROD | #25 | #40 Composite + #22 Convert harm | 4 дня |
| **P-24** | Concurrent Tester (extension of B-25 tri-model) | PROD | #26 | #21 Rushing + #15 Dynamicity | 3 дня |
| **P-25** | RerankPolicy with skip + fallback chain | PROD | #29 | #11 Beforehand + #35 Parameter changes | 2 дня |
| **P-26** | Best-of-N execution (simplified tournament) | PROD | #31 | #21 Rushing + #16 Partial | 1 день |
| **E-12** | (опц.) WASM-LSP ports (rust-analyzer, typescript) | EXT-PROD | (опц.) | #28 Mechanics substitution | 1 неделя |
| **E-13** | (опц.) Multi-instance DFC sync (Heat Cache + HOT) | EXT-PROD | (опц.) | #15 Dynamicity | 1 неделя |
| **E-14** | (опц.) Multi-instance LSP-server cluster | EXT-PROD | (опц.) | #1 Segmentation | 1 неделя |
| **F-10** | Predictive User Model K=3 + Task Embedding Index | FUTURE | (см. FUTURE7) | #10 Preliminary | — |
| **F-11** | Continuous Planner daemon (requires neuromorphic inference) | FUTURE | (см. FUTURE7) | #19 Periodic | — |
| **R-06** | Architecture synthesis documentation (v0.1+v0.2+v0.3 → v7) | meta | — | — | 4 часа |
| **R-07** | Comparison v7 vs opencode vs kilocode documentation | meta | — | — | 6 часов |

**Итого:** v7 содержит 138 тикетов (vs 117 в v6). Увеличение на 18% — за счёт speed + self-verification примитивов v7.

### Изменённые тикеты v7 vs v6

| ID v6 | Что изменилось в v7 |
|---|---|
| M-05 | SystemPromptBuilder теперь инжектирует L0 memory block (v6) + использует PromptCacheLayout (#32) для cacheable prefix |
| M-13 | PermissionPolicy: добавлены permissions для `/batch/*`, `/lsp/*`, `/tournament/*`, `/dfc/*` endpoints |
| A-04 | Observability: добавлены span-types для v7 (agent.plan, agent.execute, agent.test, agent.tournament, dfc.*, lsp.call, ukb.lookup, retrieval.orchestrate, capability.filter, predictive_planner.*, batch.run) |
| A-13 | CostAwareRouter: v7 расширен до TieredModelRouter (A-18); CostAwareRouter остаётся как cost-aware fallback layer |
| M-22 | Prompt injection defense: добавлен emit `security.incident=true` (из v6 A-17) + в v7 emit также для `lsp.rename refuted` cases |
| B-11 | Memory injection в system-prompt: теперь через DFC.assemble_hot (#18) + cacheable prefix (#32) |

---

## 1. Как пользоваться этим документом

(см. `BACKLOG6.md` §1 — без изменений)

Структура тикета:
```
### {ID} — {Title}
> Component: {ARCHITECT7 §ref} | Dependencies: {IDs} | Estimate: {days/hours} | TRIZ: {principle(s)}
#### Context
{почему эта задача нужна}
#### Goal
{что сделать}
#### Constraints
{жёсткие ограничения}
#### Acceptance Criteria
- {проверяемое условие 1}
- {проверяемое условие 2}
#### Forbidden patterns
{что нельзя делать}
#### Suggested files
- {file1}
- {file2}
```

Все тикеты v6 (M-00..M-27, A-00..A-17, B-00..B-23, P-00..P-19, E-00..E-11, F-00..F-09, R-01..R-05) остаются в силе без изменений, если явно не упомянуты в §0 «Изменённые тикеты v7 vs v6». Ниже описаны **только новые и изменённые** тикеты.

---

## 2. Фаза MVP (M-00 … M-27 — без изменений от v6)

(см. `BACKLOG6.md` §2 — полностью без изменений)

v7 не добавляет тикетов в MVP. Принцип: «не нарушать время до первого работающего агента» (3.5 недели, как v6 MVP).

---

## 3. Фаза ALPHA (A-18 … A-20 — новые в v7)

### A-18 — TieredModelRouter (extends CostAwareRouter v6) 🆕

> **Component:** ARCHITECT7 §3 #30, §6.9 | **Dependencies:** A-13 (CostAwareRouter v6), A-02 (LLM seam) | **Estimate:** 4 часа | **TRIZ:** #35 Parameter changes + #1 Segmentation

#### Context

В v6 CostAwareRouter переключает на Haiku при 70–90% budget (cost-control, не complexity-aware). Простой ход (format) при низком budget всё равно идёт на Sonnet — трата денег. В v7 planner (когда появится в BETA через #19) эмитит `tier: small | large | tournament`; TieredModelRouter выбирает модель по tier, независимо от budget.

#### Goal

1. Расширить `app/core/llm.py::CostAwareRouter` до `TieredModelRouter` (через наследование или composition).
2. Метод `select(tier: str, user_id: UUID) -> ModelSelection`:
   - `tier=small` → Haiku/Qwen-3B.
   - `tier=large` → Sonnet/Opus (default).
   - `tier=tournament` → defer to TournamentExecutor (PROD, заглушка в ALPHA).
3. Cost-aware fallback: если `budget_ratio >= 0.9` → понижать tier до `small`.
4. Span attribute: `agent.execute.tier`, `agent.execute.degraded`.
5. В ALPHA (до planner'а в BETA) — hardcoded `tier=large` default; tier эмитится в BETA.

#### Constraints

- `tier` может быть: `small | large | tournament`.
- Cost-aware fallback понижает tier, не повышает.
- Span attributes emit **до** возврата model.
- Если `tier=tournament` в ALPHA (до PROD) — degrade на `large` (TournamentExecutor ещё не реализован).
- Default tier: `large` (если planner не эмитит, что в ALPHA так и есть).

#### Acceptance Criteria

- ✅ `TieredModelRouter.select(tier="small", user_id=...)` возвращает Haiku/Qwen-3B.
- ✅ `TieredModelRouter.select(tier="large", user_id=...)` возвращает Sonnet/Opus.
- ✅ При `budget_ratio >= 0.9` — `degraded=true`, tier понижен до `small`.
- ✅ Span `agent.execute.tier` = `small|large`, `agent.execute.degraded` = `true|false`.
- ✅ Если `tier=tournament` — degrade на `large` (в ALPHA, без PROD tournament).
- ✅ Все существующие v6 tests для CostAwareRouter проходят.
- ✅ Config в `~/.orya/config.yaml`:
  ```yaml
  tiered_router:
    models:
      small: ["haiku-3.5", "qwen-3b"]
      large: ["sonnet-3.5", "opus-3.5"]
      tournament: ["sonnet-3.5", "gpt-5", "deepseek-v3"]
  ```

#### Forbidden patterns

- ❌ Изменять CostAwareRouter v6 без сохранения backward compatibility — TieredModelRouter extends, не replaces.
- ❌ Эмитить `tier` после возврата model — должен быть до.
- ❌ Hardcoded model names в коде — через settings/env.
- ❌ Использовать `tier=tournament` в ALPHA (это PROD).

#### Suggested files

- `app/core/llm/tiered_router.py`
- `app/core/llm.py` (update CostAwareRouter — extend interface)
- `tests/test_tiered_router.py`

---

### A-19 — PromptCacheLayout (Anthropic ephemeral + OpenAI prompt caching) 🆕

> **Component:** ARCHITECT7 §3 #32, §6.11 | **Dependencies:** A-02 (LLM seam), A-18 (TieredModelRouter) | **Estimate:** 6 часов | **TRIZ:** #11 Beforehand cushioning + #19 Periodic action

#### Context

В v6 CacheWrapper кэширует tool-results в Redis. Но cacheable prefix (system + tools + project_summary + L0 memory) пересчитывается каждым провайдером на каждом ходе — это +800 ms time-to-first-token. Anthropic и OpenAI имеют prompt-caching через `cache_control: ephemeral` и prompt caching (5–10 min) соответственно. В v7 PromptCacheLayout использует провайдерские prompt-caches для cross-turn KV-cache reuse.

#### Goal

1. Реализовать `app/core/llm/prompt_cache.py::PromptCacheLayout`:
   - `assemble(system, tools, project_summary, l0_memory, dynamic) -> list[BaseMessage]`:
     - Anthropic: SystemMessage с `cache_control: ephemeral` markers для cacheable prefix.
     - OpenAI: SystemMessage с cache-friendly structure (провайдер кэширует автоматически).
     - Gemini: context caching (через separate API call для регистрации prefix).
2. Cacheable prefix: system + tools + project_summary + L0 memory (4 scored-файла из 6 L0-файлов).
3. Dynamic suffix: plan + active symbols + active diff (из DFC, но DFC появится в BETA — для ALPHA dynamic suffix = past user/assistant messages).
4. Redis: `orya:prompt_cache:prefix_hash:{thread_id}` — hash of cacheable prefix (для invalidation при изменении tool-schemas).
5. Span attribute: `llm.call.cache_hit` (true|false), `llm.call.cache_age_seconds`.

#### Constraints

- Anthropic `cache_control: ephemeral` — 5-минутный TTL с sliding window (при cache hit).
- OpenAI prompt caching — automatic для prefix >1024 tokens, 5-10 min cache.
- Gemini context caching — через отдельный API call (register prefix → cache-id → use cache-id в subsequent calls).
- Prefix hash в Redis — sha256 of serialized prefix; invalidate при изменении tool-schemas или L0 memory.
- Если prefix hash changed → следующее сообщение будет cache-miss (это ОК, провайдер пересоздаст cache).
- Provider support matrix:
  - Anthropic: ✅ native support.
  - OpenAI: ✅ automatic (no special markers).
  - Ollama (local): ⚠️ partial support (через prompt-cache fixture).
  - Google Vertex: ✅ explicit context caching API.

#### Acceptance Criteria

- ✅ `PromptCacheLayout.assemble(...)` возвращает LangChain messages с `cache_control: ephemeral` для Anthropic.
- ✅ Anthropic API получает `cache_control` markers (verified через `llm.call.cache_hit=true` span).
- ✅ OpenAI prompt caching работает автоматически (verified через `llm.call.cache_hit=true` для prefix >1024 tokens).
- ✅ Prompt-cache hit rate > 40% на тестовых сессиях (provider-side metric).
- ✅ Time-to-first-token ≤ 600 ms (vs v6 ≤ 1200 ms без prompt-cache).
- ✅ Prefix hash в Redis: при изменении tool-schemas → hash changes → cache invalidated.
- ✅ `AGENT_OBS_PROMPT_CACHE_ENABLED=false` — disable (для debugging).
- ✅ Если provider не поддерживает prompt-caching — fallback to plain SystemMessage (no `cache_control`).

#### Forbidden patterns

- ❌ Mark dynamic suffix с `cache_control: ephemeral` — это wrong (dynamic меняется каждый ход).
- ❌ Хранить plaintext PII в cacheable prefix — PII-masking через guardrail (v6 A-16).
- ❌ Hardcoded provider-specific logic в general path — через provider-detection.
- ❌ Блокировать agent-loop на Gemini context-caching register API call — async с retry.

#### Suggested files

- `app/core/llm/prompt_cache.py`
- `app/core/llm/providers/anthropic.py` (update: emit cache_control markers)
- `app/core/llm/providers/openai.py` (update: cache-friendly structure)
- `app/core/llm/providers/gemini.py` (update: context-caching register)
- `tests/test_prompt_cache_layout.py`

---

### A-20 — ConnectionPool (keepalive + hot adapters) 🆕

> **Component:** ARCHITECT7 §3 #14, §6.9 | **Dependencies:** A-02 (LLM seam) | **Estimate:** 6 часов | **TRIZ:** #11 Beforehand cushioning + #15 Dynamicity

#### Context

В v6 каждый LLM-call создаёт новый TCP+TLS connection к провайдеру. Cold-start latency: 200-500 ms на каждом ходе. В v7 ConnectionPool держит 4 keepalive connections per provider, не платит cold-start каждый раз.

#### Goal

1. Реализовать `app/core/llm/connection_pool.py::ConnectionPool`:
   - Per-provider keepalive connections (`httpx.AsyncClient` + `transport`).
   - Hot pool size: 4 (default), configurable through `LLM_POOL_SIZE`.
   - LRU eviction при превышении max size.
   - Periodic health-check (раз в 30 s).
   - Fail-open: если connection unhealthy → spawn new.
2. Provider coverage: Anthropic, OpenAI, Ollama (local), Google Vertex.
3. Integration с `ChatAnthropic`, `ChatOpenAI`, `ChatOllama`, `ChatVertexAI` (LangChain) — pass `http_client` parameter.
4. Span attribute: `tcp.connect_duration_ms`, `tcp.pool_hit` (true|false).

#### Constraints

- `httpx.AsyncClient` с `transport=httpx.HTTPTransport(retries=2, keepalive_expiry=60)`.
- Hot pool size default 4, max 16.
- Health-check: HEAD request на provider's `/health` (если есть), иначе TCP connect probe.
- Если connection unhealthy — close and create new (don't block agent-loop).
- Pool metrics: `orya_llm_pool_size{provider}`, `orya_llm_pool_hit_rate{provider}`, `orya_llm_pool_unhealthy_total{provider}`.
- Thread-safe: `asyncio.Lock` for pool mutations.

#### Acceptance Criteria

- ✅ `ConnectionPool` держит 4 keepalive connections per provider (Anthropic, OpenAI, Ollama, Vertex).
- ✅ При cold-start (после restart) — первый ход не платит TCP+TLS latency (verified через `tcp.connect_duration_ms < 50` для warm connection).
- ✅ Health-check убивает unhealthy connections и создаёт новые.
- ✅ LRU eviction: при max_size=4 и 5-м provider call — oldest connection evicted.
- ✅ Span `tcp.connect_duration_ms` ≤ 50 ms для warm connections, 200-500 ms для cold.
- ✅ `orya_llm_pool_hit_rate` > 95% (большинство reuse existing connection).
- ✅ `orya_llm_pool_unhealthy_total` < 1% от total connections.

#### Forbidden patterns

- ❌ Hardcoded provider URLs — через settings/env.
- ❌ Синхронный health-check в agent-loop — async only.
- ❌ Block agent-loop при pool full — wait-free, spawn new (over limit, then evict).
- ❌ Mix connections between threads without Lock.

#### Suggested files

- `app/core/llm/connection_pool.py`
- `app/core/llm.py` (update: pass http_client to ChatX classes)
- `tests/test_connection_pool.py`

---

## 4. Фаза BETA (B-24 … B-29 — новые в v7)

### B-24 — DFC: 5 слоёв (HEAT/HOT/WARM/COLD/ICE) + BackgroundCompactor 🆕

> **Component:** ARCHITECT7 §3 #18, §6.1 | **Dependencies:** M-25 (MDStore v6), A-19 (PromptCacheLayout), A-18 (TieredModelRouter) | **Estimate:** 5 дней | **TRIZ:** #17 Another dimension + #15 Dynamicity + #19 Periodic action

#### Context

v6 ContextManager урезает историю по token-count (как в v4). На длинной сессии окно разрастается линейно — LLM видит весь шум, latency и cost растут. В v7 DFC (Dynamic Fast Context) — 5 слоёв (HEAT/HOT/WARM/COLD/ICE). В окно модели попадает только HOT (4-8K токенов). Остальные — retrievable, но не загружаются по умолчанию. DFC **не заменяет** v6 memory-layer; DFC = in-window discipline, v6 memory = long-term storage.

#### Goal

1. Реализовать `app/core/dfc/__init__.py` (пакет DFC).
2. Реализовать `app/core/dfc/dfc.py::DFC`:
   - 5 слоёв: `heat: HeatCache`, `hot: OrderedDict`, `warm: OrderedDict`, `cold: list[CompactSummary]`, `ice: UKBRouter` (UKB будет в B-27).
   - `assemble_hot(plan: Plan) -> str` — cacheable prefix + dynamic suffix для system-prompt.
   - `promote_to_hot(key, value) -> None` — promotion with demotion of oldest to warm.
   - `snapshot() -> DFC` — for Tournament (PROD) immutable copy.
3. Реализовать `app/core/dfc/heat_cache.py::HeatCache` — predicted HOT (placeholder в BETA, full impl в PROD через P-22).
4. Реализовать `app/core/dfc/context_assembler.py::ContextAssembler` — assemble hot, integrate с v6 SystemPromptBuilder.
5. Реализовать `app/core/dfc/background_compactor.py::BackgroundCompactor` — WARM→COLD на границах ходов (async).
6. Redis persistence: `orya:dfc:hot:{thread_id}`, `orya:dfc:warm:{thread_id}`.
7. Metrics: `orya_dfc_hot_size_tokens`, `orya_dfc_compaction_total`, `orya_dfc_compaction_duration_ms`.
8. Spans: `dfc.assemble_hot`, `dfc.compact`.

#### Constraints

- HOT size: 4-8K tokens (default 8K, configurable).
- WARM size: 16-32K tokens (default 32K).
- COLD size: unlimited (compacts from previous turns).
- ICE size: unlimited (UKB, external).
- HEAT Cache: 4-8K tokens (placeholder в BETA, full impl в PROD).
- HOT пересобирается каждый ход (planner-фаза задаёт prefetch hints).
- WARM→COLD compaction: async, не блокирует turn; immutable snapshot.
- DFC state persisted в Redis (для resume после restart).
- DFC state **не** persisted в PostgreSQL (это in-memory state, восстанавливается из session-log + LSP + UKB).
- Integration с v6 SystemPromptBuilder: `build_system_prompt(state, tools, dfc)` — DFC добавляет dynamic suffix.

#### Acceptance Criteria

- ✅ `DFC(ukb=mock, lsp_bus=mock, memory=mock)` инициализируется без ошибок.
- ✅ `dfc.assemble_hot(plan)` возвращает cacheable prefix + dynamic suffix, ≤16K токенов total.
- ✅ `dfc.promote_to_hot("key1", "value1")` — добавляет в HOT; при превышении MAX_HOT (8K) — oldest demoted в WARM.
- ✅ `dfc.snapshot()` возвращает immutable copy (для Tournament в PROD).
- ✅ BackgroundCompactor: после 10 ходов — async compaction WARM→COLD (verified через `orya_dfc_compaction_total` counter).
- ✅ DFC state persisted в Redis: после restart — HOT и WARM восстановлены.
- ✅ `dfc.assemble_hot` span эмитится с правильными атрибутами (`dfc.heat_hit`, `dfc.hot_size_tokens`, `dfc.warm_demoted`, `dfc.cold_compacted`).
- ✅ Integration с v6 SystemPromptBuilder: system-prompt now ≤ 8K cacheable prefix + 8K dynamic suffix.
- ✅ Integration с PromptCacheLayout (A-19): cacheable prefix marked с `cache_control: ephemeral`.

#### Forbidden patterns

- ❌ Replace v6 memory-layer (L0/L1/L2) — DFC = in-window discipline, v6 memory = long-term storage.
- ❌ Persist COLD layer (compacts) в Redis — это RAM only.
- ❌ Block agent-loop на compaction — async only.
- ❌ Mix DFC layers (e.g., write to ICE from HOT) — strict layer discipline.
- ❌ Hardcoded token limits — through settings.

#### Suggested files

- `app/core/dfc/__init__.py`
- `app/core/dfc/dfc.py`
- `app/core/dfc/heat_cache.py`
- `app/core/dfc/context_assembler.py`
- `app/core/dfc/background_compactor.py`
- `app/core/dfc/models.py` (CompactSummary dataclass)
- `tests/test_dfc.py`
- `tests/test_dfc_heat_cache.py`
- `tests/test_dfc_background_compactor.py`

---

### B-25 — Tri-Model Pipeline (plan → execute → test) 🆕

> **Component:** ARCHITECT7 §3 #19, §6.2 | **Dependencies:** B-24 (DFC), A-18 (TieredModelRouter), A-19 (PromptCacheLayout) | **Estimate:** 4 дня | **TRIZ:** #40 Composite materials + #9 Preliminary anti-action + #21 Rushing

#### Context

v6 имеет один LLM-call на ход (Sonnet/Haiku через CostAwareRouter). Чтобы доверять ответу, нужен второй LLM-call (verify), но это удваивает стоимость. В v7 Tri-Model Pipeline делит ход на три фазы: planner (small, 200-400 ms), executor (large, 2-6 s), tester (small, 200-400 ms). Tester проверяет только критерии успеха, заданные planner'ой — узкий контекст → маленькая модель → +200 ms, +$0.001 на ход.

#### Goal

1. Реализовать `app/core/workflow/tri_model.py::TriModelPipeline`:
   - LangGraph subgraph: `plan → execute → test_finalize`.
   - Concurrent tester node: стартует когда executor partial diff detectable (в BETA — basic; full concurrent в P-24).
   - Replan node: bounded N=2 retries.
   - 3 модели: planner (Haiku/Qwen-3B), executor (Sonnet via TieredModelRouter A-18), tester (Haiku/Qwen-3B).
   - Routing: planner → executor → tester; tester.verdict=pass → END; tester.verdict=fail → replan (bounded).
2. `Plan` dataclass: `steps`, `criteria`, `prefetch_hints`, `tier` (small|large|tournament).
3. Integration с DFC (B-24): `dfc.assemble_hot(plan)` в executor-фазе.
4. Spans: `agent.plan`, `agent.execute`, `agent.test` (с `concurrent=false` в BETA).
5. Metrics: `orya_tri_model_verdict{verdict}` (pass/fail/replan), `orya_tri_model_replan_total`.

#### Constraints

- Planner prompt: see `app/core/workflow/prompts.py::PLAN_PROMPT` (TODO: write).
- Tester prompt: see `app/core/workflow/prompts.py::TESTER_PROMPT` (TODO: write).
- Tester получает: criteria (from plan), diff (from executor), run_tests=false (в BETA — full run_tests в PROD через Concurrent Tester P-24).
- Replan bounded N=2: после 2 неудач → fallback на final fail (return verdict=fail, no more replans).
- В BETA Concurrent Tester — basic (not overlapped с executor); full overlap в P-24.
- LangGraph `astream_events` v2 для partial diff (но в BETA не используется, full impl в P-24).

#### Acceptance Criteria

- ✅ `TriModelPipeline(planner=Haiku, executor=Sonnet, tester=Haiku).build()` возвращает compiled LangGraph.
- ✅ Pipeline: planner → executor → tester → END (если verdict=pass) или → replan (если verdict=fail).
- ✅ Replan bounded N=2: после 2 replans → END с verdict=fail.
- ✅ Plan dataclass: `steps`, `criteria`, `prefetch_hints`, `tier` — корректно populated из planner output.
- ✅ Integration с DFC: `dfc.assemble_hot(plan)` возвращает HOT, ≤16K токенов.
- ✅ Integration с TieredModelRouter: `router.select(tier=plan.tier, user_id=...)` возвращает correct model.
- ✅ Spans: `agent.plan`, `agent.execute`, `agent.test` эмитятся.
- ✅ Metrics: `orya_tri_model_verdict{verdict=pass}` counter инкрементируется после successful turn.
- ✅ Verdict rate (pass на 1st attempt) > 75% на synthetic test dataset (10 сценариев).
- ✅ Replan rate < 20%.

#### Forbidden patterns

- ❌ Использовать Sonnet для planner/tester — дорого; Haiku/Qwen-3B достаточно.
- ❌ Block executor на tester (в BETA — sequential; concurrent в P-24).
- ❌ Unbounded replan (max 2).
- ❌ Hardcoded prompts — в `prompts.py`.

#### Suggested files

- `app/core/workflow/tri_model.py`
- `app/core/workflow/prompts.py` (PLAN_PROMPT, TESTER_PROMPT)
- `app/core/workflow/state.py` (TurnState, Plan, Verdict dataclasses)
- `tests/test_tri_model.py`
- `tests/fixtures/synthetic_dataset.yml` (10 scenarios)

---

### B-26 — LSP-bus + 6 LSP-servers + 7 LSP-tools 🆕

> **Component:** ARCHITECT7 §3 #20, §6.3, ROADMAP7 §21 | **Dependencies:** M-04 (graph skeleton), M-22 (injection defense v5) | **Estimate:** 7 дней | **TRIZ:** #28 Mechanics substitution + #24 Intermediary

#### Context

v6 добывает код-факты через `read`+`grep` (как у всех 5 SOTA) + OriaHS semantic search. Для типичной code-задачи нужно: сигнатура функции, её определение, ссылки на неё, diagnostics. Сейчас это 3-5 LLM round-trips + чтение файлов (2-20K токенов на файл). Latency 3-8 s. LSP-native даёт sub-ms latency + 100-500 токенов на операцию.

#### Goal

1. Реализовать `app/core/lsp/bus.py::LSPBus` — per-language LSP-server manager (stdio).
2. Реализовать `app/core/lsp/client.py::LSPClient` — stdio JSON-RPC client.
3. LSP-server support: 6 языков (Python, TypeScript, Rust, Go, Java, Lua).
4. Реализовать 7 LSP tools в `app/tools/lsp.py`:
   - `lsp_hover(file, line, col)` — signature + type + docstring.
   - `lsp_definition(file, line, col)` — location of definition.
   - `lsp_references(file, line, col)` — list of call-sites.
   - `lsp_symbol_search(query)` — workspace/symbol.
   - `lsp_rename(file, line, col, new_name)` — atomic rename across refs.
   - `lsp_diagnostics(file)` — мгновенные diagnostics.
   - `lsp_code_action(file, line, col)` — quick-fix, refactor.
5. File watcher (chokidar / inotify / `watchdog` Python package) → `textDocument/didChange` (incremental).
6. `app/mcp/lsp_mcp.py` — MCP-сервер обёртка для UKB (B-27).
7. LSP-server modes: `in-process` (default, subprocess), `sidecar` (docker, FUTURE+), `shared` (HTTP, FUTURE+).
8. Integration с v6 SystemPromptBuilder: LSP diagnostics pushed to DFC.hot (через `lsp.diagnostics` → `dfc.promote_to_hot`).
9. Metrics: `orya_lsp_call_total{method,language}`, `orya_lsp_latency_ms{method,language}`, `orya_lsp_server_uptime{language}`.
10. Spans: `lsp.call` (с `lsp.method`, `lsp.language`, `lsp.latency_ms`).

#### Constraints

- LSP-servers: `pyright-langserver --stdio` (Python), `typescript-language-server --stdio` (TS/JS), `rust-analyzer` (Rust), `gopls` (Go), `jdtls` (Java), `lua-language-server` (Lua).
- LSP-servers запускаются как subprocess в `in-process` mode (default).
- Workspace root = project root (auto-detected from session state).
- File watcher: `watchdog` Python package (cross-platform).
- LSP `initialize` → `initialized` → `didOpen` per file.
- `didChange` — incremental (range-based, не full text).
- LSP-server crash → auto-restart (max 3 retries, потом degraded mode).
- Degraded mode: fallback на `read+grep` для code-facts.
- LSP-server pid + port persisted в Redis (`orya:lsp:server:{language}:{workspace_hash}`) для cross-process reuse (если несколько OryaAgent instances на одной машине).
- LSP-server sandbox: separate process, no FS write (только read + diagnostics).
- LSP rename может affect >100 files → safety check (confirmed by user в BETA, automated в PROD).

#### Acceptance Criteria

- ✅ `LSPBus.ensure_server("python", workspace=Path("/tmp/test_proj"))` запускает pyright-langserver.
- ✅ `lsp_hover("/tmp/test_proj/main.py", line=10, col=5)` возвращает signature + type + docstring (если есть).
- ✅ `lsp_definition(...)` возвращает location (file, line, col) где символ определён.
- ✅ `lsp_references(...)` возвращает list of call-sites (file, line, col).
- ✅ `lsp_symbol_search("UserService")` возвращает top-K matches (sub-ms).
- ✅ `lsp_rename(...)` атомарно переименовывает symbol across all references (verified через grep -c old_name == 0 после rename).
- ✅ `lsp_diagnostics(...)` возвращает list of errors/warnings (мгновенно, vs `bash(run linter)` ~ seconds).
- ✅ `lsp_code_action(...)` возвращает list of available quick-fixes/refactors.
- ✅ File watcher: изменение `.py` файла → `didChange` → diagnostics updated (latency < 100 ms).
- ✅ LSP-server crash → auto-restart, regained within 5 s.
- ✅ 3 retries exhausted → degraded mode (fallback на read+grep, `lsp.degraded=true` span attribute).
- ✅ Latency p95: `lsp_hover` < 10 ms, `lsp_definition` < 10 ms, `lsp_references` < 20 ms, `lsp_symbol_search` < 50 ms, `lsp_rename` < 500 ms, `lsp_diagnostics` < 50 ms, `lsp_code_action` < 50 ms.
- ✅ `lsp-mcp` MCP-сервер обёртка: `lsp.hover`, `lsp.def`, `lsp.refs`, `lsp.symbol_search`, `lsp.rename`, `lsp.diagnostics`, `lsp.codeAction` exposed.
- ✅ Metrics exported в Prometheus.
- ✅ Spans: `lsp.call` с правильными атрибутами.

#### Forbidden patterns

- ❌ Использовать `read+grep` когда LSP available — LSP-first.
- ❌ LSP-server как FS-writer (rename — это OK, но не write/edit).
- ❌ Block agent-loop на LSP-server startup — lazy initialization.
- ❌ Mix LSP-server state between workspaces — workspace isolation.
- ❌ Hardcoded LSP-server paths — auto-detect or through settings.

#### Suggested files

- `app/core/lsp/__init__.py`
- `app/core/lsp/bus.py`
- `app/core/lsp/client.py`
- `app/core/lsp/watcher.py` (file watcher integration)
- `app/tools/lsp.py` (7 LSP tools)
- `app/mcp/lsp_mcp.py` (MCP server wrapper)
- `tests/test_lsp_bus.py`
- `tests/test_lsp_tools.py`
- `tests/fixtures/test_proj/` (small Python/TS/Rust/Go/Java/Lua projects for testing)

---

### B-27 — UKB Router (partial: lsp + memory) 🆕

> **Component:** ARCHITECT7 §3 #22, §6.4 | **Dependencies:** B-26 (LSP-native), v6 B-21 (SQLiteStore L1), v6 P-18 (Qdrant L2, только PROD) | **Estimate:** 3 дня | **TRIZ:** #5 Merging + #12 Equipotentiality

#### Context

v6 имеет фрагментированные retrieval-точки: `read`/`grep` (5 базовых tools), `oriahs_search` (codebase indexing), `memory_search` (L1+L2 memory). LLM должна знать, когда какую вызывать; observability фрагментирована. В v7 UKB (Unified Knowledge Bus) — единый MCP-контракт над LSP/RAG/Memory/code/KB. В BETA — partial (только lsp + memory namespaces, без oriahs/code/kb). В PROD — full (5 namespaces).

#### Goal

1. Реализовать `app/core/ukb/router.py::UKBRouter`:
   - 2 namespaces в BETA: `lsp.*`, `memory.*`.
   - Routing rules: explicit `capability` parameter → specific namespace; default → parallel lookup all (2 namespaces в BETA).
   - `lookup(query, capability=None, filters=None, top_k=5) -> list[dict]`.
   - Merge + dedupe by content hash.
2. Реализовать `app/tools/ukb.py::ukb_lookup` — single retrieval tool для LLM.
3. Integration с B-26 (LSP): `lsp-mcp` available as UKB namespace.
4. Integration с v6 memory (B-21 SQLiteStore + P-18 Qdrant в PROD): `memory-mcp` (через v6 PROD P-18) available as UKB namespace (в BETA — mock; full в PROD).
5. Metrics: `orya_ukb_lookup_total{namespace}`, `orya_ukb_lookup_duration_ms{namespace}`.
6. Spans: `ukb.lookup` (с `ukb.capability`, `ukb.namespace`, `ukb.top_k`, `ukb.merge_dedup_count`).

#### Constraints

- Routing rules: see `app/core/ukb/router.py::UKBRouter.RULES`.
- Explicit capability: `lsp.def`, `lsp.symbol_search`, `memory.semantic`, `memory.lexical`.
- Default (no capability): parallel lookup all available namespaces (lsp + memory в BETA; + oriahs + code + kb в PROD).
- Merge: by content hash (sha256 of serialized content).
- Top_k: per-namespace top_k, merged top_k = max(per-namespace top_k).
- В BETA: `memory-mcp` mock (returns empty or simple FTS5 results from v6 B-21 SQLiteStore).
- В PROD: `memory-mcp` full (v6 P-18 hybrid L1+L2).

#### Acceptance Criteria

- ✅ `ukb_lookup("function:userService.create", capability="lsp.def")` routes to `lsp-mcp` → `textDocument/definition`.
- ✅ `ukb_lookup("memory-tier design", capability="memory.semantic")` routes to `memory-mcp` → Qdrant lookup (mock в BETA).
- ✅ `ukb_lookup("hello")` (default) → parallel lookup all namespaces, merge + dedupe.
- ✅ Merge: 2 namespaces return same item → only 1 in result.
- ✅ Latency p95: ≤ 500 ms для single-namespace lookup; ≤ 800 ms для parallel multi-namespace.
- ✅ Spans: `ukb.lookup` с правильными атрибутами.
- ✅ Metrics exported.

#### Forbidden patterns

- ❌ Direct LSP/memory calls from agent-loop bypass UKB — all retrieval through `ukb_lookup`.
- ❌ Hardcoded namespace routing — through rules table.
- ❌ Mix namespaces (e.g., return LSP result with memory namespace metadata).

#### Suggested files

- `app/core/ukb/__init__.py`
- `app/core/ukb/router.py`
- `app/tools/ukb.py` (ukb_lookup tool)
- `tests/test_ukb_router.py`

---

### B-28 — RetrievalOrchestrator (7 strategies) 🆕

> **Component:** ARCHITECT7 §3 #27, §6.7 | **Dependencies:** B-24 (DFC), B-27 (UKB partial) | **Estimate:** 4 дня | **TRIZ:** #24 Intermediary + #10 Preliminary action

#### Context

v6 имеет `memory_search` tool (PROD). LLM решает, когда вызвать retrieval — но это непредсказуемо. Иногда LLM забывает; иногда вызывает лишнее. В v7 RetrievalOrchestrator — отдельный модуль, который **решает**, когда retrieve, по 7 стратегиям.

#### Goal

1. Реализовать `app/core/retrieval/orchestrator.py::RetrievalOrchestrator`:
   - 7 strategies: `none`, `standard`, `topic_continuation`, `speculative_prefetch`, `explicit_recall`, `code_lookup`, `degraded`.
   - `decide(session_state) -> str` — returns strategy name.
   - `execute(strategy, session_state) -> list[RetrievedChunk]`.
   - Heuristics: referential markers ("помнишь, обсуждали..."), similar tokens, first turn, predictive hint (placeholder в BETA, full в PROD).
2. Integration с B-24 (DFC): results → promote to HOT.
3. Integration с B-27 (UKB): UKB is the executor.
4. Integration с RerankPolicy (P-25 в PROD): orchestrator calls rerank policy; в BETA — always apply rerank.
5. Metrics: `orya_retrieval_strategy_total{strategy}`, `orya_retrieval_decision_accuracy` (через synthetic dataset).
6. Spans: `retrieval.orchestrate` (с `retrieval.strategy`, `retrieval.query`, `retrieval.rerank_applied`).

#### Constraints

- Heuristics in `app/core/retrieval/heuristics.py`:
  - Referential markers: regex `помнишь|обсуждали|ранее|в прошлый раз`.
  - Similar tokens: cosine similarity > 0.7 with previous turn (через embeddings).
  - First turn: `session_state.turn_count == 0`.
  - Predictive hint: from PredictivePlanner (placeholder в BETA, full в PROD).
- `top_k`: per strategy (см. `ARCHITECT7 §3 #27` table).
- Rerank applied per strategy (см. RerankPolicy P-25 в PROD; в BETA — always apply).
- Decision accuracy measured на synthetic dataset: 10 scenarios с known correct strategy.

#### Acceptance Criteria

- ✅ `RetrievalOrchestrator.decide(state)` возвращает один из 7 strategy names.
- ✅ `RetrievalOrchestrator.execute("none", state)` возвращает `[]`.
- ✅ `RetrievalOrchestrator.execute("standard", state)` возвращает top-3 results (в BETA — mock; в PROD — через UKB).
- ✅ `RetrievalOrchestrator.execute("explicit_recall", state)` возвращает top-10 results (после referential marker detected).
- ✅ Decision accuracy > 75% на synthetic dataset (10 scenarios).
- ✅ Integration с DFC: results → `dfc.promote_to_hot(key, value)`.
- ✅ Integration с UKB: orchestrator calls `ukb.lookup(...)` в execute.
- ✅ Spans: `retrieval.orchestrate` с правильными атрибутами.
- ✅ Metrics exported.

#### Forbidden patterns

- ❌ Block agent-loop на retrieval — async only.
- ❌ Always retrieve (default strategy = `none` для performance).
- ❌ Hardcoded heuristics — through heuristics.py table.

#### Suggested files

- `app/core/retrieval/__init__.py`
- `app/core/retrieval/orchestrator.py`
- `app/core/retrieval/heuristics.py`
- `app/core/retrieval/models.py` (RetrievedChunk dataclass)
- `tests/test_retrieval_orchestrator.py`
- `tests/fixtures/retrieval_scenarios.yml` (10 scenarios with known correct strategy)

---

### B-29 — CapabilityRegistry (dynamic tool-filter per turn) 🆕

> **Component:** ARCHITECT7 §3 #28, §6.8 | **Dependencies:** M-04 (graph skeleton), B-26 (LSP-tools), B-27 (UKB tool) | **Estimate:** 2 дня | **TRIZ:** #15 Dynamicity + #25 Self-service

#### Context

v6 имеет 5 базовых + oriahs_search + oriahs_index + memory_search + (v7: lsp_* × 7) + (v7: ukb_lookup) = 15+ tools. LLM видит все каждый ход → 1500+ токенов tool-list → noise для decision-quality. В v7 CapabilityRegistry активирует инструменты по file/content triggers per turn (8-15 visible, not all 25+).

#### Goal

1. Реализовать `app/core/tools/capability_registry.py::CapabilityRegistry`:
   - `TRIGGERS` dict: per-tool predicates (file content, language, intent).
   - `filter(all_tools, context) -> list` — returns active tools.
   - `is_relevant(tool, context) -> bool`.
2. Triggers:
   - `lsp.hover`: `ctx.language in LSP_LANGUAGES`.
   - `lsp.def`: `ctx.has_symbol_at_cursor`.
   - `lsp.rename`: `ctx.intent == "rename"`.
   - `memory.search`: `ctx.referential_marker or ctx.asking_about_past`.
   - `oriahs_search`: `not ctx.language or ctx.cross_project_search` (PROD).
   - `ukb.lookup`: `True` (default visible).
3. Integration с v6 tool-registry: filter tools before passing to LLM.
4. Metrics: `orya_capability_filter_active_count` (gauge), `orya_capability_filter_filtered_out_total`.
5. Spans: `capability.filter` (с `capability.active_count`, `capability.filtered_out_count`).

#### Constraints

- Triggers in `app/core/tools/triggers.py` table (rule-based, не LLM-based).
- LLM-mini fallback classifier: если rule-based trigger returns `None` → call LLM-mini (Haiku) для classification (в PROD; в BETA — default visible).
- Default visible: `read`, `write`, `edit`, `bash`, `grep` (5 базовых), `ukb.lookup` (single retrieval).
- Default invisible: all LSP-tools (visible when trigger matches), `oriahs_search` (PROD), `memory_search` (PROD).
- Max active tools per turn: 15.
- LLM sees filtered tool-list каждый turn.

#### Acceptance Criteria

- ✅ `CapabilityRegistry.filter(all_tools, ctx_no_language)` возвращает 5 базовых + ukb.lookup = 6 tools (no LSP, no oriahs, no memory).
- ✅ `CapabilityRegistry.filter(all_tools, ctx_python_file)` возвращает 5 базовых + ukb.lookup + lsp.hover + lsp.def + lsp.references = 9 tools.
- ✅ `CapabilityRegistry.filter(all_tools, ctx_rename_intent)` возвращает 5 базовых + ukb.lookup + lsp.rename = 7 tools.
- ✅ `CapabilityRegistry.filter(all_tools, ctx_referential_marker)` возвращает 5 базовых + ukb.lookup + memory.search = 7 tools.
- ✅ Max active tools per turn ≤ 15.
- ✅ LLM видит только filtered tools (verified через `bind_tools` в LangGraph state).
- ✅ Spans: `capability.filter` с правильными атрибутами.
- ✅ Metrics exported.

#### Forbidden patterns

- ❌ LLM-based triggers на каждом turn (rule-based primary, LLM-mini fallback в PROD).
- ❌ Block agent-loop на filter — sync, fast (<10 ms).
- ❌ Hardcoded tool-list — through triggers table.

#### Suggested files

- `app/core/tools/capability_registry.py`
- `app/core/tools/triggers.py`
- `app/core/tools/context.py` (TurnContext dataclass)
- `tests/test_capability_registry.py`

---

## 5. Фаза PROD (P-20 … P-26 — новые в v7)

### P-20 — BatchRunner + BenchmarkComparator + CLI 🆕

> **Component:** ARCHITECT7 §3 #21, §6.10, ROADMAP7 §22 | **Dependencies:** B-25 (Tri-Model), B-24 (DFC), v6 P-00 (OriaHS bootstrap, optional) | **Estimate:** 3 дня | **TRIZ:** #19 Periodic action + #25 Self-service

#### Context

v6 — только интерактивный режим. Нельзя прогнать 50 промптов на CI, нельзя сделать built-in benchmark для собственного развития. В v7 BatchRunner загружает `prompts.yml`, для каждого промпта прогоняет tri-model конвейер, пишет результат в `results.jsonl`. Тот же runner — встроенный benchmark.

#### Goal

1. Реализовать `app/batch/runner.py::BatchRunner`:
   - `run(prompts_path, output_path, parallel=4)` — parallel execution.
   - `_run_task(task)` — single task, runs tri-model.
   - Output: `results.jsonl` с `{id, status, duration_ms, tokens, cost_usd, attempts, diff, test_log}`.
2. Реализовать `app/batch/comparator.py::BenchmarkComparator`:
   - `compare(current_jsonl, baseline_jsonl) -> DiffReport`.
   - DiffReport: per-task status changes, latency diff, cost diff.
3. FastAPI endpoints (см. `ARCHITECT7 §8.1`):
   - `POST /sessions/{id}/batch/run` — sync.
   - `POST /sessions/{id}/batch/run/async` — async, returns job_id.
   - `GET /batch/status/{job_id}`.
   - `GET /batch/results/{job_id}` — download results.jsonl.
   - `POST /batch/compare`.
4. CLI: `orya batch run --input prompts.yml --output results.jsonl`, `orya batch compare --current results.jsonl --baseline main/results.jsonl`.
5. Built-in benchmark: `prompts.yml` в корне репозитория (20 эталонных задач: 5 simple, 5 medium, 5 hard, 5 cross-project).
6. Integration с DFC + Tri-Model + UKB (все BETA features).
7. Span-type: `batch.run` (с `batch.task_id`, `batch.status`, `batch.attempts`, `batch.cost_usd`).
8. Metrics: `orya_batch_run_total{status}`, `orya_batch_run_duration_ms`, `orya_batch_pass_rate`.

#### Constraints

- Parallel execution: `asyncio.Semaphore(parallel=4)` default.
- Process isolation per batch (для safety: each batch — separate subprocess в FUTURE+; в PROD — same process, but isolated DFC state).
- Output format: see `ARCHITECT7 §7.4`.
- Built-in benchmark scope: 20 tasks (5 simple + 5 medium + 5 hard + 5 cross-project).
- Each task in `prompts.yml`: `id`, `prompt`, `criteria` (list), `expected` (string, optional).
- Async endpoint: `POST /batch/run/async` returns `{"job_id": "..."}` immediately; client polls `/batch/status/{job_id}`.
- Sync endpoint: `POST /batch/run` blocks until done (timeout 60 min).
- CLI: uses async endpoint internally, polls status, prints progress.

#### Acceptance Criteria

- ✅ `orya batch run --input prompts.yml --output results.jsonl` работает, 20 tasks executed.
- ✅ Output `results.jsonl` contains 20 lines, each valid JSON.
- ✅ Pass-rate > 80% на built-in benchmark.
- ✅ `orya batch compare --current results.jsonl --baseline main/results.jsonl` показывает diff: какие tasks стали pass/fail, latency diff per task, cost diff.
- ✅ `POST /sessions/{id}/batch/run/async` returns `{job_id}` in < 100 ms.
- ✅ `GET /batch/status/{job_id}` returns `{status: "running|completed|failed", progress: 0-100}`.
- ✅ `GET /batch/results/{job_id}` returns the results.jsonl file.
- ✅ `POST /batch/compare` with two JSONL files returns DiffReport.
- ✅ Parallel execution: 4 tasks in parallel, no race conditions (verified через test с 10 parallel tasks).
- ✅ Span `batch.run` эмитится с правильными атрибутами.
- ✅ Metrics exported.

#### Forbidden patterns

- ❌ Sequential execution (1 task at a time) — parallel default 4.
- ❌ Mix DFC state between parallel tasks — each task gets isolated DFC snapshot.
- ❌ Hardcoded benchmark scope — through `prompts.yml`.
- ❌ Block agent-loop on batch execution — async only.

#### Suggested files

- `app/batch/__init__.py`
- `app/batch/runner.py`
- `app/batch/comparator.py`
- `app/batch/models.py` (BatchTask, BatchResult, DiffReport dataclasses)
- `app/api/routes/batch.py`
- `app/cli/batch.py` (CLI commands)
- `prompts.yml` (built-in benchmark, 20 tasks)
- `tests/test_batch_runner.py`
- `tests/test_batch_comparator.py`

---

### P-21 — SymbolicClassifier (LLM bypass для rename/format) 🆕

> **Component:** ARCHITECT7 §3 #23, §6.6 | **Dependencies:** B-25 (Tri-Model), B-26 (LSP-native), B-29 (CapabilityRegistry) | **Estimate:** 2 дня | **TRIZ:** #16 Partial effect + #21 Rushing

#### Context

~15% ходов в код-проекте — детерминированные (`rename`, `format`, `organize-imports`, `extract-variable`). v6 вызывает executor LLM (2-6 s, 5-20K tokens) для каждой такой задачи. В v7 SymbolicClassifier распознаёт intent; planner эмитит LSP-tool-call; executor LLM **не вызывается**; tester верифицирует. Latency: 500-1500 ms вместо 2-6 s.

#### Goal

1. Реализовать `app/core/workflow/symbolic_classifier.py::SymbolicClassifier`:
   - Regex patterns for `rename`, `format`, `organize-imports`, `extract-variable`.
   - LLM-mini fallback classifier (Haiku) для non-regex matches.
   - `classify(prompt) -> (tool_name | None, args | None)`.
2. Pipeline integration с B-25 Tri-Model:
   - Planner-фаза: if `SymbolicClassifier.classify(prompt)` returns `(tool_name, args)`:
     - Skip executor LLM.
     - Directly call LSP-tool (`lsp.rename`, `lsp.format`, etc.).
     - Tester verifies diff.
   - Fallback: if LSP-tool returns error → fall back to executor LLM (regular tri-model flow).
3. Span-type: `agent.symbolic_shortcut` (с `tool.name`, `tool.args`, `bypass_executor=true`).
4. Metrics: `orya_symbolic_shortcut_usage` (gauge), `orya_symbolic_shortcut_fallback_total` (counter).

#### Constraints

- Regex patterns: see `app/core/workflow/symbolic_classifier.py::SYMBOLIC_PATTERNS`.
- LLM-mini fallback: Haiku, prompt in `app/core/workflow/prompts.py::SYMBOLIC_CLASSIFIER_PROMPT`.
- LSP rename safety check: if `lsp.rename` affects > 100 files → confirm with user (в PROD).
- Tester: same as in B-25 (Haiku, criteria match).
- Fallback на executor: when LSP-tool fails OR tester verdict=fail.
- Symbolic Shortcut only for: `rename`, `format`, `organize-imports`, `extract-variable` (4 patterns). Other intents → regular tri-model.

#### Acceptance Criteria

- ✅ `SymbolicClassifier.classify("rename UserService to AccountService")` returns `("lsp.rename", {"old_name": "UserService", "new_name": "AccountService"})`.
- ✅ `SymbolicClassifier.classify("format src/main.py")` returns `("lsp.format", {"file": "src/main.py"})`.
- ✅ `SymbolicClassifier.classify("organize imports in src/utils.py")` returns `("lsp.organize_imports", {"file": "src/utils.py"})`.
- ✅ `SymbolicClassifier.classify("refactor this code")` returns `(None, None)` (regular tri-model flow).
- ✅ Pipeline: when `intent: symbolic` → skip executor LLM, call LSP-tool directly, tester verifies.
- ✅ Fallback: when LSP-tool returns error → executor LLM is called (regular tri-model).
- ✅ Fallback: when tester verdict=fail after symbolic shortcut → executor LLM is called (regular tri-model).
- ✅ `orya_symbolic_shortcut_usage` metric: ~15% (target).
- ✅ Latency for symbolic turn: ≤ 1500 ms (vs regular 2000-6000 ms).
- ✅ Spans: `agent.symbolic_shortcut` эмитится с `bypass_executor=true`.

#### Forbidden patterns

- ❌ Symbolic Shortcut for non-deterministic tasks (e.g., "refactor this code" — ambiguous).
- ❌ Skip tester verification — tester always verifies.
- ❌ Block agent-loop on LSP-tool call — async, <500 ms.
- ❌ Hardcoded patterns — through SYMBOLIC_PATTERNS table.

#### Suggested files

- `app/core/workflow/symbolic_classifier.py`
- `app/core/workflow/prompts.py` (update: add SYMBOLIC_CLASSIFIER_PROMPT)
- `tests/test_symbolic_classifier.py`

---

### P-22 — PredictivePlanner + Heat Cache integration 🆕

> **Component:** ARCHITECT7 §3 #24, §6.5 | **Dependencies:** B-24 (DFC Heat Cache), B-25 (Tri-Model) | **Estimate:** 5 дней | **TRIZ:** #10 Preliminary action + #11 Beforehand cushioning

#### Context

v6 SpeculativePreFetcher (rule-based) стартует после planner'а, на критическом пути. В v7 PredictivePlanner — small-модель в фоне, прогнозирует следующий промпт, prefetcher греет Heat Cache **до** прихода промпта. Когда пользователь посылает промпт, HOT уже собран из Heat Cache → **первый токен за <500 ms**.

#### Goal

1. Реализовать `app/core/workflow/predictive_planner.py::PredictivePlanner`:
   - Background asyncio task, tick=1s.
   - Model: Qwen-3B (local through Ollama) / Llama-3.2-1B / Haiku-3.5 (configurable).
   - `_predict_next() -> Prediction` — LLM-call с recent prompts + last feedback.
   - `_prefetch_to_heat(hints)` — parallel LSP + UKB + memory_search prefetch.
   - `feedback(actual_prompt, predicted_prompt)` — for DPO training later.
2. Heat Cache integration (B-24): if `confidence > 0.6` → warm Heat Cache.
3. DPO training loop: раз в N=100 ходов, update weights on pairs (predicted, actual). LoRA fine-tune (optional, FUTURE+).
4. Span-type: `predictive_planner.predict` (с `prediction.confidence`, `prediction.match` post-hoc).
5. Metrics: `orya_predictive_planner_accuracy`, `orya_predictive_planner_miss_total`, `orya_dfc_heat_hit_rate`.

#### Constraints

- Model: `settings.predictive_planner_model` (default `qwen-3b` through Ollama).
- Tick: 1 s (configurable).
- Confidence threshold: 0.6 (default).
- Heat Cache TTL: 5 минут (if not used → expired).
- DPO training: раз в 100 turns, batch update on (predicted, actual) pairs.
- Data minimization: only recent prompts (last 5), no PII in prediction input.
- Background task — не блокирует agent-loop.
- False-positive protection: if Heat Cache MISS (predicted != actual) → log `predictive_planner_miss`, next prediction gets lower confidence weight.

#### Acceptance Criteria

- ✅ `PredictivePlanner.start()` запускает background asyncio task.
- ✅ После каждого turn: `feedback(actual_prompt, predicted_prompt)` вызывается.
- ✅ Prediction: `{predicted_prompt, confidence, prefetch_hints, expected_tier}`.
- ✅ If `confidence > 0.6` → Heat Cache warmed (verified через `dfc.heat_cache` size).
- ✅ On next turn: if `actual_prompt == predicted_prompt` → Heat Cache HIT (latency <500 ms до первого токена).
- ✅ Accuracy > 60% после 2 недель (на synthetic dataset).
- ✅ Heat Cache hit rate > 50%.
- ✅ `orya_predictive_planner_miss_total` counter increments on MISS.
- ✅ DPO training: after 100 turns, model weights updated (LoRA fine-tune, optional).
- ✅ `PREDICTIVE_PLANNER_ENABLED=false` — disable.
- ✅ Span `predictive_planner.predict` эмитится с правильными атрибутами.

#### Forbidden patterns

- ❌ Use PII in prediction input — data minimization.
- ❌ Block agent-loop on prediction — async, background.
- ❌ Hardcoded model — through settings.
- ❌ Always warm Heat Cache (only if `confidence > 0.6`).

#### Suggested files

- `app/core/workflow/predictive_planner.py`
- `app/core/workflow/prompts.py` (update: add PREDICTIVE_PROMPT)
- `app/core/workflow/dpo_trainer.py` (optional, FUTURE+)
- `tests/test_predictive_planner.py`

---

### P-23 — TournamentExecutor + judge-mcp 🆕

> **Component:** ARCHITECT7 §3 #25, §6.6 | **Dependencies:** B-25 (Tri-Model), A-18 (TieredModelRouter), B-24 (DFC snapshot) | **Estimate:** 4 дня | **TRIZ:** #40 Composite materials + #22 Convert harm into benefit

#### Context

v6 CostAwareRouter — cost-control, не quality-control. Для сложных задач нет механизма «запустить N параллельных executors + judge выбирает лучшего». В v7 TournamentExecutor: planner эмитит `tier=tournament`, 3 parallel executors (different models/temperatures), judge-mcp выбирает лучшего. Latency=max(N), не sum. Cost=N×, но -2..3 replan-итераций.

#### Goal

1. Реализовать `app/core/workflow/tournament.py::TournamentExecutor`:
   - `run(plan, criteria, budget_usd=0.10) -> TournamentResult`.
   - N=3 parallel executors (different models or same model with different temperatures).
   - Cost-aware: if `estimated_cost > budget_usd` → degrade на single executor (regular tri-model flow).
   - `judge_mcp` integration: separate MCP-server for judge-вызовов.
2. Реализовать `app/mcp/judge_mcp.py` — MCP-сервер:
   - Exposes `judge.select_winner(plan, criteria, candidates) -> int`.
   - Model: Sonnet (small).
3. Integration с B-25 Tri-Model: `tier=tournament` эмитится planner'ом → TournamentExecutor активируется.
4. Integration с B-24 DFC: each executor gets immutable `dfc.snapshot()`.
5. Span-types: `agent.tournament` (с `tournament.n`, `tournament.models`, `winner_idx`, `judge.model`, `judge.cost`), `judge.call`.
6. Metrics: `orya_tournament_total{verdict}`, `orya_tournament_cost_usd`, `orya_tournament_win_rate`.

#### Constraints

- N=3 (default), configurable.
- Models: `[Sonnet, GPT-5, DeepSeek-V3]` or `[Sonnet@0.3, Sonnet@0.7, Sonnet@1.0]` (configurable).
- Judge model: Sonnet (small).
- Budget: `tournament_max_cost_usd=0.10` default.
- If `estimated_cost > budget_usd` → degrade на single executor (return regular tri-model result, `tournament.degraded=true` span attribute).
- Each executor gets immutable `dfc.snapshot()` — no shared mutable state.
- Replan on tournament disagreement (N=3, ни один не pass) → bounded N=2 retries, fallback на symbolic shortcut.

#### Acceptance Criteria

- ✅ `TournamentExecutor.run(plan, criteria)` с `tier=tournament` → 3 parallel executors started.
- ✅ All 3 executors complete (or fail) → judge-mcp called → winner_idx returned.
- ✅ Cost-aware: `estimated_cost > 0.10 USD` → degrade на single executor, `tournament.degraded=true`.
- ✅ `judge.call` span эмитится с `judge.model`, `judge.cost`.
- ✅ `agent.tournament` span: `tournament.n=3`, `tournament.models=["Sonnet", "GPT-5", "DeepSeek-V3"]`, `winner_idx=0/1/2`.
- ✅ Win-rate > 80% (judge picks winner, not replan).
- ✅ Replan on disagreement: after N=3 fails → replan с ужесточёнными критериями.
- ✅ Bounded N=2 retries: after 2 replans → END with verdict=fail.
- ✅ Each executor: immutable DFC snapshot (verified через test — mutating one executor's DFC doesn't affect others).

#### Forbidden patterns

- ❌ Unbounded tournament retries (max 2).
- ❌ Mix DFC state between parallel executors — immutable snapshot.
- ❌ Hardcoded models — through settings.
- ❌ Always run tournament (only when `tier=tournament` эмитится planner'ом).

#### Suggested files

- `app/core/workflow/tournament.py`
- `app/mcp/judge_mcp.py`
- `app/core/workflow/prompts.py` (update: add JUDGE_PROMPT)
- `tests/test_tournament_executor.py`
- `tests/test_judge_mcp.py`

---

### P-24 — Concurrent Tester (extension of B-25 tri-model) 🆕

> **Component:** ARCHITECT7 §3 #26, §6.2 | **Dependencies:** B-25 (Tri-Model), B-24 (DFC) | **Estimate:** 3 дня | **TRIZ:** #21 Rushing + #15 Dynamicity

#### Context

B-25 Tri-Model (BETA) запускает tester после завершения executor'а. Latency = executor + tester = 2.5-7 s. В v7 Concurrent Tester overlap с последними токенами executor'а на partial diff. Early-exit, если критерии уже невыполнимы.

#### Goal

1. Расширить `app/core/workflow/tri_model.py::_test_concurrent_node` (из B-25):
   - Start tester when executor partial diff detectable.
   - LangGraph `astream_events` v2 для partial diff detection.
   - Partial diff parser: detect valid diff в streaming output.
   - Early-abort executor при partial verdict = early-fail.
2. Span-types: `agent.test.concurrent`, `agent.test.early_abort`.
3. Metrics: `orya_tri_model_early_abort_total`, `orya_tri_model_verdict{verdict}`.

#### Constraints

- Partial diff detection: parse streaming output, detect valid diff (via AST-aware parser from v2 code-mcp).
- Partial verdict: tester checks criteria that don't require final diff (e.g., "endpoint exists at /health" — checkable early).
- Early-abort: if `partial_verdict.is_early_fail == true` → set `state.early_abort_executor = true` → executor stops.
- Trade-off: concurrent tester +200 ms latency на запуск, but -200..400 ms на ожидание executor + -30% cost на провальных ходах.
- Abort tester on inconsistent partial diff (e.g., partial diff parser fails) → restart с final diff.
- Lock-free snapshot reads (immutable partial diff snapshots).

#### Acceptance Criteria

- ✅ Concurrent tester starts when executor partial diff detectable (verified через `agent.test.concurrent` span с `concurrent=true`).
- ✅ Partial diff parser: detects valid diff в streaming output (e.g., for `bash` tool: when "```python" code block closes).
- ✅ Early-abort: when `partial_verdict.is_early_fail` → executor stops within 100 ms.
- ✅ `orya_tri_model_early_abort_total` counter increments on early-abort.
- ✅ Early-abort rate > 15% of failed turns.
- ✅ -30% cost на провальных ходах (verified через cost comparison test).
- ✅ -200..400 ms tester-latency (verified через latency comparison test).
- ✅ Abort tester on inconsistent partial diff → restart с final diff (verified через test с malformed streaming output).

#### Forbidden patterns

- ❌ Block executor on tester (concurrent — overlap, not sequential).
- ❌ Mix partial diff state between tester runs — immutable snapshots.
- ❌ Hardcoded partial diff parser — through AST-aware parser (code-mcp).

#### Suggested files

- `app/core/workflow/tri_model.py` (update: extend `_test_concurrent_node`)
- `app/core/workflow/partial_diff_parser.py`
- `tests/test_concurrent_tester.py`

---

### P-25 — RerankPolicy with skip + fallback chain 🆕

> **Component:** ARCHITECT7 §3 #29, §6.7 | **Dependencies:** B-27 (UKB), B-28 (RetrievalOrchestrator), v6 P-00 (OriaHS) | **Estimate:** 2 дня | **TRIZ:** #11 Beforehand cushioning + #35 Parameter changes

#### Context

v6 использует OriaHS rerank (always-on, cross-encoder ~100 ms). Для коротких queries (`"rename X"`) rerank — overhead. В v7 RerankPolicy решает: применять rerank, skip, или fallback chain.

#### Goal

1. Реализовать `app/core/retrieval/rerank_policy.py::RerankPolicy`:
   - `decide(query, state) -> RerankDecision`.
   - Strategies: `identifier_lookup` (skip rerank), `short_query` (skip), `default` (apply rerank with cache), `from_cache` (LRU).
   - `execute_with_fallback(query, ukb) -> list`.
2. Fallback chain: `hybrid+rerank → hybrid → lexical → degraded`.
3. LRU cache для повторяющихся queries (target 15-30% hit rate).
4. Integration с B-28 RetrievalOrchestrator: orchestrator calls rerank policy.
5. Span-types: `retrieval.rerank` (с `retrieval.rerank_applied`, `retrieval.rerank_cache_hit`), `retrieval.fallback` (с `retrieval.fallback_level`).
6. Metrics: `orya_rerank_skip_total{reason}`, `orya_rerank_cache_hit_rate`, `orya_rerank_fallback_total{level}`.

#### Constraints

- Identifier lookup: `re.match(r"^[a-zA-Z_][a-zA-Z0-9_]*$", query)` → skip rerank.
- Short query: `len(query.split()) < 3` → skip rerank.
- Default: apply rerank (cross-encoder через OriaHS), top_k_pre=20, top_k_post=8.
- LRU cache: max 1000 entries, TTL 5 min.
- Fallback chain:
  1. `hybrid+rerank` (default) — if reranker unavailable → 2.
  2. `hybrid` (no rerank) — if Qdrant unavailable → 3.
  3. `lexical` (FTS5 only) — if all vector unavailable → 4.
  4. `degraded` (empty result, warning) — log and continue.

#### Acceptance Criteria

- ✅ `RerankPolicy.decide("UserService", state)` returns `RerankDecision(apply_rerank=False, reason="identifier_lookup")`.
- ✅ `RerankPolicy.decide("hello world", state)` returns `RerankDecision(apply_rerank=False, reason="short_query")`.
- ✅ `RerankPolicy.decide("how to refactor UserService", state)` returns `RerankDecision(apply_rerank=True, top_k_pre=20, top_k_post=8, reason="default")`.
- ✅ LRU cache: 2nd identical query → `RerankDecision(from_cache=True)`.
- ✅ `orya_rerank_cache_hit_rate` > 15% (target 15-30%).
- ✅ Fallback chain: reranker unavailable → `hybrid` (no rerank) → `lexical` → `degraded`.
- ✅ `orya_rerank_skip_total{reason="identifier_lookup"}` counter increments.
- ✅ `retrieval.fallback` span эмитится с `fallback_level=hybrid|lexical|degraded`.
- ✅ Integration с RetrievalOrchestrator (B-28): orchestrator calls `rerank_policy.decide()` before UKB lookup.

#### Forbidden patterns

- ❌ Always-rerank (default is `decide()` based on policy).
- ❌ Hardcoded query length thresholds — through settings.
- ❌ Mix cache state between threads — Lock for LRU.

#### Suggested files

- `app/core/retrieval/rerank_policy.py`
- `app/core/retrieval/models.py` (update: add RerankDecision)
- `tests/test_rerank_policy.py`

---

### P-26 — Best-of-N execution (simplified tournament) 🆕

> **Component:** ARCHITECT7 §3 #31 | **Dependencies:** P-23 (Tournament), B-25 (Tri-Model) | **Estimate:** 1 день | **TRIZ:** #21 Rushing + #16 Partial effect

#### Context

Tournament (P-23) — full version with judge-mcp. Для simpler use cases (N=2, no judge needed, criteria match sufficient) — Best-of-N execution: 2 parallel executors, tester выбирает лучшего по criteria match (без отдельной judge-модели).

#### Goal

1. Реализовать `app/core/workflow/best_of_n.py::BestOfNExecutor`:
   - `run(plan, criteria, n=2) -> BestOfNResult`.
   - N=2 parallel executors (different temperatures).
   - Tester выбирает лучшего по criteria match (deterministic).
   - Tie-break: prefer executor.model from `models[0]`.
2. Integration с P-23 Tournament: Best-of-N активируется когда `tier=tournament` но `budget_usd < tournament_threshold` (e.g., $0.05).
3. Span-types: `agent.best_of_n` (с `best_of_n.n`, `best_of_n.winner_idx`).
4. Metrics: `orya_best_of_n_total{verdict}`, `orya_best_of_n_tie_break_total`.

#### Constraints

- N=2 (default).
- Models: same model, different temperatures (e.g., `[Sonnet@0.3, Sonnet@0.7]`).
- Tester: same as in B-25 (Haiku, criteria match).
- Criteria match: deterministic function `match_score(diff, criteria) -> float`.
- Tie-break: prefer `models[0]`.
- Activate when `tier=tournament` AND `budget_usd < 0.05` (configurable threshold).

#### Acceptance Criteria

- ✅ `BestOfNExecutor.run(plan, criteria, n=2)` returns result with `winner_idx=0|1`.
- ✅ Criteria match: deterministic, same input → same winner.
- ✅ Tie-break: if both executors have same match_score → `winner_idx=0` (preferred model).
- ✅ Activate when `tier=tournament` AND `budget < 0.05` (vs Tournament P-23 with `budget >= 0.05`).
- ✅ Span `agent.best_of_n` эмитится с `best_of_n.n=2`, `best_of_n.winner_idx=0|1`.
- ✅ `orya_best_of_n_total{verdict=pass}` counter increments after successful turn.

#### Forbidden patterns

- ❌ Use Best-of-N when Tournament is appropriate (N=3 with judge-mcp).
- ❌ Non-deterministic criteria match.
- ❌ Hardcoded N — through settings.

#### Suggested files

- `app/core/workflow/best_of_n.py`
- `tests/test_best_of_n.py`

---

## 6. Фаза EXTENSION-PROD (E-12 … E-14 — опциональные новые в v7)

### E-12 — (опц.) WASM-LSP ports (rust-analyzer, typescript) 🆕

> **Component:** ARCHITECT7 §17, ROADMAP7 §21 | **Dependencies:** B-26 (LSP-native), E-00 (EXTENSION-PROD triggers) | **Estimate:** 1 неделя | **TRIZ:** #28 Mechanics substitution

#### Context

B-26 LSP-bus использует stdio subprocess (~10 ms latency per LSP-call). Для high-frequency LSP usage (>100 calls per turn) — this is bottleneck. WASM-порты LSP-серверов (in-process, no subprocess overhead) — target latency <0.1 ms.

#### Goal

1. Compile rust-analyzer и typescript-language-server в WASM (если есть WASM-порты).
2. Интеграция с `app/core/lsp/bus.py::LSPBus` — `LSP_MODE=wasm` setting.
3. In-process WASM runtime (through `wasmtime` Python package).
4. Span attribute: `lsp.mode` (stdio|wasm).

#### Constraints

- Only for LSP-servers with WASM-ports available (rust-analyzer ✅, typescript ✅, others ❌).
- Default mode: `stdio` (B-26 baseline).
- WASM mode: opt-in через `LSP_MODE=wasm`.
- Fallback: if WASM-compile fails → degrade на stdio.

#### Acceptance Criteria

- ✅ `LSP_MODE=wasm` setting supported.
- ✅ rust-analyzer WASM port: `lsp_hover` latency < 0.1 ms (vs stdio ~10 ms).
- ✅ typescript-language-server WASM port: `lsp_hover` latency < 0.1 ms.
- ✅ Fallback: if WASM unavailable → stdio, `lsp.degraded=true` span.
- ✅ `lsp.mode` span attribute: `stdio` or `wasm`.

#### Forbidden patterns

- ❌ Force WASM mode (default stdio).
- ❌ Mix WASM and stdio for same language.

#### Suggested files

- `app/core/lsp/wasm_runtime.py`
- `app/core/lsp/bus.py` (update: support WASM mode)
- `tests/test_lsp_wasm.py`

---

### E-13 — (опц.) Multi-instance DFC sync (Heat Cache + HOT) 🆕

> **Component:** ARCHITECT7 §17, ROADMAP7 §19 | **Dependencies:** v6 E-11 (multi-instance memory), B-24 (DFC) | **Estimate:** 1 неделя | **TRIZ:** #15 Dynamicity

#### Context

v6 E-11 sync memory (L0+L1+L2) between OryaAgent instances. В v7 DFC state (HEAT, HOT, WARM) — per-instance. Для multi-instance deployment нужно sync DFC state через OriaHS (single-source-of-truth для HEAT Cache; HOT и WARM — local caches).

#### Goal

1. Heat Cache sync: pull при старте, push при записи (background).
2. HOT sync: lazy pull при Heat Cache HIT (если local HOT miss → check remote).
3. Conflict resolution: timestamp-based, latest wins.
4. Latency: eventual consistency (до 5 минут lag допустим).

#### Constraints

- Heat Cache: stored в OriaHS Qdrant collection `agent_heat` (new).
- HOT: not synced (per-instance, ephemeral).
- WARM: not synced (per-instance, ephemeral).
- COLD: not synced (per-instance, compacts).

#### Acceptance Criteria

- ✅ 2 OryaAgent instances, Predictive Planner on instance A → Heat Cache warmed → pull on instance B within 5 минут.
- ✅ Conflict: simultaneous write на A и B → latest timestamp wins.
- ✅ Local cache fallback: при offline OriaHS → чтение из local Heat Cache.

#### Forbidden patterns

- ❌ Strong consistency — eventual only.
- ❌ Sync HOT or WARM — local caches.

#### Suggested files

- `app/core/dfc/sync.py`
- `app/core/dfc/conflict_resolver.py`

---

### E-14 — (опц.) Multi-instance LSP-server cluster 🆕

> **Component:** ARCHITECT7 §17 | **Dependencies:** B-26 (LSP-native), E-13 (multi-instance DFC) | **Estimate:** 1 неделя | **TRIZ:** #1 Segmentation

#### Context

B-26 LSP-server — per-instance (subprocess per OryaAgent process). Для multi-instance deployment: shared LSP-server cluster (one LSP-server per language, shared across instances).

#### Goal

1. LSP-server cluster: one LSP-server per language, shared via HTTP transport.
2. LSP-server discovery: through Redis (`orya:lsp:server:{language}:{workspace_hash}`).
3. Client: `LSPClient` supports both stdio (B-26) and HTTP (E-14) modes.
4. Load balancing: round-robin across LSP-server replicas.

#### Constraints

- HTTP transport: through `pylsp-https` or custom HTTP wrapper.
- LSP-server discovery: at startup, query Redis for available servers.
- Load balancing: simple round-robin (no fancy algorithms).
- Fallback: if no shared LSP-server available → local stdio subprocess.

#### Acceptance Criteria

- ✅ 2 OryaAgent instances, shared LSP-server (rust-analyzer) on machine A.
- ✅ Instance B: `lsp_hover` routes to shared LSP-server (HTTP transport).
- ✅ Load balancing: 2 replicas → round-robin.
- ✅ Fallback: shared LSP-server unavailable → local stdio subprocess.

#### Forbidden patterns

- ❌ Force shared mode (default stdio in B-26).
- ❌ Hardcoded shared LSP-server URL — through Redis discovery.

#### Suggested files

- `app/core/lsp/cluster.py`
- `app/core/lsp/http_client.py`
- `tests/test_lsp_cluster.py`

---

## 7. Фаза FUTURE (F-10 … F-11 — новые в v7)

### F-10 — Predictive User Model K=3 + Task Embedding Index 🆕

> **Component:** FUTURE7.md §2 (predictive user model), §3 (task embedding index) | **Dependencies:** P-22 (Predictive Planner), P-20 (Batch Runner) | **Estimate:** — | **TRIZ:** #10 Preliminary action

(см. FUTURE7.md для деталей)

### F-11 — Continuous Planner daemon (requires neuromorphic inference) 🆕

> **Component:** FUTURE7.md §6 (continuous planner daemon) | **Dependencies:** P-22 (Predictive Planner), neuromorphic hardware | **Estimate:** — | **TRIZ:** #19 Periodic action

(см. FUTURE7.md для деталей)

---

## 8. Meta-тикеты (R-06 … R-07 — новые в v7)

### R-06 — Architecture synthesis documentation (v0.1+v0.2+v0.3 → v7) 🆕

> **Component:** ARCHITECT7 §2 (inventory) | **Dependencies:** все v7 тикеты | **Estimate:** 4 часа | **TRIZ:** —

#### Context

v7 synthesises 14 architectural primitives from v0.1/v0.2/v0.3. Нужна отдельная документация для контрибьюторов, объясняющая какой примитив откуда пришёл и почему выбран.

#### Goal

Создать `docs/V7_SYNTHESIS.md` с:
1. Inventory таблицей (примитив → источник → почему выбран → фаза).
2. Aufhebung таблицей (что сохранено, что снято).
3. Cross-references на ARCHITECT7, ARCHITECT, ARCHITECT2, ARCHITECT3.

#### Acceptance Criteria

- ✅ `docs/V7_SYNTHESIS.md` существует.
- ✅ Inventory таблица для всех 14 примитивов v7.
- ✅ Cross-references работают.

#### Suggested files

- `docs/V7_SYNTHESIS.md`

---

### R-07 — Comparison v7 vs opencode vs kilocode documentation 🆕

> **Component:** FUTURE7.md §1 (comparison) | **Dependencies:** все v7 тикеты | **Estimate:** 6 часов | **TRIZ:** —

#### Context

В FUTURE7 §1 — детальный сравнительный анализ v7 vs opencode vs kilocode. Нужна отдельная документация для контрибьюторов и для external communication (blog posts, talks).

#### Goal

Создать `docs/COMPARISON_V7_VS_OPENCODE_VS_KILOCODE.md` с:
1. Подробное сравнение по 12 характеристикам.
2. Где v7 сильнее, где слабее.
3. Migration paths (если пользователь хочет перейти с opencode/kilocode на v7).
4. References на `agents-architect.md` (родительский документ).

#### Acceptance Criteria

- ✅ `docs/COMPARISON_V7_VS_OPENCODE_VS_KILOCODE.md` существует.
- ✅ 12 характеристик сравнения.
- ✅ Migration paths описаны.

#### Suggested files

- `docs/COMPARISON_V7_VS_OPENCODE_VS_KILOCODE.md`

---

## 9. Сводная матрица тикетов × фаз

| Фаза | Кол-во тикетов v7 | Кол-во тикетов v6 | Delta | Суммарная оценка v7 |
|---|---|---|---|---|
| MVP | 28 (= v6) | 28 | +0 | ~19 дней |
| ALPHA | 21 (A-00..A-20) | 18 | +3 (TieredModelRouter, PromptCacheLayout, ConnectionPool) | ~16 дней |
| BETA | 30 (B-00..B-29) | 24 | +6 (DFC, Tri-Model, LSP, UKB, Orchestrator, Capability) | ~30 дней |
| PROD | 27 (P-00..P-26) | 20 | +7 (Batch, Symbolic, Predictive, Tournament, Concurrent Tester, RerankPolicy, Best-of-N) | ~26 дней |
| EXTENSION-PROD | 15 (E-00..E-14) | 12 | +3 опц. (WASM-LSP, multi-DFC-sync, LSP-cluster) | ~7 недель |
| FUTURE | 12 (F-00..F-11) | 10 | +2 (Predictive User Model, Continuous Planner) | ~4 месяца |
| Meta | 7 (R-01..R-07) | 5 | +2 (synthesis docs, comparison docs) | ~3 дня |
| **Итого до PROD** | **106 + 7 meta** | **90 + 5 meta** | **+18** | **~91 день (~18 недель)** |

---

## 10. Карта зависимостей между тикетами

```
MVP v7 (= v6 MVP):
  (без изменений от v6)

ALPHA v7 (3 new tickets):
  A-13 (CostAwareRouter v6) → A-18 (TieredModelRouter extends)
  A-04 (observability baseline v6) → A-19 (PromptCacheLayout cache_hit span attribute)
  A-02 (LLM seam v6) → A-20 (ConnectionPool)

BETA v7 (6 new tickets):
  M-25 (MDStore v6) + A-19 (PromptCacheLayout) + A-18 (TieredModelRouter) → B-24 (DFC)
  B-24 (DFC) + A-18 (TieredModelRouter) + A-19 (PromptCacheLayout) → B-25 (Tri-Model Pipeline)
  M-04 (graph skeleton v6) → B-26 (LSP-bus + 6 servers + 7 tools) — independent
  B-24 (DFC) + B-26 (LSP) → B-27 (UKB partial: lsp + memory)
  B-24 (DFC) + B-27 (UKB partial) → B-28 (RetrievalOrchestrator)
  B-26 (LSP) + B-27 (UKB) → B-29 (CapabilityRegistry)

PROD v7 (7 new tickets):
  v6 P-00 (OriaHS bootstrap) + B-25 (Tri-Model) + B-24 (DFC) → P-20 (Batch Runner)
  B-25 (Tri-Model) + B-26 (LSP) + B-29 (CapabilityRegistry) → P-21 (Symbolic Classifier)
  B-24 (DFC Heat Cache) + B-25 (Tri-Model) → P-22 (Predictive Planner)
  B-25 (Tri-Model) + A-18 (TieredModelRouter) + B-24 (DFC snapshot) → P-23 (Tournament)
  B-25 (Tri-Model) → P-24 (Concurrent Tester extension)
  B-27 (UKB) + B-28 (RetrievalOrchestrator) + v6 P-00 (OriaHS) → P-25 (RerankPolicy)
  P-23 (Tournament) → P-26 (Best-of-N simplified)

EXTENSION-PROD v7 (3 опц. new tickets):
  B-26 (LSP-native stdio) → E-12 (WASM-LSP опц.)
  v6 E-11 (multi-instance memory) + B-24 (DFC) → E-13 (multi-instance DFC sync опц.)
  B-26 (LSP-native) + E-13 (multi-instance DFC) → E-14 (multi-instance LSP cluster опц.)

FUTURE v7 (2 new tickets):
  P-22 (Predictive Planner) + P-20 (Batch Runner) → F-10 (Predictive User Model K=3 + Task Embedding Index)
  P-22 (Predictive Planner) + neuromorphic hardware → F-11 (Continuous Planner daemon)

META v7 (2 new tickets):
  R-06 (V7 synthesis docs) — after all v7 тикеты
  R-07 (Comparison docs) — after all v7 тикеты
```

---

## 11. Соответствие тикетов ТРИЗ-принципам и 20/80

| Принцип | Тикеты v7 | Эффект |
|---|---|---|
| (все принципы из v6 §11) | (унаследовано) | — |
| #1 Segmentation (расширение) | A-18 (TieredModelRouter tier=small/large/tournament) | Tier-based model selection |
| #5 Merging | B-27 (UKB) | Single retrieval interface |
| #9 Preliminary anti-action | B-25 (Tri-Model tester), P-24 (Concurrent Tester early-abort) | Self-verifying loop |
| #10 Preliminary action (расширение) | P-22 (Predictive Planner), B-28 (RetrievalOrchestrator), F-10 (Predictive User Model) | Forecast next prompt, prefetch заранее |
| #11 Beforehand cushioning (расширение) | A-19 (PromptCacheLayout), A-20 (ConnectionPool), P-25 (RerankPolicy fallback) | Hot pool, no cold-start |
| #12 Equipotentiality | B-27 (UKB единый формат context items) | Унифицированный retrieval |
| #15 Dynamicity (расширение) | B-24 (DFC HOT-пересборка), B-29 (CapabilityRegistry), P-23 (Tournament degrade), E-13 (multi-instance DFC) | Гибкость |
| #16 Partial effect | P-21 (Symbolic Shortcut), P-26 (Best-of-N) | LLM bypass для детерминированных задач |
| #17 Another dimension | B-24 (DFC 3 оси: file × symbol × time) | In-window context discipline |
| #19 Periodic action (расширение) | P-20 (Batch Runner), A-19 (PromptCacheLayout cross-turn) | CI-benchmark + cache |
| #21 Rushing (расширение) | P-24 (Concurrent Tester), P-21 (Symbolic Shortcut), P-26 (Best-of-N) | Overlap executor + tester |
| #22 Convert harm into benefit | P-23 (Tournament cost N× → quality N×) | Cost-quality trade-off |
| #24 Intermediary | B-26 (LSP-bus), B-27 (UKB Router), B-28 (RetrievalOrchestrator) | Посредник между LLM и sources |
| #25 Self-service (расширение) | P-20 (Batch Runner self-improvement) | User-control |
| #28 Mechanics substitution (расширение) | B-26 (LSP-native), B-27 (UKB), E-12 (WASM-LSP) | LSP вместо read+grep |
| #35 Parameter changes (расширение) | A-18 (TieredModelRouter), P-25 (RerankPolicy) | Tier-based, policy-driven |
| #40 Composite materials | B-25 (Tri-Model), P-23 (Tournament) | Multi-model pipeline |

### 20/80-анализ новых тикетов v7

| Тикет | Усилия | Ценность | 20/80? |
|---|---|---|---|
| A-18 (TieredModelRouter) | 4 часа | 60% (-25..40% cost на простых ходах) | ✅ |
| A-19 (PromptCacheLayout) | 6 часов | 70% (-800 ms time-to-first-token) | ✅ |
| A-20 (ConnectionPool) | 6 часов | 60% (-200..500 ms cold-start) | ✅ |
| B-24 (DFC) | 5 дней | 80% (tokens ≤16K, -50% cost на длинных сессиях) | ✅ |
| B-25 (Tri-Model) | 4 дня | 80% (self-verifying loop, -1..3 replan-итераций) | ✅ |
| B-26 (LSP-native) | 7 дней | 80% (-100× latency на code-facts, -10× tokens) | ✅ |
| B-27 (UKB partial) | 3 дня | 60% (единый retrieval-интерфейс) | ✅ |
| B-28 (RetrievalOrchestrator) | 4 дня | 70% (-30..60% wasted retrievals) | ✅ |
| B-29 (CapabilityRegistry) | 2 дня | 50% (-40% tool-list tokens) | ✅ |
| P-20 (Batch Runner) | 3 дня | 80% (CI-benchmark + self-improvement) | ✅ |
| P-21 (Symbolic Shortcut) | 2 дня | 80% (~15% ходов без LLM-executor) | ✅ |
| P-22 (Predictive Planner) | 5 дней | 70% (-200..400 ms planner-latency) | ✅ |
| P-23 (Tournament) | 4 дня | 60% (quality-tournament на сложных задачах) | ⚠️ (только для power-users) |
| P-24 (Concurrent Tester) | 3 дня | 60% (-30% cost на провальных ходах) | ✅ |
| P-25 (RerankPolicy) | 2 дня | 50% (-50% rerank-cost на easy queries) | ✅ |
| P-26 (Best-of-N) | 1 день | 40% (parallel executors на сложных задачах) | ⚠️ (simplified P-23) |
| E-12 (WASM-LSP опц.) | 1 неделя | 30% (только для high-frequency LSP) | ⚠️ (опционально) |
| E-13 (multi-instance DFC опц.) | 1 неделя | 30% (только для multi-instance) | ⚠️ (опционально) |
| E-14 (multi-instance LSP cluster опц.) | 1 неделя | 30% (только для multi-instance) | ⚠️ (опционально) |
| F-10 (Predictive User Model) | — | 50% (FUTURE) | ⚠️ (FUTURE) |
| F-11 (Continuous Planner) | — | 50% (FUTURE, требует hardware) | ⚠️ (FUTURE) |
| R-06 (Synthesis docs) | 4 часа | 30% (документация) | ✅ |
| R-07 (Comparison docs) | 6 часов | 30% (документация) | ✅ |

---

*Конец документа BACKLOG7.md*