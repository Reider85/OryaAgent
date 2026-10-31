# A-10 — Docker compose v2 (one-command deploy)

> Ticket: `analytics/PROMPT_ALPHA.md` §3.1 (A-10) | Estimate: 1 день | Status: executed

## Spec summary

«Docker compose (postgres, redis, chainlit, langfuse) | 1 день | one-command deploy» —
одна строка в таблице тикетов PROMPT_ALPHA.md:81 (детальной секции для A-10 нет:
BACKLOG6 §3 содержит только A-16/A-17; PROMPT §13 даёт лишь дерево файлов
`deploy/docker-compose.yml` + `deploy/Dockerfile`). Расшифровка обязательств —
в follow-up A-09 (`.opencode/plans/A-09-readme-deploy-guide.md:114`) и в README:129:
«Application containers (API/Chainlit), the `langfuse` service and the
`sampler-proxy` service … arrive with **A-10** (Docker compose v2)». Legacy A-10
«Chainlit: model-selector + settings-panel» из BACKLOG4/5 — устаревшая нумерация
v4/v5, к v6/v7 ALPHA отношения не имеет.

## Deviations & decisions

Scope согласован с пользователем до реализации (5 решений, все «recommended»):

1. **Компос в корне, Dockerfile в `deploy/`.** PROMPT §13 показывает оба файла в
   `deploy/`, но корневой `docker-compose.yml` — инвариант Makefile (`db-up`/
   `redis-up`/`stack-up`), `scripts/start.*`, quick-start и README. Перенос
   ломал бы всё это; оставлен корень + `deploy/Dockerfile` (дерево PROMPT
   соблюдено для Dockerfile, отклонение по compose-файлу).
2. **Langfuse v3 lite** (не v2, не полный стек OryaObservability): `langfuse` +
   `langfuse-worker` + `clickhouse` + `minio` поверх общих postgres/redis +
   one-shot `db-init` (идемпотентный `CREATE DATABASE langfuse` — initdb-хуки не
   перезапускаются на существующем volume) + `minio-init` не нужен (бакет
   создаётся `mkdir -p` в command minio). Версия `langfuse/langfuse:3` совпадает
   с OryaObservability и с `DOWNSTREAM_URL` ожиданиями A-15/A-17. Урезаны
   clickhouse2/vault/opa/prometheus/otel-collector — это не нужно для Langfuse.
3. **sampler-proxy в A-10** (README обещал), но поведение/audit/тесты — A-17:
   сервис собирается из соседнего `../OryaObservability` (`target: sampler-base`,
   без bind-mount рабочего дерева — образ самодостаточен), audit-пишущий
   ClickHouse-таблиц в стеке нет (лог-ошибки, никогда не raise — проверено по
   `policy_engine.record_audit`), Prometheus отсутствует (policy tick логирует
   ошибку и держит default rate — `sampler_proxy.py:540`).
4. **Профили + `COMPOSE_PROFILES`.** Без профилей ровно `postgres`/`redis`
   (инвариант Makefile/скриптов закрыт unit-тестом), `app` = api+chainlit,
   `observability` = langfuse-стек + sampler-proxy. One-command deploy:
   `COMPOSE_PROFILES=app,observability` в `.env` → `docker compose up -d --build`.
   Добавлены `make stack-up` / `make stack-down`.
5. **Верификация — полный smoke + коммит** (см. Verification).
6. **Контейнер `api` работает от root** (план предлагал non-root): bind-mount
   `./data/orya:/root/.orya` и `./data/memory:/data/memory` иначе упирается в
   права на Linux-хостах; для hardened-деплоя — в production checklist README.
   Workdir контейнера — `/workspace` (`ORYA_WORKSPACE`, default `.`), т.к.
   allowed-roots тулов — cwd + `~/.orya` + memory dir.
7. **`libpq5` в образе** — psycopg (транзитивно от langgraph-checkpoint-postgres)
   на linux не имеет ни `psycopg_binary`, ни системного libpq → первый же
   `orya db migrate` падал с `ImportError: no pq wrapper available`. ripgrep —
   обязательная runtime-зависимость grep/glob (AGENTS).
8. **Порты sampler'а параметризованы** (`SAMPLER_PROXY_PORT`,
   `SAMPLER_METRICS_PORT`) — на верификационной машине 9095 занят чужим стеком,
   как и 5432/6379/8000/3000; smoke гонялся с `POSTGRES_PORT=15432 …`
   (само по себе окружение-специфика, дефолты не менялись).
