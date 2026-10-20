# ADR-002: OriaHS как MCP-сервер retrieval для self-agent

**Status:** Proposed
**Date:** 2026-10-19
**Authors:** Vasiliy Zhila (Reider85)
**Depends on:** ADR-001
**Related:** ADR-003, ADR-004, ADR-008, ADR-009

---

## 1. Context (Контекст)

`OriaHS` — это уже работающая бэкенд-система гибридного поиска со следующими зрелыми компонентами:

- **Лексический канал** — PostgreSQL 16 + `pg_trgm` + `tsvector` (fuzzy, full-text).
- **Векторный канал** — Qdrant 1.x + `bge-m3` embeddings.
- **Fusion** — взвешенная комбинация sparse/dense с настраиваемыми весами.
- **Reranker** — cross-encoder с circuit breaker (C-01, C-03), speculative rerank (B11).
- **Facets** — агрегации для навигации по результатам.
- **Push-down фильтры** — Postgres pre-filtering для Qdrant (C-10).
- **Adaptive throttle** + **degraded mode** — устойчивость к пикам нагрузки.
- **Outbox + reconciler** — транзакционная синхронизация PG↔Qdrant.
- **Offline-eval (C-07)** — nightly замеры `recall@10`, `ndcg@10`.
- **Observability** — Prometheus + Grafana (8 дашбордов), критические метрики.

Параллельно `self-agent` (из `analytics/self-agent.md`) имеет:
- `context-manager` — только «последние N сообщений + урезание длинных tool-результатов»;
- `session-log` — JSONL append-only, без индексации;
- нет retrieval-уровня вообще;
- в §6 явным образом отложены `Memory cross-session`, `Compaction + Context Epoch`, `Skills` — все они предполагают retrieval.

Возникает естественный мост: **OriaHS уже реализует то, что self-agent запланировал на v2-v3**, но интеграция через прямой SDK свяжет два репозитория жёстко. ADR-001 вводит MCP как первичный контракт — это даёт возможность подключить OriaHS как MCP-сервер, не загрязняя ядро агента кодом клиента поиска.

---

## 2. Decision (Решение)

**OriaHS оборачивается в MCP-сервер `oriahs-mcp` и регистрируется в self-agent как первичный retrieval-провайдер.**

### 2.1. Контракт MCP-сервера `oriahs-mcp`

