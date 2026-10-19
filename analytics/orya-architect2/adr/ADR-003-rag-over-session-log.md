# ADR-003: RAG-уровень поверх session-log и knowledge base

**Status:** Proposed
**Date:** 2026-10-19
**Authors:** Vasiliy Zhila (Reider85)
**Depends on:** ADR-002
**Related:** ADR-004, ADR-005, ADR-006

---

## 1. Context (Контекст)

Текущий `session-log` (см. `analytics/self-agent.md` §4.5) — append-only JSONL с проекцией в сообщения для LLM. Это **минимально достаточное** решение для MVP, но оно создаёт три проблемы при росте:

1. **Потеря релевантного контекста.** `context-manager` держит «последние N сообщений + урезание длинных tool-результатов». Если пользователь в сообщении #5 обсуждал архитектуру базы данных, а в сообщении #45 вернулся к этой теме — ранний контекст потерян. LLM не знает, что тема уже поднималась.
2. **Отсутствие долгосрочной памяти.** Между сессиями знания не сохраняются. Каждая новая сессия начинается с нуля, даже если пользователь работает в одном проекте месяцами. В `self-agent.md` §6 это явно отложено на v2 (`Memory cross-session (SQLite FTS5)`).
3. **Отсутствие внешней knowledge base.** У агента нет доступа к проектным документам, ADR-ам, архитектурным заметкам, README других репозиториев. Каждый такой документ пришлось бы вставлять в промпт целиком.

Параллельно `OriaHS` — это готовый retrieval-движок с гибридным поиском, reranking и observability. ADR-002 подключает его как MCP-сервер. Возникает естественный вопрос: **что именно индексировать в OriaHS, чтобы закрыть все три проблемы?**

---

## 2. Decision (Решение)

**Вводится RAG-уровень из трёх типов источников, индексируемых в OriaHS через единый ingestion-пайплайн:**

### 2.1. Источники RAG

| Источник | Что индексируется | Chunking | Metadata |
|---|---|---|---|
| `session_log` | все assistant/user сообщения и tool-results из всех сессий | по сообщениям + sliding-window 3 сообщения | `session_id`, `ts`, `role`, `tool_name` |
| `knowledge_base` | markdown-документы из `~/.self-agent/kb/` и `./docs/` проекта | по заголовкам + параграфам | `source`, `path`, `title`, `tags` |
| `code_index` | файлы исходного кода проекта | по функциям/классам (tree-sitter) | `path`, `symbol`, `lang`, `git_sha` |

### 2.2. Ingestion-пайплайн (единый)

```
┌─────────────────┐    ┌──────────────────┐    ┌─────────────────┐
│ session_log     │ ─► │                  │    │                 │
│ (JSONL watcher) │    │  ingest-worker   │ ─► │ OriaHS POST     │
└─────────────────┘    │  (chunker +      │    │ /index          │
┌─────────────────┐    │  embedder +      │    │  (outbox →      │
│ kb-watcher      │ ─► │  metadata)       │    │   reconciler →  │
│ (FS events)     │    │                  │    │   Qdrant)       │
└─────────────────┘    └──────────────────┘    └─────────────────┘
┌─────────────────┐           ▲
│ code-watcher    │ ──────────┘
│ (git hooks)     │
└─────────────────┘
```

### 2.3. Retrieval-стратегия

При каждом LLM-вызове `retrieval-orchestrator` (см. ADR-004) решает:

1. **Нужен ли retrieval?** По эвристикам:
   - длина сессии > 20 сообщений;
   - в последнем user-сообщении есть referential-маркеры («как мы обсуждали», «помнишь», «как раньше»);
   - явная команда `/remember` или `/recall`;
   - LLM-вероятность retrieval-need > 0.5 (опционально, через отдельную мелкую модель).
2. **Какой источник?** По умолчанию — гибридный поиск по всем трём источникам с metadata-фильтрами. Пользователь может явно сужать (`/recall session`, `/recall docs`, `/recall code`).
3. **Сколько результатов?** top_k = 5, rerank = true. Если `retrieved_context` превышает 2000 токенов — переранжирование с жёстким отсечением.
4. **Куда вставлять?** В `system-prompt-builder` добавляется секция `<retrieved_context>` **после** identity/tools, но **до** последних сообщений. Это даёт LLM возможность ссылаться на retrieved, но не путать с актуальным диалогом.

### 2.4. Структура retrieved-context в промпте

```
<retrieved_context>
[1] (session=2026-09-15, score=0.87)
    User: как нам спроектировать memory-tier?
    Assistant: предлагаю разделить на hot/warm/cold по возрасту...

[2] (source=docs/ADR-005.md, score=0.81)
    ## 2. Decision
    Cross-session memory реализуется через SQLite FTS5 для лексического
    поиска и Qdrant для dense...

[3] (path=src/agent/memory.ts, symbol=MemoryTier, score=0.74)
    enum MemoryTier { Hot, Warm, Cold }
    class MemoryStore { ... }
</retrieved_context>
```

