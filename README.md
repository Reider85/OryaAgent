# OryaAgent v7.0

Senior Python coding agent with UI and long-term memory.

## Phase: ALPHA

Tickets M-00…M-28 (bootstrap → failure recovery) and MVP-POLISH are implemented. ALPHA adds the production-safe baseline: A-00 (auth middleware), A-01 (rate-limit), A-02 (LLM-seam trace-wrapping), A-03 (permission audit spans), A-04 (health endpoints), A-05 (session-log encryption), A-06 (JSONL span cross-link), A-07 (cache LRU + Redis tuning), A-08 (smoke tests v2) and A-09 (this deploy guide). See [PROMPT_ALPHA.md](analytics/PROMPT_ALPHA.md) for the phase spec.

## Quick Start

### Prerequisites
- Python 3.11+ (3.14 system Python is supported, but langchain compatibility may require pinning to 3.12 via `uv python pin 3.12`)
- Docker and Docker Compose (for PostgreSQL and Redis)

### Setup

1. **Clone and setup:**
   ```bash
   git clone https://github.com/Reider85/OryaAgent.git
   cd OryaAgent
   ```

2. **Install dependencies:**
   ```bash
   uv sync
   ```

3. **Start infrastructure (optional, for full MVP):**
   ```bash
   docker compose up -d
   ```

4. **Start development server:**
   ```bash
   make dev
   ```

   Or directly with uv:
   ```bash
   uv run uvicorn app.main:app --reload --port 8000
   ```