9. **langfuse-worker healthcheck — node, не python.** Скопированный из
   OryaObservability healthcheck (`python -c …`) в образе worker'а нерабочий:
   официальный `langfuse/langfuse-worker:3` — Node-only, `exec: "python":
   executable file not found`. Заменён на `node -e process.exit(0)` (liveness);
   краши и так выходят из контейнера под restart policy.
10. **Попутный фикс (не A-10-скоуп, нужен для зелёного gate):**
    `tests/integration/test_cache_redis.py::test_stats_counters_and_daily_redis_hash`
    ожидал shape статистики до A-07 (`{"hits","misses"}` без `evictions`).
    Тест пропускался без Redis; на машине с доступным Redis он впервые
    отработал в полном прогоне и упал. Ожидание выровнено с unit-тестами A-07.
11. **Фикс в соседнем репо (НЕ закоммичен, не мой репозиторий):**
    `../OryaObservability/scripts/sampler/requirements.txt` += `openpyxl>=3.1`.
    Импорт `scripts.sampler.sampler_proxy` на HEAD падал с
    `ModuleNotFoundError: No module named 'openpyxl'` —
    `agent_obs.compliance.gdpr_export` (новый модуль) импортируется безусловно
    через `agent_obs.guardrail.__init__`, а requirements.txt про него не знает.
    Иначе sampler-образ собирается, но не стартует. Требуется коммит upstream
    (см. Follow-ups); в стеке это же исправление применено через пересборку.

## Files

- `docker-compose.yml` (v2): anchor `x-orya-app-env` (container-hostname
  DATABASE_URL/REDIS_URL/ORYA_SAMPLER_PROXY_URL/ORYA_MEMORY_DIR/LANGFUSE_HOST),
  anchor `x-langfuse-env` (v3 env из OryaObservability, адаптированный под
  общий postgres/redis и dev-секреты по умолчанию); сервисы:
  `postgres`/`redis` (без профилей, без изменений), `api` (build `deploy/
  Dockerfile`, `orya db migrate && uvicorn`, env_file `.env` optional,
  healthcheck `/health`, volumes workspace/orya/memory), `chainlit` (тот же
  образ, `ORYA_API_URL=http://api:8000`, depends_on api healthy),
  `db-init`/`clickhouse`/`minio`/`langfuse`/`langfuse-worker`/`sampler-proxy`
  (профиль `observability`); volumes `postgres_data/clickhouse_data/
  clickhouse_logs/minio_data/sampler_shared`.
- `deploy/Dockerfile` (new): multi-stage на `ghcr.io/astral-sh/uv:python3.12-
  bookworm-slim` — слой deps (`uv sync --no-install-project`) → слой `app/` →
  runtime stage (+ `ripgrep`, `libpq5`), `PATH=.venv/bin`, CMD uvicorn.
- `.dockerignore` (new): контекст сжат до pyproject/uv.lock/README/app
  (в `.gitignore` снята строка `.dockerignore` — файл должен коммититься).
- `.gitignore`: `# Docker .dockerignore` → `data/` (bind-mount данные стека).
- `tests/unit/test_docker_compose.py` (new, 16 тестов): состав сервисов;
  «без профиля только postgres/redis»; профили app/observability; команда api
  (migrate+uvicorn); общий образ api/chainlit; container-hostname env;
  `ORYA_API_URL=http://api:8000`; healthchecks; sampler build/ downstream;
  langfuse v3 env; db-init идемпотентность; Dockerfile (ripgrep/uv/expose);
  `docker compose config -q` (guarded, default + app профили, skip без docker).
- `tests/unit/test_readme.py`: phase-progress тест `range(9)` → `range(11)`
  (`**A-{i:02d}**` — A-09/A-10 маркеры добавлены в README).
- `tests/integration/test_cache_redis.py`: `evictions: 0` в ожидании stats
  (решение №10).
- `README.md`: intro дополнен A-10; Deploy guide — 4-й режим (Full stack) +
  таблица всех 10 сервисов с профилями/портами/примечаниями + пример
  one-command deploy; `### Docker services (today)` — заголовок сохранён
  (контракт A-09), содержимое переписано; Production checklist — пункты про
  compose (секреты Langfuse, root-пользователь, общий redis); Langfuse секция —
  «Infra fact (A-10)» (стек поднимается) + явное «Export is still not wired»
  (A-15/A-16/A-17); Misc/infra env — `COMPOSE_PROFILES`, `ORYA_WORKSPACE`,
  `LANGFUSE_PORT`, `SAMPLER_PROXY_PORT`/`SAMPLER_METRICS_PORT`; Project
  Structure — `deploy/`, `docker-compose.yml`; Phase Progress — A-09, A-10.
