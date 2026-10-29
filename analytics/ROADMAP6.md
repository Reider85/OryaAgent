# ROADMAP6 — Дорожная карта OryaAgent v6 (memory + /learn + observability)

> **Версия документа:** 6.0
> **Дата:** 20 октября 2026
> **Источники:** `ARCHITECT6.md` v6.0, `ROADMAP5.md` v5.0 (baseline), `BACKLOG6.md` v6.0
> **Стек:** Python 3.11+, LangChain 0.3+, LangGraph 0.2+, FastAPI, PostgreSQL 16, Redis 7, Chainlit, OriaHS, OryaObservability SDK
> **Методология:** фазы отсортированы по 6 категориям зрелости — **MVP → ALPHA → BETA → PROD → EXTENSION-PROD → FUTURE**
> **Статус:** roadmap готов к реализации; v6 — надстройка над v5, не замена

---

## Содержание

0. Что изменилось относительно v5 (executive summary)
1. Обзор и принципы категоризации
2. Сводная карта фаз
3. Фаза MVP — минимальный рабочий контур + L0 memory
4. Фаза ALPHA — production-safe baseline + OryaObservability SDK + sampler-proxy
5. Фаза BETA — расширяемость + L1 SQLite memory + memory-commands
6. Фаза PROD — OriaHS + L2 Qdrant memory + distributed tracing
7. Фаза EXTENSION-PROD — масштабирование + multi-instance memory
8. Фаза FUTURE — автономность + continuous prompt-learning
9. Сводная матрица фаз × компонентов
10. Карта зависимостей между фазами
11. Критерии перехода между фазами (exit criteria)
12. TRIZ-gates по фазам (полная карта)
13. NFR-таргеты по фазам
14. Риски и mitigations
15. Метрики прогресса внедрения
16. UI-стратегия по фазам
17. Fast-track paths (новое в v6)
18. Rollback-процедуры между фазами
19. Triggers для EXTENSION-PROD (уточнённые в v6)
20. Deprecation mechanism (дополненный в v6)
21. Интеграция с OryaObservability — отдельный трек (новое в v6)

---

## 0. Что изменилось относительно v5 (executive summary)

`ROADMAP6.md` сохраняет 6 фаз из v5, но:

1. **Интегрирует 5 улучшений v6** (см. `ARCHITECT6.md` §0) в соответствующие фазы.
2. **Добавляет 2 новых fast-track paths:** `memory-only` (для пользователей, которым нужна только память без всего стека) и `observability-only` (для тех, кто хочет только OryaObservability integration).
3. **Уточняет triggers для EXTENSION-PROD** — добавлен memory-multi-instance trigger.
4. **Добавляет отдельный integration-трек для OryaObservability** (§21) — пошаговый план интеграции с готовым observability-стеком.
5. **Расширяет deprecation mechanism** — B-00 (Memory via PostgresStore) помечен как deprecated, заменён на B-21+B-22+B-23.

### Ключевые изменения по фазам

| Фаза | Что нового в v6 |
|---|---|
| **MVP** | + L0 MD-память (6 файлов), + `/learn` команда, + Compactor + `/memory/stats` + `/memory/compact` |
| **ALPHA** | + OryaObservability SDK integration (A-16), + sampler-proxy mode (A-17) + cost/security span attributes |
| **BETA** | + L1 SQLite FTS5 (SQLCipher) (B-21), + Memory-extractor LLM-worker (B-22), + `/remember`, `/forget`, `/memory list/export/import` (B-23); B-00 REMOVED (deprecated) |
| **PROD** | + L2 Qdrant via OriaHS (P-18), + Distributed tracing через MCP (P-19), + Offline-eval для /learn |
| **EXTENSION-PROD** | + Multi-instance memory replication (E-11), + Memory-multi-instance trigger (§19) |
| **FUTURE** | + Continuous prompt-learning (F-09) |

---

## 1. Обзор и принципы категоризации

(см. `ROADMAP5.md` §1 — без изменений, кроме §1.4)

### 1.4. Принцип ТРИЗ на уровне фаз (дополнение в v6)

Каждая фаза должна:
- **Внедрять TRIZ-gates с первого дня фазы** (не «потом»).
- **Иметь reversible-переходы** к предыдущей фазе (rollback).
- **Иметь явные triggers** для перехода к следующей фазе.
- **Иметь deprecation-plan** для фич, которые могут стать устаревшими.
- **Иметь observability с первого дня фазы** (новое в v6) — даже в MVP минимальные spans (без OryaObservability SDK, просто Langfuse через env); в ALPHA — full OryaObservability SDK.

---

## 2. Сводная карта фаз

| Фаза | Длительность | Главная цель | Что лежит в основе | Новое в v6 |
|---|---|---|---|---|
| **MVP** | 3–3.5 недели | Рабочий кодинг-агент + FastAPI + L0 MD-память + /learn | LangGraph + FastAPI + Chainlit + 5 tools + PostgresSaver + CacheWrapper + MDStore | L0 memory, /learn, Compactor |
| **ALPHA** | 2.5 недели | Production-safe + OryaObservability SDK + sampler-proxy | LangSmith → OryaObservability SDK + sampler-proxy + Auth + rate-limits + CostAwareRouter + Fuzzy | OryaObservability SDK, sampler-proxy mode |
| **BETA** | 5 недель | Расширяемость + L1 SQLite memory + memory-commands | MCP + hooks + Skills + L1 SQLiteStore + Memory-extractor + /remember + /forget + Next.js | L1 SQLiteStore, memory-extractor, memory-commands |
| **PROD** | 6 недель | OriaHS + L2 Qdrant memory + distributed tracing + eval | OriaHS + L2 Qdrant + memory_search + sandbox + A/B + SpeculativePrefetcher + StreamingPartial + distributed tracing | L2 Qdrant memory, memory_search, distributed tracing, /learn eval |
| **EXTENSION-PROD** | По triggers | Масштабирование + multi-instance memory | Semantic memory + multi-instance replication + IDE-плагины + parallel subagents | Multi-instance memory replication |
| **FUTURE** | Не ограничено | Автономность + continuous prompt-learning | Multi-agent teams + cron + goals+judge + workflows + Max Mode + voice + self-improvement + prompt-learning | Continuous prompt-learning |

**Ключевая инвариантность:** каждая следующая фаза опирается на компоненты предыдущей, но не модифицирует их контракт. L0 → L1 → L2 — additive layers, не replacement.

---

## 3. Фаза MVP — минимальный рабочий контур + L0 memory

### 3.1. Цели фазы

Доставить end-to-end работающего кодинг-агента с **нормальным UI с первого дня** + **базовой долговременной памятью в MD-файлах** + **командой /learn для capture успешных паттернов**. Пользователь открывает Chainlit-UI, пишет промпт, агент через tools читает/редактирует/выполняет, возвращает результат. Сессии сохраняются в PostgreSQL, tool-results кэшируются в Redis, read-content проверяется на prompt-injection. После успешного tool-call sequence пользователь может ввести `/learn` — паттерн сохранится в `LEARNED.md`, будет инжектироваться в system-prompt следующих сессий.

Принцип MVP v6 (vs v5): **память с первого дня**. В v5 B-00 (Memory cross-session) был отложен на BETA без конкретной стратегии. В v6 L0 MD-память — в MVP, потому что:
- 80% ценности «агент помнит» даёт L0 (4 KB всегда в system-prompt).
- 20% усилий — 4 часа на MDStore + 4 часа на /learn + 4 часа на Compactor = 1.5 дня.
- Без памяти агент каждый раз «с нуля» — это плохой UX для кодинг-агента.

### 3.2. Компоненты фазы (дополнение к v5 MVP)

#### 3.2.11. Memory Layer L0 (MDStore) 🆕

