# ПРОМПТ ФАЗЫ BETA — OryaAgent v7

> **Версия промпта:** 7.0
> **Дата:** 20 октября 2026
> **Источники:** `ARCHITECT7.md` v7.0 (§3 #18, #19, #20, #22, #27, #28; §6.1-6.4, §6.7-6.8, §6.11-6.12; §7; §8; §14.2; §16.1), `ROADMAP7.md` v7.0 (§5, §11.3, §13), `BACKLOG7.md` v7.0 (§4 — B-24..B-29), `BACKLOG6.md` v6.0 (§4 — B-00..B-23), `ROADMAP6.md` v6.0 (§5), ADR-0001 (DFC), ADR-0002 (LSP-native), ADR-0003 (Tri-Model), ADR-0010 (Background compaction), ADR-v02-004 (Retrieval orchestrator), ADR-v02-007 (Tool discovery), ADR-v03-100 (UKB)
> **Стек:** Python 3.11+, LangChain 0.3+, LangGraph 0.2+, FastAPI, PostgreSQL 16, Redis 7, Chainlit, Next.js, OriaHS, OryaObservability SDK, **LSP-серверы** (pyright, typescript-language-server, rust-analyzer, gopls, jdtls, lua-language-server), `watchdog` (file watcher), MCP SDK
> **Длительность:** 7 недель (поверх готового ALPHA)
> **Объём кода:** ~13000 LOC (v6 BETA ~8000 + 5000 новых v7)
> **Статус в v7:** BETA = v6 BETA + 6 новых архитектурных примитивов (DFC, Tri-Model, LSP-native, UKB, RetrievalOrchestrator, CapabilityRegistry)

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

## 3. Полный список тикетов фазы (B-00 … B-29)

v6 BETA содержит 24 тикета (B-00..B-23). v7 добавляет 6 новых (B-24..B-29). Полный перечень — 30 тикетов.

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

### 3.2. Новые v7 BETA тикеты — детальные спецификации

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

## 10. Архитектура BETA (delta к ALPHA)

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

## 11. Целевые NFR (delta к ALPHA)

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

## 12. Definition of Done (delta к ALPHA)

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
- ✅ **`orya_capability_filter_active_count` metric exported.**

---

## 13. TRIZ-gates фазы (delta к ALPHA)

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

---

## 14. Risks и mitigations (delta к ALPHA)

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

---

## 15. Forbidden patterns (delta к ALPHA)

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

---

## 16. Структура файлов (delta к ALPHA)

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
│   │   └── watcher.py              # file watcher → didChange
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
│   ├── hooks.py                    # B-04: hooks framework
│   ├── skills.py                   # B-06: skills framework
│   └── branch_manager.py           # B-09, B-10
├── tools/
│   ├── lsp.py                      # 🆕 B-26: 7 LSP tools
│   ├── ukb.py                      # 🆕 B-27: ukb_lookup tool
│   ├── oriahs_search.py            # B-02
│   ├── oriahs_index.py             # B-03
│   └── ... (5 базовых from MVP)
├── mcp/
│   ├── lsp_mcp.py                  # 🆕 B-26: MCP wrapper for LSP
│   └── oriahs_mcp.py               # B-01
├── api/
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
├── test_sqlitestore.py             # v6 B-21
├── test_memory_extractor.py        # v6 B-22
├── test_remember_forget.py         # v6 B-23
├── test_branch_manager.py          # v6 B-09, B-10
├── test_hooks.py                   # v6 B-04, B-05
├── test_skills.py                  # v6 B-06, B-07
└── fixtures/
    ├── synthetic_dataset.yml       # 🆕 B-25: 10 tri-model scenarios
    ├── retrieval_scenarios.yml     # 🆕 B-28: 10 retrieval scenarios
    └── test_proj/                  # 🆕 B-26: small Python/TS/Rust/Go/Java/Lua projects
```

---

## 17. API surface (delta к ALPHA)

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

---

## 18. Observability: расширенные spans (delta к ALPHA)

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
| `memory.extract` | `memory.extract.facts_count`, `memory.extract.source_messages` | BETA (v6 B-22) |
| `branch.fork` | `branch.source_turn`, `branch.new_session_id` | BETA (v6 B-09) |
| `branch.merge` | `branch.source_session`, `branch.target_session`, `branch.conflicts_count` | BETA (v6 B-10) |

---

## 19. Порядок реализации (рекомендуемый)

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

---

## 20. Exit criteria (переход BETA → PROD)

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

---

## 21. UI-стратегия (delta к ALPHA)

| Фаза | UI |
|---|---|
| MVP | (без UI-изменений от v6) |
| ALPHA | (без UI-изменений) |
| **BETA** | **Next.js: DFC inspector (HEAT/HOT/WARM/COLD/ICE видимость), tier indicator (small/large/tournament), LSP-server status panel** |
| PROD | + Tournament progress, Batch dashboard, Predictive hints visualization |

---

## 22. Безопасность (delta к ALPHA)

| Мера | Фаза | Описание |
|---|---|---|
| LSP-server sandbox (separate process, no FS write) | BETA | LSP не может писать в ФС (только read + diagnostics) |
| LSP-rename safety check | BETA | Подтверждение пользователем для rename > 100 refs |
| SQLCipher encryption for L1 | BETA (v6) | L1 memory зашифрована |
| Workspace isolation для LSP | BETA | LSP-servers не делят state между workspaces |
| DFC state не persisted в PostgreSQL | BETA | in-memory only, восстанавливается из session-log + LSP + UKB |
| CapabilityRegistry default deny | BETA | tools invisible по умолчанию, visible только через triggers |

---

## 23. Ссылки на исходные документы

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

---

**Готов к реализации.** После завершения BETA переходи к фазе PROD (`PROMPT_PROD.md`) — там добавятся Batch Pipeline, Symbolic Shortcut, Predictive Planner, Tournament, Concurrent Tester, RerankPolicy, Best-of-N.
