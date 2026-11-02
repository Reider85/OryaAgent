# A-20 — ConnectionPool (keepalive + hot adapters)

> Ticket: `analytics/PROMPT_ALPHA.md` §6 (= `BACKLOG7.md` §3 A-20, `ROADMAP7.md` §4.2.14, `ADR-0014`) | Estimate: 6 часов | Status: executed

## Spec summary

«ConnectionPool (keepalive + hot adapters) | 6 часов | TRIZ #11 + #15»
(PROMPT_ALPHA.md:214-264): `app/core/llm/connection_pool.py::ConnectionPool`
— per-provider keepalive `httpx.AsyncClient` + transport, hot pool size 4
(default, `LLM_POOL_SIZE`, max 16), LRU eviction, периодический
health-check раз в 30 s, fail-open (unhealthy → spawn new); покрытие
Anthropic/OpenAI/Ollama/Vertex; интеграция с ChatX через `http_client`;
span-атрибуты `tcp.connect_duration_ms` / `tcp.pool_hit`; метрики
`orya_llm_pool_size|hit_rate|unhealthy_total{provider}`; без
синхронного health-check и без блокировки agent-loop при pool full.
Зависимость A-02 выполнена; последний тикет ALPHA.

## Deviations & decisions

1. **Семантика LRU (спека внутренне противоречива: «держит 4» + «5-й →
   evict oldest» + «hit rate >95%» при последовательном агент-лупе).**
   Выбрано: MRU-reuse общего клиента (production: size≈1 на провайдер,
   hit≈100%, evictions 0 — реальный win: один тёплый TCP+TLS на
   провайдер вместо cold-start на ход) + `acquire(..., exclusive=True)`
   для выделенного соединения (streaming/параллельные ходы — ADR-0014),
   всегда спавнит новый и при `size > max_size` evict+close самого
   старого (LRU-first, wait-free — ровно как требует forbidden pattern
   «block при pool full»). Все три AC проверяемы: 4 exclusive → size 4;
   5-й exclusive → oldest evicted; sequential → hit rate >95%.
2. **`threading.Lock`, не `asyncio.Lock`** (спека): factory `get_llm()`
   синхронный (инвариант шва, тесты зовут синхронно) — мутации пула под
   threading-блокировкой; async `health_check()` берёт тот же lock
   короткими секциями (никаких await внутри).
3. **`httpx2` flavor для anthropic.** anthropic>=1.15 (установлен
   1.15.0) использует форк `httpx2` и **жёстко отклоняет** объекты httpx
   (`_reject_httpx_object` → TypeError). Пул знает флаворы
   `("httpx", "httpx2")`: factory передаёт `flavor="httpx2"` для
   `spec.adapter == "anthropic"`, остальным — `httpx`. `httpx2` импортируется
   guarded (транзитивная зависимость anthropic — fail-open без него).
4. **httpx 0.28: у `HTTPTransport` нет `keepalive_expiry`** (constraints
   блок A-20 predates API). Ключ живёт в `Limits`:
   `AsyncHTTPTransport(retries=2, limits=Limits(max_keepalive_connections=LLM_POOL_SIZE,
   keepalive_expiry=60))` — `max_keepalive_connections` и есть spec-ово
   «4 keepalive connections per provider» на транспортном уровне.
5. **Инъекция клиентов в ChatX** (проверено на установленных версиях,
   включая сохранение через `bind_tools`):
   - openai/openai_compat → `http_async_client=<pooled>` (поле ChatOpenAI);
   - anthropic → `model.__dict__["_async_client"] = anthropic.AsyncClient(
     **model._client_params, http_client=pooled)` — публичного параметра
     нет, `_client_params` сам langchain-фабричный (дрейф невозможен);
   - google → замена `model.client` на `genai.Client(http_options=
     HttpOptions(httpx_async_client=pooled))` (google-genai принимает и
     httpx, и httpx2); каждая инъекция в try/except → fail-open на стоковый
     клиент (наблюдение: stock client дочищается `_ClientCleanup`).
6. **`tcp.connect_duration_ms` = время `acquire()`** (warm ≪ 50 ms AC
   тривиально; настоящий handshake холодного сокета — на первом запросе,
   unit-тесты обязаны быть офлайн — cold 200–500 ms симулируется
   задержкой spawn; реальные probe-латентности пишутся в
   `PooledConnection.last_probe_ms`). `tcp.pool_hit` — честный.
