# A-12 — Settings v2 (env-overrides for prod)

> Ticket: `analytics/PROMPT_ALPHA.md` §3.1 (A-12) | Estimate: 4 часа | Status: executed

## Spec summary

«Settings v2 (env-overrides for prod) | 4 часа | 12-factor app» — одна строка
в таблице тикетов PROMPT_ALPHA.md:83 (детальной секции для A-12 нет — так же,
как для A-09/A-11; BACKLOG4/5 A-12 «DoD integration test» — старая нумерация v5,
не релевантна). Контекст: после A-00…A-11 конфиг-слой уже покрывает
env/.env/YAML-приоритет, SecretStr и fail-fast на слабые ключи; оставшийся
prod-разрыв — ничего не мешает загрузить прод с dev-дефолтами (auth off,
rate-limit off, CORS `*`), и оператор не может проверить, что env-overrides
реально применились.

## Deviations & decisions

Скоуп согласован с пользователем до старта: prod-guard + `orya config` CLI +
мини-sweep консистентности; критичные (fail-fast) — auth + rate-limit + CORS,
остальное — warnings.

1. **`ORYA_ENV=dev|prod` (field `app_env`).** `prod` через
   `model_validator(mode="after")` агрегирует все нарушения в одну ошибку:
   `AUTH_ENABLED=true`, `ORYA_RATE_LIMIT_ENABLED=true`, `CORS_ORIGINS` без
   wildcard `*`. Требование секрета при auth остаётся на валидаторе A-00.
   `dev` (дефолт) — kill-switch поведение прежнее, ни один существующий
   тест/деплой не меняется.
2. **Warnings вместо блокировки** — `Settings.prod_warnings()`: шифрование
   session-log off (A-05), localhost в `DATABASE_URL`/`REDIS_URL` (single-host
   деплой легитимен — предупреждаем, не роняем).
3. **`orya config show|check`** (`app/core/config_cli.py` + argparse-ветка в
   `app/main.py`, как `orya db` → `app/db/migrate.py`): `show` печатает
   эффективные настройки с редакцией `SecretStr` и best-effort источником
   каждого поля (`env` / `.env` / `config.yaml` / `default` — в порядке
   приоритета); `check` — exit 1 на невалидную конфигурацию, иначе 0 +
   prod-warnings. Оба сабкоманддиспатча идут **до** `configure_cli_logging()`,
   чтобы guard-violation печаталась читаемым сообщением, а не traceback'ом
   (любая другая команда тоже ловит ValidationError вокруг logging-setup).
4. **Sweep:** `LOG_LEVEL` — allow-list + uppercase (допущение потребителей
   `logging_setup`/`main`/`chainlit_app`, которые и так делали `.upper()`);
   `sampler_proxy_url` переведён с `Field(env=[...])` на `validation_alias=
   AliasChoices(...)` как у всех остальных полей (env-sync тест README
   читает оба стиля, поведение идентично).
5. **`config show` источник `config.yaml` — best-effort** (наличие mapped
   yaml-ключа, когда env/.env не заданы); точный пересчёт merge-логики
   не дублируется.

## Files

- `app/core/config.py`: `app_env`, `_require_prod_safe_settings`,
  `prod_warnings()`, `_normalize_log_level`, `_url_host`, алиас
  `sampler_proxy_url`.
- `app/core/config_cli.py` (new): `config_show_lines`, `run_config_show`,
  `run_config_check`.
- `app/main.py`: `orya config show|check` + ValidationError-guard.
- Тесты: `tests/unit/test_config.py` (+11 A-12), `tests/unit/test_config_cli.py`
  (new, 8), `tests/unit/test_readme.py` (`range(13)`, `ORYA_ENV` в
  CRITICAL_ENV_VARS).
- Документация: README (Phase: ALPHA, Production checklist, env-intro,
  Misc/infra-таблица, Phase Progress A-12), `.env.example`, `AGENTS.md`.
- `.opencode/plans/A-12-settings-v2.md` (this file).

## Verification

- `uv run pytest tests/unit/test_config.py tests/unit/test_config_cli.py
  tests/unit/test_readme.py tests/unit/test_api_health.py
  tests/unit/test_cli_logging.py -q` → 63 passed.
- CLI-смоуки: `orya config show` (источники/default, редакция), `orya config
  check` в dev (exit 0, «guardrails OFF»), с prod-env без auth (exit 1, FAIL),
  с полным prod-набором (exit 0, warnings про encryption/localhost).
- Гейт: `make format` → `make lint` → `uv run pytest`.

## DoD

- ✅ `ORYA_ENV=prod` с dev-дефолтами не загружает приложение (единая
  агрегированная ошибка: auth + rate-limit + CORS).
- ✅ Полный prod-набор (auth+secret, rate-limit, узкий CORS) загружается;
  wildcard `CORS_ORIGINS=*` в prod — ошибка.
- ✅ `prod_warnings()` (encryption off, localhost URLs) — не фатальны,
  показываются `orya config check`.
- ✅ `orya config show` редактирует секреты и показывает источник каждого
  поля — 12-factor проверка env-overrides.
- ✅ `LOG_LEVEL` case-insensitive + allow-list; все прежние потребители
  работают.
- ✅ README/env/AGENTS синхронизированы (env-sync тест + Phase Progress
  A-12); dev-поведение и compose не изменились.

## Follow-ups

- A-13 (CostAwareRouter): budget/env-поля добавлять тем же AliasChoices-
  паттерном; env-sync тест напомнит про README-таблицу.
- BETA/PROD: при появится второй deployment-profile (staging) — расширить
  Literal + таблицу guardrails; compose-стек можно перевести на
  `ORYA_ENV=prod` в образе, когда появятся реальные prod-секреты.

## Commit message

`A-12: Settings v2 - ORYA_ENV prod-guard (fail-fast checklist) + orya config show/check CLI`
