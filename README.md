# OryaAgent v7.0

Senior Python coding agent with UI and long-term memory.

## Phase: MVP

Tickets M-00 (bootstrap), M-01 (LLM-provider-seam), M-02 (configuration), M-03 (PostgreSQL schema), M-04 (LangGraph core) and M-05 (system-prompt builder) are implemented.

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