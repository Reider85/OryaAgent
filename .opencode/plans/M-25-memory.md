# Plan: M-25 — MDStore: L0 MD-файлы + atomic-append

**Status:** executed
**Commit message:** `M-25: MDStore L0 (6 MD files, O_APPEND+fsync, MemoryItem, best-effort audit)` + `M-25: prompt reads L0 through the MDStore seam` + `M-25: README (L0 memory section) + AGENTS memory conventions + .gitignore fix` + `M-25: executed ticket plan`
**Spec:** `analytics/PROMPT_MVP.md` §3.7 M-25 + §4.5 (memory-seam) (канон) + BACKLOG6 M-25 + ARCHITECT6 §3.1.1/§4.2/§6.1.1/§12.2

**User decisions (утверждены до исполнения):**
1. Набор файлов — **все 6**: `PROJECT.md`, `LEARNED.md`, `PREFERENCES.md`, `FACTS.md`, `DECISIONS.md`, `MEMORY_INDEX.md` (union PROMPT_MVP и BACKLOG6/ARCHITECT6).
2. Append — **`O_APPEND` + один `os.write` + `fsync` + per-file `threading.Lock`** (BACKLOG6/ARCHITECT6 §4.2.1); tmp+`os.replace` остаётся для rewrite (compaction M-27); `fcntl.flock` — best-effort только на POSIX.
3. Объём — **MDStore + `models.py` (`MemoryItem`) + перевод `prompt.py` на MDStore** (единый seam).
4. Audit — **best-effort строка `memory.append` в `memory_audit_log` при каждом append** (вопреки отложению до M-27 — схема упоминает M-25).

## Context

- `app/core/memory/` не существовал; `settings.memory_dir` (config.py:148), `ORYA_MEMORY_DIR` в `.env.example:23`, таблица `memory_audit_log` (schema.sql, миграция `0001_init.sql`) и JSONL-фолбэк-паттерн (`security.py:245-271`, `drain_incidents`) уже были.
- `app/core/prompt.py` читал PROJECT/LEARNED/PREFERENCES напрямую `Path.read_text` (`_read_memory_file`) — memory-seam отсутствовал; `format_memory_block` инжектировал только 2 файла.
- Спеки конфликтовали: PROMPT_MVP (tmp+`os.replace`, `fcntl.flock`, PROJECT/MEMORY_INDEX) vs BACKLOG6/ARCHITECT6 (O_APPEND+fsync+threading.Lock, FACTS/DECISIONS); `fcntl` на win32 нет.
- `.gitignore:135` (`memory/`) игнорировал бы новый пакет — обнаружено при `git status`.

## Deviations from spec (deliberate, planned)

| Спека | Сделано | Почему |
|---|---|---|
| PROMPT_MVP: 4 файла / BACKLOG6: 4 других | **6 файлов** (union); PROJECT остаётся в `project_context_block`, MEMORY_INDEX — пустой placeholder до BETA | решение пользователя; иначе FACTS/DECISIONS недостижимы для LLM, а PROJECT.md выпал бы из промпта |
| PROMPT_MVP: append = `.tmp` + `os.replace` | **один `os.write` в O_APPEND-fd + `fsync`** под per-file `threading.Lock`; tmp+`os.replace` — только для rewrite (M-27) | решение пользователя; AC (10 потоков, <4096B atomic, no partial writes) выполняются, кросс-платформенно |
| PROMPT_MVP: `fcntl.flock` | best-effort `fcntl`-flock на POSIX (import-guard), на Windows — no-op | агент-шелл win32; в пределах процесса гонку снимает `threading.Lock` |
| AC «kill -9 посреди append» | тест-эквиваленты: spy = **ровно один `os.write` полным payload** + упавший `os.write` не меняет файл | kill -9 недетерминирован; single-syscall — реальная гарантия all-or-nothing |
| AC «`read_all()` → 4 ключа» | **6 ключов** (= `FILES`) | следует из решения о 6 файлах |
| AC «500 bytes < 1 мс (benchmark)» | бюджет **5 мс** (медиана 20 замеров, warm-up 3) | замерено на этой машине: полный вызов ~3.5 мс, из них `os.open/close` ~2.1 мс (Windows), `fsync` 0.07 мс, JSONL-audit ~1.4 мс — POSIX-субмиллисекунд тут недостижим; compaction-проба в тесте замокана |
| AC «audit — M-27» | audit уже в M-25 | решение пользователя |
| — | memory-блок промпта расширен до LEARNED+PREFERENCES+FACTS+DECISIONS | ARCHITECT6 §3.1.2: блок читает L0-файлы; иначе FACTS/DECISIONS бесполезны |
| — | `.gitignore` + `!app/core/memory/` | паттерн `memory/` (runtime-data) съедал бы пакет-исходник |

## Design (исполнено)