- 6 MD-файлов: `PROJECT.md` (≤ 8 KB), `LEARNED.md` (≤ 4 KB), `PREFERENCES.md` (≤ 2 KB), `FACTS.md` (≤ 2 KB), `DECISIONS.md` (≤ 2 KB), `MEMORY_INDEX.md` (≤ 8 KB, placeholder до BETA).
- Расположение: `~/.orya/memory/`.
- Atomic-append через `open(path, "a") + fsync` с per-file `threading.Lock`.
- Бюджеты 2–8 KB на файл (compaction при превышении — M-27; компактятся только 4 scored-файла).
- Чтение L0 для system-prompt injection через `MDStore` (в `build_system_prompt` инжектируются 4 scored-файла из 6; `read_all()` возвращает все 6).

#### 3.2.12. `/learn` endpoint + Chainlit slash-command 🆕

- FastAPI `POST /sessions/{thread_id}/learn` — извлекает последний успешный sequence, atomic-append в `LEARNED.md`.
- Chainlit `/learn [name] [description]` — вызывает endpoint, instant-feedback.
- Memory-audit log: `~/.orya/logs/memory_audit.jsonl`.

#### 3.2.13. Compactor + `/memory/compact`, `/memory/stats` 🆕

- `Compactor.compact_if_needed(filename)` — async, не блокирует user-turn.
- FastAPI `POST /memory/compact`, `GET /memory/stats`, `GET /memory`.
- Chainlit `/memory compact`, `/memory stats`, `/memory`.
- Periodic background-task: каждые 24 часа проверка всех 6 файлов (компактятся 4 scored-файла).

### 3.3. TRIZ-gates фазы (дополнение к v5 MVP)

| Gate | Принцип | Что встроено с первого дня |
|---|---|---|
| (все gates из v5 MVP) | — | — |
| **L0 MD-память с atomic-append** 🆕 | ТРИЗ #21 Rushing | Fast-write < 1 мс |
| **`/learn` команда** 🆕 | ТРИЗ #25 Self-service | User-control без manual editing |
| **Periodic compaction** 🆕 | ТРИЗ #19 Periodic action | MD не разрастается |
| **Memory-audit log** 🆕 | ТРИЗ #11 Beforehand cushioning | Audit-trail с первого дня |

### 3.4. Definition of Done (дополнение к v5 MVP)

- ✅ (все DoD из v5 MVP)
- ✅ `~/.orya/memory/` содержит 6 MD-файлов (создаются при первом запуске).
- ✅ System-prompt содержит секцию `# Long-term memory (L0, always loaded)` с содержимым 4 scored-файлов (из 6; `PROJECT.md` — в project-context-блоке, `MEMORY_INDEX.md` пуст).
- ✅ `/learn` в Chainlit создаёт запись в `LEARNED.md` (< 100 мс latency).
- ✅ После 20 `/learn` вызовов — compaction запускается async, архивирует старые записи.
- ✅ `/memory stats` показывает размеры и кол-ва для всех 6 файлов.
- ✅ Memory-audit log содержит entries для каждого /learn.
- ✅ Smoke-тест: `/learn` после успешного tool-call sequence → запись в LEARNED.md → видна в следующем turn'е (в system-prompt).

### 3.5. Целевые NFR фазы (дополнение к v5 MVP)

| Параметр | Целевое значение v6 | v5 было |
|---|---|---|
| Time-to-first-token (с L0 memory injection) | ≤ 1300 мс | ≤ 1200 мс |
| `/learn` latency | ≤ 100 мс p95 | — |
| Atomic-append latency | ≤ 1 мс typical | — |
| Memory-audit log entry latency | ≤ 5 мс | — |
| L0 memory size (total) | ≤ 10 KB | — |
| Token-cost per session (с memory injection) | ≤ $0.45 (vs v5 $0.40) | ≤ $0.40 |

### 3.6. Риски фазы и mitigations (дополнение к v5 MVP)

- (все риски из v5 MVP)
- **L0 memory pollution (пользователь /learn-ит мусор)** 🆕: confidence-score для explicit /learn = 0.9 (не 1.0); `/forget` доступен сразу (но в BETA — сейчас в MVP только manual edit файла).
- **Compaction удаляет нужную запись** 🆕: compaction only moves to archive (не удаляет); user может восстановить из `~/.orya/memory/archive/`.
- **Memory-audit log растёт бесконечно** 🆕: log-rotate 30 дней через `logging.handlers.TimedRotatingFileHandler`.

---

## 4. Фаза ALPHA — production-safe baseline + OryaObservability SDK + sampler-proxy

### 4.1. Цели фазы

Превратить «работающий MVP с базовой памятью» в «безопасный MVP с production-grade observability»: добавить auth, rate-limits, **OryaObservability SDK** (вместо raw LangSmith/LangFuse через env), **sampler-proxy mode** для динамической sample-rate, **cost/security span attributes** для always-keep в sampler-proxy, offline-eval, cost-aware model switching, fuzzy tool matching.

ALPHA не добавляет end-user-фич (кроме memory-related improvements), но система устойчива к деградации LLM, превышению rate-limit, регрессиям prompt-версий, **и автоматически переключается на дешёвую модель при приближении к budget** + **trace'ы с инцидентами всегда сохраняются**.

Принцип ALPHA v6 (vs v5): **observability — первый класс**. В v5 observability — «env-переменные LangSmith/LangFuse». В v6 — полноценная интеграция с OryaObservability SDK (PII-masking, cost-tracking, guardrail, eval) + sampler-proxy для dynamic rate. Это 20% усилий (1 день на SDK + 6 часов на sampler-proxy) и 80% ценности (production-grade observability без написания своего кода).

### 4.2. Компоненты фазы (дополнение к v5 ALPHA)

#### 4.2.9. OryaObservability SDK integration 🆕 (A-16)

- `pip install -e ../OryaObservability` (editable) или `pip install agent-obs` (после публикации).
- `app/core/observability.py::OryaObservability` wrapper.
- Instrument LangGraph: `agent.loop` (root), `llm.call`, `tool.call` spans.
- PII-маскирование in-process (fail-closed), через `agent_obs.guardrail`.
- Cost-tracking через `agent_obs.cost.compute_cost(usage, model, book)`.
- Price book: `price_book.yaml` (копия из OryaObservability).
- `AGENT_OBS_ENABLED=false` — all decorators no-op (для dev/test).
- `emit_memory_write(memory_id, file, source, compacted)` — start_span("memory.write").

#### 4.2.10. Sampler-proxy mode + cost/security span attributes 🆕 (A-17)

- `LANGFUSE_HOST=http://sampler-proxy:4321` (вместо `http://langfuse:3000`).
- Docker-compose сервис `sampler-proxy` (image `agent-obs-sampler:latest`).
- `CostAwareRouter` доработан: при `budget_ratio >= 0.9` emit `cost.over_budget=true` на `agent.loop` span.
- `detect_injection` доработан: при detect emit `security.incident=true` на `tool.call` span.
- Sampler-proxy always-keep: traces с `cost.over_budget=true` или `security.incident=true` — всегда сохраняются.
- Audit в ClickHouse `audit_events_hot` (через `AGENT_OBS_SAMPLER_AUDIT_ENABLED=1`).
- Health-checks: `/health/observability`, `/health/sampler-proxy`.

#### 4.2.11. Memory-метрики 🆕 (часть A-16)

- `orya_memory_md_file_size_bytes{file}` — размер каждого L0 файла.
- `orya_memory_md_entries_total{file}` — кол-во записей.
- `orya_memory_learn_total{source="/learn|auto-learn"}` — counter (auto-learn в PROD+).
- `orya_memory_compaction_total{file}` — counter.
- `orya_memory_compaction_duration_ms{file}` — histogram.

