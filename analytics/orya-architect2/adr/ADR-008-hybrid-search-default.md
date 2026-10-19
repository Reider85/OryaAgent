# ADR-008: Hybrid search fusion как дефолтный retrieval mode

**Status:** Proposed
**Date:** 2026-10-19
**Authors:** Vasiliy Zhila (Reider85)
**Depends on:** ADR-002, ADR-003
**Related:** ADR-009

---

## 1. Context (Контекст)

OriaHS — это **готовая** система гибридного поиска: PostgreSQL (lexical, sparse) + Qdrant (vector, dense) + fusion + rerank. Это означает, что self-agent получает «из коробки» три режима retrieval:

1. **Lexical-only** — `POST /search?mode=lexical`. Использует `pg_trgm` (fuzzy) + `tsvector` (full-text). Сильна в: точных совпадениях, именах собственных, технических терминах, кодовых идентификаторах. Слаба в: парафразе, семантической близости.
2. **Vector-only** — `POST /search?mode=vector`. Использует Qdrant + bge-m3 embeddings. Сильна в: семантической близости, парафразе, многоязычности. Слаба в: точных терминах (например, поиск `getUserById` плохо работает через embeddings).
3. **Hybrid** — `POST /search?mode=hybrid`. Параллельно выполняет lexical + vector, потом fuses (RRF или weighted). Сильна в обоих. Слаба в: latency (двойной запрос) + стоимость.

Из `analytics/self-agent.md` §4.6 понятно, что текущий `context-manager` retrieval не делает вообще. Из ADR-003 следует, что RAG появится поверх OriaHS. Из ADR-004 — что `retrieval-orchestrator` решает, когда retrieve. Но остаётся вопрос: **какой из трёх режимов использовать по умолчанию?**

Параллельно есть небезосновательная альтернатива — **query-classification**: классифицировать запрос и выбирать режим. Например, для «найди функцию `getUserById`» — lexical, для «как мы обсуждали аутентификацию» — vector. Это добавляет сложности, но даёт лучший результат.

Также из OriaHS README видно, что есть push-down фильтры (C-10) — Postgres pre-filtering для Qdrant. Это означает, что hybrid mode уже оптимизирован для metadata-фильтров (например, `source=session_log`).

---

## 2. Decision (Решение)

**Hybrid search (sparse + dense fusion) устанавливается как дефолтный retrieval mode для self-agent. Query-classification — опциональная надстройка v0.4.**

### 2.1. Дефолтная стратегия

```typescript
const DEFAULT_RETRIEVAL_STRATEGY = {
  mode: 'hybrid',
  top_k: 5,
  rerank: true,
  fusion: 'rrf',           // Reciprocal Rank Fusion
  fusion_weights: { lexical: 0.4, vector: 0.6 },  // tuned для агентских запросов
  pushdown_filters: true,
  score_threshold: 0.3,
};
```

**Почему 0.4 / 0.6?** Агентские запросы в большинстве своем парафрастические («помнишь, мы обсуждали...»), но содержат и точные идентификаторы (function names, file paths). Чуть больший вес vector'у покрывает типичный случай.

### 2.2. Когда overrides

| Сценарий | Override | Обоснование |
|---|---|---|
| Query содержит identifier (CamelCase, snake_case, ALL_CAPS) | `mode: 'lexical'`, weight 0.8/0.2 | identifiers плохо эмбеддятся |
| Query содержит кавычки `"..."` | `mode: 'lexical'`, exact-match boost | явный exact-поиск |
| Query длинный (>20 слов) | `mode: 'vector'`, weight 0.2/0.8 | длинные запросы — семантика |
| Query содержит referential marker | `mode: 'hybrid'`, weight 0.5/0.5 | balanced |
| Явная команда `/recall code <symbol>` | `mode: 'lexical'` | code-lookup |
| Metadata-фильтр по `source: code_index` | `mode: 'hybrid'`, weight 0.6/0.4 | code-semantics гибрид |
| Reranker circuit breaker открыт | `mode: 'lexical'` (fallback) | без rerank'а dense-результаты хуже |

