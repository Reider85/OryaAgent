# Plan: M-23 — Token-efficient output (фиксация общей стратегии)

**Status:** executed
**Commit message:** `M-23: token-efficiency contract tests + >=30% token-count savings AC` + `M-23: README (M-22+M-23 phase progress, token-efficient section) + PROMPT_MVP strategy sync` + `M-23: executed ticket plan`
**Spec:** `analytics/PROMPT_MVP.md` §3.3 (M-23-строчки M-10/M-11) + BACKLOG5 M-23 + ARCHITECT5 §6.4 / улучшение #4 (ТРИЗ #28)

**User decisions (утверждены до исполнения):**
1. Scope = **только тесты + доки** — production-код уже соответствует стратегии (реализовано в M-10/M-11); рефакторинг общего render-хелпера отклонён.
2. README: backfill **M-22 + M-23** в Phase Progress/intro-список (коммит M-22 доки не обновил).
3. Коммиты — поэтапно, по конвенции репозитория.

## Context

- Стратегия закреплена предыдущими тикетами: bash → JSON + dedup ≥100 identical + char-truncate 5000 (`app/tools/bash.py`), grep/glob → compact JSON + cap 500 (`app/tools/search.py`), read → line-numbered окно 2000 строк + маркеры (10 MB cap), write/edit → компакт-строки; второй слой — `truncate_tool_messages()` в `app/core/context.py` (помечен M-23).
- Не хватало верификации: AC1 (контракт «все 6 tools отдают compact-structured output») был размазан по `test_tools.py`/`test_smoke.py`; AC2 (token-count «до/после» ≥30%) не существовал вовсе.
- PROMPT_MVP всё ещё описывал устаревшую формулировку M-23 (10K chars + `{summary, stdout_head, stderr_tail}`, max 50, ключ `match`) — superseded формами BACKLOG5 по планам M-10/M-11.

## Deviations from spec (deliberate, planned)

| Spec says | Done | Why |
|---|---|---|
| PROMPT_MVP: bash >10K → `{summary, stdout_head, stderr_tail}` | в доках/тестах BACKLOG5-форма: 5000 chars, `{stdout, stderr, exit_code, duration_ms, truncated}`, head 2500 + tail 2500 | M-10-plan precedent (BACKLOG5 новее); smoke-тест фиксирует точный key-set |
| PROMPT_MVP: grep max 50, ключ `match` | 500 (`max_matches` configurable), ключ `content` | M-11-plan precedent |
| AC2 «типичные tool-results» — не specified | 5 фикстур: repetitive-log 500 строк, unique-log 400 строк, grep 2000 матчей, glob 2000 путей, файл 5000 строк + агрегат | воспроизводимо, маржа ≥30% на каждой (55.9–99.2%) |
| «до» — что считать baseline | вывод без M-23-механизмов: raw bash-стримы, сырые `rg --json`-события (BACKLOG4 M-11 passthrough), uncapped-пути, полный файл | измеряет именно вклад M-23, не v4-референс-код |
| Token-counter — какой | `count_tokens([...], model=None)` → chars/4: детерминированно, без сети tiktoken | `context.py`: «±10% acceptable for MVP» |

## Design (исполнено)

1. **`tests/unit/test_token_efficiency.py`** (new, 12 тестов):
   - autouse `_isolated_env` — паттерн `test_tools.py` (delenv `ORYA_*`, `chdir(tmp_path)`, `clear_settings_cache()`, `MemoryCache` до/после);
   - моки: `app.tools.bash._execute_subprocess` (команда не выполняется) и `app.tools.search._run_rg` (mode-aware grep/glob) — оба через `importlib.import_module`, т.к. пакет `app.tools` затирает атрибут `bash` тулом;
   - **AC1 (6 tests):** write → `^Wrote \d+ bytes to .+`; edit → `^Edited .+: replaced \d+ occurrence\(s\)$`; read → line-numbered + untrusted-маркеры; bash → JSON key-set ровно 5 ключей + типы; grep → `{matches, count, truncated}` + per-match `{file, line, content}`; glob → `{files, count, truncated}`;
   - **AC2 (6 tests):** каждая пара «до/после» assert ≥30% + агрегат ≥30%; проверяются и включательные маркеры механизма (`... [500 identical lines] ...`, `chars truncated`, `truncated: lines 2001-5000 hidden`, `count == 500`, `truncated is True`).
2. **`README.md`** — секция «Token-efficient output (M-23)» (таблица контрактов 6 tools + второй слой, числа экономии); Phase Progress: ✅ M-22 (backfill) + ✅ M-23; intro-список тикетов продлён до M-23.
3. **`analytics/PROMPT_MVP.md`** — M-23-строчки M-10/M-11 приведены к исполненной форме (JSON-ключи, 5000/2500+2500, dedup ≥100, max 500, ключ `content`).
4. Production-код **не изменялся**.

## Result (файлы)

- Созданы: `tests/unit/test_token_efficiency.py` (334 строки, 12 тестов), `.opencode/plans/M-23-token-efficient-output.md` (этот файл).
- Изменены: `README.md`, `analytics/PROMPT_MVP.md`.

## Verified

- `uv run ruff format .` → `uv run ruff check .` → `uv run ruff format --check .` — чисто (175 files formatted).
- `uv run pytest -q` — **501 passed, 20 skipped** (скипы прежние: `rg` на PATH + infra), включая 12 новых M-23-тестов; сам файл: **12 passed in ~1.2s**.
- Замеры экономии (chars/4, те же фикстуры, что в тестах):

  | Fixture | до | после | saved |
  |---|---|---|---|
  | bash repetitive (500 identical lines) | 4 749 | 40 | **99.2%** |
  | bash long (400 unique lines → truncate) | 5 199 | 1 314 | **74.7%** |
  | grep 2000 → 500 matches (raw `rg --json` vs compact JSON) | 89 614 | 15 719 | **82.5%** |
  | glob 2000 → 500 paths | 14 999 | 4 148 | **72.3%** |
  | read 5000 lines → 2000 window | 57 222 | 25 251 | **55.9%** |
  | **aggregate (AC2)** | **171 783** | **46 472** | **72.9%** (порог 30%) |

- AC-трейс: AC1 — 6 контракт-тестов (по одному на tool); AC2 — 5 per-fixture + 1 aggregate, все ≥30%; PROMPT_MVP-формулировки сверены с кодом; README-секция фиксирует контракты для людей.
- Полный прогон показал, что док-правки ничего не сломали; smoke JSON-проверка bash (`test_smoke_bash_echo_returns_json_document`) прошла без изменений.

## Follow-up

- **M-19** (README + cross-links): секция M-23 уже есть; M-19 при своей реализации добавит ссылки на ARCHITECT5/ROADMAP5/BACKLOG5.
- **M-18**: BACKLOG5-зависимость `M-20..M-23` закрыта — smoke-тесты расширять не требовалось.
- **A-15/ALPHA**: если появится настоящий LLM-tokenizer для подсчёта — заменить chars/4 в тестах на него (сейчас детерминизм важнее точности).
- Тест намеренно мока subprocess-слои bash/rg: e2e-путь с реальными процессами покрыт `tests/unit/test_tools.py` и `tests/integration/test_tools_integration.py`.
