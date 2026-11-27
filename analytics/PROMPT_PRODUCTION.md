# ПРОМПТ ФАЗЫ PRODUCTION (PROD) — OryaAgent v7

> **Версия промпта:** 7.0
> **Дата:** 27 ноября 2026
> **Источники:** `analytics/ARCHITECT.md` (ARCHITECT7) §3 (улучшения #21, #23, #24, #25, #26, #29, #31), §6.5-6.7, §6.10, §7.4-7.5, §8.1; `analytics/ROADMAP.md` (ROADMAP7) §6 (Фаза PROD), §11.3-11.4 (exit criteria), §13 (NFR-таргеты); `analytics/BACKLOG.md` (BACKLOG7) §5 (P-20..P-26), §9-10 (матрица и карта зависимостей); `analytics/old/BACKLOG6.md` §5 (P-18..P-19); `analytics/old/BACKLOG5.md` §5 (P-00..P-17); `analytics/old/ROADMAP6.md` §6; `AGENTS.md` (конвенции репозитория, uv/ruff/тесты). Приложения: парсер AGENTS.md — адаптация TypeScript-промптов opencode/kilocode на Python; аналоги отсутствующих команд opencode — по итогам анализа логов (`oryaagent.json`, сессия «Статистика команд OryaAgent»).
> **Стек:** Python 3.11+ (venv 3.12), LangChain 0.3+, LangGraph 0.2+, FastAPI, PostgreSQL 16, Redis 7, Chainlit + Next.js, OriaHS (MCP), OryaObservability SDK, LSP-серверы (B-26), judge-mcp (новое в PROD), локальная small-модель через Ollama (Qwen-3B / Llama-3.2-1B, новое в PROD), `tree-sitter`, `PyYAML`, `python-frontmatter` (опц.), `pytest` + `ruff`.
> **Длительность:** 9 недель (v6 PROD ~6 недель + 3 недели v7 power-features), поверх готового BETA.
> **Объём кода:** ~13000 LOC v6 PROD + ~5000 LOC v7 (P-20..P-26).
> **Статус в v7:** PROD = v6 PROD (OriaHS + L2 Qdrant memory + distributed tracing + sandbox/multi-tenant/A-B/DR) + **7 power-features v7** (Batch Pipeline, Symbolic Shortcut, Predictive Planner, Tournament + judge-mcp, Concurrent Tester, RerankPolicy, Best-of-N).

---

## Промпт (ранний, приоритетный): Изоляция параллельных исполнителей и cost-границы — без ошибок в интерфейсе

> **Источник паттерна:** `anomalyco/opencode` — модель параллельных subagent-сессий с собственным step-состоянием + cost/retry-бюджеты из `model-retry.ts`. Этот промпт имеет приоритет над любыми последующими инструкциями фазы PROD, описывающими параллельное выполнение и бюджеты.

### Постулат

Любое параллельное выполнение в PROD (Batch Pipeline, Tournament, Best-of-N, Concurrent Tester, prefetch) **никогда не делит мутируемое состояние** между конкурентными задачами и **никогда не выбрасывает cost/limit-ошибку в интерфейс пользователя**. Деградация (degrade на single executor, деградация rerank-цепочки, отказ prefetch) — это нормальный ход работы системы, а не сбой: в UI виден обычный стрим ответа, в span'ах — атрибут `*.degraded=true`.

### Принцип 1. Immutable snapshot вместо общего состояния

Каждый параллельный executor получает **неизменяемый слепок** контекста: `dfc.snapshot()` (B-24) копируется на старте задачи; результаты пишутся в собственный result-slot задачи, а не в общий стейт графа. Запрещено: передавать между параллельными задачами один и тот же `dict`/`messages`-list, мутировать Heat Cache из двух задач одновременно без блокировки, делить LRU-кэш rerank между потоками без `threading.Lock`.

### Принцип 2. Cost-границы срабатывают ДО запуска, деградация — тихая

- Перед запуском Tournament/Best-of-N считай `estimated_cost = N × средняя стоимость хода` и сравни с `max_cost_usd` (default $0.10 для Tournament, $0.05 — порог Best-of-N). Превышение → **заранее** деградируй на single executor (обычный tri-model ход), а не обрывай уже запущенные.
- Degrade помечается span-атрибутом (`tournament.degraded=true`, `best_of_n.skipped=true`) и метрикой — но НЕ показывается пользователю как ошибка. Ответ ассистента в UI — обычный.
- Бюджетная блокировка на 100% (A-13 CostAwareRouter) возвращает пользователю текстовый итог с планом действий, не exception.

### Принцип 3. Отказ одной параллельной задачи не валидит батч

В BatchRunner отказ/таймаут одной задачи — запись `{status: "error"|"timeout", ...}` в её строку `results.jsonl`; остальные задачи продолжаются. Исключение из `_run_task` ловится на границе задачи, логируется в span `batch.run` (атрибут `batch.status=error`), и **не всплывает** как uncaught в endpoint `POST /batch/run/async` — клиент получает `{job_id}` и прогресс через `GET /batch/status/{job_id}`.

### Контракт для OryaAgent PROD (обязательно к реализации)

- **`TournamentExecutor` / `BestOfNExecutor` (Python, LangGraph):** N параллельных `asyncio`-задач, каждой — `snapshot = dfc.snapshot()`; сборка результата — `asyncio.gather(..., return_exceptions=True)`; исключения исполнителей конвертируются в candidates со `status=error`, judge/tester видит их как обычных кандидатов. Degrade по бюджету — до запуска.
- **`BatchRunner`:** `asyncio.Semaphore(parallel=4)`; per-task try/except; частичный прогресс в job-store (Redis) после каждой задачи; process-level изоляция DFC-стейта между задачами.
- **`PredictivePlanner`:** background-таск, любые исключения внутри tick гасятся логом + метрикой `predictive_planner_miss_total`, loop агента никогда не блокируется.
- **Chainlit / Next.js UI:** никаких error-баннеров на degrade/abort/limit — только обычный стрим; audit — через span'ы и Hooks UI.

### Антипаттерны (запрещены в PROD)

- Общий мутируемый DFC/стейт между параллельными исполнителями.
- `raise` cost/limit-ошибок сквозь граф в UI.
- Sequential-выполнение батча (1 задача за раз) — parallel default 4.
- Запуск Tournament без предварительной оценки стоимости.

---

## 0. Контекст и роль

Ты — senior Python-разработчик, продолжаешь реализацию OryaAgent v7 в репозитории `Reider85/OryaAgent`. Фазы MVP (M-00…M-27 + MVP-POLISH) и ALPHA (A-00…A-20) **завершены и влиты**, BETA (B-24…B-29: DFC, Tri-Model, LSP-native, UKB, RetrievalOrchestrator, CapabilityRegistry) должна быть завершена до старта этой фазы. Твоя задача — реализовать **фазу PROD** по тикетам ниже.

Обязательные правила работы (из `AGENTS.md`, нарушение = переделка):

1. **Спека тикета** — сначала grep по `analytics/` для id тикета; полные чтения `ARCHITECT*.md`/`BACKLOG*.md`/`ROADMAP*.md` (50-120KB) почти никогда не нужны. Выполненные планы в `.opencode/plans/*.md` при конфликте **переопределяют** старые спеки.
2. **Команды (uv):** установка `uv sync`; тесты `uv run pytest`; линт-гейт `make lint` = `uv run ruff check .` + `uv run ruff format --check .`; порядок перед завершением: **format → lint → test**. mypy/pre-commit/CI не существуют — не ссылайся на них.
3. **Тесты:** `tests/unit` (всегда), `tests/integration` (инфра-условные), `tests/e2e`, `tests/smoke` (всегда). `asyncio_mode=auto` — без `@pytest.mark.asyncio`. Конфиг-тесты обязаны сандбокситься: `monkeypatch.chdir(tmp_path)`, удалить `ORYA_*` env, `clear_settings_cache()` до и после.
4. **Архитектура:** единственный LLM-seam — `app/core/llm/` (никогда не импортируй `langchain_anthropic`/`langchain_openai` вне него); `get_tools()` возвращает инструменты **в фиксированном порядке** — расширяй список осознанно и обновляй `EXPECTED_NAMES` в `tests/integration/test_tools_integration.py`; граф не импортирует `prompt.py`/`context.py` (инжектируемые callables); схема БД — три правки (`schema.sql` + `migrations/NNNN_name.sql` + `alembic/versions/NNNN_name.py`).
5. **Конвенции инструментов:** `@tool` + async + `Annotated[str, "..."]`; блокирующая работа через `asyncio.to_thread`; ошибки — `ToolException` (chain `from exc`); FS-инструменты вызывают `validate_path()` (`app/tools/_validators.py`, allowed roots: cwd, `~/.orya`, `settings.memory_dir`); записи атомарны (`mkstemp` → fsync → `os.replace`); вывод через `wrap_untrusted()`/`detect_injection()`; bash-подобные инструменты возвращают один JSON-документ; read-only — можно `get_cache()`, write/edit/bash — никогда (инвалидация `invalidate_cache_for_path()`).
6. **Добавление инструмента = 5 шагов:** `app/tools/<name>.py` + реэкспорт в `__init__.py` + запись в `get_tools()` + `EXPECTED_NAMES`/`EXPECTED_REQUIRED_ARGS` в `tests/integration/test_tools_integration.py` + unit-тесты; read-only — добавить в permission-allowlist.
7. **Конвенции кода:** docstring модуля открывается id тикета (`"""Tool: batch runner (P-20).`); коммиты `P-20: batch runner (...)`; ruff line-length 88, double quotes, isort.

---

## 1. Цели фазы

### 1.1. Цели v6 PROD (базовые, остаются в силе)

- Full-stack memory: L0 (MD) + L1 (SQLite FTS5) + **L2 Qdrant через OriaHS** (semantic) + `memory_search` tool (гибрид).
- Distributed tracing через MCP-границу (W3C TraceContext) + offline-eval для `/learn`.
- OriaHS-интеграция для codebase (bootstrap, search, incremental index, git-aware reindex, tree-sitter chunker).
- Production-инфраструктура: multi-tenant RLS, sandbox (bwrap + egress-filter), A/B-framework, Context Epoch, LLM-migration, shadow-traffic, chaos engineering, backup & DR, Grafana-дашборды.
- Speculative pre-fetcher (v6, rule-based) и streaming partial results.

### 1.2. Новые цели v7 PROD — 7 power-features

Без этих семи улучшений v7 остаётся «v6 + DFC + LSP» — хорошая, но не уникальная система. Цель — закрыть **power-features gap**:

1. **Batch Pipeline (P-20)** — `prompts.yml → results.jsonl` + benchmark comparator + CLI.
2. **Symbolic Shortcut (P-21)** — LLM bypass для rename/format/organize-imports (500-1500 ms вместо 2-6 s).
3. **Predictive Planner (P-22)** — forecast следующего промпта, prefetch в Heat Cache до прихода.
4. **Tournament + judge-mcp (P-23)** — N параллельных исполнителей + judge-модель.
5. **Concurrent Tester (P-24)** — overlap тестера с исполнителем на partial diff, early-exit.
6. **RerankPolicy (P-25)** — policy-driven rerank skip + fallback chain.
7. **Best-of-N (P-26)** — упрощённый Tournament без judge (criteria-match).

**Принцип PROD v7:** +3 недели и ~5000 LOC к v6 PROD, но система получает self-improvement loop (batch benchmark), latency-прорыв (symbolic + predictive) и quality-механику (tournament).

---

## 2. Технологический стек (delta к BETA)

| Компонент | Статус | Заметки |
|---|---|---|
| Python 3.11+ / uv / ruff | как в BETA | venv 3.12, `asyncio_mode=auto` |
| LangGraph 0.2+ | как в BETA | расширение tri_model, новые workflow-ноды |
| **judge-mcp (MCP-сервер judge-вызовов)** | 🆕 PROD | `app/mcp/judge_mcp.py`, модель Sonnet (small) |
| **Ollama (локальная small-модель)** | 🆕 PROD | Qwen-3B / Llama-3.2-1B для PredictivePlanner; fallback Haiku-3.5 |
| **tree-sitter** | 🆕 PROD (P-03) | code-chunker для индексации OriaHS |
| **Qdrant через OriaHS MCP** | 🆕 PROD (P-18) | collection `agent_memory`, 1024-dim bge-m3, Cosine, `on_disk_payload=true` |
| OpenTelemetry propagation | 🆕 PROD (P-19) | W3C TraceContext через MCP-headers |
| bwrap / egress-filter | 🆕 PROD (P-08) | sandbox shell-команд; на Windows — Job Objects + allowlist |
| PyYAML | есть | frontmatter/`prompts.yml` |
| Grafana + Prometheus | есть с A-17 | + новые дашборды (Memory Health, Batch, Tournament) |

---

## 3. Полный список тикетов фазы (P-00 … P-26)

v6 PROD содержит 20 тикетов (P-00..P-19). v7 добавляет 7 новых (P-20..P-26). Полный перечень — 27 тикетов, ~26 дней суммарной оценки.

### 3.1. v6 PROD baseline (P-00 … P-19) — реализуй без изменений

> ⚠️ **Перед реализацией проверь текущее состояние репозитория:** часть v6-инструментов уже реализована в коде (например, `oriahs_search`/`oriahs_index` присутствуют в tool-registry). Grep по `analytics/` для id тикета + grep по `app/` и `tests/`, и реализуй только недостающее. Выполненные планы `.opencode/plans/*.md` переопределяют спеки.

| ID | Title | Estimate | Заметки |
|---|---|---|---|
| P-00 | PROD bootstrap: OriaHS connection | 1 день | подключение к OriaHS через MCP |
| P-01 | Tool: oriahs_search | 1 день | semantic codebase search через MCP |
| P-02 | Tool: oriahs_index (incremental) | 1 день | инкрементальное индексирование |
| P-03 | Code-chunker (tree-sitter) | 1 день | AST-aware чанкинг для индекса |
| P-04 | Tool: oriahs_wait_index + oriahs_delete | 4 часа | синхронизация индекса |
| P-05 | Tool: reindex_codebase (git-aware) | 1 день | reindex по git-diff |
| P-06 | Multi-tenant RLS | 1 день | row-level security в PostgreSQL |
| P-07 | A/B-framework (full) | 2 дня | конфиги-варианты, метрики по вариантам |
| P-08 | Sandbox: bwrap + egress-filter | 2 дня | изоляция bash-команд |
| P-09 | Context Epoch | 1 день | инвалидация контекст-кэша по эпохе |
| P-10 | LLM-migration framework | 1 день | безопасная смена модели/провайдера |
| P-11 | Shadow-traffic | 1 день | дубль-прогоны без влияния на ответ |
| P-12 | Chaos engineering | 1 день | инжекция отказов в тестах |
| P-13 | Backup & DR | 1 день | бэкапы PostgreSQL + L0/L1 |
| P-14 | PROD DoD integration test (расширенный) | 4 часа | сквозной прогон всех P- |
| P-15 | Monitoring dashboards (Grafana) | 1 день | provisioning-JSON, не ручной импорт |
| P-16 | Speculative pre-fetcher | 1 день | rule-based prefetch (v5, обновлено) |
| P-17 | Streaming partial results | 1 день | стрим частичных результатов |
| P-18 | **L2 Qdrant via OriaHS (memory collection) + memory_search tool** | 1 день | v6: гибрид L1 lexical + L2 semantic |
| P-19 | **Distributed tracing через MCP + offline-eval для /learn** | 1 день | v6: W3C headers, learn_reuse_rate |

Детальные спеки P-18/P-19 — в `analytics/old/BACKLOG6.md` §5 (ключевые контракты: коллекция `agent_memory` 1024-dim Cosine с payload `memory_id, type, project, source, created_at, confidence`; merge weighted lexical 0.4 / semantic 0.6, dedup by memory_id, per-project isolation с `project=__global__`; span `memory.read`; `MCPClient.callTool` инжектит `MCP-Trace-Id`/`MCP-Span-Id`/`MCP-Parent-Span-Id`; trace-completeness > 95%; `eval/datasets/agent_learn_quality.jsonl` 20 сценариев; nightly-джоба считает `learn_reuse_rate` > 30% за 30 дней; Grafana «OryaAgent Memory Health» — provisioning only).

**Forbidden patterns v6 PROD (наследуются):** Qdrant напрямую мимо OriaHS; cross-project items без пометки `global=true`; хардкод trace_id мимо `propagation.inject`; offline-eval на production-данных; ручной импорт Grafana-дашбордов; `memory_search` на каждом turn (только по необходимости).

### 3.2. Новые v7 PROD тикеты — детальные спецификации (P-20..P-26)

Карта зависимостей (реализуй в этом порядке):

```
v6 PROD done + B-25 (Tri-Model) + B-24 (DFC) → P-20 (Batch Pipeline)
B-25 (Tri-Model) + B-26 (LSP) + B-29 (CapabilityRegistry) → P-21 (Symbolic Classifier)
B-24 (DFC Heat Cache) + B-25 (Tri-Model) → P-22 (Predictive Planner)
B-25 (Tri-Model) + A-18 (TieredModelRouter) + B-24 (DFC snapshot) → P-23 (Tournament)
B-25 (Tri-Model) → P-24 (Concurrent Tester extension)
B-27 (UKB) + B-28 (RetrievalOrchestrator) + v6 P-00 (OriaHS) → P-25 (RerankPolicy)
P-23 (Tournament) → P-26 (Best-of-N simplified)
```

---

## 4. P-20 — BatchRunner + BenchmarkComparator + CLI 🆕

> **Component:** ARCHITECT7 §3 #21, §6.10, §7.4, §8.1 | **Dependencies:** B-25 (Tri-Model), B-24 (DFC), v6 P-00 (OriaHS, опц.) | **Estimate:** 3 дня | **TRIZ:** #19 Periodic action + #25 Self-service

### Context

v6 — только интерактивный режим. Нельзя прогнать 50 промптов на CI и нельзя сделать встроенный benchmark для саморазвития системы. В v7 BatchRunner загружает `prompts.yml`, для каждого промпта прогоняет tri-model конвейер (B-25), пишет результат в `results.jsonl`. Тот же runner — встроенный benchmark.

### Goal

1. `app/batch/runner.py::BatchRunner`:
   - `run(prompts_path, output_path, parallel=4)` — параллельное выполнение.
   - `_run_task(task)` — одиночная задача, запускает tri-model.
   - Output: `results.jsonl`, строка формата `{id, status, duration_ms, tokens, cost_usd, attempts, diff, test_log}` (см. ARCHITECT7 §7.4).
2. `app/batch/comparator.py::BenchmarkComparator`:
   - `compare(current_jsonl, baseline_jsonl) -> DiffReport`.
   - DiffReport: per-task изменения статуса, latency diff, cost diff.
3. FastAPI endpoints (ARCHITECT7 §8.1): `POST /sessions/{id}/batch/run` (sync, timeout 60 мин), `POST /sessions/{id}/batch/run/async` (возвращает `job_id` немедленно), `GET /batch/status/{job_id}` (`{status: "running|completed|failed", progress: 0-100}`), `GET /batch/results/{job_id}` (отдаёт results.jsonl), `POST /batch/compare`.
4. CLI: `orya batch run --input prompts.yml --output results.jsonl` и `orya batch compare --current results.jsonl --baseline main/results.jsonl` (CLI использует async endpoint, поллит статус, печатает прогресс).
5. Встроенный benchmark: `prompts.yml` в корне репозитория — 20 эталонных задач (5 simple, 5 medium, 5 hard, 5 cross-project). Каждая задача: `id`, `prompt`, `criteria` (list), `expected` (string, optional).
6. Интеграция с DFC + Tri-Model + UKB (все BETA-фичи); каждой задаче — изолированный DFC snapshot.
7. Span `batch.run` с атрибутами `batch.task_id`, `batch.status`, `batch.attempts`, `batch.cost_usd`.
8. Metrics: `orya_batch_run_total{status}`, `orya_batch_run_duration_ms`, `orya_batch_pass_rate`.

### Constraints

- Параллелизм: `asyncio.Semaphore(parallel=4)` default.
- Process isolation per batch: в PROD — same process, но изолированный DFC-стейт на задачу (в FUTURE+ — отдельные subprocess).
- Async endpoint возвращает `{"job_id": "..."}` за < 100 ms; клиент поллит `/batch/status/{job_id}`.
- Отказ задачи не валидит батч: `{status: "error"|"timeout"}` в её строке, остальные продолжаются (приоритетный промпт, Принцип 3).
- Не блокировать agent-loop батчем — только async.

### Acceptance Criteria

- ✅ `orya batch run --input prompts.yml --output results.jsonl` — 20 задач выполнено, 20 валидных JSON-строк.
- ✅ Pass-rate > 80% на built-in benchmark.
- ✅ `orya batch compare` показывает diff: какие задачи стали pass/fail, latency diff per task, cost diff.
- ✅ `POST /sessions/{id}/batch/run/async` → `{job_id}` < 100 ms; статус и результаты доступны через соответствующие GET.
- ✅ 10 параллельных задач без race conditions (тест).
- ✅ Span `batch.run` с правильными атрибутами; metrics экспортируются.

### Forbidden patterns

- ❌ Sequential execution (по одной задаче).
- ❌ Смешивание DFC-стейта между параллельными задачами.
- ❌ Хардкод benchmark-задач в коде — только через `prompts.yml`.
- ❌ Блокировка agent-loop батчем.

### Suggested files

`app/batch/__init__.py`, `app/batch/runner.py`, `app/batch/comparator.py`, `app/batch/models.py` (BatchTask, BatchResult, DiffReport), `app/api/routes/batch.py`, `app/cli/batch.py`, `prompts.yml`, `tests/test_batch_runner.py`, `tests/test_batch_comparator.py`.

---

## 5. P-21 — SymbolicClassifier (LLM bypass для rename/format) 🆕

> **Component:** ARCHITECT7 §3 #23, §6.6 | **Dependencies:** B-25 (Tri-Model), B-26 (LSP-native), B-29 (CapabilityRegistry) | **Estimate:** 2 дня | **TRIZ:** #16 Partial effect + #21 Rushing

### Context

~15% ходов в код-проекте — детерминированные (`rename`, `format`, `organize-imports`, `extract-variable`). v6 вызывает executor LLM (2-6 s, 5-20K tokens) для каждой такой задачи. В v7 SymbolicClassifier распознаёт intent; planner эмитит LSP-tool-call; executor LLM **не вызывается**; tester верифицирует. Latency: 500-1500 ms.

### Goal

1. `app/core/workflow/symbolic_classifier.py::SymbolicClassifier`:
   - Regex-паттерны для 4 интентов (таблица `SYMBOLIC_PATTERNS`).
   - LLM-mini fallback classifier (Haiku) для non-regex matches.
   - `classify(prompt) -> (tool_name | None, args | None)`.
2. Pipeline-интеграция с B-25: на planner-фазе при совпадении — skip executor LLM, прямой вызов LSP-tool (`lsp.rename`, `lsp.format`, `lsp.organize_imports`), tester верифицирует diff. Fallback на executor LLM при ошибке LSP-tool или verdict=fail.
3. Span `agent.symbolic_shortcut` (`tool.name`, `tool.args`, `bypass_executor=true`).
4. Metrics: `orya_symbolic_shortcut_usage` (gauge), `orya_symbolic_shortcut_fallback_total` (counter).

### Constraints

- Только 4 паттерна: `rename`, `format`, `organize-imports`, `extract-variable`. Остальное — обычный tri-model.
- LSP rename safety check: если `lsp.rename` затрагивает > 100 файлов — подтверждение пользователя (human-нода).
- Tester — тот же, что в B-25 (Haiku, criteria match).
- Паттерны — в таблице `SYMBOLIC_PATTERNS`, не хардкодом в if-ах.

### Acceptance Criteria

- ✅ `classify("rename UserService to AccountService")` → `("lsp.rename", {"old_name": "UserService", "new_name": "AccountService"})`.
- ✅ `classify("format src/main.py")` → `("lsp.format", {"file": "src/main.py"})`; `classify("organize imports in src/utils.py")` → `("lsp.organize_imports", {...})`.
- ✅ `classify("refactor this code")` → `(None, None)`.
- ✅ Pipeline: symbolic intent → skip executor, LSP-tool, tester verify; fallback при ошибке LSP или verdict=fail.
- ✅ `orya_symbolic_shortcut_usage` ~15% (target); latency symbolic-хода ≤ 1500 ms.
- ✅ Span `agent.symbolic_shortcut` с `bypass_executor=true`.

### Forbidden patterns

- ❌ Symbolic Shortcut для недетерминированных задач.
- ❌ Пропуск tester-верификации.
- ❌ Блокировка agent-loop на LSP-call (async, < 500 ms).
- ❌ Хардкод паттернов мимо `SYMBOLIC_PATTERNS`.

### Suggested files

`app/core/workflow/symbolic_classifier.py`, `app/core/workflow/prompts.py` (+ `SYMBOLIC_CLASSIFIER_PROMPT`), `tests/test_symbolic_classifier.py`.

---

## 6. P-22 — PredictivePlanner + Heat Cache integration 🆕

> **Component:** ARCHITECT7 §3 #24, §6.5 | **Dependencies:** B-24 (DFC Heat Cache), B-25 (Tri-Model) | **Estimate:** 5 дней | **TRIZ:** #10 Preliminary action + #11 Beforehand cushioning

### Context

v6 SpeculativePreFetcher (rule-based, P-16) стартует после planner'а, на критическом пути. В v7 PredictivePlanner — small-модель **в фоне**, прогнозирует следующий промпт, prefetcher греет Heat Cache **до** прихода промпта. Когда пользователь присылает промпт, HOT уже собран → первый токен < 500 ms.

### Goal

1. `app/core/workflow/predictive_planner.py::PredictivePlanner`:
   - Background asyncio task, tick=1s.
   - Model: `settings.predictive_planner_model` (default `qwen-3b` через Ollama; альтернативы Llama-3.2-1B / Haiku-3.5).
   - `_predict_next() -> Prediction` — LLM-call с recent prompts (последние 5) + last feedback.
   - `_prefetch_to_heat(hints)` — параллельный prefetch LSP + UKB + memory_search.
   - `feedback(actual_prompt, predicted_prompt)` — собирает пары для DPO.
2. Heat Cache (B-24): если `confidence > 0.6` → прогрев.
3. DPO training loop: раз в N=100 ходов, batch update на парах (predicted, actual); LoRA fine-tune — опционально, FUTURE+.
4. Span `predictive_planner.predict` (`prediction.confidence`, post-hoc `prediction.match`).
5. Metrics: `orya_predictive_planner_accuracy`, `orya_predictive_planner_miss_total`, `orya_dfc_heat_hit_rate`.

### Constraints

- Tick 1s (configurable); confidence threshold 0.6; Heat Cache TTL 5 мин.
- Data minimization: только последние 5 промптов, без PII во входе прогноза.
- Background task не блокирует agent-loop; любые исключения внутри tick гасятся логом + метрикой.
- Kill-switch `PREDICTIVE_PLANNER_ENABLED=false`.
- False-positive protection: при MISS — метрика `predictive_planner_miss`, следующий прогноз с меньшим весом confidence.

### Acceptance Criteria

- ✅ `start()` поднимает background task; после каждого turn вызывается `feedback(...)`.
- ✅ Prediction: `{predicted_prompt, confidence, prefetch_hints, expected_tier}`.
- ✅ `confidence > 0.6` → Heat Cache прогрет; при совпадении прогноза — HIT, первый токен < 500 ms.
- ✅ Accuracy > 60% после 2 недель (synthetic dataset); Heat Cache hit rate > 50%.
- ✅ DPO: после 100 ходов веса обновлены (LoRA — опц.).
- ✅ Span/metrics корректны; kill-switch работает.

### Forbidden patterns

- ❌ PII во входе прогноза.
- ❌ Блокировка agent-loop прогнозом.
- ❌ Хардкод модели — через settings.
- ❌ Прогрев Heat Cache без `confidence > 0.6`.

### Suggested files

`app/core/workflow/predictive_planner.py`, `app/core/workflow/prompts.py` (+ `PREDICTIVE_PROMPT`), `app/core/workflow/dpo_trainer.py` (опц.), `tests/test_predictive_planner.py`.

---

## 7. P-23 — TournamentExecutor + judge-mcp 🆕

> **Component:** ARCHITECT7 §3 #25, §6.6 | **Dependencies:** B-25 (Tri-Model), A-18 (TieredModelRouter), B-24 (DFC snapshot) | **Estimate:** 4 дня | **TRIZ:** #40 Composite materials + #22 Convert harm into benefit

### Context

CostAwareRouter (A-13) — cost-control, не quality-control. Для сложных задач нужен механизм «N параллельных исполнителей + judge выбирает лучшего». В v7 planner эмитит `tier=tournament` → TournamentExecutor: 3 параллельных исполнителя (разные модели/температуры), judge-mcp выбирает победителя. Latency = max(N), не sum. Cost = N×, но −2..3 replan-итерации.

### Goal

1. `app/core/workflow/tournament.py::TournamentExecutor`:
   - `run(plan, criteria, budget_usd=0.10) -> TournamentResult`.
   - N=3 параллельных исполнителя; каждому — immutable `dfc.snapshot()`.
   - Cost-aware: `estimated_cost > budget_usd` → degrade на single executor (regular tri-model) **до запуска**, span-атрибут `tournament.degraded=true`.
2. `app/mcp/judge_mcp.py` — MCP-сервер: `judge.select_winner(plan, criteria, candidates) -> int`; модель Sonnet (small).
3. Интеграция с B-25: `tier=tournament` от planner'а активирует Tournament; с B-24 — снапшоты; с A-18 — выбор моделей исполнителей.
4. Spans: `agent.tournament` (`tournament.n`, `tournament.models`, `winner_idx`, `judge.model`, `judge.cost`), `judge.call`.
5. Metrics: `orya_tournament_total{verdict}`, `orya_tournament_cost_usd`, `orya_tournament_win_rate`.

### Constraints

- N=3 default (configurable); модели `[Sonnet, GPT-5, DeepSeek-V3]` или `[Sonnet@0.3, Sonnet@0.7, Sonnet@1.0]` — через settings.
- Disagreement (ни один не pass) → replan с ужесточёнными критериями, bounded 2 retry, затем fallback на symbolic shortcut / verdict=fail.
- Запуск Tournament только когда planner эмитит `tier=tournament`.

### Acceptance Criteria

- ✅ 3 параллельных исполнителя, judge возвращает `winner_idx`; judge.call span с `judge.model`, `judge.cost`.
- ✅ Cost-aware degrade при `estimated_cost > 0.10 USD`, `tournament.degraded=true`.
- ✅ Win-rate > 80%; bounded 2 replan → END verdict=fail.
- ✅ Immutable DFC snapshot per executor (тест: мутация DFC одного не влияет на других).

### Forbidden patterns

- ❌ Unbounded tournament retries (max 2).
- ❌ Общий мутируемый DFC между исполнителями.
- ❌ Хардкод моделей.
- ❌ Запуск Tournament без `tier=tournament`.

### Suggested files

`app/core/workflow/tournament.py`, `app/mcp/judge_mcp.py`, `app/core/workflow/prompts.py` (+ `JUDGE_PROMPT`), `tests/test_tournament_executor.py`, `tests/test_judge_mcp.py`.

---

## 8. P-24 — Concurrent Tester (extension of B-25 tri-model) 🆕

> **Component:** ARCHITECT7 §3 #26, §6.2 | **Dependencies:** B-25 (Tri-Model), B-24 (DFC) | **Estimate:** 3 дня | **TRIZ:** #21 Rushing + #15 Dynamicity

### Context

B-25 запускает tester после завершения executor'а: latency = executor + tester = 2.5-7 s. В v7 tester overlap-ится с последними токенами executor'а на partial diff; early-exit, если критерии уже невыполнимы.

### Goal

1. Расширить `app/core/workflow/tri_model.py::_test_concurrent_node`:
   - Старт tester'а при детектируемом partial diff (LangGraph `astream_events` v2).
   - `app/core/workflow/partial_diff_parser.py` — AST-aware парсер валидного diff в streaming-выводе.
   - Early-abort executor при `partial_verdict.is_early_fail=true` (`state.early_abort_executor=true`, остановка ≤ 100 ms).
2. Spans: `agent.test.concurrent`, `agent.test.early_abort`.
3. Metrics: `orya_tri_model_early_abort_total`, `orya_tri_model_verdict{verdict}`.

### Constraints

- Partial verdict — только по критериям, проверяемым без финального diff («endpoint exists at /health»).
- Неконсистентный partial diff → abort tester, рестарт с финальным diff.
- Trade-off: +200 ms на запуск, но −200..400 ms ожидания и −30% cost на провальных ходах.
- Lock-free immutable snapshots partial diff; не блокировать executor тестером.

### Acceptance Criteria

- ✅ Concurrent старт подтверждается span `agent.test.concurrent` с `concurrent=true`.
- ✅ Парсер детектит валидный diff в streaming-выводе (в т.ч. закрытие code-блока ```python).
- ✅ Early-abort ≤ 100 ms; early-abort rate > 15% провальных ходов; −30% cost на провальных ходах; −200..400 ms tester-latency.
- ✅ Malformed streaming → рестарт с финальным diff (тест).

### Forbidden patterns

- ❌ Блокировка executor тестером.
- ❌ Общий partial-diff стейт между запусками tester'а.
- ❌ Хардкод парсера мимо AST-aware parser.

### Suggested files

`app/core/workflow/tri_model.py` (update), `app/core/workflow/partial_diff_parser.py`, `tests/test_concurrent_tester.py`.

---

## 9. P-25 — RerankPolicy with skip + fallback chain 🆕

> **Component:** ARCHITECT7 §3 #29, §6.7 | **Dependencies:** B-27 (UKB), B-28 (RetrievalOrchestrator), v6 P-00 (OriaHS) | **Estimate:** 2 дня | **TRIZ:** #11 Beforehand cushioning + #35 Parameter changes

### Context

OriaHS rerank (always-on cross-encoder ~100 ms) — overhead для коротких queries («rename X»). RerankPolicy решает: применить rerank, skip, или уйти по fallback chain.

### Goal

1. `app/core/retrieval/rerank_policy.py::RerankPolicy`:
   - `decide(query, state) -> RerankDecision`; стратегии: `identifier_lookup` (skip), `short_query` (skip), `default` (apply с кэшем), `from_cache` (LRU).
   - `execute_with_fallback(query, ukb) -> list`.
2. Fallback chain: `hybrid+rerank → hybrid → lexical → degraded`.
3. LRU-кэш повторяющихся queries: max 1000 entries, TTL 5 мин, `threading.Lock` (target hit rate 15-30%).
4. Интеграция с B-28: orchestrator вызывает `rerank_policy.decide()` перед UKB lookup.
5. Spans: `retrieval.rerank` (`retrieval.rerank_applied`, `retrieval.rerank_cache_hit`), `retrieval.fallback` (`retrieval.fallback_level`).
6. Metrics: `orya_rerank_skip_total{reason}`, `orya_rerank_cache_hit_rate`, `orya_rerank_fallback_total{level}`.

### Constraints

- Identifier lookup: `^[a-zA-Z_][a-zA-Z0-9_]*$` → skip; short query: `len(query.split()) < 3` → skip (пороги — через settings).
- Default: rerank cross-encoder через OriaHS, top_k_pre=20, top_k_post=8.
- Fallback: reranker недоступен → hybrid; Qdrant недоступен → lexical (FTS5); всё недоступно → degraded (пустой результат + warning, ход продолжается).
- Инвалидация кэша на memory updates (M-25/M-27 seam).

### Acceptance Criteria

- ✅ `decide("UserService")` → skip `identifier_lookup`; `decide("hello world")` → skip `short_query`; `decide("how to refactor UserService")` → apply.
- ✅ 2-й идентичный query → `from_cache=True`; cache hit rate > 15%.
- ✅ Fallback chain отрабатывает по недоступности компонентов; span `retrieval.fallback` с уровнем.
- ✅ Integration с RetrievalOrchestrator (B-28).

### Forbidden patterns

- ❌ Always-rerank.
- ❌ Хардкод порогов длины запроса.
- ❌ LRU без блокировки между потоками.

### Suggested files

`app/core/retrieval/rerank_policy.py`, `app/core/retrieval/models.py` (+ `RerankDecision`), `tests/test_rerank_policy.py`.

---

## 10. P-26 — Best-of-N execution (simplified tournament) 🆕

> **Component:** ARCHITECT7 §3 #31 | **Dependencies:** P-23 (Tournament), B-25 (Tri-Model) | **Estimate:** 1 день | **TRIZ:** #21 Rushing + #16 Partial effect

### Context

Tournament (P-23) — полная версия с judge-mcp. Для более простых случаев — Best-of-N: 2 параллельных исполнителя, tester выбирает лучшего по deterministic criteria match (без judge-модели).

### Goal

1. `app/core/workflow/best_of_n.py::BestOfNExecutor`:
   - `run(plan, criteria, n=2) -> BestOfNResult`.
   - N=2 параллельных исполнителя (одна модель, разные температуры, например `[Sonnet@0.3, Sonnet@0.7]`).
   - Deterministic `match_score(diff, criteria) -> float`; tie-break — prefer `models[0]`.
2. Активация: `tier=tournament` И `budget_usd < 0.05` (порог configurable); иначе — полный Tournament.
3. Spans: `agent.best_of_n` (`best_of_n.n`, `best_of_n.winner_idx`), `agent.execute.parallel`.
4. Metrics: `orya_best_of_n_total{verdict}`, `orya_best_of_n_tie_break_total`.

### Constraints

- Criteria match детерминирован: одинаковый вход → одинаковый winner.
- Tester — тот же, что в B-25.
- N — через settings.

### Acceptance Criteria

- ✅ `run(plan, criteria, n=2)` → `winner_idx=0|1`; tie → `winner_idx=0`.
- ✅ Активация при `tier=tournament` и `budget < 0.05` (Tournament — при `>= 0.05`).
- ✅ Span `agent.best_of_n`; метрики инкрементируются.

### Forbidden patterns

- ❌ Best-of-N вместо Tournament там, где бюджет позволяет judge.
- ❌ Недетерминированный criteria match.
- ❌ Хардкод N.

### Suggested files

`app/core/workflow/best_of_n.py`, `tests/test_best_of_n.py`.

---

## 11. Риски и mitigations (delta к BETA)

| Риск | Mitigation |
|---|---|
| Batch-runner memory leak (50 промптов в parallel) | `asyncio.Semaphore(parallel=4)`; process isolation per batch |
| Tournament cost blow-up | cost-aware judge; `max_cost_usd` env; degrade на single при превышении |
| Predictive Planner false-positive | confidence threshold 0.6; DPO-обучение на miss; метрика miss_total |
| Symbolic Shortcut mismatch | tester верифицирует; fallback на LLM-executor; manual review log |
| Multi-agent tournament disagreement | replan с ужесточёнными критериями; bounded N=2 retries; fallback на symbolic |
| LSP rename refuted | fallback на LLM-executor; manual review log |
| RerankPolicy cache pollution | TTL 5 мин; LRU eviction; invalidate на memory updates |
| Best-of-N inconsistent criteria match | deterministic criteria-match; tie-break по `executor.model` preference |
| L1 ↔ L2 diverge (outbox lag) | reconciler раз в час; alert при lag > 30 мин (v6) |
| Trace-context loss на MCP boundary | W3C TraceContext; nightly-проверка trace-completeness (v6) |

---

## 12. Forbidden patterns (delta к BETA)

- Общий мутируемый DFC/контекст между параллельными исполнителями и батч-задачами.
- `raise` cost/limit-ошибок сквозь граф в UI (см. приоритетный промпт).
- Qdrant напрямую мимо OriaHS; хардкод trace_id; ручной импорт Grafana-дашбордов.
- Sequential батч; блокировка agent-loop батчем/прогнозом/LSP-вызовом.
- Symbolic bypass для недетерминированных интентов; always-rerank; unbounded tournament retries.
- PII во входе PredictivePlanner; прогрев Heat Cache при `confidence <= 0.6`.
- Нарушение invariants репозитория: `get_tools()` порядок без обновления тестов; прямой импорт LLM-провайдеров вне `app/core/llm/`; мимо `validate_path()` для FS-инструментов.

---

## 13. Структура файлов (delta к BETA)

```
app/batch/                        # 🆕 P-20
  __init__.py  runner.py  comparator.py  models.py
app/api/routes/batch.py           # 🆕 P-20
app/cli/batch.py                  # 🆕 P-20
app/mcp/judge_mcp.py              # 🆕 P-23
app/core/workflow/
  symbolic_classifier.py          # 🆕 P-21
  predictive_planner.py           # 🆕 P-22
  dpo_trainer.py                  # 🆕 P-22 (опц.)
  tournament.py                   # 🆕 P-23
  best_of_n.py                    # 🆕 P-24
  partial_diff_parser.py          # 🆕 P-24
  tri_model.py                    # ✏️ P-24 (extend _test_concurrent_node)
  prompts.py                      # ✏️ +SYMBOLIC_CLASSIFIER_PROMPT, +PREDICTIVE_PROMPT, +JUDGE_PROMPT
app/core/retrieval/
  rerank_policy.py                # 🆕 P-25
  models.py                       # ✏️ +RerankDecision
app/tools/memory.py               # 🆕 P-18 (memory_search)
app/core/mcp_client.py            # ✏️ P-19 (MCP-headers propagation)
infra/oriahs/qdrant_collections.yaml      # 🆕 P-18
eval/datasets/agent_learn_quality.jsonl   # 🆕 P-19
eval/nightly_agent_learn_eval.py          # 🆕 P-19
infra/grafana/dashboards/orya_memory_health.json  # 🆕 P-19
prompts.yml                       # 🆕 P-20 (built-in benchmark, 20 задач)
tests/test_batch_runner.py  test_batch_comparator.py  test_symbolic_classifier.py
tests/test_predictive_planner.py  test_tournament_executor.py  test_judge_mcp.py
tests/test_concurrent_tester.py  test_rerank_policy.py  test_best_of_n.py
tests/test_memory_search.py
```

---

## 14. API surface (delta к BETA)

| Endpoint | Описание |
|---|---|
| `POST /sessions/{id}/batch/run` | sync-запуск батча (timeout 60 мин) |
| `POST /sessions/{id}/batch/run/async` | async-запуск, `{job_id}` < 100 ms |
| `GET /batch/status/{job_id}` | `{status: running\|completed\|failed, progress: 0-100}` |
| `GET /batch/results/{job_id}` | скачать results.jsonl |
| `POST /batch/compare` | DiffReport по двум results.jsonl |
| `POST /sessions/{id}/predict` (опц.) | ручной прогноз/статус PredictivePlanner для отладки |

SSE-кадры: `budget` (A-13) дополняется `tournament`-кадром (progress) — только в debug-режиме, в UI по умолчанию не отображается как ошибка.

---

## 15. Observability: новые span-types и metrics

**Span-types:** `batch.run`, `agent.symbolic_shortcut`, `predictive_planner.predict`, `agent.tournament`, `judge.call`, `agent.test.concurrent`, `agent.test.early_abort`, `agent.best_of_n`, `agent.execute.parallel`, `retrieval.rerank`, `retrieval.fallback`, `memory.read` (P-18).

**Metrics:** `orya_batch_run_total{status}`, `orya_batch_run_duration_ms`, `orya_batch_pass_rate`, `orya_symbolic_shortcut_usage`, `orya_symbolic_shortcut_fallback_total`, `orya_predictive_planner_accuracy`, `orya_predictive_planner_miss_total`, `orya_dfc_heat_hit_rate`, `orya_tournament_total{verdict}`, `orya_tournament_cost_usd`, `orya_tournament_win_rate`, `orya_tri_model_early_abort_total`, `orya_tri_model_verdict{verdict}`, `orya_rerank_skip_total{reason}`, `orya_rerank_cache_hit_rate`, `orya_rerank_fallback_total{level}`, `orya_best_of_n_total{verdict}`, `orya_best_of_n_tie_break_total`, `learn_reuse_rate`, `orya_llm_cost_usd_total{model}` (A-14, уже есть).

Все новые span-types экспортируются в Prometheus (через sampler-proxy A-17) и выводятся на Grafana-дашборды.

---

## 16. Порядок реализации (рекомендуемый)

1. **Неделя 1:** P-00..P-05 (OriaHS-путь: bootstrap → search → index → chunker → wait/delete → git-aware reindex) — если ещё не реализованы; проверь репозиторий перед стартом.
2. **Неделя 2:** P-06..P-13 (multi-tenant, A/B, sandbox, Context Epoch, LLM-migration, shadow, chaos, DR).
3. **Неделя 3:** P-14..P-17 + P-18 (L2 Qdrant + memory_search) + P-19 (tracing + offline-eval).
4. **Неделя 4:** P-20 (Batch Pipeline) — зависит от tri-model; сразу `prompts.yml` benchmark.
5. **Неделя 5:** P-21 (Symbolic) + P-24 (Concurrent Tester) — оба на tri-model seam.
6. **Неделя 6:** P-22 (Predictive Planner + Heat Cache).
7. **Неделя 7:** P-23 (Tournament + judge-mcp).
8. **Неделя 8:** P-25 (RerankPolicy) + P-26 (Best-of-N).
9. **Неделя 9:** P-14 (расширенный PROD DoD), Grafana-дашборды, e2e/smoke на все 7 power-features, `format → lint → test`.

## 17. Exit criteria (переход PROD → EXTENSION-PROD)

- ✅ Batch Pipeline: 20 эталонных задач, pass-rate > 80%; `orya batch compare` работает.
- ✅ Symbolic Shortcut: ~15% ходов с `intent: symbolic`, fallback работает.
- ✅ Predictive Planner: accuracy > 60% (after 2 weeks), Heat Cache hit rate > 50%.
- ✅ Tournament: cost-aware degrade работает (`tournament.degraded=true` в span'ах), win-rate > 80%.
- ✅ Concurrent Tester: early-abort rate > 15% на провальных ходах.
- ✅ RerankPolicy: skip rate 30-50% retrievals; fallback chain работает.
- ✅ Best-of-N: активация при `budget < threshold`, N=2.
- ✅ v6 PROD DoD: memory_search hybrid < 200 мс p95; trace-completeness > 95%; learn_reuse_rate > 30%.
- ✅ Все новые span-types в Prometheus; `format → lint → test` зелёные.

## 18. Целевые NFR фазы (delta к BETA)

| Параметр | Целевое PROD v7 | Было (BETA) |
|---|---|---|
| Time-to-first-token | ≤ 800 мс | ≤ 1000 мс |
| Latency p95 (поиск по проекту) | ≤ 3 s | ~5 s |
| Tokens per turn (avg) | 6-16 K | 30-60 K |
| Cost per session (30 ходов) | ≤ $0.20 | ≤ $0.30 |
| Symbolic Shortcut usage | ~15% | 0% |
| Predictive Planner accuracy | > 60% | n/a |
| Heat Cache hit rate | > 50% | n/a |
| Tournament win-rate | > 80% | n/a |
| Concurrent Tester early-abort rate (failed turns) | > 15% | n/a |
| Batch throughput (prompts/hour) | 100-400 | n/a |
| Batch pass-rate | > 80% | n/a |
| RerankPolicy skip rate | 30-50% | 0% |
| Best-of-N activation rate | 5-10% tournament-промптов | n/a |
| Memory-retrieval latency (hybrid L1+L2) | ≤ 200 мс p95 | — |
| Trace-completeness | > 95% | — |

## 19. Ссылки на исходные документы

- `analytics/ARCHITECT.md` §3 (#21 Batch, #23 Symbolic, #24 Predictive, #25 Tournament, #26 Concurrent Tester, #29 RerankPolicy, #31 Best-of-N), §6.5-6.7, §6.10, §7.4-7.5, §8.1.
- `analytics/ROADMAP.md` §6 (Фаза PROD), §10 (карта зависимостей), §11.3-11.4 (exit criteria), §13 (NFR).
- `analytics/BACKLOG.md` §5 (P-20..P-26 — детальные спецификации), §9-10.
- `analytics/old/BACKLOG6.md` §5 (P-18..P-19), `analytics/old/BACKLOG5.md` §5 (P-00..P-17), `analytics/old/ROADMAP6.md` §6.
- `AGENTS.md` — конвенции репозитория (uv, ruff, get_tools, validate_path, тесты, Windows).

---
---

# ПРИЛОЖЕНИЕ A. Промпты: парсер AGENTS.md (адаптация TypeScript → Python)

> Источник — промпты парсера AGENTS.md из opencode (TypeScript, `fast-glob` + `gray-matter`). Адаптировано под стек OryaAgent: Python 3.11+, stdlib (`pathlib`, `os`, `hashlib`, `asyncio`, `fnmatch`), PyYAML, pytest (`asyncio_mode=auto`). Все модули кладутся в `app/core/agents_md/`, интеграция — в system-prompt builder (`build_system_prompt`, стабильные секции первыми — под cacheable prefix A-19). Конвенции репозитория обязательны (раздел 0 этого документа): ruff 88, docstring с id тикета, конфиг-тесты с `monkeypatch.chdir(tmp_path)` и `clear_settings_cache()`.
> Предлагаемый id тикета: **P-27 — AGENTS.md loader (Python)**. Коммит-префикс: `P-27: agents_md loader (...)`.

## Промпт A.1 — discovery: обнаружение источников AGENTS.md

Реализуй модуль `app/core/agents_md/discovery.py` для парсера AGENTS.md (Python 3.11+, только stdlib — без внешних зависимостей).

Требования:

1. Экспортируй `async def discover_sources(opts: DiscoverOptions) -> tuple[list[SourceRef], list[str]]` (результат + warnings), где

   ```python
   @dataclass(frozen=True)
   class DiscoverOptions:
       cwd: Path
       worktree_root: Path
       global_dirs: list[Path]
       filenames: tuple[str, ...] = ("AGENTS.md", "AGENT.md", "CLAUDE.md")
       instruction_globs: tuple[str, ...] = ()
       disable_project: bool = False
   ```

2. `SourceRef = {path: Path, origin: Literal["global", "project", "config"], trusted: bool, root: Path | None}`.
3. Порядок: (a) первый существующий файл в `global_dirs` → `trusted=True`; (b) подъём от `cwd` до `worktree_root` (аналог findUp) по `filenames` — только **первая** найденная директория с совпадением, файл → `trusted=False`, `root=worktree_root`; (c) каждый glob из `instruction_globs`: поддержка `~/...` (домашняя директория, `Path.home().expanduser()`), абсолютных и относительных путей (от `cwd` вверх до `worktree_root`). Абсолютные вне worktree → `trusted=True`, иначе `trusted=False` с root.
4. Дедупликация по `path.resolve()`; сохраняй порядок: global → project → config.
5. Все ошибки ФС (`PermissionError`, `FileNotFoundError`, `OSError`) не бросаются — собираются в warnings и возвращаются вторым значением кортежа.
6. Блокирующий I/O — через `asyncio.to_thread` (конвенция репозитория).
7. Напиши unit-тесты (`tests/unit/test_agents_md_discovery.py`): вложенный проект (AGENTS.md в корне и в подпапке — выигрывает ближайший к cwd), отсутствие файлов, приоритет global над project, дедуп, `~/`-пути. Фикстуры — `tmp_path` + `monkeypatch.chdir`.

Критерии приёмки: тесты зелёные (`uv run pytest tests/unit/test_agents_md_discovery.py`), функция чистая (нет скрытого I/O кроме чтения ФС), docstrings на всех экспортах, ruff чист.

## Промпт A.2 — SafeReader и ContentParser

Реализуй модули `app/core/agents_md/reader.py` и `app/core/agents_md/frontmatter.py`.

**reader.py:**

1. `async def read_source(ref: SourceRef, opts: ReaderOptions) -> ReadResult` где `ReadResult = {content: str, size: int, hash: str, truncated: bool, mtime: float}`.
2. Ограничения: `max_per_file_bytes` (default 256 KB), `max_total_bytes` (default 1 MB) — при превышении обрезать, ставить `truncated=True`, **не** бросать исключение.
3. Если `ref.trusted is False`: проверь, что resolved-путь внутри `ref.root` (аналог `path.relative` из TS: используй `Path.resolve()` + `is_relative_to()`; учитывай симлинки через `os.path.realpath`) — иначе верни ошибку в `errors[]` и пропусти файл. Переиспользуй `validate_path()` из `app/tools/_validators.py`, где применимо.
4. Возвращай SHA-1 хеш содержимого (`hashlib.sha1`) и `mtime` (`os.stat().st_mtime`) для кэша.
5. Чтение — `asyncio.to_thread`, с `get_cache()` как read-only инструмент (M-21 seam); при `mtime`-изменении кэш инвалидируется (hot-reload поведение).

**frontmatter.py:**

1. Парсинг YAML-фронтматтера (`---` делимитеры) через `yaml.safe_load` (PyYAML уже в зависимостях; `python-frontmatter` — опционально). Никакого process-wide кэша парсера — свежие опции на каждый вызов.
2. **КРИТИЧНО (аналог бага opencode «invalid YAML silently ignored»):** если `yaml.safe_load` вернул значение, которое **не** является `dict` (например, `str` — признак молчащего отказа парсера на скаляре), бросай `FrontmatterError` с именем файла и фрагментом проблемного YAML. Запрещено «распаковывать» data, если это `str`.
3. При ошибке парсинга — один retry через `fallback_sanitization(content)`: пропуск комментариев и пустых строк, сохранение indented-продолжений, принудительное квотирование значений, содержащих `:`.
4. Если и retry не удался — `FrontmatterError` с `raise ... from exc`; ошибка **обязана** попасть в итоговый `errors[]` результата `parse_agents_md` (Промпт A.4), файл не теряется бесшумно.
5. Тесты (`tests/unit/test_agents_md_frontmatter.py`): валидный YAML; YAML вида `skill:true` (без пробела) — после санитизации парсится, до — ошибка; полностью битый YAML → `FrontmatterError` в errors[]; пустой фронтматтер.

## Промпт A.3 — references: подстановка @file и !`shell` с моделью доверия

Реализуй `app/core/agents_md/references.py` — подстановку `@file` и `` !`shell` `` внутри AGENTS.md с моделью доверия из `SourceRef`.

1. `FILE_REGEX = re.compile(r"(?<![\w`])@(\.?[^\s`,.]*(?:\.[^\s`,.]+)*)")` — извлекай ссылки из тела markdown (эквивалент lookbehind-паттерна из TS).
2. Для каждой ссылки: разрешай относительно директории файла; если `ref.trusted is False` — чтение цели разрешено только внутри `ref.root` (тот же confinement, что в reader.py — реиспользуй функцию, не дублируй).
3. Циклические ссылки (`@a.md → @b.md → @a.md`): отслеживай стек путей, глубина подстановки ≤ 5; при цикле — запись в `errors[]` (warning), ссылка заменяется на `[circular reference skipped]`.
4. Отсутствующий файл — не фатально: замена на `[missing: <path>]` + warning.
5. `` !`shell` ``-подстановки: выполняются **только** для trusted-источников; `asyncio.create_subprocess_shell` с `asyncio.wait_for(timeout=5)`, вывод обрезается до 4 KB, stdout/stderr через `wrap_untrusted()` (`app/core/security.py`); для untrusted — замена на `[shell substitution disabled for untrusted source]`.
6. Реализуй `async def attach(messages, filepath: Path, message_id: str) -> list` (аналог opencode attach): подъём от `dirname(filepath)` к worktree_root, поиск ближайшего AGENTS.md, прикрепление не чаще одного раза на `message_id` (`claims: dict[str, set[str]]`), дедуп против уже загруженных системных путей.
7. Тесты: вложенные подстановки, цикл, выход за root у untrusted, shell-запрет у untrusted, once-per-message при повторном чтении файлов из той же ветки дерева.

## Промпт A.4 — публичный API parse_agents_md и сборка системного промпта

1. `app/core/agents_md/api.py::parse_agents_md(opts) -> ParseResult` — оркестрация: `discover_sources` → `read_source` (concurrency 8: `asyncio.Semaphore(8)`, аналог opencode) → frontmatter → `references.substitute` → merge → render.
2. Merger: сохраняй порядок discovery; дедуп по resolved path + hash; при превышении `max_total_bytes` обрезай по принципу «последние источники жертвуют первыми», каждая обрезка — запись в `errors[]`.
3. Renderer: для каждого источника блок `"Instructions from: <path>\n<content>"`; пустые файлы пропускаются; если все источники пусты — `system_prompt = ""` и `errors[]` непустой.
4. Опциональный флаг `include_frontmatter: bool = False`: `True` → frontmatter сериализуется YAML-блоком перед телом (для инструментов, которым нужны структурированные метаданные); default `False` (поведение opencode).
5. Публикуй события через колбэк `on_error` (аналог Bus-абстракции opencode; в OryaAgent это может быть emit_span + лог): `FrontmatterError`, truncation, confinement violation — вызывающий код **обязан** иметь возможность показать их пользователю.
6. **Интеграция с system-prompt builder (конвенция репозитория):** добавь `agents_md_block()` в `app/core/prompt.py` и аппендь её в `build_system_prompt` (стабильная секция — до динамических git/memory блоков, чтобы сохранить cacheable prefix A-19). Тест в `tests/unit/test_prompt.py`.
7. Тесты e2e на фиктивной файловой структуре (`tests/unit/test_agents_md_api.py`): полный happy path; проект с битым AGENTS.md (ошибка видна в errors[], сессия не падает); монорепо с несколькими AGENTS.md (загружается только ближайший к cwd); untrusted-файл, ссылающийся на `/etc/passwd` — ссылка заблокирована, файл загружен; `monkeypatch.chdir` + `clear_settings_cache()` в конфиг-тестах.
8. README-секция (в `docs/` или README): формат AGENTS.md, таблица приоритетов источников, модель trust, список ошибок.

## Промпт A.5 — write-protection AGENTS.md и регрессионный тест-план

1. **Write-protection:** список защищённых имён (`AGENTS.md`, `AGENT.md`, `CLAUDE.md`) на уровне API парсера; экспортируй `is_protected_file(path: Path) -> bool`. Интеграционная точка — инструменты `write` (M-08) и `edit` (M-09): перед записью вызывай `is_protected_file()`; при срабатывании — не `ToolException`, а перевод в human-ноду графа (M-16 permission-ask): изменение защищённого файла требует явного подтверждения пользователя (как в kilocode). Fail-closed: неизвестный ответ resume — deny (конвенция `app/core/permissions.py`).
2. Закрепи регрессии, соответствующие известным багам opencode/kilocode, тестами:
   - «invalid YAML silently ignored»: `isinstance(data, str)` → `FrontmatterError`, а не загрузка агента с именем из filename и пустым конфигом;
   - «AGENTS.md not loaded after /new»: discovery выполняется на каждую сессию, кэш per-session (`ContextVar`/аргумент), а не process-wide (`lru_cache` запрещён — конвенция `get_settings()`);
   - «description not populated for markdown agents»: frontmatter `description` (или fallback из первого заголовка) обязателен для сабагентов;
   - путь создания CLI-файлов совпадает с путём загрузчика (единая константа `AGENTS_MD_DIRNAME`).
3. Hot-reload: перечитывание при изменении `mtime` (reader A.2) — тест: изменение файла между turn'ами подхватывается.
4. Тест-план оформи как markdown-документ `docs/agents-md-test-plan.md` с чек-листом: приоритет источников, confinement, циклы, лимиты, ошибки YAML, write-protection, hot-reload поведение.

---
---

# ПРИЛОЖЕНИЕ B. Промпты: аналоги отсутствующих команд opencode

> Источник — анализ сессии «Статистика команд OryaAgent» (`oryaagent.json`): в OryaAgent есть и усилены все базовые инструменты (`read`, `write`, `edit`, `bash`, `grep`, `glob`, LSP-набор, `oriahs_*`, `ukb_lookup`, `retrieval_orchestrate`), но **отсутствуют** аналоги стандартных команд opencode: слэш-команды (`/review`, `/explain`, `/audit`, `/plan`, `/compare`, `/check`, `/history`, `/component`), часть системных файловых операций (`ls`, `find`, `rm`, `mkdir`, `mv`, `cp`, `chmod` — `cat`/`find` частично покрываются `read`/`glob`/`grep`), git-команды (`git status/add/commit/push/pull`) и пакетные менеджеры (`npm install/run`, `pip install`, `cargo build`, `go build`).
> Все инструменты реализуй строго по конвенциям репозитория: «добавление инструмента = 5 шагов» (`app/tools/<name>.py` + реэкспорт + `get_tools()` + `EXPECTED_NAMES`/`EXPECTED_REQUIRED_ARGS` в `tests/integration/test_tools_integration.py` + unit-тесты), `@tool` + async + `Annotated[str, ...]`, `asyncio.to_thread` для блокирующего I/O, `validate_path()` перед любым FS-доступом, один JSON-документ на выходе, `wrap_untrusted()`/`detect_injection()` на пользовательском выводе, `ToolException` для ошибок, atomic writes (`mkstemp` → fsync → `os.replace`), read-only → `get_cache()` + permission-allowlist, write-инструменты → `invalidate_cache_for_path()`.
> Предлагаемые id тикетов: **P-28 (файловые операции), P-29 (git), P-30 (пакетные менеджеры), P-31 (слэш-команды)**. Порядок расширения `get_tools()` фиксированный — после `glob` добавляй новые в явном порядке и обновляй все тесты, проверяющие список; для фильтрации по режимам используй `CapabilityRegistry` (B-29).

## Промпт B.1 — файловые операции: `list`, `find`, `delete`, `mkdir`, `move`, `copy`, `chmod` (P-28)

Реализуй недостающие файловые инструменты аналогично opencode (`ls`, `find`, `rm`, `mkdir`, `mv`, `cp`, `chmod`), но безопаснее:

1. `app/tools/list.py::list` (аналог `ls`) — read-only: список файлов/директорий с типом, размером, mtime; параметры `dir_path` (default cwd), `depth` (default 1, max 3); JSON-вывод; `get_cache()`; allowlist в permissions.
2. `app/tools/find.py::find` (аналог `find`) — read-only: поиск по имени/шаблону (`fnmatch`) с параметрами `pattern`, `root` (validate_path), `type` (`file|dir|any`), `limit` (default 50); работает поверх `glob`/`rg --files` через общий seam `app/tools/_rg.py`; JSON-вывод.
   Примечание: `cat` отдельным инструментом **не делать** — `read` (M-07) уже лучше (пагинация, нумерация строк, детекция бинарных); в system-prompt добавь указание использовать `read` вместо `cat`, `glob`/`grep` вместо `find`.
3. `app/tools/delete.py::delete` (аналог `rm`) — **write**: только внутри allowed roots (`validate_path`); параметр `recursive: bool = False`; запрет на удаление корней allowed roots и защищённых файлов (`is_protected_file()` из Промпта A.5); путь в human-ноду (M-16) на подтверждение; после удаления `invalidate_cache_for_path()`.
4. `app/tools/mkdir.py::mkdir` — write: `os.makedirs(exist_ok=True)` только в allowed roots; валидация пути; JSON `{path, created}`.
5. `app/tools/move.py::move` (аналог `mv`) — write: `os.replace` внутри одного allowed root (кросс-устройство — `shutil.move` через `asyncio.to_thread`); запрет перезаписи существующего файла без `overwrite: bool = False`; обе стороны пути через `validate_path`.
6. `app/tools/copy.py::copy` (аналог `cp`) — write: потоковое копирование с буфером, `copy2` для метаданных; обе стороны validate_path; лимит размера (default 100 MB) с понятной ошибкой.
7. `app/tools/chmod.py::chmod` — write, **deny-by-default в permissions**: только явный allowlist режимов (например, `+x` для скриптов); запрет `chmod 777`/рекурсивного режима на директориях; JSON-отчёт об изменении.
8. Все write-инструменты: инъекция-детект на аргументах, `wrap_untrusted()` на выводе, unit-тесты (sandbox через `tmp_path`), обновление `EXPECTED_NAMES`/`EXPECTED_REQUIRED_ARGS`, порядок в `get_tools()` — после `glob`: `[read, write, edit, bash, grep, glob, list, find, delete, mkdir, move, copy, chmod]` (зафиксируй в тесте).

Критерии приёмки: `uv run pytest tests/unit/test_tools_file_ops.py tests/integration/test_tools_integration.py` зелёные; ruff чист; destructive-инструменты (`delete`, `chmod`) denied без подтверждения (тест через PermissionPolicy).

## Промпт B.2 — git-команды: единый инструмент `git` (P-29)

Реализуй `app/tools/git.py::git` — единый инструмент-обёртка над git (аналог `git status/add/commit/push/pull` из opencode), вместо пяти отдельных:

1. Параметр `subcommand: str` из allowlist: `status`, `diff`, `log`, `add`, `commit`, `push`, `pull`, `branch`, `stash` (read-only: `status`/`diff`/`log`/`branch` — в permission-allowlist, можно `get_cache()`).
2. Выполнение через `asyncio.create_subprocess_exec("git", subcommand, *args, cwd=workspace)` (никаких `shell=True`); аргументы строго типизированы: `paths: list[str]` (для add), `message: str` (для commit), `remote`/`ref` (для push/pull); инъекция-детект на всех строковых аргументах (`detect_injection`).
3. **Permission-гейтинг:** `commit` — ask по умолчанию; `push`/`pull` — ask всегда (сетевые операции); deny при mode=read-only. Конвенция fail-closed из `app/core/permissions.py`.
4. Вывод: единый JSON-документ `{subcommand, exit_code, stdout, stderr, duration_ms}`; stdout/stderr через `wrap_untrusted()`; лимит вывода (default 50 KB) с усечением.
5. `git commit` — генерация message не входит в инструмент: LLM передаёт готовый `message`; добавь в system-prompt инструкцию конвенций коммитов репозитория (`P-20: ...`).
6. Обработка отсутствия git/репозитория — `ToolException` с человекочитаемым сообщением; таймаут 120 s (`pull/push` — 600 s).
7. Тесты: monkeypatch на subprocess seam (как в `tests/integration/test_tools_integration.py` для `rg`); sandbox-репозиторий через `tmp_path` + `git init` в тесте (если git доступен, иначе conditional skip — конвенция скип-паттернов из AGENTS.md); permission-тесты: push denied без approve.

Критерии приёмки: read-only git-команды в allowlist работают без ask; push/pull требуют подтверждения; вывод — один JSON; EXPECTED-таблицы обновлены.

## Промпт B.3 — пакетные менеджеры: инструмент `pkg` (P-30)

Реализуй `app/tools/pkg.py::pkg` — унифицированный инструмент пакетных менеджеров (аналог `npm install/run`, `pip install`, `cargo build`, `go build` из opencode):

1. Параметры: `ecosystem: Literal["npm", "pip", "cargo", "go", "uv"]`, `action: Literal["install", "run", "build", "test", "audit"]`, `args: list[str]`.
2. Матрица команд (allowlist, всё остальное — `ToolException`):
   - npm: `npm install [pkgs]`, `npm run <script>` (скрипт читается из package.json, не исполняется blindly);
   - pip: `uv pip install [pkgs]` / `pip install [pkgs]` (предпочитай uv — конвенция репозитория);
   - cargo: `cargo build`, `cargo test`;
   - go: `go build ./...`, `go test ./...`;
   - uv: `uv sync`, `uv run <cmd>`.
3. Исполнение: `asyncio.create_subprocess_exec`, cwd = workspace (validate_path), таймаут 600 s (конвенция bash M-10), env через allowlist-фильтр (как в bash), вывод — один JSON `{ecosystem, action, exit_code, stdout, stderr, duration_ms}` через `wrap_untrusted()`, дедуп повторяющихся строк (>100 одинаковых — как в bash.py).
4. **Безопасность:** install/audit — ask по умолчанию; блокировка `--index-url`/`--registry` указываемых LLM (только из settings); логирование установки пакетов в tool_calls (audit-таблица).
5. Реиспользуй seam bash.py (резолюция шелла, таймауты, усечение) — вынеси общее в `app/tools/_subprocess.py`, если дублирование > 30 строк.
6. Тесты: monkeypatch subprocess seam; матрица allowlist (запрещённая команда → ToolException); таймаут; permission: install denied в read-only mode.

Критерии приёмки: `pkg` в `get_tools()` после `git`; EXPECTED-таблицы обновлены; матрица команд покрыта тестами.

## Промпт B.4 — слэш-команды: `/review`, `/explain`, `/audit`, `/plan`, `/compare`, `/check`, `/history`, `/component` (P-31)

В OryaAgent слэш-команды — **UI-слой** (Chainlit M-15 + Next.js B-11), не инструменты: команда разворачивается в пресет системного промпта/агента и отправляется как обычное сообщение. Реализуй фреймворк + 8 команд:

1. `app/core/slash.py::SlashRegistry`: `register(name, builder)`; `resolve(text) -> SlashCommand | None` (парсинг `/<name> [args]`); команда инжектирует пресет-блок в system-prompt на один turn (не ломая cacheable prefix: пресет — динамическая секция в конце, как memory-блоки).
2. Команды (каждая — builder, возвращающий системную инструкцию + опциональные параметры инструментов):
   - `/review [path|diff]` — ревью кода: инструкция «найди ошибки, отсутствующие тесты, security-проблемы; используй grep/read/lsp_diagnostics; верни список findings с severity»;
   - `/explain [path|symbol]` — объяснение кода: read + lsp_hover/lsp_definition, структурное объяснение;
   - `/audit` — аудит зависимостей: `pkg audit` (npm audit / pip-audit через P-30), отчёт по уязвимостям;
   - `/plan [task]` — планирование: переход в режим planner (tier=small), вывод плана без выполнения (tool_choice=none на первый ход);
   - `/compare [a b]` — сравнение файлов/веток: git diff (P-29) + структурное сравнение;
   - `/check [focus]` — проверка с фокусом на указанных аспектах (типы, тесты, стили): lsp_diagnostics + bash (тесты);
   - `/history [n]` — суммирование коммитов: git log + LLM-резюме;
   - `/component [name]` — генерация компонента: шаблон (для Next.js-части — React-компонент по конвенциям репозитория), atomic write.
3. UI: Chainlit — регистрация команд в настройках чата; Next.js — slash-меню с автокомплитом; audit записей команд — через Hooks UI (B-20).
4. `/history` и `/plan` не имеют side effects (read-only — в permission-allowlist автоматически); `/component` — write-путь через существующий `write` инструмент (не новый FS-доступ).
5. Тесты: registry (resolve unknown → None), каждый builder даёт непустую инструкцию, e2e на fake-model (конвенция tests/e2e): `/review` порождает ход с ожидаемым пресетом.

Критерии приёмки: все 8 команд доступны в обоих UI; resolve покрыт тестами; ни одна команда не обходит permission-policy.

---

# Сводка приложений

| Блок | Что даёт | Тикеты |
|---|---|---|
| Приложение A | Парсер AGENTS.md на Python (discovery, safe reader, frontmatter с защитой от молчащего отказа YAML, references с trust-моделью, write-protection, hot-reload) | P-27 |
| Приложение B.1 | Файловые операции: list, find, delete, mkdir, move, copy, chmod | P-28 |
| Приложение B.2 | Git: единый инструмент с permission-гейтингом | P-29 |
| Приложение B.3 | Пакетные менеджеры: npm/pip/uv/cargo/go | P-30 |
| Приложение B.4 | Слэш-команды UI: /review, /explain, /audit, /plan, /compare, /check, /history, /component | P-31 |

**Готов к реализации.** Порядок: сначала основной план фазы PROD (§16), приложения A/B — параллельно неделями 4-8, когда core-seams стабилизированы. После завершения фазы — переход к EXTENSION-PROD (E-12..E-14, опционально).