### 2.3. Fusion algorithm

OriaHS уже поддерживает взвешенный fusion (см. README — «веса в fusion»). Дефолт — **Reciprocal Rank Fusion (RRF)** с весами:

```
fused_score = w_lexical * (1 / (k + rank_lexical))
            + w_vector  * (1 / (k + rank_vector))
```

где `k = 60` (стандартный параметр RRF, сглаживает top-ranks).

Если OriaHS поддерживает weighted-sum fusion (альтернатива), можно переключаться через параметр `fusion: 'rrf' | 'weighted_sum'`.

### 2.4. Push-down фильтры

Все metadata-фильтры передаются в OriaHS, который применяет Postgres pre-filtering к lexical-каналу и Qdrant payload-filter к vector-каналу:

```typescript
const filters = {
  source: { $in: ['session_log', 'knowledge_base'] },  // исключаем code для этого запроса
  project: currentProject,
  ts: { $gte: Date.now() - 90 * 24 * 60 * 60 * 1000 },  // последние 90 дней
};
```

Это критично для производительности: без push-down Qdrant будет сканировать всю коллекцию.

### 2.5. Score normalization

После fusion score'ы нормализуются в `[0, 1]`:

```typescript
function normalizeScore(raw: number, min: number, max: number): number {
  if (max === min) return 0.5;
  return (raw - min) / (max - min);
}
```

Normalized score используется для:
- `score_threshold` (отсечение шума);
- ranking внутри tiered-context (ADR-006 Cold-tier);
- observability (гистограммы score-distribution).

### 2.6. Query-classification (опционально, v0.4)

Если query-classifier включён, перед основным retrieval запускается лёгкая классификация:

```typescript
interface QueryClassifier {
  classify(query: string): Promise<QueryClass>;
}

type QueryClass = {
  type: 'identifier' | 'paraphrase' | 'exact' | 'mixed';
  suggested_mode: 'lexical' | 'vector' | 'hybrid';
  suggested_weights: { lexical: number; vector: number };
  confidence: number;
};
```

Classifier может быть:
- **Rule-based** (regex + heuristics) — бесплатно, 90% accuracy на agent-queries.
- **LLM-based** (haiku/mini) — дорого, 95% accuracy.
- **Small ML model** (fine-tuned BERT-tiny) — средне по цене, 93% accuracy.

**Дефолт v0.2-v0.3**: rule-based classifier (если вообще нужен). **v0.4**: опциональный ML-classifier.

---

## 3. Consequences (Последствия)

### Положительные

- **Best-of-both-worlds по дефолту.** Hybrid покрывает и парафразу, и identifiers.
- **Использование OriaHS на максимум.** Все его возможности (fusion, push-down, facets) задействованы.
- **Прозрачность.** Параметры fusion настраиваемые, observability полная.
- **Cost-control.** Push-down фильтры радикально снижают cost Qdrant-сканирования.

### Отрицательные

- **Latency.** Hybrid = 2 параллельных запроса + fusion + rerank → 500-800 ms p95.
- **Cost.** Каждый retrieval дороже, чем single-mode.
- **Tuning сложности.** Веса 0.4/0.6 — гиперпараметр, требующий калибровки.
- **Иногда hybrid хуже single-mode.** Для exact-match query (`getUserById`) lexical быстрее и точнее.

### Нейтральные

- **Override-логика** — ~200 строк кода в `retrieval-orchestrator`.

---

## 4. Alternatives Considered (Альтернативы)

### A. Vector-only как дефолт

| Критерий | Hybrid | Vector-only |
|---|---|---|
| Identifier-search | ✅ | ❌ |
| Paraphrase-search | ✅ | ✅ |
| Latency | ⚠️ | ✅ |
| Cost | ⚠️ | ✅ |
| Code-lookup | ✅ | ❌ |

