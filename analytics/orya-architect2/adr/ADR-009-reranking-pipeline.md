# ADR-009: Reranking pipeline (cross-encoder) для retrieved context

**Status:** Proposed
**Date:** 2026-10-19
**Authors:** Vasiliy Zhila (Reider85)
**Depends on:** ADR-002, ADR-008
**Related:** ADR-004, ADR-010

---

## 1. Context (Контекст)

OriaHS имеет **готовый rerank-стек**:
- cross-encoder reranker (фаза Critical);
- circuit breaker (C-01, C-03);
- speculative rerank (B11) — раннее отсечение на top-N;
- метрики `reranker_latency_ms`, `circuit_breaker_state`, `circuit_breaker_opened_total`.

Это означает, что self-agent получает rerank «из коробки» через MCP-вызов (ADR-002). Однако остаются три архитектурных вопроса:

1. **Когда rerank нужен, а когда нет?** Rerank — дорогая операция (cross-encoder = full-attention над query+doc), добавляет 100-300 ms. Для простых exact-match queries он избыточен. Для парафраз и длинных запросов — критичен.
2. **Какой top_k до rerank vs после?** Rerank применяется к top-N кандидатов. Если N=20 → дорогой rerank. Если N=5 → риск, что правильный результат не попал в top-5 до rerank.
3. **Что делать при circuit breaker open?** Reranker может быть недоступен. Нужна graceful degradation.

Параллельно в ADR-008 указано, что `rerank: true` — дефолт. Но это слишком грубо. Нужно решение: **политика rerank'а для разных типов запросов и сценариев**.

---

## 2. Decision (Решение)

**Вводится `rerank-policy` — детерминированный модуль, решающий, нужен ли rerank, с каким top_k_pre, и как обрабатывать fallback.**

### 2.1. Политика rerank

| Сценарий | rerank? | top_k_pre | top_k_post | Обоснование |
|---|---|---|---|---|
| Exact-match query (кавычки или identifier) | ❌ | 5 | 5 | lexical уже точный |
| Short query (<5 слов, нет identifiers) | ✅ | 20 | 5 | короткие queries ambiguous → rerank критичен |
| Medium query (5-20 слов) | ✅ | 15 | 5 | standard |
| Long query (>20 слов, paraphrase) | ✅ | 25 | 8 | semantic ambiguity высокая |
| `code_lookup` strategy | ❌ | 5 | 5 | symbol lookup точный |
| `topic_continuation` | ✅ | 20 | 8 | topic может быть далека от exact-words |
| `explicit_recall` (`/recall`) | ✅ | 30 | 10 | пользователь явно просит лучшее |
| `speculative_prefetch` | ❌ | 3 | 3 | цена важнее точности |
| Circuit breaker open | ❌ | 10 | 5 | degraded mode, fallback to lexical |
| High-latency alert (OriaHS p95 > 1s) | ❌ | 5 | 5 | skip rerank для скорости |

### 2.2. Top-k pre-rerank

Дефолтный top_k_pre = 20. Это баланс:
- Слишком мало (5) → релевантный результат может не попасть в кандидатов.
- Слишком много (50) → rerank latency растёт линейно.

Speculative rerank (B11 из OriaHS) — это оптимизация: cross-encoder применяет early-exit, если top-candidates имеют явный score-gap. Self-agent получает это автоматически через MCP-параметр `speculative: true`.

### 2.3. Top-k post-rerank

Дефолтный top_k_post = 5. Это соответствует `Cold-tier` budget из ADR-006 (10-20% от 32k = ~3000-6400 токенов, что вмещает 5 чанков среднего размера).

### 2.4. Cross-encoder модель

OriaHS уже использует конкретный reranker (вероятно, `bge-reranker-v2-m3` или аналогичный). Self-agent не выбирает модель — он использует то, что настроено в OriaHS через `RERANKER_MODEL` env.

Через MCP-параметр можно запросить:
```json
{
  "rerank": true,
  "rerank_model": "bge-reranker-v2-m3",  // optional override
  "speculative": true,
  "rerank_top_k_pre": 20,
  "rerank_top_k_post": 5
}
```

### 2.5. Fallback chain