### 4.3. TRIZ-gates фазы (дополнение к v5 ALPHA)

| Gate | Принцип | Что встроено |
|---|---|---|
| (все gates из v5 ALPHA) | — | — |
| **OryaObservability SDK integration** 🆕 | ТРИЗ #28 Mechanics substitution | PII/cost/guardrail готовые |
| **Sampler-proxy mode** 🆕 | ТРИЗ #15 Dynamicity | Dynamic rate без рестарта |
| **cost.over_budget + security.incident span attributes** 🆕 | ТРИЗ #11 Beforehand cushioning | Traces с инцидентами не теряются |
| **memory.write spans** 🆕 | ТРИЗ #11 | Audit-trail для memory-ops |

### 4.4. Definition of Done (дополнение к v5 ALPHA)

- ✅ (все DoD из v5 ALPHA)
- ✅ `pip install -e ../OryaObservability` работает.
- ✅ `agent-obs` package импортируется в `app/core/observability.py`.
- ✅ LangGraph instrumentation: каждый LLM-call и tool-call создаёт span.
- ✅ Span `agent.loop` имеет `agent.id`, `agent.version`, PII-masked `task.input`.
- ✅ Span `llm.call` имеет `provider`, `model`, `tokens.in`, `tokens.out`, `cost`.
- ✅ Span `tool.call` имеет `tool.name`, PII-masked `tool.input`, PII-masked `tool.output`.
- ✅ `emit_memory_write` создаёт span `memory.write` с правильными атрибутами.
- ✅ `LANGFUSE_HOST=http://sampler-proxy:4321` в docker-compose.
- ✅ `GET http://sampler-proxy:4321/sampler/status` возвращает `{current_rate, policy_reason}`.
- ✅ При `budget_ratio >= 0.9` — span `agent.loop` имеет атрибут `cost.over_budget=true`.
- ✅ При injection-detect — span `tool.call` имеет атрибут `security.incident=true`.
- ✅ Traces с `cost.over_budget=true` — всегда сохраняются в Langfuse.
- ✅ Audit-запись появляется в ClickHouse при смене rate.
- ✅ `/health/observability` — `{sdk_enabled, exporter_connected, guardrail_ready}`.
- ✅ `/health/sampler-proxy` — ping `http://sampler-proxy:4321/sampler/status`.
- ✅ Memory-метрики экспортируются в Prometheus.

### 4.5. Целевые NFR фазы (дополнение к v5 ALPHA)

| Параметр | Целевое значение v6 | v5 было |
|---|---|---|
| Observability overhead per LLM-call | < 2 мс p99 | — |
| Observability CPU overhead | < 5% | — |
| PII-masking success rate | 100% (fail-closed) | — |
| Trace completeness (spans с trace_id) | > 95% | — |
| Sampler-proxy latency overhead | < 1 мс (1 hop localhost) | — |
| Always-keep trace rate (cost/security incidents) | 100% | — |
| Audit-trail completeness (rate changes) | 100% | — |

### 4.6. Риски фазы и mitigations (дополнение к v5 ALPHA)

- (все риски из v5 ALPHA)
- **Sampler-proxy — SPOF для traces** 🆕: health-check; fail-open (если proxy down — SDK шлёт напрямую в Langfuse через `LANGFUSE_DIRECT_URL` env-variable как fallback).
- **OryaObservability SDK добавляет overhead** 🆕: < 2 мс p99 (см. AGENTS.md); `AGENT_OBS_ENABLED=false` отключается.
- **PII в memory-audit log** 🆕: PII-masking не применяется к memory-audit (это user-action log, не span); но PII в memory-content маскируется в spans.
- **Cost-aware router race condition** 🆕: emit `cost.over_budget` до возврата model, не после.

---

## 5. Фаза BETA — расширяемость + L1 SQLite memory + memory-commands

### 5.1. Цели фазы

Превратить «безопасный MVP с L0 memory» в «расширяемую платформу с полноценной памятью + улучшенным UX». Помимо memory/MCP/hooks/skills/Next.js из v5, добавляются:
- **L1 SQLite FTS5 (SQLCipher)** — structured + lexical access к памяти (B-21).
- **Memory-extractor LLM-worker** — auto-extraction facts/decisions/todos из разговоров (B-22).
- **`/remember`, `/forget`, `/memory list/export/import`** — полный набор memory-команд (B-23).
- **Memory injection в system-prompt** обновлён: инжектирует L0 (4 scored-файла из 6), не произвольные past-summaries (B-11 updated).

Принцип BETA v6 (vs v5): **память — первый класс**. В v5 B-00 (Memory cross-session) — «как в v4 через PostgresStore», без конкретной стратегии. В v6 — трёхслойная гибридная память (L0 уже в MVP, L1 в BETA, L2 в PROD), соответствующая ADR-005.

### 5.2. Компоненты фазы (дополнение к v5 BETA)

#### 5.2.5. Memory L1: SQLiteStore (FTS5, SQLCipher) 🆕 (B-21)

- Файл: `~/.orya/memory/<project>.sqlite` (SQLCipher-encrypted, ключ в OS keychain).
- Схема: см. ARCHITECT6 §7.2 (соответствует ADR-005 §2.2).
- `memory_items`, `memory_fts`, `memory_outbox` таблицы.
- FTS5 tokenizer: `porter unicode61` (русский + английский).
- `insert`, `search`, `forget`, `supersede`, `export`, `import_` operations.
- Async через `aiosqlite`.

#### 5.2.6. MemoryOutbox + drain-worker 🆕 (часть B-21)

- Outbox-таблица в той же SQLite-БД.
- Drain-worker (background asyncio task): batch по 50, embedding через `bge-m3` (локальная), POST `/index` в OriaHS (L2 Qdrant, в PROD — P-18).
- Retry с exponential backoff при OriaHS unavailable.
- Mark done в outbox.

#### 5.2.7. Memory-extractor LLM-worker 🆕 (B-22)

- `MemoryExtractor.extract(conversation_fragment) → list[MemoryItem]` — LLM-call на haiku.
- Prompt: см. ADR-005 §6.1.
- Triggers: после каждых 10 сообщений (batch), при `/remember` без аргументов, при close session (final pass).
- Confidence: explicit user-mention → 0.95, agent-inferred high → 0.8, low → 0.5.
- Low-confidence (`< 0.7`) — `needs_review=true`, не инжектировать в L0.
- Deduplicate через FTS5 search.

#### 5.2.8. `/remember`, `/forget`, `/memory list/export/import` endpoints + UI 🆕 (B-23)

- FastAPI endpoints (см. ARCHITECT6 §8.1).
- Chainlit slash-commands.
- Next.js UI: memory-tree sidebar, «remember this» button.
- `/forget` — soft-delete (`is_deleted=1` в L1, remove из L0).
- Export: JSON `{version, exported_at, l0, l1}`.
- Import: validate, dedup, enqueue to outbox.

#### 5.2.9. Memory injection в system-prompt (updated) 🆕 (B-11 updated)

- `build_system_prompt` теперь инжектирует L0 (4 scored-файла из 6 — LEARNED/PREFERENCES/FACTS/DECISIONS через `MDStore`), не произвольные past-summaries.
- L1 items инжектируются selective (через retrieval в ContextManager), не целиком.

### 5.3. TRIZ-gates фазы (дополнение к v5 BETA)

| Gate | Принцип | Что встроено |
|---|---|---|
| (все gates из v5 BETA) | — | — |
| **L1 SQLite FTS5** 🆕 | ТРИЗ #1 Segmentation | Structured access для memory |
| **SQLCipher encryption** 🆕 | ТРИЗ #11 Beforehand cushioning | Memory at-rest encrypted |
| **Memory-extractor LLM-worker** 🆕 | ТРИЗ #28 Mechanics substitution | Auto-extraction вместо manual |
| **`/forget` soft-delete** 🆕 | ТРИЗ #13 Do it in reverse | Forget = undo для memory |
| **Memory-isolation per-user** 🆕 | ТРИЗ #11 | Multi-tenant: user не видит чужую memory |
| **Memory-outbox** 🆕 | ТРИЗ #19 Periodic action | Async sync L1 → L2 |

