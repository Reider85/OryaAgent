# A-11 — Alembic migrations (schema evolution)

> Ticket: `analytics/PROMPT_ALPHA.md` §3.1 (A-11) | Estimate: 4 часа | Status: executed

## Spec summary

«Alembic migrations | 4 часа | schema evolution» — одна строка в таблице
тикетов PROMPT_ALPHA.md:82 (детальной секции для A-11 нет — так же, как
для A-09; BACKLOG6 §3 содержит только A-16/A-17). Контекст: ROADMAP5 §18.2
требует для rollback фаз `alembic downgrade base` / `alembic downgrade
<phase_revision>`; M-03 осознанно выбрал plain `.sql`-раннер («asyncpg-only,
no SQLAlchemy»), A-11 вводит Alembic как оркестратор поверх тех же файлов.

## Deviations & decisions

1. **Вариант A (согласован): Alembic поверх существующих `.sql`.**
   `app/db/migrations/NNNN_name.sql` остаются источником истины upgrade-DDL
   (дрift-тесты `test_db_schema.py` живут без изменений); revision-обёртки в
   `alembic/versions/NNNN_name.py` делают `op.execute(файл)`, downgrade —
   инлайн-DDL (`.down.sql` не заводим: `0001_init.down.sql` ломал бы glob
   `load_migrations()`). SQLAlchemy появляется только как зависимость
   Alembic; приложение его не импортирует (runtime остаётся asyncpg-only).
2. **Инвариант расширен с двух до трёх правок:** схема меняется правкой
   `schema.sql` + нового `migrations/NNNN_name.sql` + `alembic/versions/NNNN_name.py`;
   1:1 защищено `tests/unit/test_alembic.py`.
