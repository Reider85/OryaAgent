# A-05 — PostgresSaver v2 (encryption at rest)

> Ticket: `PROMPT_ALPHA.md` §3.1 (A-05) | Estimate: 1 день | Status: executed

## Spec summary

«PostgresSaver v2 (encryption at rest) | 1 день | pgcrypto для session-log» —
одна строка в таблице тикетов PROMPT_ALPHA.md:76 (детальной секции для A-05
в PROMPT_ALPHA/BACKLOG6 нет). Расшифровка: расширение PostgreSQL `pgcrypto`
для симметричного шифрования session-log payload-колонок на диске.

## Deviations & decisions

1. **Scope: только таблицы session-log, не checkpoints LangGraph.** SQL-таблицы
   LangGraph (`checkpoints`, `checkpoint_blobs`, …) создаёт и читает сама
   библиотека (`AsyncPostgresSaver.setup()`); прозрачное шифрование их колонок
   требовало бы подкласса с переписыванием SQL — хрупко при обновлении langgraph
   и ломает `session_log.discover_thread_ids`/projection. Для checkpoints
   encryption at rest = уровень диска/TDE (вне этого тикета). Шифруются
   `messages.content` (TEXT) и `messages.tool_calls` (JSONB). Аудит-таблица
   `tool_calls` (args/result) не имеет app-writer'а — hook отложен.
2. **Kill-switch default off** (как A-00/A-01): `ORYA_SESSION_LOG_ENCRYPTION_ENABLED=false`
   + `ORYA_SESSION_LOG_ENCRYPTION_KEY` (SecretStr, ≥16 chars). Enabled без
   ключа → fail-fast валидатор (зеркало `_require_secret_when_auth_enabled`).
3. **Формат хранения: armored ASCII.** `armor(pgp_sym_encrypt(...))` → тот же
   TEXT-тип колонки (типы не меняются → schema drift отсутствует); для JSONB —
   `to_jsonb(armor(...))` (ciphertext как JSON-строка). Tolerant decrypt по
   префиксу `-----BEGIN PGP MESSAGE-----` — legacy plaintext-строки читаются.
4. **Путь без флага byte-identical** — SQL и параметры `log_message`/
   `list_messages` при выключенном флаге остаются прежними (все существующие
   тесты зелёные).
5. **Неверный ключ → fail loud** (ошибка `pgp_sym_decrypt` при чтении), не
   silent-возврат ciphertext. Ротация ключа — отдельный будущий тикет.
6. **Кодек-агностичные интеграционные проверки** — raw-ciphertext assertions
   извлекают колонки в text в SQL (`#>>` для JSONB), чтобы не зависеть от
   поведения asyncpg jsonb-кодека (str vs decoded object).

## Files

- `app/db/migrations/0002_session_log_encryption.sql` (new) — `CREATE EXTENSION IF NOT EXISTS pgcrypto`.
- `app/db/schema.sql` — та же строка (drift-тест `test_db_schema.py`).
- `app/core/config.py` — `session_log_encryption_enabled` / `session_log_encryption_key` + field validator (≥16) + model validator (fail-fast).
- `app/db/session_log.py` — сейм A-05: `_encryption_enabled`, `_encryption_key`, `_decrypt_content_sql`, `_decrypt_tool_calls_sql`; ветвление в `log_message` (encrypt) и `list_messages` (decrypt).
- `.env.example` — два закомментированных var.
- `tests/unit/test_session_log_encryption.py` (new) — config validation, SQL-фрагменты, flag off/on поведение, defensive `_encryption_key`.
- `tests/unit/test_db_schema.py` — +`test_pgcrypto_declared_in_schema_and_migrations`.
- `tests/integration/test_session_log_encryption_postgres.py` (new) — extension exists, ciphertext raw check, decrypt round-trip, legacy plaintext, flag-off plaintext (сам-скип без `make db-up`).
- `.opencode/plans/A-05-session-log-encryption.md` (this file).

## Verification

`make format` → `make lint` → `uv run pytest` (+ опц. `make db-up && make db-migrate` для интеграционных).

## DoD coverage

- ✅ pgcrypto раскатан и в schema.sql, и в миграции 0002 (idempotent).
- ✅ enabled+key: raw-SQL показывает PGP-armor ciphertext в messages; `list_messages` возвращает оригинал (content + tool_calls).
- ✅ Legacy plaintext-строки читаются (tolerant decrypt по armor-префиксу).
- ✅ enabled без ключа → fail-fast; ключ ≥16 символов, нигде не логируется (SecretStr).
- ✅ Flag off (default) — SQL и поведение неизменны; все существующие тесты зелёные.
- ✅ `make format` → `make lint` → `uv run pytest` pass.

## Follow-ups

- Ротация ключа / re-encrypt scan (будущий тикет).
- Шифрование checkpoints LangGraph — уровень диска/TDE или отдельный обёрточный saver.
- JSONL-проеции (`sessions_dir/*.jsonl`) — file permissions 0600 (spec) / отдельный тикет.
- `tool_calls` аудит-таблица (args/result) — app-writer ещё не существует.
