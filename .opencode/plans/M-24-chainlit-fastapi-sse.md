# Plan: M-24 — Chainlit через FastAPI (SSE)

**Status:** executed
**Commit message:** `M-24: FastAPI SSE streaming (/messages, /resume, from_cache)` + `M-24: Chainlit via FastAPI SSE (httpx client, no direct graph access)` + `M-24: README + phase progress` + `M-24: executed ticket plan`
**Spec:** `analytics/BACKLOG5.md` §M-24 (фазовый источник) + `analytics/PROMPT_MVP.md` §3.5 M-15 («через FastAPI») + ARCHITECT5 §6.7; follow-ups из `.opencode/plans/M-20-fastapi-sessions.md` («SSE остаётся тикетом M-24») и `M-21-cache.md` («пробросить from_cache в SSE tool_end и tool_steps»).

**User decisions:**
1. SSE — `?stream=true` на существующих путях `/messages` и `/resume`; без флага JSON-контракт M-20 не меняется.
2. Settings-панель (model / permission_mode / allow_list) пробрасывается в теле запроса от Chainlit; граф и политику собирает сервер.
3. Полный объём: from_cache в SSE/tool_steps **и** sidebar/история через `GET /sessions*`.

## Context

- Chainlit (`app/ui/chainlit_app.py`) драйвил graph напрямую (`build_session_graph` + `stream_graph_events` + `graph.aget_state`), FastAPI отдавал только JSON-агрегат → streaming-логика существовала в двух местах ровно так, как предупреждал ARCHITECT5 §1.
- Панель settings (M-17) собирала graph локально: `policy_from_settings()` и model-override жили в UI-процессе и после переезда графа в сервер обязаны были переехать в API.
- Общий runtime уже был в `app/core/agent.py` (M-20) — M-24 подключает к нему SSE-транспорт и отнимает у UI последние прямые вызовы graph/БД.

## Deviations from spec (deliberate + исправленные баги)

| Spec says | Done | Why |
|---|---|---|
| BACKLOG5 M-20: `/messages` всегда отдаёт SSE | SSE только при `?stream=true`, без флага — JSON (решение пользователя) | Контракт M-20 и его тесты не ломаются; UI шлёт флаг |
| BACKLOG5 M-20: `/messages` stream, `/resume` stream, cancel, `/events`, `/tools` | только `messages`+`resume` со stream; cancel/`/events` — нет | вне решённого scope (следует прежнему решению по M-20) |
| M-17: `policy_from_settings()` возвращает `PermissionConfig` | удалён → `app/core/permissions.py::build_policy()` возвращает `PermissionPolicy` | **Баг (воспроизведён):** `AttributeError: 'PermissionConfig' object has no attribute 'check'` — любая UI-сессия падала на первом tool-call; mode-override терялся |
| M-17: `build_session_graph(model="alias")` передавал строку в `build_graph` | строка резолвится через `get_llm(model=alias)`, инстанс проходит как есть | **Баг (воспроизведён):** у строки нет `.ainvoke` → ход падал |
| M-17: `settings_path()` = `get_settings().home_dir / "settings.json"` | новое поле `Settings.ui_settings_path` (+`ORYA_UI_SETTINGS_PATH`) | **Баг (воспроизведён):** `AttributeError: 'Settings' object has no attribute 'home_dir'` — `load_settings()` падал в `on_chat_start` |
| BACKLOG5 M-17: sidebar из JSONL/БД напрямую | `GET /sessions` (список) + `GET /sessions/{id}` (реплей истории) | решение пользователя: UI перестаёт лезть в core |
| UI без БД создавал thread_id локально | сохранено: stream-режим API — soft-fail логов (`degraded: true`), `POST /sessions`→503 ⇒ локальный uuid в UI | иначе переезд на API ломал работоспособность чата без Postgres (прежний UX) |
| — | `ORYA_API_URL` (default `http://127.0.0.1:8000`) + `httpx` → прямая зависимость pyproject (был транзитивным) | UI живёт в отдельном процессе (`make ui`, порт 8001) |

