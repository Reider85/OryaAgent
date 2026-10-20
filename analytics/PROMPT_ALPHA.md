# ПРОМПТ ФАЗЫ ALPHA — OryaAgent v7

> **Версия промпта:** 7.0
> **Дата:** 20 октября 2026
> **Источники:** `ARCHITECT7.md` v7.0 (§3 #14, #30, #32; §6.9, §6.11; §14.2; §16.1), `ROADMAP7.md` v7.0 (§4, §11.2, §13), `BACKLOG7.md` v7.0 (§3 — A-18, A-19, A-20), `BACKLOG6.md` v6.0 (§3 — A-00..A-17), `ROADMAP6.md` v6.0 (§4)
> **Стек:** Python 3.11+, LangChain 0.3+, LangGraph 0.2+, FastAPI, PostgreSQL 16, Redis 7, Chainlit, **OryaObservability SDK** (новое в v6 ALPHA), httpx (для ConnectionPool)
> **Длительность:** 3 недели (поверх готового MVP)
> **Объём кода:** ~4500 LOC (v6 ALPHA ~4000 + 500 новых v7)
> **Статус в v7:** ALPHA = v6 ALPHA + 3 новых low-risk улучшения (TieredModelRouter, PromptCacheLayout, ConnectionPool)

---

## 0. Контекст и роль

Ты — senior Python-разработчик, реализующий **фазу ALPHA** системы OryaAgent v7. ALPHA превращает «работающий MVP с базовой памятью» в **«production-safe + low-latency baseline»**: добавляет auth, rate-limits, OryaObservability SDK, sampler-proxy (всё из v6 ALPHA), а также **три новых low-risk улучшения v7**.

**Принцип ALPHA v7 (vs v6):** +0.5 недели, +500 LOC, но **3 low-risk улучшения** дают:
- -800 ms time-to-first-token (PromptCacheLayout)
- -25..40% cost на простых ходах (TieredModelRouter)
- -200..500 ms cold-start (ConnectionPool)

**Инвариантность:** ALPHA не нарушает контракты MVP. `get_llm()` seam остаётся, но оборачивается в `TieredModelRouter.select(tier, user_id)` и `ConnectionPool.acquire(provider)`. `build_system_prompt(state, tools)` остаётся, но добавляется optional `dfc: DFC = None` (DFC будет в BETA; в ALPHA `dfc=None` → dynamic suffix = past user/assistant messages).

---

## 1. Цели фазы

Превратить MVP в production-safe + low-latency baseline:

### 1.1. Цели v6 ALPHA (базовые, остаются в силе)

1. **Auth** (JWT/OAuth2) на FastAPI endpoints.
2. **Rate-limits** (per-user, per-endpoint) через Redis.
3. **OryaObservability SDK** — LangGraph instrumentation, spans уходят в Langfuse.
4. **Sampler-proxy** — `LANGFUSE_HOST` → proxy, который фильтрует spans (PII-masking, cost-attributes, security-attributes, always-keep traces).
5. **PII-masking** — fail-closed (если PII detected в span → span не уходит).
6. **Health endpoints** — `/health`, `/health/observability`, `/health/sampler-proxy`.
7. **Memory-метрики** в Prometheus.

### 1.2. Новые цели v7 ALPHA

8. **TieredModelRouter (#30)** — расширение CostAwareRouter v6. Planner эмитит `tier: small | large | tournament`. Router выбирает модель по tier, **независимо** от budget. Cost-aware fallback (если budget ≥90% → degrade на tier=small) остаётся из v6.
9. **PromptCacheLayout (#32)** — дисциплина cacheable prefix + dynamic suffix. Использует провайдерские prompt-caches (Anthropic `cache_control: ephemeral`, OpenAI prompt caching) для cross-turn KV-cache.
10. **ConnectionPool (#14)** — keepalive + hot adapters для LLM-provider seam. -200..500 ms cold-start TCP+TLS на каждом ходе.

---

## 2. Технологический стек (delta к MVP)

| Компонент | Технология | Назначение |
|---|---|---|
| Auth | `python-jose` + `passlib` | JWT issuance/verification |
| Rate-limit | Redis + `slowapi` | per-user, per-endpoint limits |
| Observability | `OryaObservability SDK` + OpenTelemetry + Langfuse | spans, traces |
| Sampler-proxy | FastAPI middleware | span filtering, PII-masking |
| PII-detection | `presidio-analyzer` (Microsoft) | fail-closed masking |
| Metrics | `prometheus-client` | /metrics endpoint |
| HTTP client | `httpx` (AsyncClient + transport) | ConnectionPool для LLM-providers |
| Provider-caches | Anthropic `cache_control`, OpenAI prompt-caching (auto), Gemini context-caching API | PromptCacheLayout |

---

## 3. Полный список тикетов фазы (A-00 … A-20)

v6 ALPHA содержит 18 тикетов (A-00..A-17). v7 добавляет 3 новых (A-18, A-19, A-20). Полный перечень — 21 тикет.

### 3.1. v6 ALPHA baseline (A-00 … A-17) — реализуй без изменений

| ID | Title | Estimate | Заметки |
|---|---|---|---|
| A-00 | FastAPI middleware: auth, CORS, request-id | 1 день | JWT, OAuth2 опционально |
| A-01 | Rate-limiter (Redis + slowapi) | 6 часов | per-user: 60 rpm, per-endpoint: 10 rpm на /learn |
| A-02 | LLM-seam extension (trace-wrapping) | 1 день | оборачивает `get_llm()` в span-emitter |
| A-03 | PermissionPolicy v2 (audit-log spans) | 4 часа | security.span attributes |
| A-04 | Health endpoints | 4 часа | /health, /health/observability, /health/sampler-proxy |
| A-05 | PostgresSaver v2 (encryption at rest) | 1 день | pgcrypto для session-log |
| A-06 | JSONL projection v2 (with span-ids) | 4 часа | cross-link с Langfuse traces |
| A-07 | CacheWrapper v2 (TTL + LRU) | 6 часов | Redis config tuning |
| A-08 | Smoke-тесты v2 (auth, rate-limit, observability) | 1 день | +5 сценариев |
| A-09 | README v2 (deploy guide) | 4 часа | Docker, env-vars, Langfuse setup |
| A-10 | Docker compose (postgres, redis, chainlit, langfuse) | 1 день | one-command deploy |
| A-11 | Alembic migrations | 4 часа | schema evolution |
| A-12 | Settings v2 (env-overrides for prod) | 4 часа | 12-factor app |
| A-13 | CostAwareRouter (budget tracking per session) | 1 день | degrade на Haiku при 70-90% budget |
| A-14 | Cost-tracking в spans | 6 часов | span attributes: cost.input_tokens, cost.output_tokens, cost.usd |
| A-15 | Langfuse integration | 6 часов | OTEL exporter → Langfuse |
| A-16 | **OryaObservability SDK** (instrument LangGraph) | 1 день | custom spans: agent.plan, agent.execute, agent.tool, agent.permission |
| A-17 | **Sampler-proxy mode** + cost/security span attributes | 6 часов | LANGFUSE_HOST → proxy → filter PII, add cost/security |

### 3.2. Новые v7 ALPHA тикеты — детальные спецификации

---

## 4. A-18 — TieredModelRouter (extends CostAwareRouter v6) 🆕

> **Component:** ARCHITECT7 §3 #30, §6.9 | **Dependencies:** A-13 (CostAwareRouter v6), A-02 (LLM seam) | **Estimate:** 4 часа | **TRIZ:** #35 Parameter changes + #1 Segmentation

### Context

В v6 `CostAwareRouter` переключает на Haiku при 70–90% budget (cost-control, не complexity-aware). Простой ход (format) при низком budget всё равно идёт на Sonnet — трата денег. В v7 planner (когда появится в BETA через #19) эмитит `tier: small | large | tournament`; `TieredModelRouter` выбирает модель по tier, независимо от budget.

### Goal

1. Расширить `app/core/llm.py::CostAwareRouter` до `TieredModelRouter` (через наследование или composition).
2. Метод `select(tier: str, user_id: UUID) -> ModelSelection`:
   - `tier=small` → Haiku/Qwen-3B.
   - `tier=large` → Sonnet/Opus (default).
   - `tier=tournament` → defer to TournamentExecutor (PROD, заглушка в ALPHA).
3. Cost-aware fallback: если `budget_ratio >= 0.9` → понижать tier до `small`.
4. Span attribute: `agent.execute.tier`, `agent.execute.degraded`.
5. В ALPHA (до planner'а в BETA) — hardcoded `tier=large` default; tier эмитится в BETA.

### Constraints

- `tier` может быть: `small | large | tournament`.
- Cost-aware fallback понижает tier, не повышает.
- Span attributes emit **до** возврата model.
- Если `tier=tournament` в ALPHA (до PROD) — degrade на `large` (TournamentExecutor ещё не реализован).
- Default tier: `large` (если planner не эмитит, что в ALPHA так и есть).

### Acceptance Criteria

- ✅ `TieredModelRouter.select(tier="small", user_id=...)` возвращает Haiku/Qwen-3B.
- ✅ `TieredModelRouter.select(tier="large", user_id=...)` возвращает Sonnet/Opus.
- ✅ При `budget_ratio >= 0.9` — `degraded=true`, tier понижен до `small`.
- ✅ Span `agent.execute.tier` = `small|large`, `agent.execute.degraded` = `true|false`.
- ✅ Если `tier=tournament` — degrade на `large` (в ALPHA, без PROD tournament).
- ✅ Все существующие v6 tests для CostAwareRouter проходят.
- ✅ Config в `~/.orya/config.yaml`:
  ```yaml
  tiered_router:
    models:
      small: ["haiku-3.5", "qwen-3b"]
      large: ["sonnet-3.5", "opus-3.5"]
      tournament: ["sonnet-3.5", "gpt-5", "deepseek-v3"]
  ```

### Forbidden patterns

- ❌ Изменять CostAwareRouter v6 без сохранения backward compatibility — TieredModelRouter extends, не replaces.
- ❌ Эмитить `tier` после возврата model — должен быть до.
- ❌ Hardcoded model names в коде — через settings/env.
- ❌ Использовать `tier=tournament` в ALPHA (это PROD).

### Suggested files

- `app/core/llm/tiered_router.py`
- `app/core/llm.py` (update CostAwareRouter — extend interface)
- `tests/test_tiered_router.py`

---

## 5. A-19 — PromptCacheLayout (Anthropic ephemeral + OpenAI prompt caching) 🆕

> **Component:** ARCHITECT7 §3 #32, §6.11 | **Dependencies:** A-02 (LLM seam), A-18 (TieredModelRouter) | **Estimate:** 6 часов | **TRIZ:** #11 Beforehand cushioning + #19 Periodic action

### Context

В v6 `CacheWrapper` кэширует tool-results в Redis. Но cacheable prefix (system + tools + project_summary + L0 memory) пересчитывается каждым провайдером на каждом ходе — это +800 ms time-to-first-token. Anthropic и OpenAI имеют prompt-caching через `cache_control: ephemeral` и prompt caching (5–10 min) соответственно. В v7 `PromptCacheLayout` использует провайдерские prompt-caches для cross-turn KV-cache reuse.

### Goal

1. Реализовать `app/core/llm/prompt_cache.py::PromptCacheLayout`:
   - `assemble(system, tools, project_summary, l0_memory, dynamic) -> list[BaseMessage]`:
     - Anthropic: SystemMessage с `cache_control: ephemeral` markers для cacheable prefix.
     - OpenAI: SystemMessage с cache-friendly structure (провайдер кэширует автоматически).
     - Gemini: context caching (через separate API call для регистрации prefix).
2. Cacheable prefix: system + tools + project_summary + L0 memory (4 MD-файла).
3. Dynamic suffix: plan + active symbols + active diff (из DFC, но DFC появится в BETA — для ALPHA dynamic suffix = past user/assistant messages).
4. Redis: `orya:prompt_cache:prefix_hash:{thread_id}` — hash of cacheable prefix (для invalidation при изменении tool-schemas).
5. Span attribute: `llm.call.cache_hit` (true|false), `llm.call.cache_age_seconds`.

### Constraints

- Anthropic `cache_control: ephemeral` — 5-минутный TTL с sliding window (при cache hit).
- OpenAI prompt caching — automatic для prefix >1024 tokens, 5-10 min cache.
- Gemini context caching — через отдельный API call (register prefix → cache-id → use cache-id в subsequent calls).
- Prefix hash в Redis — sha256 of serialized prefix; invalidate при изменении tool-schemas или L0 memory.
- Если prefix hash changed → следующее сообщение будет cache-miss (это ОК, провайдер пересоздаст cache).
- Provider support matrix:
  - Anthropic: ✅ native support.
  - OpenAI: ✅ automatic (no special markers).
  - Ollama (local): ⚠️ partial support (через prompt-cache fixture).
  - Google Vertex: ✅ explicit context caching API.

### Acceptance Criteria

- ✅ `PromptCacheLayout.assemble(...)` возвращает LangChain messages с `cache_control: ephemeral` для Anthropic.
- ✅ Anthropic API получает `cache_control` markers (verified через `llm.call.cache_hit=true` span).
- ✅ OpenAI prompt caching работает автоматически (verified через `llm.call.cache_hit=true` для prefix >1024 tokens).
- ✅ Prompt-cache hit rate > 40% на тестовых сессиях (provider-side metric).
- ✅ Time-to-first-token ≤ 600 ms (vs v6 ≤ 1200 ms без prompt-cache).
- ✅ Prefix hash в Redis: при изменении tool-schemas → hash changes → cache invalidated.
- ✅ `AGENT_OBS_PROMPT_CACHE_ENABLED=false` — disable (для debugging).
- ✅ Если provider не поддерживает prompt-caching — fallback to plain SystemMessage (no `cache_control`).

### Forbidden patterns

- ❌ Mark dynamic suffix с `cache_control: ephemeral` — это wrong (dynamic меняется каждый ход).
- ❌ Хранить plaintext PII в cacheable prefix — PII-masking через guardrail (v6 A-16).
- ❌ Hardcoded provider-specific logic в general path — через provider-detection.
- ❌ Блокировать agent-loop на Gemini context-caching register API call — async с retry.

### Suggested files

- `app/core/llm/prompt_cache.py`
- `app/core/llm/providers/anthropic.py` (update: emit cache_control markers)
- `app/core/llm/providers/openai.py` (update: cache-friendly structure)
- `app/core/llm/providers/gemini.py` (update: context-caching register)
- `tests/test_prompt_cache_layout.py`

---

## 6. A-20 — ConnectionPool (keepalive + hot adapters) 🆕

> **Component:** ARCHITECT7 §3 #14, §6.9 | **Dependencies:** A-02 (LLM seam) | **Estimate:** 6 часов | **TRIZ:** #11 Beforehand cushioning + #15 Dynamicity

### Context

В v6 каждый LLM-call создаёт новый TCP+TLS connection к провайдеру. Cold-start latency: 200-500 ms на каждом ходе. В v7 `ConnectionPool` держит 4 keepalive connections per provider, не платит cold-start каждый раз.

### Goal

1. Реализовать `app/core/llm/connection_pool.py::ConnectionPool`:
   - Per-provider keepalive connections (`httpx.AsyncClient` + `transport`).
   - Hot pool size: 4 (default), configurable through `LLM_POOL_SIZE`.
   - LRU eviction при превышении max size.
   - Periodic health-check (раз в 30 s).
   - Fail-open: если connection unhealthy → spawn new.
2. Provider coverage: Anthropic, OpenAI, Ollama (local), Google Vertex.
3. Integration с `ChatAnthropic`, `ChatOpenAI`, `ChatOllama`, `ChatVertexAI` (LangChain) — pass `http_client` parameter.
4. Span attribute: `tcp.connect_duration_ms`, `tcp.pool_hit` (true|false).

### Constraints

- `httpx.AsyncClient` с `transport=httpx.HTTPTransport(retries=2, keepalive_expiry=60)`.
- Hot pool size default 4, max 16.
- Health-check: HEAD request на provider's `/health` (если есть), иначе TCP connect probe.
- Если connection unhealthy — close and create new (don't block agent-loop).
- Pool metrics: `orya_llm_pool_size{provider}`, `orya_llm_pool_hit_rate{provider}`, `orya_llm_pool_unhealthy_total{provider}`.
- Thread-safe: `asyncio.Lock` for pool mutations.

### Acceptance Criteria

- ✅ `ConnectionPool` держит 4 keepalive connections per provider (Anthropic, OpenAI, Ollama, Vertex).
- ✅ При cold-start (после restart) — первый ход не платит TCP+TLS latency (verified через `tcp.connect_duration_ms < 50` для warm connection).
- ✅ Health-check убивает unhealthy connections и создаёт новые.
- ✅ LRU eviction: при max_size=4 и 5-м provider call — oldest connection evicted.
- ✅ Span `tcp.connect_duration_ms` ≤ 50 ms для warm connections, 200-500 ms для cold.
- ✅ `orya_llm_pool_hit_rate` > 95% (большинство reuse existing connection).
- ✅ `orya_llm_pool_unhealthy_total` < 1% от total connections.

### Forbidden patterns

- ❌ Hardcoded provider URLs — через settings/env.
- ❌ Синхронный health-check в agent-loop — async only.
- ❌ Block agent-loop при pool full — wait-free, spawn new (over limit, then evict).
- ❌ Mix connections between threads without Lock.

### Suggested files

- `app/core/llm/connection_pool.py`
- `app/core/llm.py` (update: pass http_client to ChatX classes)
- `tests/test_connection_pool.py`

---

## 7. Архитектура ALPHA (delta к MVP)

```
┌──────────────────────────────────────────────────────────────────┐
│                       Chainlit UI (MVP)                            │
└──────────────────────────────────────────────────────────────────┘
                              │
┌──────────────────────────────────────────────────────────────────┐
│                  FastAPI (Auth, RateLimit, CORS)                  │
│  A-00: middleware  │  A-01: slowapi  │  A-17: sampler-proxy     │
└──────────────────────────────────────────────────────────────────┘
                              │
┌──────────────────────────────────────────────────────────────────┐
│                     LangGraph (M-04)                              │
│   ┌────────────┐  ┌─────────────┐  ┌─────────────────────────┐   │
│   │ agent node │→ │ tool node   │→ │ permission node         │   │
│   │ (LLM-call) │  │ (asyncio)   │  │ (interrupt_before)      │   │
│   └────────────┘  └─────────────┘  └─────────────────────────┘   │
└──────────────────────────────────────────────────────────────────┘
                              │
   ┌──────────────────────────┴───────────────────────────┐
   ▼                                                       ▼
┌──────────────────────────────┐         ┌──────────────────────────────┐
│   LLM-seam (M-01 + A-02)    │         │   OryaObservability SDK       │
│  ┌────────────────────────┐ │         │   (A-16) — spans              │
│  │ TieredModelRouter 🆕  │ │         │   agent.plan / agent.execute   │
│  │  (A-18)                │ │         │   agent.tool / agent.permission│
│  └──────────┬─────────────┘ │         └──────────────────────────────┘
│             ▼                  │
│  ┌────────────────────────┐   │
│  │ PromptCacheLayout 🆕  │   │
│  │  (A-19)                │   │
│  └──────────┬─────────────┘   │
│             ▼                  │
│  ┌────────────────────────┐   │
│  │ ConnectionPool 🆕     │   │
│  │  (A-20)                │   │
│  └──────────┬─────────────┘   │
│             ▼                  │
│  init_chat_model (provider)   │
└──────────────────────────────┘
        │
        ▼
   Anthropic / OpenAI / Ollama / Vertex API
```

---

## 8. Целевые NFR (delta к MVP)

| Параметр | MVP | ALPHA v7 | v6 было |
|---|---|---|---|
| Time-to-first-token | ≤ 1300 ms | **≤ 600 ms** | ≤ 1200 ms |
| Prompt-cache hit rate | — | **> 40%** | — |
| Connection-pool hit rate | — | **> 95%** | — |
| Cold-start latency (после restart) | ~ 1000 ms | **≤ 200 ms** | ~ 1000 ms |
| Cost per turn (simple task, large tier) | $0.008 | **$0.005** | $0.008 (no tiered router) |
| Cost per session (30 ходов) | ≤ $0.45 | ≤ $0.40 | ≤ $0.40 |
| PII-masking coverage | — | 100% (fail-closed) | 100% |
| Auth coverage | — | 100% endpoints | 100% |
| Rate-limit enforcement | — | per-user + per-endpoint | per-user + per-endpoint |

---

## 9. Definition of Done (delta к MVP)

- ✅ (все DoD из MVP)
- ✅ Auth: все `/sessions`, `/learn`, `/memory/*` endpoints требуют JWT.
- ✅ Rate-limit: 60 rpm per-user, 10 rpm на `/learn` (anti-abuse).
- ✅ OryaObservability SDK: spans `agent.plan`, `agent.execute`, `agent.tool`, `agent.permission` уходят в Langfuse через sampler-proxy.
- ✅ Sampler-proxy: PII-masking 100% (fail-closed), cost-attributes добавляются, security-attributes (`security.incident=true` на prompt-injection).
- ✅ Always-keep traces (with `trace.always_keep=true` attribute) сохраняются в Langfuse.
- ✅ Memory-метрики экспортируются в Prometheus (`/metrics`).
- ✅ Health endpoints работают: `/health`, `/health/observability`, `/health/sampler-proxy`.
- ✅ **`TieredModelRouter.select(tier="small", user_id=...)` возвращает Haiku/Qwen-3B.**
- ✅ **`TieredModelRouter.select(tier="large", user_id=...)` возвращает Sonnet/Opus.**
- ✅ **При `budget_ratio >= 0.9` — `degraded=true`, tier понижен до `small`.**
- ✅ **Planner (когда появится в BETA) сможет эмитить tier; в ALPHA — hardcoded `large` default.**
- ✅ **`PromptCacheLayout.assemble(...)` возвращает LangChain messages с `cache_control: ephemeral`.**
- ✅ **Anthropic API получает `cache_control` markers (видно в trace через `llm.call.cache_hit=true`).**
- ✅ **Prompt-cache hit rate > 40% на тестовых сессиях (provider-side metric).**
- ✅ **`ConnectionPool` держит 4 keepalive connections per provider.**
- ✅ **При cold-start (после restart) — первый ход не платит TCP+TLS latency (verified через `tcp.connect_duration_ms` span).**
- ✅ **Health-check убивает unhealthy connections и создаёт новые.**

---

## 10. TRIZ-gates фазы (delta к MVP)

| Gate | Принцип | Что встроено |
|---|---|---|
| (все gates из MVP) | — | — |
| Auth + Rate-limit | ТРИЗ #9 Preliminary anti-action + #35 Parameter changes | pre-flight check перед destructive op |
| OryaObservability SDK | ТРИЗ #28 Mechanics substitution + #24 Intermediary | spans вместо print-логов |
| Sampler-proxy | ТРИЗ #15 Dynamicity + #24 Intermediary | proxy layer для filtering, не breaking app |
| PII-masking fail-closed | ТРИЗ #9 Preliminary anti-action | mask до отправки в Langfuse |
| CostAwareRouter | ТРИЗ #35 Parameter changes + #1 Segmentation | budget-based model selection |
| **TieredModelRouter** 🆕 | ТРИЗ #35 Parameter changes + #1 Segmentation | Tier-based model selection, бюджет-independent |
| **PromptCacheLayout** 🆕 | ТРИЗ #11 Beforehand + #19 Periodic | Provider KV-cache reuse cross-turn |
| **ConnectionPool** 🆕 | ТРИЗ #11 Beforehand + #15 Dynamicity | Hot pool, no cold-start TCP+TLS |

---

## 11. Risks и mitigations (delta к MVP)

- (все риски из MVP)
- **Auth bypass** — JWT verification на каждом endpoint, integration tests.
- **Rate-limit false-positive** — whitelist для trusted clients (`ORYA_TRUSTED_CLIENTS`).
- **Langfuse downtime** — sampler-proxy буферизует spans в Redis (retry на 5 мин).
- **PII-masking false-negative** — fail-closed: если PII-detector упал → span не уходит (security.incident).
- **Cost-tracking drift** — nightly reconciliation с provider invoices.
- **Prompt-cache invalidation при tool-registry changes** 🆕: `prompt_cache:prefix_hash` в Redis; invalidate при изменении tool-schemas.
- **ConnectionPool leak** 🆕: max_pool_size=4; LRU eviction; periodic health-check.
- **TieredModelRouter race condition** 🆕: emit `tier` до возврата model, не после.
- **Gemini context-caching API latency** 🆕: async с retry; не блокировать agent-loop.

---

## 12. Forbidden patterns (delta к MVP)

- ❌ Использовать `tier=tournament` в ALPHA (это PROD).
- ❌ Mark dynamic suffix с `cache_control: ephemeral` (он меняется каждый ход).
- ❌ Синхронный health-check в agent-loop (только async).
- ❌ Block agent-loop при pool full (wait-free, spawn new).
- ❌ Hardcoded model names в коде (через settings/env).
- ❌ Хранить plaintext PII в cacheable prefix.
- ❌ Использовать LLM-call без span-wrapping.
- ❌ Пропускать PII-masking (fail-closed обязательно).

---

## 13. Структура файлов (delta к MVP)

```
app/
├── core/
│   ├── llm/
│   │   ├── __init__.py        # get_llm() wrapper (M-01 + A-02)
│   │   ├── tiered_router.py   # 🆕 A-18: TieredModelRouter
│   │   ├── prompt_cache.py    # 🆕 A-19: PromptCacheLayout
│   │   ├── connection_pool.py # 🆕 A-20: ConnectionPool
│   │   └── providers/
│   │       ├── __init__.py
│   │       ├── anthropic.py   # cache_control markers
│   │       ├── openai.py      # cache-friendly structure
│   │       ├── ollama.py
│   │       └── gemini.py      # context-caching API
│   ├── observability/
│   │   ├── __init__.py        # A-16: OryaObservability SDK
│   │   ├── spans.py           # span emitters
│   │   └── sampler_proxy.py   # A-17: sampler-proxy
│   ├── auth/
│   │   ├── __init__.py        # A-00: JWT
│   │   └── rate_limit.py      # A-01: slowapi
│   └── ... (MVP modules)
├── api/
│   ├── middleware.py          # A-00: auth, CORS, request-id
│   ├── health.py              # A-04: /health/*
│   └── metrics.py             # /metrics (Prometheus)
├── tests/ (расширенные)
│   ├── test_tiered_router.py        # 🆕
│   ├── test_prompt_cache_layout.py  # 🆕
│   ├── test_connection_pool.py      # 🆕
│   ├── test_auth.py
│   ├── test_rate_limit.py
│   ├── test_observability.py
│   ├── test_sampler_proxy.py
│   └── smoke/test_smoke_v2.py       # +5 сценариев auth/rate-limit/observability
└── deploy/
    ├── docker-compose.yml     # A-10
    └── Dockerfile
```

---

## 14. Порядок реализации (рекомендуемый)

1. **Неделя 1:** A-00 (auth middleware), A-01 (rate-limit), A-02 (LLM-seam trace-wrapping), A-03 (permission audit), A-04 (health endpoints), A-13 (CostAwareRouter). Демонстрация: auth + observability работают, spans уходят в Langfuse.
2. **Неделя 2:** A-16 (OryaObservability SDK), A-17 (sampler-proxy), A-14 (cost-tracking), A-15 (Langfuse integration), A-05 (PostgresSaver v2), A-06 (JSONL v2), A-07 (CacheWrapper v2), A-08 (smoke v2), A-09 (README v2), A-10 (Docker), A-11 (Alembic), A-12 (Settings v2). Демонстрация: full v6 ALPHA работает.
3. **Неделя 3 (v7 additions):** A-18 (TieredModelRouter, 4 часа), A-19 (PromptCacheLayout, 6 часов), A-20 (ConnectionPool, 6 часов). Демонстрация: TTFT ≤ 600 ms, prompt-cache hit > 40%, connection-pool hit > 95%.

---

## 15. Exit criteria (переход ALPHA → BETA)

- ✅ (все exit-criteria из MVP → ALPHA)
- ✅ OryaObservability SDK интегрирован: spans уходят в Langfuse через sampler-proxy.
- ✅ PII-masking: 100% (fail-closed).
- ✅ `cost.over_budget` + `security.incident` span attributes работают.
- ✅ Always-keep traces сохраняются (verified через Langfuse query).
- ✅ Memory-метрики экспортируются в Prometheus.
- ✅ `/health/observability` и `/health/sampler-proxy` работают.
- ✅ **TieredModelRouter: `select(tier=...)` работает для small/large/tournament.**
- ✅ **PromptCacheLayout: prompt-cache hit rate > 40% (provider-side metric).**
- ✅ **ConnectionPool: cold-start latency ≤ 200 ms (vs без pool ~1000 ms).**

---

## 16. Ссылки на исходные документы

- `ARCHITECT7.md` §3 (улучшения #14, #30, #32), §6.9 (llm/tiered_router + prompt_cache + connection_pool), §6.11 (system-prompt-builder cacheable prefix), §14.2 (LOC delta +500), §16.1 (риски v7 ALPHA).
- `ROADMAP7.md` §4 (Фаза ALPHA), §11.2 (ALPHA → BETA exit criteria), §13 (NFR-таргеты по фазам).
- `BACKLOG7.md` §3 (A-18, A-19, A-20 — детальные спецификации).
- `BACKLOG6.md` §3 (A-00..A-17 — v6 ALPHA baseline).
- `ROADMAP6.md` §4 (Фаза ALPHA v6).

---

**Готов к реализации.** После завершения ALPHA переходи к фазе BETA (`PROMPT_BETA.md`) — там добавятся DFC, Tri-Model Pipeline, LSP-native, UKB, RetrievalOrchestrator, CapabilityRegistry.
