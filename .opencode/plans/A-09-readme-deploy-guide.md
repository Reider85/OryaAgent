# A-09 — README v2 (deploy guide)

> Ticket: `analytics/PROMPT_ALPHA.md` §3.1 (A-09) | Estimate: 4 часа | Status: executed

## Spec summary

«README v2 (deploy guide) | 4 часа | Docker, env-vars, Langfuse setup» —
одна строка в таблице тикетов PROMPT_ALPHA.md:80 (детальной секции для A-09
в PROMPT_ALPHA/BACKLOG6 нет; BACKLOG6 §3 содержит только A-16/A-17).
Legacy A-09 «Structured JSON-логи» из BACKLOG4/5 — устаревшая нумерация
v4/v5, к v6/v7 ALPHA отношения не имеет. Расшифровка: README приводится к
ALPHA-состоянию (A-00…A-08 уже в коде, док отставал на MVP) и получает
deploy-гайд (Docker), полный env-var референс и Langfuse-секцию.

## Deviations & decisions

1. **Scope согласован перед реализацией:** (а) Langfuse — forward-looking
   env-контракт с маркерами «planned A-15/A-16/A-17» (интеграции в коде
   нет, A-10/A-15 ещё не реализованы; контракт из ROADMAP6 §4.2.9/§4.2.10);
   (б) env-таблица — полная, из `Settings.model_fields` (52 AliasChoices +
   `ORYA_SAMPLER_PROXY_URL` через `Field(env=…)`), computed `current`/
   `overrides` исключены; (в) весь контент A-00…A-08 (operator-loop —
   follow-up A-08; Redis server-side maxmemory — follow-up A-07);
   (г) лёгкий unit-тест вместо ручной только-проверки.
2. **Дублирование «Configuration» убрано:** precedence + YAML-пример
   остались в Quick Start, полная таблица вынесена в отдельную секцию
   `## Environment variables` (pointer из Configuration).
3. **Двойные алиасы показаны recommended-правописанием** (`AUTH_ENABLED` и
   `ORYA_AUTH_ENABLED` в одной ячейке); тест требует документирования
   хотя бы одного алиаса на поле — `ORYA_TRUSTED_CLIENTS` (secondary
   алиас `RATE_LIMIT_TRUSTED_CLIENTS`) достаточен.
4. **Env-sync тест — per-field, не per-alias:** каждое env-распознаваемое
   поле Settings обязано встречаться в README; поле проходит, если
   встречён любой из его алиасов. Защита таблицы от протухания при A-12.
5. **Langfuse-плейсхолдеры и в `.env.example`:** закомментированный блок
   `LANGFUSE_*`/`AGENT_OBS_*` с пометкой «no code reads them yet» —
   контракт для операторов, не фича.
6. **Stale-правки в рамках v2:** mojibake-арrows (`?` → `—`) в Quick Start
   и Sessions API, bootstrap-заметки в Notes («bootstrap phase», «next
   phase will implement LLM provider integration» — неактуально с M-01),
   Phase Progress дополнен M-28 (пропущен прошлыми тикетами) и A-00…A-08,
   intro-список переведён на Phase: ALPHA.
7. **Ноль правок `app/`.** Только README/.env.example/AGENTS.md/тест/план.
8. **Попутный фикс test-isolation (не A-09-скоуп, но нужен для зелёного
   gate):** полный прогон детерминированно ронял 5 тестов
   `test_permission_audit.py` в паре `test_api_health.py` (воспроизводилось
   и на чистом дереве, до любых правок A-09): `test_health_observability_
   permission_disabled` мутировал `ORYA_PERMISSION_AUDIT_ENABLED=false` через
   raw `os.environ` без восстановления, а `isolated_permission_config`
   чистил env, но не `lru_cache` `get_settings()` — кэш отдавал
   `permission_audit_enabled=False`, span'ы не эмитились (`0 == 1`).
   Фикс обеих сторон по конвенции AGENTS: poisoner → `monkeypatch.setenv` +
   `clear_settings_cache()` в `finally`; victim → `clear_settings_cache()`
   до/после yield в autouse-фикстуре.

## Files