**Выбор:** Vector-only проигрывает на identifiers — критично для code-агента.

### B. Lexical-only как дефолт

| Критерий | Hybrid | Lexical-only |
|---|---|---|
| Identifier-search | ✅ | ✅ |
| Paraphrase-search | ✅ | ❌ |
| Latency | ⚠️ | ✅ |
| Multi-lingual | ✅ | ⚠️ |

**Выбор:** Lexical-only проигрывает на парафразе — критично для memory-retrieval.

### C. Query-classification как дефолт (не v0.4, а сразу)

| Критерий | Hybrid-default + opt-classifier | Classification-default |
|---|---|---|
| Готовность к v0.2 | ✅ | ❌ нужен classifier |
| Сложность | низкая | средняя |
| Worst-case latency | ✅ | ❌ + classification |
| Cost | ✅ | ❌ + classifier LLM |
| Accuracy на типичных запросах | ⚠️ 80% | ✅ 90%+ |

**Выбор:** Hybrid-default — minimum viable. Classification — v0.4 enhancement.

### D. Hybrid с weighted-sum fusion вместо RRF

| Критерий | RRF | Weighted-sum |
|---|---|---|
| Score-scale independence | ✅ | ❌ требует normalization |
| Tuning простота | ✅ один параметр k | ❌ два веса + normalization |
| Top-rank smoothing | ✅ | ❌ |
| Поддержка OriaHS | ✅ | ✅ |

**Выбор:** RRF как дефолт — проще и стабильнее. Weighted-sum — для advanced-tuners.

### E. Multi-vector retrieval (DPR + colBERT + bge-m3)

Использовать несколько embedder'ов и merge.

| Критерий | Single bge-m3 | Multi-vector |
|---|---|---|
| Cost | ✅ | ❌ x2-x3 |
| Latency | ✅ | ❌ |
| Accuracy | ⚠️ | ✅ +2-5% |
| Storage | ✅ | ❌ x2-x3 |

**Выбор:** Single bge-m3 — точность достаточна, cost-control важнее.

---

## 5. Metrics (Метрики оценки)

| Метрика | Целевое значение | Источник |
|---|---|---|
| `retrieval_mode_distribution` | hybrid 70-80%, lexical 15-25%, vector 5-10% | self-agent |
| `retrieval_recall_at_10` (overall) | > 0.85 | offline eval (C-07) |
| `retrieval_recall_at_10` (identifier-queries) | > 0.90 | offline eval |
| `retrieval_recall_at_10` (paraphrase-queries) | > 0.80 | offline eval |
| `retrieval_precision_at_5` | > 0.70 | offline eval |
| `retrieval_latency_ms` (p95, hybrid) | < 800 ms | OriaHS + self-agent |
| `retrieval_fusion_stability` (variance of fused scores) | низкая | OriaHS |
| `pushdown_filter_rate` (доля запросов с push-down) | > 70% | OriaHS |
| `score_threshold_cutoff_rate` (доля результатов отрезанных) | 10-30% | self-agent |
| `override_trigger_rate` (доля queries с override) | 10-30% | self-agent |

---

## 6. Implementation Notes

### 6.1. Retrieval-query construction

```typescript
function buildRetrievalQuery(decision: RetrievalDecision, session: SessionLog): RetrievalQuery {
  const userQuery = extractQueryText(session);
  const filters = buildFilters(decision, session);

  // identifier-detection
  const hasIdentifier = /\b[A-Z][a-zA-Z0-9]*[A-Z]\b|\b[a-z]+_[a-z_]+\b|\b[A-Z_]{3,}\b/.test(userQuery);

  if (hasIdentifier && userQuery.length < 50) {
    return {
      query: userQuery,
      mode: 'lexical',
      top_k: decision.topK,
      rerank: true,
      fusion_weights: { lexical: 0.8, vector: 0.2 },
      filters,
    };
  }

  // paraphrase-detection
  if (userQuery.split(' ').length > 20) {
    return {
      query: userQuery,
      mode: 'vector',
      top_k: decision.topK,
      rerank: true,
      fusion_weights: { lexical: 0.2, vector: 0.8 },
      filters,
    };
  }

  // default: hybrid
  return {
    query: userQuery,
    mode: 'hybrid',
    top_k: decision.topK,
    rerank: true,
    fusion: 'rrf',
    fusion_weights: { lexical: 0.4, vector: 0.6 },
    filters,
  };
}
```

