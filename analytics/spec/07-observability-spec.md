# Спецификация Observability

**Документ:** 07-observability-spec
**Дата:** 20 октября 2026
**Статус:** Draft v0.1
**Связанные документы:** [01-module-contracts.md](01-module-contracts.md), [02-llm-adapter-spec.md](02-llm-adapter-spec.md), [enterprise-features.md](enterprise-features.md)

---

## 0. Назначение

Production-grade LLM-агент должен быть observable: что происходит внутри, сколько стоит, где bottlenecks, какие ошибки. Этот документ фиксирует:

- Метрики: что измеряем, как часто, куда отгружаем
- Структурированные логи: формат, retention, filtering
- Tracing: spans, distributed tracing для multi-call scenarios
- Cost tracking: per-session, per-provider, per-tool
- Alerting: на что реагировать автоматически
- Privacy: что логируется, что нет (sensitive data redaction)

Без observability — production debugging невозможен, cost optimization — гадание, security incident response — слепой.

## 1. Принципы

### 1.1. Observability by default

Все метрики собираются без opt-in. Пользователь может отключить через config, но default — on. Это противоположность «pay-as-you-go observability» — мы хотим, чтобы каждый пользователь по умолчанию видел, что происходит.

### 1.2. Local-first

Метрики и логи хранятся локально (`~/.orya/`). Отгрузка во внешние системы (OTel, Prometheus, Datadog) — opt-in. Пользователь контролирует свои данные.

### 1.3. Structured everything

- Логи — JSON, не free text
- Метрики — labeled (Prometheus-style), не positional
- Traces — OpenTelemetry-compatible spans

### 1.4. Privacy-preserving

- Sensitive patterns (API keys, tokens) — redacted перед логированием
- Tool inputs — only `input_hash`, не полный input (для audit-log)
- User content — не отгружается во external systems по умолчанию

### 1.5. Performance-aware

- Observability overhead — <5% latency
- Async logging (через `aiologger` или `structlog` с queue)
- Sampling для high-frequency events (LLM token streams)

## 2. Метрики

### 2.1. Metric types

| Type | Описание | Пример |
|---|---|---|
| **Counter** | Монотонно растущее значение | `orya_llm_tokens_total{provider="anthropic",kind="input"} 145823` |
| **Gauge** | Текущее значение, может расти и падать | `orya_session_active_count 3` |
| **Histogram** | Распределение значений | `orya_llm_request_duration_seconds_bucket{le="5"} 47` |
| **Summary** | Quantiles (p50, p90, p99) | `orya_tool_execution_duration_seconds{quantile="0.99"} 2.3` |

### 2.2. Standard metrics

#### LLM-провайдер

```
orya_llm_tokens_total{provider, model, kind}
    # kind: input | output | cache_read | cache_write
    # type: counter

orya_llm_cost_usd_total{provider, model}
    # type: counter

orya_llm_request_duration_seconds{provider, model, outcome}
    # outcome: success | error | timeout
    # type: histogram, buckets: 0.1, 0.5, 1, 5, 10, 30, 60, 120

orya_llm_request_total{provider, model, outcome}
    # type: counter

orya_llm_errors_total{provider, error_kind}
    # error_kind: auth_failed | rate_limited | server_error | network_error | ...
    # type: counter

orya_llm_cache_hit_ratio{provider, model}
    # type: gauge, 0.0 - 1.0
    # = cache_read_tokens / (cache_read_tokens + input_tokens)
```

#### Agent loop

```
orya_loop_iterations_total{session_id}
    # type: counter

orya_loop_tool_calls_total{tool_name}
    # type: counter

orya_loop_session_duration_seconds{session_id}
    # type: gauge

orya_loop_active_count
    # type: gauge, current number of active agent loops

orya_loop_iterations_limit_reached_total
    # type: counter
```

#### Tools

```
orya_tool_execution_total{tool, outcome}
    # outcome: success | error | denied | aborted | timeout
    # type: counter

orya_tool_execution_duration_seconds{tool}
    # type: histogram, buckets: 0.01, 0.05, 0.1, 0.5, 1, 5, 30, 300

orya_tool_errors_total{tool, error_kind}
    # type: counter

orya_tool_permission_ask_total{tool, user_response}
    # user_response: yes | no | always
    # type: counter

orya_tool_bash_exit_code_total{exit_code}
    # type: counter
```

