# Plan: M-27 — Compactor + `/memory/compact`, `/memory/stats`, `/memory`

**Status:** executed
**Commit message:** `M-27: Compactor (L0 archive-based soft compaction) + /memory endpoints + /memory slash-commands + periodic worker + M-18 memory-AC unblocked` + `M-27: executed ticket plan`
**Spec:** `analytics/PROMPT_MVP.md` §3.7 M-27 + §3.5 (slash-commands) (канон; файла `PROMPT-MVP.md` в репо нет) + BACKLOG6 M-27 (AC) + ARCHITECT6 §4.2.2/§6.1.4/§4.4

**User decisions (утверждены до исполнения):**
1. Контракт endpoint'ов — **union**: глобальные `POST /memory/compact`, `GET /memory/stats`, `GET /memory` (PROMPT_MVP) **+** `POST|GET /sessions/{id}/memory[/compact|/stats]` (BACKLOG6/ARCHITECT6) на общих хендлерах — по прецеденту M-26.
2. Долг M-18 — **расблокировать всё**: canonical smoke task #5 («/learn → next turn»), проверка `/memory/stats` и atomic-append durability в `tests/smoke/`.
3. `DECISIONS.md` superseded — **маркер в блоке**: regex `superseded_by=` / `[superseded]` / `superseded:` (case-insensitive) по сырому блоку; модель M-25 не меняется.

## Context

- Спеки конфликтовали по путям (глобальные `/memory*` vs `/sessions/{thread_id}/memory*`), по формату ответов (PROMPT_MVP `{files, line_counts, token_counts, last_compacted}` vs BACKLOG6 `{files:[{name,size_bytes,entries_count,last_write_ts}], total_size_bytes}`) и по файлам (M-25/M-27 живут на шести файлах, стратегии описаны для четырёх).
- M-25 оставил заглушку: `MDStore.compact_if_needed` только логирует и возвращает `needs_compaction()`; `_maybe_compact` уже планирует async-задачу после append — M-27 подключает к ней реальную работу. Docstring M-25 обещает «rewrites = tmp + os.replace», но метода rewrite в `MDStore` нет.
- `parse_entries` (M-25) парсит блоки: `#`-заголовки пропускаются, ручной текст → `source="manual"`, `confidence=1.0`. Пересборка файла из объектов теряла бы заголовки → compaction работает с **сырыми блоками**, объекты используются только для классификации.
- AC «LEARNED.md ≤ 4 KB после compaction» стратегия «last 10 + high-confidence» сама по себе не гарантирует (последние 10 записей могут быть толстыми) → добавлен size-guard.
- `PREFERENCES`/`FACTS` обязаны хранить protected-классы (user_explicit / confidence≥0.9) даже сверх бюджета — иначе противоречие «keep all» vs «≤ 4 KB». Size-guard только для LEARNED (стратегия recency-based).
- Цепочка уже размечена в коде: `app/core/memory/compactor.py` (docstring M-25), `app/api/memory.py` (дерево PROMPT_MVP), `format_memory_block` предлагает «run /memory/compact», `permissions.TRUSTED_PREFIXES=("memory/",)`, тест `test_permissions` уже знает имена `memory/stats`, `memory/compact`.
- chainlit 2.12 без `cl.on_slash_command` → команды разбираются в `on_message` (как `/learn` в M-26).

## Deviations from spec (deliberate, planned)

