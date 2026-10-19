# ADR-006: Tiered context — hot/warm/cold для session, memory, knowledge

**Status:** Proposed
**Date:** 2026-10-19
**Authors:** Vasiliy Zhila (Reider85)
**Depends on:** ADR-003, ADR-004, ADR-005
**Related:** ADR-004, ADR-010

---

## 1. Context (Контекст)

После ADR-002 (OriaHS как MCP-сервер), ADR-003 (RAG-источники), ADR-004 (retrieval-orchestrator) и ADR-005 (cross-session memory) у self-agent появляются **три параллельных источника контекста**:

1. **Active session log** — JSONL с сообщениями текущей сессии (горячая память ядра).
2. **Cross-session memory** — SQLite + Qdrant с фактами/решениями/предпочтениями (тёплая память).
3. **Knowledge base + code index** — markdown-документы и код в Qdrant (холодная память).

Текущий `context-manager` (из `analytics/self-agent.md` §4.6) рассчитан на один источник — окно из последних N сообщений. С тремя источниками возникает три проблемы:

1. **Token budget contention.** Если отдать retrieved-context из всех источников без приоритизации, легко переполнить окно. Memory-факт «пользователь не любит TypeScript» может вытеснить критичный retrieved code-snippet.
2. **Staleness gradients.** Active session всегда свежая. Memory обновляется с задержкой (extractor LLM). KB и code-index обновляются ещё медленнее (ingestion-воркер). Это нужно учитывать при ранжировании.
3. **Recency vs relevance.** Memory-fact 3-недельной давности может быть superseded свежим decision из текущей сессии. Контекст-менеджер должен понимать иерархию.

В `analytics/agents-architect.md` §5.2 (MiMoCode) упоминается решение: «инъекции памяти — с токен-бюджетом и ранжированием важности». Но деталей нет. В индустрии стандартный паттерн — **tiered storage**: hot/warm/cold с разными политиками (как в CPU-cache, как в DB-buffer-pool, как в CDN).

---

## 2. Decision (Решение)

**Вводится tiered-context-модель: три уровня контекста с раздельными token-бюджетами, приоритезацией и fallback-стратегиями.**

### 2.1. Три тира

| Tier | Источник | Latency | Token budget | Freshness | Условие включения |
|---|---|---|---|---|---|
| **Hot** | Active session-log (последние N сообщений) | < 1 ms | 50-70% от контекстного окна | всегда свежий | всегда |
| **Warm** | Cross-session memory (ADR-005) | < 100 ms | 15-25% | обновляется extractor'ом | если есть релевантная memory |
| **Cold** | Knowledge base + code index (ADR-003) | < 800 ms | 10-20% | обновляется ingest-worker'ом | если retrieval-orchestrator решил retrieve |

### 2.2. Структура системного промпта

```
┌─────────────────────────────────────────────────────────┐
│ Identity (static)                          [cacheable]  │  ← стабильный префикс для prompt-cache
│ Tools schema (semi-static)                  [cacheable]  │
├─────────────────────────────────────────────────────────┤
│ Warm: <memory>                                           │  ← 15-25% budget
│   [1] (preference, conf=0.95) User prefers tabs           │
│   [2] (decision, conf=1.0) ADR-001: MCP as primary        │
│   [3] (fact, conf=0.8) Project uses PostgreSQL 16         │
│ </memory>                                                │
├─────────────────────────────────────────────────────────┤
│ Cold: <retrieved_context>                                │  ← 10-20% budget
│   [1] (source=ADR-005.md, score=0.81) Cross-session...    │
│   [2] (path=src/memory.ts, score=0.74) class Memory...    │
│ </retrieved_context>                                     │
├─────────────────────────────────────────────────────────┤
│ Hot: <active_session>                                    │  ← 50-70% budget
│   ...последние N сообщений...                            │
│ </active_session>                                        │
├─────────────────────────────────────────────────────────┤
│ Current task / latest user message                       │  ← всегда в конце
└─────────────────────────────────────────────────────────┘
```

### 2.3. Алгоритм приоритезации

```typescript
function composeContext(
  session: SessionLog,
  memoryResults: MemoryItem[],
  kbResults: RetrievedChunk[],
  totalBudget: number,
): ComposedContext {
  // 1. Reserve budget for Hot
  const hotBudget = Math.floor(totalBudget * 0.6);
  const hot = buildHotWindow(session, hotBudget);

  // 2. Reserve budget for Warm
  const warmBudget = Math.floor(totalBudget * 0.2);
  const warm = buildWarmWindow(memoryResults, warmBudget);

  // 3. Reserve budget for Cold
  const coldBudget = totalBudget - hot.tokens - warm.tokens;
  const cold = buildColdWindow(kbResults, coldBudget);

  // 4. Reclaim unused budget (если warm/cold не нашли достаточно)
  const unused = warm.unused + cold.unused;
  if (unused > 0) {
    hot.extend(unused);  // hot может занять остаток
  }

  return { hot, warm, cold, totalTokens: hot.tokens + warm.tokens + cold.tokens };
}
```

