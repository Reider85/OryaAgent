# ADR-004: Retrieval-orchestrator между context-manager и LLM-шовом

**Status:** Proposed
**Date:** 2026-10-19
**Authors:** Vasiliy Zhila (Reider85)
**Depends on:** ADR-001, ADR-002, ADR-003
**Related:** ADR-008, ADR-009, ADR-010

---

## 1. Context (Контекст)

В MVP `analytics/self-agent.md` §4.6 `context-manager` делает простую работу:

```
context-manager.window(session) = system_prompt + last_N_messages + truncated_tool_results
```

ADR-002 добавляет retrieval-источник (OriaHS), ADR-003 — определяет, **что** индексировать. Но остаётся открытым вопрос: **кто и как принимает решение о retrieval в каждом turn'е?**

Если отдать это `context-manager`'у — он перестанет быть простым «урезалкой» и обрастёт эвристиками, стратегиями fallback, speculative prefetch'ем. Это нарушает single responsibility и делает модуль трудно тестируемым. Если отдать `agent-loop`'у — цикл перестанет быть чистым (вывод №4 из `agents-architect.md`: «автономность надстраивается над циклом, а не встраивается в него»; это относится и к retrieval).

Параллельно OriaHS имеет собственный **search orchestrator** (`app/search/orchestrator.py`) — он координирует lexical/vector/fusion/rerank/facets/pushdown внутри одного retrieval-вызова. Это зрелый паттерн, но он решает **внутреннюю** задачу поиска. Агенту нужен **внешний** orchestrator: когда вызвать, с каким запросом, сколько результатов, как merge'ить с активным контекстом, нужен ли fallback.

---

## 2. Decision (Решение)

**Вводится модуль `retrieval-orchestrator` — отдельный слой между `context-manager` и `LLM-provider-seam`.**

### 2.1. Зона ответственности

`retrieval-orchestrator` отвечает за:

1. **Decision**: нужен ли retrieval в текущем turn'е (по эвристикам + state).
2. **Query building**: формирование поискового запроса из контекста сессии.
3. **Source routing**: выбор источника (session_log / knowledge_base / code_index / all).
4. **Strategy selection**: hybrid / lexical-only / vector-only / speculative-prefetch.
5. **Result merging**: дедупликация, score-normalisation, ordering.
6. **Token budgeting**: лимит на retrieved-context.
7. **Fallback**: если retrieval упал или вернул пустоту — degraded mode (продолжаем без retrieved).
8. **Caching**: короткий in-memory кэш одинаковых запросов внутри одной сессии.

### 2.2. Не отвечает за

- Сам search (это делает OriaHS через MCP — ADR-002).
- Хранение session-log (это `session-log` модуль).
- Вставку retrieved в промпт (это `system-prompt-builder`).
- Compaction / Context Epoch (это v2, отдельный ADR).

### 2.3. Поток данных

```mermaid
sequenceDiagram
    participant Loop as agent-loop
    participant CM as context-manager
    participant RO as retrieval-orchestrator
    participant MCP as MCPClient
    participant OriaHS as oriahs-mcp
    participant SPB as system-prompt-builder
    participant LLM as LLM-provider

    Loop->>CM: window(session)
    CM->>RO: shouldRetrieve(session)?
    RO->>RO: эвристики + state
    alt retrieval не нужен
        RO-->>CM: skip
        CM-->>Loop: messages
    else retrieval нужен
        CM->>RO: buildQuery(session)
        RO->>RO: extract entities + keywords
        RO->>MCP: callTool("hybrid_search", {query, top_k:5, rerank:true})
        MCP->>OriaHS: POST /search
        OriaHS->>OriaHS: lexical + vector + fusion + rerank
        OriaHS-->>MCP: results
        MCP-->>RO: ToolResult
        RO->>RO: merge + dedup + budget
        RO-->>CM: RetrievedContext[]
        CM->>SPB: addSection("retrieved_context", items)
        SPB-->>CM: system_prompt
        CM-->>Loop: messages + retrieved_context
    end
    Loop->>LLM: complete(messages, tools)
```

### 2.4. Стратегии retrieval

| Стратегия | Когда применяется | Запрос | top_k | rerank |
|---|---|---|---|---|
| `none` | короткая сессия, нет referential markers | — | — | — |
| `standard` | дефолт, гибридный поиск | сжатый контекст последних 5 сообщений | 5 | true |
| `topic_continuation` | referential marker («помнишь») | entities + тема | 8 | true |
| `speculative_prefetch` | длинная сессия + ожидается переход темы | предсказанная next-topic | 3 | false |
| `explicit_recall` | команда `/recall <query>` | явный query пользователя | 10 | true |
| `code_lookup` | LLM упомянула symbol/function | symbol name + сигнатура | 5 | true |
| `degraded` | OriaHS circuit breaker открыт | — | — | — |

### 2.5. State management

`retrieval-orchestrator` держит in-memory state:

