# Plan: M-15 — Chainlit UI (on_chat_start, on_message, streaming)

**Status:** executed
**Commit message:** `M-15: chainlit UI (on_chat_start, on_message, streaming)` + `M-15: executed ticket plan`
**User decisions:**
1. Chainlit → graph **напрямую** (BACKLOG4-форма), не через FastAPI/SSE — minimal M-20 не входит в тикет, M-24 (переход на SSE) остаётся отдельным будущим тикетом.
2. Checkpointer: Postgres (`get_checkpointer`) → fallback `MemorySaver` при недоступности (warning в лог, degraded-сообщение в UI).

## Deviations from spec (deliberate, documented)

| Spec says | Done | Why |
|---|---|---|
| PROMPT_MVP §3.5 (v5/v6): «Chainlit работает через FastAPI» (M-24 update) | Chainlit вызывает graph напрямую (`astream_events`) | Решение пользователя (см. выше); PROMPT_MVP §3.5 без строки M-24 — BACKLOG4-форма консистентна с «M-15…M-17 = UI» |
| BACKLOG4: проверять `state.next == ('tools',)` | `state.next == ('human',)` | M-13: `interrupt()` вызывается внутри `human`-узла — `.next` отдаёт незавершённый узел (проверено empirically) |
| BACKLOG4: `async with cl.Step(...)` в обработчике | явные `step.send()` / `step.update()` через `dict[run_id → cl.Step]` | параллельные tool-calls interleave-ят события (start A, start B, end B, end A) — `async with` закрыл бы не тот шаг |
| BACKLOG4: «`chainlit run app/ui/chainlit_app.py --port 8000`» | `make ui` → `${CHAINLIT_PORT:-8001}`; `chainlit_port` default 8000→8001 | 8000 занят `make dev` (uvicorn); `.env.example` + `test_config.py` обновлены |
| — | `asyncio.set_event_loop_policy(WindowsSelectorEventLoopPolicy)` в начале модуля (win32) | chainlit вызывает `asyncio.run()` **после** `load_module` → по умолчанию Proactor → psycopg (`AsyncPostgresSaver`) всегда падал бы; `bash.py` в docstring уже рассчитывает на Selector-цикл под uvicorn |
| BACKLOG4 AC: история после refresh / продолжение после рестарта | отложено в M-17 (sidebar сессий) | требует список сессий + восстановление треда; M-15 генерирует новый thread_id на каждый чат |
| M-16 (ask-кнопки) | hint-сообщение `_INTERRUPT_HINT` при `state.next != ()` | тикет M-16 owns UI; fail-closed: без кнопок рун стоит на паузе |
| BACKLOG4 AC: tool-cards + streaming | выделенный `stream_graph_events` (normalized `token`/`tool_start`/`tool_end`) вместо инлайн-фильтра в обработчике | маппинг событий тестируется без Chainlit-рантайма (хендлеры требуют websocket-контекст: `cl.Message` бросает `ChainlitContextException` вне сессии) |

Известные ограничения (приняты для MVP): при недоступном Postgres сессия живёт в памяти процесса (перезапуск теряет тред); assistant-лог пишется текстом без `tool_calls` (tool-шаги в типизированной таблице пока не дублируются — см. follow-up M-14).

## Result

- `app/ui/chainlit_app.py` (new) — `stream_graph_events` (astream_events v2 → token/tool_start/tool_end, пустые чанки фильтруются, content-blocks flatten), `resolve_checkpointer` (Postgres→MemorySaver), `build_session_graph` (seams: `get_tools`/`get_llm`/`get_policy`/`build_system_prompt`/`trim_messages`), `_has_pending_interrupt` / `_final_answer_text` (fallback для не-стримящих моделей), `_safe_ensure_session`/`_safe_log` (best-effort), `_start_step`/`_end_step`/`_close_steps`, хендлеры `@cl.on_chat_start` / `@cl.on_message` (stream_token → send, ошибки → `Run failed: …`), win32 Selector policy.
- `Makefile` — цель `ui` (`.PHONY` + `uv run chainlit run app/ui/chainlit_app.py --port $${CHAINLIT_PORT:-8001}`).
- `app/core/config.py` — `chainlit_port` default 8001; `tests/unit/test_config.py` assertion; `.env.example` `# CHAINLIT_PORT=8001`.
- `chainlit.md` — project-specific welcome screen (иначе chainlit regenerates эмодзи-шаблон при каждом старте).
- `tests/unit/test_chainlit_app.py` (new, 20 tests) — маппинг событий (включая v2-контракт и пустые чанки), wiring `build_session_graph` (monkeypatched seams, identity `system_prompt_fn`/`trim_fn`), checkpointer fallback/postgres, state-пробы (human-pause/finished/error), best-effort лог, `_content_text`/`_preview`.
- `tests/e2e/test_chainlit_smoke.py` (new) + `tests/e2e/__init__.py` — регистрация хендлеров + реальный прогон: scripted streaming-модель (`_stream` c `tool_call_chunks`) → `build_graph` → события tool_start/tool_end → токены в порядке рендера.
- `.opencode/plans/M-15-chainlit-ui.md` — этот файл.

## Verified

- `uv run ruff format .` + `uv run ruff check .` + `uv run ruff format --check .` — чисто.
- Полный `uv run pytest -q` — **344 passed, 18 skipped** (скипы: Postgres-инfra, live-provider ключи, `rg`; 22 новых теста M-15 зелёные).
- Boot-smoke: `chainlit run app/ui/chainlit_app.py --headless --port 8017` → «Your app is available», HTTP 200, страница отдаётся (потом процессы остановлены, порт свободен). Без Postgres в логе ожидаемый warning fallback.
- Живой ход с реальным LLM не прогонялся (нет API key в окружении) — ручной AC: `make ui`.

## Follow-up

- **M-16:** `cl.AskActionMessage` при `state.next == ("human",)` → `resume_command("approve"|"deny"|"always")` через `/sessions/{id}/resume` или напрямую с graph; сейчас — hint.
- **M-17:** sidebar-сессии + восстановление истории после refresh (сейчас thread_id теряется при перезагрузке).
- **M-24:** переключить Chainlit на FastAPI-SSE (`POST /sessions/{id}/messages`), убрать прямой graph-доступ из UI.
- **M-14 follow-up:** логировать tool-шаги в `messages` (role=`tool`) и `tool_calls` assistant-сообщений; сейчас — только user/assistant-текст.
- **README:** секция M-15 (как запустить UI) — при M-19.
