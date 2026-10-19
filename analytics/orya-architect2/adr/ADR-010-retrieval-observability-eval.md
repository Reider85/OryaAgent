# ADR-010: Observability и offline-eval для retrieval path

**Status:** Proposed
**Date:** 2026-10-19
**Authors:** Vasiliy Zhila (Reider85)
**Depends on:** ADR-002, ADR-003, ADR-004, ADR-005
**Related:** ADR-008, ADR-009

---

## 1. Context (Контекст)

OriaHS имеет зрелую observability-стек:
- Prometheus + Grafana (8 дашбордов);
- критические метрики: `reranker_latency_ms`, `circuit_breaker_state`, `eval_recall_at_10`, `eval_ndcg_at_10`, `search_degraded_total`, `qdrant_pushdown_rate_total`, `outbox_throttled_total`;
- nightly offline-eval (C-07) с замерами recall@10 / ndcg@10 на эталонном корпусе;
- DoD Critical (C-14) + NFR.

Параллельно self-agent (MVP) observability не имеет вовсе — `analytics/self-agent.md` §6 откладывает это на v2+ (`Hooks`, `Sandbox` и т.д.). Но после ADR-001..009 появляется сложный **распределённый retrieval-path**:

```
agent-loop
  └─ context-manager (tiered, ADR-006)
      └─ retrieval-orchestrator (ADR-004)
          ├─ capability-registry (ADR-007)
          ├─ rerank-policy (ADR-009)
          ├─ MCPClient (ADR-001)
          │   └─ oriahs-mcp (ADR-002)
          │       ├─ lexical (PG)
          │       ├─ vector (Qdrant)
          │       ├─ fusion
          │       └─ rerank (cross-encoder, ADR-009)
          ├─ memory SQLite (ADR-005)
          └─ rerank-cache
```

Без observability этого пути невозможно:
1. **Дебаггить «агент не нашёл релевантный контекст».** Где случился сбой — в retrieval-orchestrator? В MCP-вызове? В rerank-circuit-breaker? В tiered-context-budget?
2. **Тюнить гиперпараметры.** Какие `fusion_weights` лучше? Какой `top_k_pre` оптимален? Без метрик — гадание.
3. **Отлавливать regressions.** После обновления OriaHS или self-agent — не ухудшился ли recall@10?
4. **Аргументировать архитектурные решения.** Без оффлайн-eval невозможно доказать, что ADR-008 (hybrid default) лучше ADR-008-alt-A (vector-only).

Также есть отдельная проблема — **распределённый tracing**: один retrieval-call проходит через 4-5 сервисов, нужен trace_id, чтобы связать метрики.

---

## 2. Decision (Решение)

**Вводится единый observability-стек для retrieval path: metrics + structured logs + distributed tracing + offline-eval, с переиспользованием инфраструктуры OriaHS.**

### 2.1. Метрики (self-agent side)

Каждый компонент retrieval-path экспортирует метрики в `/metrics` endpoint (Prometheus-format):

```prometheus
# retrieval-orchestrator
retrieval_decisions_total{strategy="standard"} 1245
retrieval_decisions_total{strategy="topic_continuation"} 89
retrieval_decisions_total{strategy="degraded"} 3

retrieval_calls_total{result="success"} 1334
retrieval_calls_total{result="empty"} 78
retrieval_calls_total{result="error"} 12

retrieval_latency_ms{quantile="0.5"} 312
retrieval_latency_ms{quantile="0.95"} 782
retrieval_latency_ms{quantile="0.99"} 1245

# capability-registry
capability_visible_tools_per_turn{quantile="0.5"} 11
capability_on_demand_activations_total{reason="content_pattern"} 45
capability_false_activations_total 12

# tiered-context
context_token_usage_by_tier{tier="hot"} 18900
context_token_usage_by_tier{tier="warm"} 4200
context_token_usage_by_tier{tier="cold"} 3100
context_budget_utilization 0.82
context_reclaim_ratio 0.12

# rerank-policy
rerank_skipped_total{reason="exact_match"} 234
rerank_skipped_total{reason="circuit_breaker_open"} 8
rerank_skipped_total{reason="speculative_prefetch"} 56
rerank_cache_hit_ratio 0.23

# MCPClient (per server)
mcp_tool_call_latency_ms{server="oriahs-mcp",quantile="0.95"} 412
mcp_tool_call_errors_total{server="oriahs-mcp"} 3
mcp_server_uptime{server="oriahs-mcp"} 0.998

# memory (ADR-005)
memory_items_total{type="fact"} 234
memory_items_total{type="episodic"} 1567
memory_extraction_success_rate 0.96
memory_retrieval_latency_ms{quantile="0.95"} 89

# fallback
retrieval_fallback_total{from="hybrid_rerank",to="hybrid_no_rerank"} 8
retrieval_fallback_total{from="hybrid_no_rerank",to="lexical_only"} 2
retrieval_degraded_count 3
```