### 2.5. Privacy / retention

- **session_log**: индексируется только локально (private-режим по умолчанию). retention — 90 дней, после — auto-forget. Пользователь может явно пометить сессию как `ephemeral` (тогда не индексируется).
- **knowledge_base**: индексируется без ограничений, но только файлы явно добавленные в `~/.self-agent/kb/` или `./docs/`.
- **code_index**: индексируется текущий `git`-snapshot; при `git checkout` ingestion-воркер инвалидирует устаревшие чанки.

---

## 3. Consequences (Последствия)

### Положительные

- **Контекстная связность.** Агент «помнит» прошлые обсуждения тем без bloated prompt.
- **Доступ к знаниям.** Проектные ADR, README, документация — доступны через retrieval без ручного копирования в промпт.
- **Code-awareness.** LLM видит символы и сигнатуры из кодовой базы (через retrieval), а не только файлы, которые она явно открыла через `read`.
- **Использование OriaHS на максимум.** Все его возможности (hybrid, facets, rerank) задействованы.
- **Подготовка к v3 features.** Compaction (v2), checkpoint-writer (v3) — надстройки над тем же retrieval.

### Отрицательные

- **Двойное хранение.** Session-log в JSONL + embedding-копия в Qdrant. Consistency требует outbox-pattern (уже есть в OriaHS).
- **Ingestion-задержка.** От записи в session-log до появления в Qdrant — 1-10 секунд (через outbox). В течение этого окна retrieval не найдёт свежие данные.
- **Token budget.** Retrieved-context занимает 500-2000 токенов из окна. Нужно жёстко лимитировать.
- **False positives.** Retrieval может вернуть нерелевантные чанки, что ухудшит ответ LLM. Mitigation — rerank + low-score cutoff.
- **Privacy risk.** Если в session-log попали секреты (пароли, токены), они уйдут в Qdrant. Mitigation — secret-detector в ingestion-воркере.

### Нейтральные

- **Рост инфраструктуры.** Ingestion-воркер — отдельный процесс (~300 строк Python).

---

## 4. Alternatives Considered (Альтернативы)

### A. Только session-log (без knowledge_base и code_index)

| Критерий | Полный RAG | Только session-log |
|---|---|---|
| Покрытие сценариев | ✅ все три проблемы | ❌ только контекст |
| Сложность ingestion | средняя | низкая |
| Полезность для кодинга | ✅ высокая | средняя |
| Соответствие open-source амбициям | ✅ | ❌ |

**Выбор:** Только session-log не закрывает потребность в доступе к документации и коду.

### B. Отдельный векторный стор для каждого источника

Три инстанса Qdrant: `qdrant-sessions`, `qdrant-kb`, `qdrant-code`.

| Критерий | Один OriaHS | Три инстанса |
|---|---|---|
| Операционная сложность | ✅ низкая | ❌ высокая |
| Cross-source retrieval | ✅ один запрос | ❌ fan-out + merge |
| Изоляция политик retention | ⚠️ через metadata | ✅ |
| Стоимость | ✅ | ❌ x3 |

**Выбор:** Один OriaHS с metadata-фильтрами — проще и дешевле. Retention-политики реализуются через metadata + cron-cleanup.

### C. LangChain `ConversationalRetrievalChain` вместо своего RAG-слоя

| Критерий | Свой RAG-слир | LangChain |
|---|---|---|
| Использование OriaHS | ✅ | ❌ свой vectorstore |
| Гибридный поиск | ✅ | ⚠️ |
| Rerank | ✅ | ❌ |
| Контроль над промптом | ✅ полный | ⚠️ через prompt-template |
| Совместимость с MCP | ✅ | ❌ in-process |

**Выбор:** Свой RAG-слой поверх OriaHS — сохраняет все преимущества OriaHS.

### D. RAG только по явному запросу пользователя (`/recall`)

| Критерий | Авто-retrieval | Только по команде |
|---|---|---|
| UX | ✅ seamless | ❌ ручное |
| Latency overhead | средняя | нулевая |
| Риск false positives | выше | ниже |
| Покрытие сценариев | ✅ | ❌ пользователь забывает |

**Выбор:** Авто-retrieval с эвристиками + опциональный `/recall` для явного запроса.

---

## 5. Metrics (Метрики оценки)

| Метрика | Целевое значение | Источник |
|---|---|---|
| `retrieval_performed_ratio` | 30-60% turns | self-agent |
| `retrieval_relevant_ratio` (LLM использовала retrieved) | > 50% | self-agent (post-hoc) |
| `retrieval_false_positive_rate` (retrieved не использован) | < 30% | self-agent |
| `session_log_ingest_lag_ms` (p95) | < 5000 | ingest-worker |
| `kb_index_freshness_ms` | < 10000 (от FS event до Qdrant) | ingest-worker |
| `code_index_coverage` (доля файлов проекта в индексе) | > 95% | ingest-worker |
| `retrieval_token_budget_utilization` | 60-90% | self-agent |
| `secret_leak_incidents` | 0 | ingest-worker + audit |