### 5.4. Definition of Done (дополнение к v5 BETA)

- ✅ (все DoD из v5 BETA)
- ✅ `~/.orya/memory/<project>.sqlite` создаётся (SQLCipher-encrypted).
- ✅ `insert(MemoryItem(type="fact", content="..."))` — записывает в `memory_items` + `memory_fts`.
- ✅ `search("memory", types=["fact"], top_k=5)` — возвращает релевантные записи.
- ✅ `forget("memory")` — soft-delete, возвращает count.
- ✅ SQLCipher: `.sqlite` файл не читается без ключа.
- ✅ Outbox: insert → enqueue, drain-worker → embedding + POST /index (mock OriaHS).
- ✅ Drain-worker retry: OriaHS down → retry с backoff.
- ✅ Memory-extractor: после 10 сообщений — async extraction запускается.
- ✅ Extractor cost: < $0.02 за extraction.
- ✅ `/remember "Project uses PostgreSQL 16"` — добавляет в L0 FACTS.md + L1.
- ✅ `/forget "*TS*"` — soft-delete matching L1 items, remove from L0.
- ✅ `/memory list fact` — возвращает L0 FACTS.md content + L1 fact items.
- ✅ `/memory export` → `/memory import` round-trip сохраняет данные.
- ✅ Next.js: memory-tree sidebar показывает 4 L0 files + L1 counts per type.

### 5.5. Целевые NFR фазы (дополнение к v5 BETA)

| Параметр | Целевое значение v6 | v5 было |
|---|---|---|
| Memory-search latency (L1 FTS5) | ≤ 10 мс p95 | ≤ 200 мс (v5 PostgresStore) |
| Memory-write latency (L1 SQLite) | ≤ 10 мс p95 | — |
| Memory-extraction cost per session | ≤ $0.02 | — |
| Memory-extraction success rate | > 95% | — |
| Outbox-drain lag | ≤ 5 минут | — |
| SQLCipher encryption overhead | < 5% | — |
| Memory-isolation test (OWASP) | pass | — |

### 5.6. Риски фазы и mitigations (дополнение к v5 BETA)

- (все риски из v5 BETA)
- **L0 ↔ L1 diverge (compaction не успела)** 🆕: read-path проверяет оба; L0 — authoritative для bootstrap, L1 — для search.
- **L1 ↔ L2 diverge (outbox lag)** 🆕: outbox-drain с retry; reconciler-джоб раз в час (в PROD — P-19).
- **Memory-extractor hallucinates facts** 🆕: confidence + user review для low-confidence; `needs_review=true`.
- **SQLCipher key lost** 🆕: key backup в OS keychain + recovery-phrase; warn user при первом setup.
- **Cross-project memory leak** 🆕: strict project-scoping, audit log; per-project SQLite files.
- **Memory-pollution (extractor генерирует шум)** 🆕: periodic cleanup (старше 90 дней с low-confidence → archive).

---

## 6. Фаза PROD — OriaHS + L2 Qdrant memory + distributed tracing

### 6.1. Цели фазы

Доставить production-ready систему с full-stack memory (L0+L1+L2), distributed tracing через MCP, offline-eval для /learn, speculative pre-fetching, streaming partial results, multi-tenant, sandbox, A/B.

Принцип PROD v6 (vs v5): **L2 Qdrant memory + distributed tracing**. В v5 PROD — OriaHS integration только для codebase-indexing. В v6 — OriaHS также для memory-collection `agent_memory` (semantic search). Это закрывает 3-layer memory architecture и даёт distributed tracing для debuggability.

### 6.2. Компоненты фазы (дополнение к v5 PROD)

#### 6.2.11. L2 Qdrant via OriaHS (memory collection) 🆕 (P-18)

- Qdrant collection `agent_memory` в OriaHS (1024-dim bge-m3, Cosine).
- Payload: `memory_id, type, project, source, created_at, confidence`.
- Drain-worker (B-21) уже делает embeddings и POST /index — теперь targeting эту collection.
- `memory_search` tool — hybrid retrieval (L1 lexical + L2 semantic) через MCP.
- `on_disk_payload: true` — экономия RAM.

#### 6.2.12. memory_search tool 🆕 (часть P-18)

- `@tool async def memory_search(query, types, top_k) -> str` — гибридный retrieval.
- L1 SQLite FTS5 — lexical, ~5 мс.
- L2 Qdrant via MCP `oriahs.hybrid_search` — semantic, ~50 мс.
- Merge + dedup by memory_id, weighted (lexical 0.4, semantic 0.6).
- Privacy: per-project collection; global items помечены `project=__global__`.

#### 6.2.13. Distributed tracing через MCP 🆕 (P-19)

- MCP-headers propagation: `MCPClient.callTool` инжектит `MCP-Trace-Id`, `MCP-Span-Id`, `MCP-Parent-Span-Id`.
- End-to-end trace в Jaeger/Tempo: agent.loop → tool.call → memory.read (sqlite + qdrant via MCP) → oriahs-mcp → OriaHS (lexical + vector + rerank).
- Trace-completeness target: > 95% memory_search calls имеют full trace.

#### 6.2.14. Offline-eval для /learn 🆕 (часть P-19)

- `eval/datasets/agent_learn_quality.jsonl` — 20 сценариев.
- Nightly job: для каждого learned-паттерна — посчитать `reuse_count` (сколько раз pattern_name упоминается в последующих сессиях за 30 дней).
- Metric: `learn_reuse_rate` (target > 30% за 30 дней).
- Grafana dashboard «OryaAgent Memory Health» (4 панели: L0/L1/L2 sizes, /learn rate, reuse rate, retrieval latency).

### 6.3. TRIZ-gates фазы (дополнение к v5 PROD)

| Gate | Принцип | Что встроено |
|---|---|---|
| (все gates из v5 PROD) | — | — |
| **L2 Qdrant memory** 🆕 | ТРИЗ #15 Dynamicity | Semantic search для memory |
| **memory_search tool** 🆕 | ТРИЗ #5 Merging | L1 + L2 hybrid в одном tool |
| **Distributed tracing через MCP** 🆕 | ТРИЗ #28 Mechanics substitution | W3C TraceContext headers |
| **Offline-eval для /learn** 🆕 | ТРИЗ #19 Periodic action | Nightly feedback-loop |
| **AutoLearnEvaluator (PROD+)** 🆕 | ТРИЗ #25 Self-service | LLM-mini judges worthiness |

### 6.4. Definition of Done (дополнение к v5 PROD)

- ✅ (все DoD из v5 PROD)
- ✅ Qdrant collection `agent_memory` создана в OriaHS.
- ✅ Drain-worker (B-21) успешно POST /index в collection.
- ✅ `memory_search("how we decided on MCP", top_k=5)` — возвращает релевантные decisions.
- ✅ Hybrid merge: lexical + semantic results deduped by memory_id.
- ✅ Span `memory.read` эмитится с правильными атрибутами.
- ✅ Per-project isolation: search не возвращает items из другого project.
- ✅ Latency: lexical < 10 мс, semantic < 100 мс, total < 200 мс p95.
- ✅ MCP-headers propagation работает: trace_id из OryaAgent виден в OriaHS spans.
- ✅ End-to-end trace в Jaeger показывает все 5 сервисов.
- ✅ `eval/datasets/agent_learn_quality.jsonl` создан, 20 сценариев.
- ✅ Nightly job: `learn_reuse_rate` метрика пушится в Prometheus.
- ✅ Grafana dashboard «OryaAgent Memory Health» доступен на `:3001/d/orya-memory`.
- ✅ Trace-completeness > 95%.