```
1. hybrid + rerank (default)
   ↓ circuit breaker open OR latency > 1s
2. hybrid + no rerank (top_k_pre = 10)
   ↓ still failing
3. lexical only (no rerank, fast)
   ↓ still failing
4. degraded mode (no retrieval, agent continues with hot+warm only)
```

Каждый шаг логируется с указанием причины fallback.

### 2.6. Caching

Для коротких сессий с повторяющимися темами — rerank-кэш:

```typescript
class RerankCache {
  private cache: LRUCache<string, RetrievedChunk[]>;

  async get(query: string, candidates: RetrievedChunk[]): Promise<RetrievedChunk[] | null> {
    const key = hashKey(query, candidates.map(c => c.id));
    return this.cache.get(key);
  }

  async set(query: string, candidates: RetrievedChunk[], reranked: RetrievedChunk[]): Promise<void> {
    const key = hashKey(query, candidates.map(c => c.id));
    this.cache.set(key, reranked);
  }
}
```

Cache hit-ratio ожидается 15-30% для типичных сессий (пользователь часто возвращается к темам).

### 2.7. Speculative prefetch

Для длинных сессий — `retrieval-orchestrator` может запустить speculative retrieval:
- предсказать next-topic (по last-message + history);
- запустить hybrid_search **без rerank** в фоне;
- если пользователь действительно вернулся к этой теме — у нас уже есть кандидаты;
- применить rerank только если нужен (по политике).

Это экономит 200-400 ms на основном retrieval.

---

## 3. Consequences (Последствия)

### Положительные

- **Использование зрелого rerank'а OriaHS.** Cross-encoder + circuit breaker + speculative — уже production-ready.
- **Cost-control.** Rerank только когда нужен → экономия latency и compute.
- **Graceful degradation.** Чёткая fallback-chain при сбоях.
- **Predictable budget.** top_k_post = 5 соответствует Cold-tier budget.
- **Caching economy.** 15-30% rerank-cache hit ratio = существенная экономия.

### Отрицательные

- **Дополнительная логика.** ~300 строк кода rerank-policy.
- **Risk of skip-rerank на ambiguity.** Если эвристика решила skip, но query был ambiguous — результат хуже.
- **Cache invalidation сложности.** При обновлении memory или KB нужно инвалилировать кэш.
- **Speculative prefetch cost.** Если предсказание ошибочное — wasted retrieval.

### Нейтральные

- **Все метрики rerank'а уже в OriaHS** (`reranker_latency_ms`, `circuit_breaker_state`). Self-agent только добавляет свои (`rerank_skipped_total`, `rerank_cache_hit_ratio`).

---

## 4. Alternatives Considered (Альтернативы)

### A. Always-rerank (без политики)

| Критерий | Policy-driven | Always |
|---|---|---|
| Latency | ✅ variable | ❌ постоянный overhead |
| Cost | ✅ | ❌ x3-x5 rerank-call'ов |
| Точность на exact-match | ⚠️ (skip — ok) | ⚠️ (rerank может испортить) |
| Simplicity | средняя | ✅ |

**Выбор:** Policy-driven — exact-match query не нуждается в rerank.

### B. Never-rerank (только fusion)

| Критерий | Policy-driven | Never |
|---|---|---|
| Latency | ✅ | ✅ |
| Точность на paraphrase | ✅ | ❌ |
| Использование OriaHS rerank | ✅ | ❌ |

**Выбор:** Policy-driven — paraphrase-queries сильно выигрывают от rerank.

### C. LLM-as-reranker: использовать основную LLM для rerank

Вместо cross-encoder — основная LLM (gpt-4, claude-sonnet) ранжирует top-5.

| Критерий | Cross-encoder (OriaHS) | LLM-as-reranker |
|---|---|---|
| Latency | ✅ 100-300 ms | ❌ 500-2000 ms |
| Cost | ✅ | ❌ $$$ |
| Точность | ⚠️ good | ✅ excellent |
| Context-length | ✅ 512 tokens | ✅ full window |
| Multilingual | ✅ | ✅ |
| Использование существующего OriaHS | ✅ | ❌ |

**Выбор:** Cross-encoder — для 95% случаев. LLM-as-reranker — v2 опция для high-stakes decisions (например, выбор ADR-документа для критичного решения).

