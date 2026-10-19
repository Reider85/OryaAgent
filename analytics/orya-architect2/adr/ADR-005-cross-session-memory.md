# ADR-005: Cross-session memory через SQLite FTS5 + Qdrant

**Status:** Proposed
**Date:** 2026-10-19
**Authors:** Vasiliy Zhila (Reider85)
**Supersedes:** пункт «Memory cross-session (SQLite FTS5)» из `analytics/self-agent.md` §6 (отложен на v2)
**Depends on:** ADR-002, ADR-003
**Related:** ADR-006

---

## 1. Context (Контекст)

В `analytics/self-agent.md` §6 явным образом отложено:

> **Память между сессиями.** SQLite FTS5, `MEMORY.md`, checkpoint-writer, семантический индекс кодовой базы — не делаем. В MVP — только пользовательские преференсы в `memory.md`. Кросс-сессионная память требует решения по политике приватности и формату — это v2 (как у MiMo).

Параллельно в `analytics/agents-architect.md` §5.2 (разбор MiMoCode) выделен целый блок «Память и контекст»:

> Постоянная кросс-сессионная память на SQLite FTS5: проектный `MEMORY.md`, автоматический **checkpoint-writer-субагент** (структурированный снимок состояния), заметки и прогресс задач; при подходе к лимиту окна контекст **реконструируется** заново из чекпоинта + памяти + последних сообщений; инъекции памяти — с токен-бюджетом и ранжированием важности; `/context-limit` позволяет занижать точку компакции на модель.

Иными словами, индустриальный паттерн кросс-сессионной памяти — **гибридный**: SQLite FTS5 для лексического + structured-доступа, векторный стор для dense-семантики. И именно этот паттерн уже почти полностью реализован в **OriaHS** (PostgreSQL FTS + Qdrant).

ADR-003 вводит RAG-уровень с ingestion в OriaHS. Но этого недостаточно для **memory** — memory отличается от RAG тремя свойствами:

1. **Структурированность.** Memory — это не «чанки текста», а типизированные сущности: fact, preference, decision, todo, learned-skill. SQLite даёт реляционный доступ; Qdrant — только фильтры по metadata.
2. **Версионирование и conflict resolution.** Memory может обновляться: «старая версия X заменена на Y». Чистый retrieval-стор этого не делает — он append-only.
3. **Privacy/forget.** Memory — это личное, пользователь может запросить `forget everything about <topic>` — это операция по metadata, а не по контенту.

---

## 2. Decision (Решение)

**Cross-session memory реализуется двухслойно: SQLite FTS5 (structured + lexical) + Qdrant через OriaHS (dense), синхронизируемые через единый memory-ingest-воркер.**

### 2.1. Типы памяти

| Тип | Описание | Пример | TTL |
|---|---|---|---|
| `fact` | Факт о проекте/пользователе | «Проект использует PostgreSQL 16» | бесконечно |
| `preference` | Предпочтение пользователя | «Пользователь не любит TypeScript» | бесконечно |
| `decision` | Архитектурное решение | «ADR-001: MCP как первичный контракт» | бесконечно + supersede |
| `todo` | Задача в работе | «Доделать ADR-006» | до закрытия |
| `learned_skill` | Новый навык агента | «Если видишь ошибку X, используй паттерн Y» | бесконечно + versioning |
| `episodic` | Эпизод из прошлой сессии | «12 сентября обсуждали memory-tier» | 90 дней |
| `checkpoint` | Снимок состояния сессии | «На момент msg #45: задача X готова на 60%» | до supersede |

### 2.2. SQLite-схема