| Спека | Сделано | Почему |
|---|---|---|
| два конфликтующих контракта endpoints | union: оба префикса, общие хендлеры | решение пользователя (M-26 precedent) |
| `GET /memory` → голый markdown (AC) | JSON `{"files": {имя: тело}, "markdown": concat}` | API-консистентность (`/learn` отдаёт JSON); UI/CI берут `markdown` |
| compaction «всех 4 файлов» vs 6 файлов M-25 | compact — только 4 файла со стратегией; stats/cat — все 6 / 4 по AC | PROJECT.md/MEMORY_INDEX.md без confidence-метаданных (placeholder, контекст) |
| superseded-поля в L0-формате нет | regex-маркер в сыром блоке | решение пользователя; ручные правки файла работают, модель M-25 не тронута |
| «≤ 4 KB после compaction» для всех файлов | size-guard (архивировать старые из keep) **только** для LEARNED | PREFERENCES/FACTS хранят protected-классы (`keep all`), их trim по размеру противоречил бы спеке; переполнение → `over_limit: true` в result |
| `APScheduler` (PROMPT_MVP) | `asyncio`-цикл в lifespan (`asyncio.sleep`, configurable) | BACKLOG6 M-27: «`asyncio.create_task` с `asyncio.sleep(24*3600)`, configurable»; APScheduler — внешняя зависимость, в pyproject её нет |
| `last_compacted` в БД | `memory_dir/compaction.json` (атомарная запись) | без миграции — прецедент M-26 (audit без колонок) |
| periodic: «проверять все 4 файла, compact_if_needed» | worker гоняет `compact_all_if_needed()` — тот же код, что и ручной запуск | одна точка правды; AC «раз в 24 часа» выполняется |
| токены в stats | `len(content) // 4` (chars/4) | тот же допуск, что в M-06 (`context.count_tokens` без модели); tiktoken для MD-файлов — overkill |
| session_id в `/sessions/{id}/memory*` | принимается, валидации нет, идёт только в audit | память project-level (точно как `/learn` в M-26) |
| (баг M-25, найден AC «size_bytes») | `_write_append` открывает дескриптор с `O_BINARY` | на Windows `os.open` без него = текстовый режим → каждый `\n` писался как `\r\n`: бюджеты/статистика вились, payload не совпадал с байтами в файле; AC M-18 «atomic-append durability» без этого невыполнимо буквально |

## Design (исполнено)

