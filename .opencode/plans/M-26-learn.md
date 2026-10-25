# Plan: M-26 — `/learn` endpoint + Chainlit slash-command

**Status:** executed
**Commit message:** `M-26: /learn endpoints (session sequence + content) + Chainlit slash-command + learn audit extras` + `M-26: executed ticket plan`
**Spec:** `analytics/PROMPT_MVP.md` §3.7 M-26 + §4 (канон; файла `PROMPT-MVP.md` в репо нет) + BACKLOG6 M-26 (AC) + ARCHITECT6 §3.1.1/§4.3/§13.2

**User decisions (утверждены до исполнения):**
1. Контракт — **union**: `POST /sessions/{id}/learn` (ARCHITECT6 §4.3.1, захват последовательности; основной для Chainlit) **+** `POST /learn` (PROMPT_MVP `{content, category}` для CI/батч) на общем хелпере записи.
2. Источник sequence — **JSONL-проецирование M-14** (`{sessions_dir}/{id}.jsonl`) c best-effort `project_thread()` перед чтением; не PostgreSQL.
3. Аудит — **без миграции**: `record_memory_op` принимает `memory_id`/`source`/`trace_id` — отдельными полями в JSONL-фолбэке, склеенными в `reason` для строки PG; ключ остаётся `action` (M-25) со значением `learn`.

## Context

- Контракты спек конфликтовали: PROMPT_MVP (`POST /learn` + `{content, category}` → `{status, file, line_count}`) vs BACKLOG6/ARCHITECT6 (`POST /sessions/{id}/learn` + `{pattern_name, description, scope}` → `{learned_id, file, compacted}`, захват последней успешной последовательности).
- `messages` пишет только user/assistant/system (tool-вызовы туда не попадают); таблица `tool_calls` в schema.sql есть, но в неё не пишет никто. Носитель tool-событий с args/результатом — JSONL-проецирование M-14.
- `_message_event` не фиксировал `ToolMessage.status` (`success`/`error`) — сигнал успеха из чекпоинтов был недоступен.
- chainlit 2.12 не имеет `cl.on_slash_command` → разбор `/learn` в `on_message` (так же в примере ARCHITECT6 §4.3.2).
- M-25 уже дал seam: `MDStore.append` (per-file lock, аудит `memory.append`, автозапуск `_maybe_compact`), `MemoryItem.to_markdown`, `next_id`, `format_memory_block` читает L0 каждый turn — контракт «/learn виден на следующем turn» выполняется без правок промпта.

## Deviations from spec (deliberate, planned)

| Спека | Сделано | Почему |
|---|---|---|
| PROMPT_MVP и BACKLOG6 — разные контракты | оба эндпоинта, общий `_store_entry` | решение пользователя (union) |
| session-log из БД | JSONL-проецирование + best-effort `project_thread()` (ошибка → тихо читаем файл) | решение пользователя: работает без PG, юнит-тестируется |
| `op=learn` (§13.2) | `action="learn"` (ключ M-25) | без миграции; решение пользователя |
| колонки `memory_id/source/trace_id` в PG | JSONL-поля + склейка `memory_id=… source=… trace_id=…` в `reason` | решение пользователя |
| `compacted` после async compaction | флаг = `needs_compaction()` после append (сам append уже планирует `_maybe_compact`, M-25); ни один await не ждёт compaction | запрет блокировать ответ; реальная работа = M-27 |
| `@cl.on_slash_command("learn")` | разбор в `on_message` (`"/learn"` / `"/learn "`) + `shlex` | decorator'а нет в chainlit 2.12 |
| category fact → LEARNED.md (буква PROMPT_MVP) | `fact→FACTS.md`, `preference→PREFERENCES.md`, `project→LEARNED.md` | файловая таблица ARCHITECT6 §3.1.1 + union-решение M-25 |
| `scope` (session/project/global) | принимается (422 вне Literal), пишет всегда в project-store (`settings.memory_dir`) | `session`/`global` — заглушки TODO B-21/E-11 (BACKLOG6) |
| `emit_memory_write_span` (§4.3.1 п.5) | нет | OryaObservability в MVP отсутствует |
| AC «последняя последовательность» | обход с конца: `ai`/`system` прозрачны, стоп на первом `user` (граница хода) или на первом неуспешном tool → «последняя успешная»; пусто → 400 | формализация BACKLOG6 «successful» |
| формат строки confidence `0.90` | `0.9` (repr float в `MemoryItem.to_markdown`, M-25) | не трогаем общий render; парсинг идентичен |

## Design (исполнено)

