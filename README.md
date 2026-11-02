# OryaAgent

**Senior Python coding agent with UI and long-term memory.**

FastAPI · LangGraph · Chainlit · PostgreSQL · Redis

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/Python-3.11%20%7C%203.12%20%7C%203.13%20%7C%203.14-blue.svg)](https://www.python.org/)
[![Version 7.0.0](https://img.shields.io/badge/Version-7.0.0-6c4cc3.svg)](#)
[![Phase: ALPHA](https://img.shields.io/badge/Phase-ALPHA-orange.svg)](#roadmap--phases)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.104+-009688.svg)](https://fastapi.tiangolo.com/)
[![LangGraph](https://img.shields.io/badge/LangGraph-0.2+-blueviolet.svg)](https://github.com/langchain-ai/langgraph)
[![Chainlit](https://img.shields.io/badge/Chainlit-2.0+-orange.svg)](https://chainlit.io/)
[![Code style: Ruff](https://img.shields.io/badge/Code%20style-Ruff-000.svg)](https://docs.astral.sh/ruff/)

---

> **TL;DR** — OryaAgent is a self-hosted, production-minded coding agent: a LangGraph
> state machine with six filesystem/shell tools, an interrupt-driven permission
> gate, durable long-term memory across six Markdown files, a single declarative
> LLM seam covering 30+ providers and 45+ model aliases, bearer-JWT auth, per-identity
> cost-aware routing, OTLP-grade observability (Langfuse + OryaObservability SDK +
> sampler-proxy + Prometheus + ClickHouse), Alembic migrations, and a one-command
> Docker Compose stack. MVP (`M-00…M-28` + `MVP-POLISH`) and ALPHA (`A-00…A-20`)
> are implemented.

---

## Table of Contents

- [✨ Features](#-features)
- [🚀 Quick Start](#-quick-start)
- [🏗️ Architecture](#-architecture)
- [🤖 The Agent Loop](#-the-agent-loop)
- [🔧 Built-in Tools](#-built-in-tools)
- [🧠 Long-term Memory](#-long-term-memory)
- [🔌 LLM Provider Seam](#-llm-provider-seam)
- [🛡️ Permissions & Security](#-permissions-security)
- [📊 Observability](#-observability)
- [💰 Cost-aware Routing](#-cost-aware-routing)
- [📦 Tool-result Cache](#-tool-result-cache)
- [🌐 API Reference](#-api-reference)
- [🖥️ Chainlit UI](#-chainlit-ui)
- [💻 CLI](#-cli)
- [🗄️ Database & Migrations](#-database-migrations)
- [🐳 Deployment](#-deployment)
- [⚙️ Configuration](#-configuration)
- [📁 Project Structure](#-project-structure)
- [🧪 Testing](#-testing)
- [🗺 Roadmap & Phases](#-roadmap-phases)
- [🤝 Contributing](#-contributing)
- [📄 License](#-license)

---

## ✨ Features

### Agent core

- **LangGraph state machine** with deterministic node ordering: `agent → human → tools → assess → (agent | recover → human)`.
- **Failure-recovery loop (M-28)** — every `ToolMessage(status="error")` is triaged by the `assess` node and routed to `recover`, which asks the model for alternative plans (`recovery_max_rounds` / `recovery_variants` budgets; recover-node tokens are dropped from the streamed reply).
- **Interrupt-driven permission gate (M-13)** — destructive tool calls (`write` / `edit` / `bash` with `rm`/`mv`/`sudo`) pause via LangGraph `interrupt()` and resume with `approve | deny | always`. Batch semantics are all-or-nothing.
- **Token-efficient output (M-23)** — system prompt cache-first layout, deterministic section ordering, dynamic git/memory blocks last.
- **Streaming-first** — turns stream as SSE: `token`, `tool_start`, `tool_end`, `interrupt`, `budget`, `done`, `error`.

### Six built-in tools (locked order)

| Tool | What it does | Notable |
| --- | --- | --- |
| `read` | Read a file (path-validated, cached) | `validate_path()` before I/O |
| `write` | Atomic file writer (`mkstemp` → `fsync` → `os.replace`) | Never cached; invalidates path |
| `edit` | Atomic find-and-replace / line edit | Same atomic-write contract |
| `bash` | Shell execution (Git Bash → `cmd.exe` on Windows; skips the WSL shim) | Untrusted-output wrapped |
| `grep` | ripgrep-backed content search via shared `_rg.py` seam | Returns single JSON doc |
| `glob` | ripgrep-backed file globbing | Returns single JSON doc |

> Allowed roots for FS tools are `cwd`, `~/.orya`, and `settings.memory_dir`.

### Long-term memory (L0)

- **Six Markdown files** with per-file byte budgets and atomic appends (`O_APPEND` + `fsync` + per-file `threading.Lock`, `fcntl.flock` where available):

  | File | Budget | Purpose |
  | --- | --- | --- |
  | `PROJECT.md` | 8 192 | Project context (mission / stack) |
  | `LEARNED.md` | 4 096 | Things the agent learned |
  | `PREFERENCES.md` | 2 048 | User preferences |
  | `FACTS.md` | 2 048 | Hard facts about the codebase |
  | `DECISIONS.md` | 2 048 | Short ADR-style decisions |
  | `MEMORY_INDEX.md` | default | BETA placeholder index |

- **`/learn` endpoint (M-26)** — turn a free-form note into structured `MemoryItem` records appended to the right file.
- **Background Compactor (M-27)** — strategies partition raw blocks (headers and free text are always kept), **archive to `memory/archive/{stem}_{UTCdate}.md` first**, then `MDStore.rewrite()` under the lock. Never deletes, never rewrites without the lock.

### LLM provider seam (YAML-driven)

- **30+ providers** in `app/core/llm/providers.yaml` across four tiers:
  - **Western**: Anthropic, OpenAI, Google Gemini, xAI Grok.
  - **Chinese**: DeepSeek, Qwen, GLM/Z.AI, Xiaomi MiMo, Moonshot/Kimi, Baichuan, Minimax, StepFun, Yi, iFlyTek, SenseNova, ByteDance Doubao, Tencent Hunyuan, Baidu ERNIE.
  - **Aggregators**: OpenRouter, Together, Groq, Fireworks, SiliconFlow, NVIDIA NIM, Cerebras, SambaNova, OpenCode Zen, OpenCode Go.
  - **Local**: Ollama, LM Studio, vLLM, llama.cpp, TGI, LocalAI, Jan, GPT4All.
- **45+ model aliases** in `models.yaml` (stable names mapped to `(provider, model_id, capabilities)`).
- **Per-model capability matrix** (`capabilities.yaml`) — reasoning models without reliable tool-calling (DeepSeek-R1, `o1`, Qwen-QwQ, GLM-Zero, MiMo) are detected and fail-fast unless `require_tools=False` (plain-chat fallback).
- **`pricing.yaml`** drives per-token USD accounting; **`/llm/models/remote/{provider}`** discovers models live from the provider's `/v1/models`.
- **Importers** — `orya import --from opencode | continue | aider | cline` ingests an existing agent's provider config and writes the local YAML.
- **Single seam rule**: `langchain_anthropic` / `langchain_openai` are never imported outside `app/core/llm/`. Adding an OpenAI-compatible provider is YAML-only.

### Production-safe baseline (ALPHA `A-00…A-20`)

- **Bearer-JWT auth (A-00)** — `orya auth token --user <sub>` mints a token; `/health` stays public, every other endpoint requires `Authorization: Bearer <jwt>` when `AUTH_ENABLED=true`.
- **Rate limiting (A-01)** — Redis-backed, per-identity RPM, kill-switch `ORYA_RATE_LIMIT_ENABLED` (default off, zero-cost startup).
- **LLM tracing (A-02)** — `TracedChatModel` wraps every model and emits one `llm.call` span per invocation via the `emit_span` seam (`ORYA_LLM_TRACE_ENABLED=false` returns the raw adapter).
- **Permission audit spans (A-03)** — every `ask` / `deny` / `allow` decision is recorded as a span.
- **Health endpoints (A-04)** — `GET /health`, `GET /health/observability`, `GET /health/sampler-proxy`.
- **Session-log encryption at rest (A-05)** — `ORYA_SESSION_LOG_ENCRYPTION_ENABLED=true` + a 32-byte key.
- **JSONL span cross-link (A-06)** — `ToolMessage.metadata.span_id` ties tool calls back to their span row.
- **Cache LRU + Redis tuning (A-07)** — `ORYA_CACHE_MAX_ENTRIES`, `ORYA_CACHE_TTL_SECONDS`, `allkeys-lru` on the Redis side.
- **Smoke tests v2 (A-08)** — canonical M-18 tasks driven by a scripted fake model, always run.
- **README v2 deploy guide (A-09)** — env-var reference + README-anchor test in `tests/unit/test_readme.py`.
- **Docker Compose v2 (A-10)** — profile-driven stack (`app` = api+chainlit, `observability` = Langfuse v3 + sampler-proxy).
- **Alembic migrations (A-11)** — `alembic/versions/NNNN_name.py` wrappers over `app/db/migrations/*.sql`; `orya db migrate | downgrade | current`.
- **Settings v2 (A-12)** — `ORYA_ENV=prod` fail-fast requires auth + rate-limit + non-wildcard CORS; `orya config show | check` prints redacted effective settings with per-field source.
- **CostAwareRouter (A-13)** — per-identity daily USD budget, **degrade at 70 %, warn at 90 %, 429 at 100 %**; emits a `budget` SSE frame; kill-switch `ORYA_COST_ROUTER_ENABLED`; fallback model `ORYA_COST_ROUTER_FALLBACK_MODEL`.
- **Cost-tracking spans (A-14)** — `cost.input_tokens` / `cost.output_tokens` / `cost.usd` attributes on every `llm.call` span; `orya_llm_cost_usd_total{model}` metric.
- **Langfuse OTLP/HTTP JSON export (A-15)** — hand-rolled exporter, auto-on when `LANGFUSE_HOST` + both keys are set, `gen_ai.*` enrichment, fail-open to `LANGFUSE_DIRECT_URL` when the sampler-proxy is unreachable.
- **OryaObservability SDK bridge (A-16)** — `agent.loop` / `tool.call` / `memory.write` custom spans, `timed_span` duration context manager, PII masking via the opt-in `agent_obs` PIIDetector (fail-closed `[REDACTED:guardrail_unavailable]` without the SDK).
- **Sampler-proxy mode (A-17)** — `cost.over_budget=true` at 90 % budget, `security.incident=true` on injection; Prometheus + ClickHouse audit sink for always-keep traces.
- **TieredModelRouter (A-18)** — tier-based model selection (`small` / `large` / `tournament`) layered over the CostAwareRouter: the tier picks the model, the budget only *lowers* it to `small` at 90 %; stages `agent.execute.tier` / `agent.execute.degraded` span attributes; `tier=` keyword on `resolve_turn_model` (the planner that emits tiers arrives in BETA).
- **PromptCacheLayout (A-19)** — provider-native prompt caching of the stable system-prompt prefix (Anthropic `cache_control: ephemeral`, OpenAI automatic, Gemini context-caching), `llm.call.cache_hit` span attribute, Redis-backed prefix-hash invalidation; kill-switch `LLM_PROMPT_CACHE_ENABLED`.
- **ConnectionPool (A-20)** — per-provider keepalive clients for the LLM seam (up to `LLM_POOL_SIZE`=4, LRU-evicted, 30 s async health-check worker): warm TCP+TLS instead of a per-turn cold-start, `tcp.pool_hit` / `tcp.connect_duration_ms` span attributes, `orya_llm_pool_*` metrics; kill-switch `CONNECTION_POOL_ENABLED=false`.

### Tooling & UX

- **Chainlit UI** on `:8001`, a pure `httpx` client of the FastAPI API — never builds or drives a graph.
- **`orya` CLI** — `import`, `db migrate|downgrade|current`, `auth token`, `config show|check`.
- **One-command start** (`scripts/start.sh` / `start.ps1`) — `uv sync` → `docker compose up -d postgres redis` → `orya db migrate` → API on `:8000` → Chainlit on `:8001`, with health-gated waits and log files in `logs/`.
- **Ruff** lint+format gate (`make lint` / `make format`), `asyncio_mode=auto` pytest.

---

## 🚀 Quick Start

### Prerequisites

- **Python 3.11+** (3.12 is the repo venv; 3.13/3.14 supported — pin 3.12 with `uv python pin 3.12` if langchain compatibility complains).
- **Docker & Docker Compose** (for PostgreSQL 16 and Redis 7).
- **ripgrep** binary on PATH (hard dependency of `grep` / `glob` tools).
- **[uv](https://docs.astral.sh/uv/)** for dependency management.

### Setup

```bash
git clone https://github.com/Reider85/OryaAgent.git
cd OryaAgent
uv sync                                    # install deps (Python 3.12 venv)
docker compose up -d                       # postgres + redis (stateful infra only)
make dev                                   # FastAPI on :8000 (--reload)
make ui                                    # Chainlit UI on :8001 (separate terminal)
curl http://localhost:8000/health          # → {"status":"ok", ...}
```

Open **http://localhost:8001**, create a session, start a turn.

### One-command start

```bash
scripts/start.sh                                  # Linux / macOS / Git Bash
powershell -ExecutionPolicy Bypass -File scripts\start.ps1   # native Windows
```

The script runs the full bring-up (`uv sync` → `docker compose up -d postgres redis` → `orya db migrate` → API → Chainlit), waits on `/health` at each stage, and writes `logs/runtime.env`, `logs/api.log`, `logs/ui.log` (plus `.err.log` twins). Stop with `scripts/stop.sh` / `stop.ps1`. Flags: `--skip-sync`, `--reload`.

### Make targets

| Target | Effect |
| --- | --- |
| `make dev` | `uv run uvicorn app.main:app --reload --port 8000` |
| `make ui` | `uv run chainlit run app/ui/chainlit_app.py --port 8001` |
| `make test` | `uv run pytest` (~60 s; many conditional skips without infra) |
| `make lint` | `ruff check .` + `ruff format --check .` |
| `make format` | `ruff format .` |
| `make db-up` / `db-down` | postgres container |
| `make db-migrate` | `python -m app.db.migrate` (Alembic `upgrade head`) |
| `make db-downgrade REV=base` | roll back to a revision |
| `make db-current` | print current revision |
| `make redis-up` / `redis-down` | redis container |
| `make stack-up` / `stack-down` | full compose stack with profiles |

---

## 🏗️ Architecture

```
                         ┌─────────────────────────────┐
                         │         Chainlit UI          │
                         │   app/ui/chainlit_app.py     │  (port 8001)
                         │   pure httpx + SSE client    │
                         └───────────────┬─────────────┘
                                         │  HTTP/SSE
                                         ▼
   ┌──────────────────────────────────────────────────────────────┐
   │                         FastAPI app                           │
   │                       app/main.py                             │  (port 8000)
   │   lifespan: cache · rate-limit · cost-store · Langfuse        │
   │             exporter · OryaObs SDK · projection worker ·      │
   │             compaction worker                                 │
   │                                                               │
   │   routers: llm · sessions · learn · memory · metrics ·        │
   │             workspace · health                                │
   │   middleware: auth · rate-limit · CORS · X-Request-ID         │
   └───────────────┬──────────────────────────┬────────────────────┘
                   │                          │
                   ▼                          ▼
   ┌───────────────────────────┐   ┌──────────────────────────────┐
   │   LangGraph build_graph    │   │   LLM seam (app/core/llm)     │
   │   app/core/graph.py        │   │   factory.get_llm()           │
   │                            │   │   TracedChatModel (A-02)      │
   │  agent → human → tools →   │   │   cost_router.resolve_* (A-13)│
   │  assess → (agent|recover)  │   │                               │
   │                            │   │   YAML: providers / models /  │
   │  injected: system_prompt_  │   │   capabilities / pricing      │
   │  fn · trim_fn · policy     │   └───────────────┬──────────────┘
   └─────┬───────────────┬──────┘                   │
         │               │                          ▼
         ▼               ▼              ┌────────────────────────┐
  ┌─────────────┐  ┌──────────────┐    │  Observability seam     │
  │   Tools     │  │ Permissions  │    │  app/core/observability │
  │ read/write/ │  │  Permission  │    │  spans → emit_span      │
  │ edit/bash/  │  │   Policy     │    │  langfuse exporter      │
  │ grep/glob   │  │  deny→allow→ │    │  sdk (OryaObs bridge)   │
  │             │  │  allowlist→  │    │  pii (PIIDetector)      │
  │ _validators │  │  mode        │    └────────────────────────┘
  │ _rg seam    │  │  interrupt() │
  │ cache hook  │  │  resume()    │
  └──────┬──────┘  └──────────────┘
         │
         ▼
   ┌─────────────────────────────────────────────────────────────┐
   │  Long-term memory (app/core/memory)                          │
   │  MDStore: 6 MD files (PROJECT/LEARNED/PREFERENCES/FACTS/     │
   │           DECISIONS/MEMORY_INDEX) + memory/archive/          │
   │  Compactor (M-27): archive → MDStore.rewrite under lock      │
   │  /learn (M-26): MemoryItem.create() → MDStore.append()       │
   └─────────────────────────────────────────────────────────────┘

   ┌──────────────────────────────────────────────────────────────┐
   │  Persistence                                                  │
   │  asyncpg pool (sessions) · psycopg pool (LangGraph            │
   │  checkpoints) · Redis (cache + rate-limit + cost-store) ·     │
   │  Alembic migrations (app/db/migrations/*.sql)                 │
   └──────────────────────────────────────────────────────────────┘
```

**Dependency direction matters (enforced by tests)**:

- `app/main.py` — FastAPI app + `orya` CLI.
- `app/core/llm/` — the **only** place `langchain_anthropic` / `langchain_openai` may be imported.
- `app/core/graph.py` — `build_graph(tools, model, checkpointer, policy, *, system_prompt_fn, trim_fn)`; **must not import `prompt.py` / `context.py`** (they are injected callables — cacheable-prefix ordering depends on it).
- `app/core/tools.py` — `get_tools()` returns exactly `[read, write, edit, bash, grep, glob]` in that order; the graph, prompt builder and tests assert this.
- `app/core/permissions.py` — precedence `deny → session allowlist → allowlist → mode`; fail-closed.
- `app/core/memory/` — `MDStore` is the only entry point for the six MD files.
- `app/db/` — only `migrate.py` + `alembic/` may import SQLAlchemy/Alembic; app code stays asyncpg-only.

---

## 🤖 The Agent Loop

`app/core/graph.py :: build_graph(...)` assembles a LangGraph state machine with five nodes:

```
   ┌───────┐    ┌────────┐    ┌───────┐    ┌────────┐
   │ agent │───▶│ human  │───▶│ tools │───▶│ assess │
   └───────┘    └────────┘    └───────┘    └────┬───┘
       ▲            ▲                         │
       │            │                         ├── ok ─────▶ agent
       │            │                         │
       │            └──── recover ◀── error ──┘
       │                   │
       └───────────────────┘
```

- **`agent`** — invokes the model (selected by the CostAwareRouter between turns). Streams tokens back to the SSE channel.
- **`human`** — consumes `PermissionPolicy.check()`; turns `ask` decisions into `interrupt()` pauses. The UI answers with `resume_command("approve" | "deny" | "always")` (the last whitelists the tool for the session).
- **`tools`** — runs the batch. A cache hit returns `ToolMessage(metadata={"from_cache": True})`.
- **`assess`** (M-28) — triages `ToolMessage(status="error")` results. Success → back to `agent`. Error → `recover`.
- **`recover`** (M-28) — asks the model for alternative plans (`recovery_max_rounds`, `recovery_variants` from settings). Recover-node tokens are **dropped from the streamed reply** so the user only sees the final answer.

**Batch semantics** — if any call in one AI message is refused (by a rule or by the user), the whole batch is refused. Providers require exactly one `ToolMessage` per tool-call id; partial execution would desync the conversation history.

---

## 🔧 Built-in Tools

All tools live in `app/tools/`, are async, take `Annotated[str, "..."]` params, raise `ToolException` on failure, and shell out to ripgrep through the shared `app/tools/_rg.py` seam.

| # | Tool | Source | Mode | Cached | Notes |
| --- | --- | --- | --- | --- | --- |
| 1 | `read` | `app/tools/read.py` | read-only | yes | `validate_path()` before I/O |
| 2 | `write` | `app/tools/write.py` | destructive | never | `mkstemp` (same dir) → `fsync` → `os.replace`; calls `invalidate_cache_for_path()` |
| 3 | `edit` | `app/tools/edit.py` | destructive | never | atomic find-and-replace / line edit |
| 4 | `bash` | `app/tools/bash.py` | destructive | never | prefers Git Bash, skips the WSL `System32\bash.exe` shim, falls back to `cmd.exe` |
| 5 | `grep` | `app/tools/grep.py` | read-only | yes | ripgrep-backed content search; single JSON doc result |
| 6 | `glob` | `app/tools/glob.py` | read-only | yes | ripgrep-backed file globbing; single JSON doc result |

**Untrusted-output handling** — every user-visible file/shell output goes through `wrap_untrusted()` / `detect_injection()` in `app/core/security.py`. `bash`, `grep`, and `glob` return a single JSON document.

**Adding a tool = 5 steps** (enforced by `tests/integration/test_tools_integration.py`):

1. `app/tools/<name>.py`
2. re-export from `app/tools/__init__.py`
3. add to `get_tools()` (preserve the locked order)
4. add `EXPECTED_NAMES` / `EXPECTED_REQUIRED_ARGS` to the integration test
5. unit tests; if read-only, add to the permission allowlist

---

## 🧠 Long-term Memory

The L0 memory layer is a **Markdown-first**, durable, append-only store with background compaction.

### The six files (`app/core/memory/md_store.py`)

| File | Budget (bytes) | Append type | Used by |
| --- | --- | --- | --- |
| `PROJECT.md` | 8 192 | manual / agent-edited | `project_context_block()` in the prompt |
| `LEARNED.md` | 4 096 | `MemoryItem` (`learned`) | prompt + `/learn` |
| `PREFERENCES.md` | 2 048 | `MemoryItem` (`preference`) | prompt + `/learn` |
| `FACTS.md` | 2 048 | `MemoryItem` (`fact`) | prompt + `/learn` |
| `DECISIONS.md` | 2 048 | `MemoryItem` (`decision`) | prompt + `/learn` |
| `MEMORY_INDEX.md` | default | BETA placeholder | reserved for v7 |

### The seam

- **`MDStore`** — `append(file, content)` / `read(file)` / `read_all()` / `mtime(file)` / `stats()` / `compact_if_needed(file)` / `rewrite(file, transform)`.
- **Atomic appends** — one `os.write` into `O_APPEND` + `fsync`, under a per-file `threading.Lock`; `fcntl.flock` where available (POSIX). On Windows: `O_BINARY` + atomic append.
- **Rewrites (Compactor)** — locked read-modify-write ending in `tmp` + `fsync` + `os.replace`. A concurrent `append` can neither interleave nor be lost.
- **`record_memory_op()`** — best-effort `memory_audit_log` row (JSONL fallback if Postgres is down).
- **`get_md_store(memory_dir=...)`** — cached entry point. **Never** open the MD files directly.

### `/learn` (M-26)

`POST /learn` or `POST /sessions/{id}/learn` — turn a free-form note into one or more structured `MemoryItem` records and append them to the right file. Explicit user commands (`/learn`, `/memory/*`) **never** interrupt the permission flow.

### Background Compactor (M-27)

`compaction_worker(interval)` runs on the FastAPI lifespan (`ORYA_MEMORY_COMPACT_INTERVAL_SECONDS`, `0` disables it). A failed pass never kills the loop. Strategy:

1. Partition **raw blocks** (headers and free text are always kept).
2. **Append** the candidates to `memory/archive/{stem}_{UTCdate}.md` first.
3. **`MDStore.rewrite(file, transform)`** under the lock.

> Never hand-roll a rewrite — always archive first, then `MDStore.rewrite`.

### `/memory*` endpoints (M-25 / M-27)

| Method | Path | Effect |
| --- | --- | --- |
| `GET` | `/memory` | All six files' contents |
| `GET` | `/sessions/{id}/memory` | Same, scoped |
| `GET` | `/memory/stats` | Per-file size, mtime, % of budget |
| `GET` | `/sessions/{id}/memory/stats` | Same, scoped |
| `POST` | `/memory/compact` | Force a compaction pass |
| `POST` | `/sessions/{id}/memory/compact` | Same, scoped |

---

## 🔌 LLM Provider Seam

`app/core/llm/factory.py :: get_llm(provider, model)` is the **single** place a chat model is constructed. Everything else is declarative YAML:

| File | Purpose |
| --- | --- |
| `providers.yaml` | One entry per provider: `adapter` (`anthropic` / `openai` / `google_genai` / `openai_compat`), `base_url`, `env_var`, `default_model`, `tier`, optional `extra_headers`, `health_path`. |
| `models.yaml` | 45+ aliases mapped to `(provider, model_id, context_window, supports_tools, supports_streaming, suggests)`. |
| `capabilities.yaml` | Per-provider → `model_id` capability matrix (`supports_tools` / `supports_streaming` / `supports_system_prompt` / `context_window`). Reasoning models without reliable tool-calling get `supports_tools: false` and a `suggests:` replacement. |
| `pricing.yaml` | Per-model per-token USD pricing; consumed by `cost_tracker.price_usd()`. |

### Four provider tiers (30+ entries)

| Tier | Providers |
| --- | --- |
| **Western** | Anthropic · OpenAI · Google Gemini · xAI Grok |
| **Chinese** | DeepSeek · Qwen · GLM / Z.AI · Xiaomi MiMo · Moonshot / Kimi · Baichuan · Minimax · StepFun · Yi · iFlyTek · SenseNova · ByteDance Doubao · Tencent Hunyuan · Baidu ERNIE |
| **Aggregator** | OpenRouter · Together · Groq · Fireworks · SiliconFlow · NVIDIA NIM · Cerebras · SambaNova · OpenCode Zen · OpenCode Go |
| **Local** | Ollama · LM Studio · vLLM · llama.cpp · TGI · LocalAI · Jan · GPT4All |

### Adapters (`app/core/llm/adapters/`)

- `anthropic.py` — `langchain_anthropic` (native).
- `gemini.py` — `langchain_google_genai` (native).
- `openai_compat.py` — `ChatOpenAI(base_url=...)` for everything else.
- `local.py` — local-server discovery + dummy API keys.

### Tracing wrapper (A-02)

`TracedChatModel` wraps every model and emits **one `llm.call` span per invocation** via the `emit_span` seam (buffered through `get_span_buffer()`). `ORYA_LLM_TRACE_ENABLED=false` returns the raw adapter. Since A-14 the same wrapper stamps `cost.input_tokens` / `cost.output_tokens` / `cost.usd` on every span and accumulates `orya_llm_cost_usd_total{model}` (identity-independent — emitted even with the router kill-switch off).

### Cost-aware router (A-13)

`app/core/llm/cost_router.py :: resolve_turn_model(identity, requested_alias)` runs **between turns only**. Per-identity daily USD counters live in `app/core/cost_tracker.py` (contextvar identity, Redis-or-memory seam). Thresholds:

| Budget % | Action |
| --- | --- |
| `< 70 %` | requested model |
| `70 – 90 %` | degrade to `ORYA_COST_ROUTER_FALLBACK_MODEL` |
| `90 – 100 %` | degrade + `budget` SSE warning frame |
| `≥ 100 %` | `429` (budget exhausted) |

Kill-switch: `ORYA_COST_ROUTER_ENABLED=false`. `ModelSelection.as_dict()` feeds the `budget` SSE frame and the session payload.

### Importers

```bash
orya import --from opencode      # opencode.json → providers.yaml + models.yaml
orya import --from continue      # ~/.continue/config.json
orya import --from aider         # .aider.conf.yml
orya import --from cline          # VS Code Cline settings
```

Each importer prints found providers, the chosen default, and any missing env vars you need to set to activate the providers.

### LLM HTTP API

| Method | Path | Effect |
| --- | --- | --- |
| `GET` | `/providers` | All providers from `providers.yaml` |
| `GET` | `/models` | All aliases from `models.yaml` |
| `GET` | `/models/remote/{provider}` | Live `GET /v1/models` from the provider |
| `GET` | `/health/{provider}` | Probe `health_path` for the provider |

---

## 🛡️ Permissions & Security

### Permission policy (M-13)

`app/core/permissions.py :: PermissionPolicy` — the decision layer between the agent loop and tool execution. Decision tree:

```
ToolCall → deny-list          → DENY   (always, wins over everything)
         → session allowlist  → ALLOW  ("always" answer this session)
         → allow-list         → ALLOW  (bypasses the mode)
         → mode               → strict:     ask on write/edit/bash
                               permissive:  ask on bash with rm/mv/sudo
                               otherwise    ALLOW
```

- **Modes**: `strict` (default), `permissive`. Override per-user via `~/.orya/permissions.yml` (`ORYA_PERMISSIONS_PATH`).
- **Fail-closed**: no checkpointer ⇒ `ask` = `deny`; unknown resume answer = `deny`; a mixed approve/refuse batch is wholly refused.
- **Explicit user commands** (`/learn`, `/memory/*`) never interrupt — the user asked for them on purpose.
- **Batch semantics**: all-or-nothing (one `ToolMessage` per tool-call id).

### Auth (A-00)

- **Bearer-JWT middleware** (`app/core/auth/`). `/health` and `ORYA_AUTH_PUBLIC_PATHS` stay public; everything else requires `Authorization: Bearer <jwt>` when `AUTH_ENABLED=true`.
- **`orya auth token --user <sub> [--ttl <s>]`** mints a JWT (HS256 by default, `AUTH_ALGORITHM`, `AUTH_SECRET_KEY`, `AUTH_TOKEN_TTL_S`).
- **`ORYA_ENV=prod` fail-fast** requires `AUTH_ENABLED=true` (validator in `Settings`).

```bash
# server-side
AUTH_ENABLED=true AUTH_SECRET_KEY=$(openssl rand -hex 32)

# mint a token — raw JWT to stdout
orya auth token --user alice --ttl 3600

# use it
curl -H "Authorization: Bearer $TOKEN" http://localhost:8000/sessions

# without it → 401
```

### Rate limiting (A-01)

Redis-backed, per-identity RPM + a separate `learn` RPM. Kill-switch `ORYA_RATE_LIMIT_ENABLED` (default off — zero-cost startup). `ORYA_ENV=prod` requires it on.

### Untrusted-output & injection detection

`app/core/security.py`:

- **`wrap_untrusted(text)`** — wraps file/shell output for the model.
- **`detect_injection(text)`** — flags prompt-injection attempts; on hit, A-17 stamps `security.incident=true` on the span (always-keep in the sampler-proxy).
- **`validate_path(path)`** (`app/tools/_validators.py`) — every FS tool calls this before any I/O. Allowed roots: `cwd`, `~/.orya`, `settings.memory_dir`.

### Session-log encryption at rest (A-05)

`ORYA_SESSION_LOG_ENCRYPTION_ENABLED=true` + `ORYA_SESSION_LOG_ENCRYPTION_KEY` (32 bytes). Migrated via `app/db/migrations/0002_session_log_encryption.sql`.

### Path & workspace safety

`app/core/workspace.py` + `app/api/workspace.py :: GET /workspace/browse` — the folder picker the UI uses to open a project from the chat.

---

## 📊 Observability

A layered span pipeline on the `emit_span` seam (`app/core/observability/spans.py`):

```
TracedChatModel ─┐
PermissionPolicy ─┤── emit_span() ── buffer ──► Langfuse exporter (A-15)
MDStore          ─┤                              (OTLP/HTTP JSON, gen_ai.*)
agent_obs bridge ─┘                                      │
                                                         ▼
                                              sampler-proxy (A-17)
                                              cost.over_budget, security.incident
                                                         │
                              ┌──────────────────────────┤
                              ▼                          ▼
                      Langfuse v3 (ClickHouse)    Prometheus + ClickHouse audit
```

### Spans emitted

| Span | Source | Key attributes |
| --- | --- | --- |
| `llm.call` | `TracedChatModel` (A-02) | `gen_ai.*`, `cost.input_tokens`, `cost.output_tokens`, `cost.usd` (A-14) |
| `agent.loop` | OryaObs SDK bridge (A-16) | turn id, model alias |
| `tool.call` | OryaObs SDK bridge (A-16) | tool name, args (PII-masked), `from_cache` |
| `memory.write` | OryaObs SDK bridge (A-16) | file, bytes (PII-masked) |
| `permission.audit` | A-03 | tool, decision (`allow`/`ask`/`deny`), reason |
| `recovery.*` | M-28 | round, variants tried |

### PII masking (A-16)

Opt-in via the sibling `OryaObservability` SDK (`uv pip install -e ../OryaObservability`). When the SDK's `agent_obs.eval.PIIDetector` is available, span content is masked; **fail-closed** to `[REDACTED:guardrail_unavailable]` without it. Kill-switches: `ORYA_AGENT_OBS_ENABLED`, `ORYA_AGENT_OBS_GUARDRAIL_ENABLED`.

### Langfuse OTLP/HTTP JSON export (A-15)

`app/core/observability/langfuse.py` — a hand-rolled exporter (no `langfuse` SDK dep). Auto-on when `LANGFUSE_HOST` + `LANGFUSE_PUBLIC_KEY` + `LANGFUSE_SECRET_KEY` are set. `_finalize` → `export_span`: span batches are POSTed to `{LANGFUSE_HOST}/api/public/otel/v1/traces` with Basic auth. Fail-open to `LANGFUSE_DIRECT_URL` when the sampler-proxy is unreachable. `ORYA_LANGFUSE_EXPORT_ENABLED=false` forces off.

### Sampler-proxy mode (A-17)

A sidecar container (built from the sibling `../OryaObservability`) that fronts Langfuse and decides which traces to keep:

- `cost.over_budget=true` at 90 % budget ⇒ always keep.
- `security.incident=true` on injection ⇒ always keep.
- Audit sink: `observability.audit_events_hot` in ClickHouse (`deploy/clickhouse/01_audit_events_hot.sql`).
- `GET /sampler/status` and `GET /metrics` (Prometheus scrape).

### Health endpoints (A-04)

| Method | Path | Returns |
| --- | --- | --- |
| `GET` | `/health` | `{"status":"ok","message":"OryaAgent API is running"}` (+ component probes) |
| `GET` | `/health/observability` | Langfuse exporter + OryaObs SDK + sampler-proxy status |
| `GET` | `/health/sampler-proxy` | `GET /sampler/status` proxied |

### Metrics (A-14 / A-17)

`GET /metrics` exposes:

- `orya_llm_cost_usd_total{model}` — cumulative spend per model.
- `orya_cost_aware_switch_total` — router degrade/warn/refuse counts.
- `orya_langfuse_export_*` — exporter queue / drop / success.
- `orya_agent_obs_*` — SDK bridge availability.
- `orya_tool_cache_*` — hits / misses / evictions.

`GET /tools/cache-stats` — per-tool cache stats (M-21).

---

## 💰 Cost-aware Routing

Per-identity daily USD budget with three thresholds and a kill-switch. Lives entirely in `app/core/cost_tracker.py` (counters + `price_usd()`) and `app/core/llm/cost_router.py` (selection logic — between turns only).

```
   turn requested ──► resolve_turn_model(identity, alias)
                          │
                          ▼
            ┌─────────────────────────────┐
            │ spend_usd_today(identity)    │
            └────────────┬────────────────┘
                         │
   < 70 %  ─────────────┼──────────────► requested alias
   70–90 % ─────────────┼──────────────► fallback alias  (silent)
   90–100% ─────────────┼──────────────► fallback + budget SSE warning
   ≥ 100 % ─────────────┼──────────────► 429 Budget Exhausted
```

| Setting | Default | Effect |
| --- | --- | --- |
| `ORYA_COST_ROUTER_ENABLED` | `false` | Kill-switch |
| `ORYA_COST_BUDGET_DEFAULT_USD` | — | Per-identity daily budget |
| `ORYA_COST_ROUTER_FALLBACK_MODEL` | — | Degrade target (e.g. `glm-4.5-flash`) |
| `ORYA_COST_BACKEND` | `auto` | `auto` / `memory` / `redis` |

`budget` SSE frame shape: `ModelSelection.as_dict()` → `{"type":"budget","spend_usd":...,"budget_usd":...,"model":...,"degraded":bool}` (tiered selections add `"tier"`).

### Tiered model router (A-18)

`app/core/llm/tiered_router.py` adds **complexity routing** on top of the budget router (composition, not replacement): the caller's `tier` decides the model — `small` → `claude-haiku-3.5`, `large` → `claude-sonnet-3.5` (default) — independently of the budget; at `budget_ratio ≥ 90 %` the tier is *lowered* to `small` (never raised) and at ≥ 100 % the turn still answers `429`. `tier=tournament` degrades to `large` in ALPHA (TournamentExecutor is PROD). Every selection stages `agent.execute.tier` / `agent.execute.degraded` (plus `cost.over_budget` at ≥ 90 %) on the `agent.loop` span **before** the model is returned. Entry point: `resolve_turn_model(..., tier=...)` — `tier=None`, the only mode until the BETA planner, is the untouched v6 path. Config precedence: `ORYA_TIERED_ROUTER_*_MODEL` env > `tiered_router.models.*` in `~/.orya/config.yaml` > defaults (aliases must exist in `models.yaml`).

---

## 📦 Tool-result Cache

Read-only tools (`read`, `grep`, `glob`) may use `get_cache()`; `write`, `edit`, `bash` **never** cache and always call `invalidate_cache_for_path()` (M-21).

| Setting | Default | Effect |
| --- | --- | --- |
| `ORYA_CACHE_BACKEND` | `auto` | `auto` (probe Redis, fall back to in-memory) / `memory` / `redis` |
| `ORYA_CACHE_MAX_ENTRIES` | — | In-memory LRU cap (A-07) |
| `ORYA_CACHE_TTL_SECONDS` | — | Per-entry TTL |

A cache hit through the ToolNode returns `ToolMessage(metadata={"from_cache": True})` via `from_cache_result()` in `app/core/cache.py`. Redis is configured `maxmemory-policy allkeys-lru`.

---

## 🌐 API Reference

All routers are mounted under `/` (sessions router is `/sessions`). Health is always public; everything else requires the Bearer header when `AUTH_ENABLED=true`.

### Sessions (M-20 / M-24)

| Method | Path | Effect |
| --- | --- | --- |
| `POST` | `/sessions` | Create a session (provider, model, system-prompt overrides, workspace) |
| `GET` | `/sessions` | List sessions |
| `GET` | `/sessions/{id}` | Session metadata + state |
| `POST` | `/sessions/{id}/messages?stream=true` | Send a turn → SSE stream (`token` / `tool_start` / `tool_end` / `interrupt` / `budget` / `done` / `error`) |
| `POST` | `/sessions/{id}/resume?stream=true` | Answer an `interrupt` with `approve` / `deny` / `always` → SSE stream |
| `PATCH` | `/sessions/{id}` | Update session metadata |
| `DELETE` | `/sessions/{id}` | Delete session |

### LLM endpoints

| Method | Path |
| --- | --- |
| `GET` | `/providers` |
| `GET` | `/models` |
| `GET` | `/models/remote/{provider}` |
| `GET` | `/health/{provider}` |

### Memory & Learn

| Method | Path |
| --- | --- |
| `GET` | `/memory` · `/sessions/{id}/memory` |
| `GET` | `/memory/stats` · `/sessions/{id}/memory/stats` |
| `POST` | `/memory/compact` · `/sessions/{id}/memory/compact` |
| `POST` | `/learn` · `/sessions/{id}/learn` |

### Observability & workspace

| Method | Path |
| --- | --- |
| `GET` | `/health` · `/health/observability` · `/health/sampler-proxy` |
| `GET` | `/metrics` |
| `GET` | `/tools/cache-stats` |
| `GET` | `/workspace/browse` |

### SSE frame contract (M-24)

```
event: token
data: {"text": "import "}

event: tool_start
data: {"name": "bash", "args": {"command": "pytest -q"}, "span_id": "..."}

event: tool_end
data: {"name": "bash", "from_cache": false, "span_id": "..."}

event: interrupt
data: {"calls": [{"name": "edit", "args": {...}}], "message": "Approve edit?"}

event: budget
data: {"spend_usd": 0.42, "budget_usd": 1.0, "model": "glm-4.5-flash", "degraded": true}

event: done
data: {"turn_id": "...", "tokens_in": 1234, "tokens_out": 567, "cost_usd": 0.012}

event: error
data: {"message": "...", "code": "..."}
```

---

## 🖥️ Chainlit UI

`app/ui/chainlit_app.py` is a **pure `httpx` client** of the FastAPI API since M-24 — it never builds or drives a graph.

- **Endpoint**: `ORYA_API_URL` (default `http://127.0.0.1:8000`).
- **Sessions**: `POST /sessions`, turns via `POST /sessions/{id}/messages?stream=true`, interrupts via `/resume?stream=true`.
- **Port**: `ORYA_CHAINLIT_PORT` / `CHAINLIT_PORT` (default `8001`).
- **Settings UI**: `ORYA_UI_SETTINGS_PATH` — pick provider/model/system-prompt overrides.
- **Folder picker**: opens a workspace from the chat via `GET /workspace/browse`.
- **Interrupt UI**: `app/ui/interrupt.py` — approve / deny / always buttons.

Start it with `make ui` (separate terminal from `make dev`) or as part of `scripts/start.sh`.

---

## 💻 CLI

`orya` is the console entry point (`pyproject.toml :: [project.scripts] orya = "app.main:main"`).

```bash
orya --help
```

| Command | Effect |
| --- | --- |
| `orya import --from opencode\|continue\|aider\|cline` | Ingest provider config from another agent into local YAML |
| `orya db migrate` | Apply pending Alembic migrations (A-11) |
| `orya db downgrade <rev>` | Roll back to a revision (e.g. `base`) |
| `orya db current` | Print the current database revision |
| `orya auth token --user <sub> [--ttl <s>]` | Mint a Bearer JWT (A-00) |
| `orya config show` | Print redacted effective settings with per-field source (A-12) |
| `orya config check` | Validate `ORYA_ENV=prod` guardrails (exit 1 on violations) |

`orya config check` runs **before** logging setup, so a prod-guard violation is reported as a readable message, not a traceback.

---

## 🗄️ Database & Migrations

- **Runtime**: asyncpg pool (`app/db/__init__.py`) — sessions, session-log, memory audit log.
- **Checkpoints**: a **separate psycopg pool** (`app/db/checkpoints.py`, `AsyncPostgresSaver.setup()`) — loop-bound singleton, dropped without close on loop change. Checkpoint tables are **not** in `schema.sql` and **not** in Alembic.
- **Schema**: `app/db/schema.sql` is canonical.
- **Migrations (A-11)**: Alembic-orchestrated. `alembic/versions/NNNN_name.py` reads the matching `app/db/migrations/NNNN_name.sql` on upgrade (inline DDL on downgrade); bookkeeping in `alembic_version` (legacy `schema_migrations` dropped on first run). All entry points funnel through `app/db/migrate.py`.

> **A schema change requires THREE edits**: `schema.sql` + a new `app/db/migrations/NNNN_name.sql` + an `alembic/versions/NNNN_name.py` wrapper. `tests/unit/test_db_schema.py` (SQL drift) and `tests/unit/test_alembic.py` (1:1 wrapper) fail otherwise.

Current migrations:

| Revision | File | Effect |
| --- | --- | --- |
| `0001` | `migrations/0001_init.sql` | Initial schema (sessions, session_log, memory_audit_log) |
| `0002` | `migrations/0002_session_log_encryption.sql` | Session-log encryption at rest (A-05) |

---

## 🐳 Deployment

### Docker Compose v2 (A-10)

`docker-compose.yml` ships three profiles:

| Profile | Services |
| --- | --- |
| *(default)* | `postgres` (16) · `redis` (7, `allkeys-lru`) |
| `app` | `api` (`deploy/Dockerfile`) · `chainlit` |
| `observability` | `langfuse` (v3) · `langfuse-worker` · `clickhouse` (26.9) · `minio` · `prometheus` (v3.4.2) · `sampler-proxy` (builds from sibling `../OryaObservability`) · `db-init` · `clickhouse-obs-init` |

```bash
# 1. stateful infra only (default Quick Start)
docker compose up -d

# 2. full app stack
echo "COMPOSE_PROFILES=app" >> .env
docker compose up -d --build

# 3. full app + observability
echo "COMPOSE_PROFILES=app,observability" >> .env
docker compose up -d --build
# API:        http://localhost:8000
# UI:         http://localhost:8001
# Langfuse:   http://localhost:3000
# Prometheus: http://localhost:9090
# sampler:    http://localhost:4321/sampler/status
```

The `api` container runs `orya db migrate` before `uvicorn` (idempotent); both containers have health checks and `restart: unless-stopped`. Bare `docker compose up -d` stays postgres+redis only — locked by `tests/unit/test_docker_compose.py`.

### Dockerfile (`deploy/Dockerfile`)

One image, two commands:

- `api` → `uvicorn app.main:app` (default `CMD`).
- `chainlit` → `chainlit run app/ui/chainlit_app.py` (compose overrides `command`).

Multi-stage build on `ghcr.io/astral-sh/uv:python3.12-bookworm-slim`. Installs **ripgrep** (hard dep of `grep`/`glob`) and **libpq5** (for `psycopg`). `alembic.ini` + `alembic/` are copied in or `orya db migrate` fails.

### Production checklist (A-09 / A-12)

- [ ] `ORYA_ENV=prod` (`orya config check` passes)
- [ ] `AUTH_ENABLED=true`, `AUTH_SECRET_KEY` set (32-byte hex)
- [ ] `ORYA_RATE_LIMIT_ENABLED=true`
- [ ] `CORS_ORIGINS` non-wildcard
- [ ] `ORYA_SESSION_LOG_ENCRYPTION_ENABLED=true`, `ORYA_SESSION_LOG_ENCRYPTION_KEY` set (32 bytes)
- [ ] `ORYA_COST_ROUTER_ENABLED=true`, `ORYA_COST_BUDGET_DEFAULT_USD`, `ORYA_COST_ROUTER_FALLBACK_MODEL`
- [ ] `LANGFUSE_HOST` + `LANGFUSE_PUBLIC_KEY` + `LANGFUSE_SECRET_KEY` set (or sampler-proxy in front)
- [ ] `ORYA_LLM_TRACE_ENABLED=true` (default)
- [ ] Postgres / Redis persistence volumes
- [ ] Backups for `~/.orya` (sessions JSONL, permissions) and `ORYA_MEMORY_DIR`

---

## ⚙️ Configuration

**Precedence**: env vars → `.env` (cwd) → `~/.orya/config.yaml` → defaults. YAML fallback applies to ~10 fields in `_YAML_FALLBACKS` only when env/.env don't set them; `${ENV_VAR}` substitution, unresolved keys treated as missing. `get_settings()` is `@lru_cache` — never bind `settings` at import time. `ORYA_CONFIG_PATH` relocates the user config.

### LLM settings

| Var | Effect |
| --- | --- |
| `ORYA_LLM_PROVIDER` / `ORYA_LLM_MODEL` | Default provider / alias |
| `ORYA_LLM_API_KEY` / `ORYA_LLM_BASE_URL` | Override key / base URL |
| `ORYA_LLM_TEMPERATURE` / `ORYA_LLM_MAX_TOKENS` | Sampling / output cap |
| `ORYA_LLM_TIMEOUT_S` / `ORYA_LLM_RETRY_ATTEMPTS` / `ORYA_LLM_RETRY_BACKOFF_SECONDS` | Timeout + retry |
| `ORYA_LLM_TRACE_ENABLED` | `TracedChatModel` on/off (A-02) |
| `ORYA_LLM_TRACE_EXPORTER` | Exporter selection |

### Cost router (A-13 / A-14)

| Var | Effect |
| --- | --- |
| `ORYA_COST_ROUTER_ENABLED` | Kill-switch |
| `ORYA_COST_BUDGET_DEFAULT_USD` | Per-identity daily budget |
| `ORYA_COST_ROUTER_FALLBACK_MODEL` | Degrade target |
| `ORYA_COST_BACKEND` | `auto` / `memory` / `redis` |

### Tiered router (A-18)

| Var | Effect |
| --- | --- |
| `ORYA_TIERED_ROUTER_SMALL_MODEL` | `tier=small` alias (default `claude-haiku-3.5`) |
| `ORYA_TIERED_ROUTER_LARGE_MODEL` | `tier=large` alias (default `claude-sonnet-3.5`) |
| `ORYA_TIERED_ROUTER_TOURNAMENT_MODEL` | `tier=tournament` alias (ALPHA degrades tournament → `large`) |

Env wins over YAML, YAML over defaults — `~/.orya/config.yaml`:

```yaml
tiered_router:
  models:
    small: ["claude-haiku-3.5"]
    large: ["claude-sonnet-3.5"]
    tournament: ["claude-sonnet-3.5", "deepseek-chat"]
```

### Prompt cache (A-19)

| Var | Effect |
| --- | --- |
| `LLM_PROMPT_CACHE_ENABLED` | Provider-native prompt caching on/off (default on) |
| `LLM_PROMPT_CACHE_TTL` | Prefix-cache TTL in seconds (default `300`) |
| `LLM_PROMPT_CACHE_MAX_SIZE` | Max cached prefixes (default `1000`) |

### Connection pool (A-20)

| Var | Effect |
| --- | --- |
| `CONNECTION_POOL_ENABLED` | Keepalive pool kill-switch (default on; `false` = stock per-model clients) |
| `LLM_POOL_SIZE` | Hot connections per provider — default `4`, max `16` |
| `LLM_POOL_HEALTH_INTERVAL` | Health-check period in seconds (default `30`, `0` disables the lifespan worker) |

The pool hands `get_llm()` a warm async client per provider (httpx; the
anthropic SDK gets its vendored `httpx2` fork), stamps `tcp.pool_hit` /
`tcp.connect_duration_ms` on the turn's `llm.call` spans and exposes
`orya_llm_pool_size` / `orya_llm_pool_hit_rate` /
`orya_llm_pool_unhealthy_total` on `/metrics`.

### Auth / CORS (A-00)

| Var | Effect |
| --- | --- |
| `AUTH_ENABLED` | Toggle bearer-JWT middleware |
| `AUTH_SECRET_KEY` / `AUTH_ALGORITHM` | JWT signing |
| `AUTH_TOKEN_TTL_S` | Default token lifetime |
| `AUTH_PUBLIC_PATHS` | Public paths (always includes `/health`) |
| `ORYA_TRUSTED_CLIENTS` | Trusted-IP short-circuit |
| `ORYA_CORS_ORIGINS` | Allowed origins (non-wildcard in prod) |

### Rate limit (A-01)

| Var | Effect |
| --- | --- |
| `ORYA_RATE_LIMIT_ENABLED` | Kill-switch (default off) |
| `ORYA_RATE_LIMIT_RPM` | Per-identity RPM |
| `ORYA_RATE_LIMIT_LEARN_RPM` | Separate `/learn` RPM |
| `ORYA_RATE_LIMIT_BACKEND` | `auto` / `memory` / `redis` |

### Permissions & recovery

| Var | Effect |
| --- | --- |
| `ORYA_PERMISSION_POLICY` | `strict` / `permissive` |
| `ORYA_PERMISSIONS_PATH` | Override rules file (`~/.orya/permissions.yml`) |
| `ORYA_PERMISSION_AUDIT_ENABLED` | A-03 spans |
| `ORYA_RECOVERY_MAX_ROUNDS` | M-28 recover rounds |
| `ORYA_RECOVERY_VARIANTS` | M-28 variants per round |
| `ORYA_RECURSION_LIMIT` | LangGraph recursion cap |

### Database & Redis

| Var | Effect |
| --- | --- |
| `ORYA_DATABASE_URL` / `DATABASE_URL` | Postgres DSN (asyncpg) |
| `ORYA_DATABASE_POOL_SIZE` / `ORYA_DATABASE_MAX_OVERFLOW` | Pool sizing |
| `ORYA_REDIS_URL` / `REDIS_URL` | Redis DSN |
| `ORYA_REDIS_POOL_MAX_CONNECTIONS` / `ORYA_REDIS_SOCKET_TIMEOUT_SECONDS` | Pool tuning |
| `POSTGRES_PORT` | Host-side port override |

### Cache (M-21 / A-07)

| Var | Effect |
| --- | --- |
| `ORYA_CACHE_BACKEND` | `auto` / `memory` / `redis` |
| `ORYA_CACHE_MAX_ENTRIES` | In-memory LRU cap |
| `ORYA_CACHE_TTL_SECONDS` | Per-entry TTL |

### Memory (M-25 / M-27)

| Var | Effect |
| --- | --- |
| `ORYA_MEMORY_DIR` | Directory for the six MD files |
| `ORYA_MEMORY_COMPACT_INTERVAL_SECONDS` | Compactor pass interval (`0` = off) |

### Sessions / session-log (M-14 / A-05 / A-06)

| Var | Effect |
| --- | --- |
| `ORYA_SESSIONS_DIR` | JSONL session store |
| `ORYA_SESSION_LOG_ENCRYPTION_ENABLED` | A-05 toggle |
| `ORYA_SESSION_LOG_ENCRYPTION_KEY` | A-05 key (32 bytes) |

### Observability (A-02 / A-03 / A-15 / A-16 / A-17)

| Var | Effect |
| --- | --- |
| `ORYA_LLM_TRACE_ENABLED` | `llm.call` spans |
| `ORYA_PERMISSION_AUDIT_ENABLED` | Permission audit spans |
| `ORYA_LANGFUSE_HOST` | Langfuse OTLP endpoint (or sampler-proxy URL) |
| `ORYA_LANGFUSE_PUBLIC_KEY` / `ORYA_LANGFUSE_SECRET_KEY` | Langfuse project keys |
| `ORYA_LANGFUSE_DIRECT_URL` | Fail-open direct Langfuse URL |
| `ORYA_LANGFUSE_EXPORT_ENABLED` | Exporter kill-switch |
| `ORYA_AGENT_OBS_ENABLED` | OryaObservability SDK bridge (A-16) |
| `ORYA_AGENT_OBS_GUARDRAIL_ENABLED` | PII masking (A-16) |
| `ORYA_OTEL_EXPORTER_OTLP_ENDPOINT` | Generic OTLP endpoint |
| `ORYA_LANGSMITH_API_KEY` | LangSmith (planned) |
| `ORYA_SAMPLER_PROXY_URL` | Sampler-proxy address (A-17) |
| `ORYA_ORIAHS_URL` / `ORYA_ORIAHS_TIMEOUT_S` | OriaHS MCP retrieval server (BETA) |

### Context & UI

| Var | Effect |
| --- | --- |
| `ORYA_CONTEXT_MAX_TOKENS` / `CONTEXT_MAX_TOKENS` | Context window cap (`trim_messages`) |
| `ORYA_API_URL` | Chainlit → FastAPI URL |
| `ORYA_CHAINLIT_PORT` / `CHAINLIT_PORT` | UI port (default 8001) |
| `ORYA_UI_SETTINGS_PATH` | UI settings file |
| `ORYA_NEXTJS_PORT` | Reserved Next.js UI port |
| `ORYA_ENV` | `dev` (default) / `prod` (A-12 prod-guard) |
| `ORYA_CONFIG_PATH` | Relocate `~/.orya/config.yaml` |
| `ORYA_LOG_LEVEL` / `LOG_LEVEL` | Root log level |

---

## 📁 Project Structure

```
OryaAgent/
├── app/
│   ├── main.py                  # FastAPI app + `orya` CLI entry point
│   ├── api/                     # routers: llm, sessions, learn, memory, metrics, workspace, health, middleware
│   ├── core/
│   │   ├── agent.py             # agent runtime (streaming, recover-node token drop)
│   │   ├── graph.py             # build_graph(): agent → human → tools → assess → (agent | recover)
│   │   ├── tools.py             # get_tools() → [read, write, edit, bash, grep, glob] (locked order)
│   │   ├── prompt.py            # system-prompt builder (cache-first layout)
│   │   ├── context.py           # trim_messages(messages, max_tokens, *, model)
│   │   ├── permissions.py       # PermissionPolicy (deny → allowlist → mode)
│   │   ├── security.py          # wrap_untrusted, detect_injection, validate_path
│   │   ├── cache.py             # tool-result cache (M-21)
│   │   ├── cost_tracker.py      # per-identity budget + price_usd() (A-13/A-14)
│   │   ├── config.py            # Settings (pydantic-settings, lru_cache)
│   │   ├── config_cli.py        # `orya config show|check` (A-12)
│   │   ├── workspace.py         # workspace / folder picker
│   │   ├── logging_setup.py     # file logger + uvicorn routing
│   │   ├── auth/                # bearer-JWT middleware + rate_limit (A-00/A-01)
│   │   ├── llm/
│   │   │   ├── factory.py       # get_llm(provider, model) — single seam
│   │   │   ├── tracing.py       # TracedChatModel (A-02)
│   │   │   ├── cost_router.py   # resolve_turn_model (A-13)
│   │   │   ├── registry.py      # YAML loaders (lru_cache)
│   │   │   ├── remote.py        # /v1/models discovery
│   │   │   ├── importers.py     # opencode / continue / aider / cline
│   │   │   ├── adapters/        # anthropic, gemini, openai_compat, local
│   │   │   └── providers.yaml · models.yaml · capabilities.yaml · pricing.yaml
│   │   ├── memory/
│   │   │   ├── md_store.py      # MDStore: 6 MD files, atomic append, rewrite
│   │   │   ├── compactor.py     # M-27 background compaction
│   │   │   ├── models.py        # MemoryItem
│   │   │   └── audit.py         # memory_audit_log (JSONL fallback)
│   │   └── observability/
│   │       ├── spans.py         # emit_span / timed_span seam
│   │       ├── langfuse.py      # OTLP/HTTP JSON exporter (A-15)
│   │       ├── sdk.py           # OryaObservability bridge (A-16)
│   │       └── pii.py           # PIIDetector (A-16, fail-closed)
│   ├── tools/                   # read, write, edit, bash, grep, glob, _rg, _validators
│   ├── hooks/                   # cache_invalidation
│   ├── ui/                      # chainlit_app, sessions, settings, interrupt
│   └── db/                      # schema.sql, migrate.py (Alembic), session_log.py, checkpoints.py
│       └── migrations/          # 0001_init.sql, 0002_session_log_encryption.sql
├── alembic/                     # versions/NNNN_name.py wrappers (A-11)
├── alembic.ini
├── deploy/
│   ├── Dockerfile               # multi-stage uv:python3.12-bookworm-slim
│   ├── prometheus/prometheus.yml
│   └── clickhouse/01_audit_events_hot.sql
├── scripts/                     # start.sh / start.ps1 / stop.sh / stop.ps1
├── tests/
│   ├── unit/                    # ~40 modules, always run
│   ├── integration/             # infra-conditional (Postgres, live providers, rg)
│   ├── e2e/                     # fake-model HTTP/UI round trips
│   └── smoke/                   # M-18 canonical tasks, scripted fake model
├── analytics/                   # ARCHITECT.md … ARCHITECT7.md, ROADMAP*, BACKLOG*, ADRs, spec/
├── docker-compose.yml           # profiles: default, app, observability
├── Makefile
├── pyproject.toml
├── uv.lock
├── AGENTS.md                    # agent-pair-programming conventions
├── chainlit.md                  # Chainlit project config
└── README.md                    # ← this file
```

---

## 🧪 Testing

| Suite | Path | When |
| --- | --- | --- |
| **unit** | `tests/unit/` (~40 modules) | Always — no infra |
| **integration** | `tests/integration/` | Postgres / live providers / `rg` (conditional self-skip) |
| **e2e** | `tests/e2e/` | Always — fake-model HTTP/UI round trips |
| **smoke** | `tests/smoke/` | Always — M-18 canonical tasks with a scripted fake model (A-08) |

```bash
uv run pytest                                  # ~60 s; expect conditional skips
uv run pytest tests/unit/test_config.py::test_defaults
uv run pytest tests/unit/test_llm_providers_yaml.py
```

- `asyncio_mode = auto` — no `@pytest.mark.asyncio` needed.
- **Skips are conditional, not marker-based**: Postgres tests probe asyncpg (2 s) and self-skip unless `make db-up`; live-provider tests use `require_env("DEEPSEEK_API_KEY")`; 3 grep tests skip if `rg` is missing.
- **Config-touching tests MUST sandbox**: `monkeypatch.chdir(tmp_path)`, delete `ORYA_*` env vars, `clear_settings_cache()` (and `clear_registry_cache()` for LLM YAML) before and after. Pattern: `tests/unit/test_config.py::isolated_config`.
- **Lint gate** (no typechecker exists): `make lint` = `ruff check .` + `ruff format --check .`; fix with `make format`. Order before finishing: **format → lint → test**.

---

## 🗺 Roadmap & Phases

| Phase | Status | Tickets |
| --- | --- | --- |
| **MVP** | ✅ done | `M-00` (bootstrap) → `M-28` (failure recovery) + `MVP-POLISH` |
| **ALPHA** | ✅ done | `A-00` auth · `A-01` rate-limit · `A-02` LLM trace · `A-03` perm audit · `A-04` health · `A-05` session-log encryption · `A-06` JSONL span cross-link · `A-07` cache LRU+Redis · `A-08` smoke v2 · `A-09` README v2 · `A-10` compose v2 · `A-11` Alembic · `A-12` Settings v2 + `orya config` · `A-13` CostAwareRouter · `A-14` cost spans · `A-15` Langfuse OTLP · `A-16` OryaObs SDK + PII · `A-17` sampler-proxy · `A-18` TieredModelRouter · `A-19` prompt cache · `A-20` connection pool |
| **BETA (v7)** | 📋 designed | see `analytics/ARCHITECT7.md`, `analytics/ROADMAP7.md`, `analytics/BACKLOG7.md` |

Design docs live in `analytics/` (`ARCHITECT.md` → `ARCHITECT7.md`, `ROADMAP4` → `ROADMAP7`, `BACKLOG4` → `BACKLOG7`, `MVP-POLISH.md`, `PROMPT_MVP.md` / `PROMPT_ALPHA.md` / `PROMPT_BETA.md`) plus 15 v0.1 ADRs in `analytics/adr/` and 10 v0.2 ADRs in `analytics/orya-architect2/adr/`.

---

## 🤝 Contributing

- **Spec file is only `analytics/PROMPT_MVP.md`** (underscore). Files `PROMPT-MVP.md` / `MVP-PROMPTS.md` at repo root **never existed** — do not glob or read them.
- **For ticket M-NN / A-NN**: `grep` `analytics/` for the ticket id first. Full-file reads of `ARCHITECT*.md` / `BACKLOG*.md` / `ROADMAP*.md` (50–120 KB each) are almost never needed.
- **Executed-ticket plans** in `.opencode/plans/M-*.md` override older analytics specs on conflict (deliberate deviations).
- **Module docstrings** open with the ticket id: `"""Tool: write - atomic file writer (M-08)."""`. **Commits**: `M-13: permissions (...)`.
- **Tools**: `@tool` + async + `Annotated[str, "..."]` params; blocking work via `asyncio.to_thread`; failures raise `ToolException` (chain with `from exc`).
- **Adding a prompt section** = `*_block()` → append in `build_system_prompt` (stable sections first, dynamic git/memory last) + test in `tests/unit/test_prompt.py`.
- **Windows / agent shell**: agent tool shell is **PowerShell 5.1** (no `&&`; use `; if ($?) { ... }`). `bash.py` prefers Git Bash, skips the WSL `System32\bash.exe` shim, falls back to `cmd.exe`. Makefile uses `rm`/`find` — use the `uv run ...` equivalents directly if no Git Bash.
- **Ruff**: line-length 88, double quotes, isort on, `E501`/`B904` ignored (formatter owns length).
- **External deps not in `pyproject.toml`**: `rg` (ripgrep) binary; `psycopg_pool` arrives transitively via `langgraph-checkpoint-postgres`.

See `analytics/CONTRIBUTING.md` for the long-form guide.

---

## 📄 License

[MIT](LICENSE) © OryaAgent Team.

OryaAgent integrates with (but does not bundle) the sibling `OryaObservability` SDK for advanced PII masking and the sampler-proxy; that integration is opt-in via `uv pip install -e ../OryaObservability`.
