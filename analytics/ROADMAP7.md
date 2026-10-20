# ROADMAP7 — Дорожная карта OryaAgent v7 (speed + memory + self-verification synthesis)

> **Версия документа:** 7.0
> **Дата:** 20 октября 2026
> **Источники:** `ARCHITECT7.md` v7.0, `ROADMAP6.md` v6.0 (baseline), `BACKLOG7.md` v7.0, `ARCHITECT.md` v0.1, `ARCHITECT2.md` v0.2, `ARCHITECT3.md` v0.3
> **Стек:** Python 3.11+, LangChain 0.3+, LangGraph 0.2+, FastAPI, PostgreSQL 16, Redis 7, Chainlit, OriaHS, OryaObservability SDK, LSP-серверы
> **Методология:** 6 фаз зрелости — **MVP → ALPHA → BETA → PROD → EXTENSION-PROD → FUTURE** (унаследовано от v6), с интеграцией 14 новых улучшений v7 (см. `ARCHITECT7 §0`)
> **Статус:** roadmap готов к реализации; v7 — надстройка над v6, не замена

---

## Содержание

0. Что изменилось относительно v6 (executive summary)
1. Обзор и принципы категоризации
2. Сводная карта фаз
3. Фаза MVP — (= v6 MVP, без изменений)
4. Фаза ALPHA — (+ TieredModelRouter, PromptCacheLayout, ConnectionPool)
5. Фаза BETA — (+ DFC, Tri-Model Pipeline, LSP-native, UKB, RetrievalOrchestrator, CapabilityRegistry)
6. Фаза PROD — (+ Batch, Symbolic, Predictive, Tournament, Concurrent Tester, RerankPolicy, Best-of-N)
7. Фаза EXTENSION-PROD — (= v6 EXT-PROD + WASM-LSP опционально)
8. Фаза FUTURE — (= v6 FUTURE + см. FUTURE7.md)
9. Сводная матрица фаз × компонентов v7
10. Карта зависимостей между фазами v7
11. Критерии перехода между фазами (exit criteria, delta от v6)
12. TRIZ-gates по фазам (полная карта v7)
13. NFR-таргеты по фазам v7
14. Риски и mitigations (delta от v6)
15. Метрики прогресса внедрения v7
16. UI-стратегия по фазам (delta от v6)
17. Fast-track paths (дополнение к v6)
18. Rollback-процедуры между фазами (delta от v6)
19. Triggers для EXTENSION-PROD (уточнённые в v7)
20. Deprecation mechanism (дополненный в v7)
21. LSP integration track (новое в v7)
22. Batch-runner integration track (новое в v7)

---

## 0. Что изменилось относительно v6 (executive summary)

`ROADMAP7.md` сохраняет 6 фаз из v6, но **распределяет 14 новых улучшений v7** (см. `ARCHITECT7 §0`) по фазам согласно зависимостям:

1. **MVP** — без изменений от v6 (L0 memory, /learn, OryaObservability baseline). v7 не добавляет в MVP, чтобы не нарушать «время до первого работающего агента» (3.5 недели).
2. **ALPHA** — добавляет 3 улучшения v7: **TieredModelRouter (#30)**, **PromptCacheLayout (#32)**, **ConnectionPool (#14)**. Все три — низкорисковые, совместимы с CostAwareRouter v6, дают big latency win.
3. **BETA** — добавляет 6 улучшений v7: **DFC (#18)**, **Tri-Model Pipeline (#19)**, **LSP-native (#20)**, **UKB (#22)**, **RetrievalOrchestrator (#27)**, **CapabilityRegistry (#28)**. Это самая большая фаза (+5000 LOC, 7 недель) — закрывает главные пробелы v6.
4. **PROD** — добавляет 7 улучшений v7: **Batch Pipeline (#21)**, **Symbolic Shortcut (#23)**, **Predictive Planner (#24)**, **Tournament (#25)**, **Concurrent Tester (#26)**, **RerankPolicy (#29)**, **Best-of-N (#31)**. Power-features для power-users (+13000 LOC, 9 недель).
5. **EXTENSION-PROD** — (= v6 EXT-PROD) + опционально **WASM-LSP** (если созреет).
6. **FUTURE** — (= v6 FUTURE) + все направления из `FUTURE7.md`.

### Ключевые изменения по фазам (delta от v6)

| Фаза | Длительность | Что нового в v7 | +LOC |
|---|---|---|---|
| **MVP** | 3.5 недели (= v6) | ничего (полностью = v6 MVP) | +0 |
| **ALPHA** | 3 недели (+0.5 недели) | + TieredModelRouter (#30), PromptCacheLayout (#32), ConnectionPool (#14) | +500 |
| **BETA** | 7 недель (+2 недели) | + DFC (#18), Tri-Model Pipeline (#19), LSP-native (#20), UKB (#22), RetrievalOrchestrator (#27), CapabilityRegistry (#28) | +5000 |
| **PROD** | 9 недель (+3 недели) | + Batch Pipeline (#21), Symbolic Shortcut (#23), Predictive Planner (#24), Tournament (#25), Concurrent Tester (#26), RerankPolicy (#29), Best-of-N (#31) | +13000 |
| **EXTENSION-PROD** | по triggers | (= v6 EXT-PROD) + опционально WASM-LSP | +1000 (если WASM) |
| **FUTURE** | не ограничено | (= v6 FUTURE) + см. FUTURE7 | — |

### Что НЕ меняется

- **6 фаз зрелости** (MVP → ALPHA → BETA → PROD → EXTENSION-PROD → FUTURE) — без изменений.
- **Принцип фазовой организации** (каждая фаза опирается на предыдущую, не модифицирует её контракт) — без изменений.
- **TRIZ-gates с первого дня фазы** (внедряются вместе с фичами, не «потом») — без изменений.
- **Reversible-переходы** (rollback к предыдущей фазе) — без изменений.
- **Явные triggers** для перехода к следующей фазе — без изменений.
- **Fast-track paths** из v6 (memory-only, observability-only) — без изменений + см. §17 (новый fast-track: speed-only).
- **Deprecation mechanism** — без изменений + см. §20 (deprecation Langfuse-direct в пользу sampler-proxy в ALPHA v6/v7).

---

## 1. Обзор и принципы категоризации

(см. `ROADMAP6.md` §1 — без изменений, кроме §1.4)

### 1.4. Принцип ТРИЗ на уровне фаз (дополнение в v7)

Каждая фаза должна:
- **Внедрять TRIZ-gates с первого дня фазы** (не «потом»).
- **Иметь reversible-переходы** к предыдущей фазе (rollback).
- **Иметь явные triggers** для перехода к следующей фазе.
- **Иметь deprecation-plan** для фич, которые могут стать устаревшими.
- **Иметь observability с первого дня фазы** (из v6).
- **🆕 В v7: внедрять улучшения параллельно с зависимостями** — например, DFC (#18) и Tri-Model Pipeline (#19) в BETA параллельно, не последовательно, поскольку DFC зависит от plan + criteria (#19), а #19 зависит от HOT-context (#18).

---

## 2. Сводная карта фаз

| Фаза | Длительность | Главная цель v7 | Что лежит в основе | Новое в v7 (delta от v6) |
|---|---|---|---|---|
| **MVP** | 3.5 недели | (= v6 MVP) — Рабочий кодинг-агент + FastAPI + L0 MD-память + /learn | LangGraph + FastAPI + Chainlit + 5 tools + PostgresSaver + CacheWrapper + MDStore | ничего (= v6 MVP) |
| **ALPHA** | 3 недели | Production-safe + OryaObservability SDK + sampler-proxy + **TieredModelRouter + PromptCacheLayout + ConnectionPool** | v6 ALPHA + tiered router + prompt-cache + connection pool | TieredModelRouter (#30), PromptCacheLayout (#32), ConnectionPool (#14) |
| **BETA** | 7 недель | Расширяемость + L1 SQLite memory + **DFC + Tri-Model + LSP-native + UKB + RetrievalOrchestrator + CapabilityRegistry** | v6 BETA + 6 новых архитектурных примитивов | DFC (#18), Tri-Model (#19), LSP-native (#20), UKB (#22), RetrievalOrchestrator (#27), CapabilityRegistry (#28) |
| **PROD** | 9 недель | OriaHS + L2 Qdrant memory + **Batch Pipeline + Symbolic + Predictive + Tournament + Concurrent Tester + RerankPolicy + Best-of-N** | v6 PROD + 7 power-features | Batch Pipeline (#21), Symbolic Shortcut (#23), Predictive Planner (#24), Tournament (#25), Concurrent Tester (#26), RerankPolicy (#29), Best-of-N (#31) |
| **EXTENSION-PROD** | по triggers | Масштабирование + multi-instance memory + (опционально) WASM-LSP | v6 EXT-PROD + WASM-LSP опция | WASM-LSP (если созреет) |
| **FUTURE** | не ограничено | Автономность + continuous prompt-learning + см. FUTURE7 | v6 FUTURE + новые направления | все направления из FUTURE7.md |

**Ключевая инвариантность v7:** каждая следующая фаза опирается на компоненты предыдущей, но не модифицирует их контракт. DFC (BETA) → UKB (BETA) → Batch (PROD) → Continuous prompt-learning (FUTURE) — additive layers, не replacement.

---

## 3. Фаза MVP — (= v6 MVP, без изменений)

(см. `ROADMAP6.md` §3 — полностью без изменений)

**Принцип MVP v7:** не нарушать «время до первого работающего агента». v6 MVP (3.5 недели) — достаточно для базового code-агента с L0 memory. Добавление v7 features в MVP замедлит time-to-market без пропорциональной ценности.

### 3.1. Цели фазы (= v6)

Доставить end-to-end работающего кодинг-агента с нормальным UI с первого дня + базовой долговременной памятью в MD-файлах + командой /learn. (Подробнее — см. `ROADMAP6.md` §3.1.)

### 3.2. Компоненты фазы (= v6, M-00 … M-27)

(см. `ROADMAP6.md` §3.2 — полностью без изменений)

### 3.3. TRIZ-gates фазы (= v6)

(см. `ROADMAP6.md` §3.3)

### 3.4. DoD (= v6)

(см. `ROADMAP6.md` §3.4)

### 3.5. Целевые NFR фазы (= v6)

(см. `ROADMAP6.md` §3.5)

### 3.6. Риски фазы и mitigations (= v6)

(см. `ROADMAP6.md` §3.6)

---

## 4. Фаза ALPHA — production-safe baseline + TieredModelRouter + PromptCacheLayout + ConnectionPool

### 4.1. Цели фазы

Превратить «работающий MVP с базовой памятью» в «production-safe + low-latency baseline»: добавить auth, rate-limits, OryaObservability SDK, sampler-proxy (всё из v6 ALPHA), а также **три новых low-risk улучшения v7**:

1. **TieredModelRouter (#30)** — расширение CostAwareRouter v6. Planner эмитит `tier: small | large | tournament`. Router выбирает модель по tier, **независимо** от budget. Cost-aware fallback (если budget ≥90% → degrade на tier=small) остаётся из v6.
2. **PromptCacheLayout (#32)** — дисциплина cacheable prefix + dynamic suffix. Использует провайдерские prompt-caches (Anthropic `cache_control: ephemeral`, OpenAI prompt caching) для cross-turn KV-cache.
3. **ConnectionPool (#14)** — keepalive + hot adapters для LLM-provider seam. -200..500 ms cold-start TCP+TLS на каждом ходе.

**Принцип ALPHA v7 (vs v6):** +0.5 недели, +500 LOC, но **3 low-risk улучшения** дают -800 ms time-to-first-token (PromptCacheLayout) + -25..40% cost на простых ходах (TieredModelRouter) + -200..500 ms cold-start (ConnectionPool).

### 4.2. Компоненты фазы (дополнение к v6 ALPHA)

#### 4.2.1-4.2.11 (= v6 ALPHA — без изменений)

(см. `ROADMAP6.md` §4.2.1-4.2.11 — полностью без изменений)

#### 4.2.12. TieredModelRouter 🆕 (A-18)

- `app/core/llm/tiered_router.py::TieredModelRouter` — расширение `CostAwareRouter` (v6 A-13).
- `select(tier, user_id)` → `ModelSelection(model, tier, degraded)`.
- `tier=small` → Haiku/Qwen-3B.
- `tier=large` → Sonnet/Opus.
- `tier=tournament` → defer to TournamentExecutor (PROD).
- Cost-aware fallback: `budget_ratio >= 0.9` → degrade на tier=small.
- Span attribute: `agent.execute.tier`, `agent.execute.degraded`.

#### 4.2.13. PromptCacheLayout 🆕 (A-19)

- `app/core/llm/prompt_cache.py::PromptCacheLayout`.
- `assemble(system, tools, project_summary, l0_memory, dynamic)` → LangChain messages с `cache_control: ephemeral` markers.
- Cacheable prefix: system + tools + project_summary + L0 memory (4 MD-файла).
- Dynamic suffix: plan + active symbols + active diff (из DFC, но DFC появится в BETA — для ALPHA dynamic suffix = past user/assistant messages).
- Provider support: Anthropic `cache_control`, OpenAI prompt caching, Gemini context caching.
- Span attribute: `llm.call.cache_hit` (true|false), `llm.call.cache_age_seconds`.

#### 4.2.14. ConnectionPool 🆕 (A-20)

- `app/core/llm/connection_pool.py::ConnectionPool`.
- Per-provider keepalive connections (httpx.AsyncClient + transport).
- Hot pool size: 4 (default), configurable.
- LRU eviction при превышении.
- Periodic health-check (раз в 30 s).
- Fail-open: если connection unhealthy → spawn new.
- Provider coverage: Anthropic, OpenAI, Ollama (local), Google Vertex.

### 4.3. TRIZ-gates фазы (дополнение к v6 ALPHA)

| Gate | Принцип | Что встроено |
|---|---|---|
| (все gates из v6 ALPHA) | — | — |
| **TieredModelRouter** 🆕 | ТРИЗ #35 Parameter changes + #1 Segmentation | Tier-based model selection, бюджет-independent |
| **PromptCacheLayout** 🆕 | ТРИЗ #11 Beforehand + #19 Periodic | Provider KV-cache reuse cross-turn |
| **ConnectionPool** 🆕 | ТРИЗ #11 Beforehand + #15 Dynamicity | Hot pool, no cold-start TCP+TLS |

### 4.4. Definition of Done (дополнение к v6 ALPHA)

- ✅ (все DoD из v6 ALPHA)
- ✅ `TieredModelRouter.select(tier="small", user_id=...)` возвращает Haiku/Qwen-3B.
- ✅ `TieredModelRouter.select(tier="large", user_id=...)` возвращает Sonnet/Opus.
- ✅ При `budget_ratio >= 0.9` — `degraded=true`, tier понижен до `small`.
- ✅ Planner (когда появится в BETA) сможет эмитить tier; в ALPHA — hardcoded `large` default.
- ✅ `PromptCacheLayout.assemble(...)` возвращает LangChain messages с `cache_control: ephemeral`.
- ✅ Anthropic API получает `cache_control` markers (видно в trace через `llm.call.cache_hit=true`).
- ✅ Prompt-cache hit rate > 40% на тестовых сессиях (provider-side metric).
- ✅ `ConnectionPool` держит 4 keepalive connections per provider.
- ✅ При cold-start (после restart) — первый ход не платит TCP+TLS latency (verified через `tcp.connect_duration_ms` span).
- ✅ Health-check убивает unhealthy connections и создаёт новые.

### 4.5. Целевые NFR фазы (дополнение к v6 ALPHA)

| Параметр | Целевое значение v7 | v6 было |
|---|---|---|
| Time-to-first-token | ≤ 600 мс (vs v6 ≤ 1200 мс) | ≤ 1200 мс |
| Prompt-cache hit rate | > 60% | — |
| Connection-pool hit rate | > 95% | — |
| Cold-start latency (после restart) | ≤ 200 мс (vs v6 ~ 1000 мс) | ~ 1000 мс |
| Cost per turn (simple task, large tier) | $0.005 | $0.008 (no tiered router) |

### 4.6. Риски фазы и mitigations (дополнение к v6 ALPHA)

- (все риски из v6 ALPHA)
- **Prompt-cache invalidation при tool-registry changes** 🆕: `prompt_cache:prefix_hash` в Redis; invalidate при изменении tool-schemas.
- **ConnectionPool leak** 🆕: max_pool_size=4; LRU eviction; periodic health-check.
- **TieredModelRouter race condition** 🆕: emit `tier` до возврата model, не после.

---

## 5. Фаза BETA — расширяемость + 6 новых архитектурных примитивов v7

### 5.1. Цели фазы

Превратить «безопасный MVP с L0 memory + low-latency baseline» в «расширяемую платформу с DFC + Tri-Model + LSP-native + UKB + RetrievalOrchestrator + CapabilityRegistry». Помимо memory/MCP/hooks/skills/Next.js из v6, добавляются **6 новых архитектурных примитивов v7**:

1. **DFC (#18)** — Dynamic Fast Context, 5 слоёв (HEAT/HOT/WARM/COLD/ICE). In-window discipline, не заменяет v6 memory-layer.
2. **Tri-Model Pipeline (#19)** — LangGraph subgraph: plan → execute → test (concurrent с partial diff).
3. **LSP-native (#20)** — LSP-bus + lsp-mcp + 7 lsp-tools. Primary source код-фактов.
4. **UKB (#22)** — Unified Knowledge Bus, единый MCP-контракт над LSP/OriaHS/Memory/code/KB.
5. **RetrievalOrchestrator (#27)** — отдельный модуль, решающий когда retrieve (7 стратегий).
6. **CapabilityRegistry (#28)** — динамическая фильтрация инструментов per turn.

**Принцип BETA v7 (vs v6):** +2 недели, +5000 LOC, но закрывает **три главных пробела v6** (нет DFC, нет tri-model, нет LSP-native). Это самая большая фаза по объёму работы, но и по ценности.

### 5.2. Компоненты фазы (дополнение к v6 BETA)

#### 5.2.1-5.2.9 (= v6 BETA — без изменений)

(см. `ROADMAP6.md` §5.2.1-5.2.9 — полностью без изменений)

#### 5.2.10. DFC (Dynamic Fast Context) 🆕 (B-24)

- `app/core/dfc/__init__.py` — пакет DFC.
- `app/core/dfc/dfc.py::DFC` — 5 слоёв: HEAT/HOT/WARM/COLD/ICE.
- `app/core/dfc/heat_cache.py::HeatCache` — predicted HOT (active в PROD+ с Predictive Planner).
- `app/core/dfc/context_assembler.py::ContextAssembler` — assemble_hot() для system-prompt.
- `app/core/dfc/background_compactor.py::BackgroundCompactor` — WARM→COLD async.
- Интеграция с v6 `SystemPromptBuilder`: HOT + cacheable prefix → system-prompt.
- DFC state persisted в Redis (`orya:dfc:hot:{thread_id}`, `orya:dfc:warm:{thread_id}`).

#### 5.2.11. Tri-Model Pipeline 🆕 (B-25)

- `app/core/workflow/tri_model.py::TriModelPipeline`.
- LangGraph subgraph: plan → execute → test_finalize.
- Concurrent tester node стартует когда executor partial diff detectable.
- Replan node (bounded N=2 retries).
- Routing: planner → executor (через TieredModelRouter #30 из ALPHA), executor → tester.
- Tester verdict: pass / fail + reasons → replan if fail.
- 3 разные модели: planner (Haiku), executor (Sonnet via TieredModelRouter), tester (Haiku).
- Span-types: `agent.plan`, `agent.execute`, `agent.test`, `agent.test.concurrent`.

#### 5.2.12. LSP-native 🆕 (B-26)

- `app/core/lsp/bus.py::LSPBus` — per-language LSP-server manager.
- `app/core/lsp/client.py::LSPClient` — stdio JSON-RPC client.
- `app/tools/lsp.py` — 7 LSP tools: `lsp_hover`, `lsp_definition`, `lsp_references`, `lsp_symbol_search`, `lsp_rename`, `lsp_diagnostics`, `lsp_code_action`.
- `app/mcp/lsp_mcp.py` — MCP-сервер обёртка (для UKB в PROD).
- LSP-server support: pyright (Python), typescript-language-server (TS/JS), rust-analyzer (Rust), gopls (Go), jdtls (Java), lua-language-server (Lua).
- LSP-server modes: `in-process` (default, subprocess), `sidecar` (docker), `shared` (HTTP, FUTURE).
- File watcher (chokidar / inotify) → `textDocument/didChange` (incremental).
- Diagnostics pushed to DFC HOT (через `lsp.diagnostics` → DFC.hot).

#### 5.2.13. UKB (Unified Knowledge Bus) 🆕 (B-27 — partial, full PROD)

- `app/core/ukb/router.py::UKBRouter`.
- 5 namespaces: `lsp.*`, `oriahs.*`, `memory.*`, `code.*`, `kb.*`.
- Routing rules: explicit capability → specific namespace; default → parallel lookup all.
- In BETA: только `lsp.*` + `memory.*` (OriaHS ещё не подключён — это PROD).
- In PROD: + `oriahs.*` (через oriahs-mcp v6) + `code.*` (code-mcp v7) + `kb.*` (kb-mcp v7).
- `app/tools/ukb.py::ukb_lookup` — single retrieval tool.

#### 5.2.14. RetrievalOrchestrator 🆕 (B-28)

- `app/core/retrieval/orchestrator.py::RetrievalOrchestrator`.
- 7 strategies: `none`, `standard`, `topic_continuation`, `speculative_prefetch`, `explicit_recall`, `code_lookup`, `degraded`.
- Heuristics: referential markers, similar tokens, first turn, predictive hint.
- `decide(state)` → strategy name.
- `execute(strategy, state)` → list[RetrievedChunk].
- Integration с DFC: results → promote to HOT.
- Span-type: `retrieval.orchestrate`.

#### 5.2.15. CapabilityRegistry 🆕 (B-29)

- `app/core/tools/capability_registry.py::CapabilityRegistry`.
- Triggers: per-tool predicates (file content, language, intent).
- `filter(all_tools, context)` → active tools (8-15, not all 25+).
- Span-type: `capability.filter`.
- Metric: `orya_capability_filter_active_count` (gauge).
- LLM видит только активные инструменты per turn.

### 5.3. TRIZ-gates фазы (дополнение к v6 BETA)

| Gate | Принцип | Что встроено |
|---|---|---|
| (все gates из v6 BETA) | — | — |
| **DFC 5 слоёв** 🆕 | ТРИЗ #17 Another dimension + #15 Dynamicity | In-window context discipline |
| **Tri-Model Pipeline + Concurrent Tester** 🆕 | ТРИЗ #40 Composite + #21 Rushing + #9 Preliminary anti-action | Self-verifying loop |
| **LSP-native** 🆕 | ТРИЗ #28 Mechanics substitution + #24 Intermediary | LSP as primary code-facts source |
| **UKB** 🆕 | ТРИЗ #5 Merging + #12 Equipotentiality | Single retrieval interface |
| **RetrievalOrchestrator** 🆕 | ТРИЗ #24 Intermediary + #10 Preliminary | Policy-driven retrieval |
| **CapabilityRegistry** 🆕 | ТРИЗ #15 Dynamicity + #25 Self-service | Dynamic tool-filter |

### 5.4. Definition of Done (дополнение к v6 BETA)

- ✅ (все DoD из v6 BETA)
- ✅ DFC: `dfc.assemble_hot(plan)` возвращает cacheable prefix + dynamic suffix, ≤16K токенов на типичном ходе.
- ✅ DFC layers: HEAT (placeholder, работает в PROD), HOT (current turn), WARM (LRU), COLD (compacts), ICE (= UKB).
- ✅ BackgroundCompactor: WARM→COLD на границах ходов (async, не блокирует turn).
- ✅ Tri-Model Pipeline: planner → executor → tester (concurrent).
- ✅ Concurrent tester: abort executor при early-fail (verified через `agent.test.early_abort=true`).
- ✅ Replan bounded N=2: после 2 неудач → fallback на symbolic shortcut (PROD) или final fail.
- ✅ LSP-bus: 6 языков поддерживается (Python, TS, Rust, Go, Java, Lua).
- ✅ LSP-tools: 7 tools (`lsp_hover`, `lsp_definition`, `lsp_references`, `lsp_symbol_search`, `lsp_rename`, `lsp_diagnostics`, `lsp_code_action`).
- ✅ LSP latency: <10 ms p95 для hover/def/refs (vs `read+grep` ~100-500 ms).
- ✅ UKB Router: 5 namespaces routing (lsp, oriahs, memory, code, kb).
- ✅ `ukb.lookup(query, capability="lsp.def")` → routes to lsp-mcp.
- ✅ Default `ukb.lookup(query)` → parallel lookup all namespaces, dedupe.
- ✅ RetrievalOrchestrator: 7 strategies, decision accuracy > 75% на synthetic dataset.
- ✅ CapabilityRegistry: active tools 8-15 per turn (vs ~25+ без registry).
- ✅ `orya_capability_filter_active_count` metric exported.

### 5.5. Целевые NFR фазы (дополнение к v6 BETA)

| Параметр | Целевое значение v7 | v6 было |
|---|---|---|
| Time-to-first-token | ≤ 1000 мс (vs v6 ≤ 1200 мс) | ≤ 1200 мс |
| Tokens per turn (10-файловая задача) | 8-16 K (vs v6 30-60 K на длинной сессии) | 30-60 K |
| LSP-call latency p95 | ≤ 10 ms | — |
| Tri-Model verdict rate (pass на 1st attempt) | > 75% | — |
| Replan rate | < 20% | — |
| Symbolic Shortcut usage | 0% (появится в PROD) | — |
| UKB lookup latency p95 | ≤ 500 ms (для pre-retrieval) | — |
| RetrievalOrchestrator decision accuracy | > 75% | — |
| CapabilityRegistry: active tools per turn | 8-15 | ~15 (static) |
| Cost per session (30 ходов) | ≤ $0.30 (vs v6 $0.40) | ≤ $0.40 |
| LSP-server uptime | > 99% | — |
| Tri-Model early-abort rate | > 15% of failed turns | — |

### 5.6. Риски фазы и mitigations (дополнение к v6 BETA)

- (все риски из v6 BETA)
- **LSP-server crash на большом проекте** 🆕: auto-restart + degraded mode (read/grep fallback); workspace isolation; health-check.
- **Tri-model race condition (concurrent tester vs executor)** 🆕: immutable partial-diff snapshots; lock-free reads; abort tester на inconsistent state.
- **DFC heat cache staleness** 🆕 (placeholder — full impl в PROD): TTL 5 минут (если реализован); confidence threshold 0.6.
- **UKB routing wrong** 🆕: explicit capability parameter; rule-based routing с fallback на parallel lookup.
- **Compaction async race (DFC.compact_warm_to_cold во время executor)** 🆕: immutable snapshots; compaction на copy, swap на idle.
- **Concurrent Tester inconsistent partial diff** 🆕: abort tester; restart с final diff; lock-free snapshot reads.
- **LSP-server startup latency (10s на большом проекте)** 🆕: lazy initialization (start on first request); cache workspace state.

---

## 6. Фаза PROD — 7 power-features v7

### 6.1. Цели фазы

Доставить production-ready систему с full-stack memory (L0+L1+L2 из v6) + **7 power-features v7**:

1. **Batch Pipeline (#21)** — `prompts.yml → results.jsonl` + benchmark comparator.
2. **Symbolic Shortcut (#23)** — LLM bypass для rename/format/organize-imports.
3. **Predictive Planner (#24)** — forecast next prompt, prefetch заранее.
4. **Tournament (#25)** — N parallel executors + judge-mcp.
5. **Concurrent Tester (#26)** — overlap с executor на partial diff, early-exit (extension of BETA tri-model).
6. **RerankPolicy (#29)** — policy-driven rerank skip + fallback chain.
7. **Best-of-N (#31)** — Tree-of-Thoughts Max Mode (упрощённая версия tournament).

**Принцип PROD v7 (vs v6):** +3 недели, +13000 LOC, но закрывает **power-features gap**. Без этих 7 улучшений v7 остаётся «v6 + DFC + LSP» — хорошая, но не уникальная.

### 6.2. Компоненты фазы (дополнение к v6 PROD)

#### 6.2.1-6.2.14 (= v6 PROD — без изменений)

(см. `ROADMAP6.md` §6.2.1-6.2.14 — полностью без изменений)

#### 6.2.15. Batch Pipeline 🆕 (P-20)

- `app/batch/runner.py::BatchRunner` — `prompts.yml → results.jsonl`.
- `app/batch/comparator.py::BenchmarkComparator` — compare two `results.jsonl`.
- FastAPI endpoints: `POST /sessions/{id}/batch/run`, `POST /sessions/{id}/batch/run/async`, `GET /batch/status/{job_id}`, `GET /batch/results/{job_id}`, `POST /batch/compare`.
- CLI: `orya batch run --input prompts.yml --output results.jsonl` и `orya batch compare --current results.jsonl --baseline main/results.jsonl`.
- Parallel: `asyncio.Semaphore(parallel=4)` default.
- Output format: `results.jsonl` с `{id, status, duration_ms, tokens, cost_usd, attempts, diff, test_log}`.
- Built-in benchmark: `prompts.yml` в корне репозитория (10-20 эталонных задач).

#### 6.2.16. Symbolic Shortcut 🆕 (P-21)

- `app/core/workflow/symbolic_classifier.py::SymbolicClassifier`.
- Regex patterns + LLM-mini fallback classifier.
- Pipeline при symbolic shortcut: planner (Haiku) → `intent: symbolic` → LSP tool-call → tester verifies.
- Latency: 500-1500 ms (vs LLM-executor 2-6 s).
- Target: ~15% ходов с symbolic bypass.
- Fallback на LLM-executor если LSP rename refuted.

#### 6.2.17. Predictive Planner 🆕 (P-22)

- `app/core/workflow/predictive_planner.py::PredictivePlanner`.
- Background asyncio task, tick=1s.
- Model: Qwen-3B (local через Ollama) / Llama-3.2-1B / Haiku-3.5.
- Output: `{predicted_prompt, confidence, prefetch_hints, expected_tier}`.
- Heat Cache integration: если confidence > 0.6 → prefetch to Heat Cache.
- DPO training loop: раз в N=100 ходов, обновление weights на парах (predicted, actual).
- Metrics: `orya_predictive_planner_accuracy`, `orya_predictive_planner_miss_total`.
- Span-type: `predictive_planner.predict` (с post-hoc `prediction.match`).

#### 6.2.18. Tournament + judge-mcp 🆕 (P-23)

- `app/core/workflow/tournament.py::TournamentExecutor`.
- `app/mcp/judge_mcp.py` — отдельный MCP-сервер для judge-вызовов.
- Parallel N=3 executors (different models / temperatures).
- Judge-модель: Sonnet (small).
- Cost-aware: если `estimated_cost > max_cost_usd` (default $0.10) → degrade на single executor.
- Best-of-N (#31) — упрощённая версия без judge (выбор по criteria-match).
- Span-types: `agent.tournament`, `judge.call`.
- Metrics: `orya_tournament_total{verdict}`, `orya_tournament_cost_usd`.

#### 6.2.19. Concurrent Tester (extension of BETA tri-model) 🆕 (P-24)

- Расширение `app/core/workflow/tri_model.py::_test_concurrent_node` (из BETA).
- Early-abort executor при partial verdict = early-fail.
- Partial diff parser: detect valid diff в streaming output.
- Span-types: `agent.test.concurrent`, `agent.test.early_abort`.
- Metrics: `orya_tri_model_early_abort_total`, `orya_tri_model_verdict{verdict}`.
- Target: -30% cost на провальных ходах, -200..400 ms tester-latency.

#### 6.2.20. RerankPolicy 🆕 (P-25)

- `app/core/retrieval/rerank_policy.py::RerankPolicy`.
- Policy: identifier_lookup → skip rerank; short_query → skip; default → apply rerank with cache.
- Fallback chain: hybrid+rerank → hybrid → lexical → degraded.
- LRU cache для повторяющихся queries (target 15-30% hit rate).
- Span-types: `retrieval.rerank`, `retrieval.fallback`.
- Metrics: `orya_rerank_skip_total{reason}`, `orya_rerank_cache_hit_rate`.

#### 6.2.21. Best-of-N execution 🆕 (P-26)

- Упрощённая версия Tournament (без judge-mcp).
- N=2 parallel executors (разные temperature).
- Tester выбирает лучшего по criteria match.
- Activated когда `tier=tournament` но budget < tournament threshold.
- Span-types: `agent.best_of_n`, `agent.execute.parallel`.

### 6.3. TRIZ-gates фазы (дополнение к v6 PROD)

| Gate | Принцип | Что встроено |
|---|---|---|
| (все gates из v6 PROD) | — | — |
| **Batch Pipeline** 🆕 | ТРИЗ #19 Periodic + #25 Self-service | CI-benchmark + self-improvement feedback |
| **Symbolic Shortcut** 🆕 | ТРИЗ #16 Partial effect + #21 Rushing | LLM bypass для детерминированных задач |
| **Predictive Planner + Heat Cache** 🆕 | ТРИЗ #10 Preliminary + #11 Beforehand | Forecast next prompt, prefetch заранее |
| **Tournament + judge-mcp** 🆕 | ТРИЗ #40 Composite + #22 Convert harm | Quality-tournament, latency=max(N) |
| **Concurrent Tester** 🆕 | ТРИЗ #21 Rushing + #15 Dynamicity | Overlap с executor, early-exit |
| **RerankPolicy** 🆕 | ТРИЗ #11 Beforehand + #35 Parameter changes | Policy-driven rerank skip + fallback |
| **Best-of-N execution** 🆕 | ТРИЗ #21 Rushing + #16 Partial | Parallel N executors, criteria-match selection |

### 6.4. Definition of Done (дополнение к v6 PROD)

- ✅ (все DoD из v6 PROD)
- ✅ Batch Pipeline: `orya batch run --input prompts.yml --output results.jsonl` работает, 20 эталонных задач.
- ✅ BenchmarkComparator: `orya batch compare` показывает diff в latency/cost/pass-rate между двумя results.jsonl.
- ✅ `POST /sessions/{id}/batch/run/async` — возвращает `job_id`, статус через `/batch/status/{job_id}`.
- ✅ Symbolic Shortcut: 15% ходов с `intent: symbolic` (target); fallback на LLM-executor при LSP failure.
- ✅ `orya_symbolic_shortcut_usage` metric: ~15%.
- ✅ Predictive Planner: background task запущен, accuracy > 60% после 2 недель.
- ✅ Heat Cache hit rate > 50%.
- ✅ Tournament: `tier=tournament` эмитится planner'ом, 3 parallel executors, judge выбирает.
- ✅ Tournament cost-aware: `estimated_cost > max_cost_usd` → degrade на single executor.
- ✅ Concurrent Tester: early-abort rate > 15% на провальных ходах.
- ✅ RerankPolicy: skip rerank для identifier_lookup; fallback chain работает.
- ✅ Best-of-N: активируется когда tier=tournament но budget < threshold; N=2 parallel.
- ✅ Все новые span-types экспортируются в Prometheus.
- ✅ Все новые metrics на Grafana dashboard.

### 6.5. Целевые NFR фазы (дополнение к v6 PROD)

| Параметр | Целевое значение v7 | v6 было |
|---|---|---|
| Time-to-first-token | ≤ 800 мс (vs v6 ≤ 1000 мс) | ≤ 1000 мс |
| Latency p95 (поиск по проекту) | ≤ 3 s (vs v6 ~5 s) | ~5 s |
| Tokens per turn (avg) | 6-16 K (vs v6 30-60 K на длинной сессии) | 30-60 K |
| Cost per session (30 ходов) | ≤ $0.20 (vs v6 $0.30) | ≤ $0.30 |
| Symbolic Shortcut usage | ~15% | 0% |
| Predictive Planner accuracy | > 60% (after 2 weeks) | n/a |
| Heat Cache hit rate | > 50% | n/a |
| Tournament win-rate | > 80% | n/a |
| Concurrent Tester early-abort rate (failed turns) | > 15% | n/a |
| Batch throughput (prompts/hour) | 100-400 (vs v6 n/a) | n/a |
| Batch pass-rate | > 80% | n/a |
| RerankPolicy skip rate | 30-50% of retrievals | 0% |
| Best-of-N activation rate | 5-10% of tournament prompts | n/a |

### 6.6. Риски фазы и mitigations (дополнение к v6 PROD)

- (все риски из v6 PROD)
- **Batch-runner memory leak (50 промптов в parallel)** 🆕: semaphore для parallelism (default 4); process isolation per batch.
- **Tournament cost blow-up** 🆕: cost-aware judge; max_cost_usd env-variable; degrade на single при превышении.
- **Predictive Planner false-positive** 🆕: confidence threshold 0.6; DPO-обучение на miss; `predictive_planner_miss` metric.
- **Symbolic Shortcut mismatch** 🆕: tester верифицирует; fallback на LLM-executor при failure; manual review log.
- **Multi-agent tournament disagreement (N=3, ни один не pass)** 🆕: replan с ужесточёнными критериями; bounded N=2 retries; fallback на symbolic shortcut.
- **LSP rename refuted (LSP не нашёл references)** 🆕: fallback на LLM-executor; manual review log.
- **RerankPolicy cache pollution** 🆕: TTL 5 min; LRU eviction; invalidate на memory updates.
- **Best-of-N inconsistent criteria match** 🆕: deterministic criteria-match function; tie-break by executor.model preference.

---

## 7. Фаза EXTENSION-PROD — масштабирование (+ опционально WASM-LSP)

### 7.1. Цели фазы (дополнение к v6 EXTENSION-PROD)

(см. v6 §7.1 + новые)

В v7 EXTENSION-PROD добавляет опционально:

- **Multi-instance memory replication** (v6 E-11) — без изменений.
- **🆕 (опционально) WASM-LSP** — компиляция ключевых LSP-серверов в WASM, запуск in-process (без subprocess overhead). Целевая latency LSP: <0.1 ms (vs stdio ~10 ms).
  - Активируется только если: (a) Rust LSP-сервер (rust-analyzer) имеет WASM-порт, (b) user explicitly opts-in через `LSP_MODE=wasm`.
  - Default — stdio (BETA baseline).

### 7.2. Triggers для EXTENSION-PROD (см. §19)

---

## 8. Фаза FUTURE — автономность + continuous prompt-learning + FUTURE7

### 8.1. Цели фазы (дополнение к v6 FUTURE)

(см. v6 §8.1 + новые)

В v7 FUTURE добавляет:

- **Continuous prompt-learning** (v6 F-09) — без изменений.
- **🆕 Все направления из `FUTURE7.md`**:
  - Continuous Planner daemon (если neuromorphic inference созрел).
  - Predictive User Model K=3.
  - Task Embedding Index для nearest-neighbor lookup.
  - Adaptive Compute / continuous triage.
  - Federated Predictive Planner.
  - Quantum-style superposition executor (мысл-эксперимент).
  - Incremental LLM (generate only diff tokens).
  - Sub-millisecond LSP через WASM (если не сделано в EXTENSION-PROD).
  - Hierarchical Predictive Prefetch (entire dependency tree).
  - Continuous prompt-learning с multi-agent memory sharing.
  - Cross-user memory sharing (privacy-preserving).

(Подробности — см. `FUTURE7.md`)

---

## 9. Сводная матрица фаз × компонентов v7

| Компонент | MVP | ALPHA | BETA | PROD | EXT-PROD | FUTURE |
|---|---|---|---|---|---|---|
| (все компоненты v6 — см. `ROADMAP6 §9`) | ✅/—/✅/✅/✅/✅ по фазам | | | | | |
| **DFC (HEAT/HOT/WARM/COLD/ICE)** | — | — | ✅ | ✅ | multi-instance | continuous |
| **Tri-Model Pipeline** | — | — | ✅ | ✅ (concurrent tester) | — | — |
| **LSP-native (lsp-mcp + 7 tools)** | — | — | ✅ | ✅ | WASM-LSP | — |
| **UKB Router** | — | — | ✅ (partial: lsp+memory) | ✅ (full) | multi-instance | task-embedding |
| **RetrievalOrchestrator** | — | — | ✅ | ✅ (rerank policy) | — | — |
| **CapabilityRegistry** | — | — | ✅ | ✅ | — | — |
| **TieredModelRouter** | — | ✅ | ✅ | ✅ | — | — |
| **PromptCacheLayout** | — | ✅ | ✅ | ✅ | — | — |
| **ConnectionPool** | — | ✅ | ✅ | ✅ | — | — |
| **Batch Pipeline** | — | — | — | ✅ | — | self-improvement |
| **Symbolic Shortcut** | — | — | — | ✅ | — | — |
| **Predictive Planner + Heat Cache** | — | — | — | ✅ | — | Predictive User Model K=3 |
| **Tournament + judge-mcp** | — | — | — | ✅ | — | quantum-style |
| **Concurrent Tester** | — | — | (basic) | ✅ | — | adaptive compute |
| **RerankPolicy** | — | — | — | ✅ | — | — |
| **Best-of-N** | — | — | — | ✅ | — | — |
| **BackgroundCompactor (context)** | — | — | ✅ | ✅ | — | — |
| **L1 SQLiteStore (v6)** | — | — | ✅ | ✅ | multi-instance | — |
| **L2 Qdrant (v6)** | — | — | — | ✅ | multi-instance | — |
| **OryaObservability SDK (v6)** | basic | ✅ | ✅ | ✅ distributed | — | — |
| **Sampler-proxy (v6)** | — | ✅ | ✅ | ✅ | — | — |
| **/learn, /memory (v6)** | ✅ | ✅ | ✅ | ✅ | — | continuous |

---

## 10. Карта зависимостей между фазами v7

```
MVP v7 (= v6 MVP):
  (без изменений от v6 MVP)

ALPHA v7 (3 недели, +0.5 недели от v6 ALPHA):
  v6 ALPHA done → A-18 (TieredModelRouter) → A-19 (PromptCacheLayout) → A-20 (ConnectionPool)
  A-13 (CostAwareRouter v6) → A-18 (TieredModelRouter extends)
  A-04 (observability baseline v6) → A-19 (PromptCacheLayout cache_hit span attribute)

BETA v7 (7 недель, +2 недели от v6 BETA):
  v6 BETA done + A-18 (TieredModelRouter) → B-24 (DFC) → B-25 (Tri-Model Pipeline uses DFC.hot)
  B-26 (LSP-native) → independent (parallel с B-24/B-25)
  B-24 (DFC) + B-26 (LSP) → B-27 (UKB partial: lsp+memory)
  B-24 (DFC) + B-27 (UKB partial) → B-28 (RetrievalOrchestrator uses UKB)
  B-24 (DFC) → B-29 (CapabilityRegistry filters tools for DFC.hot)

PROD v7 (9 недель, +3 недели от v6 PROD):
  v6 PROD done + B-25 (Tri-Model) → P-24 (Concurrent Tester extension)
  B-25 (Tri-Model) + B-26 (LSP) → P-21 (Symbolic Shortcut uses LSP)
  B-24 (DFC) + B-25 (Tri-Model) → P-22 (Predictive Planner warms Heat Cache)
  B-25 (Tri-Model) → P-23 (Tournament = N parallel tri-model pipelines)
  v6 P-05 (OriaHS search) + B-27 (UKB) → P-25 (RerankPolicy extends UKB retrieval)
  P-23 (Tournament) → P-26 (Best-of-N = simplified tournament)
  v6 P-00 (OriaHS) + B-25 (Tri-Model) → P-20 (Batch Pipeline runs tri-model in parallel)

EXTENSION-PROD v7 (по triggers):
  v6 EXTENSION-PROD done + P-22 (Predictive Planner) → E-12 (Predictive User Model K=3, опц.)
  v6 E-11 (multi-instance memory) → E-13 (multi-instance DFC sync, опц.)
  B-26 (LSP stdio) → E-14 (WASM-LSP, опц.)

FUTURE v7 (не ограничено):
  PROD done + eval-metrics stable → F-09 (continuous prompt-learning, v6)
  PROD done + P-22 (Predictive Planner) → F-10 (Continuous Planner daemon)
  PROD done + P-20 (Batch) → F-11 (Task Embedding Index)
  см. FUTURE7.md для полного списка
```

---

## 11. Критерии перехода между фазами (exit criteria, delta от v6)

### 11.1. MVP → ALPHA (= v6)

(см. `ROADMAP6 §11.1` — без изменений)

### 11.2. ALPHA → BETA (дополнение к v6)

- ✅ (все exit-criteria из v6 ALPHA → BETA)
- ✅ TieredModelRouter: `select(tier=...)` работает для small/large/tournament.
- ✅ PromptCacheLayout: prompt-cache hit rate > 40% (provider-side metric).
- ✅ ConnectionPool: cold-start latency ≤ 200 ms (vs без pool ~1000 ms).

### 11.3. BETA → PROD (дополнение к v6)

- ✅ (все exit-criteria из v6 BETA → PROD)
- ✅ DFC: tokens per turn ≤ 16K на типичном ходе (vs v6 30-60K).
- ✅ Tri-Model Pipeline: verdict rate (pass на 1st attempt) > 75%.
- ✅ LSP-native: 6 языков поддерживается, latency < 10 ms p95.
- ✅ UKB: 5 namespaces routing (lsp, oriahs, memory, code, kb).
- ✅ RetrievalOrchestrator: 7 strategies, decision accuracy > 75%.
- ✅ CapabilityRegistry: active tools per turn ≤ 15 (vs ~25+ без registry).

### 11.4. PROD → EXTENSION-PROD (дополнение к v6)

- ✅ (все exit-criteria из v6 PROD → EXTENSION-PROD)
- ✅ Batch Pipeline: 20 эталонных задач в `prompts.yml`, pass-rate > 80%.
- ✅ Symbolic Shortcut: ~15% ходов с `intent: symbolic`, fallback работает.
- ✅ Predictive Planner: accuracy > 60% (after 2 weeks).
- ✅ Tournament: cost-aware degrade работает (verified через `tournament.degraded=true` span).
- ✅ Concurrent Tester: early-abort rate > 15% на провальных ходах.
- ✅ RerankPolicy: skip rate 30-50% of retrievals.

### 11.5. EXTENSION-PROD → FUTURE (= v6 + FUTURE7 reference)

(см. v6 §11.5 + см. `FUTURE7.md`)

---

## 12. TRIZ-gates по фазам (полная карта v7)

| Gate | MVP | ALPHA | BETA | PROD | EXT-PROD | FUTURE |
|---|---|---|---|---|---|---|
| (все gates из v6 §12) | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| **TieredModelRouter** 🆕 | — | ✅ | ✅ | ✅ | — | — |
| **PromptCacheLayout** 🆕 | — | ✅ | ✅ | ✅ | — | — |
| **ConnectionPool** 🆕 | — | ✅ | ✅ | ✅ | — | — |
| **DFC 5 слоёв** 🆕 | — | — | ✅ | ✅ | multi-instance | continuous |
| **Tri-Model Pipeline** 🆕 | — | — | ✅ | ✅ (concurrent) | — | — |
| **LSP-native** 🆕 | — | — | ✅ | ✅ | WASM | — |
| **UKB Router** 🆕 | — | — | ✅ (partial) | ✅ (full) | multi-instance | task-embedding |
| **RetrievalOrchestrator** 🆕 | — | — | ✅ | ✅ | — | — |
| **CapabilityRegistry** 🆕 | — | — | ✅ | ✅ | — | — |
| **Batch Pipeline** 🆕 | — | — | — | ✅ | — | self-improvement |
| **Symbolic Shortcut** 🆕 | — | — | — | ✅ | — | — |
| **Predictive Planner + Heat Cache** 🆕 | — | — | — | ✅ | — | K=3 model |
| **Tournament + judge-mcp** 🆕 | — | — | — | ✅ | — | quantum-style |
| **Concurrent Tester** 🆕 | — | — | (basic) | ✅ | — | adaptive compute |
| **RerankPolicy** 🆕 | — | — | — | ✅ | — | — |
| **Best-of-N** 🆕 | — | — | — | ✅ | — | — |
| **BackgroundCompactor (context)** 🆕 | — | — | ✅ | ✅ | — | — |

---

## 13. NFR-таргеты по фазам (v7)

| NFR | MVP | ALPHA | BETA | PROD | EXT-PROD | FUTURE |
|---|---|---|---|---|---|---|
| Time-to-first-token | ≤ 1300 ms | ≤ 600 ms | ≤ 1000 ms | ≤ 800 ms | ≤ 800 ms | ≤ 500 ms |
| Latency p95 (поиск по проекту) | — | — | ≤ 5 s | ≤ 3 s | ≤ 3 s | ≤ 2 s |
| Tokens per turn (avg) | 30-60 K | 30-60 K | 8-16 K | 6-16 K | 6-16 K | 4-12 K |
| Cost per session (30 ходов) | ≤ $0.45 | ≤ $0.40 | ≤ $0.30 | ≤ $0.20 | ≤ $0.20 | ≤ $0.15 |
| Prompt-cache hit rate | — | > 40% | > 60% | > 85% | > 85% | > 90% |
| Connection-pool hit rate | — | > 95% | > 95% | > 95% | > 95% | > 95% |
| LSP-call latency p95 | — | — | ≤ 10 ms | ≤ 10 ms | ≤ 0.1 ms (WASM) | ≤ 0.1 ms |
| Tri-Model verdict rate (pass на 1st) | — | — | > 75% | > 80% | > 80% | > 85% |
| Replan rate | — | — | < 20% | < 15% | < 15% | < 10% |
| Symbolic Shortcut usage | 0% | 0% | 0% | ~15% | ~15% | ~20% |
| Predictive Planner accuracy | n/a | n/a | n/a | > 60% (after 2 weeks) | > 70% | > 80% |
| Heat Cache hit rate | n/a | n/a | n/a | > 50% | > 60% | > 70% |
| Tournament win-rate | n/a | n/a | n/a | > 80% | > 80% | > 85% |
| Concurrent Tester early-abort rate (failed) | n/a | n/a | (basic) | > 15% | > 20% | > 25% |
| Batch throughput (prompts/hour) | n/a | n/a | n/a | 100-400 | 100-400 | 400-1000 |
| Batch pass-rate | n/a | n/a | n/a | > 80% | > 80% | > 85% |
| UKB lookup latency p95 | n/a | n/a | ≤ 500 ms (pre-retrieval) | ≤ 200 ms (heat-prefetched) | ≤ 200 ms | ≤ 100 ms |
| RetrievalOrchestrator decision accuracy | n/a | n/a | > 75% | > 80% | > 80% | > 85% |
| CapabilityRegistry: active tools per turn | ~15 | ~15 | 8-15 | 8-15 | 8-15 | 5-12 |
| RerankPolicy skip rate | 0% | 0% | 0% | 30-50% | 30-50% | 40-60% |
| Memory-retrieval latency (hybrid L1+L2) | — | — | ≤ 200 ms p95 | ≤ 200 ms p95 | ≤ 200 ms p95 | ≤ 100 ms p95 |
| Memory-search recall@10 (offline-eval) | — | — | — | > 0.85 | > 0.85 | > 0.90 |
| learn_reuse_rate (30-day) | — | — | — | > 30% | > 30% | > 50% |
| Trace-completeness | — | > 90% | > 90% | > 95% | > 95% | > 95% |
| Multi-instance memory sync lag | — | — | — | — | ≤ 5 минут | ≤ 1 минута |

---

## 14. Риски и mitigations (delta от v6)

(см. v6 §14 + новые риски v7)

### 14.1. Новые риски v7 (по фазам)

| Риск | Фаза | Mitigation |
|---|---|---|
| Prompt-cache invalidation при tool-registry changes | ALPHA | `prompt_cache:prefix_hash` в Redis; invalidate при tool-schemas changes |
| ConnectionPool leak | ALPHA | max_pool_size=4; LRU eviction; periodic health-check |
| TieredModelRouter race condition | ALPHA | emit tier до возврата model, не после |
| LSP-server crash на большом проекте | BETA | auto-restart + degraded mode (read/grep fallback); workspace isolation |
| Tri-model race condition (concurrent tester vs executor) | BETA | immutable partial-diff snapshots; lock-free reads; abort на inconsistent |
| DFC heat cache staleness (placeholder) | BETA | TTL 5 минут (если реализован); confidence threshold 0.6 |
| UKB routing wrong | BETA | explicit capability parameter; rule-based routing с fallback на parallel |
| Compaction async race | BETA | immutable snapshots; compaction на copy, swap на idle |
| Concurrent Tester inconsistent partial diff | BETA | abort tester; restart с final diff; lock-free snapshot reads |
| LSP-server startup latency (10s на большом проекте) | BETA | lazy initialization; cache workspace state |
| Batch-runner memory leak (50 промптов в parallel) | PROD | semaphore (default 4); process isolation per batch |
| Tournament cost blow-up | PROD | cost-aware judge; max_cost_usd env-variable; degrade на single |
| Predictive Planner false-positive | PROD | confidence threshold 0.6; DPO-обучение на miss |
| Symbolic Shortcut mismatch | PROD | tester верифицирует; fallback на LLM-executor; manual review |
| Multi-agent tournament disagreement | PROD | replan с ужесточёнными критериями; bounded N=2 retries; fallback на symbolic |
| LSP rename refuted | PROD | fallback на LLM-executor; manual review log |
| RerankPolicy cache pollution | PROD | TTL 5 min; LRU eviction; invalidate на memory updates |
| Best-of-N inconsistent criteria match | PROD | deterministic criteria-match function; tie-break by model preference |

---

## 15. Метрики прогресса внедрения v7

### 15.1. Новые метрики v7 (дополнение к v6)

| Метрика | MVP | ALPHA | BETA | PROD |
|---|---|---|---|---|
| DFC hot size (tokens) | — | — | tracked | tracked |
| DFC heat hit rate | — | — | (placeholder) | tracked |
| DFC compaction count | — | — | tracked | tracked |
| LSP call count | — | — | tracked | tracked |
| LSP latency | — | — | ≤ 10 ms p95 | ≤ 10 ms p95 |
| LSP server uptime | — | — | tracked | tracked |
| UKB lookup count | — | — | tracked | tracked |
| UKB lookup latency | — | — | ≤ 500 ms | ≤ 200 ms |
| Tri-Model verdict rate | — | — | tracked | tracked |
| Tri-Model early-abort rate | — | — | (basic) | tracked |
| Symbolic shortcut usage | — | — | — | ~15% |
| Tournament count | — | — | — | tracked |
| Tournament cost | — | — | — | tracked |
| Predictive planner accuracy | — | — | — | > 60% |
| Heat cache hit rate | — | — | — | > 50% |
| Batch run count | — | — | — | tracked |
| Batch pass rate | — | — | — | > 80% |
| Prompt cache hit rate | — | > 40% | > 60% | > 85% |
| Connection pool hit rate | — | > 95% | > 95% | > 95% |
| Capability filter active count | — | — | tracked | tracked |
| Rerank skip rate | — | — | — | 30-50% |
| Tiered router tier distribution | — | tracked | tracked | tracked |

---

## 16. UI-стратегия по фазам (delta от v6)

(см. v6 §16 + новые)

### 16.1. Изменения v7

| Фаза | Что нового в UI |
|---|---|
| MVP | (= v6 MVP) |
| ALPHA | (= v6 ALPHA) + tier indicator (small/large/tournament), cache hit indicator |
| BETA | Next.js: DFC inspector (HEAT/HOT/WARM/COLD/ICE видимость), LSP-server status panel, capability filter view, retrieval strategy indicator |
| PROD | Next.js: tournament progress (N parallel executors live), symbolic shortcut indicator, predictive planner confidence indicator, batch runner CLI + dashboard |
| EXTENSION-PROD | Next.js: multi-instance DFC sync indicator, WASM-LSP indicator (если активирован) |
| FUTURE | Next.js: continuous prompt-learning A/B results, predictive user model visualization, task embedding search panel |

---

## 17. Fast-track paths (дополнение к v6)

### 17.1-17.3. Fast-track paths из v6 (сохраняются)

(см. v6 §17.1-17.3 — memory-only, observability-only)

### 17.4. Новый fast-track: speed-only 🆕

Для пользователей, которым нужен кодинг-агент с максимальной скоростью, но без full memory-layer + observability stack.

```
MVP (базовый L0 memory) → ALPHA (TieredModelRouter + PromptCacheLayout + ConnectionPool) → BETA (DFC + Tri-Model + LSP-native + UKB + RetrievalOrchestrator + CapabilityRegistry) → stop (before PROD)
```

- ❌ No L1/L2 memory (только L0 MD-файлы для /learn).
- ❌ No OryaObservability SDK (basic Langfuse env).
- ❌ No sampler-proxy.
- ❌ No OriaHS.
- ❌ No Batch, Symbolic, Predictive, Tournament, Concurrent Tester, RerankPolicy.
- ✅ DFC + Tri-Model + LSP + UKB + RetrievalOrchestrator + CapabilityRegistry.
- ✅ Latency p50 < 1s на типичных code-задачах.

**Use-case:** single-user code-агент на локальной машине, где нужна максимальная скорость и минимум инфраструктуры.

### 17.5. Новый fast-track: benchmark-only 🆕

Для CI/CD pipeline, где нужен только batch-runner.

```
MVP (базовый L0 memory) → BETA (DFC + Tri-Model, без LSP/UKB) → PROD (Batch Pipeline only) → stop
```

- ❌ No LSP, UKB, RetrievalOrchestrator, CapabilityRegistry (если не нужно retrieval).
- ❌ No observability stack.
- ❌ No memory L1/L2.
- ✅ Batch Pipeline + Tri-Model + DFC.
- ✅ `orya batch run --input prompts.yml --output results.jsonl` работает.

**Use-case:** CI-benchmark для собственного развития агента.

---

## 18. Rollback-процедуры между фазами (delta от v6)

(см. v6 §18 + дополнения)

### 18.1. Rollback PROD → BETA (новое в v7)

Откатывание power-features v7 (Batch, Symbolic, Predictive, Tournament, Concurrent Tester, RerankPolicy, Best-of-N):

- Отключить через env-переменные:
  - `BATCH_RUNNER_ENABLED=false`
  - `SYMBOLIC_SHORTCUT_ENABLED=false`
  - `PREDICTIVE_PLANNER_ENABLED=false`
  - `TOURNAMENT_ENABLED=false`
  - `CONCURRENT_TESTER_ENABLED=false` (вернуться к sequential tester)
  - `RERANK_POLICY_ENABLED=false` (вернуться к always-rerank)
  - `BEST_OF_N_ENABLED=false`
- Все v7 PROD features — feature-flagged, могут быть отключены без кода изменений.
- DFC + Tri-Model + LSP + UKB (BETA features) остаются включёнными.

### 18.2. Rollback BETA → ALPHA (новое в v7)

- Отключить DFC: `DFC_ENABLED=false` (вернуться к v6 ContextManager last-N + truncate).
- Отключить Tri-Model: `TRI_MODEL_ENABLED=false` (вернуться к single LLM-call).
- Отключить LSP: `LSP_ENABLED=false` (вернуться к read+grep+OriaHS).
- Отключить UKB: `UKB_ENABLED=false` (вернуться к отдельным memory_search / oriahs_search tools).
- Отключить RetrievalOrchestrator: `RETRIEVAL_ORCHESTRATOR_ENABLED=false`.
- Отключить CapabilityRegistry: `CAPABILITY_REGISTRY_ENABLED=false` (вернуться к static tool-list).

### 18.3. Rollback ALPHA → MVP (новое в v7)

- Отключить TieredModelRouter: `TIERED_ROUTER_ENABLED=false` (вернуться к CostAwareRouter v6).
- Отключить PromptCacheLayout: `PROMPT_CACHE_ENABLED=false`.
- Отключить ConnectionPool: `CONNECTION_POOL_ENABLED=false`.

---

## 19. Triggers для EXTENSION-PROD (уточнённые в v7)

(см. v6 §19 + дополнения)

### 19.1. Triggers из v6 (сохраняются)

- (см. v6 §19 — multi-tenant, multi-instance, semantic memory)

### 19.2. Новые triggers v7

- **Multi-instance DFC sync need**: 2+ OryaAgent instances на одной БД → нужна multi-instance DFC sync (Heat Cache + HOT sync через OriaHS).
- **WASM-LSP demand**: если stdio LSP latency (~10 ms) недостаточна для high-frequency LSP calls (>100 per turn), активировать WASM-LSP research track.
- **Predictive Planner accuracy plateau**: если accuracy стагнирует на ~60% более 4 недель → активировать Predictive User Model K=3 research (FUTURE+).

---

## 20. Deprecation mechanism (дополненный в v7)

(см. v6 §20 + дополнения)

### 20.1. Deprecated в v7

| Что | Когда | Замена |
|---|---|---|
| Langfuse direct (`LANGFUSE_HOST=http://langfuse:3000`) | ALPHA v6 | sampler-proxy (`LANGFUSE_HOST=http://sampler-proxy:4321`) |
| B-00 Memory via PostgresStore (v6 B-00 REMOVED) | BETA v6 | L0 MD + L1 SQLiteStore + L2 Qdrant |
| **CostAwareRouter v6 (как primary router)** 🆕 | ALPHA v7 | TieredModelRouter v7 (расширяет CostAwareRouter, не заменяет) |
| **CacheWrapper без prompt-cache** 🆕 | ALPHA v7 | CacheWrapper + PromptCacheLayout (для cross-turn prefix) |
| **Static tool-list** 🆕 | BETA v7 | CapabilityRegistry (dynamic per turn) |
| **Single LLM-call per turn** 🆕 | BETA v7 | Tri-Model Pipeline (plan → execute → test) |
| **read+grep как primary code-facts** 🆕 | BETA v7 | LSP-native (#20) — primary, read/grep — fallback |
| **Sequential tester** 🆕 | PROD v7 | Concurrent Tester (#26) — overlap с executor |
| **Always-rerank** 🆕 | PROD v7 | RerankPolicy (#29) — policy-driven skip |

### 20.2. Deprecation timeline v7

- **ALPHA v7**: deprecate `LANGFUSE_HOST=langfuse-direct` → sampler-proxy (в v6 уже начато, v7 завершает).
- **BETA v7**: deprecate static tool-list → CapabilityRegistry; deprecate single LLM-call → Tri-Model; deprecate read+grep → LSP-native.
- **PROD v7**: deprecate sequential tester → Concurrent Tester; deprecate always-rerank → RerankPolicy.

---

## 21. LSP integration track (новое в v7)

Это отдельный трек интеграции LSP-серверов, параллельный основным фазам:

### 21.1. Этапы LSP integration

| Этап | Фаза | Что | LOC |
|---|---|---|---|
| LSP-1 | BETA | LSP-bus + 6 LSP-servers (pyright, typescript-ls, rust-analyzer, gopls, jdtls, lua-ls) | ~1500 |
| LSP-2 | BETA | 7 LSP-tools (hover, def, refs, symbol_search, rename, diagnostics, code_action) | ~700 |
| LSP-3 | BETA | lsp-mcp (MCP-обёртка для UKB) | ~500 |
| LSP-4 | BETA | File watcher → didChange (incremental) | ~200 |
| LSP-5 | PROD | LSP-server health-checks + auto-restart | ~200 |
| LSP-6 | EXTENSION-PROD (опц.) | WASM-LSP ports (rust-analyzer, typescript) | ~500 |

### 21.2. LSP-server coverage matrix

| Language | LSP-server | BETA | PROD | EXT-PROD (WASM) |
|---|---|---|---|---|
| Python | pyright | ✅ | ✅ | — |
| TypeScript / JavaScript | typescript-language-server | ✅ | ✅ | ✅ (WASM port exists) |
| Rust | rust-analyzer | ✅ | ✅ | ✅ (WASM port exists) |
| Go | gopls | ✅ | ✅ | — |
| Java | jdtls | ✅ | ✅ | — |
| Lua | lua-language-server | ✅ | ✅ | — |
| C/C++ | clangd | — | (FUTURE) | — |
| C# | OmniSharp | — | (FUTURE) | — |
| Ruby | solargraph | — | (FUTURE) | — |

### 21.3. LSP-server deployment modes

(см. `ARCHITECT7 §13.2` — in-process / sidecar / shared)

---

## 22. Batch-runner integration track (новое в v7)

Это отдельный трек интеграции batch-runner, параллельный основным фазам:

### 22.1. Этапы Batch integration

| Этап | Фаза | Что | LOC |
|---|---|---|---|
| BATCH-1 | PROD | BatchRunner core (prompts.yml → results.jsonl) | ~500 |
| BATCH-2 | PROD | BenchmarkComparator (compare two results.jsonl) | ~100 |
| BATCH-3 | PROD | FastAPI endpoints (/batch/run, /batch/run/async, /batch/status, /batch/results, /batch/compare) | ~300 |
| BATCH-4 | PROD | CLI (`orya batch run`, `orya batch compare`) | ~100 |
| BATCH-5 | PROD | Built-in benchmark (prompts.yml в репозитории, 10-20 эталонных задач) | ~200 (тесты) |
| BATCH-6 | PROD | Parallel execution with semaphore | (часть BATCH-1) |
| BATCH-7 | FUTURE | Task Embedding Index (nearest-neighbor lookup для self-improvement) | — |

### 22.2. Built-in benchmark scope

`prompts.yml` в репозитории включает:
- 5 простых задач (single file edit, format, rename).
- 5 средних задач (multi-file refactor, add test, fix bug).
- 5 сложных задач (extract class, introduce design pattern, full feature impl).
- 5 cross-project задач (для UKB retrieval testing).

Каждая задача имеет: `id`, `prompt`, `criteria` (list), `expected` (string, optional).

---

*Конец документа ROADMAP7.md*