### 2.2. Structured logs (JSONL)

Каждый retrieval-event логируется в `~/.self-agent/logs/retrieval.jsonl`:

```jsonl
{"ts":"2026-10-19T10:00:00.123Z","trace_id":"abc123","span_id":"def456","event":"retrieval_start","session":"sess_xyz","strategy":"standard","query_hash":"q1h2"}
{"ts":"2026-10-19T10:00:00.234Z","trace_id":"abc123","span_id":"ghi789","event":"mcp_call_start","server":"oriahs-mcp","tool":"hybrid_search"}
{"ts":"2026-10-19T10:00:00.876Z","trace_id":"abc123","span_id":"ghi789","event":"mcp_call_end","latency_ms":642,"result_count":5}
{"ts":"2026-10-19T10:00:00.901Z","trace_id":"abc123","span_id":"jkl012","event":"rerank_applied","top_k_pre":15,"top_k_post":5,"rerank_latency_ms":187}
{"ts":"2026-10-19T10:00:00.912Z","trace_id":"abc123","span_id":"def456","event":"retrieval_end","total_latency_ms":789,"results_used":true}
```

Логи используются для:
- debug конкретного сбоя (по `trace_id`);
- replay сессии (по `session_id`);
- offline-eval (по `query_hash`).

### 2.3. Distributed tracing (OpenTelemetry)

Каждый retrieval-span имеет `trace_id`, передаваемый через MCP-headers:

```
MCP-Trace-Id: abc123
MCP-Span-Id: ghi789
MCP-Parent-Span-Id: def456
```

OriaHS принимает эти заголовки и включает в свои span'ы. В итоге в Jaeger/Tempo видна единая trace:

```
[agent-loop] retrieval
  ├─ [retrieval-orchestrator] decide
  ├─ [retrieval-orchestrator] buildQuery
  ├─ [MCPClient] callTool(hybrid_search)
  │   └─ [oriahs-mcp] handle
  │       ├─ [OriaHS] lexical_search (PG)
  │       ├─ [OriaHS] vector_search (Qdrant)
  │       ├─ [OriaHS] fusion
  │       └─ [OriaHS] rerank (cross-encoder)
  └─ [retrieval-orchestrator] merge + budget
```

### 2.4. Offline-eval (расширение C-07 из OriaHS)

К существующему nightly-eval OriaHS добавляются **agent-specific** datasets:

#### 2.4.1. `eval/datasets/agent_session_recall.jsonl`

50 сценариев с past-session-retrieval:

```jsonl
{"id":"sr001","query":"помнишь, мы обсуждали memory-tier?","expected_session_id":"sess_2026_09_15","expected_keyword_match":["memory","tier","hot","warm","cold"],"min_recall_at_10":0.8}
{"id":"sr002","query":"как мы решили проблему с circuit breaker?","expected_session_id":"sess_2026_09_22","expected_keyword_match":["circuit","breaker","rerank"],"min_recall_at_10":0.7}
```

#### 2.4.2. `eval/datasets/agent_kb_recall.jsonl`

30 сценариев с ADR/KB-retrieval:

```jsonl
{"id":"kb001","query":"почему мы выбрали MCP?","expected_doc":"ADR-001-mcp-as-primary-tool-contract.md","expected_keyword_match":["MCP","contract","tool"],"min_recall_at_10":0.9}
{"id":"kb002","query":"как устроена memory?","expected_doc":"ADR-005-cross-session-memory.md","expected_keyword_match":["SQLite","Qdrant","FTS5"],"min_recall_at_10":0.9}
```

#### 2.4.3. `eval/datasets/agent_code_recall.jsonl`

30 сценариев с code-lookup:

```jsonl
{"id":"cr001","query":"getUserById","expected_file":"src/api/users.ts","expected_symbol":"getUserById","min_recall_at_10":1.0,"mode_hint":"lexical"}
{"id":"cr002","query":"function that handles memory retrieval","expected_file":"src/agent/retrieval.ts","expected_symbol":"retrieveMemory","min_recall_at_10":0.8,"mode_hint":"hybrid"}
```

