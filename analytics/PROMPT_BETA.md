# ПРОМПТ ФАЗЫ BETA — OryaAgent v7

> **Версия промпта:** 7.0
> **Дата:** 20 октября 2026
> **Источники:** `ARCHITECT7.md` v7.0 (§3 #18, #19, #20, #22, #27, #28; §6.1-6.4, §6.7-6.8, §6.11-6.12; §7; §8; §14.2; §16.1), `ROADMAP7.md` v7.0 (§5, §11.3, §13), `BACKLOG7.md` v7.0 (§4 — B-24..B-29), `BACKLOG6.md` v6.0 (§4 — B-00..B-23), `ROADMAP6.md` v6.0 (§5), ADR-0001 (DFC), ADR-0002 (LSP-native), ADR-0003 (Tri-Model), ADR-0010 (Background compaction), ADR-v02-004 (Retrieval orchestrator), ADR-v02-007 (Tool discovery), ADR-v03-100 (UKB)
> **Стек:** Python 3.11+, LangChain 0.3+, LangGraph 0.2+, FastAPI, PostgreSQL 16, Redis 7, Chainlit, Next.js, OriaHS, OryaObservability SDK, **LSP-серверы** (pyright, typescript-language-server, rust-analyzer, gopls, jdtls, lua-language-server, `vscode-css-languageserver`/`vscode-html-languageserver` — FUTURE+ в PROD), `watchdog` (file watcher), MCP SDK, per-language toolchains (`mvn`/`cargo`/`go`/`npm`/`pnpm`), `google-java-format`/`rustfmt`/`gofmt`/`prettier`, `checkstyle`/`clippy`/`govet`/`eslint`/`axe-core`
> **Длительность:** 7 недель (поверх готового ALPHA)
> **Объём кода:** ~13000 LOC (v6 BETA ~8000 + 5000 новых v7)
> **Статус в v7:** BETA = v6 BETA + 6 новых архитектурных примитивов (DFC, Tri-Model, LSP-native, UKB, RetrievalOrchestrator, CapabilityRegistry) + per-language-capability layer (B-30: `agent_program(language, task)` + 5 skill-bundles Java/Rust/Go/JS/Frontend + per-language hooks)

---

## Промпт (ранний, приоритетный): Бесшовная работа с лимитами рекурсии — без ошибок в интерфейсе

> **Источник паттерна:** `anomalyco/opencode` — `packages/core/src/session/runner/llm.ts` (§252-272), `packages/core/src/session/runner/max-steps.ts`, `packages/core/src/tool/plugin/subagent.ts` (§123-139), `packages/core/src/model-retry.ts`. Этот промпт имеет приоритет над любыми последующими инструкциями, описывающими обработку лимитов итераций/рекурсии в BETA.

### Постулат

При срабатывании лимита итераций, глубины подагентов или retry-бюджета **никогда не выбрасывай ошибку в интерфейс пользователя**. В UI (Chainlit и Next.js) остановка должна восприниматься как естественное завершение хода модели, а не как сбой. Никаких красных баннеров, toast-уведомлений об ошибках, модальных окон или stack-trace — только обычный текстовый ответ ассистента.

### Принцип 1. Soft-nudge на шаге цикла агента (вместо исключения)

Когда `step >= agent.steps` (лимит итераций в текущей сессии), НЕ прерывай ход и НЕ показывай в UI сообщение об ошибке. Вместо этого:

1. Тихо инжектируй в транскрипт ассистентское сообщение `MAX_STEPS_PROMPT` — директиву вида: «достигнут максимум шагов для этого агента, инструменты отключены до следующего ввода пользователя, отвечай ТОЛЬКО текстом — итог по работе, что сделано, что осталось, рекомендации дальше».
2. Установи `tool_choice = "none"` на этом запросе к модели — инструменты физически недоступны на финальном шаге, LLM вынуждена выдать текстовый итоговый ответ, а не пытаться продолжить рекурсию.
3. Сохрани `tools` в определениях запроса (это сохраняет cache-prefix провайдера и не ломает контракт), но не разрешай их вызов.
4. Результат: в UI виден обычный финальный ответ ассистента, как если бы модель сама решила завершиться.

`StepFailedError` использовать **только** для truly-fatal случаев: output-limit исчерпан после двух продолжений подряд, compaction failed irrecoverably. Лимит шагов — НЕ fatal, а нормальное завершение.

### Принцип 2. Глубина подагентов — soft `ToolFailure`, не hard error

Глубина вложенных подагентов (`subagent_depth`, default = 1) проверяется **только в момент спавна** через `parentID`-walk по дереву сессий. При `depth >= limit`:

- Возвращай `ToolFailure` с сообщением вида `Subagent depth limit reached (${limit}). Increase "experimental.subagent_depth" to allow nested subagents.` — это **мягкая ошибка инструмента**, которую LLM воспринимает как обычный tool-result (видит сообщение, перепланирует, выбирает другую стратегию), а не как фатальный сбой сессии.
- Каждый спавн подагента создаёт **дочернюю сессию с собственным счётчиком шагов, сброшенным в 1** — лимит итераций родителя НЕ наследуется. Ребёнок может выполнить полный цикл шагов заново. Это и есть «бесшовный обход» рекурсии: формально цепочка обрывается на spawn-time depth-check, но фактически продолжается через свежую сессию с чистым step-стейтом.
- Для подагента в background-режиме возвращай структурированный результат `{ sessionID, status: "running", output: "..." }` — модель видит, что подагент работает в фоне, и продолжает основной поток без poll/sleep.

### Принцип 3. Retry policy — ограниченная, без бесконечных циклов

Повторные попытки на retryable ошибки (429 RateLimit, 529 ProviderInternal, Transport/Timeout):

- Экспоненциальный backoff от 2s, capped на 10s per gap, максимум 10 retry-попыток (≈84s ожидания при всех неудачах, 67-101s с jitter). `retry-after` от провайдера bounded сверху 15 минутами, чтобы враждебный/битый заголовок не повесил вызов на часы.
- Для timeout — отдельный, жёсткий кап `MAX_TIMEOUT_RETRIES = 3` (timeout уже потратил минуты ожидания до неудачи, общий бюджет урезан).
- One-shot вызовы (image/decision/stateless-генерация) — до 3 попыток, только когда запрос точно не дошёл до провайдера (`notRun`: rate-limit, overload 503/529, not-sent transport, ECONNREFUSED/ENOTFOUND/EAI_AGAIN). Не ретраить запросы, которые провайдер уже выполнил и списал.
- После исчерпания бюджета ошибка возвращается как `AIError` и обрабатывается как обычный tool-result/assistant-error, не падая в UI как uncaught exception.

### Контракт для OryaAgent BETA (обязательно к реализации)

- **`SessionRunner` (Python, LangGraph node):** лимит шагов реализуй через soft-nudge + `tool_choice="none"`, **не** через `raise`. Текст `MAX_STEPS_PROMPT` — локализуемая константа в `prompts/max_steps.py`, инжектируется как `Message.assistant(...)` в транскрипт перед финальным `model.generate`.
- **`SubagentTool` (B-29 / CapabilityRegistry):** (а) считает глубину через parentID-walk по `SessionStore`, (б) возвращает `ToolFailure(...)` (НЕ exception) при `depth >= subagent_depth`, (в) `sessions.create(parentID=current, step=1)` — дочерняя сессия со сброшенным step-счётчиком, лимит предка не наследуется.
- **`ModelRetry` (TieredModelRouter adapter):** exponential 2s→10s, max 10, timeout-cap 3, one-shot-cap 3, retry-after-cap 15min. Все ошибки после исчерпания бюджета — `AIError` как tool-result, не uncaught.
- **Next.js Web UI (B-11..B-20):** при срабатывании лимита рекурсии/шагов **не показывать** error-индикаторы. Только обычный streaming ответ ассистента. Audit-запись о срабатывании лимита — в `Hooks UI` (B-20) как audit-entry, не как user-facing ошибка.
- **Chainlit mirror:** то же — никаких `cl.ErrorMessage` на soft-лимиты.

### Антипаттерны (запрещены в BETA)

- `raise MaxStepsExceeded` / `raise RecursionLimit` в любом месте runner'а — нарушает постулат.
- Глобальный `max_iterations` на всю сессию с hard-stop — ломает цепочки подагентов.
- Наследование step-счётчика от родителя к ребёнку — убивает «бесшовный обход через свежую сессию».
- Retry-loop без `max_recurs` и без `retry-after` cap — `SessionRetry.policy()` без upper bound (см. opencode issue #21960).
- Toast/modal на soft-ToolFailure в UI — превращает soft-fail в hard-fail с точки зрения пользователя.

---

## 0. Контекст и роль

Ты — senior Python-разработчик, реализующий **фазу BETA** системы OryaAgent v7. BETA превращает «безопасный MVP с L0 memory + low-latency baseline» в **«расширяемую платформу с DFC + Tri-Model + LSP-native + UKB + RetrievalOrchestrator + CapabilityRegistry»**.

Помимо memory/MCP/hooks/skills/Next.js из v6 BETA, добавляются **6 новых архитектурных примитивов v7**. Это самая большая фаза по объёму работы (7 недель, +5000 LOC), но и по ценности — она закрывает **три главных пробела v6** (нет DFC, нет tri-model, нет LSP-native).

**Принцип BETA v7 (vs v6):** +2 недели, +5000 LOC, но:
- DFC держит окно ≤16K токенов (vs v6 30-60K на длинной сессии)
- Tri-Model Pipeline даёт self-verifying loop в каждом ходе
- LSP-native даёт -100× latency + -10× tokens на code-facts
- UKB унифицирует retrieval-интерфейс
- RetrievalOrchestrator решает, когда retrieve (7 стратегий)
- CapabilityRegistry фильтрует tools per turn (8-15 visible, not all 25+)

**Инвариантность:** BETA не нарушает контракты ALPHA. `TieredModelRouter` остаётся, но получает tier от planner'а (B-25). `PromptCacheLayout` остаётся, но cacheable prefix теперь строится через `dfc.assemble_hot(plan)`. `ConnectionPool` остаётся без изменений.

---

## 1. Цели фазы

Превратить «production-safe + low-latency baseline» (ALPHA) в «расширяемую платформу»:

### 1.1. Цели v6 BETA (базовые, остаются в силе)

1. **Трёхслойная память L0+L1+L2:**
   - L0: MDStore (MVP) — 6 MD-файлов (в system-prompt-блоке — 4 scored).
   - L1: SQLiteStore (B-21) — FTS5 + SQLCipher, MemoryOutbox + drain-worker.
   - L2: Qdrant через OriaHS (P-18, PROD).
2. **Memory-extractor LLM-worker (B-22)** — batch haiku, extracts facts после N сообщений.
3. **`/remember`, `/forget`, `/memory list/export/import` endpoints + UI (B-23)**.
4. **MCP integration** — OriaHS как MCP-сервер.
5. **Hooks** (pre/post-tool) для custom logic.
6. **Skills** (declarative tool-bundles).
7. **Next.js Web UI** (parallel to Chainlit).
8. **BranchManager** (fork/merge sessions).

### 1.2. Новые цели v7 BETA

9. **DFC (#18)** — Dynamic Fast Context, 5 слоёв (HEAT/HOT/WARM/COLD/ICE). In-window discipline, не заменяет v6 memory-layer.
10. **Tri-Model Pipeline (#19)** — LangGraph subgraph: plan → execute → test (concurrent с partial diff).
11. **LSP-native (#20)** — LSP-bus + lsp-mcp + 7 lsp-tools. Primary source код-фактов.
12. **UKB (#22)** — Unified Knowledge Bus, единый MCP-контракт над LSP/OriaHS/Memory/code/KB.
13. **RetrievalOrchestrator (#27)** — отдельный модуль, решающий когда retrieve (7 стратегий).
14. **CapabilityRegistry (#28)** — динамическая фильтрация инструментов per turn.

---

## 2. Технологический стек (delta к ALPHA)

| Компонент | Технология | Назначение |
|---|---|---|
| LSP-серверы | pyright, typescript-language-server, rust-analyzer, gopls, jdtls, lua-language-server | code-facts source |
| File watcher | `watchdog` (Python) | cross-platform FS events → `textDocument/didChange` |
| JSON-RPC client | custom stdio client (или `pylsp-stdio`) | LSP-server communication |
| Vector DB (L2) | Qdrant (через OriaHS в PROD) | semantic search |
| L1 store | SQLite + FTS5 + SQLCipher | lexical search + encryption |
| Embeddings | `bge-m3` (sentence-transformers, local) | no API call, fast |
| MCP SDK | `mcp` Python package | MCP server / client |
| Next.js | Next.js 14+ | Web UI (parallel to Chainlit) |

---

## 3. Полный список тикетов фазы (B-00 … B-30)

v6 BETA содержит 24 тикета (B-00..B-23). v7 добавляет 6 новых (B-24..B-29) + B-30 (multi-language programming capabilities, per-language LSP bindings). Полный перечень — 31 тикет.

### 3.1. v6 BETA baseline (B-00 … B-23) — реализуй без изменений

| ID | Title | Estimate | Заметки |
|---|---|---|---|
| B-00 | REMOVED (в v6) | — | merged into M-20 |
| B-01 | MCP server: oriahs-mcp | 1 день | OriaHS как MCP server |
| B-02 | oriahs_search tool (через MCP) | 4 часа | semantic codebase search |
| B-03 | oriahs_index tool | 4 часа | index project |
| B-04 | Hooks framework (pre/post-tool) | 1 день | registry + execution |
| B-05 | Hook: auto-format после write/edit | 4 часа | example hook |
| B-06 | Skills framework (declarative tool-bundles) | 1 день | YAML skill definitions |
| B-07 | Skill: code-review (комбинирует tools) | 4 часа | example skill |
| B-08 | REMOVED → M-20 (v5) | — | merged into MVP |
| B-09 | BranchManager: fork session | 1 день | create branch from any turn |
| B-10 | BranchManager: merge branches | 1 день | merge tool-call sequences |
| B-11 | Next.js Web UI: chat interface | 2 дня | parallel to Chainlit |
| B-12 | Next.js Web UI: session sidebar | 1 день | list, search, filter |
| B-13 | Next.js Web UI: settings panel | 4 часа | LLM-provider, permission-policy |
| B-14 | Next.js Web UI: tool-call visualization | 1 день | collapsible JSON tree |
| B-15 | WebSocket для streaming | 1 день | real-time token streaming |
| B-16 | Memory UI: list, edit, delete | 1 день | UI for L0+L1 memory |
| B-17 | Memory UI: import/export | 4 часа | JSON import/export |
| B-18 | BranchManager UI | 1 день | visualize branches, merge dialog |
| B-19 | Skills UI: browse + activate | 4 часа | list skills, toggle |
| B-20 | Hooks UI: view executed hooks | 4 часа | audit log |
| B-21 | **SQLiteStore (L1, FTS5, SQLCipher) + MemoryOutbox + drain-worker** | 2 дня | L1 memory layer |
| B-22 | **Memory-extractor LLM-worker (batch, haiku)** | 1 день | extract facts after N messages |
| B-23 | **`/remember`, `/forget`, `/memory list/export/import` endpoints + UI** | 1 день | memory CRUD |

### 3.2. Новые v7 BETA тикеты — детальные спецификации (B-24..B-30)

---

## 4. B-24 — DFC: 5 слоёв (HEAT/HOT/WARM/COLD/ICE) + BackgroundCompactor 🆕

> **Component:** ARCHITECT7 §3 #18, §6.1, §7.2 | **Dependencies:** M-25 (MDStore v6), A-19 (PromptCacheLayout), A-18 (TieredModelRouter) | **Estimate:** 5 дней | **TRIZ:** #17 Another dimension + #15 Dynamicity + #19 Periodic action | **ADR:** ADR-0001 (Dynamic Fast Context), ADR-0010 (Background compaction)

### Context

v6 `ContextManager` урезает историю по token-count (как в v4). На длинной сессии окно разрастается линейно — LLM видит весь шум, latency и cost растут. В v7 DFC (Dynamic Fast Context) — 5 слоёв (HEAT/HOT/WARM/COLD/ICE). В окно модели попадает только HOT (4-8K токенов). Остальные — retrievable, но не загружаются по умолчанию. DFC **не заменяет** v6 memory-layer; DFC = in-window discipline, v6 memory = long-term storage.

### Goal

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

### Constraints

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

### Acceptance Criteria

- ✅ `DFC(ukb=mock, lsp_bus=mock, memory=mock)` инициализируется без ошибок.
- ✅ `dfc.assemble_hot(plan)` возвращает cacheable prefix + dynamic suffix, ≤16K токенов total.
- ✅ `dfc.promote_to_hot("key1", "value1")` — добавляет в HOT; при превышении MAX_HOT (8K) — oldest demoted в WARM.
- ✅ `dfc.snapshot()` возвращает immutable copy (для Tournament в PROD).
- ✅ BackgroundCompactor: после 10 ходов — async compaction WARM→COLD (verified через `orya_dfc_compaction_total` counter).
- ✅ DFC state persisted в Redis: после restart — HOT и WARM восстановлены.
- ✅ `dfc.assemble_hot` span эмитится с правильными атрибутами (`dfc.heat_hit`, `dfc.hot_size_tokens`, `dfc.warm_demoted`, `dfc.cold_compacted`).
- ✅ Integration с v6 SystemPromptBuilder: system-prompt now ≤ 8K cacheable prefix + 8K dynamic suffix.
- ✅ Integration с PromptCacheLayout (A-19): cacheable prefix marked с `cache_control: ephemeral`.

### Forbidden patterns

- ❌ Replace v6 memory-layer (L0/L1/L2) — DFC = in-window discipline, v6 memory = long-term storage.
- ❌ Persist COLD layer (compacts) в Redis — это RAM only.
- ❌ Block agent-loop на compaction — async only.
- ❌ Mix DFC layers (e.g., write to ICE from HOT) — strict layer discipline.
- ❌ Hardcoded token limits — through settings.

### Suggested files

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

## 5. B-25 — Tri-Model Pipeline (plan → execute → test) 🆕

> **Component:** ARCHITECT7 §3 #19, §6.2, ADR-v07-001 (Streaming Tri-Model) | **Dependencies:** B-24 (DFC), A-18 (TieredModelRouter), A-19 (PromptCacheLayout) | **Estimate:** 4 дня | **TRIZ:** #40 Composite materials + #9 Preliminary anti-action + #21 Rushing | **ADR:** ADR-0003 (Tri-model pipeline)

### Context

v6 имеет один LLM-call на ход (Sonnet/Haiku через CostAwareRouter). Чтобы доверять ответу, нужен второй LLM-call (verify), но это удваивает стоимость. В v7 Tri-Model Pipeline делит ход на три фазы: planner (small, 200-400 ms), executor (large, 2-6 s), tester (small, 200-400 ms). Tester проверяет только критерии успеха, заданные planner'ой — узкий контекст → маленькая модель → +200 ms, +$0.001 на ход.

### Goal

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

### Constraints

- Planner prompt: see `app/core/workflow/prompts.py::PLAN_PROMPT` (TODO: write).
- Tester prompt: see `app/core/workflow/prompts.py::TESTER_PROMPT` (TODO: write).
- Tester получает: criteria (from plan), diff (from executor), run_tests=false (в BETA — full run_tests в PROD через Concurrent Tester P-24).
- Replan bounded N=2: после 2 неудач → fallback на final fail (return verdict=fail, no more replans).
- В BETA Concurrent Tester — basic (not overlapped с executor); full overlap в P-24.
- LangGraph `astream_events` v2 для partial diff (но в BETA не используется, full impl в P-24).

### Acceptance Criteria

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

### Forbidden patterns

- ❌ Использовать Sonnet для planner/tester — дорого; Haiku/Qwen-3B достаточно.
- ❌ Block executor на tester (в BETA — sequential; concurrent в P-24).
- ❌ Unbounded replan (max 2).
- ❌ Hardcoded prompts — в `prompts.py`.

### Suggested files

- `app/core/workflow/tri_model.py`
- `app/core/workflow/prompts.py` (PLAN_PROMPT, TESTER_PROMPT)
- `app/core/workflow/state.py` (TurnState, Plan, Verdict dataclasses)
- `tests/test_tri_model.py`
- `tests/fixtures/synthetic_dataset.yml` (10 scenarios)

---

## 6. B-26 — LSP-bus + 6 LSP-servers + 7 LSP-tools 🆕

> **Component:** ARCHITECT7 §3 #20, §6.3, §8, §12, ROADMAP7 §21 | **Dependencies:** M-04 (graph skeleton), M-22 (injection defense v5) | **Estimate:** 7 дней | **TRIZ:** #28 Mechanics substitution + #24 Intermediary | **ADR:** ADR-0002 (LSP-native code facts)

### Context

v6 добывает код-факты через `read`+`grep` (как у всех 5 SOTA) + OriaHS semantic search. Для типичной code-задачи нужно: сигнатура функции, её определение, ссылки на неё, diagnostics. Сейчас это 3-5 LLM round-trips + чтение файлов (2-20K токенов на файл). Latency 3-8 s. LSP-native даёт sub-ms latency + 100-500 токенов на операцию.

### Goal

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

### Constraints

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

### Acceptance Criteria

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

### Forbidden patterns

- ❌ Использовать `read+grep` когда LSP available — LSP-first.
- ❌ LSP-server как FS-writer (rename — это OK, но не write/edit).
- ❌ Block agent-loop на LSP-server startup — lazy initialization.
- ❌ Mix LSP-server state between workspaces — workspace isolation.
- ❌ Hardcoded LSP-server paths — auto-detect or through settings.

### Suggested files

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

## 7. B-27 — UKB Router (partial: lsp + memory) 🆕

> **Component:** ARCHITECT7 §3 #22, §6.4 | **Dependencies:** B-26 (LSP-native), v6 B-21 (SQLiteStore L1), v6 P-18 (Qdrant L2, только PROD) | **Estimate:** 3 дня | **TRIZ:** #5 Merging + #12 Equipotentiality | **ADR:** ADR-v03-100 (UKB)

### Context

v6 имеет фрагментированные retrieval-точки: `read`/`grep` (5 базовых tools), `oriahs_search` (codebase indexing), `memory_search` (L1+L2 memory). LLM должна знать, когда какую вызывать; observability фрагментирована. В v7 UKB (Unified Knowledge Bus) — единый MCP-контракт над LSP/RAG/Memory/code/KB. В BETA — partial (только lsp + memory namespaces, без oriahs/code/kb). В PROD — full (5 namespaces).

### Goal

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

### Constraints

- Routing rules: see `app/core/ukb/router.py::UKBRouter.RULES`.
- Explicit capability: `lsp.def`, `lsp.symbol_search`, `memory.semantic`, `memory.lexical`.
- Default (no capability): parallel lookup all available namespaces (lsp + memory в BETA; + oriahs + code + kb в PROD).
- Merge: by content hash (sha256 of serialized content).
- Top_k: per-namespace top_k, merged top_k = max(per-namespace top_k).
- В BETA: `memory-mcp` mock (returns empty or simple FTS5 results from v6 B-21 SQLiteStore).
- В PROD: `memory-mcp` full (v6 P-18 hybrid L1+L2).

### Acceptance Criteria

- ✅ `ukb_lookup("function:userService.create", capability="lsp.def")` routes to `lsp-mcp` → `textDocument/definition`.
- ✅ `ukb_lookup("memory-tier design", capability="memory.semantic")` routes to `memory-mcp` → Qdrant lookup (mock в BETA).
- ✅ `ukb_lookup("hello")` (default) → parallel lookup all namespaces, merge + dedupe.
- ✅ Merge: 2 namespaces return same item → only 1 in result.
- ✅ Latency p95: ≤ 500 ms для single-namespace lookup; ≤ 800 ms для parallel multi-namespace.
- ✅ Spans: `ukb.lookup` с правильными атрибутами.
- ✅ Metrics exported.

### Forbidden patterns

- ❌ Direct LSP/memory calls from agent-loop bypass UKB — all retrieval through `ukb_lookup`.
- ❌ Hardcoded namespace routing — through rules table.
- ❌ Mix namespaces (e.g., return LSP result with memory namespace metadata).

### Suggested files

- `app/core/ukb/__init__.py`
- `app/core/ukb/router.py`
- `app/tools/ukb.py` (ukb_lookup tool)
- `tests/test_ukb_router.py`

---

## 8. B-28 — RetrievalOrchestrator (7 strategies) 🆕

> **Component:** ARCHITECT7 §3 #27, §6.7 | **Dependencies:** B-24 (DFC), B-27 (UKB partial) | **Estimate:** 4 дня | **TRIZ:** #24 Intermediary + #10 Preliminary action | **ADR:** ADR-v02-004 (Retrieval orchestrator)

### Context

v6 имеет `memory_search` tool (PROD). LLM решает, когда вызвать retrieval — но это непредсказуемо. Иногда LLM забывает; иногда вызывает лишнее. В v7 RetrievalOrchestrator — отдельный модуль, который **решает**, когда retrieve, по 7 стратегиям.

### Goal

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

### Constraints

- Heuristics in `app/core/retrieval/heuristics.py`:
  - Referential markers: regex `помнишь|обсуждали|ранее|в прошлый раз`.
  - Similar tokens: cosine similarity > 0.7 with previous turn (через embeddings).
  - First turn: `session_state.turn_count == 0`.
  - Predictive hint: from PredictivePlanner (placeholder в BETA, full в PROD).
- `top_k`: per strategy (см. `ARCHITECT7 §3 #27` table).
- Rerank applied per strategy (см. RerankPolicy P-25 в PROD; в BETA — always apply).
- Decision accuracy measured на synthetic dataset: 10 scenarios с known correct strategy.

### Acceptance Criteria

- ✅ `RetrievalOrchestrator.decide(state)` возвращает один из 7 strategy names.
- ✅ `RetrievalOrchestrator.execute("none", state)` возвращает `[]`.
- ✅ `RetrievalOrchestrator.execute("standard", state)` возвращает top-3 results (в BETA — mock; в PROD — через UKB).
- ✅ `RetrievalOrchestrator.execute("explicit_recall", state)` возвращает top-10 results (после referential marker detected).
- ✅ Decision accuracy > 75% на synthetic dataset (10 scenarios).
- ✅ Integration с DFC: results → `dfc.promote_to_hot(key, value)`.
- ✅ Integration с UKB: orchestrator calls `ukb.lookup(...)` в execute.
- ✅ Spans: `retrieval.orchestrate` с правильными атрибутами.
- ✅ Metrics exported.

### Forbidden patterns

- ❌ Block agent-loop на retrieval — async only.
- ❌ Always retrieve (default strategy = `none` для performance).
- ❌ Hardcoded heuristics — through heuristics.py table.

### Suggested files

- `app/core/retrieval/__init__.py`
- `app/core/retrieval/orchestrator.py`
- `app/core/retrieval/heuristics.py`
- `app/core/retrieval/models.py` (RetrievedChunk dataclass)
- `tests/test_retrieval_orchestrator.py`
- `tests/fixtures/retrieval_scenarios.yml` (10 scenarios with known correct strategy)

---

## 9. B-29 — CapabilityRegistry (dynamic tool-filter per turn) 🆕

> **Component:** ARCHITECT7 §3 #28, §6.8 | **Dependencies:** M-04 (graph skeleton), B-26 (LSP-tools), B-27 (UKB tool) | **Estimate:** 2 дня | **TRIZ:** #15 Dynamicity + #25 Self-service | **ADR:** ADR-v02-007 (Tool discovery)

### Context

v6 имеет 5 базовых + oriahs_search + oriahs_index + memory_search + (v7: lsp_* × 7) + (v7: ukb_lookup) = 15+ tools. LLM видит все каждый ход → 1500+ токенов tool-list → noise для decision-quality. В v7 CapabilityRegistry активирует инструменты по file/content triggers per turn (8-15 visible, not all 25+).

### Goal

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

### Constraints

- Triggers in `app/core/tools/triggers.py` table (rule-based, не LLM-based).
- LLM-mini fallback classifier: если rule-based trigger returns `None` → call LLM-mini (Haiku) для classification (в PROD; в BETA — default visible).
- Default visible: `read`, `write`, `edit`, `bash`, `grep` (5 базовых), `ukb.lookup` (single retrieval).
- Default invisible: all LSP-tools (visible when trigger matches), `oriahs_search` (PROD), `memory_search` (PROD).
- Max active tools per turn: 15.
- LLM sees filtered tool-list каждый turn.

### Acceptance Criteria

- ✅ `CapabilityRegistry.filter(all_tools, ctx_no_language)` возвращает 5 базовых + ukb.lookup = 6 tools (no LSP, no oriahs, no memory).
- ✅ `CapabilityRegistry.filter(all_tools, ctx_python_file)` возвращает 5 базовых + ukb.lookup + lsp.hover + lsp.def + lsp.references = 9 tools.
- ✅ `CapabilityRegistry.filter(all_tools, ctx_rename_intent)` возвращает 5 базовых + ukb.lookup + lsp.rename = 7 tools.
- ✅ `CapabilityRegistry.filter(all_tools, ctx_referential_marker)` возвращает 5 базовых + ukb.lookup + memory.search = 7 tools.
- ✅ Max active tools per turn ≤ 15.
- ✅ LLM видит только filtered tools (verified через `bind_tools` в LangGraph state).
- ✅ Spans: `capability.filter` с правильными атрибутами.
- ✅ Metrics exported.

### Forbidden patterns

- ❌ LLM-based triggers на каждом turn (rule-based primary, LLM-mini fallback в PROD).
- ❌ Block agent-loop на filter — sync, fast (<10 ms).
- ❌ Hardcoded tool-list — through triggers table.

### Suggested files

- `app/core/tools/capability_registry.py`
- `app/core/tools/triggers.py`
- `app/core/tools/context.py` (TurnContext dataclass)
- `tests/test_capability_registry.py`

---

## 10. B-30 — Multi-language programming capabilities + per-language LSP bindings (Java, Rust, Go, JavaScript, Frontend) 🆕

> **Component:** ARCHITECT7 §3 #20 (LSP-native extension), §6.3 (LSP-bus), §8 (API surface) | **Dependencies:** B-26 (LSP-bus + 6 LSP-servers), B-29 (CapabilityRegistry), B-06 (Skills framework, v6), B-04 (Hooks, v6), B-24 (DFC) | **Estimate:** 5 дней | **TRIZ:** #15 Dynamicity + #28 Mechanics substitution + #5 Merging + #25 Self-service | **ADR:** ADR-0002 (LSP-native code facts), ADR-v02-007 (Tool discovery)

### Context

B-26 уже даёт LSP-bus + 7 LSP-tools + 6 LSP-servers (pyright, typescript-language-server, rust-analyzer, gopls, jdtls, lua-language-server) — но это **инфраструктура** для code-facts. Что отсутствует: единая **capability-функция агента** для программирования на каждом языке — то есть декларативный контракт `agent_program(language, task)` + per-language skill-bundles (YAML) + per-language hook-sets (lint/format/build) + per-language LSP-config matrix. Без B-30 агент умеет «вызвать LSP-инструменты», но не имеет единой «функции программирования на Java/Rust/Go/JS» с встроенными best-practices, автоформатированием и рефакторинг-рецептами для каждого языка.

B-30 закрывает этот пробел: вводит `LanguageCapabilityRegistry` (надстройка над `CapabilityRegistry` из B-29), capability-function `agent_program(language, task)`, 5 языковых skill-bundles (Java/Rust/Go/JS/Frontend), 9 per-language hook-sets (auto-format + auto-lint + frontend accessibility-hint) и per-language `LSPServerConfig` (init options + file-exts + build/test/lint/format commands).

**Языки и LSP-binding'и (B-30 contract):**

| Language | LSP server | File extensions | Build | Test | Lint | Format |
|---|---|---|---|---|---|---|
| Java | `jdtls` (Eclipse JDT) | `.java` | `mvn compile` (Maven) / `gradle compileJava` (Gradle) | `mvn test` / `gradle test` | `checkstyle` | `google-java-format` |
| Rust | `rust-analyzer` | `.rs` | `cargo build` | `cargo test` | `cargo clippy` | `rustfmt` |
| Go | `gopls` | `.go` | `go build ./...` | `go test ./...` | `go vet` | `gofmt -w` |
| JavaScript | `typescript-language-server` (`allow_js: true`) | `.js`, `.mjs`, `.cjs` | `npm run build` | `npm test` | `eslint` | `prettier --write` |
| Frontend (TSX/JSX + CSS/HTML) | `typescript-language-server` (`jsx: "react"`) + `vscode-css-languageserver` + `vscode-html-languageserver` (FUTURE+ в PROD) | `.tsx`, `.jsx`, `.css`, `.html` | `npm run build` | `npm test` | `eslint` (TSX/JSX) + `stylelint` (CSS) | `prettier --write` + axe-core hint (non-blocking) |

### Goal

1. Реализовать `app/core/capability/language_registry.py::LanguageCapabilityRegistry`:
   - `LANGUAGES`: dict с поддерживаемыми языками и их LSP-binding'ами (таблица выше).
   - `resolve(language: str) -> LanguageCapability` — returns `LanguageCapability` dataclass (`language`, `lsp_server`, `file_exts`, `build_cmd`, `test_cmd`, `lint_cmd`, `format_cmd`, `skill_bundle`, `hooks`).
   - `detect(file_path: str | Path) -> str` — auto-detect language by extension (`.java` → `java`, `.rs` → `rust`, `.go` → `go`, `.js`/`.mjs`/`.cjs` → `javascript`, `.tsx`/`.jsx` → `frontend`, `.py` → `python`, `.ts` → `typescript`, `.lua` → `lua`).
   - `is_supported(language: str) -> bool`.
   - `list_supported() -> list[str]` — для `/capability/languages` endpoint.
2. Реализовать capability-function `agent_program(language: str, task: str) -> str` в `app/core/capability/program.py`:
   - Не LLM-tool, а **capability-router** (internal callable): detect-language → resolve-capability → activate skill-bundle (B-06) → activate hook-set (B-04) → ensure LSP-server lazy (B-26 `LSPBus.ensure_server`) → return "ready" message для system-prompt.
   - В system-prompt появляется блок: «Active language: Java (jdtls LSP). Skills: java-maven-build, java-junit-test, java-refactor. Hooks: auto-format-google-java-format, auto-lint-checkstyle. Build: `mvn compile`. Test: `mvn test`.»
   - Вызывается planner'ой (B-25) явно: `agent_program("java", "add logging to UserService.create")` — агент переходит в «Java-mode» с bound lsp_* tools, skill-bundle и hook-set.
3. Реализовать 5 языковых skill-bundles в `app/skills/`:
   - `java-maven.yaml`: tools = `[lsp_hover, lsp_definition, lsp_references, lsp_rename, lsp_diagnostics, lsp_code_action, lsp_symbol_search, bash, read, write, edit, grep]`; hooks = `[auto-format-google-java-format, auto-lint-checkstyle]`; build_cmd = `mvn -q compile`; test_cmd = `mvn -q test`; refactor_actions = `[extract_method, convert_to_record, generate_hashCode_equals, add_missing_interface_methods]`.
   - `rust-cargo.yaml`: tools = `[lsp_*, bash (cargo build/test/clippy/fmt), read, write, edit, grep]`; hooks = `[auto-format-rustfmt, auto-lint-clippy]`; build_cmd = `cargo build`; test_cmd = `cargo test`; refactor_actions = `[extract_function, convert_to_async, generate_impl_block, fix_clippy_lint]`.
   - `go-mod.yaml`: tools = `[lsp_*, bash (go build/test/vet/fmt), read, write, edit, grep]`; hooks = `[auto-format-gofmt, auto-lint-govet]`; build_cmd = `go build ./...`; test_cmd = `go test ./...`; refactor_actions = `[extract_function, convert_to_interface, implement_missing_methods, fix_struct_tag]`.
   - `javascript-node.yaml`: tools = `[lsp_*, bash (npm/pnpm/yarn run), read, write, edit, grep]`; hooks = `[auto-format-prettier, auto-lint-eslint]`; build_cmd = `npm run build`; test_cmd = `npm test`; refactor_actions = `[extract_to_function, convert_to_arrow_function, add_missing_return_type, fix_eslint_rule]`.
   - `frontend-tsx.yaml`: tools = `[lsp_*, bash (npm/pnpm run), read, write, edit, grep]`; hooks = `[auto-format-prettier, auto-lint-eslint, accessibility-hint-axe]`; build_cmd = `npm run build`; test_cmd = `npm test`; refactor_actions = `[extract_to_component, convert_to_arrow_function, add_missing_return_type, fix_eslint_rule, fix_a11y_violation]`.
4. Реализовать per-language hook-sets в `app/hooks/` (post-write/edit, non-blocking):
   - `auto_format_google_java_format.py` — `google-java-format -i <file>` на `.java`.
   - `auto_format_rustfmt.py` — `rustfmt --edition 2021 <file>` на `.rs`.
   - `auto_format_gofmt.py` — `gofmt -w <file>` на `.go`.
   - `auto_format_prettier.py` — `prettier --write <file>` на `.js`/`.mjs`/`.cjs`/`.jsx`/`.tsx`/`.css`/`.html`.
   - `auto_lint_checkstyle.py` — `checkstyle -c /google_checks.xml <file>` на `.java`.
   - `auto_lint_clippy.py` — `cargo clippy --message-format=short` на `.rs` (cargo workspace).
   - `auto_lint_govet.py` — `go vet ./...` на `.go` (package-level).
   - `auto_lint_eslint.py` — `eslint --format=compact <file>` на `.js`/`.mjs`/`.cjs`/`.jsx`/`.tsx`.
   - `accessibility_hint_axe.py` — `axe-core` headless hint на `.tsx`/`.jsx` (non-blocking, suggestion-only, через Playwright FUTURE+ в PROD; в BETA — static-rules hint).
5. Реализовать per-language LSP-config в `app/core/lsp/config.py::LSPServerConfig`:
   - `LANGUAGES`: dict с init options для каждого LSP-сервера.
   - Java (jdtls): `settings.java.configuration.runtimes` (auto-detect `JAVA_HOME`), `settings.java.import.maven.enabled=true`, `settings.java.import.gradle.enabled=true`, `initializationOptions.workspaceFolders`, `-data <workspace_dir>`, `bundles=[]`.
   - Rust (rust-analyzer): `initializationOptions.cargo.loadOutDirsFromCheck=true`, `initializationOptions.procMacro.enable=true`, `initializationOptions.checkOnSave.command="clippy"`, `initializationOptions.diagnostics.enable=true`.
   - Go (gopls): `initializationOptions.build.staticcheck=true`, `initializationOptions.buildFlags=[]`, `initializationOptions.go.buildTags=""`, `initializationOptions.ui.diagnostic.staticcheck=true`.
   - JavaScript/TypeScript (typescript-language-server): `initializationOptions.tsserver.preferences.includePackageJsonAutomaticImports=true`, `initializationOptions.tsserver.preferences.importModuleSpecifierPreference="relative"`, `initializationOptions.javascript.implicitProjectConfig.allowJs=true` (для чистого JS), `initializationOptions.typescript.preferences.jsxAttributeCompletionStyle="auto"`.
   - Frontend TSX/JSX: `initializationOptions.typescript.jsx="react"`, `initializationOptions.typescript.suggest.enabled=true`, `initializationOptions.tsserver.preferences.jsxAttributeCompletionStyle="auto"`; CSS LSP (`vscode-css-languageserver`) и HTML LSP (`vscode-html-languageserver`) — FUTURE+ в PROD (BETA: TSX/JSX через tsserver, CSS/HTML — без LSP, plain `read+grep`).
6. Реализовать per-language LSP-рефакторинг-рецепты (mapping code-action → execution):
   - Java: `lsp_code_action` → `extract_method`, `convert_to_record`, `generate_hashCode_equals`, `add_missing_interface_methods`.
   - Rust: `lsp_code_action` → `extract_function`, `convert_to_async`, `generate_impl_block`, `fix_clippy_lint`.
   - Go: `lsp_code_action` → `extract_function`, `convert_to_interface`, `implement_missing_methods`, `fix_struct_tag`.
   - JS/TS/Frontend: `lsp_code_action` → `extract_to_function`/`extract_to_component`, `convert_to_arrow_function`, `add_missing_return_type`, `fix_eslint_rule`, `fix_a11y_violation` (frontend only).
7. Integration с B-29 (CapabilityRegistry): `LanguageCapabilityRegistry.resolve(language).tools` добавляет per-language LSP-tools в `CapabilityRegistry.filter(...)` через новый trigger `ctx.language == capability.language` (extensions `.java`/`.rs`/`.go`/`.js`/`.tsx`).
8. Integration с B-06 (Skills, v6): skill-bundles (YAML) регистрируются через `SkillRegistry.register(...)`; активируются автоматически при `agent_program(language, task)`.
9. Integration с B-04 (Hooks, v6): per-language hook-sets регистрируются через `HookRegistry.register(...)`; активируются автоматически при `agent_program(language, task)` (post-write/edit).
10. Integration с B-26 (LSP-bus): `LanguageCapabilityRegistry.resolve(language).lsp_server` → `LSPBus.ensure_server(language, workspace)` — lazy init, auto-restart, workspace isolation (все контракты B-26).
11. Integration с B-24 (DFC): `agent_program(language, task)` добавляет capability-stamp в DFC.hot (через `dfc.promote_to_hot("language_capability", capability_block)`), ≤500 токенов.
12. Integration с v6 SystemPromptBuilder: новый блок `language_capability_block()` → `build_system_prompt(state, tools, dfc, language_capability)` (stable-then-dynamic ordering сохраняется).
13. Metrics: `orya_language_program_total{language}`, `orya_language_program_duration_ms{language}`, `orya_language_skill_activated_total{language,skill}`, `orya_language_hook_executed_total{language,hook}`, `orya_lsp_call_total{method,language}` (extended из B-26 с per-language label).
14. Spans: `language.program` (с `language.name`, `language.lsp_server`, `language.skill_count`, `language.hook_count`, `language.build_cmd`, `language.test_cmd`).

### Constraints

- Per-language LSP-server config: see `app/core/lsp/config.py::LSPServerConfig.LANGUAGES` (rule-based table, не LLM-based).
- Java (jdtls): requires JDK 17+ на машине (auto-detected via `JAVA_HOME`); workspace dir = `.orya/jdtls/{workspace_hash}`; supports Maven (`pom.xml`) и Gradle (`build.gradle`, `build.gradle.kts`); `bundles=[]` (no VSCode extensions).
- Rust (rust-analyzer): requires `rustup` + `cargo`; `rust-analyzer` binary via `rustup component add rust-analyzer`; workspace = `Cargo.toml` parent dir.
- Go (gopls): requires Go 1.21+; `gopls` via `go install golang.org/x/tools/gopls@latest`; workspace = `go.mod` parent dir.
- JavaScript/TypeScript (typescript-language-server): requires Node.js 20+; npm packages `typescript-language-server` + `typescript`; workspace = `package.json` parent dir.
- Frontend (TSX/JSX): TS server handles `.tsx`/`.jsx` via `typescript.jsx="react"`; CSS LSP (`vscode-css-languageserver`) и HTML LSP (`vscode-html-languageserver`) — FUTURE+ в PROD (BETA: TSX/JSX через tsserver, CSS/HTML — без LSP, plain `read+grep`).
- Per-language hook-set: post-write/edit hooks (auto-format, auto-lint) — non-blocking, errors → `ToolMessage` warning (не failure).
- `accessibility-hint-axe` hook (frontend): non-blocking suggestion-only (no turn fail); в BETA — static-rules hint (rules table), full axe-core в PROD через Playwright.
- Skill-bundle activation: max 1 skill-bundle active per turn (per language); смена языка в mid-turn → deactivate previous skill-bundle.
- `agent_program(language, task)` capability-function: **не** LLM-tool, а capability-router (internal callable); exposed to LLM через system-prompt block + bound tools (не через `bind_tools`).
- Per-language LSP-server lifecycle: lazy init (B-26), auto-restart (B-26, max 3 retries), workspace isolation (B-26).
- Per-language build/test/lint/format commands: через settings (`ORYA_JAVA_BUILD_CMD`, `ORYA_RUST_BUILD_CMD`, `ORYA_GO_BUILD_CMD`, `ORYA_JS_BUILD_CMD`, `ORYA_FRONTEND_BUILD_CMD`, и аналоги для `*_TEST_CMD`, `*_LINT_CMD`, `*_FORMAT_CMD`) с defaults из таблицы выше.
- Per-language refactor-recipe execution: через `lsp_code_action` + `lsp_rename` (B-26), confirmation needed для > 100 refs (B-26 constraint).
- Per-language LSP-tools bound в CapabilityRegistry: trigger `ctx.language == capability.language` → visible lsp_* tools; default invisible (B-29 contract).
- `agent_program` fail-closed: unknown `language` → `ValueError("Unsupported language: <lang>. Supported: <list>")`, no fallback.

### Acceptance Criteria

- ✅ `LanguageCapabilityRegistry.resolve("java")` возвращает `LanguageCapability(language="java", lsp_server="jdtls", file_exts=[".java"], build_cmd="mvn compile", test_cmd="mvn test", lint_cmd="checkstyle", format_cmd="google-java-format", skill_bundle="java-maven", hooks=["auto-format-google-java-format", "auto-lint-checkstyle"])`.
- ✅ `LanguageCapabilityRegistry.resolve("rust")` → rust-analyzer, `cargo build`/`cargo test`, `rustfmt`, `cargo clippy`.
- ✅ `LanguageCapabilityRegistry.resolve("go")` → gopls, `go build`/`go test`/`go vet`/`gofmt`.
- ✅ `LanguageCapabilityRegistry.resolve("javascript")` → typescript-language-server (`allow_js: true`), `npm run build`/`npm test`, `prettier`, `eslint`.
- ✅ `LanguageCapabilityRegistry.resolve("frontend")` → typescript-language-server (`jsx: "react"`), `npm run build`/`npm test`, `prettier`, `eslint`, axe-hint; CSS/HTML LSP — FUTURE+ (BETA: TSX/JSX через tsserver).
- ✅ `LanguageCapabilityRegistry.detect("src/com/example/Main.java")` → `"java"`.
- ✅ `LanguageCapabilityRegistry.detect("src/lib.rs")` → `"rust"`.
- ✅ `LanguageCapabilityRegistry.detect("cmd/server/main.go")` → `"go"`.
- ✅ `LanguageCapabilityRegistry.detect("src/App.tsx")` → `"frontend"`.
- ✅ `LanguageCapabilityRegistry.detect("src/utils.js")` → `"javascript"`.
- ✅ `agent_program("java", "add logging to UserService.create")` активирует java-maven skill + jdtls LSP (lazy) + auto-format-google-java-format + auto-lint-checkstyle hooks; system-prompt содержит «Active language: Java (jdtls LSP)»; LLM видит lsp_* tools bound к jdtls; `dfc.promote_to_hot("language_capability", ...)` вызван.
- ✅ Java refactoring: `lsp_code_action` на `.java` возвращает `extract_method` / `generate_hashCode_equals` (если применимо к курсору).
- ✅ Rust refactoring: `lsp_code_action` на `.rs` возвращает `extract_function` / `fix_clippy_lint`.
- ✅ Go refactoring: `lsp_code_action` на `.go` возвращает `extract_function` / `implement_missing_methods`.
- ✅ JS/TS refactoring: `lsp_code_action` на `.tsx` возвращает `extract_to_component` / `convert_to_arrow_function`.
- ✅ Auto-format hooks: после `edit("src/com/example/Main.java", ...)` → `google-java-format -i Main.java` runs → file reformatted (verified через re-read).
- ✅ Auto-format hooks (Rust): после `edit("src/lib.rs", ...)` → `rustfmt --edition 2021 lib.rs` runs → file reformatted.
- ✅ Auto-format hooks (Go): после `edit("main.go", ...)` → `gofmt -w main.go` runs.
- ✅ Auto-format hooks (Frontend): после `edit("src/Button.tsx", ...)` → `prettier --write Button.tsx` runs.
- ✅ Auto-lint hooks: после `edit("src/lib.rs", ...)` → `cargo clippy` runs → warnings в `ToolMessage` (non-blocking).
- ✅ Frontend axe-hint: после `edit("src/Button.tsx", ...)` → static-rules accessibility hint в `ToolMessage` (non-blocking, suggestion-only).
- ✅ Integration с B-29 CapabilityRegistry: `CapabilityRegistry.filter(all_tools, ctx_java_file)` включает lsp_* tools (jdtls-bound) + java-maven skill-bundle tools (max 15 active tools).
- ✅ Integration с B-26 LSPBus: `agent_program("rust", ...)` → `LSPBus.ensure_server("rust", workspace)` запускает rust-analyzer (lazy).
- ✅ Integration с v6 Skills (B-06): skill-bundle `java-maven.yaml` registered в `SkillRegistry`, activated при `agent_program("java", ...)`.
- ✅ Integration с v6 Hooks (B-04): hook `auto_format_google_java_format.py` registered в `HookRegistry`, executed post-write/edit на `.java`.
- ✅ Integration с B-24 DFC: `agent_program` → `dfc.promote_to_hot("language_capability", capability_block)` (≤500 токенов).
- ✅ Latency p95: `agent_program(language, task)` (warm LSP-server) < 100 ms; cold-start LSP-server (first time): < 10 s (jdtls), < 5 s (rust-analyzer), < 3 s (gopls, tsserver).
- ✅ Fail-closed: `agent_program("klingon", ...)` → `ValueError("Unsupported language: klingon. Supported: ['python', 'typescript', 'javascript', 'rust', 'go', 'java', 'lua', 'frontend']")`.
- ✅ Metrics exported: `orya_language_program_total{language="java"}` counter инкрементируется после `agent_program("java", ...)`.
- ✅ Spans: `language.program` с правильными атрибутами (`language.name`, `language.lsp_server`, `language.skill_count`, `language.hook_count`).

### Forbidden patterns

- ❌ Hardcoded LSP-server configs — через `LSPServerConfig.LANGUAGES` table.
- ❌ Hardcoded build/test/lint/format commands — через settings (`ORYA_<LANG>_*_CMD`).
- ❌ Block agent-loop на `agent_program` (LSP-server lazy init в background, capability-router sync < 100 ms).
- ❌ Per-language hook fails hard — non-blocking, errors → `ToolMessage` warning (не ToolException).
- ❌ Mix languages в одном skill-bundle (один bundle = один language; frontend TSX/JSX + CSS/HTML — один bundle, т.к. это один «frontend» language domain).
- ❌ Use Sonnet для `agent_program` (capability-router — не LLM-call; planner B-25 вызывает `agent_program` synchronously без LLM).
- ❌ Frontend LSP без TSX/JSX support (tsserver `typescript.jsx="react"` обязателен для `.tsx`/`.jsx`).
- ❌ Auto-format hooks modify files outside the language's extensions (e.g., `google-java-format` на `.py` — forbidden; hook должен no-op).
- ❌ `agent_program` без `LanguageCapabilityRegistry.resolve` (fail-closed если `language` unsupported).
- ❌ CSS/HTML LSP в BETA (FUTURE+ в PROD через `vscode-css-languageserver` / `vscode-html-languageserver`); в BETA CSS/HTML — plain `read+grep`.
- ❌ Activate > 1 skill-bundle per turn (max 1 per language; смена языка → deactivate previous).
- ❌ axe-hint hook в BETA — full axe-core через Playwright (только PROD); в BETA static-rules hint.
- ❌ Bypass `CapabilityRegistry` (B-29) при активации per-language tools — все tool-filtering через `CapabilityRegistry.filter(...)`.

### Suggested files

- `app/core/capability/__init__.py`
- `app/core/capability/language_registry.py` (`LanguageCapabilityRegistry`, `LanguageCapability` dataclass)
- `app/core/capability/program.py` (`agent_program` capability-function)
- `app/core/lsp/config.py` (`LSPServerConfig`, per-language init options)
- `app/skills/java-maven.yaml`
- `app/skills/rust-cargo.yaml`
- `app/skills/go-mod.yaml`
- `app/skills/javascript-node.yaml`
- `app/skills/frontend-tsx.yaml`
- `app/hooks/auto_format_google_java_format.py`
- `app/hooks/auto_format_rustfmt.py`
- `app/hooks/auto_format_gofmt.py`
- `app/hooks/auto_format_prettier.py`
- `app/hooks/auto_lint_checkstyle.py`
- `app/hooks/auto_lint_clippy.py`
- `app/hooks/auto_lint_govet.py`
- `app/hooks/auto_lint_eslint.py`
- `app/hooks/accessibility_hint_axe.py`
- `app/api/capability.py` (`GET /capability/languages`, `POST /capability/program`)
- `tests/test_language_capability_registry.py`
- `tests/test_agent_program.py`
- `tests/test_lsp_config.py`
- `tests/fixtures/multi_lang_proj/` (small Java/Rust/Go/JS/TSX projects for testing)

---

## 11. Архитектура BETA (delta к ALPHA)

```
┌─────────────────────────────────────────────────────────────────┐
│                  UI: Chainlit + Next.js (B-11..B-13)              │
└─────────────────────────────────────────────────────────────────┘
                              │
┌─────────────────────────────────────────────────────────────────┐
│       FastAPI (Auth + RateLimit + Observability — from ALPHA)    │
└─────────────────────────────────────────────────────────────────┘
                              │
┌─────────────────────────────────────────────────────────────────┐
│                    Tri-Model Pipeline (B-25) 🆕                  │
│   ┌─────────┐    ┌──────────┐    ┌─────────┐    ┌─────────┐     │
│   │ planner │ →  │ executor │ →  │ tester  │ →  │ END or  │     │
│   │ (Haiku) │    │ (Sonnet) │    │ (Haiku) │    │ replan×2│     │
│   └─────────┘    └────┬─────┘    └─────────┘    └─────────┘     │
│                       │                                          │
│                       │ uses                                      │
│                       ▼                                          │
│                ┌───────────────┐                                  │
│                │ DFC (B-24) 🆕│                                   │
│                │  HEAT/HOT/    │                                  │
│                │  WARM/COLD/   │                                  │
│                │  ICE          │                                  │
│                └───────┬───────┘                                  │
│                        │                                          │
│                ┌───────▼───────┐                                  │
│                │ CapabilityReg │ → filter tools per turn          │
│                │  (B-29) 🆕    │   (8-15 visible, not all 25+)   │
│                └───────┬───────┘                                  │
│                        │                                          │
│                ┌───────▼───────┐                                  │
│                │ RetrievalOrch │ → decides when retrieve           │
│                │  (B-28) 🆕    │   (7 strategies)                  │
│                └───────┬───────┘                                  │
│                        │                                          │
│                ┌───────▼───────┐                                  │
│                │ UKB (B-27) 🆕│ → unified retrieval                │
│                │  lsp + memory│   (5 namespaces в PROD)           │
│                └───────┬───────┘                                  │
│                        │                                          │
│                ┌───────▼───────┐                                  │
│                │ LSP-bus (B-26)│ → 6 LSP-servers, 7 tools          │
│                │     🆕        │   sub-ms code-facts               │
│                └───────────────┘                                  │
└─────────────────────────────────────────────────────────────────┘
                              │
┌─────────────────────────────────────────────────────────────────┐
│         LLM-seam (ALPHA: TieredModelRouter + PromptCache + Pool) │
└─────────────────────────────────────────────────────────────────┘
                              │
                ┌─────────────┴──────────────┐
                ▼                            ▼
          Anthropic / OpenAI            LSP-servers
            / Ollama / Vertex          (pyright, tsserver, etc.)
```

---

## 12. Целевые NFR (delta к ALPHA)

| Параметр | ALPHA | BETA v7 | v6 было |
|---|---|---|---|
| Time-to-first-token | ≤ 600 ms | **≤ 1000 ms** (дольше из-за tri-model planner) | ≤ 1200 ms |
| Tokens per turn (10-файловая задача) | 30-60 K | **8-16 K** | 30-60 K |
| LSP-call latency p95 | — | **≤ 10 ms** | — |
| Tri-Model verdict rate (pass на 1st attempt) | — | **> 75%** | — |
| Replan rate | — | **< 20%** | — |
| Symbolic Shortcut usage | 0% | 0% (появится в PROD) | — |
| UKB lookup latency p95 | — | **≤ 500 ms** (pre-retrieval) | — |
| RetrievalOrchestrator decision accuracy | — | **> 75%** | — |
| CapabilityRegistry: active tools per turn | ~15 (static) | **8-15** (dynamic) | ~15 (static) |
| Cost per session (30 ходов) | ≤ $0.40 | **≤ $0.30** | ≤ $0.40 |
| LSP-server uptime | — | **> 99%** | — |
| Tri-Model early-abort rate | — | (basic в BETA) | — |
| Prompt-cache hit rate | > 40% | **> 60%** | — |

---

## 13. Definition of Done (delta к ALPHA)

- ✅ (все DoD из ALPHA)
- ✅ MCP: `oriahs-mcp` работает как MCP-сервер, `oriahs_search`, `oriahs_index` доступны как tools.
- ✅ Hooks: pre/post-tool hooks работают (B-04), auto-format hook (B-05) работает.
- ✅ Skills: declarative skill-bundles (YAML), code-review skill (B-07) работает.
- ✅ BranchManager: fork/merge sessions работает (B-09, B-10).
- ✅ Next.js Web UI: chat, sidebar, settings, tool-call visualization, WebSocket streaming (B-11..B-15).
- ✅ Memory UI: list, edit, delete, import/export (B-16, B-17).
- ✅ BranchManager UI (B-18), Skills UI (B-19), Hooks UI (B-20).
- ✅ SQLiteStore L1: insert, search, forget, supersede, export, import (B-21).
- ✅ SQLCipher encryption: файл не читается без ключа.
- ✅ Outbox-drain-worker работает с retry.
- ✅ Memory-extractor: после 10 сообщений — async extraction (B-22).
- ✅ /remember, /forget, /memory list/export/import работают end-to-end (B-23).
- ✅ **DFC: `dfc.assemble_hot(plan)` возвращает cacheable prefix + dynamic suffix, ≤16K токенов на типичном ходе.**
- ✅ **DFC layers: HEAT (placeholder, работает в PROD), HOT (current turn), WARM (LRU), COLD (compacts), ICE (= UKB).**
- ✅ **BackgroundCompactor: WARM→COLD на границах ходов (async, не блокирует turn).**
- ✅ **Tri-Model Pipeline: planner → executor → tester (concurrent).**
- ✅ **Concurrent tester: abort executor при early-fail (verified через `agent.test.early_abort=true`).**
- ✅ **Replan bounded N=2: после 2 неудач → fallback на symbolic shortcut (PROD) или final fail.**
- ✅ **LSP-bus: 6 языков поддерживается (Python, TS, Rust, Go, Java, Lua).**
- ✅ **LSP-tools: 7 tools (`lsp_hover`, `lsp_definition`, `lsp_references`, `lsp_symbol_search`, `lsp_rename`, `lsp_diagnostics`, `lsp_code_action`).**
- ✅ **LSP latency: <10 ms p95 для hover/def/refs (vs `read+grep` ~100-500 ms).**
- ✅ **UKB Router: 5 namespaces routing (lsp, oriahs, memory, code, kb) — в BETA: lsp + memory.**
- ✅ **`ukb.lookup(query, capability="lsp.def")` → routes to lsp-mcp.**
- ✅ **Default `ukb.lookup(query)` → parallel lookup all namespaces, dedupe.**
- ✅ **RetrievalOrchestrator: 7 strategies, decision accuracy > 75% на synthetic dataset.**
- ✅ **CapabilityRegistry: active tools 8-15 per turn (vs ~25+ без registry).**
- ✅ **`orya_capability_filter_active_count` metric exported.
- ✅ **B-30 Multi-language: `LanguageCapabilityRegistry.resolve("java"|"rust"|"go"|"javascript"|"frontend")` возвращает корректные `LanguageCapability` dataclass instances.**
- ✅ **`agent_program(language, task)` capability-function: активирует per-language skill-bundle + hook-set + LSP-server (lazy), stamp в DFC.hot.**
- ✅ **Per-language skill-bundles (YAML): java-maven, rust-cargo, go-mod, javascript-node, frontend-tsx — registered в SkillRegistry (v6 B-06).**
- ✅ **Per-language hook-sets (9 hooks): auto-format (4: google-java-format/rustfmt/gofmt/prettier), auto-lint (4: checkstyle/clippy/govet/eslint), accessibility-hint-axe (frontend) — registered в HookRegistry (v6 B-04), non-blocking.**
- ✅ **Per-language LSP-config в `app/core/lsp/config.py::LSPServerConfig` (init options для jdtls/rust-analyzer/gopls/typescript-language-server).**
- ✅ **Per-language refactor-recipes: `lsp_code_action` mapping для extract_method/extract_function/extract_to_component/generate_hashCode_equals/implement_missing_methods/fix_clippy_lint/fix_eslint_rule/fix_a11y_violation.**
- ✅ **Frontend TSX/JSX через tsserver (`typescript.jsx="react"`); CSS/HTML LSP — FUTURE+ (PROD).**
- ✅ **Latency p95 `agent_program` (warm LSP): < 100 ms; cold-start LSP-server: < 10 s (jdtls), < 5 s (rust-analyzer), < 3 s (gopls/tsserver).****

---

## 14. TRIZ-gates фазы (delta к ALPHA)

| Gate | Принцип | Что встроено |
|---|---|---|
| (все gates из ALPHA) | — | — |
| MCP integration | ТРИЗ #24 Intermediary + #28 Mechanics substitution | MCP server as tool source |
| Hooks framework | ТРИЗ #35 Parameter changes + #15 Dynamicity | pre/post-tool custom logic |
| Skills (declarative bundles) | ТРИЗ #15 Dynamicity + #25 Self-service | YAML skill definitions |
| BranchManager | ТРИЗ #17 Another dimension + #9 Preliminary anti-action | parallel session branches |
| SQLiteStore L1 (FTS5) | ТРИЗ #1 Segmentation + #28 Mechanics substitution | lexical search layer |
| MemoryOutbox + drain-worker | ТРИЗ #21 Rushing + #19 Periodic | async write queue |
| Memory-extractor (batch LLM) | ТРИЗ #28 Mechanics substitution + #35 Parameter changes | LLM extraction after N msgs |
| **DFC 5 слоёв** 🆕 | ТРИЗ #17 Another dimension + #15 Dynamicity | In-window context discipline |
| **Tri-Model Pipeline + Concurrent Tester** 🆕 | ТРИЗ #40 Composite + #21 Rushing + #9 Preliminary anti-action | Self-verifying loop |
| **LSP-native** 🆕 | ТРИЗ #28 Mechanics substitution + #24 Intermediary | LSP as primary code-facts source |
| **UKB** 🆕 | ТРИЗ #5 Merging + #12 Equipotentiality | Single retrieval interface |
| **RetrievalOrchestrator** 🆕 | ТРИЗ #24 Intermediary + #10 Preliminary | Policy-driven retrieval |
| **CapabilityRegistry** 🆕 | ТРИЗ #15 Dynamicity + #25 Self-service | Dynamic tool-filter |
| **BackgroundCompactor** 🆕 | ТРИЗ #19 Periodic + #15 Dynamicity | async context compaction |
| **Multi-language programming capabilities (B-30)** 🆕 | ТРИЗ #15 Dynamicity + #28 Mechanics substitution + #5 Merging + #25 Self-service | Per-language capability-router `agent_program(lang, task)` + skill-bundles + hook-sets + LSP-config |

---

## 15. Risks и mitigations (delta к ALPHA)

- (все риски из ALPHA)
- **LSP-server crash на большом проекте** 🆕: auto-restart + degraded mode (read/grep fallback); workspace isolation; health-check.
- **Tri-model race condition (concurrent tester vs executor)** 🆕: immutable partial-diff snapshots; lock-free reads; abort tester на inconsistent state.
- **DFC heat cache staleness** 🆕 (placeholder — full impl в PROD): TTL 5 минут (если реализован); confidence threshold 0.6.
- **UKB routing wrong** 🆕: explicit capability parameter; rule-based routing с fallback на parallel lookup.
- **Compaction async race (DFC.compact_warm_to_cold во время executor)** 🆕: immutable snapshots; compaction на copy, swap на idle.
- **Concurrent Tester inconsistent partial diff** 🆕: abort tester; restart с final diff; lock-free snapshot reads.
- **LSP-server startup latency (10s на большом проекте)** 🆕: lazy initialization (start on first request); cache workspace state.
- **SQLCipher key management** — env-var `ORYA_SQLCIPHER_KEY` + keyring fallback.
- **Memory-extractor LLM cost** — batch haiku, max 1 extraction per 10 messages.
- **BranchManager merge conflicts** — manual merge dialog в UI; tool-call replay.
- **LSP-server cold-start latency (jdtls до 10 s на большом Maven-проекте)** 🆕: lazy init (B-26); warm-pool в PROD (P-26); capability-router `agent_program` не блокирует turn (sync < 100 ms, LSP init в background).
- **Per-language hook fails (e.g., `checkstyle` missing)** 🆕: non-blocking, errors → `ToolMessage` warning (не ToolException); auto-detect binary via `shutil.which`; degraded mode (skip hook) если binary missing.
- **Skill-bundle conflict (2 languages в одном turn)** 🆕: max 1 skill-bundle per turn; смена языка → `SkillRegistry.deactivate(previous)` + `activate(new)`.
- **Frontend axe-hint false positives** 🆕: non-blocking suggestion-only (no turn fail); в PROD — full axe-core через Playwright с configurable rules.
- **Java JDK version mismatch (jdtls требует JDK 17+, project на JDK 11)** 🆕: auto-detect `JAVA_HOME` + `java -version`; warning если major < 17; fallback на JDK 17 runtime + project target bytecode (jdtls supports cross-compilation).
- **Rust `rust-analyzer` version drift vs `cargo`** 🆕: pin `rust-analyzer` через `rustup component add rust-analyzer` (matches toolchain); CI test на stable + nightly.
- **Go `gopls` workspace folder mismatch (`go.mod` в subdir)** 🆕: auto-detect nearest `go.mod` parent; workspace = `go.mod` dir (не session cwd).
- **Frontend CSS/HTML LSP missing в BETA** 🆕: BETA — plain `read+grep` для CSS/HTML; PROD — `vscode-css-languageserver` + `vscode-html-languageserver` (FUTURE+).

---

## 16. Forbidden patterns (delta к ALPHA)

- ❌ Использовать `read+grep` когда LSP available — LSP-first.
- ❌ Replace v6 memory-layer (L0/L1/L2) — DFC = in-window discipline.
- ❌ Direct LSP/memory calls from agent-loop bypass UKB — all retrieval through `ukb_lookup`.
- ❌ Block agent-loop на LSP-server startup — lazy initialization.
- ❌ Block executor на tester (в BETA — sequential; concurrent в P-24).
- ❌ Unbounded replan (max 2).
- ❌ LLM-based triggers на каждом turn (rule-based primary).
- ❌ Hardcoded LSP-server paths — auto-detect or through settings.
- ❌ LSP-server как FS-writer (rename — это OK, но не write/edit).
- ❌ Mix DFC layers (e.g., write to ICE from HOT) — strict layer discipline.
- ❌ Persist COLD layer в Redis — это RAM only.
- ❌ Hardcoded token limits в DFC — through settings.
- ❌ Mix LSP-server state between workspaces — workspace isolation.
- ❌ Always retrieve (default strategy = `none`).
- ❌ Hardcoded LSP-server configs в `LanguageCapabilityRegistry` — через `LSPServerConfig.LANGUAGES` table.
- ❌ Block agent-loop на `agent_program` (LSP-server lazy init в background).
- ❌ Per-language hook fails hard — non-blocking, errors → `ToolMessage` warning.
- ❌ Mix languages в одном skill-bundle (один bundle = один language; frontend TSX/JSX + CSS/HTML — один bundle).
- ❌ Use Sonnet для `agent_program` (capability-router — не LLM-call).
- ❌ Frontend LSP без TSX/JSX support (`typescript.jsx="react"` обязателен).
- ❌ Auto-format hooks modify files outside the language's extensions.
- ❌ `agent_program` без `LanguageCapabilityRegistry.resolve` (fail-closed для unsupported language).
- ❌ CSS/HTML LSP в BETA (FUTURE+ в PROD).
- ❌ Activate > 1 skill-bundle per turn.
- ❌ Bypass `CapabilityRegistry` (B-29) при активации per-language tools.

---

## 17. Структура файлов (delta к ALPHA)

```
app/
├── core/
│   ├── dfc/                        # 🆕 B-24
│   │   ├── __init__.py
│   │   ├── dfc.py                  # DFC class, 5 layers
│   │   ├── heat_cache.py           # HeatCache (placeholder)
│   │   ├── context_assembler.py    # ContextAssembler
│   │   ├── background_compactor.py # BackgroundCompactor
│   │   └── models.py               # CompactSummary
│   ├── workflow/                   # 🆕 B-25
│   │   ├── __init__.py
│   │   ├── tri_model.py            # TriModelPipeline
│   │   ├── prompts.py              # PLAN_PROMPT, TESTER_PROMPT
│   │   └── state.py                # TurnState, Plan, Verdict
│   ├── lsp/                        # 🆕 B-26
│   │   ├── __init__.py
│   │   ├── bus.py                  # LSPBus
│   │   ├── client.py               # LSPClient (stdio JSON-RPC)
│   │   ├── watcher.py              # file watcher → didChange
│   │   └── config.py               # 🆕 B-30: LSPServerConfig (per-language init options)
│   ├── ukb/                        # 🆕 B-27
│   │   ├── __init__.py
│   │   └── router.py               # UKBRouter
│   ├── retrieval/                  # 🆕 B-28
│   │   ├── __init__.py
│   │   ├── orchestrator.py         # RetrievalOrchestrator
│   │   ├── heuristics.py           # heuristics table
│   │   └── models.py               # RetrievedChunk
│   ├── tools/                      # 🆕 B-29
│   │   ├── capability_registry.py  # CapabilityRegistry
│   │   ├── triggers.py             # triggers table
│   │   └── context.py              # TurnContext
│   ├── memory/                     # v6 B-21, B-22
│   │   ├── md_store.py            # L0, 6 файлов (from MVP M-25)
│   │   ├── sqlitestore.py          # L1 (FTS5 + SQLCipher)
│   │   ├── outbox.py               # MemoryOutbox + drain-worker
│   │   ├── extractor.py            # memory-extractor (batch LLM)
│   │   └── compactor.py            # L0→L1 compaction (from MVP M-27)
│   ├── capability/                 # 🆕 B-30: per-language programming
│   │   ├── __init__.py
│   │   ├── language_registry.py    # LanguageCapabilityRegistry + LanguageCapability
│   │   └── program.py              # agent_program(language, task)
│   ├── hooks.py                    # B-04: hooks framework
│   ├── skills.py                   # B-06: skills framework
│   └── branch_manager.py           # B-09, B-10
├── tools/
│   ├── lsp.py                      # 🆕 B-26: 7 LSP tools
│   ├── ukb.py                      # 🆕 B-27: ukb_lookup tool
│   ├── oriahs_search.py            # B-02
│   ├── oriahs_index.py             # B-03
│   └── ... (5 базовых from MVP)
├── skills/                        # 🆕 B-30: per-language skill-bundles (YAML)
│   ├── java-maven.yaml             # 🆕 B-30: Java + Maven + jdtls
│   ├── rust-cargo.yaml             # 🆕 B-30: Rust + Cargo + rust-analyzer
│   ├── go-mod.yaml                 # 🆕 B-30: Go + modules + gopls
│   ├── javascript-node.yaml        # 🆕 B-30: JavaScript + Node + tsserver
│   └── frontend-tsx.yaml           # 🆕 B-30: TSX/JSX + tsserver + prettier + axe
├── hooks/                         # 🆕 B-30: per-language hook-sets
│   ├── auto_format_google_java_format.py
│   ├── auto_format_rustfmt.py
│   ├── auto_format_gofmt.py
│   ├── auto_format_prettier.py
│   ├── auto_lint_checkstyle.py
│   ├── auto_lint_clippy.py
│   ├── auto_lint_govet.py
│   ├── auto_lint_eslint.py
│   └── accessibility_hint_axe.py
│   └── ... (5 базовых from MVP)
├── mcp/
│   ├── lsp_mcp.py                  # 🆕 B-26: MCP wrapper for LSP
│   └── oriahs_mcp.py               # B-01
├── api/
│   ├── capability.py               # 🆕 B-30: GET /capability/languages, POST /capability/program
│   ├── remember.py                 # B-23: /remember, /forget
│   ├── memory.py                   # B-23: /memory list/export/import (extended)
│   ├── branches.py                 # B-09, B-10: fork/merge
│   ├── skills.py                   # B-07, B-19
│   └── hooks.py                    # B-04, B-20
└── web/                            # Next.js Web UI (B-11..B-20)
    ├── package.json
    ├── app/
    │   ├── page.tsx                # chat interface
    │   ├── sessions/               # sidebar
    │   ├── settings/
    │   ├── memory/                 # memory UI
    │   ├── branches/               # branch manager
    │   └── skills/                 # skills browser
    └── components/

tests/
├── test_dfc.py                     # 🆕
├── test_dfc_heat_cache.py          # 🆕
├── test_dfc_background_compactor.py # 🆕
├── test_tri_model.py               # 🆕
├── test_lsp_bus.py                 # 🆕
├── test_lsp_tools.py               # 🆕
├── test_ukb_router.py              # 🆕
├── test_retrieval_orchestrator.py  # 🆕
├── test_capability_registry.py     # 🆕
├── test_language_capability_registry.py # 🆕 B-30
├── test_agent_program.py           # 🆕 B-30
├── test_lsp_config.py              # 🆕 B-30
├── test_sqlitestore.py             # v6 B-21
├── test_memory_extractor.py        # v6 B-22
├── test_remember_forget.py         # v6 B-23
├── test_branch_manager.py          # v6 B-09, B-10
├── test_hooks.py                   # v6 B-04, B-05
├── test_skills.py                  # v6 B-06, B-07
└── fixtures/
    ├── synthetic_dataset.yml       # 🆕 B-25: 10 tri-model scenarios
    ├── retrieval_scenarios.yml     # 🆕 B-28: 10 retrieval scenarios
    ├── test_proj/                  # 🆕 B-26: small Python/TS/Rust/Go/Java/Lua projects
    └── multi_lang_proj/            # 🆕 B-30: small Java/Rust/Go/JS/TSX projects for testing
```

---

## 18. API surface (delta к ALPHA)

| Method | Endpoint | Phase | Назначение |
|---|---|---|---|
| `GET` | `/sessions/{id}/dfc/state` | BETA | Просмотр DFC state (для debugging) |
| `POST` | `/sessions/{id}/dfc/compact` | BETA | Принудительная context compaction (WARM→COLD) |
| `GET` | `/lsp/status` | BETA | Статус LSP-серверов (uptime, latency) |
| `POST` | `/lsp/restart/{language}` | BETA | Restart LSP-сервера (если завис) |
| `POST` | `/remember` | BETA (v6 B-23) | Add fact to memory (L0 or L1) |
| `DELETE` | `/forget/{memory_id}` | BETA (v6 B-23) | Forget specific memory |
| `GET` | `/memory` | BETA (v6 B-23) | List all memories (L0 + L1) |
| `POST` | `/memory/export` | BETA (v6 B-23) | Export all memories as JSON |
| `POST` | `/memory/import` | BETA (v6 B-23) | Import memories from JSON |
| `POST` | `/sessions/{id}/fork` | BETA (v6 B-09) | Fork session at specific turn |
| `POST` | `/sessions/{id}/merge` | BETA (v6 B-10) | Merge branch into main |
| `GET` | `/skills` | BETA (v6 B-06) | List available skills |
| `POST` | `/skills/{name}/activate` | BETA (v6 B-06) | Activate skill for session |
| `GET` | `/hooks/executed` | BETA (v6 B-04) | Audit log of executed hooks |
| `GET` | `/capability/languages` | BETA (B-30) | List supported languages + LSP-binding'и (java/rust/go/javascript/frontend/python/typescript/lua) |
| `POST` | `/capability/program` | BETA (B-30) | Activate `agent_program(language, task)` — activates skill-bundle + hook-set + LSP-server (lazy) |
| `GET` | `/capability/active` | BETA (B-30) | Currently active language + skill-bundle + hooks для session |
| `GET` | `/lsp/config/{language}` | BETA (B-30) | Per-language `LSPServerConfig` (init options, file-exts, build/test/lint/format cmds) |

---

## 19. Observability: расширенные spans (delta к ALPHA)

| Span type | Атрибуты | Фаза |
|---|---|---|
| `agent.plan` | `agent.plan.tier`, `agent.plan.steps_count`, `agent.plan.criteria_count` | BETA 🆕 |
| `agent.execute` | `agent.execute.tier`, `agent.execute.degraded`, `agent.execute.model` | ALPHA (extended в BETA) |
| `agent.test` | `agent.test.verdict`, `agent.test.concurrent`, `agent.test.early_abort` | BETA 🆕 |
| `agent.test.concurrent` | `agent.test.concurrent.overlap_ms`, `agent.test.concurrent.abort_reason` | BETA basic (full в P-24) |
| `dfc.assemble_hot` | `dfc.heat_hit`, `dfc.hot_size_tokens`, `dfc.warm_demoted`, `dfc.cold_compacted` | BETA 🆕 |
| `dfc.compact` | `dfc.compact.layer_from`, `dfc.compact.layer_to`, `dfc.compact.items_count` | BETA 🆕 |
| `lsp.call` | `lsp.method`, `lsp.language`, `lsp.latency_ms`, `lsp.degraded` | BETA 🆕 |
| `ukb.lookup` | `ukb.capability`, `ukb.namespace`, `ukb.top_k`, `ukb.merge_dedup_count` | BETA 🆕 |
| `retrieval.orchestrate` | `retrieval.strategy`, `retrieval.query`, `retrieval.rerank_applied` | BETA 🆕 |
| `capability.filter` | `capability.active_count`, `capability.filtered_out_count` | BETA 🆕 |
| `language.program` | `language.name`, `language.lsp_server`, `language.skill_count`, `language.hook_count`, `language.build_cmd`, `language.test_cmd` | BETA 🆕 (B-30) |
| `memory.extract` | `memory.extract.facts_count`, `memory.extract.source_messages` | BETA (v6 B-22) |
| `branch.fork` | `branch.source_turn`, `branch.new_session_id` | BETA (v6 B-09) |
| `branch.merge` | `branch.source_session`, `branch.target_session`, `branch.conflicts_count` | BETA (v6 B-10) |

---

## 20. Порядок реализации (рекомендуемый)

### Недели 1-2 (v6 BETA baseline)

1. **Неделя 1:** B-01 (oriahs-mcp), B-02 (oriahs_search), B-03 (oriahs_index), B-04 (hooks framework), B-05 (auto-format hook), B-06 (skills framework), B-07 (code-review skill).
2. **Неделя 2:** B-09 (BranchManager fork), B-10 (BranchManager merge), B-21 (SQLiteStore L1), B-22 (memory-extractor), B-23 (/remember, /forget, /memory/*).

Демонстрация: MCP + hooks + skills + BranchManager + L1 memory работают.

### Недели 3-4 (Next.js Web UI)

3. **Неделя 3:** B-11 (Next.js chat), B-12 (sidebar), B-13 (settings), B-14 (tool-call viz), B-15 (WebSocket streaming).
4. **Неделя 4:** B-16 (memory UI), B-17 (import/export UI), B-18 (branch UI), B-19 (skills UI), B-20 (hooks UI).

Демонстрация: full Next.js UI parallel to Chainlit.

### Недели 5-7 (v7 BETA additions — 6 новых примитивов)

5. **Неделя 5:** B-26 (LSP-bus + 6 servers + 7 tools — 7 дней, самый объёмный). Демонстрация: LSP-tools работают, sub-ms latency.
6. **Неделя 6:** B-24 (DFC — 5 дней), B-25 (Tri-Model — 4 дня, параллельно с B-24). Демонстрация: tri-model pipeline, DFC держит окно ≤16K.
7. **Неделя 7:** B-27 (UKB — 3 дня), B-28 (RetrievalOrchestrator — 4 дня), B-29 (CapabilityRegistry — 2 дня). Демонстрация: UKB unified retrieval, orchestrator 7 strategies, capability filter 8-15 tools.
8. **Неделя 7 (продолжение):** B-30 (Multi-language programming capabilities — 5 дней, параллельно с B-28/B-29 во второй половине недели). Демонстрация: `agent_program("java"|"rust"|"go"|"javascript"|"frontend", task)` активирует per-language skill-bundle + hook-set + LSP-server; auto-format и auto-lint hooks работают; per-language refactor-recipes через `lsp_code_action`.

---

## 21. Exit criteria (переход BETA → PROD)

- ✅ (все exit-criteria из ALPHA → BETA)
- ✅ L1 SQLiteStore работает: insert, search, forget, supersede, export, import.
- ✅ SQLCipher encryption: файл не читается без ключа.
- ✅ Outbox-drain-worker работает с retry.
- ✅ Memory-extractor: после 10 сообщений — async extraction.
- ✅ /remember, /forget, /memory list/export/import работают end-to-end.
- ✅ MCP: oriahs-mcp работает, oriahs_search, oriahs_index доступны.
- ✅ Hooks + Skills frameworks работают.
- ✅ BranchManager: fork/merge работает.
- ✅ Next.js Web UI: chat, sidebar, settings, tool-call viz, WebSocket streaming.
- ✅ **DFC: tokens per turn ≤ 16K на типичном ходе (vs v6 30-60K).**
- ✅ **Tri-Model Pipeline: verdict rate (pass на 1st attempt) > 75%.**
- ✅ **LSP-native: 6 языков поддерживается, latency < 10 ms p95.**
- ✅ **UKB: 5 namespaces routing (lsp, oriahs, memory, code, kb) — partial в BETA (lsp + memory).**
- ✅ **RetrievalOrchestrator: 7 strategies, decision accuracy > 75%.**
- ✅ **CapabilityRegistry: active tools per turn ≤ 15 (vs ~25+ без registry).**
- ✅ **B-30 Multi-language: `agent_program("java"|"rust"|"go"|"javascript"|"frontend", task)` работает end-to-end (skill-bundle + hook-set + LSP-server).**
- ✅ **Per-language skill-bundles (5 YAML): java-maven, rust-cargo, go-mod, javascript-node, frontend-tsx.**
- ✅ **Per-language hook-sets (9 hooks): auto-format (4) + auto-lint (4) + accessibility-hint-axe (frontend).**
- ✅ **Per-language LSP-config: jdtls / rust-analyzer / gopls / typescript-language-server с правильными init options.**
- ✅ **Latency p95 `agent_program` (warm LSP): < 100 ms; cold-start: < 10 s (jdtls), < 5 s (rust-analyzer), < 3 s (gopls/tsserver).**
- ✅ **Frontend TSX/JSX через tsserver (`typescript.jsx="react"`); CSS/HTML LSP — FUTURE+ (PROD).**

---

## 22. UI-стратегия (delta к ALPHA)

| Фаза | UI |
|---|---|
| MVP | (без UI-изменений от v6) |
| ALPHA | (без UI-изменений) |
| **BETA** | **Next.js: DFC inspector (HEAT/HOT/WARM/COLD/ICE видимость), tier indicator (small/large/tournament), LSP-server status panel** |
| **BETA (B-30)** | **+ Active language indicator (java/rust/go/javascript/frontend) + skill-bundle badge + hook-set status (auto-format/auto-lint) + LSP-config viewer (`/lsp/config/{language}`)** |
| PROD | + Tournament progress, Batch dashboard, Predictive hints visualization |

---

## 23. Безопасность (delta к ALPHA)

| Мера | Фаза | Описание |
|---|---|---|
| LSP-server sandbox (separate process, no FS write) | BETA | LSP не может писать в ФС (только read + diagnostics) |
| LSP-rename safety check | BETA | Подтверждение пользователем для rename > 100 refs |
| SQLCipher encryption for L1 | BETA (v6) | L1 memory зашифрована |
| Workspace isolation для LSP | BETA | LSP-servers не делят state между workspaces |
| DFC state не persisted в PostgreSQL | BETA | in-memory only, восстанавливается из session-log + LSP + UKB |
| CapabilityRegistry default deny | BETA | tools invisible по умолчанию, visible только через triggers |
| Per-language hook sandbox (no FS write outside file-exts) | BETA (B-30) | auto-format/auto-lint hooks могут модифицировать только файлы своих расширений (`.java`/`.rs`/`.go`/`.js`/`.tsx`/`.jsx`/`.css`/`.html`); enforced через `validate_path()` + extension check (v6 `_validators.py`) |
| Per-language build/test/lint cmd injection guard | BETA (B-30) | commands из settings (`ORYA_<LANG>_*_CMD`), не от LLM; `wrap_untrusted()` на output (v6 security seam) |
| axe-hint non-blocking | BETA (B-30) | accessibility hint не может fail turn (suggestion-only) |
| `agent_program` fail-closed для unsupported language | BETA (B-30) | unknown language → `ValueError`, no fallback |

---

## 24. Ссылки на исходные документы

- `ARCHITECT7.md` §3 (улучшения #18, #19, #20, #22, #27, #28), §6.1-6.4 (модули dfc/tri_model/lsp/ukb), §6.7-6.8 (retrieval/capability), §6.11-6.12 (system-prompt + ukb.lookup tool), §7 (схема данных), §8 (API surface), §14.2 (LOC delta +5000), §16.1 (риски v7 BETA).
- `ROADMAP7.md` §5 (Фаза BETA), §11.3 (BETA → PROD exit criteria), §13 (NFR-таргеты по фазам), §21 (UI-стратегия).
- `BACKLOG7.md` §4 (B-24..B-29 — детальные спецификации).
- `BACKLOG6.md` §4 (B-00..B-23 — v6 BETA baseline).
- `ROADMAP6.md` §5 (Фаза BETA v6).
- `analytics/adr/ADR-0001-dynamic-fast-context.md` — DFC.
- `analytics/adr/ADR-0002-lsp-native-code-facts.md` — LSP-native.
- `analytics/adr/ADR-0003-tri-model-plan-execute-test.md` — Tri-Model.
- `analytics/adr/ADR-0010-background-compaction.md` — Background compaction.
- `analytics/orya-architect2/adr/ADR-004-retrieval-orchestrator.md` — RetrievalOrchestrator.
- `analytics/orya-architect2/adr/ADR-007-tool-discovery-via-mcp.md` — CapabilityRegistry.
- `analytics/orya-architect2/adr/ADR-001-mcp-as-primary-tool-contract.md` — UKB.
- `analytics/adr/ADR-0002-lsp-native-code-facts.md` §extension (B-30) — per-language programming capabilities + skill-bundles + hook-sets + LSP-config matrix (Java/Rust/Go/JS/Frontend).
- `analytics/orya-architect2/adr/ADR-007-tool-discovery-via-mcp.md` §extension (B-30) — `LanguageCapabilityRegistry` надстройка над `CapabilityRegistry` (B-29).

---

**Готов к реализации.** После завершения BETA переходи к фазе PROD (`PROMPT_PROD.md`) — там добавятся Batch Pipeline, Symbolic Shortcut, Predictive Planner, Tournament, Concurrent Tester, RerankPolicy, Best-of-N.
