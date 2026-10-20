# BACKLOG6 — Бэклог задач OryaAgent v6 (memory + /learn + observability)

> **Версия документа:** 6.0
> **Дата:** 20 октября 2026
> **Источники:** `ARCHITECT6.md` v6.0, `ROADMAP6.md` v6.0, `BACKLOG5.md` v5.0 (baseline)
> **Стек:** Python 3.11+, LangChain 0.3+, LangGraph 0.2+, FastAPI, PostgreSQL 16, Redis 7, Chainlit, OriaHS, OryaObservability SDK
> **Формат:** spec-driven тикеты (Context / Goal / Constraints / Acceptance Criteria / Forbidden patterns / Suggested files)
> **Гранулярность:** 1 тикет = 1 задача (~2 часа – 2 дня работы)
> **Статус:** бэклог готов к реализации; v6 — надстройка над v5, не замена

---

## Содержание

0. Что изменилось относительно v5 (executive summary)
1. Как пользоваться этим документом
2. Фаза MVP (M-00 … M-27) — 28 тикетов (25 v5 + 3 новых)
3. Фаза ALPHA (A-00 … A-17) — 18 тикетов (16 v5 + 2 новых)
4. Фаза BETA (B-00 … B-23) — 24 тикета (21 v5 + 3 новых)
5. Фаза PROD (P-00 … P-19) — 20 тикетов (18 v5 + 2 новых)
6. Фаза EXTENSION-PROD (E-00 … E-11) — 12 тикетов (11 v5 + 1 новый)
7. Фаза FUTURE (F-00 … F-09) — 10 тикетов (9 v5 + 1 новый)
8. Meta-тикеты (R-01 … R-05) — 5 тикетов (4 v5 + 1 новый)
9. Сводная матрица тикетов × фаз
10. Карта зависимостей между тикетами
11. Соответствие тикетов ТРИЗ-принципам и 20/80

---

## 0. Что изменилось относительно v5 (executive summary)

`BACKLOG6.md` сохраняет структуру `BACKLOG5.md`, но добавляет **12 новых тикетов** для реализации 5 улучшений v6 (см. `ARCHITECT6.md` §0):

### Новые тикеты в v6

| ID | Title | Фаза | Принцип | Estimate |
|---|---|---|---|---|
| **M-25** | MDStore: L0 MD-файлы (4 шт.) + atomic-append | MVP | #21 Rushing | 4 часа |
| **M-26** | `/learn` endpoint + Chainlit slash-command | MVP | #25 Self-service | 4 часа |
| **M-27** | Compactor (L0 → L1 placeholder) + /memory/compact | MVP | #19 Periodic action | 4 часа |
| **A-16** | OryaObservability SDK integration (instrument LangGraph) | ALPHA | #28 Mechanics substitution | 1 день |
| **A-17** | Sampler-proxy mode (LANGFUSE_HOST → proxy) + cost/security span attributes | ALPHA | #15 Dynamicity | 6 часов |
| **B-21** | SQLiteStore (L1, FTS5, SQLCipher) + MemoryOutbox + drain-worker | BETA | #1 Segmentation | 2 дня |
| **B-22** | Memory-extractor LLM-worker (batch, haiku) | BETA | #28 Mechanics substitution | 1 день |
| **B-23** | `/remember`, `/forget`, `/memory list/export/import` endpoints + UI | BETA | #25 Self-service | 1 день |
| **P-18** | L2 Qdrant via OriaHS (memory collection) + memory_search tool | PROD | #15 Dynamicity | 1 день |
| **P-19** | Distributed tracing через MCP + offline-eval для /learn | PROD | #28 Mechanics substitution | 1 день |
| **E-11** | Multi-instance memory replication (sync через OriaHS) | EXTENSION-PROD | #15 Dynamicity | 1 неделя |
| **F-09** | Continuous prompt-learning (LLM-judge per memory-write) | FUTURE | #35 Parameter changes | — |
| **R-05** | Memory-architecture documentation (3-tier hybrid) | meta | — | 4 часа |

**Итого:** v6 содержит 117 тикетов (vs 104 в v5). Увеличение на 12% — за счёт memory + observability integration.

### Изменённые тикеты v6 vs v5