#### 2.4.4. `eval/datasets/agent_memory_recall.jsonl`

20 сценариев с cross-session memory:

```jsonl
{"id":"mr001","query":"what does the user prefer?","expected_memory_type":"preference","expected_keyword_match":["tabs","spaces"],"min_recall_at_10":0.9}
{"id":"mr002","query":"what did we decide about retrieval?","expected_memory_type":"decision","expected_keyword_match":["retrieval","orchestrator"],"min_recall_at_10":0.8}
```

### 2.5. Online-eval (production sampling)

5% production-retrieval-calls логируются с **post-hoc relevance-judgment**:
- После ответа LLM пользователь видит subtle-промпт: «Помог ли retrieved-контекст?» (yes/no/skip).
- Или: LLM-self-judge — отдельная мелкая LLM-оценка «использовала ли я retrieved-контекст?».

Online-metrics:
- `retrieval_helpfulness_rate` (доля yes) — target > 60%;
- `retrieval_used_in_answer_rate` (LLM-self-judge) — target > 50%.

### 2.6. DoD-retrieval (Definition of Done для retrieval path)

Чек-лист готовности retrieval-path к релизу:

- [ ] Все компоненты retrieval-path экспортируют метрики.
- [ ] `retrieval_latency_ms` p95 < 800 ms.
- [ ] `retrieval_decisions_total` covers все 7 стратегий из ADR-004.
- [ ] Offline-eval `eval_recall_at_10` > 0.85 по всем 4 датасетам.
- [ ] Distributed tracing работает end-to-end (agent → MCP → OriaHS).
- [ ] Fallback-chain покрыта тестами (3 уровня: rerank-skip, circuit-breaker, total-fail).
- [ ] Audit-log всех MCP-вызовов (для security).
- [ ] Grafana-dashboard «Self-agent retrieval» добавлен (наследует 8 дашбордов OriaHS + 4 новых).

### 2.7. Grafana-дашборды (4 новых поверх 8 OriaHS)

1. **Self-agent Retrieval Overview** — latency p50/p95/p99, decisions distribution, fallback rate.
2. **Tiered Context Budget** — token usage by tier, reclaim ratio, overflow count.
3. **Memory Health** — items by type, extraction success, retrieval recall.
4. **MCP Servers** — per-server latency, error-rate, uptime, tool-call volume.

---

## 3. Consequences (Последствия)

### Положительные

- **Использование инфраструктуры OriaHS.** Prometheus + Grafana + offline-eval уже работают.
- **Дебаггинг distributed-path.** trace_id связывает все компоненты.
- **Data-driven tuning.** Метрики дают объективную базу для гиперпараметров.
- **Regression detection.** Nightly-eval отлавливает ухудшения.
- **Open-source credibility.** Observability — критичный пункт для контрибьюторов.

### Отрицательные

- **Дополнительный код.** ~400-500 строк metrics+logging.
- **Performance overhead.** Метрики и tracing добавляют 5-10% overhead.
- **Storage cost.** Structured-logs растут (~1-10 MB/day для типичного пользователя).
- **Eval-maintenance.** 130 сценариев в 4 датасетах нужно поддерживать актуальными.

### Нейтральные

- **OpenTelemetry SDK** — стандартная зависимость, ~2MB в bundle.

---

## 4. Alternatives Considered (Альтернативы)

### A. Только structured logs (без metrics + tracing)

| Критерий | Full observability | Logs-only |
|---|---|---|
| Real-time alerting | ✅ | ❌ |
| Distributed tracing | ✅ | ❌ |
| Grafana-визуализация | ✅ | ⚠️ Loki |
| Cost | ⚠️ | ✅ |
| Open-source готовность | ✅ | ⚠️ |

**Выбор:** Full observability — Prometheus+Grafana уже в OriaHS.

### B. Только OriaHS-метрики (без self-agent-side)

| Критерий | Full (self-agent + OriaHS) | OriaHS-only |
|---|---|---|
| Видимость tiered-context | ✅ | ❌ |
| Видимость retrieval-decisions | ✅ | ❌ |
| Видимость MCPClient | ✅ | ❌ |
| Дебаггинг end-to-end | ✅ | ❌ |

**Выбор:** Full — self-agent-side метрики критичны для дебаггинга.

### C. Datadog / NewRelic (managed observability)

| Критерий | Prometheus+Grafana (self-hosted) | Managed |
|---|---|---|
| Privacy | ✅ | ❌ |
| Cost (open-source) | ✅ | ❌ |
| Использование OriaHS-стека | ✅ | ❌ |
| Setup-усилия | средние | низкие |