```sql
-- основной storage
CREATE TABLE memory_items (
  id TEXT PRIMARY KEY,                  -- ULID
  type TEXT NOT NULL,                   -- fact|preference|decision|todo|learned_skill|episodic|checkpoint
  content TEXT NOT NULL,                -- основной текст
  source TEXT NOT NULL,                 -- session_id | user_explicit | agent_inferred
  project TEXT,                         -- project context (nullable)
  created_at INTEGER NOT NULL,
  updated_at INTEGER NOT NULL,
  superseded_by TEXT,                   -- FK на новый id (для версионирования)
  confidence REAL DEFAULT 1.0,          -- 0..1, для agent_inferred
  metadata TEXT,                        -- JSON
  embedding_id TEXT,                    -- FK на Qdrant point id
  is_deleted INTEGER DEFAULT 0
);

-- FTS5 виртуальная таблица
CREATE VIRTUAL TABLE memory_fts USING fts5(
  content,
  content_type UNINDEXED,
  tokenize = 'porter unicode61'
);

-- триггер синхронизации
CREATE TRIGGER memory_ai AFTER INSERT ON memory_items BEGIN
  INSERT INTO memory_fts(rowid, content, content_type)
  VALUES (new.id, new.content, new.type);
END;

-- индексы
CREATE INDEX idx_memory_type_project ON memory_items(type, project) WHERE is_deleted = 0;
CREATE INDEX idx_memory_updated ON memory_items(updated_at DESC) WHERE is_deleted = 0;
```

### 2.3. Qdrant-коллекция `agent_memory`

```yaml
# qdrant_collections.yaml (OriaHS)
collections:
  agent_memory:
    vectors:
      size: 1024
      distance: Cosine
    payload_schema:
      memory_id: keyword
      type: keyword
      project: keyword
      source: keyword
      created_at: integer
      confidence: float
    on_disk_payload: true
```

### 2.4. Memory-ingest-воркер

```
┌─────────────────────────┐
│ session-log (JSONL)     │
└──────────┬──────────────┘
           │ watch
           ▼
┌─────────────────────────┐    ┌─────────────────────────┐
│ memory-extractor        │ ─► │ memory-ingest-worker    │
│ (LLM-based, haiku/mini) │    │  - SQLite write         │
│  - extract facts        │    │  - OriaHS POST /index   │
│  - extract decisions    │    │  - outbox → Qdrant      │
│  - extract todos        │    └─────────────────────────┘
│  - deduplicate          │
└─────────────────────────┘
```

Извлечение памяти — это **отдельная LLM-задача** на дешёвой модели (gpt-4o-mini / claude-haiku / yandex-gpt-lite), запускаемая:
- после каждого 10-го сообщения сессии (batch);
- при явной команде `/remember`;
- при закрытии сессии (final pass).

### 2.5. Retrieval-патч retrieval-orchestrator (ADR-004)

`retrieval-orchestrator` получает новый источник — `agent_memory`:

```typescript
type RetrievalSource = 'session_log' | 'knowledge_base' | 'code_index' | 'agent_memory';
```

Memory-retrieval имеет особенности:
- **Lexical-first**: сначала SQLite FTS5 (миллисекунды), потом Qdrant (десятки миллисекунд).
- **Type-filtering**: можно запросить только `decisions` или `preferences`.
- **Confidence-weighted**: low-confidence memories имеют пониженный score.
- **Project-scoped**: по умолчанию retrieval ограничен текущим project.

### 2.6. Операции пользователя

| Команда | Что делает | Storage |
|---|---|---|
| `/remember <text>` | явное добавление fact/preference | SQLite + Qdrant |
| `/forget <pattern>` | soft-delete по pattern-match | SQLite (`is_deleted=1`) + Qdrant (filter delete) |
| `/forget session <id>` | forget эпизодов конкретной сессии | metadata-filter |
| `/memory list [type]` | просмотр памяти | SQLite |
| `/memory export` | экспорт в JSON | SQLite |
| `/memory import <file>` | импорт | SQLite + Qdrant reindex |

### 2.7. Privacy

- **Default: project-local.** Каждый проект имеет свой `~/.self-agent/memory/<project>.sqlite`. Memory не утекает между проектами.
- **Global facts.** Пользователь может явно пометить memory как `global` (например, «я предпочитаю tab indentation») — она доступна во всех проектах.
- **Encryption at rest.** SQLite-file шифруется через SQLCipher, ключ в OS keychain.
- **Audit log.** Все записи/чтения memory логируются в `memory_audit.jsonl`.

---

## 3. Consequences (Последствия)

### Положительные

- **Контекстная связность между сессиями.** Агент «помнит» предпочтения и решения пользователя.
- **Structured access.** Через SQL можно: «покажи все TODO за последний месяц», «покажи все ADR с confidence > 0.8».
- **Использование OriaHS-инфраструктуры.** Qdrant-коллекция, outbox, reconciler, observability — всё уже есть.
- **Подготовка к checkpoint-writer (v3).** Схема memory_items готова для типа `checkpoint`.
- **Privacy by design.** Project-local + encryption + audit log.