### 2.4. Политики fallback

| Сценарий | Поведение |
|---|---|
| Memory пуста (новый проект) | Warm-бюджет → Hot |
| Retrieval ничего не нашёл | Cold-бюджет → Hot |
| Retrieval упал (circuit breaker) | Cold-бюджет → Hot, лог `retrieval_degraded` |
| Memory-retrieval вернул шум (score < 0.3) | Warm-window пустой, бюджет → Hot |
| Active session короткая (<10 msg) | Hot-бюджет сокращается до 40%, остаток → Warm+Cold |
| Total budget < 4000 tokens | только Hot (модель с маленьким окном) |

### 2.5. Приоритезация внутри тира

**Hot** — по recency (последние N), с урезанием длинных tool-results.

**Warm** — по формуле:
```
warm_score = memory_confidence * 0.5
           + recency_weight * 0.3        // exponential decay по updated_at
           + retrieval_score * 0.2       // FTS/Qdrant score
```

**Cold** — по `retrieval_score` после rerank (без доп. веса).

### 2.6. Compaction-готовность

Структура готова к v2-Compaction + Context Epoch (из `analytics/self-agent.md` §6):

- **Context Epoch** — Hot-тир получает `cacheable_prefix` (identity + tools + warm), который не меняется в пределах epoch'а.
- **Compaction** — когда Hot переполняется, старые сообщения суммаризируются и переезжают в Warm как `episodic`-memory.
- **Checkpoint-writer (v3)** — периодически делает snapshot Hot в Warm с типом `checkpoint`.

Это означает, что tiered-модель не нужно переписывать при добавлении compaction — она естественным образом расширяется.

---

## 3. Consequences (Последствия)

### Положительные

- **Предсказуемый budget.** Каждый tier имеет чёткую квоту, нет ситуаций «retrieval переполнил промпт».
- **Приоритезация по важности.** Memory-fact с confidence=1.0 не вытесняется свежим, но мало-релевантным code-snippet.
- **Prompt-cache friendly.** Warm и Cold секции — между ними и Hot есть стабильные границы; prefix (identity+tools+warm) кэшируется.
- **Готовность к v2/v3.** Compaction и Context Epoch надстраиваются без переписывания tier-модели.
- **Observability.** Можно отдельно мерять token-usage по тирам, видеть неэффективность.

### Отрицательные

- **Сложность tuning'а.** Доли budget (60/20/20) — гиперпараметры, требующие калибровки под проект.
- **Risk of starving Cold.** Если Hot и Warm агрессивны, Cold может не получать budget → retrieval бесполезен.
- **Latency на Cold-тире.** Cold-секция требует retrieval, который добавляет 500-800 ms к turn'у.
- **Compaction сложности.** Когда Hot сжимается в Warm, нужно решить: какие episodic-памяти supersede'ить.

### Нейтральные

- **Tiered-context-manager** — расширение существующего `context-manager` на ~300-400 строк.

---

## 4. Alternatives Considered (Альтернативы)

### A. Single-pool: все источники в одну очередь, top-K по score

| Критерий | Tiered | Single-pool |
|---|---|---|
| Гарантия Hot-включения | ✅ всегда | ❌ может быть вытеснен |
| Приоритезация по типу | ✅ | ❌ только по score |
| Сложность | средняя | низкая |
| Predictability | ✅ | ❌ |
| Prompt-cache stability | ✅ | ❌ |

**Выбор:** Tiered — Hot должен быть всегда. Single-pool может потерять критичный активный контекст.

### B. Fixed-ratio без dynamic reclaim

Жёстко 60/20/20, без перераспределения.

| Критерий | Dynamic reclaim | Fixed |
|---|---|---|
| Budget utilization | ✅ высокий | ❌ теряется |
| Predictability | ⚠️ | ✅ |
| Сложность | средняя | низкая |

**Выбор:** Dynamic reclaim — лучше утилизация, особенно на коротких сессиях.

### C. LLM-as-router: модель сама решает, что включить

LLM получает список доступных chunks и сама выбирает.

| Критерий | Tiered-deterministic | LLM-as-router |
|---|---|---|
| Latency | ✅ deterministic | ❌ +1 LLM-call |
| Стоимость | ✅ | ❌ каждый turn |
| Контроль budget | ✅ | ❌ LLM может перебрать |
| Гибкость | ⚠️ | ✅ |
| Предсказуемость | ✅ | ❌ |

**Выбор:** Deterministic tiered — для MVP. LLM-as-router — v2 опция для power-users.

### D. Только Hot + только Memory (без Cold)

| Критерий | Hot+Warm+Cold | Hot+Warm |
|---|---|---|
| Покрытие сценариев | ✅ | ❌ нет доступа к KB/code |
| Token budget для Hot | ✅ сбалансирован | ✅ больше для Hot |
| Использование OriaHS | ✅ полное | ⚠️ частичное |

