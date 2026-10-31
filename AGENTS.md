# AGENTS.md

Senior Python coding agent (FastAPI + LangGraph + LLM provider seam). MVP phase done through M-28 + MVP-POLISH. ALPHA done through A-09: A-00 (auth middleware), A-01 (rate-limit), A-02 (seam trace-wrapping), A-03 (permission audit spans), A-04 (health endpoints), A-05 (session-log encryption), A-06 (JSONL span cross-link), A-07 (cache LRU + Redis tuning), A-08 (smoke tests v2), A-09 (README v2 deploy guide — env-var reference + README anchors test in `tests/unit/test_readme.py`). Remaining ALPHA: A-10…A-20 (Docker stack, Alembic, Settings v2, CostAwareRouter, cost-tracking, Langfuse, OryaObservability SDK, sampler-proxy, v7 additions).

## Ticket specs (read this first when implementing M-NN)

- Spec file is **only** `analytics/PROMPT_MVP.md` (underscore). Files `PROMPT-MVP.md` / `MVP-PROMPTS.md` at repo root **never existed** — do not glob or read them.
- For ticket M-NN: grep `analytics/` for the ticket id first. Full-file reads of ARCHITECT*.md / BACKLOG*.md / ROADMAP*.md (50–120KB each) are almost never needed.
- Executed-ticket plans in `.opencode/plans/M-*.md` override older analytics specs on conflict (deliberate deviations).

## Commands (uv-based; Makefile needs Git Bash on Windows)

- Install: `uv sync` (venv is Python 3.12; pyproject floor is 3.11)
- Dev server: `make dev` or `uv run uvicorn app.main:app --reload --port 8000`
- Tests: `uv run pytest` (~60s; expect many conditional skips without infra)
- Single test: `uv run pytest tests/unit/test_config.py::test_defaults`
- Lint gate (both, no typechecker exists): `make lint` = `uv run ruff check .` + `uv run ruff format --check .`; fix with `make format`
- Order before finishing: format → lint → test. No mypy/pre-commit/CI exist despite analytics docs claiming so.
- DB: `make db-up` (docker compose postgres:16), `make db-migrate` (= `python -m app.db.migrate`). Host port: `POSTGRES_PORT=5435 make db-up` + matching `DATABASE_URL`.

## Tests

- Suites: `tests/unit` (always run), `tests/integration` (infra-conditional), `tests/e2e` (fake-model HTTP/UI round trips — always run, no infra), `tests/smoke` (M-18 canonical tasks with a scripted fake model — always run). `asyncio_mode=auto` — no `@pytest.mark.asyncio` needed. No custom pytest markers registered.
- Skips are conditional, not marker-based: Postgres tests probe asyncpg (2s) and self-skip unless `make db-up`; live-provider tests use `require_env("DEEPSEEK_API_KEY")` from `tests/integration/_helpers.py`; 3 grep tests skip if `rg` missing.
- `tests/integration/test_tools_integration.py` always runs (mocks the `rg` subprocess seam via monkeypatch).
- Config-touching tests MUST sandbox: `monkeypatch.chdir(tmp_path)`, delete `ORYA_*` env vars, call `clear_settings_cache()` (and `clear_registry_cache()` for LLM YAML registries) before and after — `get_settings()`/registry loaders are `lru_cache` singletons, and repo-root `.env` leaks otherwise. Copy the pattern from `tests/unit/test_config.py::isolated_config`.

## Architecture (dependency direction matters)