### Offline-eval (расширение C-07 из OriaHS)

Добавить в `eval/datasets/`:
- `agent_session_recall_eval.jsonl` — 50 сценариев с проверкой recall@10 по past-session контексту;
- `agent_kb_recall_eval.jsonl` — 30 сценариев с проверкой recall@10 по KB;
- `agent_code_recall_eval.jsonl` — 30 сценариев с проверкой recall@10 по коду.

---

## 6. Implementation Notes

### 6.1. Ingestion-воркер (Python, отдельный процесс)

```python
# ingest/worker.py
import json, asyncio, hashlib
from pathlib import Path
from watchfiles import awatch
from mcp_client import MCPClient  # стандартный MCP-клиент
from .chunkers import chunk_session, chunk_markdown, chunk_code
from .detectors import detect_secrets

class IngestWorker:
    def __init__(self, mcp: MCPClient, kb_root: Path, code_root: Path):
        self.mcp = mcp
        self.kb_root = kb_root
        self.code_root = code_root

    async def ingest_session_event(self, event: dict):
        if detect_secrets(json.dumps(event)):
            await self.audit_log("secret_detected", event); return
        for chunk in chunk_session(event):
            await self.mcp.call_tool("index_document", {
                "content": chunk.content,
                "metadata": {**chunk.metadata, "source": "session_log"},
                "collection": "agent_context"
            })

    async def watch_kb(self):
        async for changes in awatch(self.kb_root):
            for change_type, path in changes:
                if change_type == self.added_or_modified:
                    await self.reindex_kb_file(path)

    async def watch_code(self):
        # через git post-commit hook, не watchfiles
        ...
```

### 6.2. Chunking-стратегии

| Источник | Стратегия | Размер чанка | Overlap |
|---|---|---|---|
| session_log | по сообщениям + sliding window 3 msg | 200-500 токенов | 1 msg |
| markdown (kb, ADR) | по заголовкам H2/H3 + параграфам | 300-700 токенов | 0 |
| code | tree-sitter: function/class/enum | 100-1000 токенов | 0 |

### 6.3. Self-agent: эвристики retrieval-need

```typescript
function shouldRetrieve(session: SessionLog): boolean {
  const msgs = session.events().filter(isMessage);
  if (msgs.length < 20) return false;  // короткая сессия — не нужно

  const lastUser = msgs.filter(e => e.role === 'user').pop();
  if (!lastUser) return false;

  const referentialPatterns = [
    /\b(как (мы )?обсуждали|помнишь|ранее|как раньше|в прошлый раз)\b/i,
    /\b(тот самый|известный|из прошлого)\b/i,
  ];
  if (referentialPatterns.some(p => p.test(lastUser.content))) return true;

  // повторное упоминание сущности из ранней сессии
  const entities = extractEntities(lastUser.content);
  if (entities.some(e => mentionedEarly(session, e))) return true;

  return false;
}
```

### 6.4. Контракт `<retrieved_context>` секции

```typescript
function buildRetrievedContext(results: RetrievedChunk[]): string {
  if (results.length === 0) return '';
  const items = results.map((r, i) => {
    const meta = formatMetadata(r.metadata);
    return `[${i+1}] (${meta}, score=${r.score.toFixed(2)})\n    ${r.content.trim()}`;
  });
  return `<retrieved_context>\n${items.join('\n\n')}\n</retrieved_context>`;
}
```

---

## 7. Risks (Риски)

| Риск | Вероятность | Влияние | Митигация |
|---|---|---|---|
| Secret leak в Qdrant | средняя | критическое | secret-detector в ingest + audit log |
| Stale code index после git checkout | высокая | среднее | post-checkout hook + invalidation по `git_sha` |
| Retrieval возвращает шум | высокая | среднее | rerank + score cutoff 0.3 + top_k=5 |
| Token budget overflow | средняя | среднее | hard cap 2000 токенов + truncation |
| Ingestion-воркер падает | средняя | высокое | systemd unit + alerting на `ingest_lag` |
| Приватность: чужой проект в индексе | низкая | критическое | явный whitelist через `~/.self-agent/kb/` |

---

## 8. References (Ссылки)

- `analytics/self-agent.md` §4.5 — session-log
- `analytics/self-agent.md` §6 — Memory cross-session отложена на v2
- `OriaHS/README.md` — outbox + reconciler
- ADR-002 — OriaHS как MCP-сервер
- ADR-004 — Retrieval-orchestrator
- ADR-005 — Cross-session memory
- ADR-006 — Tiered context (hot/warm/cold)
- bge-m3 embedder: https://huggingface.co/BAAI/bge-m3
- tree-sitter: https://tree-sitter.github.io