1. **`app/core/memory/compactor.py`** (новый):
   - `CompactionResult` (dataclass): `file, changed, before_bytes, after_bytes, kept, archived, archive_path, over_limit`.
   - `Compactor(store)` + `get_compactor()` (кэш по `memory_dir`, паттерн `get_md_store`). Ядро синхронное (`compact`/`compact_all`), async-обёртки через `asyncio.to_thread` — I/O и `threading.Lock` не блокируют loop (forbidden: `time.sleep`, блокировка turn'а).
   - `STRATEGIES` = `{PREFERENCES, LEARNED, FACTS, DECISIONS}` (ARCHITECT6 §6.1.4). Блочный парсинг сырого текста (сплит как в `parse_entries`); классификация по мета-строке блока; `#`-заголовки и распознаваемо-нераспознанные блоки → **keep всегда**.
   - Стратегии: `PREFERENCES` — archive только `agent_inferred` + confidence<0.8; `LEARNED` — keep = последние 10 ∪ confidence≥0.9, затем size-guard (archive старых из keep, пока ≤ budget, минимум один новейший блок); `FACTS` — keep confidence≥0.9; `DECISIONS` — archive при superseded-маркере.
   - Архив: `{memory_dir}/archive/{stem}_{YYYYMMDD}.md` (UTC), только `O_APPEND`, повторный запуск в тот же день дописывает в тот же файл; порядок crash-safe — **сначала append в архив, потом rewrite L0** (дубль безопасен, потеря невозможна).
   - Rewrite идёт через новый `MDStore.rewrite(file, transform)` (per-file lock, чтение+преобразование+запись одним critical section, tmp + `fsync` + `os.replace`) — закрывает «compaction без per-file lock» и даёт AC «no partial after crash»; параллельный `append` во время compaction не теряется.
   - Аудит: `record_memory_op("memory.compact", file, reason=..., actor=...)` (who/when/what/why, PROMPT_MVP); состояние `last_compacted` per file → `memory_dir/compaction.json` (атомарно, tmp+replace).
   - `compaction_worker(interval, *, sleep=asyncio.sleep)` — цикл `sleep(interval)` → `compact_all_if_needed()`; мок `sleep` в тесте проверяет интервал 86400 (AC «mock time»).
   - `compact_if_needed(file)` — по `store.needs_compaction()`; именно его дёргает M-25-хук `_maybe_compact`.
2. **`app/core/memory/md_store.py`**: + `replace(file, content)` (per-file lock, tmp в той же директории, `fsync`, `os.replace`); `compact_if_needed` делегирует в Compactor (lazy import — без цикла модулей); `_maybe_compact` не меняется.
3. **`app/core/config.py`**: `memory_compact_interval_s: int = 86400` (`ORYA_MEMORY_COMPACT_INTERVAL_SECONDS`) + запись в `_YAML_FALLBACKS`; строка в `.env.example`.
4. **`app/api/memory.py`** (новый): `router = APIRouter(tags=["memory"])`
   - `POST /memory/compact` + `POST /sessions/{session_id}/memory/compact` → `{status, results: [CompactionResult...], total_archived}`.
   - `GET /memory/stats` + `GET /sessions/{session_id}/memory/stats` → union: `files[{name, size_bytes, entries_count, line_count, token_count, last_write_ts, max_bytes, over_limit}]`, `total_size_bytes`, `line_counts{}`, `token_counts{}`, `last_compacted`.
   - `GET /memory` + `GET /sessions/{session_id}/memory` → `{files, markdown}` — конкатенация 4 файлов в порядке `format_memory_block`.
5. **`app/main.py`**: `include_router(memory_router)`; lifespan запускает `compaction_worker(settings.memory_compact_interval_s)` при interval>0 и гасит на shutdown (рядом с projection-worker).
6. **`app/ui/chainlit_app.py`**: в `on_message` до отправки хода — парсер union-команд (`/memory`, `/memory stats|compact`, `/memory/stats`, `/memory/compact`, `/memory cat|show`); хендлеры `_handle_memory` по образцу `_handle_learn` (httpx через `make_client`, статус≠200 → детали, httpx-ошибка → «unreachable»). Рендер: stats → markdown-таблица, compact → строка per file, cat → markdown контента.
7. **README**: секция «Compactor (M-27)» (таблица endpoints, стратегии, periodic) + строка Phase Progress; **AGENTS.md**: memory-строка (compactor.py, endpoints, worker).

## Result (файлы)

- Созданы: `app/core/memory/compactor.py`, `app/api/memory.py`, `tests/unit/test_compactor.py` (20), `tests/unit/test_api_memory.py` (8).
- Изменены: `app/core/memory/md_store.py` (`rewrite()` + `O_BINARY` + реальный `compact_if_needed`), `app/core/memory/__init__.py` (re-export Compactor-сева), `app/core/config.py`, `.env.example`, `app/main.py`, `app/ui/chainlit_app.py` (+7 тестов), `tests/unit/test_md_store.py` (+3), `tests/unit/test_config.py` (+1), `tests/unit/test_chainlit_app.py` (+7), `tests/smoke/test_smoke.py` (task 5 раскипнут + 2 memory-AC), `README.md` (секция Compactor + Phase Progress), `AGENTS.md` (memory-сева + "~10 fields").

## Verified

- `uv run ruff format .` → `uv run ruff check .` → `uv run ruff format --check .` — чисто (194 файла).
- `uv run pytest -q` — **655 passed, 19 skipped** (было 616/20: −1 skip = smoke #5 раскипнут, +39 тестов), 83 s; оставшиеся скипы — условные (Postgres/live-providers/`rg`).
- AC-трейс M-27 (всё в тестах): 20 записей → async `compact_if_needed` → LEARNED ≤ 4096 B + архив содержит старые; `POST /memory/compact` → 4 результата + `total_archived`; `GET /memory/stats` → union-shape (`files`/`line_counts`/`token_counts`/`last_compacted`); `GET /memory` → `{files, markdown}`; worker спит ровно 86400 между проходами (mock `sleep`) и компактит, `0` = выключен, падение прохода не убивает цикл; crash до `os.replace` → старый файл без `*.tmp`, архив уже содержит блоки (retry без потерь); append во время compaction не теряется; protected-классы PREFERENCES не trim-ятся (`over_limit: true`); заголовки/ручной текст/`source=user_explicit` не архивируются; `memory.compact` аудит (actor/trigger/counts) + `compaction.json`; union-пути и обе раскладки slash-команд (`/memory stats` и `/memory/stats`); smoke: факт из `/learn` виден в system-prompt следующего turn (через реальный `build_system_prompt` в graph), `GET /memory/stats`, 40 параллельных append без torn-записей.

## Follow-up

- B-21 (SQLiteStore L1): compaction вместо архива на диске начнёт писать в L1 + outbox; интерфейс `Compactor` уже не меняется.
- `scope=session|global` (B-21/E-11) — как и в `/learn`, пишется в project-store.
- Если protected-записи (user_explicit / confidence≥0.9) раздуют PREFERENCES/FACTS сверх бюджета — либо поднять бюджет, либо L1-переезд; сейчас только `over_limit`-флаг в result/stats.
