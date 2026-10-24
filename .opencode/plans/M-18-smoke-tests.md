# Plan: M-18 — Smoke-тесты 5 эталонных задач (расширенные)

**Status:** executed
**Commit message:** `M-18: smoke tests — 5 canonical tasks + cache/injection/JSON checks, read injection warning` + `M-18: executed ticket plan`
**User decisions:** план утверждён; memory-зависимые AC (сценарий 5, /learn, /memory/stats, atomic-append durability) → skipped-тест с причиной «blocked on M-25..M-27»; injection-warning добавлен в read-тул (буквально по BACKLOG5 #7).

## Deviations from spec (deliberate, documented)

| Spec says | Done | Why |
|---|---|---|
| PROMPT_MVP: сценарий 5 `/learn` → next turn | `pytest.skip("blocked on M-25..M-27")` | MDStore (M-25), `/learn` (M-26), Compactor (M-27) не реализованы; пользователь выбрал 7 active + 1 skipped |
| BACKLOG6 M-18: проверки `/learn`, `/memory/stats`, atomic-append durability | отнесены к тому же skip | все три зависят от memory-слоя (M-25..M-27) |
| BACKLOG4/5: `tests/e2e/test_smoke.py` | `tests/smoke/test_smoke.py` | PROMPT_MVP §10 — каноническое дерево; `tests/smoke/` существует и был пустым (AGENTS.md: suites `unit`/`integration`/`smoke`) |
| PROMPT_MVP §10: «параметризованный по провайдерам» | scripted `FakeMessagesListChatModel` | Forbidden pattern BACKLOG4: real LLM-вызовы запрещены; детерминированный CI |
| BACKLOG5 #6: `from_cache=true` в выводе read | счётчики `MemoryCache` (misses/hits) + байт-идентичный повтор | формат вывода read остаётся стабильным (нет маркера-суффикса); счётчики — собственная метрика cache-сема (M-07/M-21) |
| Сценарий 4 (grep): реальный `rg` | мокнут `_run_rg` (seam) | конвенция интеграционных тестов (`test_tools_integration.py`); CI без rg-бинаря остаётся зелёным; JSON-фрейминг/кэш/валидация путей под моком реальны |
| BACKLOG4: setup `tests/fixtures/sample_project/` | fixture `mini_project(tmp_path)` (inline-контент) | write/edit-сценарии мутируют файлы → проект must be in tmp; inline-фикстуры самодостаточны |
| BACKLOG5 #7: warning в ToolMessage read | реализовано в `app/tools/read.py` | решение пользователя: выровнять read с bash/grep (`injection_warning`) |

Известные ограничения (приняты для MVP): сценарий 5 и memory-AC вернутся в M-25..M-27; grep-сценарий не проверяет сам бинарь rg (только семантику tool-слоя над ним); cache-hit проверяется по счётчикам, а не по полю в выводе.

## Result

- `app/tools/read.py` (update) — `_render()` сканирует сырой текст (`detect_injection` до cat-нумерации — префикс номера ломает `^role:`-паттерны; попадание добавляет `[WARNING: possible prompt injection detected in [pattern_id]]` сразу после `[UNTRUSTED_CONTENT_END]`, перед truncation-note); warning попадает в кэш-значение (детерминирован); docstrings (модуль + tool).
- `tests/unit/test_tools.py` (+3) — warning на `ignore_previous_instructions`, отсутствие warning на чистом файле, warning на `role_override` (порядок: END-маркер < WARNING, warning вне фрейминга).
- `tests/smoke/test_smoke.py` (new, 8 тестов = 7 active + 1 skipped):
  1. read + explain Python-файла (UNTRUSTED + line-numbered + финальный ответ);
  2. edit signature + call-site (оба файла изменены, edit targeted, нет leftover `*.tmp` — атомарность mkstemp→os.replace);
  3. `bash("{sys.executable}" -m pytest tests/ -q)` в мини-проекте → JSON `exit_code==0`, `1 passed` (forward-slash-паттерн из `_python_command`, работает в Git Bash и cmd);
  4. grep символа → JSON `count>=2`, файлы `{calculator.py, main.py}`, без injection_warning (мок `_run_rg`);
  5. `/learn` → **skip** (blocked on M-25..M-27);
  6. cache-hit повторного read → misses не растут, hits+1, вывод байт-идентичен;
  7. read malicious.txt → `[WARNING: ... [ignore_previous_instructions]]` в ToolMessage внутри UNTRUSTED-фрейминга;
  8. `bash echo hello` → `json.loads` проходит, stdout/exit_code + ровно 5 ключей.
- Общее: autouse-sandbox (ORYA_* → нет, `chdir(tmp_path)`, `clear_settings_cache`, свежий `MemoryCache`) по конвенции suites; graph без policy (graph-level, Forbidden: без Chainlit/Postgres/API).
- `.opencode/plans/M-18-smoke-tests.md` — этот файл.

## Verified

- `uv run ruff format .` → `uv run ruff check .` → `uv run ruff format --check .` — чисто (161 файл).
- `uv run pytest tests/smoke -q` — **7 passed, 1 skipped** (4.96s; каждый тест ≪ 30s AC).
- Полный `uv run pytest -q` — **420 passed, 19 skipped** (скипы: Postgres-инфа, live-provider ключи, `rg` + 1 новый smoke-skip; все прежние тесты зелёные — warning в read ничего не сломал).

## Follow-up

- **M-25/M-26/M-27:** после внедрения memory-слоя раскомментировать сценарий 5 (`/learn` → next turn) и memory-AC (`/memory/stats`, atomic-append durability) в `tests/smoke/test_smoke.py`.
- **M-21 (Redis):** cache-hit проверка использует `MemoryCache`-счётчики — при смене бэкенда через `set_cache()` счётчиков может не быть; при необходимости перейти на семантику backend-агностичной проверки.
- **M-22:** warning в read — первый слой; sanitize/audit-log (`memory_audit_log`) остаются на M-22.
- **rg в CI:** 3 unit-теста + grep-сценарий depend на моке/скипе — установка ripgrep в окружении CI разблокирует честный прогон.