| ID v5 | Что изменилось в v6 |
|---|---|
| M-05 | SystemPromptBuilder теперь инжектирует L0 memory block (см. M-25) |
| M-13 | PermissionPolicy: /learn, /memory/* — без interrupt (trust user explicit command) |
| M-18 | Smoke-тесты: добавлены проверки /learn, /memory/stats, atomic-append durability |
| B-00 | Memory cross-session via PostgresStore → REMOVED, заменён на B-21 (SQLiteStore) + B-22 (extractor) + B-23 (commands) |
| B-11 | Memory injection в system-prompt → обновлён: инжектирует L0 (4 MD-файла), не произвольные past-summaries |
| A-04 | Observability: добавлен A-16 (OryaObservability SDK) и A-17 (sampler-proxy mode) |
| A-13 | CostAwareRouter: добавлен emit `cost.over_budget` span attribute (см. A-17) |
| M-22 | Prompt injection defense: добавлен emit `security.incident` span attribute (см. A-17) |

---

## 1. Как пользоваться этим документом

(см. `BACKLOG5.md` §1 — без изменений)

Структура тикета:
```
### {ID} — {Title}
> Component: {ARCHITECT6 §ref} | Dependencies: {IDs} | Estimate: {days/hours} | TRIZ: {principle(s)}
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

Все тикеты v5 (M-00..M-24, A-00..A-15, B-00..B-20, P-00..P-17, E-00..E-10, F-00..F-08, R-01..R-04) остаются в силе без изменений, если явно не упомянуты в §0 «Изменённые тикеты v6 vs v5». Ниже описаны **только новые и изменённые** тикеты.

---

## 2. Фаза MVP (M-25 … M-27 — новые в v6)

### M-25 — MDStore: L0 MD-файлы + atomic-append 🆕

> **Component:** ARCHITECT6 §3.1, §6.1.1, §4.2 | **Dependencies:** M-02 (settings), M-04 (graph skeleton) | **Estimate:** 4 часа | **TRIZ:** #21 Rushing

#### Context

В v5 B-00 (Memory cross-session) — «как в v4 через PostgresStore», без конкретной стратегии. В v6 вводится L0 — MD-файлы, которые:
- Always-in-prompt (bootstrap): 4 KB на файл, ~1000 токенов на system-prompt.
- Fast write через atomic-append (< 1 мс типично).
- Human-readable & editable: пользователь открывает `LEARNED.md`, видит список, правит.
- Git-diffable (если пользователь захочет версионировать memory-директорию в отдельном private-repo).

L0 — критичный слой, потому что /learn должен писать за < 10 мс (не блокировать user-turn) и запись должна быть durable (survive crash). SQLite INSERT — 5-10 мс; MD append — < 1 мс. Поэтому /learn пишет в L0 MD, не в L1 SQLite.

#### Goal

Реализовать `app/core/memory/md_store.py::MDStore` с 4 MD-файлами:
- `PREFERENCES.md` (≤ 2 KB) — preferences пользователя/проекта.
- `LEARNED.md` (≤ 4 KB) — успешно выполненные команды (через /learn).
- `FACTS.md` (≤ 2 KB) — критические факты о проекте.
- `DECISIONS.md` (≤ 2 KB) — архитектурные решения (короткие выжимки).

Реализовать atomic-append через `open(path, "a") + fsync` с per-file `threading.Lock`.

#### Constraints

- Расположение: `$ORYA_MEMORY_DIR` (default `~/.orya/memory/`).
- Директория создаётся при первом запуске (`mkdir -p`).
- Формат записи: см. ARCHITECT6 §3.1.1 (markdown-блок с YAML-like meta-строкой).
- Atomic-append: для writes < 4096 bytes POSIX гарантирует atomicity в O_APPEND mode.
- `fsync` после каждого append — durability при crash.
- Per-file `threading.Lock` — защищает от lost-updates внутри процесса.
- `read_all()` — для system-prompt injection, читает все 4 файла, возвращает `dict[filename, content]`.
- `stats()` — для /memory/stats: размер, кол-во записей, last-write timestamp.

#### Acceptance Criteria

- ✅ `MDStore(Path("/tmp/test_memory"))` создаёт директорию и 4 пустых файла.
- ✅ `md_store.append("LEARNED.md", entry)` пишет в конец файла, fsync.
- ✅ Concurrent `append` из 10 threads — все 10 записей сохраняются (no lost-updates).
- ✅ После crash (kill -9) в середине append — файл либо содержит старую запись полностью, либо новую полностью (no partial writes).
- ✅ `md_store.read_all()` возвращает dict с 4 ключами.
- ✅ `md_store.stats()` возвращает размер, кол-во, last-write для каждого файла.
- ✅ Запись размером 500 bytes завершается за < 1 мс (benchmark в test).
- ✅ Если файл > 4 KB после append — `compact_if_needed()` вызывается async (см. M-27).

#### Forbidden patterns

- ❌ Использовать `open(path, "w")` для append — потеряет данные при concurrent writes.
- ❌ Использовать in-memory cache без flush — теряется при crash.
- ❌ Использовать async-file-IO без fsync — не durable.
- ❌ Хранить absolute paths в MD-файлах — ломает portability.
- ❌ Хранить PII в MD без пометки `pii=true` — нарушает audit.

#### Suggested files

- `app/core/memory/__init__.py`
- `app/core/memory/md_store.py`
- `app/core/memory/models.py` (MemoryItem dataclass)
- `tests/test_md_store.py`

---

### M-26 — `/learn` endpoint + Chainlit slash-command 🆕

> **Component:** ARCHITECT6 §4.3, §8.1 | **Dependencies:** M-14 (session-log), M-20 (FastAPI), M-25 (MDStore) | **Estimate:** 4 часа | **TRIZ:** #25 Self-service

#### Context

Пользователь хочет зафиксировать успешный паттерн в один клик/команду. В v5 такой возможности нет — память только «как в v4 через PostgresStore», без явных команд. В v6 добавляется `/learn` — capture последнего успешного tool-call-sequence из session-log → atomic-append в `LEARNED.md`.

«Успешный» определяется как:
- Tool-call завершился без exception.
- Exit-code / status — success (для bash: `exit_code=0`, для edit: `applied=true`, для read: `file_exists=true`).
- Пользователь не прервал (не cancel в interrupt-modal).

#### Goal

Реализовать:
1. FastAPI endpoint `POST /sessions/{thread_id}/learn` — извлекает последний успешный sequence из session-log, формирует запись в формате ARCHITECT6 §3.1.1, atomic-append в `LEARNED.md`, возвращает `learned_id` + `compacted` flag.
2. Chainlit slash-command `/learn [name] [description]` — вызывает endpoint, показывает feedback.
3. Memory-audit log entry (JSONL).

#### Constraints

- Endpoint signature: см. ARCHITECT6 §4.3.1.
- Если `pattern_name` не передан — auto-name через `tool1_tool2_...` (например, `grep_read_edit`).
- `scope`: `session` (default) | `project` | `global`. Сейчас реализован только `project` (пишет в `~/.orya/memory/LEARNED.md`); `session` и `global` — заглушки (TODO в B-21 для session, E-11 для global).
- Atomic-append — неблокирующий (через M-25).
- Async compaction запускается после append, но не блокирует response.
- Memory-audit log: `~/.orya/logs/memory_audit.jsonl` (rotation 30 дней).
- Chainlit: `cl.AskActionMessage` не нужен — `/learn` это explicit user action, без подтверждения.
- Если последний sequence не успешный (была ошибка) — вернуть 400 с понятным сообщением.

#### Acceptance Criteria

- ✅ `POST /sessions/{thread_id}/learn` с body `{}` возвращает `{learned_id, file, compacted}`.
- ✅ Запись появляется в `LEARNED.md` в формате ARCHITECT6 §3.1.1.
- ✅ Memory-audit log содержит entry с op=learn, file, memory_id, source, trace_id.
- ✅ Chainlit `/learn` показывает feedback: «✅ Learned: learn_001 → LEARNED.md (compacted: false)».
- ✅ `/learn refactor_extract "Refactor: extract function"` — создаёт запись с pattern_name=refactor_extract, description=...
- ✅ Если последний tool-call был с ошибкой — 400 «No successful tool-call sequence to learn».
- ✅ Concurrent `/learn` из 2 сессий — обе записи сохраняются (no lost-updates).

#### Forbidden patterns

- ❌ Блокировать response на compaction — async только.
- ❌ Использовать LLM для извлечения pattern (на MVP) — просто записать sequence как есть.
- ❌ Писать в L1 SQLite (это B-21) — только L0 MD.
- ❌ Использовать `time.sleep()` для ожидания compaction — async.

#### Suggested files

- `app/api/routes/learn.py`
- `app/core/memory/audit.py`
- `app/ui/chainlit_app.py` (update: handle `/learn` slash-command)
- `tests/test_learn_endpoint.py`

---

### M-27 — Compactor + `/memory/compact`, `/memory/stats` 🆕

> **Component:** ARCHITECT6 §3.4, §4.2.2, §6.1.4 | **Dependencies:** M-25 (MDStore) | **Estimate:** 4 часа | **TRIZ:** #19 Periodic action

#### Context

L0 MD-файлы имеют лимит 4 KB. Если /learn вызывается часто, файл быстро растёт. Без compaction — система деградирует: system-prompt разрастается, /learn начинает тормозить (большой append).

В MVP L1 SQLite ещё не реализован (это B-21). Поэтому Compactor в MVP делает «soft compaction»: удаляет low-confidence и старые записи, переносит в `~/.orya/memory/archive/LEARNED_<date>.md` (plain archive, без SQLite). В BETA (B-21) — переносит в L1 SQLite.

#### Goal

Реализовать:
1. `app/core/memory/compactor.py::Compactor` с 4 стратегиями (по одной на файл).
2. FastAPI endpoints:
   - `POST /sessions/{thread_id}/memory/compact` — принудительная compaction всех 4 файлов.
   - `GET /sessions/{thread_id}/memory/stats` — размер, кол-во, last-write для каждого файла.
   - `GET /sessions/{thread_id}/memory` — показать содержимое 4 файлов (cat).
3. Chainlit slash-commands `/memory compact`, `/memory stats`, `/memory`.
4. Periodic background-task: каждые 24 часа проверять все 4 файла, compact_if_needed.

#### Constraints

- Стратегии (см. ARCHITECT6 §4.2.2):
  - `PREFERENCES.md`: keep all `source=user_explicit`; archive `source=agent_inferred` с `confidence < 0.8`.
  - `LEARNED.md`: keep last 10 + high-confidence (≥ 0.9); archive старые / low-confidence.
  - `FACTS.md`: keep all `confidence >= 0.9`; archive остальные.
  - `DECISIONS.md`: keep non-superseded; archive superseded.
- Archive: `~/.orya/memory/archive/<filename>_<date>.md` (append-only archive).
- Atomic rewrite: `os.rename(tmp, target)` — atomic на POSIX.
- Periodic task: `asyncio.create_task` с `asyncio.sleep(24 * 3600)`, configurable.
- Stats response: `{files: [{name, size_bytes, entries_count, last_write_ts}], total_size_bytes}`.

#### Acceptance Criteria

- ✅ После 20 `/learn` вызовов (LEARNED.md > 4 KB) — `compact_if_needed` запускается async.
- ✅ После compaction — LEARNED.md ≤ 4 KB, архив содержит перенесённые записи.
- ✅ `POST /memory/compact` — синхронная compaction всех 4 файлов, возвращает result per file.
- ✅ `GET /memory/stats` — возвращает размеры, кол-во, last-write.
- ✅ `GET /memory` — возвращает конкатенацию 4 файлов (markdown).
- ✅ Periodic task запускается раз в 24 часа (проверить через mock time в test).
- ✅ Atomic rewrite: после crash в середине rewrite — файл либо старый, либо новый (no partial).

#### Forbidden patterns

- ❌ Использовать `os.unlink` + `open(w)` — не atomic, окно потери данных.
- ❌ Блокировать user-turn на compaction — async только (кроме `/memory/compact` endpoint).
- ❌ Удалять записи навсегда — archive обязателен.
- ❌ Compaction без per-file lock — race condition.

#### Suggested files

- `app/core/memory/compactor.py`
- `app/api/routes/memory.py`
- `app/ui/chainlit_app.py` (update: handle `/memory*` slash-commands)
- `tests/test_compactor.py`

---

## 3. Фаза ALPHA (A-16 … A-17 — новые в v6)

### A-16 — OryaObservability SDK integration 🆕

> **Component:** ARCHITECT6 §9.1, §9.2 | **Dependencies:** A-02 (LLM seam), A-04 (observability baseline), M-04 (graph) | **Estimate:** 1 день | **TRIZ:** #28 Mechanics substitution

#### Context

В v5 observability — «LangSmith/LangFuse через env-переменные». Это работает на базовом уровне (traces уходят), но упускает 4 важных слоя observability для LLM-агентов (см. ARCHITECT6 §9.1):
1. PII-маскирование в traces (OryaObservability `agent_obs.guardrail`).
2. Per-token cost-tracking через `price_book.yaml` (OryaObservability `agent_obs.cost`).
3. Rule-based + LLM-as-judge eval (OryaObservability `agent_obs.eval`).
4. Embedding-drift и KL-divergence (OryaObservability `agent_obs.drift`).

20/80: вместо написания своего PII-маскирования и cost-tracker'а (~2000+ LOC), OryaAgent подключает готовый `agent_obs` package — 5% усилий, 80% ценности.

#### Goal

1. Добавить `agent-obs` в dependencies (`pyproject.toml`).
2. Реализовать `app/core/observability.py::OryaObservability` wrapper:
   - Инициализация `ObservabilitySDK` с guardrail, exporter, price_book.
   - `instrument_graph(graph)` — обернуть LangGraph nodes в spans (agent.loop, llm.call, tool.call).
   - `emit_memory_write(memory_id, file, source, compacted)` — start_span("memory.write").
3. Настроить environment variables (см. ARCHITECT6 §9.3.4).
4. Тест: запуск agent-loop → проверка, что span уходит в exporter (mock Langfuse).

#### Constraints

- `agent-obs` package: editable install из `../OryaObservability` (или pip install после публикации).
- LangGraph instrumentation: использовать `astream_events` v2 для перехвата `on_chat_model_stream`, `on_tool_start`, `on_tool_end`.
- Span-types: `agent.loop` (root), `llm.call` (chat-model invocation), `tool.call` (tool invocation), `memory.write` (custom).
- PII-маскирование: in-process, fail-closed (если guardrail unavailable → `[REDACTED:guardrail_unavailable]`).
- Cost-tracking: использовать `agent_obs.cost.compute_cost(usage, model, book)` для каждого `llm.call`.
- Price book: `price_book.yaml` в корне проекта (см. OryaObservability `price_book.yaml`).
- `AGENT_OBS_ENABLED=false` — все decorators становятся no-op (для dev/test).

#### Acceptance Criteria

- ✅ `pip install -e ../OryaObservability` работает.
- ✅ `OryaObservability(settings)` инициализируется без ошибок.
- ✅ `instrument_graph(graph)` — каждый LLM-call и tool-call создаёт span.
- ✅ Span `agent.loop` имеет `agent.id`, `agent.version`, `task.input` (PII-masked).
- ✅ Span `llm.call` имеет `provider`, `model`, `tokens.in`, `tokens.out`, `cost`.
- ✅ Span `tool.call` имеет `tool.name`, `tool.input` (PII-masked), `tool.output` (PII-masked).
- ✅ `emit_memory_write(...)` создаёт span `memory.write` с правильными атрибутами.
- ✅ PII в prompt (например, email) — маскируется в span attributes.
- ✅ Mock Langfuse exporter получает все spans.
- ✅ `AGENT_OBS_ENABLED=false` — decorators no-op, graph работает без observability.

#### Forbidden patterns

- ❌ Писать свой PII-masking — использовать `agent_obs.guardrail`.
- ❌ Писать свой cost-tracker — использовать `agent_obs.cost.compute_cost`.
- ❌ Блокировать agent-loop на observability — fire-and-forget export.
- ❌ Хранить plaintext PII в spans — маскирование обязательно in-process.
- ❌ Использовать LangSmith exporter — только Langfuse (для совместимости с sampler-proxy).

#### Suggested files

- `app/core/observability.py`
- `pyproject.toml` (add `agent-obs` dependency)
- `price_book.yaml` (copy from OryaObservability)
- `tests/test_observability_integration.py`

---

### A-17 — Sampler-proxy mode + cost/security span attributes 🆕

> **Component:** ARCHITECT6 §9.3 | **Dependencies:** A-13 (CostAwareRouter), M-22 (injection defense), A-16 (SDK) | **Estimate:** 6 часов | **TRIZ:** #15 Dynamicity, #11 Beforehand cushioning

#### Context

Sampler-proxy в OryaObservability (PC30-32) — OTLP/HTTP proxy с динамической sample-rate. Решает проблему: OTel Collector не имеет admin-API для reload, смена rate требует рестарта. Proxy хранит rate in-memory, применение — одно присваивание под lock.

Sampler-proxy **всегда сохраняет** трейсы с атрибутами:
- `status.code == STATUS_CODE_ERROR`
- `cost.over_budget == "true"`
- `security.incident == "true"`

Чтобы OryaAgent попадал в always-keep при cost-превышении или prompt-injection — нужно эмитить эти span attributes. Это доработка CostAwareRouter (A-13) и injection-detector (M-22).

#### Goal

1. Настроить `LANGFUSE_HOST=http://sampler-proxy:4321` в docker-compose (вместо `http://langfuse:3000`).
2. Доработать `CostAwareRouter.get_model_for_user()` — при `budget_ratio >= 0.9` эмитить `cost.over_budget=true` на текущем `agent.loop` span.
3. Доработать `detect_injection(content)` — при detect эмитить `security.incident=true` на текущем `tool.call` span.
4. Добавить docker-compose сервис `sampler-proxy` (image `agent-obs-sampler:latest`).
5. Health-check endpoints: `/health/observability`, `/health/sampler-proxy`.
6. Тест: end-to-end — cost-превышение → trace сохраняется в Langfuse (через sampler-proxy always-keep).

#### Constraints

- Sampler-proxy image: build из `../OryaObservability/scripts/sampler/Dockerfile`.
- Ports: `4321:4321` (OTLP/HTTP), `9095:9095` (Prometheus /metrics).
- `DOWNSTREAM_URL=http://langfuse:3000` (Langfuse base URL, без `/api/public/otel/v1/traces`).
- `PROMETHEUS_URL=http://prometheus:9090` — для PolicyEngine.
- `AGENT_OBS_SAMPLER_MODE=proxy` (default).
- `AGENT_OBS_SAMPLER_AUDIT_ENABLED=1` — audit в ClickHouse.
- Span attributes: строковые `"true"`, не boolean (см. `is_interesting_span()` в sampler_proxy.py).
- CostAwareRouter: emit атрибут **до** возврата model, чтобы span был помечен до завершения turn.
- detect_injection: emit атрибут **внутри** tool-call span (через `trace.get_current_span()`).

#### Acceptance Criteria

- ✅ `docker compose up sampler-proxy langfuse` — оба сервиса здоровы.
- ✅ `GET http://sampler-proxy:4321/sampler/status` возвращает `{current_rate, policy_reason, last_changed_at}`.
- ✅ OryaAgent шлёт OTLP/HTTP на `http://sampler-proxy:4321` (видно в логах SDK).
- ✅ При `budget_ratio >= 0.9` — span `agent.loop` имеет атрибут `cost.over_budget=true`.
- ✅ При injection-detect — span `tool.call` имеет атрибут `security.incident=true`.
- ✅ Traces с `cost.over_budget=true` — всегда сохраняются в Langfuse (даже если `current_rate=0.05`).
- ✅ Traces с `security.incident=true` — всегда сохраняются.
- ✅ Audit-запись появляется в ClickHouse `audit_events_hot` при смене rate.
- ✅ `/health/observability` — `{sdk_enabled, exporter_connected, guardrail_ready}`.
- ✅ `/health/sampler-proxy` — ping `http://sampler-proxy:4321/sampler/status`, 200 OK.

#### Forbidden patterns

- ❌ Использовать `LANGFUSE_HOST=http://langfuse:3000` напрямую — теряем sampler-proxy.
- ❌ Эмитить boolean `true` вместо string `"true"` — sampler-proxy сравнивает со строкой.
- ❌ Блокировать agent-loop на health-check — async с timeout.
- ❌ Hardcoded URLs в коде — через settings/env.

#### Suggested files

- `app/core/llm.py` (update CostAwareRouter)
- `app/tools/security.py` (update detect_injection)
- `app/api/routes/health.py` (add observability + sampler-proxy checks)
- `infra/docker-compose.yml` (add sampler-proxy service)
- `tests/test_sampler_proxy_integration.py`

---

## 4. Фаза BETA (B-21 … B-23 — новые в v6; B-00 REMOVED)

### B-00 — REMOVED 🆕

В v5 B-00 был «Memory cross-session via PostgresStore (как в v4)». В v6 заменён на B-21 (SQLiteStore L1) + B-22 (memory-extractor) + B-23 (memory commands). Это соответствует ADR-005, который уже есть в репозитории, но не был интегрирован в BACKLOG5.

### B-21 — SQLiteStore (L1, FTS5, SQLCipher) + MemoryOutbox + drain-worker 🆕

> **Component:** ARCHITECT6 §3.2, §6.1.2, §6.1.3 | **Dependencies:** M-25 (MDStore), M-27 (Compactor) | **Estimate:** 2 дня | **TRIZ:** #1 Segmentation

#### Context

L0 MD-файлы не масштабируются > 100 записей (см. ARCHITECT6 §2.4). Для structured queries («покажи все TODO за месяц»), lexical search («помнишь, обсуждали memory-tier?»), forget-by-pattern и conflict resolution нужен SQL. ADR-005 уже спроектировал SQLite FTS5 + SQLCipher схему; в v6 реализуем.

SQLiteStore (L1) — per-project, SQLCipher-encrypted. MemoryOutbox — таблица в той же SQLite-БД, drain-воркер асинхронно читает outbox, делает embedding (bge-m3) и POST `/index` в OriaHS (L2 Qdrant, в PROD — P-18).

#### Goal

1. Реализовать `app/core/memory/sqlite_store.py::SQLiteStore`:
   - `insert(item) → id` — INSERT + FTS5 trigger + outbox entry.
   - `search(query, types, top_k) → list[MemoryItem]` — FTS5 + filter.
   - `forget(pattern) → count` — soft-delete (`is_deleted=1`).
   - `supersede(old_id, new_id)` — UPDATE superseded_by.
   - `export() → list[dict]`, `import_(items) → count`.
2. Реализовать `app/core/memory/outbox.py::MemoryOutbox`:
   - `enqueue(memory_id, op, payload)`.
   - `drain_batch(batch_size) → list[OutboxItem]`.
   - `mark_done(item_id)`.
3. Реализовать drain-worker (background asyncio task):
   - Читает outbox batch по 50.
   - Делает embedding через `bge-m3` (локальная модель, CPU).
   - POST `/index` в OriaHS (если available — иначе retry).
   - Mark done в outbox.
4. SQLCipher encryption: ключ из OS keychain (macOS Keychain / Linux secret-tool / Windows DPAPI).

#### Constraints

- Файл: `~/.orya/memory/<project>.sqlite` (SQLCipher-encrypted).
- Схема: см. ARCHITECT6 §7.2 (соответствует ADR-005 §2.2).
- FTS5 tokenizer: `porter unicode61` — для русского + английского.
- Embeddings: `bge-m3` (1024-dim), локально через `sentence-transformers` или `fastembed`.
- Drain-worker: `asyncio.create_task` с `asyncio.sleep(60)` между batch'ами.
- Если OriaHS unavailable — retry с exponential backoff (1s, 2s, 4s, ..., max 5min).
- SQLCipher key: если keychain unavailable — fallback на env-variable `ORYA_MEMORY_KEY` (warn user).
- Запись в SQLite — async через `aiosqlite`.

#### Acceptance Criteria

- ✅ `SQLiteStore(Path("/tmp/test.sqlite"), key="test")` создаёт БД с таблицами из ARCHITECT6 §7.2.
- ✅ `insert(MemoryItem(type="fact", content="...", ...))` — записывает в `memory_items` и `memory_fts`.
- ✅ `search("memory", types=["fact"], top_k=5)` — возвращает релевантные записи.
- ✅ `forget("memory")` — помечает `is_deleted=1` для matching records, возвращает count.
- ✅ `supersede(old_id, new_id)` — устанавливает `superseded_by` на old_id.
- ✅ SQLCipher encryption: `.sqlite` файл не читается без ключа (проверить через `sqlite3` CLI без PRAGMA key).
- ✅ Outbox: insert → enqueue, drain-worker → embedding + POST /index (mock OriaHS).
- ✅ Drain-worker retry: OriaHS down → retry с backoff, не теряет entries.
- ✅ `export() → import_()` round-trip: данные сохраняются.

#### Forbidden patterns

- ❌ Хранить SQLCipher key в plaintext — только OS keychain или env-variable.
- ❌ Использовать `sqlite3` module синхронно в agent-loop — только `aiosqlite` async.
- ❌ Embedding через OpenAI API (дорого + privacy) — только локальная bge-m3.
- ❌ Drain-worker блокирует agent-loop — background task.
- ❌ FTS5 tokenizer без `unicode61` — плохо для русского.

#### Suggested files

- `app/core/memory/sqlite_store.py`
- `app/core/memory/outbox.py`
- `app/core/memory/drain_worker.py`
- `app/core/memory/embedding.py` (bge-m3 wrapper)
- `app/core/keychain.py` (OS keychain access)
- `tests/test_sqlite_store.py`

---

### B-22 — Memory-extractor LLM-worker (batch, haiku) 🆕

> **Component:** ARCHITECT6 §3.4, ADR-005 §6.1 | **Dependencies:** B-21 (SQLiteStore) | **Estimate:** 1 день | **TRIZ:** #28 Mechanics substitution

#### Context

Не все memory-items попадают в L0 через явные команды (/learn, /remember). Большая часть — agent-inferred: агент сам извлекает facts/decisions/todos из разговоров. Делать это в основном agent-loop — дорого (LLM-call на каждом turn). ADR-005 §2.4 предлагает отдельного memory-extractor-воркера на дешёвой модели (gpt-4o-mini / claude-haiku / yandex-gpt-lite), запускаемого:
- после каждого 10-го сообщения сессии (batch);
- при явной команде `/remember` (без аргументов — извлечь из последних сообщений);
- при закрытии сессии (final pass).

#### Goal

1. Реализовать `app/core/memory/extractor.py::MemoryExtractor`:
   - `extract(conversation_fragment) → list[MemoryItem]` — LLM-call на haiku.
   - Prompt: см. ADR-005 §6.1.
   - Output: JSON array of `{type, content, confidence, project, supersede_id}`.
   - Deduplicate: проверка на existing items через FTS5 search.
2. Batch-trigger: после каждых 10 сообщений в сессии — async extraction.
3. Final-pass: при `POST /sessions/{id}/close` — extraction всей сессии.
4. Confidence: explicit user-mention → 0.95, agent-inferred high-confidence → 0.8, low → 0.5.
5. Если confidence < 0.7 — помечать `needs_review=true`, не инжектировать в L0 (только L1).

#### Constraints

- LLM: `settings.llm_memory_extractor_model` (default `claude-haiku` или `gpt-4o-mini`).
- Cost-target: < $0.02 за extraction (на haiku).
- Prompt template: см. ADR-005 §6.1.
- Batch size: 10 сообщений (configurable).
- Async — не блокировать agent-loop.
- Deduplicate через FTS5: если найден existing item с score > 0.8 — supersede, не insert.
- Final-pass: при close session, отдельная LLM-call на всю сессию.

#### Acceptance Criteria

- ✅ После 10 сообщений в сессии — async extraction запускается.
- ✅ Extractor возвращает список MemoryItem с правильными типами.
- ✅ Confidence: explicit user-mention → 0.95, inferred → 0.5-0.8.
- ✅ Deduplicate: похожий existing item → supersede, не duplicate.
- ✅ Low-confidence items (`< 0.7`) — помечены `needs_review=true`.
- ✅ Cost: < $0.02 за extraction (проверить через mock billing).
- ✅ Final-pass при close session — extraction всей сессии.
- ✅ Если extractor LLM unavailable — log warning, retry на следующем batch.

#### Forbidden patterns

- ❌ Использовать основную модель (Sonnet) для extraction — дорого.
- ❌ Синхронный extraction в agent-loop — async только.
- ❌ Insert без dedup check — будут дубликаты.
- ❌ Хранить plaintext PII в extracted memory — PII-masking через guardrail.

#### Suggested files

- `app/core/memory/extractor.py`
- `app/core/memory/prompts.py` (extraction prompt template)
- `tests/test_memory_extractor.py`

---

### B-23 — `/remember`, `/forget`, `/memory list/export/import` endpoints + UI 🆕

> **Component:** ARCHITECT6 §4.4, §8.1 | **Dependencies:** M-25 (MDStore), M-26 (/learn), B-21 (SQLiteStore), B-22 (extractor) | **Estimate:** 1 день | **TRIZ:** #25 Self-service

#### Context

В MVP у нас есть только /learn и /memory/stats/compact. В BETA добавляются остальные memory-команды:
- `/remember <text>` — explicit fact/preference.
- `/forget <pattern>` — soft-delete по pattern.
- `/forget session <id>` — forget эпизодов конкретной сессии.
- `/memory list [type]` — просмотр L0 + L1.
- `/memory export` — экспорт в JSON.
- `/memory import <file>` — импорт из JSON.

Эти команды работают с обоими слоями L0 (MD) и L1 (SQLite) — в зависимости от типа и confidence.

#### Goal

1. FastAPI endpoints (см. ARCHITECT6 §8.1):
   - `POST /sessions/{id}/remember` — body: `{text, type, scope}`. Если type=preference и confidence=high → L0 + L1. Иначе → L1 only.
   - `POST /sessions/{id}/forget` — body: `{pattern}` или `{session_id}`. Soft-delete в L1 + remove from L0.
   - `GET /sessions/{id}/memory?type=` — list L0 (cat) + L1 (SQL).
   - `GET /sessions/{id}/memory/export` — JSON export of L0 + L1.
   - `POST /sessions/{id}/memory/import` — JSON import в L0 (high-confidence) + L1 (rest) + outbox → L2.
2. Chainlit slash-commands: `/remember`, `/forget`, `/memory list`, `/memory export`, `/memory import`.
3. Next.js UI (B-05): sidebar с memory-tree, «remember this» button у каждого message.

#### Constraints

- `/remember` без type — auto-detect через LLM-mini (haiku): fact vs preference vs decision.
- `/forget` — soft-delete (`is_deleted=1` в L1, remove из L0), не hard-delete.
- `/forget session <id>` — metadata-filter в L1 (`source=session_id`), remove из L0 (по metadata).
- Export: JSON `{version, exported_at, l0: {file: content}, l1: [items]}`.
- Import: validate schema, dedup through FTS5, enqueue to outbox.
- UI: memory-tree показывает L0 files + L1 items count per type.
- UI: «remember this» button — quick /remember с current message как text.

#### Acceptance Criteria

- ✅ `/remember "Project uses PostgreSQL 16"` (auto-detect type=fact) — добавляет в L0 FACTS.md + L1.
- ✅ `/forget "*TS*"` — soft-delete matching L1 items, remove from L0, возвращает count.
- ✅ `/forget session sess_2026_10_20` — soft-delete эпизодов конкретной сессии.
- ✅ `/memory list fact` — возвращает L0 FACTS.md content + L1 fact items.
- ✅ `/memory export` — валидный JSON, round-trip через `/memory import` сохраняет данные.
- ✅ UI: memory-tree sidebar показывает 4 L0 files + L1 counts.
- ✅ UI: «remember this» button создаёт /remember с текущим сообщением.

#### Forbidden patterns

- ❌ Hard-delete в L1 — только soft-delete (`is_deleted=1`).
- ❌ Import без dedup — будут дубликаты.
- ❌ `/forget` без audit log — все forget-операции должны логироваться.
- ❌ Export PII без маскирования — если `mask_pii=true` в query param.

#### Suggested files

- `app/api/routes/memory.py` (extend: /remember, /forget, /memory list, export, import)
- `app/ui/chainlit_app.py` (update: handle new slash-commands)
- `frontend/components/MemoryTree.tsx` (Next.js)
- `tests/test_memory_commands.py`

---

## 5. Фаза PROD (P-18 … P-19 — новые в v6)

### P-18 — L2 Qdrant via OriaHS (memory collection) + memory_search tool 🆕

> **Component:** ARCHITECT6 §3.3, §6.3 | **Dependencies:** P-00 (OriaHS bootstrap), B-21 (SQLiteStore + outbox) | **Estimate:** 1 день | **TRIZ:** #15 Dynamicity

#### Context

L1 SQLite даёт lexical search, но не semantic. Для запросов «как мы решали похожую проблему?» нужен vector search. ADR-005 §2.3 спроектировал Qdrant collection `agent_memory` через OriaHS. В PROD реализуем:
- Qdrant collection `agent_memory` в OriaHS (1024-dim, Cosine).
- Drain-worker (B-21) уже делает embeddings и POST /index — теперь targeting эту collection.
- `memory_search` tool — гибридный retrieval из L1 SQLite (lexical) + L2 Qdrant (semantic) через MCP.

#### Goal

1. Создать Qdrant collection `agent_memory` через OriaHS API (см. ARCHITECT6 §3.3).
2. Реализовать `app/tools/memory.py::memory_search` tool:
   - `memory_search(query, types, top_k)` — hybrid retrieval.
   - L1 SQLite FTS5 — lexical, ~5 мс.
   - L2 Qdrant via MCP `oriahs.hybrid_search` — semantic, ~50 мс.
   - Merge + dedup by memory_id.
3. Tool registered в tool-registry, доступен LLM в PROD+.
4. Observability: каждый memory_search эмитит span `memory.read` (см. ARCHITECT6 §9.5).

#### Constraints

- Qdrant collection: `agent_memory`, 1024-dim (bge-m3), Cosine distance.
- Payload: `memory_id, type, project, source, created_at, confidence`.
- `on_disk_payload: true` — экономия RAM.
- LLM вызывает `memory_search` только когда нужно (system-prompt инструкция: «Use memory_search when user asks about past decisions or similar problems»).
- Hybrid merge: weighted (lexical 0.4, semantic 0.6), configurable.
- Privacy: L2 — per-project collection (filter `project=current_project`); global items помечены `project=__global__`.

#### Acceptance Criteria

- ✅ Qdrant collection `agent_memory` создана в OriaHS.
- ✅ Drain-worker (B-21) успешно POST /index в collection.
- ✅ `memory_search("how we decided on MCP", top_k=5)` — возвращает релевантные decisions.
- ✅ Hybrid merge: lexical + semantic results deduped by memory_id.
- ✅ Span `memory.read` эмитится с правильными атрибутами.
- ✅ Per-project isolation: search не возвращает items из другого project.
- ✅ Latency: lexical < 10 мс, semantic < 100 мс, total < 200 мс p95.

#### Forbidden patterns

- ❌ Использовать Qdrant напрямую (мимо OriaHS) — нарушение ADR-002.
- ❌ Cross-project items без явной пометки `global=true` — privacy violation.
- ❌ `memory_search` на каждом turn — только по необходимости (LLM-self-judge).

#### Suggested files

- `app/tools/memory.py`
- `infra/oriahs/qdrant_collections.yaml` (declare agent_memory collection)
- `tests/test_memory_search.py`

---

### P-19 — Distributed tracing через MCP + offline-eval для /learn 🆕

> **Component:** ARCHITECT6 §9.5, §9.6 | **Dependencies:** P-18 (memory_search), A-16 (SDK), A-17 (sampler-proxy) | **Estimate:** 1 день | **TRIZ:** #28 Mechanics substitution

#### Context

В PROD появляется OriaHS integration → distributed tracing через MCP boundary (см. ADR-010 §2.3). Каждый memory_search проходит через 4-5 сервисов (agent → MCPClient → oriahs-mcp → OriaHS lexical/vector/fusion/rerank). Без trace_id связать метрики нельзя.

Также нужен offline-eval для /learn — измерить, какие learned-паттерны реально переиспользуются. Это даёт feedback-loop для улучшения /learn (например, если auto-learned паттерны никогда не переиспользуются — понизить их confidence).

#### Goal

1. MCP-headers propagation (см. ADR-010 §6.2):
   - `MCPClient.callTool` автоматически инжектит `MCP-Trace-Id`, `MCP-Span-Id`, `MCP-Parent-Span-Id`.
   - OriaHS принимает эти headers и включает в свои span'ы.
2. End-to-end trace в Jaeger/Tempo:
   - `[agent.loop] → [tool.call] memory_search → [memory.read] sqlite_fts5 + [memory.read] qdrant via MCP → [oriahs-mcp] hybrid_search → [OriaHS] lexical + vector + rerank`
3. Offline-eval dataset `eval/datasets/agent_learn_quality.jsonl` (см. ARCHITECT6 §9.6.1).
4. Nightly job: для каждого learned-паттерна — посчитать `reuse_count` (сколько раз pattern_name упоминается в последующих сессиях за 30 дней).
5. Metric: `learn_reuse_rate` (target > 30% за 30 дней).
6. Grafana dashboard «OryaAgent Memory Health» (4 панели: L0/L1/L2 sizes, /learn rate, reuse rate, retrieval latency).

#### Constraints

- MCP-headers: W3C TraceContext-compatible (через `opentelemetry.propagation.inject`).
- Trace-completeness target: > 95% memory_search calls имеют full trace.
- Offline-eval: nightly cron, результаты в Prometheus pushgateway.
- `learn_reuse_rate`: доля learned-паттернов с `reuse_count >= 1` за 30 дней.
- Grafana dashboard: provisioned, не manual import.

#### Acceptance Criteria

- ✅ MCP-headers propagation работает: trace_id из OryaAgent виден в OriaHS spans.
- ✅ End-to-end trace в Jaeger показывает все 5 сервисов.
- ✅ `eval/datasets/agent_learn_quality.jsonl` создан, 20 сценариев.
- ✅ Nightly job: `learn_reuse_rate` метрика пушится в Prometheus.
- ✅ Grafana dashboard «OryaAgent Memory Health» доступен на `:3001/d/orya-memory`.
- ✅ Trace-completeness > 95% (проверить через Jaeger query).

#### Forbidden patterns

- ❌ Хардкодить trace_id — только через `propagation.inject`.
- ❌ Offline-eval на production data — synthetic datasets только.
- ❌ Manual Grafana dashboard import — provisioning only.

#### Suggested files

- `app/core/mcp_client.py` (add headers propagation)
- `eval/datasets/agent_learn_quality.jsonl`
- `eval/nightly_agent_learn_eval.py`
- `infra/grafana/dashboards/orya_memory_health.json`

---

## 6. Фаза EXTENSION-PROD (E-11 — новый в v6)

### E-11 — Multi-instance memory replication (sync через OriaHS) 🆕

> **Component:** ARCHITECT6 §17 (multi-instance replication — НЕ делаем в v6, но в EXTENSION-PROD) | **Dependencies:** P-18 (L2 Qdrant), P-06 (multi-tenant) | **Estimate:** 1 неделя | **TRIZ:** #15 Dynamicity

#### Context

В v6 default — single-machine: `~/.orya/memory/` локальная директория. В EXTENSION-PROD (multi-instance deployment) нужно синхронизировать memory между машинами. Решение: OryaHS как single-source-of-truth для L2, L0 + L1 — local caches.

#### Goal

1. L0 MD-файлы — local cache, синхронизируются с L2 OriaHS при запуске агента.
2. L1 SQLite — local cache, sync через outbox (уже в B-21).
3. Conflict resolution: L2 authoritative; при конфликте — L2 wins, L0/L1 обновляются.
4. Multi-instance: 2+ OryaAgent instances на одной БД через OriaHS.

#### Constraints

- L0 sync: pull при старте, push при записи (background).
- L1 sync: outbox-drain уже работает (B-21).
- Conflict: timestamp-based, L2 wins.
- Latency: eventual consistency (до 5 минут lag допустим).

#### Acceptance Criteria

- ✅ 2 OryaAgent instances, `/learn` на instance A — появляется в L2 → pull на instance B в течение 5 минут.
- ✅ Conflict: одновременная запись на A и B — L2 сохраняет одну (по timestamp), обе инстансы синхронизируются.
- ✅ L0 local cache: при offline OriaHS — чтение работает из L0; при online — sync.

#### Forbidden patterns

- ❌ Strong consistency — не нужно для memory.
- ❌ Synchronous sync на каждый /learn — background only.

#### Suggested files

- `app/core/memory/sync.py`
- `app/core/memory/conflict_resolver.py`

---

## 7. Фаза FUTURE (F-09 — новый в v6)

### F-09 — Continuous prompt-learning (LLM-judge per memory-write) 🆕

> **Component:** ARCHITECT6 §17 (continuous prompt-learning — НЕ делаем в v6) | **Dependencies:** PROD done, eval-metrics stable | **Estimate:** — | **TRIZ:** #35 Parameter changes

#### Context

В PROD+ у нас есть /learn и auto-learn. FUTURE — агент сам улучшает свой system-prompt на основе накопленной памяти:
- LLM-judge оценивает каждый memory-write: «достойна ли эта запись войти в system-prompt как behavior-rule?».
- Если да — добавляется в `BEHAVIOR_RULES.md` (новый L0 файл).
- Periodic review: low-value rules удаляются.

#### Goal

(определится в FUTURE)

#### Constraints

- Risk of regression — A/B-testing обязателен.
- LLM-judge cost — sampling (5% memory-writes).
- Manual override: пользователь может удалить любое rule.

#### Acceptance Criteria

(определится в FUTURE)

#### Suggested files

- `app/core/memory/prompt_learner.py` (TBD)

---

## 8. Meta-тикеты (R-05 — новый в v6)

### R-05 — Memory-architecture documentation (3-tier hybrid) 🆕

> **Component:** ARCHITECT6 §2, §3 | **Dependencies:** все memory-тикеты | **Estimate:** 4 часа | **TRIZ:** —

#### Context

В v5 B-00 (Memory cross-session via PostgresStore) — «как в v4», без конкретной стратегии. В v6 введена трёхслойная гибридная память. Нужна отдельная документация для контрибьюторов.

#### Goal

Создать `docs/MEMORY_ARCHITECTURE.md` с:
1. Объяснением, почему 3 слоя (не 1, не 2).
2. Схемой L0/L1/L2.
3. Compaction flow.
4. /learn и fast-update mechanism.
5. ADR-005 ссылка как primary source.

#### Constraints

- Документация на русском (как ARCHITECT5/6).
- Диаграммы в mermaid.
- Cross-references на ARCHITECT6 §2, §3, §4.

#### Acceptance Criteria

- ✅ `docs/MEMORY_ARCHITECTURE.md` существует.
- ✅ Cross-references на ARCHITECT6 работают.
- ✅ Examples для каждого слоя.

#### Suggested files

- `docs/MEMORY_ARCHITECTURE.md`

---

## 9. Сводная матрица тикетов × фаз

| Фаза | Кол-во тикетов v6 | Кол-во тикетов v5 | Delta | Суммарная оценка v6 |
|---|---|---|---|---|
| MVP | 28 (M-00..M-27) | 25 | +3 (MDStore, /learn, Compactor) | ~19 дней |
| ALPHA | 18 (A-00..A-17) | 16 | +2 (SDK, sampler-proxy) | ~14 дней |
| BETA | 24 (B-00..B-23, без B-00 REMOVED) | 21 | +3 (SQLiteStore, Extractor, /memory commands) — 1 (B-00 removed) | ~22 дней |
| PROD | 20 (P-00..P-19) | 18 | +2 (Qdrant L2, distributed tracing + eval) | ~19 дней |
| EXTENSION-PROD | 12 (E-00..E-11) | 11 | +1 (multi-instance replication) | ~6 недель |
| FUTURE | 10 (F-00..F-09) | 9 | +1 (continuous prompt-learning) | ~4 месяца |
| Meta | 5 (R-01..R-05) | 4 | +1 (memory docs) | ~2.5 дня |
| **Итого до PROD** | **90 + 5 meta** | **80 + 4 meta** | **+11** | **~74 дня (~15 недель)** |

---

## 10. Карта зависимостей между тикетами

```
MVP v6 (дополнение к v5):
  M-02 (settings) → M-25 (MDStore) → M-26 (/learn), M-27 (Compactor)
  M-14 (session-log) → M-26 (/learn — extracts last successful sequence)
  M-20 (FastAPI) → M-26 (/learn endpoint), M-27 (/memory endpoints)
  M-22 (injection defense) → integrated with A-17 (security.incident span)

ALPHA v6 (дополнение к v5):
  A-04 (observability baseline) → A-16 (OryaObservability SDK) → A-17 (sampler-proxy mode)
  A-13 (CostAwareRouter) → A-17 (cost.over_budget span attribute)
  A-02 (LLM seam) → A-16 (instrument LangGraph)

BETA v6 (замена B-00):
  M-25 (MDStore) + M-27 (Compactor) → B-21 (SQLiteStore L1 + outbox + drain-worker)
  B-21 → B-22 (memory-extractor LLM-worker)
  B-21 + B-22 → B-23 (/remember, /forget, /memory list/export/import)
  B-11 (memory injection в system-prompt) → updated: инжектирует L0 (4 MD-файла)

PROD v6 (дополнение к v5):
  P-00 (OriaHS bootstrap) + B-21 (outbox) → P-18 (L2 Qdrant + memory_search tool)
  A-16 (SDK) + A-17 (sampler-proxy) + P-18 → P-19 (distributed tracing + offline-eval)
  P-05 (OriaHS search) → P-18 (memory_search использует same MCP)

EXTENSION-PROD v6:
  P-18 (L2 Qdrant) + P-06 (multi-tenant) → E-11 (multi-instance replication)

FUTURE v6:
  PROD done + eval-metrics stable → F-09 (continuous prompt-learning)

META v6:
  R-05 (memory docs) — after B-21, B-22, B-23, P-18 done
```

---

## 11. Соответствие тикетов ТРИЗ-принципам и 20/80

| Принцип | Тикеты v6 | Эффект |
|---|---|---|
| #1 Segmentation | B-21 (L1 SQLite separate from L0 MD) | Разделение storage по свойствам |
| #5 Merging | (унаследовано из v5: B-18) | — |
| #10 Preliminary action | (унаследовано из v5: P-16) | — |
| #11 Beforehand cushioning | A-17 (cost.over_budget + security.incident → always-keep) | Traces с инцидентами не теряются |
| #13 Do it in reverse | (унаследовано из v5: B-19) | — |
| #15 Dynamicity | A-17 (sampler-proxy dynamic rate), P-18 (L2 hybrid), E-11 (multi-instance) | Гибкость |
| #19 Periodic action | M-27 (periodic compaction), B-22 (batch extraction) | Предсказуемость |
| #21 Rushing | M-25 (atomic-append < 1 мс) | Fast-write |
| #22 Convert harm into benefit | (унаследовано из v5: A-14) | — |
| #25 Self-service | M-26 (/learn), B-23 (/remember, /forget) | User-control без manual editing |
| #28 Mechanics substitution | A-16 (OryaObservability SDK вместо своего), B-22 (extractor LLM вместо manual), P-19 (distributed tracing вместо log-only) | Меньше своего кода |
| #35 Parameter changes | F-09 (continuous prompt-learning) | — |

### 20/80-анализ новых тикетов v6

| Тикет | Усилия | Ценность | 20/80? |
|---|---|---|---|
| M-25 (MDStore) | 4 часа | 80% (L0 — базовая память) | ✅ |
| M-26 (/learn) | 4 часа | 80% (capture pattern в 1 click) | ✅ |
| M-27 (Compactor) | 4 часа | 80% (MD не разрастается) | ✅ |
| A-16 (OryaObservability SDK) | 1 день | 80% (PII/cost/guardrail готовые) | ✅ |
| A-17 (sampler-proxy) | 6 часов | 80% (dynamic rate без рестарта) | ✅ |
| B-21 (SQLiteStore L1) | 2 дня | 80% (structured access для memory) | ✅ |
| B-22 (memory-extractor) | 1 день | 60% (auto-extraction — nice-to-have) | ✅ |
| B-23 (memory commands) | 1 день | 80% (user-control memory) | ✅ |
| P-18 (L2 Qdrant) | 1 день | 60% (semantic search — для power-users) | ✅ |
| P-19 (distributed tracing + eval) | 1 день | 70% (debuggability + feedback-loop) | ✅ |
| E-11 (multi-instance replication) | 1 неделя | 30% (только для multi-instance) | ⚠️ (перенесён в EXTENSION-PROD) |
| F-09 (continuous prompt-learning) | — | 50% (risk of regression) | ⚠️ (FUTURE) |
| R-05 (memory docs) | 4 часа | 30% (документация) | ✅ |

---

*Конец документа BACKLOG6.md*
