# Plan: M-21 — CacheWrapper (Redis для read/grep/glob)

**Status:** executed
**Commit message:** `M-21: Redis CacheWrapper (path invalidation, per-tool stats, from_cache metadata)` + `M-21: /metrics + /tools/cache-stats` + `M-21: executed ticket plan`
**Spec:** `analytics/PROMPT_MVP.md` §3.4 M-21 (фазовый источник) + BACKLOG5 M-21 + ARCHITECT5 §6.4/§7.2/§8.1/§9.1

**User decisions (утверждены до исполнения):**
1. Эндпоинты: **оба** — `/metrics` (Prometheus text, руками, без prometheus-client) **и** `/tools/cache-stats` (JSON); gauge hit_rate → A-15.
2. TTL default **300 с** (BACKLOG5 «5 минут»), конфиг `ORYA_CACHE_TTL_SECONDS`.
3. Дефолтный бэкенд **`auto`**: probe Redis → fallback MemoryCache + warning (soft-fail по образцу M-14); `redis` = fail-fast; `memory` = без сети.

## Context

- Сема M-07 уже в `app/core/cache.py` (`CacheLike{get,set}`, `MemoryCache`, `get/set_cache`, `build_cache_key` = sha256(args+mtime)); read/grep/glob кэшируют, write/edit/bash — нет. Модуль был stdlib-only, `DEFAULT_TTL_SECONDS=3600`.
- Тулы возвращали `str` — `from_cache` в `ToolMessage.metadata` отсутствовал; инвалидация была только «lazy» (mtime в ключе); Redis (`redis>=5`, сервис в docker-compose, `REDIS_URL` в `.env.example`) нигде не подключался; не было статистики и `/metrics`.
- Эмпирическая проверка на установленных langchain-core 1.6.12 / langgraph 1.2.16: `ToolRuntime` хранится в `langgraph.prebuilt.tool_node`, `Annotated[ToolRuntime | None, InjectedToolArg]` **скрыт** от LLM-схемы (`tool_call_schema`/`convert_to_openai_tool` его не видят) и **инжектится именем** `runtime` только через ToolNode; прямой `ainvoke()` получает `None`. Хит возвращает `ToolMessage(metadata={"from_cache": True})` с корректным `tool_call_id` (проверено end-to-end через ToolNode). `ToolMessage.metadata` в lc 1.6 — pydantic *extra* (не field), переживает graph state и checkpointer.

## Deviations from spec (deliberate, planned)

| Spec says | Done | Why |
|---|---|---|
| BACKLOG5: key = `sha256(args)` + SCAN + `path in cached` | ключ как в PROMPT_MVP (args+**mtime**) + **path-index** (`orya:tool_cache:idx:{path}` → SET ключей) | mtime даёт корректность бесплатно; idx даёт O(1)-инвалидацию вместо сканирования (скетч BACKLOG5 полагался на подстроку payload) |
| Cacheable: read, grep | + **glob** (кэшируется с M-11) | read-only, консистентность |
| `CacheWrapper.scan`-invalidation для grep | grep/glob передают `path=None` в `set()`; eager-idx покрывает только single-file read | результат grep покрывает много файлов → SADD на каждый матч недопустим (до 500 RTT); корректность обеспечивает mtime+TTL |
| Redis-stats `orya:cache_stats:{date}:{tool}` — источник для /metrics | mirror `HINCRBY` best-effort; `/metrics` читает **process-local** счётчики | single-process MVP; daily aggregation (таблица `cache_stats`) + Grafana — A-15 |
| `orya_tool_cache_hit_rate` gauge в /metrics | hit_rate только в JSON `/tools/cache-stats` | M-21 AC требует только `*_hits_total`; gauge → A-15 |
| «Не использовать in-memory cache» (запрет BACKLOG5) | `auto` фолбэк на MemoryCache с warning | требование пользователя; паттерн M-14 soft-fail; `redis` backend — fail-fast для прод-конфигурации |
| Backlog AC: отмена мисса через ToolMessage? нет | `from_cache`-метадата **только на хит**; мисс остаётся `str` | «при cache-hit: ToolMessage с metadata» (BACKLOG5); payload байт-в-байт идентичен (smoke AC не сломан) |
| Pre-search кэш grep (follow-up M-12) | не делаем | вне AC M-21; для «новый файл попал в матч» нужен отдельный дизайн ключа |
| Изоляция per-user | без user_id (нет auth в MVP) | схема ключа документирована под будущий префикс |

## Design (исполнено)