## Design

### 1. `app/core/agent.py`
- `_from_cache(output)` → в `tool_end` поле `"from_cache"` (читает `ToolMessage.metadata`); `tool_steps` JSON/SSE несут его же (M-21 follow-up).
- Новые `stream_turn()` / `stream_resume()` → общий `_aggregate_turn()`: промежуточные события + терминальный `done{status, reply, tool_steps, pending}`; **`run_turn`/`run_resume` переписаны как тонкие обёртки** (`_final_done`) — одна агрегация на два транспорта.
- `build_session_graph(model=...)`: `None` → `get_llm()`, `str` → `get_llm(model=alias)`, иначе инстанс как есть.

### 2. `app/core/permissions.py`
- `build_policy(mode=None, *, allow_patterns=(), config_path=None) -> PermissionPolicy` — mode (fallback strict с warning) + allow-list → extra `Rule("*", allow)`.
- `PermissionPolicy.session_allowed_tools()` — публичный доступ к M-13 session-allowlist для переноса при смене настроек.

### 3. `app/api/sessions.py`
- `stream: bool = Query(False)` на `/messages` и `/resume` → `StreamingResponse(media_type="text/event-stream", headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"})`.
- `MessageCreate`/`ResumeRequest` наследуют `TurnSettings{model, permission_mode, allow_list}`.
- `_sse_turn()`: форвард кадров, `interrupt` при paused-ходе, финальный `done` (+assistant-лог), на исключении после старта — `error` + `done{status:"error"}`.
- `_policy_for(sid, mode, allow_list)`: кэш `{sid: ((mode, tuple(allow)), policy)}`; смена ключа пересобирает политику с переносом session-allowlist.
- Stream-режим: `ensure_session`/`log_message` через `_soft_db()` (варн + `degraded`), JSON остался strict 503.

### 4. `app/ui/chainlit_app.py` (переписан)
- `iter_sse(lines)` — SSE-парсер (event/data, многострочный data, комментарии, без колона — message, не-JSON — текст).
- `on_chat_start`: `POST /sessions` → `thread_id`; `ConnectError` ⇒ fail-closed сообщение («make dev»), 503 ⇒ локальный uuid + degraded-сообщение; `init_cache()` убран (кэш живёт в API-процессе).
- `on_message`: `client.stream("POST", .../messages?stream=true", json={content, **overrides})` → рендер token/tool_start/tool_end (cache-hit → имя шага `"read (cached)"`) → по `interrupted`-`done` → `ask_permission` → `POST .../resume?stream=true` → цикл; fallback `done.reply` для не-стримящих моделей; `ApiError`/`httpx.HTTPError` → сообщения.
- sidebar → `GET /sessions?page=1&size=10`; new/switch → `POST`/`GET /sessions`; история → реплей `messages` (user/assistant).
- `on_settings_update` → только `save_settings` (граф не пересобираем). Убраны win32 Selector-policy, `_safe_log`/`_safe_ensure_session`, прямые импорты graph-сема.

### 5. Конфиг/депсы
`Settings.api_url` (`ORYA_API_URL`), `Settings.ui_settings_path` (`ORYA_UI_SETTINGS_PATH`, валидатор `~`-расширения), `httpx>=0.27.0` в pyproject (+`uv sync`), `.env.example`.