1. **`app/api/learn.py`** (новый):
   - `LearnRequest` (`pattern_name?`, `description?`, `scope: Literal["session","project","global"]="session"`), `LearnContentRequest` (`content` min 1, `category: Literal[...]`), `LearnResponse` (`status`, `learned_id`, `file`, `compacted`, `line_count`).
   - Извлечение: `load_events` (tolerant JSONL) → `extract_sequence` (обход назад, см. таблицу) → `_is_success`: `payload.status=="error"` | префикс `Denied by policy:`/`Denied:` | bash: JSON в `[UNTRUSTED_CONTENT_*]` c `exit_code != 0` (старые логи без `status` живут на эвристиках).
   - `auto_name` = ordered-unique имён → `grep_read_edit` (санитайзер `[a-z0-9_]`, cap 60); `format_entry` — блок §3.1.1 (Сценарий/Паттерн `name(args)` через `→`/Контекст с `name:`/Условие успеха).
   - `_store_entry`: под процессным `threading.Lock` — `next_id(store.read(file), kind)` → `MemoryItem.create` → `store.append(..., session_id=...)` → `needs_compaction` → `line_count`; затем `record_memory_op("learn", ...)` c `memory_id/source/trace_id` (uuid4 hex16).
   - Эндпоинты: `POST /sessions/{session_id}/learn` (best-effort `project_thread`, 400 «No successful tool-call sequence to learn») и `POST /learn` (маппинг категории → файл, kind/confidence через `kind_for`/`_CONFIDENCE`).
2. **`app/core/memory/audit.py`** — `record_memory_op(+memory_id=, source=, trace_id=)`: JSONL всегда с этими ключами, PG-строка получает их в `reason` (`base; memory_id=… source=… trace_id=…`).
3. **`app/db/session_log.py`** — `_message_event`: `payload["status"]` для `ToolMessage` (аддитивно, обратно совместимо).
4. **`app/main.py`** — `include_router(learn_router)` (после sessions).
5. **`app/ui/chainlit_app.py`** — `_learn_args` (shlex, фолбэк на split при незакрытых кавычках), `_handle_learn` (POST, 400 → `/learn failed: <detail>`, httpx → «unreachable»), хук в `on_message` до отправки хода; фидбек ``✅ Learned: `learn_001` → LEARNED.md (compacted: false)``.
6. **`README.md`** — секция «`/learn` (M-26)» (таблица эндпоинтов, контракт, audit, slash-command) + строка Phase Progress.

## Result (файлы)

- Созданы: `app/api/learn.py`, `tests/unit/test_api_learn.py` (26).
- Изменены: `app/core/memory/audit.py`, `app/db/session_log.py`, `app/main.py`, `app/ui/chainlit_app.py`, `tests/unit/test_chainlit_app.py` (+6: `/learn`-хендлеры и парсер), `tests/unit/test_session_log.py` (+1: `status` в проекции), `README.md`.

## Verified

- `uv run ruff format .` → `uv run ruff check .` → `uv run ruff format --check .` — чисто (188 файлов).
- `uv run pytest -q` — **616 passed, 20 skipped** (прежние условные скипы), 93 s.
- AC-трейс M-26: оба роута в openapi; `{}` → `{status:"ok", learned_id:"learn_001", file:"LEARNED.md", compacted:false, line_count}`; запись `- [learned] id=learn_001 | confidence=0.9 | source=/learn | ts=…` парсится `parse_entries`; auto-name `grep_read_edit` + `pattern_name`/`description` в записи; последний tool с ошибкой / отказ / `exit_code=2` / без tool-вызовов / без файла → 400 с текстом AC; ошибка *до* успеха → захватывается только успешный ход; `status`-фолбэк на старых логах; сбой `project_thread` не роняет запрос; неизвестный `scope` → 422; файл >4096 → `compacted:true`; две сессии → `learn_001`+`learn_002` без потерь; 2 потока через `_store_entry` (barrier) → уникальные id и обе записи; аудит: JSONL содержит `action=learn`, `file`, `memory_id`, `source`, `trace_id` (+ сложенные в `reason` поля и рядом `memory.append`); `POST /learn` маппит категории (fact→FACTS, preference→PREFERENCES, project→LEARNED) и валидирует пустой content/чужую категорию → 422; после `/learn` `format_memory_block()` содержит факт; проекция отдаёт `status` tool-сообщений; UI: `/learn name "desc"` шлёт верный JSON одним запросом (ход не отправляется) и рендерит ровно строку AC, `/learn` → пустой body, 400/недоступный сервер/нет сессии → понятные сообщения.

## Follow-up

- **M-27** Compactor: реальный `compact_if_needed`, `POST /sessions/{id}/memory/compact`, `GET .../memory/stats` — `compacted`-флаг M-26 уже опирается на `needs_compaction()`.
- `tests/smoke/test_smoke.py::test_smoke_learn_fact_used_next_turn` всё ещё skip-ится с формулировкой «blocked on M-25/M-26/M-27» — M-25/M-26 закрыты, расблокировка канонической задачи 5/5 остаётся за M-18/M-27.
- B-21 (scope=session в L1 SQLite) и E-11 (global) — `scope` сейчас принимается, но пишет в project-store.
- Расширить проекцию/чтение `tool_calls`-таблицы, если `/learn` понадобится вне API-процесса (проект-agnostic L1).
