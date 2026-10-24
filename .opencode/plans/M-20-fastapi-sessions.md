# Plan: M-20 — FastAPI /sessions endpoints

**Status:** executed
**Commit message:** `M-20: FastAPI /sessions endpoints (CRUD, full-turn messages, resume; shared agent runtime)` + `M-20: README sessions API + phase progress` + `M-20: executed ticket plan`
**User decisions:** scope = PROMPT_MVP + resume + GET /sessions со списком; JSON-ответ (не SSE); план утверждён без изменений, deviations — таблица ниже.
**Spec:** `analytics/PROMPT_MVP.md` §3.6 M-20 (фазовый источник) + BACKLOG5 M-20 (resume/пагинация — расширение по решению пользователя)

**User decisions:**
1. Scope = PROMPT_MVP (CRUD + messages) **+ `POST /sessions/{id}/resume`** (позволяет non-UI клиентам разрулить M-13 interrupt); SSE/cancel/`/metrics`/`/tools` — нет (SSE-стриминг остаётся тикетом M-24).
2. `POST /sessions/{id}/messages` — **JSON, полный ход** (не SSE): дожидаемся конца, отдаём `{status, reply, tool_steps, pending_interrupt}`.
3. **`GET /sessions` со списком + пагинацией** (`?page=1&size=20`) — включён.

## Context

- `app/main.py` — FastAPI-приложение уже есть (lifespan + `/health` + `/llm/*` router); sessions-router подключается туда же.
- Таблицы `sessions` / `messages` (M-03) и `log_message` / `ensure_session` (M-14) готовы; `sessions.status IN ('active','closed','aborted')` — soft-delete = `status='closed'` (schema-изменений **нет**).
- Graph-сборка (`build_session_graph`, `resolve_checkpointer`, нормализация событий, `get_pending_interrupt`) сейчас живёт в `app/ui/chainlit_app.py` / `app/ui/interrupt.py`, которые импортируют `chainlit` — API не может их импортировать. Forbidden pattern PROMPT_MVP §9: «не дублировать logic между Chainlit UI и FastAPI — общий app/core/ layer» → выносим в `app/core/agent.py`.
- M-15-решение пользователя: Chainlit продолжает ходить в graph напрямую — **UI не переписываем**, только переносим общий код.

## Deviations from spec (deliberate, planned)

| Spec says | Done | Why |
|---|---|---|
| PROMPT_MVP: файл `app/api/sessions.py` с 4 эндпоинтами | + `GET /sessions` (пагинация) и `POST /sessions/{id}/resume` | Решение пользователя; resume — минимальный способ ответить на M-13-interrupt через API (BACKLOG5-форма) |
| BACKLOG5: SSE-стрим token/tool_start/tool_end/interrupt/done | JSON-ответ полного хода | Решение пользователя; стриминг — M-24 (Chainlit via FastAPI) |
| BACKLOG5: `app/api/schemas.py` | pydantic-модели инлайном в `app/api/sessions.py` | Один файл на тикет (структура PROMPT_MVP §10); при M-26/M-27 вынесем, если станет тесно |
| M-14 follow-up: «M-20 trigger `project_thread` перед выдачей истории» | не делаем | JSONL — debug/replay-проекция; история для API читается из `messages`-таблицы, триггер не влияет на ответ |
| BACKLOG5: `/health/ready`, `/metrics`, `/tools`, cancel | нет | Отложено (не в решённом scope); `/health` уже существует |

## Design

### 1. `app/core/agent.py` (new) — общий runtime сессии (UI + API)

Перенос из `app/ui/chainlit_app.py` без изменения поведения (chainlit_app оставляет тонкие алиасы — существующие тесты/e2e не ломаются):

- `content_text(content) -> str` (бывший `_content_text`);
- `resolve_checkpointer() -> (checkpointer, degraded)` (Postgres → MemorySaver);
- `build_session_graph(thread_id, checkpointer, *, model=None, policy=None)` — seams: `get_tools` / `get_llm` / `get_policy` / `build_system_prompt` / `trim_messages`;
- `stream_graph_events(graph, user_input, config)` + `_stream_normalized` (astream_events v2 → `token`/`tool_start`/`tool_end`);
- `has_pending_interrupt(graph, config)`, `final_answer_text(graph, config)`;
- `PendingInterrupt` + `get_pending_interrupt(state)` — переезжают из `app/ui/interrupt.py` (там останется re-export + Chainlit-часть `ask_permission`).

Новое (нужно API, юнит-тестируемо без Chainlit/LLM):

- `TurnResult` (dataclass): `status: "ok"|"interrupted"`, `reply: str`, `tool_steps: list[dict]` (`{tool, args, output, run_id}`), `pending: PendingInterrupt | None`;
- `async run_turn(graph, user_input, config) -> TurnResult` — стримит события, накапливает токены/шаги; после итерации `has_pending_interrupt` → статус `interrupted` + payload; иначе `ok` (fallback `final_answer_text` для не-стримящих моделей — как в M-15);
- `async run_resume(graph, decision, config) -> TurnResult` — то же через `resume_graph_events` (`resume_command(decision)`; `decision` ∈ `approve`/`deny`/`always`).