- `.env.example`: блок «Docker compose stack (A-10)» + уточнённый комментарий
  Langfuse-блока (инфра есть, экспорт — A-15).
- `Makefile`: `stack-up` / `stack-down`, .PHONY.
- `AGENTS.md`: статус «ALPHA done through A-10», команда stack-up + инвариант
  профилей.
- `.opencode/plans/A-10-docker-compose.md` (this file).

## Verification

1. `docker compose config -q` и `docker compose --profile app --profile
   observability config -q` — оба OK.
2. `uv run pytest tests/unit/test_docker_compose.py tests/unit/test_readme.py`
   → 22 passed.
3. **Полный smoke** (с порт-оверрайдами из-за занятых на машине 5432/6379/8000/
   3000/9095): `docker compose --profile app --profile observability up -d
   --build` → все 10 сервисов: `postgres/redis/api/chainlit/clickhouse/minio/
   langfuse/langfuse-worker/sampler-proxy` **healthy**, `db-init` Exited (0).
   Эндпоинты: `:18000/health` 200, `:18001/` 200 (Chainlit HTML),
   `:13000/api/public/health` 200 (`{"version":"3.225.9"}`),
   `:4321/sampler/status` 200 (`current_rate 0.1, policy_reason default`),
   `:19095/metrics` 200; `/health/observability` 200; in-network проба из
   контейнера chainlit → `http://api:8000/health` 200 (M-24-ссылка жива).
4. Lifecycle-инвариант: `down` чистый → голый `docker compose up -d` пытается
   поднять **только** postgres+redis (провал на этой машине — занятый хостом
   `:6379`, пре-существующая коллизия окружения, не регрессия; README-раздел
   про порт-оверрайды покрывает) → `down` снова чистый.
5. `ruff format` → `ruff check` → `ruff format --check` — clean (236 файлов).
6. `uv run pytest` (полный): **927 passed, 21 skipped, 0 failed**
   (базовый A-09: 903/29/0; +16 compose-тестов, +8 ранее-скипавшихся
   интеграционных, −1 починенный stale-тест).

## DoD coverage

- ✅ One-command deploy: `COMPOSE_PROFILES=app,observability` + `docker
  compose up -d --build` (эквивалент `make stack-up`) поднимает postgres,
  redis, api, chainlit, langfuse (v3: web+worker+clickhouse+minio), sampler-proxy.
- ✅ PROMPT-строка сервисов соблюдена: postgres, redis, chainlit (+api — из
  README-обещания A-09), langfuse; sampler-proxy — как обещал README.
- ✅ Обратная совместимость: голый `docker compose up -d`, `make db-up`/
  `redis-up`, `scripts/start.*` не меняются (зафиксировано тестом).
- ✅ Приложение в контейнере: миграции при старте, `/health` 200, UI↔API по
  compose-сети, персистентные volume для `~/.orya` и L0-памяти.
- ✅ Langfuse v3 поднимается и здоров; first-boot `LANGFUSE_INIT_*`; экспорт
  явно помечен как невпущенный (A-15/16/17) — ничего не выдаётся за
  реализованное.
- ✅ Структура стека закреплена unit-тестами (16), README — 6 A-09-тестами
  (включая новые маркеры A-09/A-10).
- ✅ `make format` → `make lint` → `uv run pytest` pass (927/21/0).

## Follow-ups

- **Sibling-repo commit:** `../OryaObservability/scripts/sampler/requirements.txt`
  (+ `openpyxl>=3.1`) — лежит незакоммиченным в чужом репо (решение №11);
  там же незакоммичен чужой WIP — не трогал.
- A-11 (Alembic): заменить `orya db migrate` в команде `api`.
- A-15: секция Langfuse README из «planned» становится экспорт-фактом;
  `LANGFUSE_*` env — читаемые кодом.
- A-17: sampler-proxy — policy/prompt-injection-связка, audit DDL
  (`AGENT_OBS_SAMPLER_AUDIT_*`), Prometheus-зависимость (решение №3).
- A-16/A-15: healthcheck `/health/sampler-proxy` из контейнера api уже
  настроен (`ORYA_SAMPLER_PROXY_URL=http://sampler-proxy:4321`).
- Возможный ergonomics: авто-подбор портов при конфликте (как в
  `scripts/start.*`) — ручные `*_PORT`-оверрайды задокументированы.

## Commit message

`A-10: docker compose v2 - api/chainlit/langfuse/sampler-proxy stack with profiles (one-command deploy)`
