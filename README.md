# OryaAgent v7.0

Senior Python coding agent with UI and long-term memory.

## Phase: MVP

Tickets M-00 (bootstrap), M-01 (LLM-provider-seam), M-02 (configuration), M-03 (PostgreSQL schema), M-04 (LangGraph core), M-05 (system-prompt builder), M-06 (context manager), M-07 (tool `read`), M-08 (tool `write`), M-09 (tool `edit`), M-10 (tool `bash`), M-11 (tools `grep`/`glob`), M-12 (tool-registry integration), M-13 (permissions), M-14 (session-log), M-15 (Chainlit UI), M-16 (permission ask-prompt), M-17 (sidebar/settings), M-18 (smoke tests), M-20 (sessions API), M-21 (Redis cache), M-22 (prompt-injection defense), M-23 (token-efficient output) and M-24 (Chainlit via FastAPI/SSE) are implemented.

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

6. **Start the Chainlit UI (another terminal):**
   ```bash
   make ui
   ```
   The chat opens on http://localhost:8001 and talks to the FastAPI server over HTTP/SSE (`ORYA_API_URL`, default `http://127.0.0.1:8000`) ? `make dev` must be running.

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

```python
from app.core.config import get_settings

settings = get_settings()
```

## Project Structure

```
app/
├── main.py              # FastAPI entry point
├── core/               # Core components (M-01+)
├── tools/              # Coding tools (M-07+)
├── api/                # API endpoints (M-20+)
└── ui/                 # Chainlit UI (M-15+)
tests/                  # Test suites
└── conftest.py         # Test configuration
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
4. **Long-term memory** — `LEARNED.md` + `PREFERENCES.md` (L0, M-25 files), capped at 8 KB.
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

## Sessions API (M-20)

`app/api/sessions.py` exposes the session lifecycle for every client: CI and batch jobs over JSON, the Chainlit UI (M-24) over SSE. The UI never touches the graph ? `Chainlit → FastAPI → LangGraph` ? and both response modes share the session-agent runtime in `app/core/agent.py` (graph assembly, checkpointer fallback, `stream_turn`/`run_turn`).

| Endpoint | Purpose |
|---|---|
| `POST /sessions` | Create a session (server-side uuid4) → `{session_id, created_at, status, ...}` |
| `GET /sessions?page=1&size=20` | Paginated list, newest activity first → `{items, total, page, size}` |
| `GET /sessions/{id}` | Metadata + typed `messages` (M-14 log), 404 when unknown |
| `POST /sessions/{id}/messages` | Run one full turn — JSON by default, SSE stream with `?stream=true` (see below) |
| `POST /sessions/{id}/resume` | Answer a pending permission interrupt: `{decision: "allow"\|"deny"\|"always"}`, 409 when nothing is pending; also streamable with `?stream=true` |
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

## Tool-result cache (M-21)

Repeated tool calls for unchanged files are served from a cache instead of re-running the tool (TRIZ #28). The seam lives in `app/core/cache.py`:

- **Keys:** `orya:tool_cache:{tool}:{sha256(args + mtime_ns)}` — the file mtime is part of the key, so any change makes the next call a miss automatically.
- **Backends:** `CacheWrapper` (Redis) is the primary backend; `ORYA_CACHE_BACKEND` selects `auto` (probe Redis at startup, fall back to `MemoryCache` with a warning — the default), `redis` (fail fast) or `memory` (never touch Redis). TTL is `ORYA_CACHE_TTL_SECONDS` (default 300s per BACKLOG5).
- **Cacheable:** `read`, `grep`, `glob`. Never cached: `write`, `edit`, `bash` (side effects) — write/edit instead call `invalidate_cache_for_path()` (`app/hooks/cache_invalidation.py`), which drops every entry registered for the changed path through the Redis `orya:tool_cache:idx:{path}` index.
- **Cache-hit marker:** when a tool call goes through the graph, a hit returns a `ToolMessage` with `metadata={"from_cache": true}` (direct `ainvoke()` calls keep returning the plain payload).
- **Stats:** process-local per-tool counters (Redis additionally mirrors `orya:cache_stats:{date}:{tool}` hashes).

```bash
make redis-up   # start Redis (docker compose), optional — auto mode falls back to memory
curl -s localhost:8000/metrics            # Prometheus text: orya_tool_cache_hits_total{tool="read"}
curl -s localhost:8000/tools/cache-stats  # {"backend": "...", "tools": {"read": {"hits": 1, "misses": 1, "hit_rate": 0.5}}}
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

## Documentation

- [Architecture v7](analytics/ARCHITECT7.md)
- [Roadmap v7](analytics/ROADMAP7.md)
- [Backlog v7](analytics/BACKLOG7.md)
- [MVP Phase Prompt](analytics/PROMPT_MVP.md)

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
- ... (see [PROMPT_MVP.md](analytics/PROMPT_MVP.md) for full 28 tickets)

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

- This is a **bootstrap phase** - minimal working structure only
- Next phase will implement LLM provider integration and basic agent functionality
- Windows: `make` command may require Git Bash/WSL or use `uv run ...` directly
- Docker Compose is optional for M-00 but required for full MVP (M-03+)

---

Built with ❤️ using LangChain, LangGraph, FastAPI, Chainlit, PostgreSQL, and Redis.