1. **`app/core/config.py`** — `cache_ttl_seconds` (default 300) и `cache_backend: auto|memory|redis` (default auto); env-only, не в `_YAML_FALLBACKS` (~9 полей сохранены).
2. **`app/core/cache.py`** — расширен:
   - `DEFAULT_TTL_SECONDS = 300`; `_Stats` (per-tool hits/misses, глобальные `.hits/.misses` сохранены);
   - `MemoryCache`: `_by_path` index + `invalidate(path)` + `stats()`; `set(..., path=None)`;
   - **`CacheWrapper(redis, ttl)`**: `GET/SET ex`, `SADD/SMEMBERS/DELETE` по idx, `HINCRBY/EXPIRE` daily-stats (best-effort), любые Redis-ошибки → miss/skip + warning (`ping()`/`close()`); bytes-decode tolerant;
   - `init_cache(force=False)` (идемпотентный; auto-probe c `REDIS_PROBE_TIMEOUT_S=1.0`, закрытие клиента при фолбэке) / `close_cache()` (aclose + reset + сброс флага);
   - `get_cache_stats()` → `{backend, ttl_seconds, tools:{tool:{hits,misses,hit_rate}}}`;
   - `from_cache_result(content, name, tool_call_id)` — ToolMessage со следом `from_cache` либо `str`.
3. **`app/hooks/cache_invalidation.py`** (+`__init__`) — `invalidate_cache_for_path()`: getattr-guard + soft-fail; вызывается из **write** и **edit** после успешной записи.
4. **Тулы**: read/grep/glob получили параметр `runtime: Annotated[ToolRuntime | None, InjectedToolArg] = None` (скрыт от модели) и на хит возвращают `from_cache_result(...)`; `cache.set(..., path=str(resolved))` в read; grep/glob — `path=None` (см. deviations). `graph.py` **не трогали**.
5. **`app/api/metrics.py`** (new, router без prefix): `GET /metrics` (text/plain; version=0.0.4, `# HELP/# TYPE` + `orya_tool_cache_{hits,misses}_total{tool="…"}`) и `GET /tools/cache-stats` (JSON); регистрация в `app/main.py`.
6. **Wiring**: lifespan `app/main.py` → `await init_cache()` / `await close_cache()`; `on_chat_start` в Chainlit → `await init_cache()` (идемпотентность).
7. **Makefile**: `redis-up` / `redis-down`; **`.env.example`**: `ORYA_CACHE_BACKEND`/`ORYA_CACHE_TTL_SECONDS`; **README**: секция «Tool-result cache (M-21)» + команды + `REDIS_PORT` note + Phase Progress ✅ M-21 + intro-список; **AGENTS.md**: факт про Redis/кэш-конвенции обновлён.

## Result (файлы)

- Изменены: `app/core/config.py`, `app/core/cache.py`, `app/main.py`, `app/tools/{read,search,write,edit}.py`, `app/ui/chainlit_app.py`, `Makefile`, `.env.example`, `README.md`, `AGENTS.md`, `tests/unit/test_tools.py` (+3 теста).
- Созданы: `app/core/cache.py` — CacheWrapper/init/stats (расширен), `app/hooks/cache_invalidation.py`, `app/api/metrics.py`, `tests/unit/test_cache.py` (21), `tests/unit/test_api_metrics.py` (5), `tests/integration/test_cache_redis.py` (5).

## Verified

- `uv run ruff format .` → `uv run ruff check .` → `uv run ruff format --check .` — чисто.
- `uv run pytest -q` в трёх окружениях:
  - с живым Redis (`REDIS_URL=redis://127.0.0.1:6381`, `docker compose up -d redis` c `REDIS_PORT=6381`): **489 passed, 20 skipped**;
  - с мёртвым Redis (`REDIS_URL=redis://127.0.0.1:9`, «чистая машина»): **484 passed, 25 skipped** (5 redis-тестов self-skip);
  - дефолтное окружение (на машине уже занят 6379 чужим Redis — auto-probe его находит): **489 passed, 20 skipped**.
- Live-server smoke (`uvicorn --port 18777`): лог `Tool cache backend: CacheWrapper/Redis ... (TTL 300s)`; `/health` 200; `/metrics` отдаёт HELP/TYPE; `/tools/cache-stats` → `{"backend":"CacheWrapper","ttl_seconds":300.0,...}`.
- AC-трейс: повторный read через graph → `ToolMessage.metadata == {"from_cache": True}` (unit + redis-integration); после edit/write старые записи пути удаляются (`_entries` пуст) — eager, не только TTL; первый вызов — miss, повторный в пределах TTL — hit (unit + redis); `/metrics` содержит `orya_tool_cache_hits_total{tool="read"}`; per-tool изоляция счётчиков; cache-isolation per-user — schema-заметка (нет auth).
- LLM-схема тулов не изменилась: `runtime` отсутствует в `tool_call_schema`/OpenAI-конверсии (проверено), существующие прямые `ainvoke()`-тесты и smoke байт-в-байт прошли **без правок**.

## Follow-up

- **A-15**: hit_rate gauge в `/metrics`, prometheus-client, daily aggregation в таблицу `cache_stats`, Grafana `orya-cache-stats.json`.
- **M-24**: пробросить `from_cache` в SSE-событие `tool_end` и `tool_steps` API.
- Pre-search кэш grep (follow-up M-12) — отдельный дизайн ключа + invalidation для создания файлов.
- Per-user префикс ключа — при появлении ALPHA-auth.
- `make redis-up` на хостах с занятым 6379 → `REDIS_PORT=6381 make redis-up` + `REDIS_URL` (задокументировано в README).