```typescript
interface RetrievalState {
  lastQueryHash?: string;        // для дедупликации
  lastRetrievedIds: Set<string>; // для дедупликации между turn'ами
  prefetchCache: Map<string, RetrievedChunk[]>; // speculative
  failedAttempts: number;        // для backoff
  circuitBreakerOpen: boolean;   // зеркалирует OriaHS
}
```

State не персистится между сессиями — это горячий кэш одного run'а.

### 2.6. Token budgeting

```typescript
const DEFAULT_BUDGET = 2000; // токенов на retrieved_context

function budgetResults(results: RetrievedChunk[], budget: number): RetrievedChunk[] {
  let total = 0;
  const out: RetrievedChunk[] = [];
  for (const r of results.sort((a, b) => b.score - a.score)) {
    const t = countTokens(r.content);
    if (total + t > budget) {
      // пробуем truncated-версию
      const truncated = truncate(r.content, budget - total);
      if (truncated) out.push({ ...r, content: truncated });
      break;
    }
    out.push(r);
    total += t;
  }
  return out;
}
```

---

## 3. Consequences (Последствия)

### Положительные

- **Чистота `context-manager`.** Остается простым «окном»; retrieval-логика вынесена.
- **Чистота `agent-loop`.** Цикл не знает про retrieval.
- **Тестируемость.** `retrieval-orchestrator` тестируется изолированно — mock `MCPClient`, проверка стратегий.
- **Расширяемость.** Новая стратегия = новый класс, реализующий `RetrievalStrategy` интерфейс.
- **Observability.** Все retrieval-решения логируются: стратегия, latency, hit/miss, score distribution.
- **Дорожка к v2/v3 features.** Compaction, checkpoint-writer, autonomous-mode — все они потребуют retrieval-orchestrator как готовую точку.

### Отрицательные

- **Дополнительный модуль.** ~500-700 строк кода.
- **Латентность.** Один retrieval-вызов добавляет 200-800 ms к turn'у.
- **Сложность настройки.** Эвристики retrieval-need требуют тюнинга под проект.
- **Risk of over-engineering.** Для коротких сессий orchestrator может оказаться оверхедом.

### Нейтральные

- **State in-memory** — теряется при рестарте агента. Для MVP это приемлемо; персистенция — v2.

---

## 4. Alternatives Considered (Альтернативы)

### A. Inline в `context-manager`

Логика retrieval — внутри `context-manager.window()`.

| Критерий | Отдельный orchestrator | Inline в CM |
|---|---|---|
| Single responsibility | ✅ | ❌ CM делает 2 вещи |
| Тестируемость | ✅ | ❌ |
| Расширяемость стратегий | ✅ plugin-style | ❌ if-else ladder |
| Соответствие принципам self-agent.md | ✅ | ❌ |

**Выбор:** Отдельный модуль. CM остаётся простым.

### B. LLM-as-router: отдельная маленькая модель решает, нужен ли retrieval

Использовать дешёвую модель (gpt-4o-mini, claude-haiku) для принятия решения retrieval yes/no.

| Критерий | Эвристики | LLM-as-router |
|---|---|---|
| Latency | ✅ 0 ms | ❌ 100-300 ms |
| Стоимость | ✅ нулевая | ❌ каждый turn платный |
| Точность | ⚠️ средняя | ✅ высокая |
| Сложность | ✅ низкая | ❌ средняя |
| Предсказуемость | ✅ | ❌ |

**Выбор:** Эвристики — для MVP. LLM-as-router — как опция v2 для power-users.

### C. Always-retrieve (каждый turn)

| Критерий | Smart retrieval | Always-retrieve |
|---|---|---|
| Latency | ✅ variable | ❌ постоянный overhead |
| Стоимость OriaHS | ✅ | ❌ x3-x5 запросов |
| Покрытие | ⚠️ может пропустить | ✅ 100% |
| Усталость LLM от noise | ✅ | ❌ false positives |

**Выбор:** Smart retrieval. Always-retrieve создаёт noise и дорогу.

### D. Retrieval как обычный MCP-инструмент (LLM сама решает вызвать)

Не делать proactive retrieval — пусть LLM явно вызывает `hybrid_search` через tool-call, когда считает нужным.

| Критерий | Proactive orchestrator | Reactive tool-call |
|---|---|---|
| UX seamless | ✅ | ⚠️ LLM может забыть вызвать |
| Контроль бюджета | ✅ | ❌ LLM может вызвать 10 раз |
| Тестируемость стратегии | ✅ | ❌ |
| Свобода LLM | ⚠️ ограничена | ✅ |
| Соответствие `agents-architect.md` выводу №4 | ✅ retrieval — надстройка | ❌ retrieval — инструмент |

**Выбор:** Proactive orchestrator как дефолт + reactive tool-call как дополнение (LLM может явно вызвать `hybrid_search` для уточняющего запроса).

---

## 5. Metrics (Метрики оценки)

