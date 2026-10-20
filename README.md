# OryaAgent v7.0

Senior Python coding agent with UI and long-term memory.

## Phase: MVP

Tickets M-00 (bootstrap), M-01 (LLM-provider-seam) and M-02 (configuration) are implemented.

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

## Documentation

- [Architecture v7](analytics/ARCHITECT7.md)
- [Roadmap v7](analytics/ROADMAP7.md)
- [Backlog v7](analytics/BACKLOG7.md)
- [MVP Phase Prompt](analytics/PROMPT_MVP.md)

## Phase Progress

- ✅ **M-00** - Bootstrap project structure
- ✅ **M-01** - LLM-provider-seam: `get_llm()`, 34 providers (YAML registries), importers, `/llm/*` endpoints
- ✅ **M-02** - pydantic-settings configuration: `Settings`, `~/.orya/config.yaml` merge, env/.env priority
- 📋 **M-03** - PostgreSQL schema
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