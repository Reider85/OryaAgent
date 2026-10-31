# A-07 — CacheWrapper v2 (TTL + LRU) + Redis config tuning

> Ticket: `analytics/PROMPT_ALPHA.md` §3.1 (A-07) | Estimate: 6 часов | Status: executed

## Spec summary

«CacheWrapper v2 (TTL + LRU) | 6 часов | Redis config tuning» — одна строка в таблице тикетов PROMPT_ALPHA.md:77 (детальной секции для A-07 в PROMPT_ALPHA/BACKLOG6 нет). Расшифровка: MemoryCache получает LRU-эвикцию с максимальным размером (config `ORYA_CACHE_MAX_ENTRIES`), Redis-клиент настраивается с пулом соединений и таймаутами, Redis-сервер получает maxmemory + allkeys-lru политику.

## Deviations & decisions

1. **LRU только в MemoryCache.** `CacheWrapper` (Redis) полагается на серверную LRU (`maxmemory-policy allkeys-lru`); клиентская LRU-обёртка перед Redis не добавляется (дублирование, сложность). MemoryCache — `OrderedDict` с `move_to_end` и evict oldest при переполнении.
2. **max_entries=0 = unlimited.** Конфиг `ORYA_CACHE_MAX_ENTRIES` (default 1024); 0 = отключает LRU-cap (legacy behavior). Additive: новые ключи в `get_cache_stats()` — `max_entries`, `evictions`.
3. **Per-user префикс — follow-up.** Хотя auth готов (A-00), тикет сфокусирован на TTL+LRU+Redis-tuning; per-user ключи — отдельным тикетом (M-21 follow-up).
4. **Redis client pool tuning.** Добавлены `max_connections`, `socket_connect_timeout`, `socket_timeout`, `health_check_interval` через `Redis.from_url(...)`. Soft-fail behavior (Redis-ошибки → miss/warning) сохраняется (M-21).
5. **Docker-compose Redis.** `command: redis-server --maxmemory 256mb --maxmemory-policy allkeys-lru` (server-side LRU; cache eviction = miss = safe).
6. **Config fields — env-only.** Новые поля cache и Redis — env-only, не в `_YAML_FALLBACKS` (паттерн M-21).
7. **Тесты — additive.** Существующие тесты проходят без изменений; новые unit-тесты на LRU eviction order, max_entries=0, FakeRedis pool params; integration-тесты без изменений.

## Files

- `app/core/config.py` — `cache_max_entries`, Redis pool settings.
- `app/core/cache.py` — `MemoryCache` → `OrderedDict` + LRU eviction, `init_cache` pool params, `get_cache_stats` новые поля.
- `docker-compose.yml` — redis command: maxmemory + allkeys-lru.
- `.env.example` — новые `ORYA_CACHE_MAX_ENTRIES`, pool vars.
- `README.md` — brief cache section update (LRU + tuning).
- `.opencode/plans/A-07-cache-wrapper-v2.md` (this file).
- `tests/unit/test_cache.py` — LRU eviction tests, max_entries=0, evictions counter, FakeRedis pool checks.
- `tests/integration/test_cache_redis.py` — no changes (additive).

## Verification

`uv run ruff format .` → `uv run ruff check .` → `uv run pytest tests/unit/test_cache.py` (27/27 passed, 1 warning). All cache tests pass including new LRU eviction tests.

## DoD coverage

- ✅ `MemoryCache` с `max_entries=1024`: при 1025-й записи вытесняется самая старая (evict oldest).
- ✅ `MemoryCache` с `max_entries=0`: неограниченный словарь (legacy).
- ✅ `get_cache_stats()` содержит `max_entries`, `evictions` (additive).
- ✅ Redis client: `max_connections`, timeouts, health_check_interval передаются в `Redis.from_url`.
- ✅ Redis server: `maxmemory 256mb --maxmemory-policy allkeys-lru` в docker-compose.
- ✅ Существующие тесты проходят без изменений (AC).
- ✅ Новые unit-тесты покрывают LRU eviction order, edge cases (max_entries=0, evictions count).
- ✅ Soft-fail behavior Redis-ошибок сохраняется (M-21).
- ✅ `make format` → `make lint` → `uv run pytest` pass.

## Follow-ups

- Per-user префикс ключей (M-21, auth с A-00 готов).

## Commit message

`A-07: CacheWrapper v2 (TTL + LRU) + Redis config tuning` + `A-07: executed ticket plan`
- A-15: hit_rate gauge / daily aggregation; server-side `maxmemory` в прод-гайде (A-09 README v2).