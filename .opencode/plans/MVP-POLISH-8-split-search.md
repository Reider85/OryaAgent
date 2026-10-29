# Plan: MVP-POLISH-8 — Split app/tools/search.py into grep.py + glob.py

**Status:** executed
**Commit message:** `MVP-POLISH-8: split app/tools/search.py into grep.py + glob.py (shared _rg seam)`
**User decisions:** разделить код (не обновлять spec); PROMPT_MVP.md уже соответствует (§3.3 M-11 + §10 дерево файлов) — spec не тронут. Реверс осознанного отклонения M-11 (`.opencode/plans/M-11-search.md`: единый `search.py` chosen because BACKLOG4/5 ссылались на `search.py`).

## Problem

- `PROMPT_MVP.md` (канонический spec, AGENTS.md)expects `app/tools/grep.py` + `app/tools/glob.py` (§3.3 M-11 строки 296-297, §10 дерево 587-588); код держал оба tool в одном 389-строчном `app/tools/search.py`.
- Репо-конвенция: один tool — один файл (`read.py`, `write.py`, `edit.py`, `bash.py`); AGENTS.md «Adding a tool = `app/tools/<name>.py`».
- MVP-POLISH.md #8: «Split app/tools/search.py into grep.py + glob.py (or update spec §10)» — выбран split.

## Result

| Файл | Что |
|---|---|
| `app/tools/_rg.py` (new, private; precedent `_validators.py`) | Общий seam: `RG_TIMEOUT`, `DEFAULT_MAX_MATCHES`, `_run_rg_sync` (Popen + watchdog + rg-not-found), `_run_rg` async wrapper (mock-точка), `_max_mtime_ns`, `_render` |
| `app/tools/grep.py` (new) | `@tool grep` + grep-only `_build_rg_argv`, `_parse_match_events`; import shared из `_rg` |
| `app/tools/glob.py` (new) | `@tool glob` (argv inline, как раньше) |
| `app/tools/search.py` | удалён |
| `app/tools/__init__.py`, `app/core/tools.py` | imports → `from app.tools.glob import glob` / `from app.tools.grep import grep`; `get_tools()` список неизменен `[read, write, edit, bash, grep, glob]` |

Контракты, cache keys (`"grep"`/`"glob"`), untrusted framing, injection detection, exit-code mapping — перенесены без изменений (pure file move).

### Тесты (4 файла; seam-моки)

Python gotcha: `__init__.py` re-bind'ит `glob`/`grep` на tool-объекты, затеняя submodules → тесты грузят модули через `importlib.import_module` (прецедент `test_token_efficiency.py`).

- `tests/unit/test_tools.py`: -`from app.tools import search as search_module`; +`glob_module`/`grep_module`/`rg_module` via importlib; `_mock_rg` патчит `_run_rg` на обоих tool-модулях; `test_rg_not_found...` патчит `rg_module.shutil.which`.
- `tests/integration/test_tools_integration.py`: importlib `glob`+`grep` модули; full-cycle тест патчит оба seam'а.
- `tests/smoke/test_smoke.py`: importlib `grep` модуль; grep-тест патчит его.
- `tests/unit/test_token_efficiency.py`: `_mock_rg` патчит оба модуля одним fake.

Real-rg тесты (skipif без `rg`), `EXPECTED_NAMES` — без изменений.

## Verified

- `uv run ruff format .` → `uv run ruff check .` + `uv run ruff format --check .` — чисто.
- `uv run pytest tests/unit tests/integration tests/smoke` — **758 passed, 24 skipped** (0 failures; skip = условные: Postgres/Redis/live-providers без инфры + 3 real-rg теста без rg в PATH).
