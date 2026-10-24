# Plan: M-11 — Tool: grep/glob (ripgrep, token-efficient JSON)

**Status:** executed
**Commit message:** `M-11: tool grep/glob (rg --json, JSON token-efficient output, injection detection, cache seam, registry)`

## Deviations from spec (deliberate, documented)

| Spec says | Done | Why |
|---|---|---|
| PROMPT_MVP: файлы `grep.py`+`glob.py`; BACKLOG4/5: `app/tools/search.py` | `app/tools/search.py` — единый модуль с обоими tool | Выбор пользователя (оба бэклога ссылаются на `search.py`) |
| PROMPT_MVP: max **50** matches; BACKLOG4/5: max **500** | 500 (`DEFAULT_MAX_MATCHES`), configurable параметром `max_matches` | Precedent M-10: bash взял BACKLOG5-лимит (5000 chars), не PROMPT_MVP (10K); BACKLOG5 — более новый слой (v5) |
| PROMPT_MVP: `{"file","line","match"}`; BACKLOG5/ARCHITECT5: `{"file","line","content"}` | `content` | BACKLOG5/ARCHITECT5 согласованы; M-10 тоже следовал BACKLOG5-форме |
| PROMPT_MVP: `-> list[dict]` (grep) / `-> list[str]` (glob) | JSON-**строка** `{"matches":[...],"count","truncated"}` / `{"files":[...],"count","truncated"}` внутри `[UNTRUSTED_CONTENT_START/END]` | Конвенция M-07..M-10: tool возвращает `str`; untrusted-framing обязателен (M-22); обёртка одинакова с bash (M-10) |
| PROMPT_MVP: `grep(pattern, path, glob_pattern="*")`; BACKLOG4: `GrepInput(pattern, glob, path, type)` | `grep(pattern, glob=None, path=".", type=None, max_matches=500)` — Annotated-args, без args_schema | Конвенция M-07..M-10 (Annotated); BACKLOG4-имена параметров (`glob`, `type`) |
| PROMPT_MVP: glob отдельный tool; M-12-реестр: ровно 5 tools `[read,write,edit,bash,grep]` | Реализованы grep + glob; `get_tools()` → **6 tools** (grep, glob зарегистрированы) | PROMPT_MVP — фазовый документ (precedent M-09); glob — read-only safe (M-13 всегда ALLOW); список M-12 «5 tools» устарел — **M-12 должен обновить AC на 6 tools** |
| «Интеграция с CacheWrapper» без деталей ключа | Кэш только при ≥1 match: `build_cache_key("grep"/"glob", args, max_mtime_ns по matched files)`; пустой результат не кэшируется | mtime-инвалидация как у read (M-21); rg всегда выполняется (результат — источник invalidation-key); pre-search кэш требует write-hook из M-12 |
| BACKLOG4: `rg --json --line-number --with-filename` | `rg --no-config --json` (grep) / `rg --no-config --files --glob` (glob) | `--json` уже содержит path+line_number; `--no-config` гарантирует детерминизм (игнор ~/.ripgreprc) |
| PROMPT_MVP: «Использует ripgrep (subprocess)» — без fallback | Без Python-fallback (Forbidden: «только rg subprocess»); rg не найден → `ToolException("ripgrep (rg) not found in PATH...")` | Forbidden-паттерн; bash-прецедент fail-fast |
| Timeout/kill не специцированы для grep | `RG_TIMEOUT=30s` watchdog (`threading.Timer` + kill); truncation kill при cap; subprocess в `asyncio.to_thread` | Консистентно с M-10 (kill при timeout/cancel) |

## Result

- `app/tools/search.py` — `_run_rg` seam (`asyncio.to_thread` + `Popen`, argv-list, no shell) + `@tool grep(pattern, glob, path, type, max_matches)`: validate_path, пустой pattern/max_matches<1 → ToolException, `--` separator (pattern с `-` не инжектит флаги), парсинг `rg --json` match-events → `{"file","line","content"}`, cap `max_matches` с `truncated`, exit 1 = no matches (не ошибка), exit 2 = ToolException со stderr, injection detection по консолидированному content → `injection_warning` (как bash), wrap_untrusted, cache по max-mtime matched files. `@tool glob(pattern, path, max_matches)`: `rg --files --glob {pattern}` (positionals у `--files` — пути, поэтому glob строится явно, не через `_build_rg_argv`), аналогичный cap/truncation/cache/wrap.
- `app/tools/__init__.py` / `app/core/tools.py` — `grep`, `glob` экспортированы и зарегистрированы: `get_tools()` → `[read, write, edit, bash, grep, glob]`.
- `tests/unit/test_tools.py` — +23 теста (118 в файле): JSON-структура+маркеры, argv (glob/type/`--`/leading-dash), пустой pattern, max_matches<1, path escape (grep+glob), truncation (grep+glob), exit 1 → empty, exit 2 → ToolException, truncated-kill skips error, injection warning, cache hit + mtime-invalidation, glob JSON+argv, glob empty pattern, rg-not-found, graph e2e grep, 4 real-rg теста (skipif `rg` отсутствует; проверены с временно скачанным rg 14.1.1 — 3 passed + real glob). Registry/bind_tools assert'ы обновлены на 6-tool список.
- README: M-11 ✅ в Phase Progress (M-10 уже был) + intro-список тикетов расширён до M-11.
- Verified: **238 unit tests green** (включая 4 real-rg с временным rg в PATH), `ruff check` + `ruff format --check` чистые; smoke реального grep/glob по репозиторию — корректный JSON.

## Follow-up for M-12

- Обновить AC M-12: `get_registered_tools()` теперь возвращает **6** tools (`[read, write, edit, bash, grep, glob]`), не 5.