#### Sessions

```
orya_session_active_count
    # type: gauge

orya_session_events_total{session_id, kind}
    # type: counter

orya_session_size_bytes{session_id}
    # type: gauge

orya_session_duration_seconds{session_id}
    # type: gauge

orya_session_cost_usd{session_id}
    # type: gauge

orya_session_tokens_total{session_id, kind}
    # type: counter
```

#### Context manager

```
orya_context_window_tokens{session_id}
    # type: gauge, current tokens in window

orya_context_window_limit{model}
    # type: gauge, max tokens for model

orya_context_truncation_total{session_id}
    # type: counter
```

#### Performance

```
orya_cold_start_duration_seconds
    # type: histogram, time from process start to first prompt

orya_llm_token_to_render_latency_ms
    # type: histogram, time from LLM token received to rendered in TUI

orya_tool_call_to_execution_latency_ms
    # type: histogram, time from LLM tool_call_end to tool.execute start
```

#### File system

```
orya_fs_files_accessed_total{tool}
    # type: counter

orya_fs_bytes_read_total{tool}
    # type: counter

orya_fs_bytes_written_total{tool}
    # type: counter
```

### 2.3. Custom metrics

Пользователь может добавлять свои metrics через custom hooks (v2) или через `~/.orya/metrics.yml`:

```yaml
custom_metrics:
  - name: my_team_deploys_total
    description: "Number of deployments triggered by OryaAgent"
    type: counter
    labels: [environment]
```

В MVP — только standard metrics. Custom metrics — v2.

### 2.4. Storage

Локально — в `~/.orya/metrics.jsonl` (append-only JSON Lines):

```json
{"ts":"2026-10-20T14:32:01Z","metric":"orya_llm_tokens_total","labels":{"provider":"anthropic","model":"claude-3-5-sonnet","kind":"input"},"value":145823}
{"ts":"2026-10-20T14:32:01Z","metric":"orya_llm_cost_usd_total","labels":{"provider":"anthropic","model":"claude-3-5-sonnet"},"value":0.015923}
```

Rotation: при 50 MB → rotate to `.1`, `.2`, ... до 5 files (250 MB max).

### 2.5. Export

Через config:

```yaml
observability:
  metrics:
    enabled: true  # default
    export_to:
      - kind: otel
        endpoint: http://otel-collector:4317
        interval: 60s
      - kind: prometheus
        endpoint: http://prometheus-push:9091/metrics/job/orya
        interval: 30s
      - kind: datadog
        api_key_env: DATADOG_API_KEY
        site: datadoghq.com
        interval: 60s
```

В MVP — local-only. External exporters — v0.2.0+.

### 2.6. Visualisation

`orya stats` команда — выводит aggregated metrics в TUI:

```
$ orya stats

OryaAgent Statistics (last 30 days)
========================================

Sessions: 47
Total cost: $12.45
Total tokens: 4.2M (input), 287k (output), 3.8M (cache_read)

By provider:
  anthropic (claude-3-5-sonnet): 38 sessions, $9.80, 3.5M tokens
  openai (gpt-4o): 9 sessions, $2.65, 0.7M tokens

By tool:
  bash: 234 calls (avg 250ms)
  read: 412 calls (avg 12ms)
  write: 89 calls (avg 35ms)
  edit: 156 calls (avg 28ms)
  grep: 78 calls (avg 145ms)

Errors: 3 (1 auth_failed, 2 network_error)

Top sessions by cost:
  1. 20261018-refactor-auth ($2.10)
  2. 20261019-debug-tests ($1.80)
  3. 20261020-add-endpoint ($1.20)
```

TUI dashboard — `orya stats live` — обновляется в реальном времени.

## 3. Структурированные логи

### 3.1. Format

JSON Lines, через `structlog`:

```json
{"ts":"2026-10-20T14:32:01.123456Z","level":"info","event":"session_started","session_id":"20261020-143201-a3f2b9c1","provider":"anthropic","model":"claude-3-5-sonnet-20241022","working_dir":"/home/user/project"}
{"ts":"2026-10-20T14:32:05.456789Z","level":"info","event":"llm_call_started","session_id":"20261020-143201-a3f2b9c1","provider":"anthropic","model":"claude-3-5-sonnet-20241022","input_tokens_estimated":12500}
{"ts":"2026-10-20T14:32:09.789012Z","level":"info","event":"llm_call_completed","session_id":"20261020-143201-a3f2b9c1","provider":"anthropic","duration_ms":4231,"input_tokens":12500,"output_tokens":842,"cost_usd":0.015923}
{"ts":"2026-10-20T14:32:10.012345Z","level":"info","event":"tool_call_started","session_id":"20261020-143201-a3f2b9c1","call_id":"abc123","tool":"bash"}
{"ts":"2026-10-20T14:32:10.045678Z","level":"info","event":"permission_decision","call_id":"abc123","tool":"bash","decision":"ask","user_response":"yes","duration_ms":2340}
{"ts":"2026-10-20T14:32:10.578901Z","level":"info","event":"tool_call_completed","call_id":"abc123","tool":"bash","outcome":"success","duration_ms":42,"exit_code":0}
```

### 3.2. Levels

| Level | Использование |
|---|---|
| `debug` | Detailed internal state, hot-path tracing |
| `info` | Normal operation events |
| `warning` | Unexpected but recoverable (e.g., partial write discarded) |
| `error` | Operation failed, but agent continues |
| `critical` | Agent cannot continue (e.g., session-log write failed) |

### 3.3. Events

| Event | Level | Когда | Context |
|---|---|---|---|
| `session_started` | info | New session | session_id, provider, model, working_dir |
| `session_resumed` | info | Resume | session_id, resumed_from_seq |
| `session_closed` | info | Close | session_id, duration, cost |
| `session_aborted` | warning | Ctrl+C / signal | session_id, reason |
| `llm_call_started` | debug | Before LLM API call | session_id, provider, model, input_tokens_estimated |
| `llm_call_completed` | info | After LLM response | session_id, provider, duration_ms, tokens, cost |
| `llm_call_error` | error | LLM failure | session_id, provider, error_kind, message |
| `tool_call_started` | debug | Before tool execute | session_id, call_id, tool |
| `tool_call_completed` | info | After tool execute | call_id, tool, outcome, duration_ms |
| `permission_decision` | info | Permission asked/granted | call_id, tool, decision, user_response |
| `context_truncated` | warning | Context window exceeded | session_id, tokens_before, tokens_after |
| `compaction_triggered` | info | v2: compaction | session_id, strategy, tokens_before/after |
| `config_changed` | info | `orya config set` | key, old_value, new_value |
| `sensitive_access` | warning | Sensitive file accessed | path, call_id, approved_by |
| `prompt_injection_suspected` | warning | v2: heuristic detected | call_id, reason |
| `audit_log_rotated` | info | Audit log rotation | old_size, new_file |
| `error_unexpected` | error | Unhandled exception | exception, traceback (filtered) |

### 3.4. Sensitive data redaction

Перед логированием каждое поле проходит через redaction filter:

```python
SENSITIVE_PATTERNS = [
    (r"sk-[a-zA-Z0-9]{20,}", "<REDACTED:openai_key>"),
    (r"sk-ant-[a-zA-Z0-9]{20,}", "<REDACTED:anthropic_key>"),
    (r"AKIA[A-Z0-9]{16}", "<REDACTED:aws_key>"),
    (r"ghp_[a-zA-Z0-9]{36}", "<REDACTED:github_token>"),
    # ... extensibile
]


def redact(value: Any) -> Any:
    if isinstance(value, str):
        for pattern, replacement in SENSITIVE_PATTERNS:
            value = re.sub(pattern, replacement, value)
    elif isinstance(value, dict):
        return {k: redact(v) for k, v in value.items()}
    elif isinstance(value, list):
        return [redact(v) for v in value]
    return value
```

Configuration в `~/.orya/sensitive.yml` — пользователь может добавить свои patterns (например, internal API keys).

### 3.5. Storage

`~/.orya/logs/`:
- `orya.jsonl` — main log (info level и выше)
- `orya.debug.jsonl` — debug level (только если `log_level=debug`)
- `audit.jsonl` — security-relevant events (см. [05-security-model.md](05-security-model.md))
- `errors.jsonl` — error level и выше, для quick filtering

