# OryaAgent v7.0

Senior Python coding agent with UI and long-term memory.

## Phase: MVP (M-00 Bootstrap)

This is the bootstrap phase (M-00) of OryaAgent v7.0. The project structure has been initialized and is ready for development.

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

Copy `.env.example` to `.env` and configure your LLM provider API keys:

```bash
cp .env.example .env
# Edit .env with your API keys
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

- ✅ **M-00** - Bootstrap project structure (this phase)
- 📋 **M-01** - LLM-provider-seam (next)
- 📋 **M-02** - pydantic-settings configuration
- 📋 **M-03** - PostgreSQL schema
- ... (see [PROMPT_MVP.md](analytics/PROMPT_MVP.md) for full 28 tickets)

## Notes

- This is a **bootstrap phase** - minimal working structure only
- Next phase will implement LLM provider integration and basic agent functionality
- Windows: `make` command may require Git Bash/WSL or use `uv run ...` directly
- Docker Compose is optional for M-00 but required for full MVP (M-03+)

---

Built with ❤️ using LangChain, LangGraph, FastAPI, Chainlit, PostgreSQL, and Redis.