5. **Health check:**
   ```bash
   curl http://localhost:8000/health
   # Should return: {"status": "ok", "message": "OryaAgent API is running"}
   ```
   `/health` is always public; once `AUTH_ENABLED=true` every other endpoint requires a `Authorization: Bearer <token>` header (see [Authentication (A-00)](#authentication-a-00)).

6. **Start the Chainlit UI (another terminal):**
   ```bash
   make ui
   ```
   The chat opens on http://localhost:8001 and talks to the FastAPI server over HTTP/SSE (`ORYA_API_URL`, default `http://127.0.0.1:8000`) — `make dev` must be running.

### One-command start

Instead of running the steps above by hand:

```bash
scripts/start.sh              # Linux / macOS / Git Bash (Windows)
powershell -ExecutionPolicy Bypass -File scripts\start.ps1   # native Windows
```

The script runs the full bring-up: `uv sync` → `docker compose up -d postgres redis` → `orya db migrate` (idempotent) → background API (`:8000`) → background Chainlit UI (`:8001`), waiting on `/health` at each stage. Logs go to `logs/api.log`, `logs/ui.log` (plus `.err.log` twins); ports and URLs are picked up from the environment or `.env` and recorded in `logs/runtime.env`. Stop everything with `scripts/stop.sh` / `scripts/stop.ps1`. Flags: `--skip-sync`, `--reload` (uvicorn autoreload).

### Development Commands

- `make dev` - Start development server (FastAPI on port 8000)
- `make ui` - Chainlit chat UI (port 8001, M-15/M-24; requires `make dev`)
- `make test` - Run tests
- `make lint` - Lint code with ruff
- `make format` - Format code with ruff
- `make clean` - Clean up build artifacts
- `make db-up` / `make db-migrate` / `make db-down` - PostgreSQL lifecycle (M-03)
- `make redis-up` / `make redis-down` - Redis for the tool-result cache (M-21)

### Configuration

Settings are typed in `app/core/config.py` (pydantic-settings, M-02). Sources by priority:

1. **Environment variables / `.env`** — copy `.env.example` to `.env`:
   ```bash
   cp .env.example .env
   # Edit .env with your API keys
   ```
2. **`~/.orya/config.yaml`** — multi-provider config (used only for fields not set via env). API keys go through `${ENV_VAR}` substitution, never plaintext:
   ```yaml
   llm:
     default_provider: anthropic
     default_model: claude-sonnet-3.5
     providers:
       deepseek:
         api_key: ${DEEPSEEK_API_KEY}
         base_url: https://api.deepseek.com/v1
         default_model: deepseek-chat
   ```
3. **Defaults** in `Settings` (provider `anthropic`, model `claude-sonnet-3.5`, permission policy `strict`, ...).

The full env-var reference — every knob, its aliases and defaults — lives in [Environment variables](#environment-variables) below.

```python
from app.core.config import get_settings

settings = get_settings()
```

## Deploy guide

Three supported ways to run OryaAgent, from a laptop to a single-host deployment:

| Mode | Command | What runs |
|---|---|---|
| Dev (manual) | `make dev` + `make ui` | API on `:8000`, Chainlit on `:8001`; infra via `make db-up` / `make redis-up` |
| One-command | `scripts/start.sh` or `scripts\start.ps1` | `uv sync` → compose postgres/redis → migrations → background API + UI (see [One-command start](#one-command-start)) |
| Infra in Docker | `docker compose up -d` | PostgreSQL 16 + Redis 7 only — the app itself runs on the host |

### Docker services (today)

`docker-compose.yml` provides the stateful dependencies only:

| Service | Image | Host port | Notes |
|---|---|---|---|
| `postgres` | `postgres:16` | `${POSTGRES_PORT:-5432}` | db/user `orya`/`orya_sessions`, volume `postgres_data`, `pg_isready` healthcheck |
| `redis` | `redis:7` | `${REDIS_PORT:-6379}` | `redis-server --maxmemory 256mb --maxmemory-policy allkeys-lru` — server-side LRU (A-07); eviction = cache miss = safe |

Port conflicts: `POSTGRES_PORT=5435 make db-up` (plus a matching `DATABASE_URL`) and `REDIS_PORT=6381 make redis-up` (plus a matching `REDIS_URL`). The start scripts detect an already-running container and reuse its ports.

Application containers (API/Chainlit), the `langfuse` service and the `sampler-proxy` service are **not** in this compose file yet — they arrive with **A-10** (Docker compose v2). Until then the app is deployed as a host process (`uv run uvicorn app.main:app`, `chainlit run app/ui/chainlit_app.py`) supervised the way you prefer (systemd, nssm, pm2 — the repo's `scripts/start.*` are the reference implementation).

### Production checklist

- `AUTH_ENABLED=true` + `AUTH_SECRET_KEY` (≥ 32 chars) — Bearer-JWT on every non-public endpoint (A-00).
- `ORYA_RATE_LIMIT_ENABLED=true` — 60 rpm per user, 10 rpm on `/learn` (A-01).
- `ORYA_SESSION_LOG_ENCRYPTION_ENABLED=true` + `ORYA_SESSION_LOG_ENCRYPTION_KEY` (≥ 16 chars) — pgcrypto at-rest encryption for `messages.content` / `messages.tool_calls` (A-05; needs `make db-migrate` for the `pgcrypto` extension).
- Run `orya db migrate` (idempotent) as part of every deploy.
- Set `DATABASE_URL` / `REDIS_URL` explicitly; do not rely on the localhost defaults.
- Narrow `CORS_ORIGINS` to your UI origin(s) instead of the `*` default.
- Keep `LOG_LEVEL=INFO` (or `WARNING`); logs go to stdout/journald (the start scripts write `logs/*.log`).
- The API returns `X-Request-ID` on every response (echoed or minted) — propagate it through your reverse proxy.
- `/health`, `/docs`, `/redoc`, `/openapi.json`, `/metrics` are JWT-exempt (`AUTH_PUBLIC_PATHS`); everything else requires `Authorization: Bearer <token>`.

### Langfuse setup (planned — A-15/A-16/A-17)

Langfuse export is **not wired yet**. The in-process observability seam already works (A-02/A-03/A-04/A-06); the env contract below is what the ALPHA observability stack will consume, so infra and secrets can be prepared now.

**Works today:**

| Knob | Effect |
|---|---|
| `ORYA_LLM_TRACE_ENABLED` (default `true`) | Wrap every `get_llm()` model in `TracedChatModel` — one `llm.call` span per invocation |
| `ORYA_LLM_TRACE_EXPORTER=stdout` | Debug-export each finished span as a JSON line (default `off` = buffer only) |
| `ORYA_PERMISSION_AUDIT_ENABLED` (default `true`) | `agent.permission` spans on permission decisions |
| `GET /health/observability` | `{sdk_enabled, exporter_connected, guardrail_ready, span_buffer_size}` |
| JSONL projection (A-06) | every event carries `trace_id` / `span_id` — the cross-link to a future Langfuse trace |

**Planned env contract** (A-15 Langfuse integration, A-16 OryaObservability SDK, A-17 sampler-proxy) — placeholders, no code reads them yet:

| Env var | Planned role |
|---|---|
| `LANGFUSE_HOST` | Tracing endpoint; in the A-10 compose stack it points at the sampler-proxy: `http://sampler-proxy:4321` |
| `LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY` | Langfuse project credentials |
| `LANGFUSE_DIRECT_URL` | Fail-open fallback straight to Langfuse when the sampler-proxy is down |
| `OTEL_EXPORTER_OTLP_ENDPOINT` (or `ORYA_OTEL_EXPORTER_OTLP_ENDPOINT`) | OTLP collector endpoint — the setting already exists in `Settings` |
| `ORYA_SAMPLER_PROXY_URL` (default `http://sampler-proxy:4321`) | Sampler-proxy base URL probed by `GET /health/sampler-proxy` (A-04) |
| `AGENT_OBS_ENABLED` / `AGENT_OBS_SAMPLER_AUDIT_ENABLED` | OryaObservability SDK kill-switch / sampler audit trail |

Until A-15 lands, use `ORYA_LLM_TRACE_EXPORTER=stdout` plus the JSONL `trace_id` cross-link for offline debugging.

## Environment variables

Every knob recognized by `app/core/config.py`, by group. Most settings accept two spellings — the legacy unprefixed name and an `ORYA_`-prefixed twin (e.g. `AUTH_ENABLED` and `ORYA_AUTH_ENABLED` are equivalent); either may be used, and env vars always win over `.env` and `~/.orya/config.yaml`. `~` in path values is expanded. The copyable template is `.env.example`.

### LLM (M-01/M-02)

| Env var | Default | Description |
|---|---|---|
| `ORYA_LLM_PROVIDER` | `anthropic` | Default LLM provider key from `providers.yaml` |
| `ORYA_LLM_MODEL` | `claude-sonnet-3.5` | Default model alias (`models.yaml`) or raw model id |
| `ORYA_LLM_API_KEY` | — | Override API key; provider-specific env vars (`DEEPSEEK_API_KEY`, …) usually win |
| `ORYA_LLM_BASE_URL` | — | Endpoint override for OpenAI-compatible providers |
| `ORYA_LLM_TEMPERATURE` | `0.0` | Sampling temperature |
| `ORYA_LLM_MAX_TOKENS` | `8192` | Max completion tokens |
| `ORYA_LLM_TIMEOUT_S` | `120` | Per-call provider timeout (seconds) |
| `ORYA_LLM_RETRY_ATTEMPTS` | `3` | Total attempts of one provider call (incl. the first) |
| `ORYA_LLM_RETRY_BACKOFF_SECONDS` | `1.0` | Base delay of the exponential retry backoff |

### Observability (A-02/A-03/A-04, planned A-15…A-17)

| Env var | Default | Description |
|---|---|---|
| `ORYA_LLM_TRACE_ENABLED` | `true` | `TracedChatModel` wrapper: one `llm.call` span per `get_llm()` call; `false` = raw adapter |
| `ORYA_LLM_TRACE_EXPORTER` | `off` | `off` \| `stdout` — debug JSON export of finished spans |
| `ORYA_PERMISSION_AUDIT_ENABLED` | `true` | Emit `agent.permission` audit spans |
| `LANGSMITH_API_KEY` | — | Placeholder (LangSmith) |
| `OTEL_EXPORTER_OTLP_ENDPOINT` / `ORYA_OTEL_EXPORTER_OTLP_ENDPOINT` | — | OTLP collector endpoint (planned Langfuse export) |
| `ORYA_SAMPLER_PROXY_URL` | `http://sampler-proxy:4321` | Sampler-proxy base URL for `/health/sampler-proxy` |

### Database (M-03)

| Env var | Default | Description |
|---|---|---|
| `DATABASE_URL` / `ORYA_DATABASE_URL` | `postgresql://orya:orya_password@localhost:5432/orya_sessions` | asyncpg connection string |
| `DATABASE_POOL_SIZE` | `5` | asyncpg pool size |
| `DATABASE_MAX_OVERFLOW` | `10` | asyncpg pool max overflow |

### Redis / tool-result cache (M-21, A-07)

| Env var | Default | Description |
|---|---|---|
| `REDIS_URL` / `ORYA_REDIS_URL` | `redis://localhost:6379` | Redis connection URL |
| `ORYA_CACHE_BACKEND` | `auto` | `auto` \| `memory` \| `redis` — `auto` probes Redis at startup and falls back to memory |
| `ORYA_CACHE_TTL_SECONDS` | `300` | Tool-result cache TTL |
| `ORYA_CACHE_MAX_ENTRIES` | `1024` | `MemoryCache` LRU capacity; `0` = unlimited |
| `ORYA_REDIS_POOL_MAX_CONNECTIONS` | `10` | Redis client pool max connections |
| `ORYA_REDIS_SOCKET_TIMEOUT_SECONDS` | `5.0` | Redis client socket timeout |

### Memory (M-25/M-27)

| Env var | Default | Description |
|---|---|---|
| `ORYA_MEMORY_DIR` | `~/.orya/memory` | L0 MD files + `archive/` + audit fallback |
| `ORYA_MEMORY_COMPACT_INTERVAL_SECONDS` | `86400` | Periodic L0 compaction worker; `0` disables it |

### Sessions / session-log (M-14, A-05/A-06)

| Env var | Default | Description |
|---|---|---|
| `ORYA_SESSIONS_DIR` | `~/.orya/sessions` | JSONL projection directory (`{session_id}.jsonl` + `.meta.json`) |
| `SESSION_LOG_ENCRYPTION_ENABLED` / `ORYA_SESSION_LOG_ENCRYPTION_ENABLED` | `false` | pgcrypto at-rest encryption of `messages.content` / `messages.tool_calls` |
| `SESSION_LOG_ENCRYPTION_KEY` / `ORYA_SESSION_LOG_ENCRYPTION_KEY` | — | Symmetric passphrase for `pgp_sym_encrypt` (≥ 16 chars, required when enabled) |

### Permissions / agent loop (M-04/M-13, M-28)

| Env var | Default | Description |
|---|---|---|
| `ORYA_PERMISSION_POLICY` | `strict` | `strict` \| `permissive` |
| `ORYA_PERMISSIONS_PATH` | `~/.orya/permissions.yml` | User allow/deny rule overrides (ADR-004); absent → built-ins |
| `ORYA_RECURSION_LIMIT` | `25` | Max agent-loop iterations (LangGraph `recursion_limit`) |
| `ORYA_RECOVERY_MAX_ROUNDS` | `3` | How many times a failed tool batch may trigger the recover node (M-28) |
| `ORYA_RECOVERY_VARIANTS` | `5` | Alternative approaches the recover nudge asks the model for |
| `ORYA_CONTEXT_MAX_TOKENS` | `120000` | Context-window budget; history is trimmed to fit (M-06) |

### Auth / CORS (A-00)

| Env var | Default | Description |
|---|---|---|
| `AUTH_ENABLED` / `ORYA_AUTH_ENABLED` | `false` | Kill-switch: Bearer-JWT enforcement on all non-public endpoints |
| `AUTH_SECRET_KEY` / `ORYA_AUTH_SECRET_KEY` | — | HS256 signing secret (≥ 32 chars); required when auth is on — also used by `orya auth token` |
| `AUTH_ALGORITHM` / `ORYA_AUTH_ALGORITHM` | `HS256` | JWT algorithm |
| `AUTH_TOKEN_TTL_S` / `ORYA_AUTH_TOKEN_TTL_S` | `86400` | Lifetime of tokens minted by `orya auth token` |
| `AUTH_PUBLIC_PATHS` / `ORYA_AUTH_PUBLIC_PATHS` | `/health,/docs,/redoc,/openapi.json,/metrics` | CSV (or JSON array) of path prefixes exempt from JWT |
| `CORS_ORIGINS` / `ORYA_CORS_ORIGINS` | `*` | CSV of allowed browser origins |

### Rate limit (A-01)

| Env var | Default | Description |
|---|---|---|
| `RATE_LIMIT_ENABLED` / `ORYA_RATE_LIMIT_ENABLED` | `false` | Kill-switch: 429 + `Retry-After` per request |
| `RATE_LIMIT_RPM` / `ORYA_RATE_LIMIT_RPM` | `60` | Per-user requests-per-minute on every endpoint |
| `RATE_LIMIT_LEARN_RPM` / `ORYA_RATE_LIMIT_LEARN_RPM` | `10` | Tighter per-user RPM for `/learn` (anti-abuse) |
| `RATE_LIMIT_BACKEND` / `ORYA_RATE_LIMIT_BACKEND` | `auto` | `auto` \| `memory` \| `redis` |
| `ORYA_TRUSTED_CLIENTS` | — | CSV/JSON list of user ids or client IPs exempt from limiting |

### UI (M-15/M-17/M-24)

| Env var | Default | Description |
|---|---|---|
| `ORYA_API_URL` | `http://127.0.0.1:8000` | FastAPI base URL the Chainlit UI calls over HTTP/SSE |
| `CHAINLIT_PORT` / `ORYA_CHAINLIT_PORT` | `8001` | Chainlit port (`make ui`, start scripts) |
| `ORYA_UI_SETTINGS_PATH` | `~/.orya/settings.json` | Settings-panel state: model, permission mode, allow-list |
| `NEXTJS_PORT` / `ORYA_NEXTJS_PORT` | `3000` | Next.js UI port (BETA placeholder) |

### Misc / infra

| Env var | Default | Description |
|---|---|---|
| `LOG_LEVEL` / `ORYA_LOG_LEVEL` | `INFO` | Python logging level |
| `ORYA_CONFIG_PATH` | `~/.orya/config.yaml` | Relocates the user YAML config file |
| `ORIAHS_URL` / `ORYA_ORIAHS_URL` | — | OriaHS endpoint (PROD placeholder) |
| `ORIAHS_TIMEOUT_S` / `ORYA_ORIAHS_TIMEOUT_S` | `30` | OriaHS request timeout |
| `POSTGRES_PORT` | `5432` | Host port published by docker compose (not read by the app) |
| `REDIS_PORT` | `6379` | Host port published by docker compose (not read by the app) |
| `API_PORT` | `8000` | API port for the start scripts |

Provider API keys (`DEEPSEEK_API_KEY`, `DASHSCOPE_API_KEY`, `ZHIPUAI_API_KEY`, `OPENROUTER_API_KEY`, …) are read by the per-provider adapters via `providers.yaml` — see `.env.example` and [LLM Providers (M-01)](#llm-providers-m-01).

## Project Structure

```
app/
├── main.py              # FastAPI entry point + orya CLI
├── core/                # Core components (M-01+)
│   ├── auth/            # JWT issuance/verification (A-00)
│   ├── memory/          # L0 MDStore memory seam (M-25)
│   └── observability/   # span buffer + emitters (A-02/A-03)
├── tools/               # Coding tools (M-07+)
├── api/                 # API endpoints (M-20+): middleware (A-00), health (A-04)
└── ui/                  # Chainlit UI (M-15+)
scripts/                 # one-command start/stop (sh + ps1)
tests/                   # Test suites
└── conftest.py          # Test configuration
```

## Database (M-03)

PostgreSQL stores session metadata, typed messages, tool-call audit and the memory audit log; LangGraph checkpoints live in separate tables managed by `AsyncPostgresSaver`.

- **Schema:** `app/db/schema.sql` (canonical) — tables `sessions`, `messages`, `tool_calls`, `memory_audit_log`.
- **Migrations:** plain SQL files in `app/db/migrations/` (`NNNN_name.sql`), tracked in `schema_migrations`, applied idempotently:

  ```bash
  make db-up       # start PostgreSQL via docker compose
  make db-migrate  # apply pending migrations (or: orya db migrate / python -m app.db.migrate)
  ```

  Host port conflicts can be resolved with `POSTGRES_PORT=5435 make db-up` (plus a matching `DATABASE_URL`).
- **Pool:** `from app.db import get_asyncpg_pool` — lazy asyncpg singleton from `settings.database_url` / `DATABASE_POOL_SIZE` / `DATABASE_MAX_OVERFLOW`.
- **Checkpoints (M-04 wiring):** `from app.db.checkpoints import get_checkpointer` — `AsyncPostgresSaver` over the same database; `setup()` creates/migrates `checkpoints*` tables. On Windows, psycopg requires a `SelectorEventLoop` (uvicorn already uses one).

## System Prompt (M-05)

`app/core/prompt.py::build_system_prompt(state, tools) -> list[BaseMessage]` assembles the agent's system message from six independently testable sections:

1. **Identity** — who the agent is and its working style (static, cacheable prefix).
2. **Tool descriptions** — each tool rendered as OpenAI-function JSON via `convert_to_openai_function`.
3. **Project context** — working directory, best-effort `git status`, and `PROJECT.md` from the memory dir.
4. **Long-term memory** — `LEARNED.md` + `PREFERENCES.md` + `FACTS.md` + `DECISIONS.md` read through the M-25 `MDStore` seam, capped at 8 KB.
5. **Behavior rules** — workspace hygiene, atomic edits, destructive-op confirmation (static).
6. **Untrusted-content policy** — tool results / file content are data, never instructions (M-22, prompt side).

Stable sections come first so the prompt keeps a cacheable prefix for the ALPHA PromptCacheLayout; dynamic data (git, memory files) follows. The M-04 graph prepends the returned `SystemMessage` to the conversation — the builder never returns history.

To add a new section: write a `*_block()` function returning `str` and append it in `build_system_prompt`; add a test in `tests/unit/test_prompt.py`.

## Context Manager (M-06)

`app/core/context.py::trim_messages(messages, max_tokens=None) -> list[BaseMessage]` keeps the conversation within the context-window budget before each model call (default 120 000 tokens, `ORYA_CONTEXT_MAX_TOKENS`):

1. **Tool-result truncation** — `ToolMessage` over 5 000 chars keeps the first 100 and last 50 lines with a `[N lines truncated]` marker (M-23 token-efficient output).
2. **Thinking strip** — `reasoning_content` emitted by reasoning models (DeepSeek-R1, o1, GLM-Zero) is removed from the history; the final answer survives.
3. **Sliding window** — LangChain `trim_messages` with `strategy="last"` (newest turns win), `start_on="human"` (never start mid-turn), `include_system=True` (a `SystemMessage` always survives), `allow_partial=False`.

Token counting uses `tiktoken` for known OpenAI-family models and falls back to a `chars/4` approximation for every other provider (Claude, Gemini, DeepSeek, local models) — `encoding_for_model` is never called for unknown models.

The M-04 graph does not import this module: it accepts an optional `trim_fn` seam on `build_graph()` (same pattern as `system_prompt_fn`), so `agent_node` trims the history before prepending the freshly built system prompt. `trim_state(state)` is a thin wrapper returning a `{"messages": ...}` state update.

v7 BETA will replace the implementation with DFC (5 layers) — the `trim_messages(messages, max_tokens) -> list[BaseMessage]` signature is an architectural invariant and stays.

## Permissions (M-13)

`app/core/permissions.py::PermissionPolicy` gates every pending tool call before it reaches the tool node; the graph's `human` review node pauses on `ask` via LangGraph's dynamic `interrupt()` (M-04 wiring).

Decision precedence — first match wins:

1. **Deny-list** — catastrophic bash patterns (`rm -rf /`, fork bombs, `dd` to disk, piped remote scripts); wins over everything, including the session allowlist.
2. **Session allowlist** — tools approved with "don't ask again" (`resume_command("always")`, `record_session_allow`).
3. **Allow-list** — safe calls bypass the mode: `read`/`grep`/`glob`, read-only bash (`ls`, `cat`, `pwd`, `git status|diff|log|branch`, `head`, `tail`, `wc`, ...).
4. **Mode** — `strict` (default) asks on `write`/`edit`/`bash`; `permissive` asks only on `bash` containing `rm`/`mv`/`sudo`.

Explicit user commands (`/learn`, `/memory/*`) never interrupt. When a batch mixes refused and allowed calls, the whole batch is refused (providers require exactly one `ToolMessage` per tool-call id). Without a checkpointer, `ask` is denied (fail-closed).

Mode is selected with `ORYA_PERMISSION_POLICY=strict|permissive`; rules are overridden per user in `~/.orya/permissions.yml` (a present key replaces the built-in list for that section):

```yaml
allow_rules:
  - tool: bash
    pattern: '^npm(\s+|$).*'
    description: npm commands
deny_rules:
  - tool: bash
    pattern: 'rm\s+-rf?\s+/(\s|$)'
    description: rm -rf on filesystem root
```

Resuming a paused run: `resume_command("approve")` runs the call, `"deny"` refuses it, `"always"` approves and stops asking about this tool for the rest of the session; unknown answers are treated as a denial (fail-closed).

## Session-log (M-14)

`app/db/session_log.py` keeps two complementary views of a session:

1. **Typed `messages` rows** (PostgreSQL) — `log_message(session_id, role, content, tool_calls, tool_call_id)` assigns `MAX(seq)+1` within the session and ensures the parent `sessions` row exists (M-03 schema). Query-friendly log for the UI/API layers.
2. **JSONL projection** — an append-only `~/.orya/sessions/{session_id}.jsonl` file derived from the LangGraph `AsyncPostgresSaver` checkpoints, one event per line:
   ```json
   {"ts": "2026-01-01T00:00:02+00:00", "type": "tool", "payload": {"message_id": "...", "content": "echo: hi", "tool_call_id": "call_1"}}
   ```
   `type` is `user` / `ai` / `tool` / `system`. Used for replay, debug and audit.

Projection is idempotent: each thread has a `{session_id}.meta.json` marker (`last_processed_ts`); a projection run only processes newer checkpoints and only emits messages that appeared since the previous snapshot, so re-running the worker appends nothing. The directory comes from `ORYA_SESSIONS_DIR` (default `~/.orya/sessions`).

A background projection worker starts with the FastAPI app (lifespan in `app/main.py`) and periodically discovers threads from the `checkpoints` table. It soft-fails without PostgreSQL — the API stays up and retries on the next pass.

### Encryption at rest (A-05)

With `SESSION_LOG_ENCRYPTION_ENABLED=true` and `SESSION_LOG_ENCRYPTION_KEY` (≥ 16 chars — validation fails fast otherwise), `log_message()` encrypts the payload columns through PostgreSQL `pgcrypto` (`pgp_sym_encrypt`, armored ASCII) and `list_messages()` decrypts them:

- **Covered:** `messages.content` (TEXT) and `messages.tool_calls` (JSONB, ciphertext wrapped via `to_jsonb(armor(...))`).
- **Not covered:** LangGraph checkpoint tables — they are written by `AsyncPostgresSaver` outside the app writer; at-rest protection for the whole database belongs at the volume/disk layer.
- **Legacy tolerance:** rows written before encryption (plaintext) still decrypt — the reader only applies `pgp_sym_decrypt` when the payload carries `-----BEGIN PGP MESSAGE-----`.
- **Off by default** (dev/tests keep byte-identical plaintext); enabling requires migration `0002_session_log_encryption.sql` (`CREATE EXTENSION IF NOT EXISTS pgcrypto`).

### Span cross-link (A-06)

The JSONL projection is additive: every event carries the observability ids of the turn it belongs to — `trace_id` on user/ai/tool events and `span_id` where the emitter knows it (AI/tool-call messages stamped from `additional_kwargs["orya_span"]`). One LangGraph turn shares one `trace_id` (the turn-trace contextvar set by the runtime), so a future Langfuse trace (A-15) and the local JSONL projection can be joined on it. v1 readers are unaffected — the fields are top-level additions consumed with `.get()`.

## Sessions API (M-20)

`app/api/sessions.py` exposes the session lifecycle for every client: CI and batch jobs over JSON, the Chainlit UI (M-24) over SSE. The UI never touches the graph — `Chainlit → FastAPI → LangGraph` — and both response modes share the session-agent runtime in `app/core/agent.py` (graph assembly, checkpointer fallback, `stream_turn`/`run_turn`).

| Endpoint | Purpose |
|---|---|
| `POST /sessions` | Create a session (server-side uuid4) → `{session_id, created_at, status, ...}` |
| `GET /sessions?page=1&size=20` | Paginated list, newest activity first → `{items, total, page, size}` |
| `GET /sessions/{id}` | Metadata + typed `messages` (M-14 log), 404 when unknown |
| `POST /sessions/{id}/messages` | Run one full turn — JSON by default, SSE stream with `?stream=true` (see below) |
| `POST /sessions/{id}/resume` | Answer a pending permission interrupt: `{decision: "allow"\|"deny"\|"always"}`, 409 when nothing is pending; also streamable with `?stream=true` |
| `PATCH /sessions/{id}` | Open/close the project directory: `{working_dir: "..."}` (validated, persisted on the row) or `{working_dir: null}` to close; 400 on an unusable path |
| `GET /workspace/browse?path=…` | Subdirectory listing for the UI's «Open project» folder picker — dirs only, sorted, capped at 200 (`truncated: true`); default path is the server cwd; `parent: null` at a filesystem root |
| `DELETE /sessions/{id}` | Soft-delete — flips `sessions.status` to `closed`, history kept for audit |

`POST /sessions/{id}/messages` accepts `{"content": "..."}` and returns:

```json
{
  "session_id": "...",
  "status": "ok",
  "reply": "final answer text",
  "tool_steps": [{"run_id": "...", "tool": "read", "args": {"path": "..."}, "output": "...", "from_cache": false}],
  "pending_interrupt": null,
  "degraded": false
}
```

- `status: "interrupted"` — the run paused at the M-13 permission gate; `pending_interrupt` carries `{tool, args, reason}` and the client answers via `POST /sessions/{id}/resume`. A resumed batch may pause again (one tool call per interrupt).
- `degraded: true` — PostgreSQL checkpointer was unavailable, state lives in memory (mirrors the UI fallback).
- DB failures return `503 {"detail": "database unavailable"}`; a failed run returns `502`.
- The permission policy is cached per session process-wide, so «Approve & don't ask again» (M-13 session allowlist) survives across API calls within the process lifetime.
- Interactive docs: `http://localhost:8000/docs` (OpenAPI).

### Opening a project from the chat (folder picker)

The Chainlit UI opens a project folder in the main chat window: the **Open project** button (next to the session list) or the `/open` command (`/open /path/to/project` opens a path directly) starts a clickable folder browser — subdirectories, `.. (up)`, **Open this folder**, **Cancel**. The picker is a **single chat message rewritten in place**: clicking **Open project** again or navigating updates it instead of stacking another window whose stale buttons act on a different message. Folder buttons carry a folder icon with the full path as tooltip, the commands their own icons (`up` / `open` / `cancel`). The pick is applied immediately (`PATCH /sessions/{id}`) and saved as the UI default, so new sessions open the same project; the settings panel's *Working directory* field stays in sync. The browser lists directories only, through `GET /workspace/browse` — the Chainlit process never touches the filesystem itself. The session sidebar works the same way (one message, refreshed on **New session** / session switch).

### SSE streaming (M-24)

`POST /sessions/{id}/messages?stream=true` (and `/resume?stream=true`) returns `text/event-stream` instead of a buffered JSON turn — this is the transport the Chainlit UI uses:

| Frame | Data |
|---|---|
| `token` | `{"content": "..."}` — one streamed model chunk |
| `tool_start` | `{"run_id", "tool", "args"}` |
| `tool_end` | `{"run_id", "tool", "output", "from_cache"}` — `from_cache: true` marks an M-21 cache hit |
| `interrupt` | `{"tool", "args", "reason"}` — the run paused at the M-13 permission gate |
| `error` | `{"detail"}` — a failure after the response started (always followed by `done`) |
| `done` | `{"session_id", "status", "reply", "tool_steps", "pending_interrupt", "degraded"}` — terminal frame |

Both turn endpoints also accept the UI settings-panel overrides — `model`, `permission_mode`, `allow_list` — and the server builds the model/policy for the session from them (the M-13 session allowlist is carried over when the settings change). In stream mode the session-log writes are best-effort: a database outage reports `degraded: true` instead of `503`, so a live chat is never aborted.

```bash
curl -N -X POST "localhost:8000/sessions/$SID/messages?stream=true" \\
  -H 'content-type: application/json' -d '{"content":"run the tests"}'
```

Example:

```bash
SID=$(curl -s -X POST localhost:8000/sessions -H 'content-type: application/json' \
  -d '{"title":"ci run"}' | python -c "import sys,json;print(json.load(sys.stdin)['session_id'])")
curl -s -X POST localhost:8000/sessions/$SID/messages \
  -H 'content-type: application/json' -d '{"content":"run the tests"}'
```

## Authentication (A-00)

FastAPI-level Bearer-JWT enforcement as pure ASGI middleware (so SSE streams pass through unbuffered). **Off by default** (`AUTH_ENABLED=false`) for dev/tests compatibility.

| Piece | Behavior |
|---|---|
| Token | HS256 JWT; `sub` claim = user id (`request.state.user_id`), default TTL 86 400 s (`AUTH_TOKEN_TTL_S`) |
| Enforcement | every endpoint except `AUTH_PUBLIC_PATHS` (`/health`, `/docs`, `/redoc`, `/openapi.json`, `/metrics`) answers `401` without a valid `Authorization: Bearer <token>` |
| Secret | `AUTH_SECRET_KEY` must be ≥ 32 chars; auth without it fails fast |
| Request id | every response carries `X-Request-ID` (echoed from the request or minted — even on 401) |
| CORS | `CORS_ORIGINS` (CSV, default `*`) |
| Identity | the JWT `sub` feeds the A-01 per-user rate-limit buckets |

Operator loop — mint a token on the server, then call the API:

```bash
# server-side (e.g. in .env or the service environment)
export AUTH_ENABLED=true
export AUTH_SECRET_KEY="$(python -c 'import secrets; print(secrets.token_urlsafe(48))')"

# mint a token — the raw JWT goes to stdout
TOKEN=$(uv run orya auth token --user alice)

curl -s -H "Authorization: Bearer $TOKEN" -H 'content-type: application/json' \
  -d '{"title":"deploy check"}' http://localhost:8000/sessions

# without the header the same call is rejected
curl -s -o /dev/null -w '%{http_code}\n' -X POST \
  -H 'content-type: application/json' -d '{}' http://localhost:8000/sessions
# -> 401
```

`orya auth token` signs with `AUTH_SECRET_KEY` (required even when the middleware kill-switch is off). The Chainlit UI has no login flow yet (UI login is outside ALPHA scope) — with auth enabled, drive the API from scripts/CI, or keep `AUTH_ENABLED=false` on localhost.

## Rate limiting (A-01)

Per-user request budgets enforced by middleware, **off by default** (`RATE_LIMIT_ENABLED=false`):

| Bucket | Default | Scope |
|---|---|---|
| Per-user | `RATE_LIMIT_RPM=60` | every endpoint, keyed by JWT `sub` (or client IP when auth is off) |
| `/learn` | `RATE_LIMIT_LEARN_RPM=10` | `POST /learn` + `POST /sessions/{id}/learn` — tighter anti-abuse bucket |

Over-budget requests answer `429` with `Retry-After` (seconds) plus `x-ratelimit-limit` / `x-ratelimit-remaining: 0` headers. `RATE_LIMIT_BACKEND=auto` uses Redis when it is reachable and falls back to an in-process limiter (`memory` pins the fallback, `redis` fails fast). `ORYA_TRUSTED_CLIENTS` (CSV of user ids or client IPs) exempts operators from limiting.

## Health endpoints (A-04)

| Endpoint | Purpose |
|---|---|
| `GET /health` | Liveness — `{"status": "ok", "message": "OryaAgent API is running"}`; always public, no auth |
| `GET /health/observability` | Observability seam — `{"sdk_enabled", "exporter_connected", "guardrail_ready", "span_buffer_size"}` |
| `GET /health/sampler-proxy` | Probes `ORYA_SAMPLER_PROXY_URL/sampler/status` — `200` when reachable, `503` when unconfigured/unreachable (the proxy itself ships with A-17) |

All three are JWT-exempt public paths, so load balancers and uptime checks work without credentials.

## LLM tracing & audit spans (A-02, A-03)

Every model returned by `get_llm()` is wrapped in `TracedChatModel`: one `llm.call` span per invocation (provider, model, tokens, duration) buffered in-process. Permission decisions add `agent.permission` spans. The seam is fail-soft — span emission never raises into the agent loop.

| Knob | Effect |
|---|---|
| `ORYA_LLM_TRACE_ENABLED` (default `true`) | `false` returns the raw provider adapter — zero spans, zero overhead |
| `ORYA_LLM_TRACE_EXPORTER=stdout` | each finished span also prints as a JSON debug line (default: buffer only) |
| `ORYA_PERMISSION_AUDIT_ENABLED` (default `true`) | permission-decision audit spans |
| `GET /health/observability` | live view of the buffer and kill-switch state |

Spans carry `trace_id`/`span_id`; the same ids land in the JSONL projection (A-06), which is the offline cross-link until the Langfuse exporter ships (see [Langfuse setup](#langfuse-setup-planned--a-15a-16a-17)). Smoke coverage: `tests/smoke/test_smoke_v2.py` scenario 5 drives a scripted turn and asserts the span → health chain.

## Tool-result cache (M-21)

Repeated tool calls for unchanged files are served from a cache instead of re-running the tool (TRIZ #28). The seam lives in `app/core/cache.py`:

- **Keys:** `orya:tool_cache:{tool}:{sha256(args + mtime_ns)}` — the file mtime is part of the key, so any change makes the next call a miss automatically.
- **Backends:** `CacheWrapper` (Redis) is the primary backend; `ORYA_CACHE_BACKEND` selects `auto` (probe Redis at startup, fall back to `MemoryCache` with a warning — the default), `redis` (fail fast) or `memory` (never touch Redis). TTL is `ORYA_CACHE_TTL_SECONDS` (default 300s per BACKLOG5).
- **LRU eviction:** `MemoryCache` has configurable capacity (`ORYA_CACHE_MAX_ENTRIES=1024`); 0 = unlimited. Entries are evicted LRU when the capacity is exceeded. Redis uses server-side LRU (`maxmemory 256mb --maxmemory-policy allkeys-lru` in docker-compose).
- **Cacheable:** `read`, `grep`, `glob`. Never cached: `write`, `edit`, `bash` (side effects) — write/edit instead call `invalidate_cache_for_path()` (`app/hooks/cache_invalidation.py`), which drops every entry registered for the changed path through the Redis `orya:tool_cache:idx:{path}` index.
- **Cache-hit marker:** when a tool call goes through the graph, a hit returns a `ToolMessage` with `metadata={"from_cache": true}` (direct `ainvoke()` calls keep returning the plain payload).
- **Stats:** process-local per-tool counters (Redis additionally mirrors `orya:cache_stats:{date}:{tool}` hashes).

```bash
make redis-up   # start Redis (docker compose), optional — auto mode falls back to memory
curl -s localhost:8000/metrics            # Prometheus text: orya_tool_cache_hits_total{tool="read"}
curl -s localhost:8000/tools/cache-stats  # {"backend": "...", "max_entries": 1024, "evictions": 0, "tools": {"read": {"hits": 1, "misses": 1, "hit_rate": 0.5}}}
```

Host port conflicts can be resolved with `REDIS_PORT=6381 make redis-up` (plus a matching `REDIS_URL`).

## Token-efficient output (M-23)

Every tool returns the smallest document that still carries the information (TRIZ #28, mechanics substitution); `tests/unit/test_token_efficiency.py` locks the contract in and measures the savings (aggregate ≈73%, every typical fixture ≥30%):

| Tool | Output contract |
|---|---|
| `read` | line-numbered window (2 000 lines), `[truncated: lines X-Y hidden ...]` marker, 10 MB size cap |
| `write` | `Wrote {n} bytes to {path}` |
| `edit` | `Edited {path}: replaced {n} occurrence(s)` |
| `bash` | JSON `{stdout, stderr, exit_code, duration_ms, truncated}` — streams capped at 5 000 chars (2 500 head + `... [N chars truncated] ...` + 2 500 tail), ≥100 identical consecutive lines collapse to `... [N identical lines] ...` |
| `grep` | JSON `{matches: [{file, line, content}], count, truncated}` — max 500 matches per call (`max_matches`) |
| `glob` | JSON `{files: [...], count, truncated}` — max 500 paths per call |

The second layer sits in the context manager: any `ToolMessage` over 5 000 chars is cut to the first 100 / last 50 lines before it reaches the model (M-06 pipeline, M-23 marker).

## Long-term memory (M-25)

`app/core/memory/` is the L0 memory seam: six human-readable MD files in `settings.memory_dir` (default `~/.orya/memory`, `ORYA_MEMORY_DIR`), created empty on first use.

| File | Budget | Purpose |
|---|---|---|
| `PROJECT.md` | 8 KB | project mission / stack / conventions — injected in the project-context block |
| `LEARNED.md` | 4 KB | facts learned through `/learn` (M-26) |
| `PREFERENCES.md` | 2 KB | user and project preferences |
| `FACTS.md` | 2 KB | critical project facts |
| `DECISIONS.md` | 2 KB | short ADR-style decisions |
| `MEMORY_INDEX.md` | 8 KB | L1/L2 index (empty placeholder until BETA) |

```python
from app.core.memory import get_md_store

store = get_md_store()  # cached MDStore for settings.memory_dir
store.append("LEARNED.md", entry)  # atomic: one O_APPEND write + fsync
store.read("PROJECT.md")  # str ("" when blank or missing)
store.read_all()  # dict of all six files (prompt input)
store.mtime("LEARNED.md")  # for cache invalidation
store.stats()  # bytes / entries / last_write / over_limit
```

- **Atomicity:** one `os.write` into an `O_APPEND` descriptor plus `fsync`, serialized by a per-file `threading.Lock` (`fcntl.flock` advisory locking where POSIX provides it). Concurrent appends lose no entries and a crash never tears a record; full-file rewrites (M-27 compaction) go through `tmp` + `os.replace`.
- **Budget:** an append that pushes a file past its budget schedules `compact_if_needed()`, which the M-27 Compactor executes asynchronously (see below).
- **Audit:** every append is recorded best-effort in `memory_audit_log`, falling back to `{memory_dir}/audit/memory_audit.jsonl` when PostgreSQL is unreachable.
- **Records:** entries follow the ARCHITECT6 §3.1.1 block format (`- [fact] id=... | confidence=... | source=... | ts=...` + indented text) — `MemoryItem.to_markdown()` / `parse_entries()` round-trip, and hand-edited free text stays valid.
- **Prompt:** `format_memory_block()` injects LEARNED / PREFERENCES / FACTS / DECISIONS through the same seam, capped at 8 KB.

## `/learn` (M-26)

Two endpoints write into the L0 files through the `MDStore` seam:

| Endpoint | Body | Effect |
|---|---|---|
| `POST /sessions/{id}/learn` | `{pattern_name?, description?, scope?}` | Extracts the session's **last successful tool-call sequence** from the JSONL projection (M-14), renders a `[learned]` block in the ARCHITECT6 §3.1.1 format and appends it to `LEARNED.md`. `pattern_name` defaults to the auto-name `grep_read_edit`; `400 "No successful tool-call sequence to learn"` when the last turn has no successful tool call (error, non-zero bash exit, permission refusal). |
| `POST /learn` | `{content, category: "fact"\|"preference"\|"project"}` | Appends `content` to `FACTS.md` / `PREFERENCES.md` / `LEARNED.md` (PROMPT_MVP contract for CI/batch clients). |

Both answer `{status, learned_id, file, compacted, line_count}`; `compacted` reports that the file is over budget — the compaction itself runs asynchronously through the M-27 Compactor. Every call additionally writes an `action="learn"` audit record carrying `memory_id` / `source` / `trace_id` (own fields in the JSONL fallback, folded into `reason` for the PostgreSQL row).

In the Chainlit UI, `/learn [name] [description]` calls the session endpoint and replies ``✅ Learned: `learn_001` → LEARNED.md (compacted: false)`` — no confirmation prompt, and the entry is visible to the model from the next turn (`format_memory_block()` reads the same files).

## Compactor (M-27)

`app/core/memory/compactor.py` keeps the L0 files within budget with strategy-based *soft* compaction: rejected blocks move to `~/.orya/memory/archive/{stem}_{YYYYMMDD}.md` (append-only — same-day runs append to the same file) and the L0 file is rewritten atomically under its per-file lock. Nothing is ever deleted — with no L1 store in the MVP (that is B-21), the archive is the cold tier.

| Endpoint | Effect |
|---|---|
| `POST /memory/compact` · `POST /sessions/{id}/memory/compact` | Synchronously compacts the four strategy files: `{status, results: [{file, changed, before_bytes, after_bytes, kept, archived, archive_path, over_limit}], total_archived}`. |
| `GET /memory/stats` · `GET /sessions/{id}/memory/stats` | `{files: [{name, size_bytes, entries_count, line_count, token_count, last_write_ts, max_bytes, over_limit}], total_size_bytes, line_counts, token_counts, last_compacted}` — the union of the PROMPT_MVP and BACKLOG6 shapes (tokens are the `chars/4` approximation). |
| `GET /memory` · `GET /sessions/{id}/memory` | The four files as `{files, markdown}` — `markdown` is the concatenation the AC asks for. |

Strategies (ARCHITECT6 §4.2.2): `PREFERENCES.md` archives only `agent_inferred` entries with confidence < 0.8; `LEARNED.md` keeps the last 10 entries and everything with confidence ≥ 0.9, then archives the oldest kept entries until the file fits its 4 KB budget; `FACTS.md` keeps confidence ≥ 0.9; `DECISIONS.md` archives blocks carrying a superseded marker (`superseded_by=` / `[superseded]` / `superseded:`). `PROJECT.md` and `MEMORY_INDEX.md` have no strategy — they appear in stats but are never compacted (they are context, not scored records).

- **Triggers:** an append over budget (`MDStore._maybe_compact`, async), the endpoints above, and a periodic worker started by the FastAPI lifespan every `ORYA_MEMORY_COMPACT_INTERVAL_SECONDS` (default 86400; `0` disables it).
- **Crash safety:** the archived blocks land in the archive *first*, then the rewrite goes tmp + `fsync` + `os.replace` — a crash can only duplicate, never lose, and never leaves a partial file.
- **Audit:** every run writes a `memory.compact` row (trigger / kept / archived / byte delta in `reason`) and stamps `{memory_dir}/compaction.json`, the `last_compacted` field of `/memory/stats`.
- **UI:** `/memory`, `/memory stats`, `/memory compact` (and the `/memory/…` spellings) render the content, a stats table or the per-file report — never a chat turn.

## Documentation

- [Architecture v7](analytics/ARCHITECT7.md)
- [Roadmap v7](analytics/ROADMAP7.md)
- [Backlog v7](analytics/BACKLOG7.md)
- [MVP Phase Prompt](analytics/PROMPT_MVP.md)
- [ALPHA Phase Prompt](analytics/PROMPT_ALPHA.md)

## Phase Progress

- ✅ **M-00** - Bootstrap project structure
- ✅ **M-01** - LLM-provider-seam: `get_llm()`, 34 providers (YAML registries), importers, `/llm/*` endpoints
- ✅ **M-02** - pydantic-settings configuration: `Settings`, `~/.orya/config.yaml` merge, env/.env priority
- ✅ **M-03** - PostgreSQL schema: `schema.sql` (4 tables), asyncpg pool, SQL migrations (`orya db migrate`), PostgresSaver checkpoints
- ✅ **M-04** - LangGraph core: StateGraph agent-loop, permission-review node, `interrupt_before` ask-mode, run config
- ✅ **M-05** - System-prompt builder: `build_system_prompt()` with identity, tools, project context, L0 memory, behavior rules, untrusted-content policy
- ✅ **M-06** - Context manager: `trim_messages()` — tool-result truncation, thinking strip, sliding window (`trim_fn` seam in the graph)
- ✅ **M-07** - Tool `read`: line-numbered pagination, path validation, untrusted-content framing, cache seam (M-21)
- ✅ **M-08** - Tool `write`: atomic write (tmp + `os.replace`), `create_dirs`, path validation, registry wiring
- ✅ **M-09** - Tool `edit`: exact string replacement, uniqueness guard, `replace_all`, atomic rewrite, registry wiring
- ✅ **M-10** - Tool `bash`: JSON output (stdout/stderr/exit_code/duration_ms/truncated), char-based truncation, line dedup, injection detection, allowlist-env, timeout/cancel process kill
- ✅ **M-11** - Tools `grep`/`glob`: ripgrep-backed search, JSON token-efficient output (`matches`/`files` + truncation flag), injection detection, untrusted framing, path validation, cache seam
- ✅ **M-12** - Tool-registry integration: `get_tools()` full 6-tool list, `graph.bind_tools` wiring, integration tests (full-cycle agent→tools→agent e2e + offline real-model bind/schema check)
- ✅ **M-13** - Permissions: `PermissionPolicy` (strict/permissive), deny→session→allow→mode rule precedence, session allowlist, interrupt-driven ask via the graph's permission-review node
- ✅ **M-14** - Session-log: typed `messages` writer (`log_message`), JSONL projection of PostgresSaver checkpoints (`~/.orya/sessions/{id}.jsonl`, ts-deduped), background projection worker (FastAPI lifespan)
- ✅ **M-15** - Chainlit UI: `on_chat_start` / `on_message`, normalized streaming (`token`/`tool_start`/`tool_end`), Postgres checkpointer with in-memory fallback — since M-24 routed through FastAPI SSE
- ✅ **M-16** - Permission ask-prompt: `cl.AskActionMessage` with Approve / Deny / don't-ask-again, resume loop until the batch completes
- ✅ **M-17** - Sidebar & settings: session list from JSONL + DB titles, session switching with history restore, model/permission/allow-list panel (`~/.orya/settings.json`)
- ✅ **M-18** - Smoke tests: 5 canonical tasks (read/explain, atomic edit, bash+pytest, grep report, `/learn`) + cache/injection/JSON checks
- ✅ **M-20** - Sessions API: `/sessions` CRUD (create, paginated list, metadata+messages, soft-delete), full-turn `POST /sessions/{id}/messages` (JSON with `tool_steps`/`pending_interrupt`), `POST /sessions/{id}/resume` for the M-13 permission gate; shared session-agent runtime (`app/core/agent.py`); SSE mode added by M-24
- ✅ **M-21** - CacheWrapper: Redis backend (`ORYA_CACHE_BACKEND=auto|memory|redis`, TTL `ORYA_CACHE_TTL_SECONDS`), per-path invalidation hook on write/edit, `from_cache` ToolMessage metadata, `/metrics` (Prometheus text) + `/tools/cache-stats`
- ✅ **M-22** - Prompt injection defense: pattern detection in `read`/`bash`/`grep` output (warning travels inside the payload), `sanitize_untrusted()` framing, `memory_audit_log` audit rows, `orya_prompt_injection_warnings_total` metric, prompt-side policy block
- ✅ **M-23** - Token-efficient output: compact structured contracts for all six tools (JSON bash/grep/glob, capped windows, dedup), `truncate_tool_messages()` second layer, token-count tests proving ≥30% savings on typical tool-results
- ✅ **M-24** - Chainlit via FastAPI: SSE streaming endpoints (`?stream=true` on `/messages` + `/resume`; `token`/`tool_start`/`tool_end`/`interrupt`/`done`/`error` frames), settings overrides (model/mode/allow-list) resolved server-side, UI rewritten as an httpx client with no direct graph access, `from_cache` propagated into `tool_end`/`tool_steps`
- ✅ **M-25** - Long-term memory: `MDStore` L0 (six MD files in `ORYA_MEMORY_DIR`, atomic `O_APPEND`+`fsync` append with per-file locks, size budgets + compaction hook, best-effort `memory_audit_log` audit), `MemoryItem` record model, system prompt reads L0 through the store seam
- ✅ **M-26** - `/learn`: `POST /sessions/{id}/learn` (last successful tool sequence from the M-14 JSONL projection → `[learned]` block in `LEARNED.md`, auto pattern names, 400 on a failed last call), `POST /learn` content contract (`fact|preference|project`), Chainlit `/learn [name] [description]` slash-command, `learn` audit records (`memory_id`/`source`/`trace_id`)
- ✅ **M-27** - Compactor: strategy-based soft compaction into `memory/archive/` (4 strategies + LEARNED size-guard, archive-first crash ordering, locked atomic rewrite), union endpoints `POST /memory/compact` + `GET /memory/stats` + `GET /memory` (and their `/sessions/{id}/memory*` twins), `memory.compact` audit + `compaction.json`, periodic worker (`ORYA_MEMORY_COMPACT_INTERVAL_SECONDS`), Chainlit `/memory [stats|compact]` commands, M-18 memory-AC unblocked (smoke task 5, `/memory/stats`, append durability)
- ✅ **M-28** - Failure recovery: `assess` triages failed tool batches and the `recover` node asks the model for alternatives (`ORYA_RECOVERY_MAX_ROUNDS` / `ORYA_RECOVERY_VARIANTS`), recover-node tokens dropped from the streamed reply
- ✅ **A-00** - Auth middleware: pure-ASGI Bearer-JWT enforcement (`AUTH_ENABLED` kill-switch, secret ≥ 32 chars fail-fast), public paths, CORS, `X-Request-ID` echo/mint, CLI `orya auth token`
- ✅ **A-01** - Rate limit: per-user 60 rpm + `/learn` 10 rpm buckets, `429` + `Retry-After`/`x-ratelimit-*`, Redis/memory seam (`ORYA_RATE_LIMIT_BACKEND`), `ORYA_TRUSTED_CLIENTS` whitelist
- ✅ **A-02** - LLM-seam trace-wrapping: `TracedChatModel` emits one `llm.call` span per `get_llm()` call (`ORYA_LLM_TRACE_ENABLED` kill-switch, in-process span buffer, `stdout` debug exporter)
- ✅ **A-03** - Permission audit spans: `agent.permission` spans with security attributes on permission decisions (`ORYA_PERMISSION_AUDIT_ENABLED`)
- ✅ **A-04** - Health endpoints: `/health`, `/health/observability`, `/health/sampler-proxy` (all public, sampler-proxy fail-closed 503)
- ✅ **A-05** - Session-log encryption at rest: pgcrypto `pgp_sym_encrypt` for `messages.content`/`messages.tool_calls` (kill-switch, key ≥ 16, legacy plaintext tolerated)
- ✅ **A-06** - JSONL projection v2: top-level `trace_id`/`span_id` stamped from the turn-trace contextvar — offline cross-link to Langfuse traces
- ✅ **A-07** - CacheWrapper v2: `MemoryCache` LRU with `ORYA_CACHE_MAX_ENTRIES`, Redis client pool tuning, server-side `maxmemory 256mb --maxmemory-policy allkeys-lru`
- ✅ **A-08** - Smoke tests v2: +5 deterministic scenarios covering auth enforcement, operator-loop, rate-limit buckets, observability chain and the tracing kill-switch (`tests/smoke/test_smoke_v2.py`)
- ... (see [PROMPT_MVP.md](analytics/PROMPT_MVP.md) for the 28 MVP tickets and [PROMPT_ALPHA.md](analytics/PROMPT_ALPHA.md) for A-00…A-20)

## LLM Providers (M-01)

The agent is provider-agnostic: all models are constructed through a single seam.

```python
from app.core.llm import get_llm

llm = get_llm("deepseek", "deepseek-chat")  # Chinese provider (OpenAI-compat)
llm = get_llm("anthropic", "claude-sonnet-3.5")  # Western provider (native)
llm = get_llm("ollama", "ollama-coder")  # Local server
```

- **Registry:** `app/core/llm/providers.yaml` (34 providers) + `models.yaml` (41 aliases) — to add a provider, add a YAML entry; no code changes needed for OpenAI-compatible endpoints.
- **Capability detection:** reasoning models without tool-calling (`deepseek-reasoner`, `o1`, `glm-zero-preview`) fail fast with a suggested replacement; pass `require_tools=False` for plain chat.
- **API keys:** env vars (`DEEPSEEK_API_KEY`, `DASHSCOPE_API_KEY`, ...) or `ORYA_LLM_API_KEY`; see `.env.example`.
- **Import from another agent:** `orya import --from opencode|continue|aider`.
- **Registry endpoints:** `GET /llm/providers`, `GET /llm/models`, `GET /llm/health/{provider}`.

## Notes

- Current phase: **ALPHA** — production-safe baseline (auth, rate-limit, tracing, health); BETA adds DFC, L1 memory and MCP (see `analytics/PROMPT_BETA.md`)
- Windows: the `make` targets need Git Bash/WSL — or use the `uv run ...` equivalents / `scripts\start.ps1` directly
- Docker Compose is optional for a minimal dev loop but required for full functionality (PostgreSQL for M-03+, Redis optional for the M-21 cache — `auto` mode falls back to in-process memory)

---

Built with ❤️ using LangChain, LangGraph, FastAPI, Chainlit, PostgreSQL, and Redis.