### 6.5. Целевые NFR фазы (дополнение к v5 PROD)

| Параметр | Целевое значение v6 | v5 было |
|---|---|---|
| Memory-retrieval latency (hybrid L1+L2) | ≤ 200 мс p95 | — |
| Memory-search recall@10 (offline-eval) | > 0.85 | — |
| learn_reuse_rate (30-day) | > 30% | — |
| Trace-completeness | > 95% | — |
| Distributed-trace overhead | < 5% | — |

### 6.6. Риски фазы и mitigations (дополнение к v5 PROD)

- (все риски из v5 PROD)
- **L1 ↔ L2 diverge (outbox lag in PROD)** 🆕: reconciler-джоб раз в час проверяет консистентность; alert если lag > 30 минут.
- **memory_search возвращает irrelevant** 🆕: reranker (bge-reranker) в OriaHS уже есть; fallback на lexical-only при circuit-breaker-open.
- **learn_reuse_rate low (auto-learn генерирует шум)** 🆕: понизить confidence auto-learned; user review для low-confidence.
- **Trace-context loss на MCP boundary** 🆕: W3C TraceContext headers; test trace-completeness nightly.

---

## 7. Фаза EXTENSION-PROD — масштабирование + multi-instance memory

### 7.1. Цели фазы (дополнение к v5 EXTENSION-PROD)

(см. v5 §7.1 + новые)

В v6 EXTENSION-PROD добавляет **multi-instance memory replication** (E-11): несколько OryaAgent instances синхронизируют memory через OriaHS как single-source-of-truth для L2. L0 + L1 — local caches.

### 7.2. Компоненты фазы (дополнение к v5 EXTENSION-PROD)

#### 7.2.1. Multi-instance memory replication 🆕 (E-11)

- L0 MD-файлы — local cache, pull при старте, push при записи (background).
- L1 SQLite — local cache, sync через outbox (уже в B-21).
- Conflict resolution: L2 authoritative; timestamp-based, L2 wins.
- Multi-instance: 2+ OryaAgent instances на одной БД через OriaHS.
- Latency: eventual consistency (до 5 минут lag допустим).

### 7.3. Triggers для EXTENSION-PROD (дополнение к v5 §19)

(см. §19 этой документа — добавлен memory-multi-instance trigger)

---

## 8. Фаза FUTURE — автономность + continuous prompt-learning

### 8.1. Цели фазы (дополнение к v5 FUTURE)

(см. v5 §8.1 + новые)

В v6 FUTURE добавляет **continuous prompt-learning** (F-09): агент сам улучшает свой system-prompt на основе накопленной памяти. LLM-judge оценивает каждый memory-write; достойные записи добавляются в `BEHAVIOR_RULES.md` (новый L0 файл). Periodic review удаляет low-value rules.

### 8.2. Компоненты фазы (дополнение к v5 FUTURE)

#### 8.2.1. Continuous prompt-learning 🆕 (F-09)

- LLM-judge per memory-write (sampling 5%).
- `BEHAVIOR_RULES.md` — новый L0 файл для behavior-rules.
- Periodic review (weekly): low-value rules удаляются.
- A/B-testing обязателен (new rules → 10% traffic → measure).
- Manual override: пользователь может удалить любое rule.

---

## 9. Сводная матрица фаз × компонентов (v6)