Rotation:
- `orya.jsonl` — 100 MB → rotate, keep 10 files (1 GB max)
- `orya.debug.jsonl` — 50 MB → rotate, keep 3 files (150 MB max)
- `audit.jsonl` — 100 MB → rotate, keep 10 files (1 GB max), затем archive в `.zst`
- `errors.jsonl` — 10 MB → rotate, keep 20 files (200 MB max)

### 3.6. Filtering and queries

```bash
# Просмотр логов
orya logs show --since="2 hours ago"
orya logs show --level=error
orya logs show --event=llm_call_completed --session=abc123

# Grep через логи
orya logs grep "permission_decision" --since="today"

# Экспорт
orya logs export --from=2026-10-01 --to=2026-10-20 --format=json > logs.json
```

## 4. Tracing

### 4.1. OpenTelemetry-compatible

OryaAgent генерирует OTel spans для каждого significant operation. Tracing — opt-in (default off для MVP, on для enterprise).

```python
# Пример span tree
session_run (span)
├── llm_call #1 (span)
│   ├── http_request (span)
│   └── http_response_parsing (span)
├── tool_call read (span)
│   └── file_read (span)
├── permission_decision (span)
├── tool_call bash (span)
│   ├── subprocess_start (span)
│   └── subprocess_wait (span)
├── llm_call #2 (span)
└── ...
```

### 4.2. Span attributes

Каждый span имеет attributes:

```python
span = tracer.start_span("llm_call")
span.set_attribute("provider", "anthropic")
span.set_attribute("model", "claude-3-5-sonnet-20241022")
span.set_attribute("input_tokens", 12500)
span.set_attribute("output_tokens", 842)
span.set_attribute("cost_usd", 0.015923)
span.set_attribute("session_id", "20261020-143201-a3f2b9c1")
# Sensitive: input/output content — НЕ в span attributes
```

### 4.3. Sampling

- **Default:** no sampling (все spans сохраняются локально)
- **For external export:** head-based sampling, 10% (configurable)
- **For errors:** 100% sampling (all error spans)

### 4.4. Export

```yaml
observability:
  tracing:
    enabled: false  # default off for MVP
    export_to:
      - kind: otel
        endpoint: http://otel-collector:4317
        sample_rate: 0.1
      - kind: jaeger
        endpoint: http://jaeger:14268/api/traces
        sample_rate: 1.0
```

Local trace viewer: `orya traces show <session_id>` — открывает web viewer (через `opentelemetry-instrumentation-asyncio` + local trace storage).

## 5. Cost tracking

### 5.1. Per-session cost

Каждая сессия имеет computed cost:

```python
class SessionCost(BaseModel):
    total_usd: Decimal
    by_provider: dict[str, Decimal]
    by_model: dict[str, Decimal]
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_write_tokens: int
    cache_savings_usd: Decimal  # how much saved via cache
```

Обновляется после каждого LLM-call. Хранится в `.meta.json` и в `~/.orya/metrics.jsonl`.

### 5.2. Budget management

```yaml
# ~/.orya/config.yml
budget:
  per_session_usd: 5.00      # warn at $5, hard-limit at $10
  per_day_usd: 20.00          # warn at $20, hard-limit at $30
  per_month_usd: 200.00       # warn at $200, hard-limit at $250
  hard_limit_action: stop    # stop | ask | warn
```

При достижении warn-threshold — TUI показывает предупреждение. При hard-limit:
- `stop`: agent_loop останавливается, пользователь видит модалку с опциями
- `ask`: agent_loop спрашивает «continue anyway?»
- `warn`: логируется, но не останавливается

### 5.3. Cost projection

`orya cost estimate` — оценивает стоимость для типичных задач:

```
$ orya cost estimate --task="refactor 5 files"

Estimated cost:
  Low:  $0.05 (3-5 LLM calls, 1k tokens each)
  Med:  $0.20 (8-12 LLM calls, 2k tokens each, 50% cache hit)
  High: $0.80 (15-25 LLM calls, 5k tokens each, 0% cache hit)

Based on:
  Provider: anthropic (claude-3-5-sonnet)
  Historical: avg 12 LLM calls per "refactor" task in your sessions
```