- `app/main.py` — FastAPI app + `orya` CLI (`orya import --from opencode|continue|aider|cline`, `orya db migrate`).
- `app/core/llm/` — single LLM seam: `get_llm(provider, model)` (`factory.py`). **Never import `langchain_anthropic`/`langchain_openai` outside this package.** Providers live in YAML: `providers.yaml`, `models.yaml` (aliases), `capabilities.yaml`, `pricing.yaml` — adding an OpenAI-compatible provider is YAML-only; tests in `tests/unit/test_llm_providers_yaml.py` enforce structure. `app/core/llm/settings.py` is a deprecated shim → import `app.core.config`. Since A-02 the factory wraps models in `TracedChatModel` (`tracing.py`, one `llm.call` span per invocation, buffer via `get_span_buffer()`); `ORYA_LLM_TRACE_ENABLED=false` returns the raw adapter (seam tests sandbox this).
- `app/core/graph.py` — `build_graph(tools, model, checkpointer, policy, *, system_prompt_fn, trim_fn)`; nodes: `agent → human → tools → assess → (agent | recover → human)`. **The graph must not import `prompt.py`/`context.py`** — they're injected callables (cacheable-prefix ordering depends on it). M-28 adds failure recovery: `assess` triages `ToolMessage(status="error")` results, `recover` asks the model for alternatives (budgets `recovery_max_rounds`/`recovery_variants` from settings; recover-node tokens are dropped from the streamed reply in `app/core/agent.py`).
- `app/core/tools.py` — `get_tools()` returns exactly `[read, write, edit, bash, grep, glob]` **in that order**; graph, prompt builder, and tests assert this. Never hardcode a tool list elsewhere.
- `app/core/permissions.py` — `PermissionPolicy`: precedence deny → session allowlist → allowlist → mode. Fail-closed: no checkpointer ⇒ `ask` = deny; unknown resume answer = deny; a mixed approve/refuse batch is wholly refused.
- `app/core/context.py` — `trim_messages(messages, max_tokens, *, model)` signature is an architectural invariant (v7 BETA keeps it).
- `app/core/memory/` — L0 memory seam (M-25): `MDStore` over the six MD files in `settings.memory_dir` (`append/read/read_all/mtime/stats` + `compact_if_needed` hook), `get_md_store()` as the cached entry point, `record_memory_op()` for the best-effort `memory_audit_log` row (JSONL fallback). Prompt builder and `/learn` (M-26) go through it — never open the MD files directly. Append = one `os.write` into `O_APPEND` + `fsync` under a per-file lock (`O_BINARY` on Windows; tmp+`os.replace` only for rewrites); records use `MemoryItem.to_markdown()` (ARCHITECT6 §3.1.1). M-27 adds `Compactor` (`compactor.py`, re-exported from the package): strategies partition **raw blocks** (headers/free text always kept) → append to `memory/archive/{stem}_{UTCdate}.md` **first**, then `MDStore.rewrite(file, transform)` (locked read-modify-write) — never delete, never rewrite without the lock; `get_compactor()`/`compaction_worker(interval)` (lifespan, `ORYA_MEMORY_COMPACT_INTERVAL_SECONDS`, 0 = off). `/memory*` endpoints live in `app/api/memory.py` as **union paths** (`/memory/...` + `/sessions/{id}/memory/...` over shared handlers).
- `app/db/` — app tables use **asyncpg** (`schema.sql` canonical + `migrations/NNNN_name.sql`); checkpoints use a **separate psycopg pool** (`checkpoints.py`, `AsyncPostgresSaver.setup()`). **A schema change requires editing BOTH `schema.sql` AND a new migration file** — `tests/unit/test_db_schema.py` fails on drift. Checkpoint tables are not in schema.sql.
- `app/ui/` = Chainlit (M-15+), since M-24 a pure httpx client of FastAPI: `ORYA_API_URL` (default `http://127.0.0.1:8000`), sessions via `POST /sessions`, turns via `POST /sessions/{id}/messages?stream=true` + `/resume?stream=true` (SSE frames `token`/`tool_start`/`tool_end`/`interrupt`/`done`/`error`) — the UI never builds or drives a graph. Redis backs the M-21 tool-result cache (`ORYA_CACHE_BACKEND=auto|memory|redis`, probed in the FastAPI lifespan only).