`app/core/graph.py` не трогаем (инвариант: graph не импортирует prompt/context).

### 2. `app/db/session_log.py` — CRUD сессий (строки таблицы `sessions`)

Рядом с существующим `ensure_session`/`log_message` (M-14 owns таблицу):

- `async create_session(*, session_id=None, title=None, provider=None, model=None, working_dir=None, metadata=None, pool=None) -> dict` — генерит `uuid4()` если не задан, `INSERT ... ON CONFLICT DO NOTHING` + `SELECT` → `{session_id, created_at, status, ...}`;
- `async get_session(session_id, *, pool=None) -> dict | None`;
- `async list_sessions(*, limit, offset, pool=None) -> tuple[list[dict], int]` — `ORDER BY last_activity_at DESC` + `COUNT(*)`;
- `async set_session_status(session_id, status, *, pool=None) -> dict | None` — soft-delete (`status='closed'`), валидация статуса;
- `async list_messages(session_id, *, limit=1000, offset=0, pool=None) -> list[dict]` — `ORDER BY seq`.

Всё `async def`, только asyncpg; ошибки БД не глотаем — 503 поднимает API-слой.

### 3. `app/api/sessions.py` (new) — router `/sessions`

Pydantic-схемы: `SessionCreate {title?, provider?, model?, working_dir?, metadata?}`, `MessageCreate {content: str (min_length=1)}`, `ResumeRequest {decision: Literal["allow","deny","always"]}`.

| Endpoint | Поведение |
|---|---|
| `POST /sessions` | `create_session(...)` → 200 `{session_id, created_at, status, ...}` |
| `GET /sessions?page=1&size=20` | `list_sessions` → `{items, total, page, size}` (cap size ≤ 100) |
| `GET /sessions/{id}` | `get_session` → 404; иначе metadata + `list_messages` → `{..., messages: [...]}` |
| `POST /sessions/{id}/messages` | см. ниже |
| `POST /sessions/{id}/resume` | `decision` → `run_resume`; если pending-interrupt нет → **409** |
| `DELETE /sessions/{id}` | `set_session_status(..., "closed")` → 404 если нет; иначе `{session_id, status: "closed"}` (200) |

`POST /messages` (полный ход):
1. `ensure_session` (lenient auto-create — CI может писать в новый thread_id; GET/DELETE/resume — строго 404 при неизвестном id);
2. `log_message(session_id, "user", content)`;
3. checkpointer: `resolve_checkpointer()` (degraded-фолбэк как в UI);
4. **policy per session**: модульный кэш `_session_policies[session_id] = get_policy()` — «always» (session allowlist M-13) живёт между запросами в рамках процесса (в `cl.user_session` это делалось для UI; документируем ограничение);
5. `graph = build_session_graph(...)`; `result = await run_turn(...)`; при `ok` — `log_message(assistant)`;
6. Ответ: `{session_id, status, reply, tool_steps, pending_interrupt, degraded}` (пустые токены/шаги → `[]`).

Ошибка хода (LLM недоступен и т.п.) → `HTTPException(502, detail=...)`. БД недоступна → `503 {"detail": "database unavailable"}`. Auth нет (dev, как в BACKLOG5).

Только `async def`; никаких sync-дефов; `get_settings()` не биндим на import-time.

### 4. `app/main.py` — `app.include_router(sessions_router)` (после llm_router).

### 5. Тесты

`tests/unit/test_api_sessions.py` (new, всегда бегут; sandbox-паттерн `isolated_config` из `test_config.py`; FakePool из `test_session_log.py` по образцу):
- CRUD-контракт SQL: create → 200 + session_id; list-пагинация (LIMIT/OFFSET/COUNT); get 404; get возвращает messages по seq; delete → closed; delete 404; повторный delete идемпотентен по статусу;
- `POST /messages`: monkeypatch seams (`resolve_checkpointer`→MemorySaver, `build_session_graph`→fake-graph с `astream_events`/`aget_state`) → `status=ok`, reply накоплен, tool_steps; `interrupted`-кейс → `pending_interrupt` в ответе + user-сообщение залогировано (записи в FakePool);
- `POST /resume`: allow→`approve`-resume, deny, always; без pending → 409; невалидный decision → 422 (pydantic);
- 503 при недоступной БД (FakePool бросает); пустой content → 422; `/sessions` подключён в app (router registration).

`tests/integration/test_api_sessions_postgres.py` (new, skip без БД; SelectorEventLoop на win32 — паттерн `test_db_postgres.py`):
- create → list(page) → get(metadata+messages) → delete → get 404, через реальный `TestClient` + реальную БД (LLM фейковый — monkeypatch `build_session_graph`/модель);
- roundtrip `log_message` → `GET /sessions/{id}` отдаёт залогированные сообщения.

Существующие `tests/unit/test_chainlit_app.py`, `test_interrupt.py`, e2e — должны пройти **без правок** (re-export алиасы в ui-модулях).

### 6. README

Секция «Sessions API (M-20)» (таблица эндпоинтов, примеры curl) + Phase Progress ✅ M-20 + обновить intro-список тикетов.