### D. Multi-stage rerank: cross-encoder → LLM

Сначала cross-encoder на top-20 → top-5, потом LLM на top-5 → top-3.

| Критерий | Single-stage cross-encoder | Multi-stage |
|---|---|---|
| Latency | ✅ | ❌ +500-1000 ms |
| Точность | ⚠️ good | ✅ excellent |
| Cost | ✅ | ❌ |
| Применимость MVP | ✅ | ❌ overkill |

**Выбор:** Single-stage — для v0.2-v0.5. Multi-stage — v3 для high-stakes retrieval.

### E. ColBERT-style late-interaction (вместо cross-encoder)

| Критерий | Cross-encoder | ColBERT |
|---|---|---|
| Latency | ⚠️ | ✅ |
| Storage | ✅ | ❌ x10 (per-token embeddings) |
| Точность | ✅ | ✅ |
| Готовность в OriaHS | ✅ | ❌ нужна интеграция |

**Выбор:** Cross-encoder — OriaHS уже его использует. ColBERT — v3 если станет узким местом.

---

## 5. Metrics (Метрики оценки)

| Метрика | Целевое значение | Источник |
|---|---|---|
| `rerank_skip_rate` (доля retrievals без rerank) | 20-40% | self-agent |
| `rerank_skip_reasons` distribution | exact-match 50%, fallback 30%, prefetch 20% | self-agent |
| `rerank_cache_hit_ratio` | 15-30% | self-agent |
| `rerank_latency_ms` (p95, при включённом rerank) | < 300 ms | OriaHS |
| `rerank_circuit_breaker_open_total` per day | < 5 | OriaHS |
| `rerank_fallback_to_lexical_count` per day | < 10 | self-agent |
| `retrieval_ndcg_at_10_with_rerank` | > 0.80 | offline eval |
| `retrieval_ndcg_at_10_without_rerank` | > 0.65 | offline eval (baseline) |
| `rerank_improvement_delta` (ndcg with - ndcg without) | > 0.15 | offline eval |
| `speculative_prefetch_hit_ratio` | > 40% (если включён) | self-agent |

---

## 6. Implementation Notes

### 6.1. Rerank-policy module

```typescript
interface RerankPolicy {
  decide(query: RetrievalQuery, session: SessionLog, state: RetrievalState): RerankDecision;
}

interface RerankDecision {
  rerank: boolean;
  top_k_pre: number;
  top_k_post: number;
  speculative: boolean;
  reason: string;
}

class DefaultRerankPolicy implements RerankPolicy {
  decide(query, session, state): RerankDecision {
    // 1. circuit breaker check
    if (state.circuitBreakerOpen) {
      return { rerank: false, top_k_pre: 10, top_k_post: 5, speculative: false,
               reason: 'circuit_breaker_open' };
    }

    // 2. latency alert check
    if (state.avgOriaHSLatencyMs > 1000) {
      return { rerank: false, top_k_pre: 5, top_k_post: 5, speculative: false,
               reason: 'high_latency_alert' };
    }

    // 3. query-type check
    if (query.mode === 'lexical' && isExactMatch(query.query)) {
      return { rerank: false, top_k_pre: 5, top_k_post: 5, speculative: false,
               reason: 'exact_match' };
    }

    // 4. strategy-based defaults
    switch (query.strategy) {
      case 'code_lookup':
        return { rerank: false, top_k_pre: 5, top_k_post: 5, speculative: false,
                 reason: 'code_lookup_no_rerank' };
      case 'topic_continuation':
        return { rerank: true, top_k_pre: 20, top_k_post: 8, speculative: true,
                 reason: 'topic_continuation' };
      case 'explicit_recall':
        return { rerank: true, top_k_pre: 30, top_k_post: 10, speculative: false,
                 reason: 'explicit_recall' };
      case 'speculative_prefetch':
        return { rerank: false, top_k_pre: 3, top_k_post: 3, speculative: false,
                 reason: 'speculative_prefetch' };
      default:
        // standard
        return { rerank: true, top_k_pre: 15, top_k_post: 5, speculative: true,
                 reason: 'standard' };
    }
  }
}
```

### 6.2. Integration с retrieval-orchestrator