**Выбор:** Self-hosted — приватность и переиспользование.

### D. Eval только на production (без offline)

| Критерий | Offline + online | Production-only |
|---|---|---|
| Regression detection | ✅ | ❌ |
| A/B-test новых стратегий | ✅ | ⚠️ |
| Privacy | ✅ (synthetic data) | ⚠️ |
| Coverage edge-cases | ✅ | ❌ |

**Выбор:** Offline (nightly, synthetic) + online (production sampling) — оба нужны.

### E. LLM-as-judge для retrieval-quality (без offline datasets)

Использовать LLM для оценки retrieval-качества на каждом запросе.

| Критерий | Offline datasets + LLM-judge | LLM-as-judge only |
|---|---|---|
| Cost | ✅ (offline) | ❌ каждый retrieval |
| Determinism | ✅ | ❌ |
| Coverage edge-cases | ✅ curated | ⚠️ |
| Recall@10 measurable | ✅ | ❌ |

**Выбор:** Offline datasets — quantitative metrics. LLM-as-judge — опциональное дополнение для qualitative analysis.

---

## 5. Metrics (Метрики оценки — meta-level)

Эти метрики измеряют сам observability-стек:

| Метрика | Целевое значение | Источник |
|---|---|---|
| `observability_overhead_pct` (overhead на retrieval-latency) | < 10% | benchmark |
| `metrics_scrape_success_rate` | > 99% | Prometheus |
| `trace_completeness` (доля retrieval-calls с full trace) | > 95% | Jaeger |
| `offline_eval_pass_rate` (по 4 датасетам) | 100% | nightly job |
| `online_eval_sample_rate` | 5% production | self-agent |
| `grafana_dashboard_uptime` | > 99.5% | Grafana |
| `structured_log_storage_mb_per_day` | < 50 MB | log-rotate |
| `alert_to_resolution_time_ms` (p95) | < 5 min | oncall |

---

## 6. Implementation Notes

### 6.1. OpenTelemetry-setup

```typescript
// self-agent/core/observability/tracing.ts
import { trace, context, SpanStatusCode } from '@opentelemetry/api';
import { OTLPTraceExporter } from '@opentelemetry/exporter-trace-otlp-http';

const tracer = trace.getTracer('self-agent');

export async function tracedRetrieval<T>(
  name: string,
  fn: (span: Span) => Promise<T>,
): Promise<T> {
  return tracer.startActiveSpan(name, async (span) => {
    try {
      const result = await fn(span);
      span.setStatus({ code: SpanStatusCode.OK });
      return result;
    } catch (e) {
      span.setStatus({ code: SpanStatusCode.ERROR, message: e.message });
      throw e;
    } finally {
      span.end();
    }
  });
}
```

### 6.2. MCP-headers propagation

```typescript
// MCPClient автоматически инжектит trace-headers
class MCPClient {
  async callTool(name: string, input: unknown): Promise<ToolResult> {
    const span = trace.getActiveSpan();
    const headers: Record<string, string> = {};

    if (span) {
      const ctx = trace.setSpan(context.active(), span);
      const carrier: Record<string, string> = {};
      propagation.inject(ctx, carrier);
      Object.assign(headers, carrier);
    }

    return this.transport.call(name, input, headers);
  }
}
```

### 6.3. Prometheus-exporter

```typescript
// self-agent/core/observability/metrics.ts
import { Counter, Histogram, Gauge, register } from 'prom-client';

export const retrievalDecisions = new Counter({
  name: 'retrieval_decisions_total',
  help: 'Total retrieval decisions by strategy',
  labelNames: ['strategy'],
});

export const retrievalLatency = new Histogram({
  name: 'retrieval_latency_ms',
  help: 'Retrieval latency in milliseconds',
  buckets: [50, 100, 200, 400, 800, 1500, 3000],
});

export const tieredContextTokens = new Gauge({
  name: 'context_token_usage_by_tier',
  help: 'Token usage by tier',
  labelNames: ['tier'],
});

// /metrics endpoint
app.get('/metrics', async (req, res) => {
  res.set('Content-Type', register.contentType);
  res.end(await register.metrics());
});
```

### 6.4. Nightly-eval job (расширение C-07)