Сервер экспонирует следующие MCP-инструменты (mapping на существующие REST-endpoint'ы OriaHS):

| MCP tool | HTTP endpoint в OriaHS | Назначение |
|---|---|---|
| `hybrid_search` | `POST /search` | гибридный sparse+dense поиск с fusion |
| `lexical_search` | `POST /search?mode=lexical` | только pg_trgm/tsvector |
| `vector_search` | `POST /search?mode=vector` | только Qdrant |
| `retrieve_facets` | `POST /facets` | агрегации для навигации |
| `index_document` | `POST /index` | добавление документа (для ingestion из session-log) |
| `get_document` | `GET /documents/{id}` | точечное чтение |
| `health_check` | `GET /health/ready` | проба живости |

И MCP-ресурс:

| MCP resource | Назначение |
|---|---|
| `oriahs://collections/{name}/schema` | схема коллекции Qdrant для prompt-injection |

### 2.2. Транспорт

- **Transport:** HTTP + SSE (не stdio) — OriaHS уже работает как отдельный сервис в Docker-стеке.
- **Auth:** Bearer token через `ORIAHS_TOKEN` env. Token-scoping: read-only token для агента, write token только для ingestion-пайплайна (ADR-005).
- **Discovery:** `tools/list` кэшируется на 120s (статичная schema), `resources/list` — на 300s.

### 2.3. Декларативная регистрация в self-agent

```yaml
# ~/.self-agent/mcp.yml
servers:
  - name: oriahs-retrieval
    transport: http
    url: ${ORIAHS_BASE_URL}/mcp
    auth:
      type: bearer
      token_env: ORIAHS_TOKEN
      scopes: [read]
    tool_filter: ["hybrid_search", "lexical_search", "vector_search", "retrieve_facets", "get_document"]
    cache_ttl: 120s
    health_check: 30s
    retry:
      attempts: 3
      backoff: exponential
      base_ms: 100
```

### 2.4. Использование в `context-manager`

`context-manager` (бывший «урезалка») превращается в **retrieval-aware context manager**:

1. Перед сборкой LLM-запроса запускается retrieval-orchestrator (см. ADR-004).
2. Retrieval-orchestrator решает, нужен ли retrieval (по эвристикам: длинная сессия, упоминание прошлых тем, явный запрос пользователя).
3. Если нужен — формирует запрос к `hybrid_search` через MCP.
4. Результаты вставляются в системный промпт как секция `<retrieved_context>` (см. ADR-003).

### 2.5. Ingestion-пайплайн (отдельный процесс)

Сам `agent-loop` **не пишет** в OriaHS напрямую — это делает отдельный ingestion-воркер:

```
session-log (JSONL)
   │
   ▼
session-ingest-worker (отдельный процесс)
   │  chunking + embedding (bge-m3) + metadata
   ▼
OriaHS POST /index  ───►  outbox  ───►  reconciler ───►  Qdrant
```

Это сохраняет transactional outbox pattern OriaHS и не нагружает agent-loop.

---

## 3. Consequences (Последствия)

### Положительные

- **Переиспользование зрелой системы.** Self-agent получает production-ready retrieval без 6-12 месяцев разработки.
- **Observability out-of-the-box.** Метрики `reranker_latency_ms`, `circuit_breaker_state`, `eval_recall_at_10` уже собираются Prometheus'ом OriaHS.
- **Изоляция сбоев.** Падение OriaHS = degraded-режим агента (без retrieval, но работающий).
- **Multi-tenant использование.** OriaHS может одновременно обслуживать self-agent, IDE-плагин, batch-eval.
- **Дорожка к offline-eval.** C-07 nightly eval можно прогонять на эталонных агентских запросах, замеряя recall@10 retrieval-провайдера для агентского контекста.

### Отрицательные

- **Сетевая зависимость.** Если OriaHS и self-agent на разных машинах — latency растёт.
- **Версионный риск.** Эволюция `OriaHS` API требует обратной совместимости MCP-сервера.
- **Двойное хранение контекста.** Session-log остаётся в JSONL, а его embedding-копия — в Qdrant. Нужно consistency-решение.
- **Сложность отладки.** Trace распределён между агентом и OriaHS — нужен distributed tracing (OpenTelemetry).

### Нейтральные

- **Размер `oriahs-mcp`-сервера** — ~400-500 строк Python (FastMCP или аналогичный фреймворк).

---

## 4. Alternatives Considered (Альтернативы)

### A. Прямой Python SDK к OriaHS (без MCP)

```python
# self-agent/core/retrieval/oriahs_client.py
class OriaHSClient:
    def __init__(self, base_url: str, token: str): ...
    async def search(self, q: str, mode: str = "hybrid") -> list[Doc]: ...
    async def index(self, doc: Document) -> None: ...
```

| Критерий | MCP-сервер | Прямой SDK |
|---|---|---|
| Связанность | ✅ слабая (контракт MCP) | ❌ сильная (REST-типы) |
| Переиспользование в других клиентах | ✅ (TS, Rust, Go) | ❌ только Python |
| Tool-discovery | ✅ динамический | ❌ статический |
| Latency | +JSON-RPC overhead | прямой HTTP |
| Сложность | + MCP-слой | проще |
| Соответствие ADR-001 | ✅ | ❌ нарушает |
| Поддержка сторонних tool-clients (Claude Desktop, Cursor) | ✅ | ❌ |

**Выбор:** MCP-сервер — соответствует ADR-001, даёт бесплатную совместимость со сторонними клиентами.

### B. Встроить retrieval в ядро self-agent (in-process)

Поднять Qdrant и PostgreSQL рядом с ядром, реализовать orchestrator в `tool-registry`.

| Критерий | MCP-сервер OriaHS | In-process retrieval |
|---|---|---|
| Использование готового OriaHS | ✅ | ❌ переписывание |
| Resource-sharing с другими сервисами | ✅ | ❌ |
| Latency | сетевая | минимальная |
| Изоляция сбоев | ✅ процессная | ❌ падение роняет агент |
| Соответствие принципу «in-process только performance-critical» | ✅ | ❌ retrieval — не performance-critical для MVP |

**Выбор:** In-process создаёт дублирование с OriaHS. Retrieval не является hot-path (вызывается 0-3 раза за turn, не на каждый token).

### C. LangChain/LlamaIndex RetrievalTool

Использовать готовый retrieval-фреймворк с собственным векторным стором.

| Критерий | MCP-сервер OriaHS | LangChain retrieval |
|---|---|---|
| Использование существующих данных OriaHS | ✅ | ❌ отдельный store |
| Hybrid search (sparse+dense) | ✅ зрелый | ⚠️ базовый |
| Reranking с circuit breaker | ✅ | ❌ |
| Offline-eval | ✅ C-07 | ❌ |

**Выбор:** LangChain не даёт того, что уже есть в OriaHS. Гибридный поиск и rerank — критичны, и OriaHS их уже продакшн-готова.

---

## 5. Metrics (Метрики оценки)

Эти метрики должны собираться и в self-agent, и в OriaHS, и коррелировать через `trace_id`:

| Метрика | Целевое значение | Источник |
|---|---|---|
| `retrieval_tool_call_count` | 0.5-3 за turn | self-agent |
| `retrieval_tool_call_latency_ms` (p95) | < 500 ms | self-agent + OriaHS |
| `retrieval_hit_rate` (доля turns, где retrieved-контекст попал в LLM-промпт) | 30-60% | self-agent |
| `retrieval_precision_at_5` (по агентским relevance-меткам) | > 0.7 | offline eval |
| `eval_recall_at_10` (унаследовано из OriaHS C-07) | > 0.85 | OriaHS |
| `eval_ndcg_at_10` | > 0.75 | OriaHS |
| `reranker_circuit_breaker_open_total` | < 5/день | OriaHS |
| `oriahs_mcp_server_uptime` | > 99.5% | health-check |

---

## 6. Implementation Notes

### 6.1. Скелет `oriahs-mcp` сервера (Python)

```python
# oriahs_mcp/server.py
from mcp.server import Server
from mcp.types import Tool, TextContent
import httpx
from .config import OriaHSConfig

app = Server("oriahs-mcp")
cfg = OriaHSConfig.from_env()
client = httpx.AsyncClient(
    base_url=cfg.base_url, headers={"Authorization": f"Bearer {cfg.token}"}
)


@app.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="hybrid_search",
            description="Hybrid (sparse + dense) search over indexed documents. Use when you need to retrieve relevant context from long-term memory, past sessions, or knowledge base.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Natural-language query",
                    },
                    "top_k": {
                        "type": "integer",
                        "default": 10,
                        "minimum": 1,
                        "maximum": 50,
                    },
                    "mode": {
                        "type": "string",
                        "enum": ["hybrid", "lexical", "vector"],
                        "default": "hybrid",
                    },
                    "filters": {
                        "type": "object",
                        "description": 'Facet filters, e.g. {"source": "session_log"}',
                    },
                    "rerank": {"type": "boolean", "default": True},
                },
                "required": ["query"],
            },
        ),
        # ... other tools
    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    if name == "hybrid_search":
        r = await client.post(
            "/search", json={"query": arguments["query"], **arguments}
        )
        r.raise_for_status()
        results = r.json()["results"]
        return [TextContent(type="text", text=format_results(results))]
    # ... other tools


def format_results(results: list[dict]) -> str:
    return "\n\n".join(
        f"[{i + 1}] (score={r['score']:.3f}) {r['content'][:500]}"
        for i, r in enumerate(results)
    )


if __name__ == "__main__":
    import asyncio
    from mcp.server.stdio import stdio_server  # or HTTP transport

    asyncio.run(stdio_server(app))
```

### 6.2. Docker-интеграция

```yaml
# docker-compose.yml (OriaHS) — добавляется сервис
services:
  oriahs-mcp:
    build: ./oriahs_mcp
    environment:
      ORIAHS_BASE_URL: http://api:8000
      ORIAHS_TOKEN: ${ORIAHS_MCP_TOKEN}
    ports:
      - "8765:8765"
    depends_on:
      - api
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8765/health"]
      interval: 30s
```

### 6.3. Self-agent: retrieval-aware context manager

```typescript
// self-agent/core/context-manager.ts (изменения)
export class ContextManager {
  constructor(
    private mcp: MCPClient,
    private retriever: RetrievalOrchestrator,  // ADR-004
  ) {}

  async window(session: SessionLog): Promise<{ messages: Message[]; retrievedContext?: string }> {
    const messages = this.basicWindow(session);
    const shouldRetrieve = this.retriever.shouldRetrieve(session);
    if (!shouldRetrieve) return { messages };

    const query = this.retriever.buildQuery(session);
    const results = await this.mcp.callTool("hybrid_search", {
      query, top_k: 5, mode: "hybrid", rerank: true,
    });
    return { messages, retrievedContext: results.text };
  }
}
```

### 6.4. Mapping метрик OriaHS → self-agent

| OriaHS метрика | self-agent метрика | Корреляция |
|---|---|---|
| `reranker_latency_ms` | `retrieval_tool_call_latency_ms` (chunk: rerank) | sum по одному call |
| `eval_recall_at_10` | `retrieval_precision_at_5` | обе из C-07 dataset |
| `circuit_breaker_state` | `retrieval_degraded` (boolean) | 1:1 |

---

## 7. Risks (Риски)

| Риск | Вероятность | Влияние | Митигация |
|---|---|---|---|
| OriaHS API меняется (breaking change) | средняя | высокое | MCP-сервер — точка стабилизации, версия в URL (`/mcp/v1`) |
| Токен-аут OriaHS во время длинной сессии | низкая | среднее | refresh-token flow, кэш tool-list |
| Latency retrieval > 2s ломает UX | средняя | высокое | speculative prefetch (см. ADR-009), timeout 1500ms + degraded mode |
| Ingestion-воркер отстаёт от session-log | высокая | среднее | lag-метрика, alerting, batched writes |
| Qdrant и PG расходятся (outbox lag) | низкая | высокое | уже покрыто reconciler'ом OriaHS, метрика `outbox_lag` |

---

## 8. References (Ссылки)

- `OriaHS/README.md` — стек, фаза Critical
- `OriaHS/analitics/ARCHITECT.md` — детальная архитектура (упоминается в README OriaHS)
- `analytics/self-agent.md` §4.6 — текущий `context-manager`
- ADR-001 — MCP-контракт
- ADR-004 — retrieval-orchestrator
- FastMCP framework: https://github.com/jlowin/fastmcp
