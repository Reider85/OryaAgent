# Plan: M-17 — Chainlit UI: sidebar сессий, settings

**Status:** executed
**Commit message:** `M-17: sidebar сессий, settings panel, session switching` + `M-17: executed ticket plan`
**User decisions:** план утверждён (PROMPT_MVP §3.5 + BACKLOG4; slash-команды отложены в M-26/M-27, JSONL+fallback, settings.json persistence).

## Deviations from spec (deliberate, documented)

| Spec says | Done | Why |
|---|---|---|
| PROMPT_MVP: slash-commands `/learn`, `/memory/*` | deferred в M-26/M-27 | MDStore (M-25), `/learn` (M-26), `/memory/*` (M-27) не реализованы — отдельные тикеты; пользователь выбрал defer |
| PROMPT_MVP: список сессий из таблицы `sessions` | `~/.orya/sessions/*.jsonl` по mtime + enrich title из `sessions` table | degraded-mode (MemorySaver fallback) — JSONL работает без Postgres; обогащение title при доступности БД |
| BACKLOG4: mode `ask`/`auto` | `strict`/`permissive` | M-13-фактические режимы ADR-004 (`ask`/`auto` устарели) |
| BACKLOG4: dropdown из 2 моделей | алиасы из `models.yaml` с `supports_tools=true` (~41) | YAML-реестр M-01 — не хардкодить модели; `load_models()` фильтр по `supports_tools` |
| PROMPT_MVP: theme в settings | defer | Chainlit theme — статичный `config.tomm`, не runtime-changeable; UI theme не поддерживается в MVP |
| BACKLOG4: allow_list textarea → session allowlist | `allow_list` → extra allow rules (`Rule("*", pattern, allow)`) | session allowlist (`_session_allowed`) не персистентен; allow_list → правила в PermissionConfig |

Известные ограничения (приняты для MVP): session allowlist теряется при смене settings; degraded-mode сессии после рестарта процесса пусты; slash-команды вне тикета.

## Result

- `app/ui/settings.py` (new) — `UISettings` (model, permission_mode, allow_list), `load_settings`/`save_settings` (JSON, `~/.orya/settings.json`), `model_choices` (фильтр `supports_tools=true`), `policy_from_settings` (mode + allow_list → extra allow rules).
- `app/ui/sessions.py` (new) — `list_sessions` (список `*.jsonl` по mtime, limit=10), `enrich_titles_from_db` (best-effort title из `sessions` table), `SessionInfo` dataclass.
- `app/ui/chainlit_app.py` (update) — `build_session_graph` с model/policy overrides, `@cl.on_chat_start` с sidebar (New session + session list actions) и settings-panel (model-select, mode-select, allow_list-textarea), `@cl.on_settings_update` → rebuild graph + save JSON, `switch_thread` helper, история восстановления из `graph.aget_state` → replay в чат.
- `tests/unit/test_ui_settings.py` (new, 15 tests) — roundtrip, defaults, corrupt JSON, model_choices фильтр, policy_from_settings.
- `tests/unit/test_ui_sessions.py` (new, 10 tests) — mtime-сортировка, limit=10, title reading, missing dir → [].
- `tests/unit/test_chainlit_app.py` (+8) — `build_session_graph` overrides, `switch_thread` на фейках.
- `tests/e2e/test_sidebar.py` (new, 3 tests) — 2 сессии (JSONL в tmp) → switch → graph пересобран, история восстановлена; без Chainlit-websocket.
- `.opencode/plans/M-17-sidebar-settings.md` — этот файл.

## Verified

- `uv run ruff format .` + `uv run ruff check .` + `uv run ruff format --check .` — чисто.
- Полный `uv run pytest -q` — **370 passed, 18 skipped** (скипы: Postgres-инфа, live-provider ключи, `rg`; 33 новых теста M-17 зелёные).

## Follow-up

- **M-26/M-27:** slash-commands `/learn`, `/memory/stats`, `/memory/compact` (MDStore, endpoints).
- **M-20/M-24:** FastAPI `/sessions` endpoints + SSE-маршрутизация (текущий direct graph → SSE).
- **Session allowlist персистенция:** сохранять allow_list в settings и восстанавливать в policy при rebuild.
- **Theme:** runtime theme switching — возможно, через Chainlit custom theme API в будущем.
- **Memory-режим:** улучшить handling degraded-mode при session switching (сейчас показывает пустую историю для старых сессий).