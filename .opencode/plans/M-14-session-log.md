# Plan: M-14 — Session-log (PostgresSaver + JSONL projection)

**Status:** executed
**Commit message:** `M-14: session-log (log_message, JSONL projection, sessions_dir config)` (`6a0832f`) + `M-14: README session-log section + phase progress` + `M-14: executed ticket plan`
**User decisions:** план утверждён без изменений (PROMPT_MVP как фазовый источник истины; deviations — осознанные, таблица ниже).

## Deviations from spec (deliberate, documented)

| Spec says | Done | Why |
|---|---|---|
| BACKLOG4: `app/core/session.py::get_checkpointer` | уже существовал в `app/db/checkpoints.py` (M-03) — не дублируем; весь M-14 lives in `app/db/session_log.py` | DRY; структура PROMPT_MVP §10 указывает `db/session_log.py`; прецедент M-13: PROMPT_MVP фазовый приоритет над BACKLOG4 |
| BACKLOG4: «воркер читает `graph.aget_state_history(config)`» | `checkpointer.alist(config)` напрямую (`AsyncPostgresSaver`) | На старте приложения graph-инстанса нет (он собирается per-request в M-15); `alist` отдаёт те же `CheckpointTuple` (`checkpoint["ts"]`, `channel_values["messages"]`), без зависимости от `build_graph` |
| BACKLOG4: дедупликация только по `ts` (`last_processed_ts` в meta.json) | `last_processed_ts` гейтит чекпоинты **+** эмиссия дельты сообщений между соседними снапшотами | Снапшот `channel_values["messages"]` хранит **всю** историю треда — без дельты каждый новый checkpoint повторно эмитил бы старые сообщения; дельта по `message.id` (LangGraph присваивает uuid через `add_messages`); meta содержит ровно `{"last_processed_ts"}` как в спеке |
| PROMPT_MVP: `log_message(session_id, role, content, tool_calls)` | + необязательный `tool_call_id`, авто-`seq` (`COALESCE(MAX(seq),0)+1` в INSERT..SELECT), `ensure_session()` перед insert (FK), инъекция `pool=` для тестов | Таблица `messages` (M-03) имеет FK на `sessions` и `UNIQUE(session_id, seq)`; `tool_call_id` — колонка в canonical schema |
| «JSONL projection — отдельный async-воркер при старте приложения» | FastAPI lifespan (`app/main.py::_lifespan`) → `asyncio.create_task(projection_worker())`; цикл discover (`SELECT DISTINCT thread_id FROM checkpoints`) → project → sleep 30s; все ошибки — warning, retry; cancel на shutdown | `TestClient` в `tests/conftest.py` гоняет lifespan — worker обязан soft-fail без БД; «прогрессия по ts» переживает рестарт процесса через meta.json |
| Формат события `{"ts","type","payload"}` (BACKLOG4) | как указано; `type` ∈ `user`/`ai`/`tool`/`system`; payload: `message_id`, `content`, опционально `tool_calls`/`tool_call_id`/`name` | AC «≥3 events (user, ai, tool)» после одного tool-turn |

Известные ограничения (приняты для MVP): гонка конкурентных `log_message` по `seq` (пишется последовательно с уровня сессии); потеря meta → полный re-emit истории в append-only файл (consumer может дедуплицировать по `message_id`).

## Result

- `app/db/session_log.py` (new) — `ensure_session` / `log_message` (typed messages, авто-seq, JSONB tool_calls), `discover_thread_ids`, `project_thread` (checkpoint→JSONL, ts-dedup + message-id дельта, meta.json), `projection_pass` / `projection_worker` (soft-fail, stop-event), `session_jsonl_path`.
- `app/core/config.py` — `sessions_dir` (default `~/.orya/sessions`, env `ORYA_SESSIONS_DIR`, yaml-fallback, tilde-expansion); `.env.example` — закомментированный `ORYA_SESSIONS_DIR`.
- `app/main.py` — lifespan: mkdir `sessions_dir` + фоновый `projection_worker`; shutdown — cancel/await.
- `tests/unit/test_session_log.py` (new, 15 tests) — fake-pool SQL-контракт `log_message`/`ensure_session`/`discover_thread_ids` (включая UndefinedTable→[]), JSONL: полный tool-turn user/ai/tool/ai, idempotent rerun, append-only дельта, corrupt-meta re-project, worker stop/failure-survival, путь из настроек (sandbox `ORYA_SESSIONS_DIR`).
- `tests/unit/test_config.py` (+3) — default/env-tilde/yaml для `sessions_dir`.
- `tests/integration/test_session_log_postgres.py` (new) — реальный Postgres+checkpointer (SelectorEventLoop на win32): graph.ainvoke → project ≥3 events (user/ai/tool) → rerun 0 → discover → `close_checkpointer`+re-get → `aget_state` возвращает последнее состояние (AC «после рестарта»); roundtrip `log_message` (авто-seq 1..3, tool_calls JSONB, ensure_session).
- `README.md` — секция «Session-log (M-14)» + Phase Progress ✅ M-14 + intro-список тикетов.
- `.opencode/plans/M-14-session-log.md` — этот файл.

## Verified

- `uv run pytest tests/unit/test_session_log.py tests/unit/test_config.py -q` — **35 passed**.
- Полный `uv run pytest -q` при поднятой инфраструктуре (`POSTGRES_PORT=5435 make db-up`, `DATABASE_URL=...@localhost:5435/...`) — **330 passed, 10 skipped** (skips: live-provider ключи + `rg` на PATH; интеграционные Postgres-тесты M-03/M-04/M-14 прошли).
- `uv run ruff check .` + `uv run ruff format --check .` — чисто.

## Follow-up

- **M-15/M-16 (UI):** вызывать `log_message` на каждом ходе агента (user/assistant/tool) — typed-лог пока пишется только напрямую/API-слоем; JSONL пишется воркером автоматически.
- **M-20 (/sessions):** список сессий из `sessions.last_activity_at` + ручной trigger `project_thread` перед выдачей истории.
- **Retention (ARCHITECT4 §6.5):** партиционирование/удаление старше 90 дней — не в MVP.
- **v6 M-14:** BranchManager поверх того же checkpoint-шва (BACKLOG5).