- `README.md` (rewrite to v2, 422 → ~710 lines):
  - шапка `## Phase: ALPHA` + intro A-00…A-09;
  - Quick Start: health-check note про auth, `### One-command start`
    (scripts/start.sh|ps1);
  - `## Deploy guide`: modes-таблица, Docker services (postgres:16 +
    redis:7, хост-порты, server-side `maxmemory 256mb allkeys-lru`),
    production checklist (auth/rate-limit/encryption/migrations/CORS/
    X-Request-ID), `### Langfuse setup (planned — A-15/A-16/A-17)`
    (works-today таблица + planned env contract);
  - `## Environment variables`: 12 групп, ~57 строк (LLM, observability,
    database, redis/cache, memory, sessions, permissions/agent-loop,
    auth/CORS, rate-limit, UI, misc/infra, provider keys pointer);
  - секции A-00…A-08: Authentication (operator-loop curl), Rate limiting
    (headers/backends), Health endpoints (таблица), LLM tracing & audit
    spans; `### Encryption at rest (A-05)` и `### Span cross-link (A-06)`
    внутри Session-log;
  - хвост: Documentation + PROMPT_ALPHA, Phase Progress A-00…A-08,
    Notes обновлены, Project Structure + auth/observability/api-middleware.
- `.env.example` — observability/Langfuse placeholder-блок (контракт A-15…A-17).
- `tests/unit/test_readme.py` (new) — 6 тестов: обязательные заголовки,
  operator-loop/deploy-маркеры, forward-looking Langfuse-секция, Phase
  Progress A-00…A-08, критичные env-имена, env-sync по `Settings.model_fields`.
- `tests/unit/test_permission_audit.py` / `tests/unit/test_api_health.py` —
  фикс test-isolation (решение №8): `clear_settings_cache()` в autouse-фикстуре
  A-03; raw `os.environ` → `monkeypatch.setenv` + `finally`-очистка кэша в A-04.
- `AGENTS.md` — строка статуса: ALPHA done through A-09 + указание на
  `tests/unit/test_readme.py`.
- `.opencode/plans/A-09-readme-deploy-guide.md` (this file).

## Verification

`uv run pytest tests/unit/test_readme.py -v` → 6 passed.
`uv run pytest tests/unit/test_api_health.py tests/unit/test_permission_audit.py -q`
→ 21 passed (детерминированно, до/после фикса — 16 passed + 5 failed).
Затем `make format` → `make lint` → `uv run pytest` (полный прогон):
**903 passed, 29 skipped, 0 failed**.

## DoD coverage

- ✅ README — deploy guide: три режима запуска, docker-compose-сервисы с
  портами/healthchecks/LRU-политикой, production checklist.
- ✅ Полный env-var референс из `Settings` (включая двойные алиасы и
  compose-only `POSTGRES_PORT`/`REDIS_PORT`/`API_PORT`); протухание
  защищено env-sync тестом.
- ✅ Langfuse setup: works-today (A-02/A-03/A-04/A-06) + planned env
  контракт (LANGFUSE_*/OTEL/sampler-proxy/AGENT_OBS_*) с явными маркерами
  A-15/A-16/A-17 — ничего не выдаётся за реализованное.
- ✅ ALPHA-контент A-00…A-08 задокументирован, включая operator-loop
  (follow-up A-08) и server-side Redis maxmemory (follow-up A-07).
- ✅ README-якоря закреплены unit-тестом (6 тестов, без инфры).
- ✅ Фикс test-isolation A-03/A-04 (предсуществующий баг, воспроизводился на
  чистом дереве): парный прогон `test_api_health` + `test_permission_audit` зелёный.
- ✅ `make format` → `make lint` → `uv run pytest` pass (903 passed / 29 skipped).

## Follow-ups

- A-10 (Docker compose v2): deploy-гайд заменит «app на хосте» на
  compose-стек (API/UI/langfuse/sampler-proxy), Langfuse-секция — факты.
- A-15/A-16/A-17: planned-таблица Langfuse становится «works today».
- A-12 (Settings v2): env-sync тест напомнит о правке таблицы README.

## Commit message

`A-09: README v2 - deploy guide, env-var reference, ALPHA sections (A-00..A-08)`