### Отрицательные

- **Двойное хранение + синхронизация.** SQLite + Qdrant — два источника истины. Outbox-pattern (как в OriaHS) обязателен.
- **LLM-cost extraction'а.** Memory-extractor работает на каждой сессии. На haiku/mini — допустимо ($0.001-0.01 за сессию), но не бесплатно.
- **Risk of memory pollution.** LLM может извлечь неверный fact. Mitigation: confidence-score + user review.
- **Conflict resolution сложен.** Если пользователь меняет предпочтение — старое нужно supersede, не удалить. Это влияет на retrieval.
- **Зависимость от SQLite.** Хотя SQLite embedded, это всё ещё отдельный storage-движок в стеке агента.

### Нейтральные

- **Размер memory-ingest-воркера** — ~600-800 строк Python.

---

## 4. Alternatives Considered (Альтернативы)

### A. Только Qdrant (без SQLite)

Вся память — в Qdrant с metadata.

| Критерий | SQLite + Qdrant | Только Qdrant |
|---|---|---|
| Lexical search | ✅ FTS5 | ⚠️ Qdrant payload text-search слаб |
| Structured queries (type, project, date-range) | ✅ SQL | ⚠️ filter-combos |
| Conflict resolution / supersede | ✅ SQL JOIN | ❌ сложно |
| Forget by pattern | ✅ LIKE | ❌ content-search по Qdrant слаб |
| Latency lexical | ✅ <5 ms | ❌ 50-100 ms |
| Сложность | средняя | низкая |
| Backup / portability | ✅ .sqlite file | ❌ Qdrant dump |

**Выбор:** SQLite обязателен для structured-операций и forget-by-pattern.

### B. Только SQLite FTS5 (без Qdrant)

| Критерий | SQLite + Qdrant | Только SQLite |
|---|---|---|
| Semantic search | ✅ | ❌ |
| Hybrid search | ✅ | ❌ только lexical |
| Использование OriaHS | ✅ | ❌ дублирование |
| Соответствие MiMo-паттерну | ✅ | ⚠️ |

**Выбор:** Qdrant нужен для semantic. MiMo использует FTS5-only, но у MiMo нет OriaHS.

### C. MEMORY.md как plain-text (как в Claude Code / MiMo)

Markdown-файл с предпочтениями, инъектируемый в каждый промпт целиком.

| Критерий | SQLite + Qdrant | MEMORY.md |
|---|---|---|
| Масштаб | ✅ тысячи записей | ❌ до 100 строк |
| Retrieval | ✅ selective | ❌ весь файл в промпт |
| Structured queries | ✅ | ❌ |
| Privacy / forget | ✅ | ⚠️ ручное редактирование |
| UX простота | ⚠️ | ✅ |
| Token cost | ✅ дешёвый (selective) | ❌ дорогой (весь файл) |

**Выбор:** MEMORY.md сохраняется как **bootstrap-слой** (короткие critical-preferences, всегда в промпте), SQLite+Qdrant — для масштабируемой memory. Гибрид.

### D. Pinecone / Weaviate Cloud (managed vector store)

| Критерий | Qdrant (через OriaHS) | Managed cloud |
|---|---|---|
| Self-hosted privacy | ✅ | ❌ данные уходят |
| Latency (local) | ✅ <50 ms | ❌ 100-300 ms |
| Использование существующего OriaHS | ✅ | ❌ |
| Стоимость | ✅ нулевая | ❌ per-query |
| Offline / airgap | ✅ | ❌ |

**Выбор:** Qdrant через OriaHS — приватность и переиспользование.

---

## 5. Metrics (Метрики оценки)

| Метрика | Целевое значение | Источник |
|---|---|---|
| `memory_items_total` (per project) | растёт стабильно | SQLite |
| `memory_items_by_type` distribution | balanced except episodic | SQLite |
| `memory_extraction_success_rate` | > 95% | ingest-worker |
| `memory_extraction_llm_cost_per_session` | < $0.02 | ingest-worker |
| `memory_retrieval_recall_at_5` | > 0.8 | offline eval |
| `memory_retrieval_latency_ms` (p95, SQLite+Qdrant) | < 100 ms | self-agent |
| `memory_supersede_rate` (доля обновляемых) | 5-15% | SQLite |
| `memory_forget_latency_ms` | < 500 ms | SQLite + Qdrant filter-delete |
| `memory_audit_log_completeness` | 100% | audit |
| `memory_conflict_unresolved_count` | < 5 | SQLite |