### 6. Тесты (50 новых; 501 → 551 passed)
- `tests/unit/test_agent_runtime.py` (new, 33) — маппинг событий/state-пробы/wiring перенесены из `test_chainlit_app.py`; + `stream_turn`/`stream_resume`/`done`-контракт, from_cache в событиях и `tool_steps`, резолв model-алиаса.
- `tests/unit/test_chainlit_app.py` (переписан, 31) — SSE-парсер (6), рендер (8, incl. cache-marker и error/missing-done), handlers поверх `httpx.MockTransport` (создание сессии/503-fallback/API-down, стрим, interrupt→resume-цикл, hint, ошибки), settings/sidebar/history.
- `tests/unit/test_api_sessions.py` (+10) — SSE-кадры и заголовки, interrupt-кадр, soft-fail при упавшей БД, from_cache (SSE+JSON), overrides → `build_session_graph`, кэш политик с переносом allowlist, resume-stream, 409.
- `tests/e2e/test_sse_roundtrip.py` (new, 5) — реальный HTTP: стрим с tool-шагами, interrupt → `/resume` с исполнением тула, 409, `error`-кадр при падении модели, JSON-регрессия (shared `MemorySaver`, scripted model, без LLM/БД).
- `tests/e2e/test_chainlit_smoke.py`, `test_ask_prompt.py` — импорты `ui.*` → `app.core.agent.*`.
- `tests/unit/test_permissions.py` (+7) — `build_policy` (базовые правила, allow-list, fallback режима, невалидный mode, usable-PolicyLike-регрессия на старый баг, session-allowlist roundtrip).
- `tests/unit/test_ui_settings.py` — `TestPolicyFromSettings` удалён (переехал в `test_permissions`), + `TestSettingsPath` (регрессия на `home_dir`).
- `tests/unit/test_config.py` — дефолты `api_url`, `ui_settings_path`.

## Result

- `app/core/agent.py` — `TurnStreamEvent`, `_from_cache`, `_aggregate_turn`/`stream_turn`/`stream_resume`/`_final_done`, `run_turn`/`run_resume`-обёртки, резолв model-алиаса.
- `app/core/permissions.py` — `build_policy()`, `session_allowed_tools()`.
- `app/api/sessions.py` — SSE-режим двух эндпоинтов (`_sse`, `_sse_turn`, `_soft_db`), `TurnSettings`-overrides, policy-кэш с ключом настроек.
- `app/ui/chainlit_app.py` — HTTP/SSE-клиент (~470 строк): `iter_sse`, `_render_events`, `_stream`, `_create_session`, `_list_sessions`, `_load_history`, 5 хендлеров.
- `app/ui/settings.py` — `policy_from_settings` удалён, `settings_path()` → `ui_settings_path` (баг-фикс).
- `app/core/config.py`, `pyproject.toml` (+`httpx`), `.env.example`, `app/ui/__init__.py`.
- `README.md` — quick-start шаг `make dev` + `make ui`, раздел «SSE streaming (M-24)» (таблица кадров, curl `-N`), обновлены Sessions API/Phase Progress/intro; `AGENTS.md` — факт про UI как httpx-клиента.
- `.opencode/plans/M-24-chainlit-fastapi-sse.md` — этот файл.

## Verified

- `uv run ruff format .` → `uv run ruff check .` → `uv run ruff format --check .` — чисто (8 файлов переформатировано).
- `uv run pytest -q` — **551 passed, 20 skipped** (базлайн до правок: 501 passed, 20 skipped; скипы прежние: `rg` на PATH + infra/live-ключи).
- Boot-smoke: `chainlit run app/ui/chainlit_app.py --headless --port 8017` → «Your app is available», HTTP 200, stderr пуст (процесс остановлен, порт освобождён).
- Три latent-бага M-17 воспроизведены запуском до фикса и закрыты регресс-тестами (`build_policy` usable-PolicyLike, `settings_path`, резолв алиаса модели).

## Follow-up

- **Cancel** `POST /sessions/{id}/cancel` + `GET /sessions/{id}/events` (BACKLOG5) — при появлении первого клиента.
- **M-17 тема/throttle** — панель шлёт overrides каждый запрос; при росте payload думать о session-level settings (`PATCH /sessions/{id}`).
- **ALPHA A-11**: `/sessions` и stream-эндпоинты открыты (dev) — JWT/API-key появится в ALPHA-auth.
- **M-18**: BACKLOG5-зависимость M-24 закрыта — smoke-расширение не потребовалось (roundtrip покрыт `tests/e2e/test_sse_roundtrip.py`).
