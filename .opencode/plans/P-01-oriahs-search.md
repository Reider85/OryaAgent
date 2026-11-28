# P-01 — oriahs_search: contract alignment and registry exposure

> Ticket: P-01 (v6 PROD baseline, `analytics/PROMPT_PRODUCTION.md:121`) | Estimate: 1 day | Status: executed

## Spec summary

- Detailed contract: `analytics/old/BACKLOG4.md:1919-1935` + `analytics/old/ARCHITECT4.md:963-1009`.
- `oriahs_search(query, top_k=20 [1..100], filters=None, rerank=True, fusion="rrf", explain=False) -> str`; markdown list with `file:line` + snippet.
- v7 relabel: semantic codebase search **through MCP** (`PROMPT_PRODUCTION.md:121`); tool must be available to the agent and degrade silently (`service unavailable, use grep`).

## Deviations & decisions

- **MCP seam kept.** The v4 spec called the backend directly from the tool; P-00 (`40a4744`) established `tool → oriahs-mcp HTTP facade → POST /search`, so the new knobs are threaded through the facade instead. `tenant_id` injection (fresh REST contract) is retained.
- **`Annotated` params, not `args_schema=OriasSearchInput`.** AGENTS.md mandates `@tool` + `Annotated`, and `tests/integration/test_tools_integration.py` converts every tool through `convert_to_openai_function`.
- **Config-resolved defaults.** `top_k`/`rerank`/`fusion`/`explain` default to `None` in the signature and resolve from `Settings` at call time; this satisfies "never bind settings at import time" while keeping effective defaults 20 / true / rrf / false.
- **Cache key includes the effective knobs**, so changing settings cannot serve a stale result. TTL is config-driven.
- **Kill-switch `ORYA_ORIAHS_SEARCH_ENABLED=false`** degrades to the exact P-00 fallback message with a `semantic.search` span (`status=degraded`) — never a UI error.
- **Trigger map** (`app/core/tools/triggers.py:69`) is left unchanged; capability-based filtering remains inert until that seam is wired.
- Dead `_fallback_lexical_search()` (different message, never called) removed.

## Files

- `app/core/config.py` — 7 P-01 Settings fields with legacy aliases.
- `app/core/mcp_config.py` — `get_fallback_config()` now derives from Settings (single source of truth).
- `app/core/oriahs_client.py` — `line` in mapped hits; `search()` forwards P-01 knobs.
- `app/mcp/oriahs_mcp.py` — `hybrid_search` MCP schema + validation + forwarding.
- `app/tools/oriahs_search.py` — signature, validation, cache key, MCP args, `file:line` output, kill-switch.
- `app/tools/__init__.py`, `app/core/tools/__init__.py` — tool exported and appended to the live registry (8th position).
- `app/core/permissions.py` — read-only allow rule.
- `.env.example`, `README.md`, `docs/B-02-oriahs-search-tool.md` — env reference updated (`test_readme.py` pins every env alias in README).
- Tests: `tests/test_oriahs_search.py`, `tests/unit/test_oriahs_client.py`, `tests/integration/test_oriahs_mcp_integration.py`, `tests/integration/test_tools_integration.py`, `tests/unit/test_tools.py`, `tests/unit/test_config.py`.

## Verification

```powershell
uv run ruff format .
make lint
uv run pytest tests/test_oriahs_search.py tests/unit/test_oriahs_client.py tests/integration/test_oriahs_mcp_integration.py tests/integration/test_tools_integration.py tests/unit/test_tools.py tests/unit/test_config.py tests/unit/test_readme.py
uv run pytest
```

Full-suite note: the repo already carried 7 untracked WIP files
(`app/api/contracts.py`, `app/api/notifications.py`, `app/core/contract_timer.py`,
`app/core/notifications.py`, `app/core/scheduler.py`,
`app/db/migrations/003_contracts_notifications.*`) with 116 ruff errors and
many unrelated full-suite failures (`agent.py:564 KeyError: 'pending'`,
missing `MDStore.get_session_memory_dir`, BETA capability/UKB registry
expectations). P-01 scoped tests and `tests/performance/test_oriahs_search_performance.py`
are green; those pre-existing failures were not touched.

## DoD

- `get_tools()` returns 8 tools in canonical order (`oriahs_search` last); OpenAI schemas pin `query` as the only required arg.
- P-01 signature/knobs valid; `top_k` 1..100; `fusion` restricted to `rrf|weighted`; output contains `file:line`.
- Backend unreachable or tool disabled → exact fallback string, no exception in the user stream.
- Spans `semantic.search` / `mcp.call` and semantic-search metrics unchanged/annotated.
- `format → lint → test` green (no infra needed for the P-01 tests).

## Commit message

`P-01: oriahs_search contract alignment and registry exposure (...)`

(Only commit on explicit user request.)