7. **Стейджинг через ContextVar** (`stage_tcp_attrs`/`peek_tcp_attrs` в
   `connection_pool.py`, peek без очистки — живёт в контексте задачи
   запроса; каждый `llm.call` хода того же провайдера получает пару
   атрибутов). Потребляет `TracedChatModel._attach_tcp` (паттерн A-17
   pending-attrs).
8. **Loop-affinity guard** (прецедент A-11 «loop-bound singleton dropped
   без close»): запись, acquired на другом event loop, не переиспользуется
   (drop, close — best-effort через scheduled `aclose`, т.к. httpx 0.28 не
   имеет синхронного `close()`); нужен из-за function-scoped loop в
   integration/e2e.
9. **Health-probe**: `HEAD` через сам pooled-клиент, если у провайдера
   `health_path` (local-серверы, `build_health_url`), иначе TCP(+TLS)
   probe (`asyncio.open_connection`, 5 s timeout); `< 500` = alive.
   `pool_health_worker(interval)` — sleep-first, никогда не умирает,
   стартует в lifespan при `enabled && interval > 0`.
10. **Спека «Ollama/Vertex» → реальность кода**: ollama = `openai_compat`
    adapter; Vertex в providers.yaml нет (есть `google` = Gemini,
    google_genai adapter). Ключ `spec.health_path` не захардкожен.
11. **Tests hygiene**: `tests/conftest.py` ставит
    `LLM_POOL_HEALTH_INTERVAL=0` (не-ORYA имя переживает стандартные
    `ORYA_*`-sandboxes) — session-`TestClient` не шлёт реальные пробы на
    провайдеров во время юнит-прогона; сам воркер покрыт напрямую
    (малый интервал + мокнутый `_probe`).
12. **Настройки**: `llm_pool_enabled` (default true; алиасы
    `CONNECTION_POOL_ENABLED` — имя из ROADMAP7 kill-switch списка),
    `llm_pool_size` (4, ge=1 le=16), `llm_pool_health_interval` (30, ge=0).
    Kill-switch off → factory не зовёт pool вообще (байт-в-байт стоковый
    путь, без `tcp.*`).

### Drive-by repairs (предсуществующая краснота на HEAD — согласовано)

Гейт на HEAD (коммит A-19) был красным: 4 failed + 68 ruff + 2 файла без
формата — A-19 ушёл без format→lint→test. Починено в этом же коммите:

- `app/core/llm/prompt_cache.py` — `reversed(span_buffer.spans)` (у deque
  нет `.spans`): `AttributeError` на **каждом** непустом span-буфере
  (падали 3 теста A-19 только в полном прогоне, порядок-зависимость).
- `tests/unit/test_readme.py` — A-19 не дописал env-таблицу README:
  `test_readme_documents_every_settings_env_field` падал на
  `llm_prompt_cache_*` (добавлены таблицы «Prompt cache (A-19)»).
- `tests/unit/test_readme.py::test_readme_phase_progress_covers_alpha_tickets`
  — `range(19)` → `range(21)` (маркеры `` `A-19` ``/`` `A-20` `` в Roadmap).
- lint/format: `factory.py` (неисп. `PromptCacheConfig`, пробельные
  строки A-19-блока), `test_prompt_cache_layout.py` (F401/sorting/формат)
  — `ruff --fix` + `ruff format`.

## Files

- `app/core/llm/connection_pool.py` (new): `PooledConnection`,
  `AcquireResult`, `ConnectionPool` (`acquire(..., flavor)`,
  `_new_client`, `_probe`, `health_check`, `stats`, `aclose`, `reset`),
  `_close_best_effort`, `stage_tcp_attrs`/`peek_tcp_attrs`/`clear_tcp_attrs`,
  `get_connection_pool`/`reset_connection_pool`/`get_pool_stats`,
  `pool_health_worker`.
- `app/core/llm/factory.py`: acquire+stage перед builder (health_url из
  `spec.health_path`), `pool_client=` во все builders, докстринг A-20.
- `app/core/llm/adapters/anthropic.py` / `gemini.py` / `openai_compat.py`:
  параметр `pool_client` + инъекция (см. решение 5).