3. **Единый bookkeeping:** `alembic_version` (не двойной учёт со старой
   `schema_migrations` — таблица дропается после первого Alembic-upgrade'а).
   Revision id = file stem (`0002_session_log_encryption` = MVP-граница).
4. **`apply_migrations()` теряет параметр `pool`:** ядро синхронное
   (Alembic programmatic API + sync psycopg), async-обёртки крутятся через
   `asyncio.to_thread` (никаких event-loop/Proactor-проблем на win32).
   Обновлены все call sites: `orya db migrate`, интеграционные тесты.
   CLI расширен: `orya db migrate|downgrade <rev>|current` (+ `make
   db-downgrade REV=…`, `make db-current`).
5. **Legacy-БД:** `.sql`-файлы идемпотентны → `upgrade head` на базе до A-11
   = no-op DDL + штамп `alembic_version` + дроп `schema_migrations`
   (проверено смоуком на реальной БД).
6. **CWD-независимость:** `alembic_config()` пиннит `script_location` в
   абсолютный путь (ini хранит относительный для bare-CLI из корня).
7. **env.py не трогает root-logger**, если приложение/тесты уже сконфигурировали
   логгинг (иначе ini сбрасывает уровень на WARN и съедает CLI-сводку).
8. **URL-нормализация:** `sync_url()` переводит `postgres://` /
   `postgresql://` / `postgresql+asyncpg://` → `postgresql+psycopg://`
   (дефолт `settings.database_url` работает как есть).
9. **Тест roundtrip — в изолированной схеме** (`options=-c search_path=…` на
   URL): `downgrade base` + re-upgrade в схеме `alembic_rt_a11`, чтобы suite
   не.DropTable'ил реальные dev-данные; pgcrypto (DB-wide) восстанавливается
   в finally полной перестановкой расширения.
10. **Deploy:** `deploy/Dockerfile` теперь COPY `alembic.ini` + `alembic/`
    (api-контейнер запускает `orya db migrate` на старте).

## Drive-by фикс A-05 (не A-11-скоуп, нужен для зелёного gate с infra)

PG-интеграционные тесты A-05 исторически всегда скипались (без инфры) и
оказались сломанными против канонического `postgres:16` (pgcrypto 1.3):

1. `pgp_sym_encrypt(convert_to($3,'UTF8'), …)` — в pgcrypto overload
   `(text, text)`, bytea-аргумент → `UndefinedFunctionError`.
2. `convert_from(pgp_sym_decrypt(…), 'UTF8')` — `pgp_sym_decrypt` уже
   возвращает text → `UndefinedFunctionError`.
3. Главное: `pgp_sym_decrypt` в этом билде **не принимает ASCII-armored
   вход** («Wrong key or corrupt data»; binary-roundtrip того же ciphertext
   работает; `unarmor` в pgcrypto 1.3 postgres:16 отсутствует) — формат
   «armored» невоспроизводим на канонической инфраструктуре.

Фикс: хранение `orya1:` + `encode(ciphertext,'base64')` (детекция
зашифрованных строк по префиксу сохраняет tolerant-decrypt), read-side
`pgp_sym_decrypt(decode(substring(…), 'base64'), key)`. Затронуты
`app/db/session_log.py` (write + два decrypt-фрагмента), unit- и
интеграционные тесты A-05, README-секция «Encryption at rest».

## Drive-by фикс #2: cross-loop singletons (не A-11-скоуп, нужен для полного gate с infra)

Полный прогон с поднятым PG вскрыл предсуществующую проблему: asyncpg-пул
(`app/db/__init__.py`) и psycopg-чекпоинтер (`app/db/checkpoints.py`) —
loop-bound синглтоны; между тестовыми прогонами с разными event loop'ами
(await из e2e → интеграционные) `await singleton.close()` с чужого loop
падал с «attached to a different loop» (FAIL в
`test_api_sessions_roundtrip` + ERROR at teardown в `test_db_postgres`).
Фикс: синглтоны отслеживают создавший loop; при смене loop'а singleton
**отбрасывается без close** (close с чужого loop небезопасен; старый пул
умирает вместе со своим loop'ом), `get_checkpointer()` перевызывается, а
не переиспользует чужой. Юнит-тест `test_pool_recreated_when_loop_changes`
обновлён под новый контракт (`closed is False`).

## Files

- `alembic.ini`, `alembic/env.py`, `alembic/script.py.mako`,
  `alembic/versions/0001_init.py`, `alembic/versions/0002_session_log_encryption.py`
  (new).
- `app/db/migrate.py` (переписан: sync_url/alembic_config/revisions_between/
  upgrade/downgrade/current + async-обёртки + argparse CLI).
- `app/db/__init__.py` (docstring), `app/main.py` (`orya db migrate|downgrade|current`).
- Тесты: `tests/unit/test_alembic.py` (new, 10 тестов), `test_db_pool.py`
  (fake-pool-миграции удалены), `test_cli_logging.py` (zero-arg fakes),
  `test_readme.py` (Phase Progress A-00…A-11), `test_db_postgres.py`
  (сигнатура + изолированный roundtrip).
- Интеграционные: 5 файлов `apply_migrations(pool)` → `apply_migrations()`.
- A-05 drive-by: `app/db/session_log.py`, `tests/unit/test_session_log_encryption.py`,
  `tests/integration/test_session_log_encryption_postgres.py`, README.
- `Makefile` (db-downgrade/db-current), `deploy/Dockerfile`, `.dockerignore`,
  `README.md` (Database/Migrations, checklist, Phase Progress), `AGENTS.md`,
  `pyproject.toml`/`uv.lock` (alembic, sqlalchemy, psycopg[binary]).
- `.opencode/plans/A-11-alembic-migrations.md` (this file).

## Verification

- `uv run pytest tests/unit/test_alembic.py tests/unit/test_db_pool.py
  tests/unit/test_cli_logging.py tests/unit/test_db_schema.py
  tests/unit/test_readme.py tests/unit/test_session_log_encryption.py -q` → passed.
- С `DATABASE_URL` на `make db-up` (порт 5435 — на хосте 5432 занят нативным
  postgres.exe): `test_db_postgres.py` (6/6, включая downgrade/reupgrade
  roundtrip в изолированной схеме) + api/graph/session_log/session_log_encryption
  интеграционные → 12/12.
- CLI-смоуки: `python -m app.db.migrate current|migrate|downgrade base|migrate`;
  симуляция legacy-БД (дроп `alembic_version` + ручная `schema_migrations`) —
  upgrade штампует и дропает legacy-таблицу; `downgrade base` оставляет
  только checkpoints*-таблицы.
- Гейт: `make format` → `make lint` → `uv run pytest`:
  **с инфрой (DATABASE_URL на `make db-up`): 946 passed, 10 skipped, 0 failed**;
  **стандартный прогон (без инфры): 934 passed, 22 skipped, 0 failed**.

## DoD

- ✅ `alembic upgrade head` / `alembic downgrade base` работают (ROADMAP5 §18.2
  rollback-история; downgrade 0001 удаляет все 4 таблицы, 0002 — pgcrypto).
- ✅ Schema evolution: новая правка схемы = `.sql` + revision-обёртка
  (1:1-тест), bookkeeping только `alembic_version`.
- ✅ Legacy-путь прозрачен (идемпотентный no-op + штамп + дроп
  `schema_migrations`), проверено на реальной БД.
- ✅ Runtime остаётся asyncpg-only; SQLAlchemy/Alembic изолированы в
  `app/db/migrate.py` + `alembic/`.
- ✅ `orya db migrate` без изменений для операторов/контейнера (A-10), плюс
  `downgrade`/`current`; README/AGENTS/Makefile обновлены.
- ✅ Полный прогон тестов зелёный (unit + e2e + smoke + интеграционные при
  поднятом PG).

## Follow-ups

- A-12 (Settings v2): новые env-поля не требуют правок миграций, но
  env-sync тест README напомнит о таблице.
- BETA/PROD: новые фазовые миграции добавляются парой `.sql` + revision;
  фазовая граница ревизии фиксируется в README-rollback-секции.
- A-05: возможный follow-up — документировать/протестировать миграцию
  формата armored → `orya1:`+base64 (все существующие инсталляции с
  включённым шифрованием фактически не работали на канонической инфраструктуре,
  так что старых armored-данных быть не должно).
- Пул/чекпоинтер: при жизни с несколькими loop'ами (prod — один uvicorn loop,
  не задет) foreign-loop пул отбрасывается без close — со временем можно
  добавить explicit dispose-хук, если появится второй долгоживущий loop.

## Commit message

`A-11: Alembic migrations - upgrade/downgrade over .sql files, alembic_version bookkeeping (+ A-05 drive-by: base64 crypto format)`