## Conventions

- Module docstrings open with ticket id: `"""Tool: write - atomic file writer (M-08).` Commits: `M-13: permissions (...)`.
- Tools: `@tool` + async + `Annotated[str, "..."]` params; blocking work via `asyncio.to_thread`; failures raise `ToolException` (chain with `from exc`). FS tools must call `validate_path()` (`app/tools/_validators.py`) before any I/O; allowed roots = cwd, `~/.orya`, `settings.memory_dir`. Writes are atomic (`mkstemp` same dir → fsync → `os.replace`).
- User-visible file/shell output goes through `wrap_untrusted()`/`detect_injection()` (`app/core/security.py`); bash/grep/glob return a single JSON document. Read-only tools may use `get_cache()`; write/edit/bash never cache (they call `invalidate_cache_for_path()` — M-21). A cache hit through the ToolNode returns `ToolMessage(metadata={"from_cache": True})` (`from_cache_result()` in `app/core/cache.py`).
- Adding a tool = 5 steps: `app/tools/<name>.py` + `__init__.py` re-export + `get_tools()` + `EXPECTED_NAMES`/`EXPECTED_REQUIRED_ARGS` in `tests/integration/test_tools_integration.py` + unit tests; add read-only tools to the permission allowlist.
- Adding a prompt section = `*_block()` → append in `build_system_prompt` (stable sections first, dynamic git/memory last) + test in `tests/unit/test_prompt.py`.
- Memory: write L0 entries via `MDStore.append()` (never `open(path, "w")`/manual append), build them with `MemoryItem.create()`, and treat `record_memory_op()` as never-raising. Empty L0 files are meaningful — prompt placeholders (`(empty)`, `(no PROJECT.md`) key off blank content. Compaction belongs to `Compactor` (never hand-roll a rewrite: it must archive first, then `MDStore.rewrite`).
- Ruff: line-length 88, double quotes, isort on, E501/B904 ignored (formatter owns length).

## Config

Precedence: env vars → `.env` (cwd) → `~/.orya/config.yaml` → defaults. YAML fallback only applies to ~10 fields in `_YAML_FALLBACKS` and only when env/.env don't set them; `${ENV_VAR}` substitution, unresolved keys treated as missing. `get_settings()` is `@lru_cache` — never bind `settings` at import time; use `get_settings()`. `ORYA_CONFIG_PATH` relocates user config.

## Windows / agent shell

- Agent tool shell is **PowerShell 5.1**, not bash: no `&&` (use `; if ($?) { ... }`), quote paths with spaces, `$ErrorActionPreference` matters.
- `rg` is often **not on the agent PATH** even though grep/glob tools need it. For log/DB analysis use `Select-String` or Python; installing ripgrep un-skips 3 unit tests.
- Inline Python: pipe via here-string `$code = @'...'@ | python -` (nested quotes in `python -c` break in PS 5.1).
- `analytics/*.md` may be **Windows-1251** (Cyrillic). Use `Get-Content -Encoding` / Python `encoding='cp1251'` if mojibake.
- psycopg checkpoints **cannot** run on ProactorEventLoop → Postgres tests build an explicit `SelectorEventLoop` on win32 (copy from `tests/integration/test_db_postgres.py:214`). Uvicorn already uses Selector.
- `bash.py` prefers Git Bash (`...\Git\bin\bash.exe`), explicitly skips the WSL `System32\bash.exe` shim, else `cmd.exe`.
- Makefile uses `rm`/`find` → use the `uv run ...` equivalents directly if no Git Bash.

## External deps not in pyproject

- `rg` (ripgrep) binary required by grep/glob tools (ToolException if missing; both shell out through the shared seam `app/tools/_rg.py` — split out of `search.py` in MVP-POLISH-8).
- `psycopg_pool` is used by checkpoints but only arrives transitively (via `langgraph-checkpoint-postgres`) — don't rely on it staying.