Это rough estimate, не promise.

## 6. Alerting

### 6.1. Alert types

| Alert | Trigger | Severity | Action |
|---|---|---|---|
| Cost budget exceeded | session/day/month cost > hard-limit | High | Stop agent, show modal |
| LLM error rate high | >10% errors за 10 min | Medium | Log, show TUI warning |
| Session too long | session duration > 4 hours | Low | Suggest `/compact` (v2) |
| Tool error rate high | >20% errors за 10 min | Medium | Log, suggest investigation |
| Sensitive access spike | >5 sensitive asks in 5 min | High | Log, show security warning |
| Audit log rotation fail | rotation failed | Critical | Stop agent, alert user |

### 6.2. Alert delivery

- **TUI inline:** показываются в реальном времени в REPL
- **Log:** все alerts логируются в `errors.jsonl`
- **External notification** (v2): через webhook (Slack, email)

### 6.3. Alert configuration

```yaml
observability:
  alerts:
    cost_budget:
      enabled: true
      per_session_usd: 5.00
    error_rate:
      enabled: true
      threshold: 0.10  # 10%
      window_minutes: 10
    sensitive_access:
      enabled: true
      threshold: 5
      window_minutes: 5
```

## 7. Privacy и data handling

### 7.1. Что логируется

✅ **Логируется:**
- Event type, timestamp, session_id, call_id
- Provider name, model name, token counts, cost
- Tool name, outcome, duration, error_kind
- Permission decisions (без full input)
- File paths (но не содержимое)
- Bash commands (но не output, в audit-log)
- Stack traces для errors (filtered через redaction)

❌ **НЕ логируется:**
- LLM input/output content (только token counts)
- File content (только path)
- Bash stdout/stderr (только size, exit_code)
- API keys, tokens, secrets (redacted)
- User PII (если не critical для debugging)

### 7.2. Что отгружается externally

✅ **Отгружается (если export enabled):**
- Aggregated metrics (counters, gauges, histograms)
- Span attributes (без sensitive content)
- Event metadata (без content)

❌ **НЕ отгружается externally (даже с export enabled):**
- File content
- Bash output
- LLM content
- User input (полный текст)
- Stack traces (могут содержать sensitive variable values)

### 7.3. User control

```yaml
observability:
  privacy:
    redact_sensitive: true          # default
    redact_file_paths: false         # default: paths OK
    redact_command_args: false       # default: args OK (но redacted sensitive values)
    local_only: true                 # default: metrics/logs только локально
    external_export_requires_opt_in: true
```

Пользователь может:
- Полностью отключить metrics/logs: `observability.enabled: false`
- Включить debug logging: `log_level: debug`
- Отключить external export: `local_only: true`
- Расширить sensitive patterns: `~/.orya/sensitive.yml`

## 8. Performance considerations

### 8.1. Overhead budget

| Operation | Overhead target |
|---|---|
| LLM-call completion (logging + metrics) | <5ms |
| Tool execute (audit + metrics) | <2ms |
| Stream token (metrics increment) | <0.1ms |
| Session event append (with logging) | <10ms |
| Span creation | <0.5ms |

### 8.2. Async logging

Все log writes — через async queue, не блокируют hot-path:

```python
class AsyncLogger:
    def __init__(self, sink: Path, queue_size: int = 1000):
        self._queue: asyncio.Queue = asyncio.Queue(queue_size)
        self._sink = sink
        self._task: asyncio.Task | None = None

    async def start(self):
        self._task = asyncio.create_task(self._writer())

    async def _writer(self):
        async with aiofiles.open(self._sink, "a") as f:
            while True:
                entry = await self._queue.get()
                if entry is None:  # shutdown signal
                    break
                await f.write(entry + "\n")
                await f.flush()

    def log(self, entry: dict):
        try:
            self._queue.put_nowait(json.dumps(entry))
        except asyncio.QueueFull:
            # Drop log entry, increment drop counter
            ...
```

Если queue full — log entry дропается (с счётчиком дропов). Это предпочтительнее, чем блокировка hot-path.

### 8.3. Metrics batching

Метрики — aggregated, не individual writes:

```python
class MetricsCollector:
    def __init__(self):
        self._counters: dict[str, int] = {}
        self._histograms: dict[str, list[float]] = {}
        self._lock = asyncio.Lock()
    
    async def increment(self, name: str, value: int = 1, labels: dict = None):
        key = self._key(name, labels)
        async with self._lock:
            self._counters[key] = self._counters.get(key, 0) + value
    
    async def flush(self):
        """Flush metrics to disk. Called every 60s."""
        async with self._lock:
            snapshot = (self._counters, self._histograms)
            self._counters = {}
            self._histograms = {}
        
        # Write to metrics.jsonl
        for key, value in snapshot[0].items():
            await self._write_metric(key, value)
```

Batching — 60s window. Crash может потерять до 60s of metrics. Acceptable trade-off.

## 9. Debugging workflow

### 9.1. Standard debugging

```bash
# 1. Пользователь сообщает о проблеме
$ orya
> что в README?
[ERROR] LLM call failed: rate_limited

# 2. Пользователь включает debug logging
$ orya --debug
# или
$ orya config set log_level debug

# 3. Повторяет действие, собирает логи
> что в README?
[debug logs visible in TUI]

# 4. Экспортирует логи для bug report
$ orya logs export --since="5 minutes ago" --format=zip > debug.zip

# 5. Открывает Issue с приложенным debug.zip
```

### 9.2. Bug report template

```markdown
## Bug description
What happened?

## Steps to reproduce
1. ...
2. ...

## Expected behavior
What should have happened?

## Actual behavior
What actually happened?

## Environment
- OryaAgent version: orya --version
- Python version: python --version
- OS: ...
- LLM provider: ...

## Logs
[attached debug.zip]

## Configuration
[redacted ~/.orya/config.yml]
```

### 9.3. Diagnostic commands

```bash
orya doctor        # checks installation, config, provider connectivity
orya stats         # aggregated statistics
orya logs show     # recent logs
orya sessions list # recent sessions
orya audit show    # audit log
orya config show   # current configuration (redacted)
```

## 10. Enterprise observability

### 10.1. OTel collector forwarding

```yaml
observability:
  enterprise:
    enabled: true
    otel_collector: http://otel-collector.corp:4317
    metrics_interval: 60s
    traces_sample_rate: 0.1
    logs_forwarding: true
    logs_filter: "level>=info"  # don't forward debug
```

Все metrics, traces, logs — отгружаются в corporate OTel collector. From there — to Prometheus, Jaeger, ELK, Datadog, etc.

### 10.2. Audit log forwarding

```yaml
audit:
  forward_to:
    - kind: otel
      endpoint: http://otel-collector.corp:4317
    - kind: syslog
      host: siem.corp.example.com
      port: 514
      format: rfc5424
    - kind: splunk
      endpoint: https://splunk.corp:8088
      token_env: SPLUNK_HEC_TOKEN
```

Audit log — separate from general observability. Mandatory for compliance-sensitive environments.

### 10.3. SLO monitoring

```yaml
observability:
  slo:
    - name: llm_availability
      target: 99.5%
      window: 30d
      alert_if_breach: true
    - name: cold_start_under_500ms
      target: 95%
      window: 7d
    - name: token_to_render_under_50ms
      target: 99%
      window: 7d
```

SLO breaches — alerting через corporate alerting system.

## 11. Открытые вопросы

1. **Log sampling для debug-level?** При `log_level=debug` — много логов. Sampling strategy? MVP: no sampling. v2: adaptive sampling.

2. **Distributed tracing для subagents (v3)?** Subagents — отдельные process или coroutine? Если process — distributed tracing через trace context propagation.

3. **Cost dashboard real-time?** Live updating cost dashboard в TUI? MVP: показывать после каждого LLM-call. v2: real-time updating.

4. **Telemetry opt-in для anonymous usage stats?** Help understand feature usage, but privacy concern. MVP: no telemetry. v2: opt-in through `orya telemetry enable`.

---

**Следующие шаги:**

1. Реализовать `structlog` setup с JSON output
2. Реализовать `MetricsCollector` с batching
3. Реализовать `AsyncLogger` с queue
4. Реализовать `orya stats` command
5. Документировать OTel integration для enterprise