### 6.2. Push-down filters construction

```typescript
function buildFilters(decision: RetrievalDecision, session: SessionLog): MetadataFilter {
  const filters: MetadataFilter = {
    project: session.projectId,
  };

  // exclude current session from session_log results
  if (decision.source !== 'knowledge_base') {
    filters.exclude_sessions = [session.id];
  }

  // retention for episodic memory
  if (decision.source === 'agent_memory') {
    filters.ts_gte = Date.now() - 90 * 24 * 60 * 60 * 1000;
    filters.memory_type_in = ['fact', 'preference', 'decision', 'episodic'];
    filters.confidence_gte = 0.5;
  }

  return filters;
}
```

### 6.3. Rerank-fallback

```typescript
async function retrieveWithFallback(query: RetrievalQuery, mcp: MCPClient): Promise<RetrievedChunk[]> {
  try {
    return await mcp.callTool('hybrid_search', query);
  } catch (e) {
    if (e instanceof CircuitBreakerOpenError) {
      // reranker circuit breaker — fallback to lexical without rerank
      return await mcp.callTool('hybrid_search', { ...query, rerank: false, mode: 'lexical' });
    }
    throw e;
  }
}
```

### 6.4. Offline-eval extension (C-07 из OriaHS)

Добавить в `eval/datasets/`:

```jsonl
{"id":"q1","query":"getUserById","expected_source":"code_index","expected_top1_contains":"getUserById","mode_hint":"lexical"}
{"id":"q2","query":"как мы обсуждали memory tier","expected_source":"session_log","expected_keywords":["memory","tier","hot","warm"],"mode_hint":"vector"}
{"id":"q3","query":"ADR-001 MCP","expected_source":"knowledge_base","expected_keywords":["MCP","contract","tool"],"mode_hint":"hybrid"}
```

Эти queries прогоняются nightly (C-07) с замером recall@10 per mode.

### 6.5. Tuning loop

1. nightly-eval прогоняет 100 queries с разными `fusion_weights` (grid search).
2. Логирует recall@10 per weight combo.
3. Раз в неделю автоматически применяется best-weight, если улучшение > 3%.

---

## 7. Risks (Риски)

| Риск | Вероятность | Влияние | Митигация |
|---|---|---|---|
| Hybrid latency > 1s | средняя | высокое | speculative prefetch + cache + parallel запросы |
| Identifier-detection false negative | средняя | среднее | regex-tuning + offline-eval |
| Fusion weights устарели | высокая | среднее | auto-tuning loop (weekly) |
| Qdrant payload-filter медленный | низкая | среднее | push-down в PG + index on payload |
| Reranker circuit breaker открывается часто | средняя | высокое | мониторинг + fallback to lexical |
| Score normalization inconsistency между modes | средняя | низкое | единая normalizeScore() |

---

## 8. References (Ссылки)

- `OriaHS/README.md` — фаза Critical, fusion weights, push-down фильтры (C-10)
- `OriaHS/analitics/ARCHITECT.md` — детальная архитектура search-orchestrator
- `analytics/self-agent.md` §4.6 — текущий context-manager без retrieval
- ADR-002 — OriaHS как MCP-сервер
- ADR-003 — RAG-источники
- ADR-004 — Retrieval-orchestrator
- ADR-009 — Reranking pipeline
- Reciprocal Rank Fusion (Cormack et al.): https://plg.uwaterloo.ca/~gvcormac/cormacksigir09-rrf.pdf
- bge-m3: https://huggingface.co/BAAI/bge-m3