**Выбор:** Three-tier — Cold даёт доступ к KB/code, что критично для code-агента.

---

## 5. Metrics (Метрики оценки)

| Метрика | Целевое значение | Источник |
|---|---|---|
| `context_token_usage_by_tier` | Hot 50-70%, Warm 15-25%, Cold 10-20% | self-agent |
| `context_budget_utilization` | 80-95% | self-agent |
| `context_warm_hit_ratio` (доля turns с warm-секцией) | 40-70% | self-agent |
| `context_cold_hit_ratio` | 20-50% | self-agent |
| `context_reclaim_ratio` (доля reclaimed budget) | 5-20% | self-agent |
| `prompt_cache_hit_rate` (для cacheable prefix) | > 60% | LLM provider |
| `context_compaction_rate` (доля turns, требующих compaction) | < 5% | self-agent |
| `context_overflow_count` (когда даже после reclaim не влезло) | 0 | self-agent |

---

## 6. Implementation Notes

### 6.1. Интерфейс `TieredContextManager`

```typescript
interface TieredContextManager {
  compose(session: SessionLog, opts: ComposeOpts): Promise<ComposedContext>;
}

interface ComposeOpts {
  totalBudget: number;
  hotRatio: number;     // default 0.6
  warmRatio: number;    // default 0.2
  coldRatio: number;    // default 0.2
  enableWarm: boolean;
  enableCold: boolean;
}

interface ComposedContext {
  hot: { messages: Message[]; tokens: number };
  warm: { items: MemoryItem[]; tokens: number };
  cold: { chunks: RetrievedChunk[]; tokens: number };
  totalTokens: number;
  reclaimedTokens: number;
  systemPrompt: string;
}
```

### 6.2. Recency-weight для Warm

```typescript
function recencyWeight(updatedAt: number, now: number): number {
  const days = (now - updatedAt) / (24 * 60 * 60 * 1000);
  return Math.exp(-days / 30);  // half-life ~21 days
}
```

### 6.3. Compaction (preview для v2)

```typescript
async function compactHotToWarm(hot: Message[], threshold: number): Promise<MemoryItem[]> {
  if (hot.tokens < threshold) return [];
  const summary = await llm.summarize(hot.messages);  // одна LLM-call
  const episodic: MemoryItem = {
    id: ulid(),
    type: 'episodic',
    content: summary,
    source: currentSessionId,
    created_at: Date.now(),
    confidence: 0.7,
  };
  await memoryStore.save(episodic);
  return [episodic];
}
```

### 6.4. Prompt-cache stability

```
[cacheable_prefix]
  identity
  tools schema
  warm-секция  ← обновляется реже, чем hot
[/cacheable_prefix]
hot-секция
current task
```

Warm обновляется при изменении memory (extractor сработал), Hot — каждый turn. Cache-hit на prefix ~60-80% при типичных сессиях.

### 6.5. Config

```yaml
# ~/.self-agent/context.yml
budget:
  total_tokens: 32000
  hot_ratio: 0.6
  warm_ratio: 0.2
  cold_ratio: 0.2
warm:
  enabled: true
  max_items: 8
  min_confidence: 0.5
  recency_half_life_days: 21
cold:
  enabled: true
  max_chunks: 5
  min_score: 0.3
reclaim:
  enabled: true
  min_reclaimable_tokens: 500
compaction:
  enabled: false  # v2
  threshold_tokens: 24000
```

---

## 7. Risks (Риски)

| Риск | Вероятность | Влияние | Митигация |
|---|---|---|---|
| Tuning гиперпараметров под каждый проект | высокая | среднее | defaults + per-project overrides |
| Cold-starvation при агрессивном Hot | средняя | среднее | минимальный Cold-budget 10% |
| Warm-staleness: устаревшая memory вводит в заблуждение | средняя | высокое | recency-weight + supersede-logic |
| Prompt-cache instability при частом изменении Warm | средняя | среднее | Warm-batch update (не чаще раза в 5 turn'ов) |
| Compaction-bugs (когда v2 добавится) | средняя | высокое | ADR отдельно + thorough offline-eval |
| Token-counting inaccuracy (tiktoken vs actual) | высокая | низкое | safety margin 5% |

---

## 8. References (Ссылки)

- `analytics/self-agent.md` §4.6 — текущий `context-manager`
- `analytics/self-agent.md` §6 — Compaction + Context Epoch отложены на v2
- `analytics/agents-architect.md` §5.2 — MiMo tiered-memory + checkpoint-writer
- `analytics/agents-architect.md` §2.2 — OpenCode Context Epoch
- ADR-003 — RAG-источники
- ADR-004 — Retrieval-orchestrator
- ADR-005 — Cross-session memory
- ADR-010 — Observability & eval для retrieval path
- Prompt caching (Anthropic): https://docs.anthropic.com/en/docs/build-with-claude/prompt-caching