```python
# eval/nightly_agent_eval.py
import asyncio, json
from datasets import load_dataset
from mcp_client import MCPClient

async def run_agent_eval():
    mcp = MCPClient(...)
    await mcp.start(...)

    results = {}
    for dataset_name in ['agent_session_recall', 'agent_kb_recall',
                         'agent_code_recall', 'agent_memory_recall']:
        ds = load_dataset(f'eval/datasets/{dataset_name}.jsonl')
        metrics = {'recall_at_10': [], 'ndcg_at_10': []}

        for item in ds:
            res = await mcp.call_tool('hybrid_search', {
                'query': item['query'],
                'top_k': 10,
                'rerank': True,
                'mode': item.get('mode_hint', 'hybrid'),
            })
            score = score_result(res, item)
            metrics['recall_at_10'].append(score.recall)
            metrics['ndcg_at_10'].append(score.ndcg)

        results[dataset_name] = {
            'recall_at_10_avg': sum(metrics['recall_at_10']) / len(metrics['recall_at_10']),
            'ndcg_at_10_avg': sum(metrics['ndcg_at_10']) / len(metrics['ndcg_at_10']),
        }

    # write to Prometheus pushgateway
    push_to_gateway('prometheus-pushgateway:9091', job='nightly-agent-eval', registry=registry)

    return results
```

### 6.5. Grafana dashboard (JSON-фрагмент)

```json
{
  "title": "Self-agent Retrieval Overview",
  "panels": [
    {
      "title": "Retrieval latency (p50/p95/p99)",
      "targets": [{"expr": "histogram_quantile(0.50, sum(rate(retrieval_latency_ms_bucket[5m])) by (le))"}]
    },
    {
      "title": "Decisions distribution",
      "targets": [{"expr": "sum(rate(retrieval_decisions_total[5m])) by (strategy)"}]
    },
    {
      "title": "Fallback rate",
      "targets": [{"expr": "sum(rate(retrieval_fallback_total[5m])) by (from, to)"}]
    },
    {
      "title": "Offline-eval recall@10 (per dataset)",
      "targets": [{"expr": "nightly_agent_eval_recall_at_10_avg"}]
    }
  ]
}
```

### 6.6. Alerting rules

```yaml
# monitoring/prometheus/rules/self_agent_retrieval.yml
groups:
  - name: self_agent_retrieval
    rules:
      - alert: RetrievalLatencyHigh
        expr: histogram_quantile(0.95, sum(rate(retrieval_latency_ms_bucket[5m])) by (le)) > 1500
        for: 5m
        annotations:
          summary: "Retrieval p95 latency > 1.5s"

      - alert: RetrievalErrorRateHigh
        expr: sum(rate(retrieval_calls_total{result="error"}[5m])) / sum(rate(retrieval_calls_total[5m])) > 0.05
        for: 10m
        annotations:
          summary: "Retrieval error rate > 5%"

      - alert: EvalRecallDrop
        expr: nightly_agent_eval_recall_at_10_avg < 0.80
        for: 1h
        annotations:
          summary: "Offline-eval recall@10 dropped below 0.80"

      - alert: CircuitBreakerStuck
        expr: rerank_circuit_breaker_state == 1
        for: 30m
        annotations:
          summary: "Reranker circuit breaker open for >30min"
```

---

## 7. Risks (Риски)

| Риск | Вероятность | Влияние | Митигация |
|---|---|---|---|
| Observability-overhead убивает latency | средняя | среднее | sampling, async-export |
| Logs растут бесконечно | высокая | низкое | log-rotate + retention policy |
| Trace-context loss на MCP boundary | средняя | среднее | W3C TraceContext headers |
| Eval datasets устаревают | высокая | среднее | periodic review + auto-update |
| Alert fatigue | средняя | среднее | smart alerting (multi-condition) |
| Privacy: logs содержат user-content | высокая | критическое | PII-redaction в log-processor |

---

## 8. References (Ссылки)

- `OriaHS/README.md` — observability-стек (Prometheus, Grafana, 8 дашбордов, critical metrics)
- `OriaHS/analitics/ARCHITECT.md` — детальная observability-архитектура
- `OriaHS/grafana/provisioning/` — существующие дашборды
- `analytics/self-agent.md` §6 — observability отложена на v2
- ADR-002 — OriaHS как MCP-сервер (источник baseline-метрик)
- ADR-004 — Retrieval-orchestrator (метрики decisions)
- ADR-006 — Tiered context (метрики token-usage)
- ADR-009 — Reranking pipeline (метрики circuit breaker)
- OpenTelemetry: https://opentelemetry.io
- Prometheus client_nodejs: https://github.com/siimon/prom-client
