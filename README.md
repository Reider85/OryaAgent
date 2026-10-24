# OryaAgent v7.0

Senior Python coding agent with UI and long-term memory.

## Phase: MVP

Tickets M-00 (bootstrap), M-01 (LLM-provider-seam), M-02 (configuration), M-03 (PostgreSQL schema), M-04 (LangGraph core), M-05 (system-prompt builder), M-06 (context manager), M-07 (tool `read`), M-08 (tool `write`), M-09 (tool `edit`), M-10 (tool `bash`), M-11 (tools `grep`/`glob`), M-12 (tool-registry integration) and M-13 (permissions) are implemented.

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

### Development Commands

- `make dev` - Start development server (FastAPI on port 8000)
- `make test` - Run tests
- `make lint` - Lint code with ruff
- `make format` - Format code with ruff
- `make clean` - Clean up build artifacts
- `make db-up` / `make db-migrate` / `make db-down` - PostgreSQL lifecycle (M-03)

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