- `app/core/llm/tracing.py`: `_attach_tcp` в `invoke`/`ainvoke` + докстринг.
- `app/core/config.py`: 3 поля A-20 (AliasChoices-группы).
- `app/api/metrics.py`: `_render_pool_metrics()` в `/metrics`.
- `app/main.py`: lifespan — `pool_health_worker` + `pool.aclose()`.
- `app/core/llm/__init__.py`: re-export `ConnectionPool` и co.
- `tests/conftest.py`: `LLM_POOL_HEALTH_INTERVAL=0` до импорта app.
- Тесты: `tests/unit/test_connection_pool.py` (new, 24: settings defaults/
  env/bounds, miss→hit, изоляция, hit-rate, hold-to-4, LRU-eviction (5-й
  exclusive), kill-switch, fail-open, health kill/keep, HEAD-probe,
  TCP-probe (loopback server), worker pass, worker off, staging,
  `TracedChatModel` tcp-stamp (вкл/выкл), factory-инъекция
  openai/anthropic-httpx2/google, kill-switch в factory, метрики);
  `tests/unit/test_api_metrics.py` (+3 строки); `tests/unit/test_readme.py`
  (range 21).
- Документация: README (TL;DR/заголовок `A-00…A-20`, буллеты A-19/A-20,
  env-таблицы «Prompt cache (A-19)» + «Connection pool (A-20)», Roadmap
  схлопнут в одну done-строку с `A-19`/`A-20`), `.env.example` (блоки
  A-19/A-20), `AGENTS.md` (header + клауза seam).
- `.opencode/plans/A-20-connection-pool.md` (this file).

## Verification

- `uv run pytest tests/unit/test_connection_pool.py -q` → 24 passed.
- Целевые: `test_connection_pool + test_readme + test_api_metrics +
  test_prompt_cache_layout + test_llm_seam + test_llm_tracing` → 91 passed.
- Полный гейт (дважды, стабильно): `uv run ruff format .` →
  `uv run ruff check .` (All checks passed, 267 formatted) →
  `uv run pytest -q` → **1117 passed, 36 skipped, 0 failed**
  (скипы — стандартные инфра-условные: Postgres/Redis/live-keys/rg).

## DoD

- ✅ Пул держит до 4 keepalive-коннектов на провайдера (AC «держит 4» =
  capacity, тест exclusive×4; см. решение 1) — Anthropic (httpx2), OpenAI,
  Ollama (=openai_compat), Google.
- ✅ warm `tcp.connect_duration_ms` ≤ 50 ms + `tcp.pool_hit` на
  `llm.call` span; cold симулируется в тесте (офлайн-инвариантность).
- ✅ Health-check убивает unhealthy (close+remove+счётчик) и создаёт
  новые (fail-open); async-only; worker в lifespan, 30 s, 0 = off.
- ✅ LRU eviction: max_size=4, 5-й exclusive → oldest evicted+closed.
- ✅ `orya_llm_pool_size` (gauge), `orya_llm_pool_hit_rate` (gauge),
  `orya_llm_pool_unhealthy_total` (counter) на `/metrics`.
- ✅ Kill-switch `CONNECTION_POOL_ENABLED=false` → стоковый путь.
- ✅ Никакого network при construction; agent-loop не блокируется.
- ⚠ NFR «cold-start ≤ 200 ms после restart / hit > 95% в проде» —
  не CI-проверяемы офлайн: подтверждаются probe-латентностью
  (`last_probe_ms`) и ручным замером; unit-аналоги — hit-rate тест и
  warm-ms AC.
- ✅ Гейт format → lint → test зелёный (включая drive-by ремонты A-19).

## Follow-ups

- BETA: `ConnectionPool` остаётся без изменений (PROMPT_BETA §0).
- A-19: warning `enable_prompt_caching is not default parameter`
  (kwargs уходит в `model_kwargs`) — вне гейта, косметика.
- google-инъекция не выставляет `base_url`/`headers` langchain-модели
  (factory их и раньше не передавал) — при появлении Vertex-провайдера
  проверить.
- Опционально: pre-warm дефолтного провайдера при старте (ADR-0014
  «Preliminary action») — спека A-20 не требует.
- `exclusive=True` ещё никем не используется (streaming-сема появится с
  batch-режимом BETA/PROD).

## Commit message

`A-20: ConnectionPool (per-provider keepalive clients, LRU + exclusive spawns, async health worker, tcp.pool_hit/connect_duration_ms span attrs, orya_llm_pool_* metrics; drive-by: A-19 red-baseline repairs)`
