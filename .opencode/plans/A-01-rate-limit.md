# A-01 — Rate-limiter (per-user 60 rpm, /learn 10 rpm)

> Ticket: `PROMPT_ALPHA.md` §3.1 (A-01) + §9 DoD + §11 risks | Estimate: 6 часов | Status: executed

## Spec summary

«Rate-limiter (Redis + slowapi) | per-user: 60 rpm, per-endpoint: 10 rpm на /learn» —
production anti-abuse: каждый JWT-пользователь получает 60 запросов в минуту,
эндпоинты /learn (оба: `POST /learn` и `POST /sessions/{id}/learn`) — 10 rpm.
429 Too Many Requests + `Retry-After`. Whitelist trusted clients
(`ORYA_TRUSTED_CLIENTS`, PROMPT §11).

## Deviations & decisions

1. **Отклонение от «slowapi» (буквально).** slowapi middleware — BaseHTTPMiddleware
   (буферизует SSE `/sessions/{id}/messages?stream=true`, из-за чего A-00 перешёл
   на pure-ASGI), его Redis-хранилище — синхронный redis (блокирует event loop).
   Реализован собственный pure-ASGI `RateLimitMiddleware` + `RateLimiter`-шов на
   `redis.asyncio` (тот же стиль, что M-21 CacheWrapper). Зависимость slowapi
   не добавляется.
2. **Kill-switch default OFF** (`ORYA_RATE_LIMIT_ENABLED=false`) — консистентно с
   A-00 (`ORYA_AUTH_ENABLED=false`): dev, Chainlit UI и e2e/smoke сьюты не
   ломаются; в prod включается env-ом.
3. **Fixed window** (INCR+EXPIRE / dict, окно = календарная минута) — «60 rpm»
   читается буквально; `Retry-After` = секунды до конца окна. Token-bucket из
   старого BACK4 A-02 — не нужен.
4. **Ключ бакета**: `user:{user_id}` (из JWT `sub`, который A-00 кладёт в
   `scope["state"]["user_id"]`); когда auth выключен — fallback на client IP
   (`scope["client"][0]`). Per-endpoint лимит тоже per-user
   (`ep:{user_id}:learn`), чтобы один пользователь не задевал других.
5. **Trusted clients** (`ORYA_TRUSTED_CLIENTS`, CSV/JSON) — совпадение с
   user_id ИЛИ client IP; exempt без инкремента счётчиков.
6. **Exempt-пути**: те же public prefixes, что у auth (`auth_public_path_list`:
   /health, /docs, /redoc, /openapi.json, /metrics) + OPTIONS preflight —
   health-check'и балансировщика не должны съедать лимит.
7. **Soft-fail как в M-21**: Redis недоступен → in-memory счётчики
   (auto); `ORYA_RATE_LIMIT_BACKEND=redis` — fail-fast. Ключ Redis:
   `orya:rate:{scope}:{user}:{window}` TTL 120 s.
8. **Порядок middleware**: RateLimit добавляется ПЕРВЫМ (innermost) —
   выполняется после auth (нужен user_id), CORS/request-id остаются снаружи
   (429 получает CORS- и X-Request-ID-заголовки).

## Files

- `app/core/auth/rate_limit.py` (new): `MemoryRateLimiter`, `RedisRateLimiter`,
  `RateDecision`, `get/set/init/close_rate_limiter()`.
- `app/api/middleware.py`: `RateLimitMiddleware` + `_reject_too_many()`,
  `install_middleware` wiring.
- `app/core/config.py`: `rate_limit_enabled`, `rate_limit_rpm`,
  `rate_limit_learn_rpm`, `rate_limit_backend`, `rate_limit_trusted_clients`
  (+ `rate_limit_trusted_list` property).
- `app/main.py`: lifespan `init_rate_limiter()` / `close_rate_limiter()`.
- `.env.example`: A-01 block.
- `tests/unit/test_rate_limit.py` (new): settings, MemoryRateLimiter,
  RedisRateLimiter (FakeRedis), middleware unit + HTTP (429/Retry-After/
  trusted/kill-switch/learn 10 rpm/DoD 60 rpm).
- `tests/integration/test_rate_limit_redis.py` (new, skip без Redis).
- `AGENTS.md`: статусная строка ALPHA (A-00, A-01, A-02).

## Verification

`make format` → `make lint` → `uv run pytest`.

## DoD coverage

- ✅ 60 rpm per-user → 429 с Retry-After на 61-м запросе (per-user bucket).
- ✅ 10 rpm на `/learn` и `/sessions/{id}/learn` (per-user-per-endpoint).
- ✅ Kill-switch default off; включение — `ORYA_RATE_LIMIT_ENABLED=true`.
- ✅ Trusted clients (`ORYA_TRUSTED_CLIENTS`) не лимитируются.
- ✅ Redis-backed (ключи `orya:rate:*`, TTL); memory fallback без Redis.
- ✅ SSE-safe: pure-ASGI middleware, стримы не буферизуются.

## Follow-ups

- A-04/A-15: экспорт счётчиков лимитера в Prometheus (`/metrics`).
- Token-bucket precision (сглаживание границ окна) — если NFR ужесточатся.