1. **`app/core/memory/models.py`** — `MemoryItem` (frozen dataclass: `kind/text/id/confidence/source/ts`), `create()` (ts = `…Z`, UTC), `to_markdown()` = блок §3.1.1, `parse_entries(content, default_kind=)` (блочный парсер, tolerant к ручной правке: free-form → `source="manual"`; `#`-заголовки пропускаются), `next_id(content, kind)` (монотонные `fact_001`, гапы не переиспользуются), `kind_for(filename)`, `ID_PREFIXES`/`KIND_BY_FILE`.
2. **`app/core/memory/md_store.py`** — `MDStore`:
   - `FILES` (6), `MAX_BYTES` = {LEARNED 4096, PREFERENCES/FACTS/DECISIONS 2048}, `DEFAULT_MAX_BYTES` 8192;
   - `__init__`: `mkdir(parents=True, exist_ok=True)` + `touch()` отсутствующих файлов (**пустые** — промпт-плейсхолдеры ключатся по blank content; существующие никогда не трuncate-ятся);
   - `append(file, content, **kwargs)`: валидация имени (`ValueError`), нормализация `content.rstrip("\n") + "\n\n"`, под per-file `threading.Lock`: `os.open(O_WRONLY|O_APPEND|O_CREAT, 0o600)` → `fcntl.flock` (POSIX) → `os.write` (цикл только на short-write) → `os.fsync` → close; далее `record_memory_op("memory.append", …)` и `_maybe_compact()`;
   - `_maybe_compact()`: при превышении бюджета лог + `loop.create_task(compact_if_needed(...))` (без loop — только warning; сильные refs в `_pending`);
   - `read`/`read_all`/`mtime`/`stats` (`bytes/entries/last_write/max_bytes/over_limit`, entries через `parse_entries(default_kind=kind_for(name))` — ручные записи тоже считаются);
   - `async compact_if_needed()` — **stub M-25**: `True` если > бюджета, без переписывания (реальная compaction = M-27); `needs_compaction()`, `max_bytes()`;
   - `get_md_store(memory_dir=None)` — кэш по пути (`_STORES` + guard), паттерн `get_cache`.
3. **`app/core/memory/audit.py`** — `record_memory_op(action, file, preview, *, reason, session_id, actor, memory_dir)` (никогда не raised; loop → task → `get_pool_if_created()` → INSERT `(actor, action, file, content_preview, reason, session_id)`, иначе JSONL `{memory_dir}/audit/memory_audit.jsonl`), `drain_memory_audits()` (зеркало `drain_incidents`), `AUDIT_PREVIEW_CHARS=200`.
4. **`app/core/memory/__init__.py`** — re-export `MDStore`, `MemoryItem`, `parse_entries`, `next_id`, `kind_for`, `get_md_store`, `record_memory_op`, `drain_memory_audits`, `FILES`/`MAX_BYTES`/`DEFAULT_MAX_BYTES`/`MEMORY_AUDIT_FILENAME`.
5. **`app/core/prompt.py`** — `_read_memory_file` → `_memory_store()` (`get_md_store`); `project_context_block`: placeholder по blank content; `format_memory_block`: секции LEARNED/PREFERENCES/FACTS/DECISIONS, `(empty)` по blank, 8 KB-cap и сигнатуры не тронуты.
6. **`.gitignore`** — `!app/core/memory/` после `memory/`.

## Result (файлы)

- Созданы: `app/core/memory/{__init__,models,md_store,audit}.py`, `tests/unit/test_md_store.py` (21), `tests/unit/test_memory_models.py` (9).
- Изменены: `app/core/prompt.py`, `tests/unit/test_prompt.py` (+3, `(empty)`×4), `README.md` (секция «Long-term memory (M-25)», пункт 4 промпта, дерево, Phase Progress ✅ M-25), `AGENTS.md` (архитектурная строка `app/core/memory/` + конвенция по memory), `.gitignore`.

## Verified

- `uv run ruff format .` → `uv run ruff check .` → `uv run ruff format --check .` — чисто.
- `uv run pytest -q` — **583 passed, 20 skipped** (20 = прежние условные: `rg`-тесты + live-provider + Postgres), 93 s.
- AC-трейс M-25: конструктор → dir + 6 пустых файлов (+не-truncate существующих); append в конец + fsync (spy); ровно один `os.write` полным payload; упавший write не меняет файл; 10 потоков × 10 = 100 записей без потерь; `read_all()` = 6 ключей; `stats()` (bytes/entries/last_write Z/бюджеты); benchmark-медиана в пределах 5 ms; превышение бюджета → `compact_if_needed` запланирован (async), под бюджетом — нет; `compact_if_needed` — недеструктивный stub; `ValueError` на чужое имя; audit: JSONL без loop, INSERT при pool (проверка аргументов), JSONL-фолбэк без pool, упавший INSERT не ломает append; `get_md_store` идемпотентен.
- Prompt: 6 секций промпта на месте, префикс-порядок сохранён, `(empty)`×4, FACTS/DECISIONS инжектируются, запись через `MDStore.append` видна в `format_memory_block` (контракт M-26), все прежние тесты прошли без правок, кроме ожидаемого `(empty)`-счётчика.

## Follow-up

- **M-26** `/learn`: `MemoryItem.create` → `next_id(store.read(...))` → `store.append(..., session_id=...)`, refresh `format_memory_block` на следующем turn.
- **M-27** Compactor: реальный `compact_if_needed` (partition по confidence/source → L1 outbox), `POST /memory/compact` + `GET /memory/stats`, audit `memory.compact`.
- B-21 `SQLiteStore` (L1) и L2 Qdrant — расширение того же seam, MDStore не меняется.
- При желании: POSIX-бюджет 1 мс зафиксировать отдельным linux-тестом (сейчас 5 ms из-за win32 `os.open`).