| Метрика | Целевое значение | Источник |
|---|---|---|
| `retrieval_decision_accuracy` (правильно ли решил retrieve/skip) | > 75% | offline eval |
| `retrieval_strategy_distribution` | balanced | self-agent |
| `retrieval_orchestrator_latency_ms` (p95) | < 100 ms (без MCP-call) | self-agent |
| `retrieval_total_latency_ms` (p95) включая MCP | < 800 ms | self-agent + OriaHS |
| `retrieval_cache_hit_ratio` | > 20% | self-agent |
| `retrieval_token_budget_utilization` | 60-90% | self-agent |
| `retrieval_degraded_count` | < 5% turns | self-agent |
| `retrieval_strategy_effectiveness` (precision@5 per strategy) | > 0.6 для каждой | offline eval |

---

## 6. Implementation Notes

### 6.1. Интерфейс `RetrievalOrchestrator`

```typescript
interface RetrievalOrchestrator {
  decide(session: SessionLog): RetrievalDecision;
  buildQuery(session: SessionLog, decision: RetrievalDecision): RetrievalQuery;
  execute(query: RetrievalQuery, mcp: MCPClient): Promise<RetrievedChunk[]>;
  merge(results: RetrievedChunk[], state: RetrievalState): RetrievedChunk[];
  budget(results: RetrievedChunk[], limit: number): RetrievedChunk[];
}

type RetrievalDecision =
  | { strategy: 'none' }
  | { strategy: 'standard' | 'topic_continuation' | 'speculative_prefetch'
      | 'explicit_recall' | 'code_lookup'; source: RetrievalSource; topK: number; rerank: boolean }
  | { strategy: 'degraded'; reason: string };
```

### 6.2. Стратегии как plug-in

```typescript
interface RetrievalStrategy {
  name: string;
  applies(session: SessionLog): boolean;
  buildQuery(session: SessionLog): RetrievalQuery;
  priority: number;
}

class TopicContinuationStrategy implements RetrievalStrategy {
  name = 'topic_continuation';
  priority = 30;

  applies(session: SessionLog): boolean {
    const lastUser = lastUserMessage(session);
    return REFERENTIAL_PATTERNS.some(p => p.test(lastUser.content));
  }

  buildQuery(session: SessionLog): RetrievalQuery {
    const entities = extractEntities(lastUserMessage(session).content);
    return {
      query: entities.join(' '),
      source: 'all',
      topK: 8,
      rerank: true,
      filters: { exclude_sessions: [currentSessionId(session)] }
    };
  }
}
```

### 6.3. Интеграция в `context-manager`

```typescript
class ContextManager {
  constructor(private retriever: RetrievalOrchestrator, private mcp: MCPClient) {}

  async window(session: SessionLog): Promise<ContextWindow> {
    const messages = this.basicWindow(session);
    const decision = this.retriever.decide(session);
    if (decision.strategy === 'none' || decision.strategy === 'degraded') {
      return { messages, systemPrompt: this.sysBuilder.build(session, decision) };
    }
    const query = this.retriever.buildQuery(session, decision);
    const results = await this.retriever.execute(query, this.mcp);
    const merged = this.retriever.merge(results, this.state);
    const budgeted = this.retriever.budget(merged, DEFAULT_BUDGET);
    return {
      messages,
      systemPrompt: this.sysBuilder.build(session, decision, budgeted),
    };
  }
}
```

### 6.4. Observability-хуки

```typescript
// каждый retrieval-вызов логируется
tracing.span('retrieval', (span) => {
  span.setAttribute('strategy', decision.strategy);
  span.setAttribute('query', query.query);
  span.setAttribute('top_k', query.topK);
  span.setAttribute('results_count', results.length);
  span.setAttribute('latency_ms', elapsed);
  span.setAttribute('cache_hit', isCacheHit);
  // ...
});
```

---

## 7. Risks (Риски)

| Риск | Вероятность | Влияние | Митигация |
|---|---|---|---|
| Эвристики retrieval-need неточны | высокая | среднее | offline-eval + тюнинг + LLM-as-router v2 |
| Latency orchestrator + MCP > 1s | средняя | высокое | speculative prefetch, cache, parallel retrieval |
| Token budget too tight → loss of context | средняя | среднее | dynamic budget от длины сессии |
| Orchestrator state divergent с OriaHS circuit breaker | низкая | среднее | polling circuit_breaker_state каждую минуту |
| Стратегии конфликтуют (multiple apply) | средняя | низкое | priority + first-match |
| Over-engineering: orchestrator для коротких сессий | средняя | низкое | early exit при `msgs.length < 20` |

---

## 8. References (Ссылки)

- `analytics/self-agent.md` §4.6 — текущий `context-manager`
- `analytics/agents-architect.md` §7 вывод №4 — автономность надстраивается над циклом
- `OriaHS/README.md` — search orchestrator внутри OriaHS (`app/search/orchestrator.py`)
- ADR-002 — OriaHS как MCP-сервер
- ADR-003 — RAG-источники
- ADR-008 — Hybrid search fusion
- ADR-009 — Reranking pipeline
- ADR-010 — Observability & eval