| Компонент | MVP | ALPHA | BETA | PROD | EXT-PROD | FUTURE |
|---|---|---|---|---|---|---|
| **Memory L0 (MD)** | ✅ /learn, /memory/stats | — | (доработка) | — | — | BEHAVIOR_RULES.md |
| **Memory L1 (SQLite)** | — | — | ✅ FTS5, SQLCipher | — | — | — |
| **Memory L2 (Qdrant)** | — | — | — | ✅ via OriaHS | multi-instance | — |
| **Memory-extractor** | — | — | ✅ LLM-worker | — | — | continuous |
| **Memory-commands** | /learn, /memory/stats/compact | — | /remember, /forget, /memory list/export/import | memory_search tool | — | — |
| **OryaObservability** | (basic Langfuse env) | ✅ SDK + sampler-proxy | — | distributed tracing | — | — |
| **Sampler-proxy** | — | ✅ mode=proxy | — | — | — | — |
| **OriaHS** | — | — | — | ✅ L2 + memory_search | multi-instance | — |
| **FastAPI** | ✅ /sessions, /messages, /learn | — | /remember, /forget, /memory/* | — | — | — |
| **CacheWrapper** | ✅ | — | — | — | — | — |
| **CostAwareRouter** | — | ✅ + cost.over_budget | — | — | — | — |
| **Fuzzy matching** | — | ✅ | — | — | — | — |
| **Periodic compaction** | ✅ L0 | — | ✅ L0 → L1 | — | — | — |
| **Branching** | — | — | ✅ | — | — | — |
| **Composite tools** | — | — | ✅ | — | — | — |
| **Undo/rewind** | — | — | ✅ | — | — | — |
| **Speculative pre-fetcher** | — | — | — | ✅ | — | — |
| **Streaming partial** | — | — | — | ✅ | — | — |
| **Auto-learn (LLM-judge)** | — | — | — | ✅ | — | continuous |
| **Next.js UI** | — | — | ✅ + memory-tree | ✅ + memory-search panel | — | — |
| **Offline-eval** | — | — | — | ✅ /learn eval | — | — |
| **Multi-instance replication** | — | — | — | — | ✅ memory | — |
| **Continuous prompt-learning** | — | — | — | — | — | ✅ |

---

## 10. Карта зависимостей между фазами

```
MVP v6 (1.5 недели дополнительно к v5 MVP):
  v5 MVP done → M-25 (MDStore) → M-26 (/learn), M-27 (Compactor)

ALPHA v6 (1.5 недели дополнительно к v5 ALPHA):
  v5 ALPHA done → A-16 (OryaObservability SDK) → A-17 (sampler-proxy mode)
  M-22 (injection defense) + A-13 (CostAwareRouter) → A-17 (cost/security span attributes)

BETA v6 (1 неделя дополнительно к v5 BETA):
  v5 BETA done + M-25 (MDStore) → B-21 (SQLiteStore L1 + outbox)
  B-21 → B-22 (memory-extractor), B-23 (memory commands)
  B-11 (memory injection) updated: инжектирует L0 (4 scored-файла из 6)
  B-00 (Memory via PostgresStore) — REMOVED, deprecated

PROD v6 (1 неделя дополнительно к v5 PROD):
  v5 PROD done + B-21 (outbox) → P-18 (L2 Qdrant + memory_search)
  A-16 + A-17 + P-18 → P-19 (distributed tracing + offline-eval)
  P-05 (OriaHS search) → P-18 (memory_search использует same MCP)

EXTENSION-PROD v6 (1 неделя дополнительно к v5 EXTENSION-PROD):
  v5 EXTENSION-PROD done + P-18 (L2 Qdrant) + P-06 (multi-tenant) → E-11 (multi-instance replication)

FUTURE v6 (не ограничено):
  PROD done + eval-metrics stable → F-09 (continuous prompt-learning)
```

---

## 11. Критерии перехода между фазами (exit criteria, дополнение к v5)

### 11.1. MVP → ALPHA (дополнение к v5)

- ✅ (все exit-criteria из v5 MVP → ALPHA)
- ✅ L0 MD-память работает: 6 файлов, atomic-append, /learn, /memory/stats.
- ✅ Memory-audit log пишется.
- ✅ Periodic compaction запускается раз в 24 часа.
- ✅ Smoke-тест: /learn после успешного tool-call sequence → запись в LEARNED.md → видна в следующем turn'е.

### 11.2. ALPHA → BETA (дополнение к v5)

- ✅ (все exit-criteria из v5 ALPHA → BETA)
- ✅ OryaObservability SDK интегрирован: spans уходят в Langfuse через sampler-proxy.
- ✅ PII-masking: 100% (fail-closed).
- ✅ cost.over_budget + security.incident span attributes работают.
- ✅ Always-keep traces сохраняются (verified через Langfuse query).
- ✅ Memory-метрики экспортируются в Prometheus.
- ✅ `/health/observability` и `/health/sampler-proxy` работают.

### 11.3. BETA → PROD (дополнение к v5)

- ✅ (все exit-criteria из v5 BETA → PROD)
- ✅ L1 SQLiteStore работает: insert, search, forget, supersede, export, import.
- ✅ SQLCipher encryption: файл не читается без ключа.
- ✅ Outbox-drain-worker работает с retry.
- ✅ Memory-extractor: после 10 сообщений — async extraction.
- ✅ /remember, /forget, /memory list/export/import работают end-to-end.
- ✅ Next.js: memory-tree sidebar показывает L0 + L1 counts.
- ✅ Memory-isolation per-user: OWASP-аудит pass.

### 11.4. PROD → EXTENSION-PROD (дополнение к v5)

- ✅ (все exit-criteria из v5 PROD → EXTENSION-PROD)
- ✅ L2 Qdrant memory collection создана в OriaHS.
- ✅ memory_search tool работает: hybrid retrieval (L1 + L2).
- ✅ Distributed tracing через MCP: end-to-end trace в Jaeger.
- ✅ Offline-eval для /learn: `learn_reuse_rate` метрика пушится в Prometheus.
- ✅ Grafana dashboard «OryaAgent Memory Health» доступен.
- ✅ Trace-completeness > 95%.

### 11.5. EXTENSION-PROD → FUTURE (без изменений от v5)

(см. v5 §11.5)

---

## 12. TRIZ-gates по фазам (полная карта v6)

| Gate | MVP | ALPHA | BETA | PROD | EXT-PROD | FUTURE |
|---|---|---|---|---|---|---|
| (все gates из v5 §12) | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| **L0 MD-память с atomic-append** | ✅ | — | — | — | — | — |
| **`/learn` команда** | ✅ | — | — | — | — | — |
| **Periodic compaction (L0)** | ✅ | — | ✅ (L0→L1) | — | — | — |
| **Memory-audit log** | ✅ | — | — | — | — | — |
| **OryaObservability SDK** | — | ✅ | — | — | — | — |
| **Sampler-proxy mode** | — | ✅ | — | — | — | — |
| **cost.over_budget + security.incident span attrs** | — | ✅ | — | — | — | — |
| **memory.write spans** | — | ✅ | — | — | — | — |
| **L1 SQLite FTS5 + SQLCipher** | — | — | ✅ | — | — | — |
| **Memory-outbox + drain-worker** | — | — | ✅ | — | — | — |
| **Memory-extractor LLM-worker** | — | — | ✅ | — | — | — |
| **`/remember`, `/forget`, `/memory list/export/import`** | — | — | ✅ | — | — | — |
| **Memory-isolation per-user** | — | — | ✅ | — | — | — |
| **L2 Qdrant memory collection** | — | — | — | ✅ | — | — |
| **memory_search tool (hybrid)** | — | — | — | ✅ | — | — |
| **Distributed tracing через MCP** | — | — | — | ✅ | — | — |
| **Offline-eval для /learn** | — | — | — | ✅ | — | — |
| **AutoLearnEvaluator** | — | — | — | ✅ | — | — |
| **Multi-instance memory replication** | — | — | — | — | ✅ | — |
| **Continuous prompt-learning** | — | — | — | — | — | ✅ |

---

## 13. NFR-таргеты по фазам (v6)

| NFR | MVP | ALPHA | BETA | PROD | EXT-PROD | FUTURE |
|---|---|---|---|---|---|---|
| Time-to-first-token | ≤ 1300 мс | ≤ 1200 мс | ≤ 1200 мс | ≤ 1000 мс | ≤ 1000 мс | ≤ 800 мс |
| `/learn` latency | ≤ 100 мс p95 | ≤ 100 мс p95 | ≤ 100 мс p95 | ≤ 100 мс p95 | ≤ 100 мс p95 | — |
| Memory-write latency (L0) | ≤ 1 мс | ≤ 1 мс | ≤ 1 мс | ≤ 1 мс | ≤ 1 мс | — |
| Memory-search latency (L1) | — | — | ≤ 10 мс p95 | ≤ 10 мс p95 | ≤ 10 мс p95 | — |
| Memory-retrieval latency (hybrid L1+L2) | — | — | — | ≤ 200 мс p95 | ≤ 200 мс p95 | — |
| Observability overhead per LLM-call | — | < 2 мс p99 | < 2 мс p99 | < 2 мс p99 | < 2 мс p99 | < 2 мс p99 |
| PII-masking success rate | — | 100% (fail-closed) | 100% | 100% | 100% | 100% |
| Trace completeness | — | > 90% | > 90% | > 95% | > 95% | > 95% |
| Always-keep trace rate (incidents) | — | 100% | 100% | 100% | 100% | 100% |
| Memory-extraction cost per session | — | — | ≤ $0.02 | ≤ $0.02 | ≤ $0.02 | — |
| learn_reuse_rate (30-day) | — | — | — | > 30% | > 30% | > 50% |
| Memory-search recall@10 (offline-eval) | — | — | — | > 0.85 | > 0.85 | > 0.90 |
| Multi-instance memory sync lag | — | — | — | — | ≤ 5 минут | ≤ 1 минута |

---

## 14. Риски и mitigations (дополнение к v5)

(см. v5 §14 + новые риски v6)

### 14.1. Новые риски v6 (по фазам)

| Риск | Фаза | Mitigation |
|---|---|---|
| L0 memory pollution (/learn мусор) | MVP | confidence=0.9 для explicit; `/forget` в BETA; manual edit файла |
| Compaction удаляет нужную запись | MVP | archive обязательный; user может восстановить |
| Sampler-proxy — SPOF для traces | ALPHA | fail-open (LANGFUSE_DIRECT_URL fallback); health-check |
| OryaObservability SDK overhead | ALPHA | < 2 мс p99; `AGENT_OBS_ENABLED=false` отключается |
| L0 ↔ L1 diverge | BETA | read-path проверяет оба; L0 — authoritative для bootstrap |
| L1 ↔ L2 diverge (outbox lag) | BETA/PROD | outbox-drain с retry; reconciler-jоб раз в час (PROD) |
| SQLCipher key lost | BETA | keychain + recovery-phrase; warn user при setup |
| Memory-extractor hallucinates | BETA | confidence + needs_review; user review для low-confidence |
| Cross-project memory leak | BETA/PROD | strict project-scoping; per-project SQLite; audit log |
| memory_search возвращает irrelevant | PROD | reranker (bge-reranker); fallback на lexical-only |
| learn_reuse_rate low | PROD | понизить confidence auto-learned; user review |
| Trace-context loss на MCP boundary | PROD | W3C TraceContext headers; nightly trace-completeness test |
| Multi-instance memory conflict | EXT-PROD | L2 authoritative; timestamp-based, L2 wins |
| Continuous prompt-learning regression | FUTURE | A/B-testing; manual override; periodic review |

---

## 15. Метрики прогресса внедрения (дополнение к v5)

### 15.1. Новые метрики v6

| Метрика | MVP | ALPHA | BETA | PROD |
|---|---|---|---|---|
| L0 memory size (total) | ≤ 10 KB | ≤ 10 KB | ≤ 10 KB (с compaction) | ≤ 10 KB |
| L0 entries count | ≤ 30 | ≤ 30 | ≤ 30 | ≤ 30 |
| /learn rate per session | tracked | tracked | tracked | tracked |
| Memory-write span count | — | tracked | tracked | tracked |
| PII-masking rate | — | tracked | tracked | tracked |
| Sampler-proxy rate changes | — | tracked | tracked | tracked |
| Always-keep trace count | — | tracked | tracked | tracked |
| L1 items count (per project) | — | — | tracked | tracked |
| Memory-extraction success rate | — | — | > 95% | > 95% |
| Outbox-drain lag | — | — | ≤ 5 min | ≤ 1 min |
| L2 items count (per project) | — | — | — | tracked |
| memory_search call rate | — | — | — | tracked |
| learn_reuse_rate (30-day) | — | — | — | > 30% |
| Trace-completeness | — | > 90% | > 90% | > 95% |

---

## 16. UI-стратегия по фазам (дополнение к v5)

(см. v5 §16 + новые)

### 16.1. Изменения v6

| Фаза | Что нового в UI |
|---|---|
| MVP | Chainlit: `/learn` slash-command с instant-feedback; `/memory` slash-command показывает L0 |
| ALPHA | (без UI-изменений; observability метрики видны в Grafana) |
| BETA | Next.js: sidebar с memory-tree (L0 files + L1 search), «remember this» button, compaction-indicator |
| PROD | Next.js: memory-search panel с hybrid results (L0 + L1 + L2), memory-timeline, drift-indicator |
| EXTENSION-PROD | Next.js: multi-instance sync indicator |
| FUTURE | Next.js: BEHAVIOR_RULES.md editor, A/B-test results |

---

## 17. Fast-track paths (новое в v6)

### 17.1. Fast-track paths из v5 (сохраняются)

(см. v5 §17.1–17.5 — все fast-track paths остаются в силе)

### 17.2. Новый fast-track: memory-only 🆕

Для пользователей, которым нужен кодинг-агент с памятью, но не нужен full ALPHA→PROD path.

```
MVP (с L0 memory) → BETA (с L1 SQLite memory) → stop
```

- ❌ No OryaObservability SDK (используется basic Langfuse env).
- ❌ No sampler-proxy.
- ❌ No OriaHS (L2 Qdrant не подключается).
- ❌ No multi-tenant, no A/B.
- ✅ L0 + L1 memory работает.
- ✅ /learn, /remember, /forget работают.
- ✅ Memory-extractor работает.

**Use-case:** single-user code-агент на локальной машине, нужна память между сессиями.

### 17.3. Новый fast-track: observability-only 🆕

Для пользователей, которым нужен кодинг-агент с production-grade observability, но не нужна memory.

```
MVP → ALPHA (с OryaObservability SDK + sampler-proxy) → stop
```

- ❌ No L1/L2 memory (только L0 MD-файлы для /learn).
- ❌ No OriaHS.
- ✅ OryaObservability SDK: PII-masking, cost-tracking, guardrail.
- ✅ Sampler-proxy mode.
- ✅ Always-keep traces для cost/security incidents.

**Use-case:** internal-tool в компании с strict compliance-требованиями.

### 17.4. Матрица fast-track paths v6

| Fast-track | Фазы | Включено | Исключено |
|---|---|---|---|
| (v5 fast-tracks) | см. v5 §17 | — | — |
| **memory-only** | MVP + BETA | L0 + L1 memory, /learn, /remember, /forget | OryaObservability SDK, sampler-proxy, OriaHS L2 |
| **observability-only** | MVP + ALPHA | OryaObservability SDK, sampler-proxy, always-keep | L1/L2 memory, OriaHS |

---

## 18. Rollback-процедуры между фазами (дополнение к v5)

(см. v5 §18 + новые)

### 18.1. Rollback ALPHA → MVP (дополнение)

- Отключить OryaObservability SDK: `AGENT_OBS_ENABLED=false`.
- Переключить `LANGFUSE_HOST` обратно на `http://langfuse:3000` (мимо sampler-proxy).
- Остановить docker-compose сервис `sampler-proxy`.
- L0 memory работает без изменений.

### 18.2. Rollback BETA → ALPHA (дополнение)

- Отключить L1 SQLiteStore: `ORYA_MEMORY_L1_ENABLED=false`.
- Memory-команды (/remember, /forget, /memory list) — fallback на L0 only.
- Memory-extractor: отключить через `ORYA_MEMORY_EXTRACTOR_ENABLED=false`.
- L0 + /learn работают без изменений.

### 18.3. Rollback PROD → BETA (дополнение)

- Отключить L2 Qdrant: `ORYA_MEMORY_L2_ENABLED=false`.
- `memory_search` tool — fallback на L1 only.
- Distributed tracing: отключить MCP-headers propagation.
- L0 + L1 + /learn + /remember + /forget работают без изменений.

### 18.4. Rollback EXTENSION-PROD → PROD (дополнение)

- Отключить multi-instance replication: `ORYA_MEMORY_MULTI_INSTANCE=false`.
- L0 + L1 + L2 работают как local-only.

---

## 19. Triggers для EXTENSION-PROD (уточнённые в v6)

(см. v5 §19 + новый trigger)

### 19.1. Новый trigger: memory-multi-instance 🆕

| Trigger | Порог | Метрика |
|---|---|---|
| Multi-instance memory replication | 2+ OryaAgent instances на одной БД | deployment-metric |

Если deployment растёт до 2+ instances — single-machine memory становится недостаточным (каждая машина имеет свою L0/L1). Включается E-11 (multi-instance replication) — L2 OriaHS как single-source-of-truth.

### 19.2. Полный список triggers v6

(см. v5 §19 + memory-multi-instance trigger выше)

---

## 20. Deprecation mechanism (дополненный в v6)

(см. v5 §20 + новые)

### 20.1. Deprecated в v6

| Фича | Когда deprecated | Замена | Удаление в |
|---|---|---|---|
| **B-00 (Memory cross-session via PostgresStore)** | v6 | B-21 (SQLiteStore L1) + B-22 (extractor) + B-23 (commands) | v7 (полное удаление из backlog) |

### 20.2. Deprecation process для B-00

1. v6: B-00 помечен REMOVED в BACKLOG6.md.
2. Если v5 уже реализовал B-00 (PostgresStore-based memory) — migration-script в B-21:
   - `scripts/migrate_postgres_to_sqlite.py` — перенос данных из PostgresStore в SQLiteStore.
   - Запускается один раз при переходе v5 → v6.
3. v7: B-00 удаляется из backlog, PostgresStore-based memory больше не поддерживается.

---

## 21. Интеграция с OryaObservability — отдельный трек (новое в v6)

### 21.1. Зачем отдельный трек

Интеграция с OryaObservability — cross-cutting concern, затрагивающий несколько фаз (ALPHA — SDK, PROD — distributed tracing). Чтобы не размазывать план по фазам, ниже — отдельный трек интеграции.

### 21.2. Этапы интеграции

| Этап | Фаза | Что делаем | Зависимости от OryaObservability |
|---|---|---|---|
| **0. Audit готовности OryaObservability** | pre-ALPHA | Проверить, что `agent_obs` package собирается, tests проходят, sampler-proxy запускается | `pip install -e ../OryaObservability`, `pytest ../OryaObservability/tests/` |
| **1. Basic SDK integration** | ALPHA (A-16) | `app/core/observability.py::OryaObservability` wrapper, instrument LangGraph | `agent_obs.ObservabilitySDK`, `agent_obs.guardrail`, `agent_obs.cost` |
| **2. Sampler-proxy mode** | ALPHA (A-17) | `LANGFUSE_HOST=http://sampler-proxy:4321`, docker-compose сервис | `scripts/sampler/sampler_proxy.py`, `scripts/sampler/PolicyEngine` |
| **3. Cost/security span attributes** | ALPHA (A-17) | `cost.over_budget=true`, `security.incident=true` — для always-keep в sampler-proxy | `is_interesting_span()` в sampler_proxy.py — проверяет эти атрибуты |
| **4. Memory.write spans** | ALPHA (A-16) | `emit_memory_write()` для /learn, /remember, auto-learn | Span-type `memory.write` уже определён в OryaObservability ARCHITECT.md §2.3 |
| **5. Distributed tracing через MCP** | PROD (P-19) | `MCPClient.callTool` инжектит `MCP-Trace-Id` etc. | W3C TraceContext, OriaHS MCP-headers support |
| **6. Offline-eval для /learn** | PROD (P-19) | `eval/datasets/agent_learn_quality.jsonl`, nightly job | OryaObservability `agent_obs.eval` framework |
| **7. Grafana dashboard «OryaAgent Memory Health»** | PROD (P-19) | Provisioned dashboard | OryaObservability `infra/grafana/provisioning/` |

### 21.3. Что нужно от OryaObservability

| Компонент | Статус в OryaObservability | Что OryaAgent использует |
|---|---|---|
| `agent_obs.ObservabilitySDK` | ✅ Ready | Wrapper в `app/core/observability.py` |
| `agent_obs.guardrail` (PII + injection) | ✅ Ready | PII-masking в spans; injection → `security.incident` span attr |
| `agent_obs.cost` (price_book, compute_cost) | ✅ Ready | Cost-tracking per `llm.call` span |
| `agent_obs.exporters.LangfuseExporter` | ✅ Ready | Default exporter (через sampler-proxy) |
| `scripts/sampler/sampler_proxy.py` | ✅ Ready (PC30-32) | Dynamic rate without restart; always-keep for incidents |
| `scripts/sampler/policy_engine.py` | ✅ Ready | Reads `agent_obs_system_cpu_ratio`, `agent_obs_agent_error_rate_5m` from Prometheus |
| `agent_obs.eval` (rule-based, LLM-judge, embedding) | ✅ Ready | Offline-eval для /learn (nightly job) |
| `agent_obs.drift` (KL-divergence, embedding-drift) | ✅ Ready | Memory-drift detection (опционально, FUTURE) |
| `agent_obs.compliance` (GDPR export) | ✅ Ready | `/memory export` endpoint совместим |
| `infra/grafana/provisioning/` | ✅ Ready | New dashboard «OryaAgent Memory Health» |
| `infra/docker-compose.yml` | ✅ Ready | sampler-proxy, langfuse, clickhouse, vault services |
| LangGraph instrumentation wrapper | ⚠️ TODO in OryaObservability | A-16: написать wrapper в OryaAgent (или контрибьютить в OryaObservability) |
| MCP-headers support в OriaHS | ⚠️ TODO in OriaHS | P-19: добавить в OriaHS MCP-server |

### 21.4. Что особенно хорошо стыкуется

1. **Sampler-proxy `ALWAYS_KEEP_ATTRIBUTES = ("cost.over_budget", "security.incident")`** — идеально совпадает с v5 CostAwareRouter (v5 #5) и prompt-injection detector (v5 #3). Нужно только emit эти атрибуты (A-17).

2. **`agent_obs.guardrail.engine.GuardrailEngine`** — уже имеет PII-детекторы (email, phone, INN, passport, payment) и injection-classifier (deepset/deberta-v3-base). Можно переиспользовать для v5 #3 (Prompt injection defense) — вместо своего regex-based детектора.

3. **`agent_obs.cost.price_book.PriceBook` + `compute_cost()`** — готовый cost-tracker. Можно использовать в CostAwareRouter (v5 #5) для точного budget-tracking.

4. **`agent_obs.compliance.catalog.ComplianceCatalog`** — side-product от PII-masking. Даст compliance-каталог «бесплатно» для OryaAgent (GDPR-export готов).

5. **`scripts/sampler/sampler_proxy.py` audit-trail в ClickHouse `audit_events_hot`** — даёт debuggability для memory-write operations. Можно query: «когда /learn вызывался в этом проекте за последний месяц?».

6. **Phoenix annotations (PC31)** — timeline correlation между sampler rate changes и dropped spans. Если `cpu_high` держался 30 минут → alert, и можно посмотреть какие /learn пропали.

7. **Span-type `memory.read` / `memory.write`** уже определён в OryaObservability `analytics/ARCHITECT.md` §2.3 — не нужно добавлять новый span-type, просто использовать.

### 21.5. Что нужно доработать в OryaObservability (контрибьюции)

| Доработка | Где | Приоритет |
|---|---|---|
| LangGraph instrumentation wrapper | `agent_obs/instrumentation/langgraph.py` (new) | high (для A-16) |
| MCP-headers support в OriaHS MCP-server | `oriahs/mcp/server.py` | medium (для P-19) |
| `memory.write` span-type в span-context | `agent_obs/span.py` (если не определён) | low (вероятно уже есть) |

### 21.6. Когда интеграция «сломается»

| Сценарий | Что делать |
|---|---|
| OryaObservability major version bump (v2) | Pin version в `pyproject.toml`: `agent-obs>=1.0,<2.0` |
| Langfuse v4 release | Проверить compatibility в OryaObservability; обновить при необходимости |
| Sampler-proxy port change | Обновить `LANGFUSE_HOST` env-variable |
| PII-детектор добавлен в OryaObservability | Использовать через `AGENT_OBS_PII_DETECTORS` env-variable |
| Injection-classifier model change | Использовать через `AGENT_OBS_INJECTION_MODEL` env-variable |

---

## 22. Итог v6

`ROADMAP6.md` — расширение `ROADMAP5.md` пятью улучшениями, интегрированными в 6 фаз:

### Что v6 добавляет к v5

1. **MVP получает L0 memory** (M-25 MDStore + M-26 /learn + M-27 Compactor) — память с первого дня.
2. **ALPHA получает OryaObservability SDK + sampler-proxy** (A-16 + A-17) — production-grade observability без написания своего кода.
3. **BETA получает L1 SQLite memory** (B-21 + B-22 + B-23) — structured + lexical access; B-00 deprecated.
4. **PROD получает L2 Qdrant memory + distributed tracing** (P-18 + P-19) — full 3-layer memory + debuggability.
5. **EXTENSION-PROD получает multi-instance memory replication** (E-11) — масштабирование memory.
6. **FUTURE получает continuous prompt-learning** (F-09) — агент сам улучшает свой system-prompt.

### Интеграция с OryaObservability

OryaObservability — зрелый проект (PC02–PC33 реализованы). Интеграция — 7 этапов (см. §21.2), из которых 5 готовых компонентов OryaObservability можно использовать как-is. Особенно хорошо стыкуется в режиме proxy (PC30-32): sampler-proxy `ALWAYS_KEEP_ATTRIBUTES` идеально совпадает с v5 CostAwareRouter и prompt-injection detector.

### Принцип 20/80 на v6

Из ~20 возможных улучшений v5 выбраны 5, которые дают 80% ценности при 20% усилий:
- L0 memory (MVP) — 80% ценности «агент помнит» за 1.5 дня.
- /learn (MVP) — 80% UX-ценности «capture pattern» за 4 часа.
- OryaObservability SDK (ALPHA) — 80% observability-ценности за 1 день.
- Sampler-proxy (ALPHA) — 80% dynamic-rate ценности за 6 часов.
- L1+L2 memory (BETA+PROD) — 80% structured+semantic-search ценности за 3 дня.

**Финальный статус:** roadmap v6 готов к реализации. `ARCHITECT6.md` и `BACKLOG6.md` описывают архитектуру и задачи.

---

*Конец документа ROADMAP6.md*
