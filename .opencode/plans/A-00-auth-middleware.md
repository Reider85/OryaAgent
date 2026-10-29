# A-00 — FastAPI middleware: auth, CORS, request-id

> Ticket: `PROMPT_ALPHA.md` §3.1 (A-00) | Estimate: 1 день | Status: executed

## Spec summary

«FastAPI middleware: auth, CORS, request-id | JWT, OAuth2 опционально» —
чистый ASGI-стек: AuthMiddleware (Bearer-JWT enforcement), SettingsCorsMiddleware
(динамическая CORS), RequestIdMiddleware (X-Request-ID). Kill-switch
`ORYA_AUTH_ENABLED` (default off) для совместимости с dev/tests.

## Deviations & decisions

1. **Отклонение от BACKLOG4 A-00 (Chainlit PasswordAuthProvider).** PROMPT_ALPHA v7
   переопределяет A-00 как FastAPI middleware вместо Chainlit UI login. Старая
   спека (users table, bcrypt, login screen) — не в v7 ALPHA scope; UI login —
   separate ticket (не в списке A-00..A-17).
2. **OAuth2 опционально (не реализовано).** В v7 ALPHA нет тикета для OAuth2;
   old BACKLOG4 A-01 (Google/GitHub OAuth) — не реализован; оставлено как optional.
3. **Pure-ASGI middleware** (не BaseHTTPMiddleware) — SSE endpoints (`/sessions/{id}/messages?stream=true`)
   проходят без буферизации, Starlette middleware stack order: auth → CORS → request-id.
4. **Stateless JWT** (no user store) — `sub` claim = identity, consumed by A-01 rate-limiter.
5. **Fail-fast validation** — weak JWT secret (≥32 chars), auth without secret raises ValidationError.

## Files

- `app/api/middleware.py` (new): `AuthMiddleware`, `SettingsCorsMiddleware`, `RequestIdMiddleware`, `install_middleware()`.
- `app/core/auth/__init__.py` (new): `create_token()`, `decode_token()`, `AuthError`.
- `app/core/config.py`: auth settings (`auth_enabled`, `auth_secret_key`, `auth_algorithm`, `auth_token_ttl_s`, `auth_public_paths`, `cors_origins`).
- `app/main.py`: `install_middleware()` call, CLI `orya auth token`.
- `.env.example`: Auth & CORS env vars with defaults.
- `tests/unit/test_auth.py` (new, 30 tests): token roundtrip, middleware unit, HTTP enforcement, request-id, CORS, CLI.
- `pyproject.toml`: PyJWT dependency.

## Verification

`ruff format` → `ruff check` → `uv run pytest` (807 passed, 24 skipped — conditional infra skips).

## DoD coverage

- ✅ Auth: все /sessions, /learn, /memory/* endpoints требуют JWT (middleware + parametrized test).
- ✅ Public paths: /health, /docs, /redoc, /openapi.json, /metrics exempt.
- ✅ CLI: `orya auth token --user` (JWT minting).
- ✅ CORS dynamic rebuild on settings change.
- ✅ Request-ID echo/mint + X-Request-ID header on all responses (even 401).
- ✅ Kill-switch default off for dev/tests compatibility.

## Follow-ups

- UI login flow (separate ticket, not in ALPHA v7 scope).
- OAuth2 providers (optional, not in ALPHA v7 scope).