---

## 6. Implementation Notes

### 6.1. Memory-extractor prompt (упрощённый)

```
You are a memory extraction assistant. Read the conversation fragment below and extract
memory items in JSON. Each item has:
- type: fact | preference | decision | todo | learned_skill | episodic | checkpoint
- content: short, factual, in third person
- confidence: 0..1 (lower if inferred, higher if explicit)
- project: if mentioned
- supersede_id: if this updates an existing memory

Only extract durable, cross-session-relevant items. Skip ephemeral task state.

CONVERSATION:
{{conversation_fragment}}

OUTPUT (JSON array):
[
  {"type": "preference", "content": "User prefers tabs over spaces", "confidence": 0.95},
  {"type": "decision", "content": "Project will use OryaHS for retrieval", "confidence": 1.0}
]
```

### 6.2. SQLite-доступ из self-agent

Self-agent (TypeScript) обращается к SQLite через `better-sqlite3` (sync) или `sql.js` (WASM). Учитывая, что memory-ops — это не hot-path, sync-доступ приемлем.

### 6.3. Sync SQLite ↔ Qdrant через outbox

```sql
-- при INSERT в memory_items:
INSERT INTO memory_outbox (memory_id, op, payload, created_at)
VALUES (new.id, 'index', json_object(...), strftime('%s','now'));
```

Outbox-drain-воркер (Python) читает `memory_outbox`, делает embedding (bge-m3) и POST `/index` в OriaHS. Это симметрично с существующим outbox OriaHS.

### 6.4. Retrieval-запрос к memory

```typescript
async function retrieveMemory(query: string, opts: MemoryQueryOpts): Promise<MemoryItem[]> {
  // 1. SQLite FTS5 — lexical
  const lexical = await sqlite.query(
    `SELECT m.*, bm25(memory_fts) as score
     FROM memory_fts JOIN memory_items m ON m.id = memory_fts.rowid
     WHERE memory_fts MATCH ? AND m.is_deleted = 0 AND m.type IN (?)
     ORDER BY score LIMIT ?`,
    [query, opts.types, opts.topK]
  );

  // 2. OriaHS Qdrant — semantic
  const semantic = await mcp.callTool('hybrid_search', {
    query, top_k: opts.topK, mode: 'vector',
    filters: { collection: 'agent_memory', project: opts.project }
  });

  // 3. Merge + dedup
  return mergeByMemoryId(lexical, semantic);
}
```

### 6.5. Encryption at rest

```python
# memory-ingest-worker opens SQLite with SQLCipher
import sqlcipher3
conn = sqlcipher3.connect(memory_db_path)
conn.execute(f"PRAGMA key = \"{key_from_keychain()}\";")
```

---

## 7. Risks (Риски)

| Риск | Вероятность | Влияние | Митигация |
|---|---|---|---|
| LLM-extractor галлюцинирует факты | высокая | среднее | confidence + user review для low-confidence |
| Memory pollution (мусор накапливается) | высокая | среднее | 90-day TTL для episodic, periodic cleanup |
| SQLite ↔ Qdrant diverge | средняя | высокое | outbox + reconciler + consistency-check job |
| SQLCipher key lost | низкая | критическое | key backup в OS keychain + recovery-phrase |
| Cross-project memory leak | низкая | критическое | strict project-scoping, audit log |
| Latency SQLite на больших memory | низкая | низкое | FTS5 + индексы; при 100k+ items — sharding |

---

## 8. References (Ссылки)

- `analytics/self-agent.md` §6 — Memory cross-session отложена
- `analytics/agents-architect.md` §5.2 — MiMo memory pattern
- `OriaHS/README.md` — outbox + reconciler pattern
- SQLite FTS5 docs: https://www.sqlite.org/fts5.html
- SQLCipher: https://www.zetetic.net/sqlcipher/
- ADR-002 — OriaHS как MCP-сервер
- ADR-003 — RAG-источники
- ADR-004 — Retrieval-orchestrator
- ADR-006 — Tiered context
