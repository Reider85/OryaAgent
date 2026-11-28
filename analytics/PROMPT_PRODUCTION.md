# ПРОМПТ ФАЗЫ PRODUCTION (PROD) И ЗАКРЫТИЕ ПРОБЕЛОВ СИЛЬНОГО АГЕНТА — OryaAgent v7

> **Версия промпта:** 7.1 (объединённый документ: Часть I — фаза PROD, Часть II — закрытие пробелов сильного агента)
> **Дата:** 28 ноября 2026
> **Источники:** `analytics/ARCHITECT.md` (ARCHITECT7) §3 (улучшения #21, #23, #24, #25, #26, #29, #31), §6.5-6.7, §6.10, §7.4-7.5, §8.1; `analytics/ROADMAP.md` (ROADMAP7) §6 (Фаза PROD), §11.3-11.4 (exit criteria), §13 (NFR-таргеты); `analytics/BACKLOG.md` (BACKLOG7) §5 (P-20..P-26), §9-10 (матрица и карта зависимостей); `analytics/old/BACKLOG6.md` §5 (P-18..P-19); `analytics/old/BACKLOG5.md` §5 (P-00..P-17); `analytics/old/ROADMAP6.md` §6; `AGENTS.md` (конвенции репозитория, uv/ruff/тесты). Приложения: парсер AGENTS.md — адаптация TypeScript-промптов opencode/kilocode на Python; аналоги отсутствующих команд opencode — по итогам анализа логов (`oryaagent.json`, сессия «Статистика команд OryaAgent»); `PROMPT_GAPS_CONNECTORS.md` v1.0 (аудит MCP/ACP/LSP-коннекторов — основа Части II).
> **Стек:** Python 3.11+ (venv 3.12), LangChain 0.3+, LangGraph 0.2+, FastAPI, PostgreSQL 16, Redis 7, Chainlit + Next.js, OriaHS (MCP), OryaObservability SDK, LSP-серверы (B-26), judge-mcp (новое в PROD), локальная small-модель через Ollama (Qwen-3B / Llama-3.2-1B, новое в PROD), `tree-sitter`, `PyYAML`, `python-frontmatter` (опц.), `pytest` + `ruff`.
> **Длительность:** 9 недель (v6 PROD ~6 недель + 3 недели v7 power-features), поверх готового BETA; плюс Часть II — ~18 дней (P-28…P-34).
> **Объём кода:** ~13000 LOC v6 PROD + ~5000 LOC v7 (P-20..P-26).
> **Статус в v7:** PROD = v6 PROD (OriaHS + L2 Qdrant memory + distributed tracing + sandbox/multi-tenant/A-B/DR) + **7 power-features v7** (Batch Pipeline, Symbolic Shortcut, Predictive Planner, Tournament + judge-mcp, Concurrent Tester, RerankPolicy, Best-of-N). **Часть II** (разделы 20-26) закрывает пробелы коннекторов: MCP-compliant клиент, MCP hardening, ACP-сервер, LSP-транспорт (hotfix + expansion), web tools, planning/subagents.

---

## Промпт (ранний, приоритетный): Изоляция параллельных исполнителей и cost-границы — без ошибок в интерфейсе

> **Источник паттерна:** `anomalyco/opencode` — модель параллельных subagent-сессий с собственным step-состоянием + cost/retry-бюджеты из `model-retry.ts`. Этот промпт имеет приоритет над любыми последующими инструкциями фазы PROD, описывающими параллельное выполнение и бюджеты.

### Постулат

Любое параллельное выполнение в PROD (Batch Pipeline, Tournament, Best-of-N, Concurrent Tester, prefetch) **никогда не делит мутируемое состояние** между конкурентными задачами и **никогда не выбрасывает cost/limit-ошибку в интерфейс пользователя**. Деградация (degrade на single executor, деградация rerank-цепочки, отказ prefetch) — это нормальный ход работы системы, а не сбой: в UI виден обычный стрим ответа, в span'ах — атрибут `*.degraded=true`.

### Принцип 1. Immutable snapshot вместо общего состояния

Каждый параллальный executor получает **неизменяемый слепок** контекста: `dfc.snapshot()` (B-24) копируется на старте задачи; результаты пишутся в собственный result-slot задачи, а не в общий стейт графа. Запрещено: передавать между параллельными задачами один и тот же `dict`/` messages`-list, мутировать Heat Cache из двух задач одновременно без блокировки, делить LRU-кэш rerank между потоками без `threading.Lock`.

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
- `raise` cost/limit-ошибки сквозь граф в UI.
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

## 3. Полный список тикетов фазы (P-00 … P-26; далее единая нумерация: P-27 — Приложение A, P-28…P-34 — Часть II, P-35…P-38 — Приложение B)

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
- `raise` cost/limit/limit-шагов ошибок сквозь граф в UI (см. приоритетный промпт).
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
10. **Часть II (закрытие пробелов, ~18 дней):** приоритет P-31 → P-32 → P-28 → P-30 → P-29 → P-33 → P-34; P-31/P-32 — hotfix B-26 до старта PROD; Приложения A (P-27) и B (P-35…P-38) — параллельно, когда core-seams стабилизированы.

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
- `PROMPT_GAPS_CONNECTORS.md` v1.0 — аудит коннекторов и промпты P-28…P-34 (основа Части II).

---
---

# ЧАСТЬ II. ЗАКРЫТИЕ ПРОБЕЛОВ СИЛЬНОГО АГЕНТА — аудит коннекторов и промпты (P-28…P-34)

> **База аудита:** репозиторий `Reider85/OryaAgent` (ветка main, коммит da931a4), файлы `app/mcp/client.py`, `app/mcp/oriahs_mcp.py`, `app/mcp/lsp_mcp.py`, `app/mcp/ukb_mcp.py`, `app/core/lsp/bus.py`, `app/core/lsp/config.py`, `app/tools/` (полный реестр), `app/core/` (структура), `app/api/` (маршруты). Источник — отдельный документ `PROMPT_GAPS_CONNECTORS.md` v1.0, объединённый в этот документ как Часть II; единая нумерация: P-00…P-26 — Часть I (фаза PROD), P-27 — Приложение A, P-28…P-34 — Часть II, P-35…P-38 — Приложение B.
> **Формат:** та же конвенция, что и PROD-промпт: id тикета, Context / Goal / Constraints / Acceptance Criteria / Forbidden patterns / Suggested files, конвенции `AGENTS.md` обязательны (uv, ruff 88, `get_tools()` + `EXPECTED_NAMES`, `validate_path()`, `asyncio.to_thread`, docstring с id тикета, `format → lint → test`).

---

## 20. Резюме аудита: что есть и чего не хватает

### 20.1. Текущее состояние (подтверждено по коду)

| Компонент | Статус в репо | Где |
|---|---|---|
| B-24 DFC | есть | `app/core/dfc/` |
| B-25 Tri-Model | есть | `app/core/workflow/tri_model.py` |
| B-26 LSP-native | есть, **с критическим дефектом транспорта** (см. §21.3) | `app/core/lsp/bus.py`, `app/tools/lsp.py`, `app/mcp/lsp_mcp.py` |
| B-27 UKB, B-28 RetrievalOrchestrator, B-29 CapabilityRegistry | есть | `app/core/ukb/`, `app/core/retrieval/`, `app/core/capability/` |
| MCP-серверы (OriaHS, LSP, UKB) | есть: `mcp.server.Server` SDK + stdio + собственный HTTP-фасад | `app/mcp/oriahs_mcp.py` и др. |
| MCP-клиент | есть, **но это не MCP-протокол** (см. §21.1) | `app/mcp/client.py` |
| ACP (Agent Client Protocol) | **отсутствует полностью** (см. §22) | — |
| PROD-тикети P-20…P-26 (batch, tournament, judge-mcp, memory_search и т.д.) | не реализованы (ожидаемо — репо в BETA) | отсутствуют `app/batch/`, `app/mcp/judge_mcp.py`, `app/tools/memory.py`, `app/core/retrieval/rerank_policy.py` |
| AGENTS.md loader (P-27) | промпт есть в Приложении A этого документа, в репо не реализован (`app/core/agents_md/` отсутствует) | — |

### 20.2. Главные пробелы «сильного агента» (кратко)

1. **MCP-клиент — не MCP.** `app/mcp/client.py` говорит по собственному REST-контракту (`GET /health`, `GET /tools`, `POST /call`), а не по протоколу MCP (JSON-RPC 2.0, handshake `initialize`, capabilities, транспорта stdio/SSE/streamable-HTTP). Следствие: агент **не может подключать внешние MCP-серверы** — экосистемный разрыв, главный пробел коннекторов.
2. **ACP отсутствует.** Ни файла, ни упоминания Agent Client Protocol. Агента нельзя вести из Zed/других ACP-редакторов.
3. **LSP-клиент сломан на транспорте.** `bus.py` шлёт JSON с `\n`-делимитером, а LSP требует фрейминг `Content-Length: N\r\n\r\n`. Против реальных серверов (pyright, rust-analyzer, gopls, jdtls, typescript-language-server) клиент не заработает — приёмка B-26, судя по всему, прошла на моках. Плюс: server→client-запросы теряются, push-диагностика не слушается, capabilities не объявлены.
4. **LSP-покрытие языков: 6 из ~30+ популярных.** Нет C/C++ (clangd), C#, Ruby, PHP, Kotlin, Swift, Bash, YAML/JSON/HTML/CSS (при том что `frontend`-конфиг заявляет `.css`/`.html`, которые typescript-language-server не обслуживает) и др. Полная таблица — §23.
5. **Нет web-инструментов** (`web_search`/`web_fetch`) — агент изолирован от интернета.
6. **Нет planning/todo-инструмента и generic-субагентов** (Task-делегирование с изолированным DFC-snapshot) — Tournament (P-23) закрывает только качество исполнения, но не параллельную декомпозицию задач.
7. **Мелочи-ред flags:** глобальный `asyncio.Lock` в `MCPClient.call_tool` сериализует ВСЕ вызовы инструментов; process-wide singleton `_mcp_client_instance` нарушает собственную конвенцию репо (ср. `clear_settings_cache()`); конфиги LSP дублированы в `bus.py` и `config.py` (два источника правды); Redis-«переиспользование» LSP-серверов — заглушка (пишет pid, подключиться к процессу не может).

### 20.3. Порядок реализации новых тикетов

```
P-31 (LSP transport fix) — СНАЧАЛА, блокер для B-26-инвариантов и P-21
P-28 (MCP-compliant client + реестр внешних серверов)
P-29 (MCP hardening: auth + tracing) → зависит от P-28
P-30 (ACP server) — независимо, можно параллельно с P-28
P-32 (LSP expansion: новые серверы + format/organize_imports) → после P-31; нужен ДО P-21 (Symbolic Shortcut требует lsp.format/lsp.organize_imports)
P-33 (web tools) — независимо
P-34 (planning + subagents) — независимо, DFC-snapshot из B-24
```

Суммарная оценка: **~17–19 дней**. Рекомендация: P-31 и P-32 вставить в BETA как hotfix B-26 (до старта PROD), остальные — в начало фазы PROD.

---

## 21. Аудит MCP-коннекторов

### 21.1. Клиент: `app/mcp/client.py` — собственный REST, а не MCP

Фактический контракт: `GET /health`, `GET /tools`, `POST /call {name, arguments}` поверх httpx. Это работоспособный «внутренний RPC», но:

- нет JSON-RPC 2.0 и handshake `initialize`/`initialized`, нет согласования capabilities;
- нет транспорта stdio — невозможно запустить произвольный внешний MCP-сервер (`npx -y @modelcontextprotocol/server-...`);
- нет ресурсов (`resources/list`, `resources/read`), промптов (`prompts/list`) и sampling;
- нет уведомлений `notifications/tools/list_changed` → кэш инструментов протухает молча;
- нет авторизации по спецификации MCP (OAuth 2.1, RFC 9728 metadata);
- нет `MCP-Trace-Id`/`MCP-Span-Id`/W3C `traceparent` — разрыв трассировки на MCP-границе (прямой конфликт с P-19);
- `call_tool` держит **глобальный** `asyncio.Lock` — все MCP-вызовы выстроены в одну очередь;
- `_mcp_client_instance` — process-wide singleton без механизма сброса, вразрез с конвенцией репозитория о кэшах.

### 21.2. Серверы: `oriahs_mcp.py` / `lsp_mcp.py` / `ukb_mcp.py`

Серверы сделаны правильно (официальный `mcp` SDK, `Server`, stdio-транспорт), но основной путь в compose — **кастомный HTTP-фасад** (`create_http_app`), т.е. MCP-протокол end-to-end фактически не используется. `judge_mcp.py` (P-23) отсутствует — входит в PROD.

### 21.3. Вывод

Коннектор MCP реализован «в одну сторону» (свои серверы — свой клиент). Чего не хватает сильному агенту: **универсального MCP-клиента для внешних серверов** с реестром (`mcp.json`), неймспейсингом инструментов, health/degrade, авторизацией и трассировкой. Закрывают тикеты P-28 и P-29.

---

## 22. Аудит ACP-коннектора

ACP (Agent Client Protocol, агент-клиентский протокол, принятый в Zed) в репозитории отсутствует: нет файлов, конфигов, CLI-точки входа. Для код-агента ACP — самый дешёвый способ получить редактор-хост-интеграцию: JSON-RPC поверх stdio, редактор сам даёт FS/терминал/permissions. Реализация — тикет P-30 (OryaAgent как ACP-**сервер**, редактор — клиент). Опционально на FUTURE+: A2A (agent-to-agent) — межагентный протокол, отдельный домен, не путать с ACP.

---

## 23. Аудит LSP: каких серверов и возможностей не хватает

### 23.1. Поддерживается сейчас (bus.py + config.py)

| Язык | Сервер | Комментарий |
|---|---|---|
| Python | `pyright-langserver --stdio` | ок |
| TypeScript | `typescript-language-server --stdio` | ок |
| Rust | `rust-analyzer` | ок |
| Go | `gopls stdio` | ок |
| Java | `jdtls` | ок |
| Lua | `lua-language-server` | ок |
| «frontend» | `typescript-language-server` | **дефект:** заявлены `.tsx/.jsx/.css/.html`, но TS-сервер не обслуживает CSS/HTML — нужны vscode-langservers-extracted |

### 23.2. Недостающие LSP-серверы (рекомендуемые к добавлению)

**Приоритет 0 (массовые экосистемы, добавлять в первую очередь):**

| Язык | LSP-сервер | Команда | Extensions |
|---|---|---|---|
| C/C++ | clangd | `clangd --background-index` | `.c .h .cpp .hpp .cc` |
| C# | csharp-ls (или OmniSharp) | `csharp-ls` | `.cs` |
| Ruby | ruby-lsp | `ruby-lsp` | `.rb` |
| PHP | intelephense | `intelephense --stdio` | `.php` |
| Kotlin | kotlin-lsp | `kotlin-lsp` | `.kt .kts` |
| Swift | sourcekit-lsp | `sourcekit-lsp` | `.swift` |
| Bash | bash-language-server | `bash-language-server start` | `.sh .bash` |
| CSS/HTML/JSON | vscode-langservers-extracted | `vscode-css-language-server --stdio` / `vscode-html-language-server --stdio` / `vscode-json-language-server --stdio` | `.css .html .json` |

**Приоритет 1 (частые в агентских задачах):**

| Язык | LSP-сервер | Extensions |
|---|---|---|
| Scala | metals | `.scala` |
| Dart/Flutter | dart language-server | `.dart` |
| Elixir | elixir-ls | `.ex .exs` |
| Zig | zls | `.zig` |
| Haskell | haskell-language-server | `.hs` |
| Vue | vue-language-server (Volar) | `.vue` |
| Svelte | svelte-language-server | `.svelte` |
| Terraform | terraform-ls | `.tf` |
| TOML | taplo | `.toml` |
| YAML | yaml-language-server | `.yml .yaml` |
| Protobuf | buf / protobuf-language-server | `.proto` |

**Приоритет 2 (по спросу):** Julia (`julia --startup-file=no --history-file=no --eval "using LanguageServer..."`), OCaml (`ocamllsp`), F# (`fsautocomplete`), R (`R --slave -e languageserver::run()`), Nix (`nil`/`nixd`), Markdown (`marksman`), GraphQL (`graphql-lsp`), SQL (`sqls`), Groovy, Crystal, Solidity.

### 23.3. Дефекты LSP-клиента (вне списка серверов)

1. **Фрейминг транспорта сломан** (см. §20.2 п.3) — блокер.
2. `_handle_message`: сообщения с `id` и `method` (server→client **requests**: `workspace/applyEdit`, `workspace/configuration`, `client/registerCapability`) попадают в ветку «response» и теряются.
3. Гонка `_send_request`: future регистрируется после отправки — ответ, пришедший раньше регистрации, не находит будущего.
4. Диагностика только pull (`textDocument/diagnostic`); rust-analyzer и ряд серверов pull не поддерживают — нужен листенер `textDocument/publishDiagnostics` + `wait_for_diagnostics(timeout)`.
5. `capabilities: {}` — клиентские возможности не объявлены; ответ `initialize` (server capabilities) игнорируется.
6. Нет `textDocument/didSave`, `workspace/didChangeWatchedFiles`, `textDocument/formatting`, organize-imports (codeAction kind `source.organizeImports`), call hierarchy — а P-21 (Symbolic Shortcut) требует `lsp.format` и `lsp.organize_imports`.
7. Дублирование конфигураций между `bus.py::_initialize_server_configs` и `config.py::LANGUAGE_LSP_CONFIGS` — два источника правды.
8. Redis-«cross-process reuse» — заглушка (пишется pid, подключение к чужому процессу невозможно).

Закрывают тикеты P-31 (transport + bidirectional) и P-32 (новые серверы + новые tools).

---

## 24. Промпты-тикети (P-28…P-34)

> Общие правила (наследуются из `AGENTS.md`): спека тикета — grep по `analytics/`; команды `uv sync` / `uv run pytest` / `make lint`; порядок завершения **format → lint → test**; LLM-seam только `app/core/llm/`; `get_tools()` фиксированный порядок + `EXPECTED_NAMES`/`EXPECTED_REQUIRED_ARGS` в `tests/integration/test_tools_integration.py`; FS-инструменты через `validate_path()`; вывод наружу через `wrap_untrusted()`/`detect_injection()`; добавление инструмента = 5 шагов; docstring модуля с id тикета; коммиты `<ID>: ...`.

---

## 24.1. P-28 — MCP-compliant клиент (JSON-RPC + транспорта) и реестр внешних MCP-серверов

> **Dependencies:** нет (независим от PROD-цепочки) | **Estimate:** 3 дня | **TRIZ:** #24 Intermediary
> **Проблема:** `app/mcp/client.py` — собственный REST-контракт (`GET /health`, `GET /tools`, `POST /call`), а не протокол MCP. Агент не может подключать внешние MCP-серверы.

### Goal

1. `app/mcp/mcp_client_v2.py::MCPClientV2` — клиент на официальном SDK `mcp` (`ClientSession`):
   - Транспорта: `stdio_client` (spawn внешнего сервера: `command`, `args`, `env`) и `streamablehttp_client` (SSE-fallback). Выбор — по конфигу сервера.
   - Полный handshake: `initialize` → подтверждение capabilities → `notifications/initialized`.
   - `list_tools()`, `call_tool()` через JSON-RPC; поддержка `resources/list`/`resources/read` и `prompts/list` (read-only, в реестр — отдельным типом).
2. Реестр внешних серверов: `.orya/mcp.json` (формат совместим с Claude Desktop/Cursor: `{"mcpServers": {"<name>": {"command"/"url", "args", "env"}}}`) + env-override `ORYA_MCP_SERVERS`. Валидация схемой, secrets только через env (`${VAR}`-подстановка, никогда не в файле).
3. Мостинг инструментов в агента: внешние tools попадают в `get_tools()` с неймспейсом `mcp__<server>__<tool>` — **добавляются в конец списка**, `EXPECTED_NAMES`/`EXPECTED_REQUIRED_ARGS` в `tests/integration/test_tools_integration.py` обновляются; описание-схема пробрасывается из `inputSchema` MCP.
4. Lifecycle: per-server health-проверка при старте; недоступный сервер → degrade (его инструменты не добавляются, `mcp.server_degraded=true` в span, UI не показывает ошибку); retry-connect с экспоненциальным backoff (max 3).
5. Убрать глобальный `asyncio.Lock` из `call_tool`: конкурентность per-server (lock на сервер, не на клиент). Убрать process-wide singleton — инжектировать клиент через фабрику с явным сбросом (аналог `clear_settings_cache()`).
6. Обратная совместимость: внутренние HTTP-фасады (`oriahs-mcp` и др.) работают; миграция OriaHS-клиента на V2 — отдельным флагом `ORYA_MCP_CLIENT_V2=true` (default true для внешних серверов).
7. Spans: `mcp.initialize`, `mcp.call` (`mcp.server`, `mcp.tool`, `mcp.duration_ms`). Metrics: `orya_mcp_call_total{server,status}`, `orya_mcp_tool_count{server}`, `orya_mcp_server_up{server}`.

### Acceptance Criteria

- ✅ Подключение реального внешнего сервера: `npx -y @modelcontextprotocol/server-filesystem <dir>` через stdio → `list_tools()` возвращает его инструменты, вызов `mcp__filesystem__read_text_file` работает.
- ✅ Подключение streamable-HTTP сервера (любой публичный reference-сервер) — handshake и call проходят.
- ✅ `.orya/mcp.json` валидируется; битый JSON → ясная ошибка при старте, сессия не падает; отсутствующий сервер → degrade, не exception.
- ✅ 10 параллельных `call_tool` к одному серверу — без deadlock; к двум серверам — реально параллельно (тест по времени).
- ✅ `get_tools()` содержит неймспейсированные инструменты, интеграционный тест зелёный.
- ✅ Format → lint → test зелёные.

### Forbidden patterns

- ❌ Кастомный «почти-MCP» JSON-RPC мимо SDK (если только не обосновано в плане).
- ❌ Глобальная блокировка всех вызовов одним lock.
- ❌ Secrets в `mcp.json` (только `${VAR}`-подстановка).
- ❌ Мутирующий доступ внешних tools к DFC без `validate_path()`-эквивалента (FS-root из конфига сервера).

### Suggested files

`app/mcp/mcp_client_v2.py`, `app/mcp/registry.py`, `app/mcp/bridge.py` (mcp→langchain tools), `.orya/mcp.json.example`, `tests/unit/test_mcp_registry.py`, `tests/integration/test_mcp_client_v2.py`.

---

## 24.2. P-29 — MCP hardening: OAuth 2.1, W3C trace propagation, resilience

> **Dependencies:** P-28 | **Estimate:** 2 дня | **TRIZ:** #11 Beforehand cushioning
> **Проблема:** нет авторизации по спецификации MCP (OAuth 2.1), нет `MCP-Trace-Id`/W3C-пропагации на MCP-границе (конфликт с P-19), нет circuit breaker.

### Goal

1. Авторизация: для HTTP-транспорта — OAuth 2.1 authorization code + PKCE, RFC 9728 protected-resource metadata discovery, refresh-token flow; токены в keyring/env, никогда в логах. Для локальных stdio-серверов — auth не требуется.
2. Trace propagation (интеграция с P-19): `MCPClientV2` инжектит `MCP-Trace-Id`/`MCP-Span-Id`/`MCP-Parent-Span-Id` + W3C `traceparent` в заголовки и в `_meta` JSON-RPC для stdio; `trace-completeness > 95%` проверяется существующим nightly.
3. Resilience: per-server circuit breaker (5 ошибок подряд → open 60 s → half-open probe); timeout policy per tool (default 30 s, конфиг); идемпотентные ретраи только для сетевых ошибок (5xx/timeout), не для `isError=true` ответов.
4. Rate/size limits: max payload 5 MB, max tools per server 200 (защита от раздутых серверов), предупреждение в span при превышении.
5. Notifications: обработка `notifications/tools/list_changed` → инвалидация кэша инструментов сервера (не полный рестарт сессии).

### Acceptance Criteria

- ✅ HTTP-сервер с включённым OAuth 2.1 подключается (тест с локальным stub-authorization-server).
- ✅ Span `mcp.call` содержит `MCP-Trace-Id`, совпадающий с корневым trace; trace-completeness > 95% на e2e-прогоне.
- ✅ Circuit breaker: 5 подряд ошибок → сервер open, вызовы fail-fast с degrade-метрикой, через 60 s half-open.
- ✅ `tools/list_changed` обновляет кэш без перезапуска (тест).

### Forbidden patterns

- ❌ Токены/секреты в логах, span-атрибутах и results.
- ❌ Ретраи неидемпотентных вызовов «на всякий случай».
- ❌ Хардкод trace-заголовков мимо propagation-хелпера (P-19).

### Suggested files

`app/mcp/auth.py`, `app/mcp/resilience.py`, `app/mcp/mcp_client_v2.py` (update), `tests/unit/test_mcp_resilience.py`, `tests/integration/test_mcp_oauth.py`.

---

## 24.3. P-30 — ACP-сервер (Agent Client Protocol): OryaAgent как ACP-агент для редакторов

> **Dependencies:** нет (граф агента из B-25/DFC) | **Estimate:** 3 дня | **TRIZ:** #6 Universality
> **Проблема:** ACP отсутствует полностью; агента нельзя вести из Zed и других ACP-совместимых хостов.

### Goal

1. `app/acp/server.py::ACPServer` — JSON-RPC 2.0 поверх stdio (фрейминг LSP-совместимый `Content-Length`), реализующий роль **agent**:
   - `initialize` → capabilities (loadSession: true/false, promptCapabilities: embed, meta);
   - `session/new` (cwd, mcpServers от хоста) → `session/update` стрим;
   - `session/load` (resume), `session/prompt` (блоки текста/embeddedResource), `session/cancel`;
   - нотификации `session/update`: `agent_message_chunk` (стрим токенов), `tool_call` / `tool_call_update` (pending → in_progress → completed/failed, kind: read/edit/delete/move/search/execute/think/fetch/other), `plan` (entries с priority/status), `current_mode`;
   - `session/request_permission` → мост в существующую permission-ноду (M-16, `app/core/permissions.py`, fail-closed);
   - callbacks `fs/read_text_file`, `fs/write_text_file` → мост в read/write-инструменты (`validate_path()` сохраняется); `terminal/*` → мост в sandbox-bash (bwrap, P-08 если реализован, иначе per-OS allowlist).
2. Адаптер: ACP-сессия оборачивает существующий LangGraph-граф; стриминг через `astream_events` v2 → `agent_message_chunk`; ходы tri-model маппятся в plan-entries (planner/executor/tester).
3. CLI: `orya acp` (точка входа в `app/cli/`) — запуск ACP-сервера над workspace; документация подключения к Zed (в `docs/acp.md`).
4. MCP-серверы, переданные хостом в `session/new`, добавляются в реестр P-28 на время сессии (неймспейс `acp__<name>__<tool>`).
5. Spans: `acp.session`, `acp.prompt`, `acp.permission`. Metrics: `orya_acp_session_total`, `orya_acp_message_chunks_total`, `orya_acp_permission_total{decision}`.

### Constraints

- ACP-сервер не мутирует глобальные настройки; per-session DFC snapshot (конвенция приоритетного промпта PROD: immutable snapshot).
- Никаких error-баннеров в хост: ошибки хода → `session/update` с `tool_call_update status=failed` + текстовый итог.
- JSON-RPC id строго коррелируются; входящие server→client-запросы не теряются (урок из LSP-аудита §23.3 п.2).

### Acceptance Criteria

- ✅ `echo '{"jsonrpc":"2.0","id":1,"method":"initialize",...}' | orya acp` — корректный ответ с capabilities.
- ✅ E2E со скриптом-клиентом: session/new → session/prompt «создай файл hello.py» → стрим chunks + tool_call(edit) + request_permission → completed.
- ✅ Cancel: `session/cancel` останавливает ход ≤ 500 ms.
- ✅ Подключение из Zed (ручная проверка по `docs/acp.md`) — агентовая сессия отвечает в редакторе.
- ✅ Фрейминг `Content-Length` — юнит-тест на fragmentation (сообщение, разбитое на несколько chunk-ов чтения).

### Forbidden patterns

- ❌ ACP-сервер с правами шире permission-модели агента (request_permission обязателен для write/execute).
- ❌ newline-delimited JSON вместо Content-Length фрейминга.
- ❌ Потеря server→client requests (id+method).

### Suggested files

`app/acp/__init__.py`, `app/acp/server.py`, `app/acp/protocol.py` (фрейминг, переиспользуемый P-31), `app/acp/adapter.py`, `app/cli/acp.py`, `docs/acp.md`, `tests/unit/test_acp_protocol.py`, `tests/e2e/test_acp_session.py`.

---

## 24.4. P-31 — HOTFIX LSP-транспорта: Content-Length фрейминг + bidirectional-запросы

> **Dependencies:** нет | **Estimate:** 2 дня | **Приоритет:** блокер B-26 и P-21
> **Проблема:** `app/core/lsp/bus.py` шлёт newline-delimited JSON; LSP требует `Content-Length: N\r\n\r\n`. Против реальных серверов клиент не работает (приёмка B-26 прошла на моках). Server→client-запросы теряются; гонка регистрации future; push-диагностика не слушается.

### Goal

1. `app/acp/protocol.py` → `app/core/lsp/protocol.py::LSPBaseProtocol` (общий с ACP, P-30):
   - Отправка: `Content-Length: N\r\n\r\n<body>`; чтение: парсер заголовков с буферизацией, устойчивый к fragmentation/partial reads (тест: тело разбито на 3 chunk-а).
   - Заменить `buffer.split("\n", 1)` на фрейм-парсер; `json.loads` только на полном фрейме.
2. Bidirectional-обработка в `_handle_message`:
   - сообщение с `id` + `method` — это **запрос сервера**: отвечай результатом/ошибкой; роутинг `workspace/applyEdit` (применить WorkspaceEdit атомарно через write-инструмент), `workspace/configuration` (вернуть секции из init_options), `client/registerCapability`, `window/workDoneProgress/create`;
   - сообщение с `id` без `method` — response: resolve future **по id**; исправь гонку — регистрируй future до отправки.
3. Client capabilities в `initialize`: `textDocument` (hover, definition, references, rename, codeAction, diagnostic, publishDiagnostics), `workspace` (applyEdit, symbol, configuration, didChangeWatchedFiles, workspaceFolders). Парси ответ сервера: если capability отсутствует — помечай метод недоступным (`server.supports(method) -> bool`), не шли запрос.
4. Диагностика: слушай `textDocument/publishDiagnostics` (кэш per-file + `asyncio.Event`); `diagnostics()` = pull (если сервер поддерживает) с merge push-кэша; добавь `wait_for_diagnostics(file, timeout=10)`.
5. Фикс `_initialize`: `didOpen` для всех уже открытых файлов workspace при старте (limit 100), `didSave` после edit-инструментов (seam в `app/tools/edit.py::after_edit`).
6. Redis-reuse: честно пометить как FUTURE+ (убрать заглушку записи pid) или реализовать через отдельный LSP-gateway-процесс; сейчас — удалить вводящий в заблуждение код и `lsp.redis_reuse=false` в settings.
7. Регрессионные тесты против **реальных** серверов (integration, инфра-условные): pyright — hover/diagnostic; mock-server с фреймингом — все методы. Unit: fragmentation, серверный запрос applyEdit, публикация diagnostics, гонка ответов (ответ до регистрации future).

### Acceptance Criteria

- ✅ `pytest tests/integration/test_lsp_pyright.py` — зелёный против реального pyright-langserver (hover возвращает содержимое).
- ✅ Fragmentation-тест: JSON разрезан на 3 записи чтения — парсер собирает.
- ✅ `workspace/applyEdit` от сервера применяется атомарно; тест с mock-сервером.
- ✅ `wait_for_diagnostics` получает push-диагностику от rust-analyzer (у которого pull отсутствует) — integration-тест, инфра-условный.
- ✅ `lsp_diagnostics` на файле с ошибкой возвращает ошибки < 100 ms после didOpen.

### Forbidden patterns

- ❌ Накаких readline-парсеров по `\n` для LSP/ACP транспорта.
- ❌ Игнорирование server-capabilities (запросы методов, которые сервер не объявил).
- ❌ Mock-only тесты для транспортного слоя (минимум один integration с реальным сервером).

### Suggested files

`app/core/lsp/protocol.py`, `app/core/lsp/bus.py` (update), `app/core/lsp/diagnostics.py`, `tests/unit/test_lsp_protocol.py`, `tests/integration/test_lsp_pyright.py`, `tests/integration/test_lsp_rust_analyzer.py`.

---

## 24.5. P-32 — LSP expansion: 9 новых серверов + lsp.format / lsp.organize_imports / lsp_call_hierarchy

> **Dependencies:** P-31 | **Estimate:** 3 дня | **TRIZ:** #5 Merging
> **Проблема:** 6 языков из ~30+ популярных; `frontend`-конфиг заявляет `.css/.html`, которые typescript-language-server не обслуживает; нет tools форматирования и organize-imports, необходимых P-21 (Symbolic Shortcut).

### Goal

1. Единый источник правды: `bus.py::_initialize_server_configs` удаляется, `LSPBus` читает `LANGUAGE_LSP_CONFIGS` из `config.py`; маппинг расширений не пересекается (один extension → один сервер; `.h` → clangd, конфликт с C++ решается detection по содержимому — опц.).
2. Новые серверы (Приоритет 0 из §23.2): clangd (C/C++), csharp-ls, ruby-lsp, intelephense, kotlin-lsp, sourcekit-lsp, bash-language-server, yaml-language-server, vscode-css/html/json-language-server (`vscode-langservers-extracted`); `frontend` разбивается на `frontend-ts` (ts/tsx/js/jsx), `frontend-css`, `frontend-html`.
3. Ленивый старт + idle- reap: сервер запускается на первый запрос языка (не все 15 сразу); после 10 мин бездействия — shutdown (configurable); max одновременно работающих серверов 6 (LRU-вытеснение).
4. Capability detection при старте сессии: бинарник сервера есть в PATH → язык enabled; нет → degraded-режим (fallback read+grep), `lsp.language_disabled{language}` метрика; в system prompt — заметка какие LSP-возможности доступны.
5. Новые инструменты (полные 5 шагов конвенции): `lsp_format` (`textDocument/formatting` + range-форматирование), `lsp_organize_imports` (codeAction kind `source.organizeImports` + applyEdit через P-31), `lsp_call_hierarchy` (prepare/incoming/outgoing calls). Read-only`lsp_format`? — нет: это write → permission-allowlist не добавлять; `lsp_organize_imports` — write; `lsp_call_hierarchy` — read-only.
6. `docker-compose.yml` / `deploy/`: опциональный профиль `lsp-full` с установленными серверами; базовый образ — pyright+typescript (как сейчас).
7. Spans `lsp.call{language,method}`; metrics `orya_lsp_tool_total{tool,language,status}`, `orya_lsp_server_uptime_seconds{language}`.

### Acceptance Criteria

- ✅ `get_supported_languages()` возвращает ≥ 14 записей; extension-маппинг без конфликтов (тест).
- ✅ `lsp_format("main.py")` форматирует файл (integration с реальным сервером или black через LSP-шлюз pyright не поддерживает formatting — тогда через `ruff-lsp` опционально; допустимый fallback: файл-локальный форматтер с пометкой в span `lsp.format.fallback=true`).
- ✅ `lsp_organize_imports("src/utils.py")` возвращает применённый WorkspaceEdit (использует P-31 applyEdit).
- ✅ Ленивый старт: 20 запросов только к Python не поднимают остальные серверы (тест по числу процессов).
- ✅ Отсутствие clangd в PATH → язык disabled, ход агента не падает (degraded fallback-тест).
- ✅ `EXPECTED_NAMES` обновлён, `format → lint → test` зелёные.

### Forbidden patterns

- ❌ Дублирование конфигов серверов (второй источник правды запрещён).
- ❌ Запуск всех серверов при старте сессии.
- ❌ Инструменты format/organize_imports без permission-ноды (это write-операции).

### Suggested files

`app/core/lsp/config.py` (update), `app/core/lsp/bus.py` (update), `app/core/lsp/registry.py` (новый: capabilities + lazy lifecycle), `app/tools/lsp.py` (update: +3 tools), `tests/unit/test_lsp_registry.py`, `tests/integration/test_lsp_format.py`.

---

## 24.6. P-33 — Web tools: web_search / web_fetch

> **Dependencies:** нет | **Estimate:** 2 дня | **TRIZ:** #23 Feedback
> **Проблема:** у агента нет доступа к интернету — нет инструментов `web_search` и `web_fetch` в `app/tools/`. Сильный агент вне код-контекста (актуальные доки, версии библиотек, issue-трекеры) слеп.

### Goal

1. `app/tools/web_search.py` — `@tool`, async, `Annotated[str, ...]`: поиск через сконфигурированный провайдер (env `ORYA_WEB_SEARCH_PROVIDER`: `tavily` | `brave` | `serper` | `duckduckgo` (fallback без ключа)); возврат — один JSON-документ (конвенция): `{query, results: [{title, url, snippet}], provider}`; top_k ≤ 10.
2. `app/tools/web_fetch.py` — fetch URL: timeout 15 s, max size 2 MB, HTML→markdown/text extraction (readability-подход), `wrap_untrusted()` на контент + `detect_injection()` (страницы — классический вектор prompt-injection).
3. SSRF-защита: allowlist схем (http/https), запрет private/loopback/link-local CIDR (`ipaddress`), запрет redirect на private, DNS-rebinding — резолв и повторная проверка IP перед запросом; `validate_path()` не применим — вместо него отдельный `validate_url()` в `app/tools/_validators.py`.
4. Кэш: get_cache() для обоих (read-only), TTL 15 мин на URL; инвалидация стандартная.
5. Permission: оба read-only → permission-allowlist; но `web_fetch` доменных исключений — human-нода при отсутствии в allowlist (env `ORYA_WEB_FETCH_ALLOWLIST`).
6. Оба инструмента — в `get_tools()`, `EXPECTED_NAMES`, unit-тесты с моком HTTP (никогда реальный интернет в тестах).

### Acceptance Criteria

- ✅ `web_search("fastapi background tasks")` валидный JSON с ≥ 1 результатом (интеграционный тест помечен infra-условным).
- ✅ SSRF-тесты: `http://127.0.0.1`, `http://169.254.169.254`, redirect на private — все отклонены.
- ✅ Prompt-injection в содержимом страницы детектится (`detect_injection` hit → span-атрибут).
- ✅ `EXPECTED_NAMES` обновлён; `format → lint → test` зелёные.

### Forbidden patterns

- ❌ Fetch без size/timeout лимитов.
- ❌ Контент страницы в контекст без `wrap_untrusted()`.
- ❌ Реальные сетевые вызовы в unit-тестах.

### Suggested files

`app/tools/web_search.py`, `app/tools/web_fetch.py`, `app/tools/_validators.py` (+`validate_url`), `tests/unit/test_web_tools.py`, `tests/integration/test_web_tools_live.py` (infra-conditional).

---

## 24.7. P-34 — Planning/todo + generic subagents (Task-делегирование)

> **Dependencies:** B-24 (DFC snapshot) | **Estimate:** 2–3 дня | **TRIZ:** #1 Segmentation
> **Проблема:** нет planning/todo-инструмента (план не виден пользователю и не переживает компакцию) и нет generic-механизма субагентов — Tournament (P-23) — это quality-механика одной задачи, а не декомпозиция.

### Goal

1. `app/tools/todo.py` — `todo_write(todo_list)` / `todo_read()`: структура `{id, content, status: pending|in_progress|completed, priority}`; хранится в DFC (Persistence-layer), сериализуется в сессию; UI: Chainlit-панель плана обновляется по `todo_write`-событию; в system prompt — текущий план (динамическая секция, после cacheable prefix).
2. Правило в промпте planner-фазы: многошаговые задачи (> 3 шага) обязаны начинаться с `todo_write`.
3. `app/core/subagents.py::SubagentRunner` + `app/tools/task.py::task` — делегирование подзадачи субагенту:
   - субагент получает **immutable `dfc.snapshot()`** + изолированный result-slot (конвенция приоритетного промпта PROD — никакого общего мутируемого стейта);
   - ограничения: depth ≤ 2 (субагент не может порождать субагентов), max 4 параллельных (`asyncio.Semaphore`), budget per subagent (`max_cost_usd`, default $0.05) — превышение → degrade до запуска, не exception;
   - возврат — строка-отчёт (не раздутый контекст), span `subagent.run{depth, cost_usd, status}`;
   - доступ к инструментам — подмножество (без write/edit по умолчанию; расширение — через permission-ноду).
4. `todo_write`-события и статусы субагентов стримятся в UI как plan-entries (совместимо с ACP `session/update plan` из P-30 — один источник событий).

### Acceptance Criteria

- ✅ `todo_write` с 5 пунктами → план виден в system prompt следующего хода и в UI.
- ✅ Субагент depth 1 возвращает отчёт; мутирование DFC субагентом не видно родителю (тест на snapshot-изоляцию).
- ✅ 4 параллельных субагента — ок; 5-й ждёт семафора; budget-превышение → degrade со span-атрибутом, без exception в UI.
- ✅ Depth 2: субагент, вызвавший `task`, получает ToolException «depth limit».

### Forbidden patterns

- ❌ Общий мутируемый DFC между родителем и субагентами.
- ❌ Unbounded рекурсия делегирования (max depth 2).
- ❌ `raise` budget-ошибки сквозь граф в UI.

### Suggested files

`app/tools/todo.py`, `app/tools/task.py`, `app/core/subagents.py`, `app/core/workflow/state.py` (+todo-секция), `tests/unit/test_todo_tool.py`, `tests/unit/test_subagents.py`.

---

## 25. Сводная таблица

| ID | Title | Estimate | Закрывает пробел |
|---|---|---|---|
| P-28 | MCP-compliant клиент + реестр внешних серверов | 3 д | MCP-коннектор (внешние серверы) |
| P-29 | MCP hardening: OAuth 2.1, trace, resilience | 2 д | MCP-коннектор (прод. готовность) |
| P-30 | ACP-сервер (Agent Client Protocol) | 3 д | ACP-коннектор (отсутствует) |
| P-31 | HOTFIX: LSP Content-Length фрейминг + bidirectional | 2 д | LSP-транспорт (блокер B-26/P-21) |
| P-32 | LSP expansion: 9 серверов + format/imports/hierarchy | 3 д | LSP-покрытие языков |
| P-33 | Web tools (web_search/web_fetch) | 2 д | Доступ к интернету |
| P-34 | Planning/todo + subagents | 3 д | Декомпозиция и видимость плана |
| **Σ** | | **~18 д** | |

Приоритет реализации: **P-31 → P-32 → P-28 → P-30 → P-29 → P-33 → P-34** (P-31 — до PROD, как hotfix BETA). Напоминание: P-27 (AGENTS.md loader, Приложение A этого документа) также не реализован в репо — рекомендуется включить в ту же волну, он независим.

## 26. Ссылки

- Код аудита: `app/mcp/client.py`, `app/mcp/oriahs_mcp.py`, `app/core/lsp/bus.py`, `app/core/lsp/config.py`, `app/core/lsp/README.md`, `app/tools/` (реестр), `app/api/`.
- Документы: `analytics/ARCHITECT.md`, `analytics/BACKLOG.md` (P-20…P-26), `analytics/ROADMAP.md`, `AGENTS.md`, настоящий объединённый документ (Часть I — фаза PROD; Часть II — P-28…P-34; Приложение A — P-27; Приложение B — P-35…P-38).
- Спецификации: Model Context Protocol (JSON-RPC 2.0, stdio/streamable-HTTP, OAuth 2.1 RFC 6750/6749/9728), Agent Client Protocol (initialize/session/prompt/session-update, stdio, Content-Length), LSP 3.17 (Base Protocol, publishDiagnostics).

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
> Предлагаемые id тикетов: **P-35 (файловые операции), P-36 (git), P-37 (пакетные менеджеры), P-38 (слэш-команды)** — нумерация сдвинута относительно исходного промпта: P-28…P-34 заняты тикетами Части II (коннекторы). Порядок расширения `get_tools()` фиксированный — после `glob` добавляй новые в явном порядке и обновляй все тесты, проверяющие список; для фильтрации по режимам используй `CapabilityRegistry` (B-29).

## Промпт B.1 — файловые операции: `list`, `find`, `delete`, `mkdir`, `move`, `copy`, `chmod` (P-35)

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

## Промпт B.2 — git-команды: единый инструмент `git` (P-36)

Реализуй `app/tools/git.py::git` — единый инструмент-обёртка над git (аналог `git status/add/commit/push/pull` из opencode), вместо пяти отдельных:

1. Параметр `subcommand: str` из allowlist: `status`, `diff`, `log`, `add`, `commit`, `push`, `pull`, `branch`, `stash` (read-only: `status`/`diff`/`log`/`branch` — в permission-allowlist, можно `get_cache()`).
2. Выполнение через `asyncio.create_subprocess_exec("git", subcommand, *args, cwd=workspace)` (никаких `shell=True`); аргументы строго типизированы: `paths: list[str]` (для add), `message: str` (для commit), `remote`/`ref` (для push/pull); инъекция-детект на всех строковых аргументах (`detect_injection`).
3. **Permission-гейтинг:** `commit` — ask по умолчанию; `push`/`pull` — ask всегда (сетевые операции); deny при mode=read-only. Конвенция fail-closed из `app/core/permissions.py`.
4. Вывод: единый JSON-документ `{subcommand, exit_code, stdout, stderr, duration_ms}`; stdout/stderr через `wrap_untrusted()`; лимит вывода (default 50 KB) с усечением.
5. `git commit` — генерация message не входит в инструмент: LLM передаёт готовый `message`; добавь в system-prompt инструкцию конвенций коммитов репозитория (`P-20: ...`).
6. Обработка отсутствия git/репозитория — `ToolException` с человекочитаемым сообщением; таймаут 120 s (`pull/push` — 600 s).
7. Тесты: monkeypatch на subprocess seam (как в `tests/integration/test_tools_integration.py` для `rg`); sandbox-репозиторий через `tmp_path` + `git init` в тесте (если git доступен, иначе conditional skip — конвенция скип-паттернов из AGENTS.md); permission-тесты: push denied без approve.

Критерии приёмки: read-only git-команды в allowlist работают без ask; push/pull требуют подтверждения; вывод — один JSON; EXPECTED-таблицы обновлены.

## Промпт B.3 — пакетные менеджеры: инструмент `pkg` (P-37)

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

## Промпт B.4 — слэш-команды: `/review`, `/explain`, `/audit`, `/plan`, `/compare`, `/check`, `/history`, `/component` (P-38)

В OryaAgent слэш-команды — **UI-слой** (Chainlit M-15 + Next.js B-11), не инструменты: команда разворачивается в пресет системного промпта/агента и отправляется как обычное сообщение. Реализуй фреймворк + 8 команд:

1. `app/core/slash.py::SlashRegistry`: `register(name, builder)`; `resolve(text) -> SlashCommand | None` (парсинг `/<name> [args]`); команда инжектирует пресет-блок в system-prompt на один turn (не ломая cacheable prefix: пресет — динамическая секция в конце, как memory-блоки).
2. Команды (каждая — builder, возвращающий системную инструкцию + опциональные параметры инструментов):
   - `/review [path|diff]` — ревью кода: инструкция «найди ошибки, отсутствующие тесты, security-проблемы; используй grep/read/lsp_diagnostics; верни список findings с severity»;
   - `/explain [path|symbol]` — объяснение кода: read + lsp_hover/lsp_definition, структурное объяснение;
   - `/audit` — аудит зависимостей: `pkg audit` (npm audit / pip-audit через P-37), отчёт по уязвимостям;
   - `/plan [task]` — планирование: переход в режим planner (tier=small), вывод плана без выполнения (tool_choice=none на первый ход);
   - `/compare [a b]` — сравнение файлов/веток: git diff (P-36) + структурное сравнение;
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
| Часть II | Аудит коннекторов и промпты: MCP-compliant клиент, MCP hardening, ACP-сервер, LSP-транспорт hotfix, LSP expansion, web tools, planning/subagents | P-28…P-34 |
| Приложение B.1 | Файловые операции: list, find, delete, mkdir, move, copy, chmod | P-35 |
| Приложение B.2 | Git: единый инструмент с permission-гейтингом | P-36 |
| Приложение B.3 | Пакетные менеджеры: npm/pip/uv/cargo/go | P-37 |
| Приложение B.4 | Слэш-команды UI: /review, /explain, /audit, /plan, /compare, /check, /history, /component | P-38 |

**Готов к реализации.** Порядок: сначала основной план фазы PROD (§16); Часть II (P-28…P-34) — по приоритету P-31 → P-32 → P-28 → P-30 → P-29 → P-33 → P-34 (P-31/P-32 — hotfix BETA до старта PROD); Приложения A (P-27) и B (P-35…P-38) — параллельно неделями 4-8, когда core-seams стабилизированы. После завершения фазы — переход к EXTENSION-PROD (E-12..E-14, опционально).