## Forbidden patterns (контроль)

- ❌ импорт `langchain_*` вне `app/core/llm/` — соблюдаем (только seams);
- ❌ хардкод tool-list — только `get_tools()`;
- ❌ sync `def` в эндпоинтах; ❌ `JSONResponse` для стримов — стримов нет (JSON);
- ❌ дублирование logic UI/API — вынос в `app/core/agent.py`;
- ❌ schema.sql дрейф — схема не меняется.

## Result

- `app/core/agent.py` (new) — `StreamEvent`, `content_text`, `preview`, `stream_graph_events`/`resume_graph_events`, `resolve_checkpointer`, `build_session_graph`, `has_pending_interrupt`, `final_answer_text`, `PendingInterrupt`/`get_pending_interrupt` (перенесено из `app/ui/*`), новые `TurnResult` / `run_turn` / `run_resume`; win32 Selector-policy теперь ставится здесь.
- `app/api/sessions.py` (new) — router `/sessions` (6 эндпоинтов, все `async def`): create/list(page,size≤100)/get+messages/messages/resume(409 без pending)/delete(soft → `closed`); `SessionCreate`/`MessageCreate`(min_length=1)/`ResumeRequest(allow|deny|always)`; `_session_policies` process-cache (M-13 session allowlist между запросами); `_db()` → 503, неудачный ход → 502.
- `app/db/session_log.py` — `SESSION_STATUSES`, `_session_row` (ISO-даты), `create_session` (uuid4 + metadata JSONB + RETURNING), `get_session`, `list_sessions` (LIMIT/OFFSET + COUNT, ORDER BY last_activity_at DESC), `set_session_status` (валидация + `last_activity_at=now()`), `list_messages` (ORDER BY seq).
- `app/ui/chainlit_app.py` — только рендер/хендлеры; импорты из `app.core.agent` с алиасами (`_content_text`, `_preview`, `_has_pending_interrupt`, `_final_answer_text`) — поведение не менялось.
- `app/ui/interrupt.py` — `PendingInterrupt`/`get_pending_interrupt` re-export из agent; Chainlit-часть (`ask_permission` и пр.) на месте; добавлен `__all__`.
- `app/main.py` — `app.include_router(sessions_router)`.
- `README.md` — секция «Sessions API (M-20)» (таблица, JSON-контракт, curl-пример), Phase Progress ✅ M-15..M-18 (пропущены прошлыми тикетами) + M-20, intro-список тикетов.
- `tests/unit/test_api_sessions.py` (new, 28) — регистрация router (OpenAPI), CRUD SQL-контракт (FakePool), пагинация+cap, 404/503/422, полный ход/интerrupted/fallback/auto-create, resume allow→approve + 409 + повторный interrupt, delete + очистка policy-cache; sandbox `isolated_config`.
- `tests/unit/test_session_log.py` (+7) — CRUD-хелперы напрямую (uuid, metadata JSONB, ORDER BY, валидация статуса, ISO-даты).
- `tests/integration/test_api_sessions_postgres.py` (new) — реальный HTTP через `httpx.ASGITransport` + реальная БД (SelectorEventLoop на win32): create→list→messages (typed round-trip user/assistant)→resume 409→soft-delete (UPDATE status='closed')→404-кейсы; LLM фейковый, checkpointer in-memory.
- `tests/unit/test_chainlit_app.py` — патчи внутренних seams (`build_graph`, `get_checkpointer`, `get_llm`...) перенаправлены с `ui.` на `agent.` (8 тестов); остальные 48+ e2e без правок.

## Verified

- `uv run ruff format .` → `uv run ruff check .` → `uv run ruff format --check .` — чисто (5 автофиксов: неиспользуемые импорты, isort, f-string).
- `uv run pytest -q` при поднятой БД (`docker compose up -d postgres` c `POSTGRES_PORT=5435` + `DATABASE_URL=...@localhost:5435/...`) — **464 passed, 11 skipped** (скипы: `rg` на PATH + live-provider ключи); все интеграционные Postgres-тесты M-03/M-04/M-14/M-20 прошли.
- OpenAPI: `/sessions`, `/sessions/{session_id}`, `/sessions/{session_id}/messages`, `/sessions/{session_id}/resume` зарегистрированы.

## Deviations (исполненные — таблица выше, кратко)

- +2 эндпоинта сверх PROMPT_MVP (resume, GET-список) — решение пользователя; SSE отложен в M-24.
- `schemas.py` не создавался — pydantic-модели инлайн в `sessions.py`.
- `project_thread`-триггер перед выдачей истории не делался (API читает `messages`, JSONL не влияет на ответ).

## Follow-up

- **M-24:** Chainlit → `POST /sessions/{id}/messages` SSE (стриминг-события BACKLOG5); после чего `run_turn` отдаст генератор событий вместо агрегата.
- Cancel-эндпоинт + `GET /sessions/{id}/events` (BACKLOG5) — при появлении первого клиента.
- Policy-cache per session — при ALPHA-auth сменится на per-user; «always» сейчас переживает только рестарт процесса.
- `/metrics`, `/health/ready` — отдельным тикетом (ALPHA observability).