```typescript
class RetrievalOrchestrator {
  async execute(query: RetrievalQuery, mcp: MCPClient): Promise<RetrievedChunk[]> {
    const decision = this.rerankPolicy.decide(query, this.session, this.state);

    // check cache
    const cacheKey = hashKey(query, decision);
    const cached = await this.rerankCache.get(cacheKey);
    if (cached) return cached;

    // execute retrieval with rerank params
    const results = await mcp.callTool('hybrid_search', {
      ...query,
      rerank: decision.rerank,
      rerank_top_k_pre: decision.top_k_pre,
      rerank_top_k_post: decision.top_k_post,
      speculative: decision.speculative,
    });

    // cache and return
    await this.rerankCache.set(cacheKey, results);
    return results;
  }
}
```

### 6.3. Fallback handler

```typescript
async function retrieveWithFallback(query, mcp, policy, state): Promise<RetrievedChunk[]> {
  try {
    return await primaryRetrieve(query, mcp, policy, state);
  } catch (e) {
    if (e instanceof CircuitBreakerOpenError) {
      state.circuitBreakerOpen = true;
      // retry without rerank
      const fallbackQuery = { ...query, rerank: false, mode: 'lexical' };
      return await mcp.callTool('hybrid_search', fallbackQuery);
    }
    if (e instanceof TimeoutError) {
      // retry with shorter top_k
      const fallbackQuery = { ...query, top_k: 3, rerank: false };
      return await mcp.callTool('hybrid_search', fallbackQuery);
    }
    throw e;
  }
}
```

### 6.4. Speculative prefetch

```typescript
class SpeculativePrefetcher {
  private prefetched: Map<string, RetrievedChunk[]> = new Map();

  async maybePrefetch(session: SessionLog, mcp: MCPClient): Promise<void> {
    const predicted = this.predictNextTopic(session);
    if (!predicted) return;

    const cacheKey = `prefetch:${predicted.hash}`;
    if (this.prefetched.has(cacheKey)) return;

    const results = await mcp.callTool('hybrid_search', {
      query: predicted.query,
      mode: 'hybrid',
      top_k: 3,
      rerank: false,  // cheap prefetch
    });

    this.prefetched.set(cacheKey, results);
  }

  // вызывается из retrieval-orchestrator перед основным retrieve
  checkPrefetch(query: string): RetrievedChunk[] | null {
    const predicted = this.predictNextTopic(this.session);
    if (predicted && predicted.query === query) {
      return this.prefetched.get(`prefetch:${predicted.hash}`);
    }
    return null;
  }
}
```

### 6.5. Cache invalidation

```typescript
// при изменении memory (ADR-005)
memoryStore.on('change', (event) => {
  rerankCache.invalidateByFilter((key) => key.includes(`memory:${event.memoryId}`));
});

// при reindex KB (ADR-003)
ingestWorker.on('kb_reindexed', () => {
  rerankCache.clear();
});
```

---

## 7. Risks (Риски)

| Риск | Вероятность | Влияние | Митигация |
|---|---|---|---|
| Skip-rerank на ambiguous query → low precision | средняя | среднее | conservative policy + offline-eval |
| Circuit breaker синхронизация state с OriaHS | средняя | среднее | polling + event-driven updates |
| Cache stale после memory update | высокая | среднее | event-driven invalidation |
| Speculative prefetch wrong-topic → wasted cost | высокая | низкое | low top_k + cheap mode |
| Reranker model drift (после обновления OriaHS) | низкая | среднее | version-pinning + canary |
| Cross-encoder context limit (512 tokens) | средняя | среднее | chunk-size control в ingestion |

---

## 8. References (Ссылки)

- `OriaHS/README.md` — reranker + circuit breaker (C-01, C-03) + speculative rerank (B11)
- `OriaHS/C03_IMPLEMENTATION_REPORT.md` — детали circuit breaker
- ADR-002 — OriaHS как MCP-сервер
- ADR-004 — Retrieval-orchestrator
- ADR-008 — Hybrid search fusion
- bge-reranker-v2-m3: https://huggingface.co/BAAI/bge-reranker-v2-m3
- Cross-encoders: https://www.sbert.net/examples/cross_encoder/usage/usage.html
