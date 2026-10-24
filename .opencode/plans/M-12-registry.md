# Plan: M-12 — Tool-registry integration

**Status:** executed
**Commit message:** `M-12: tool-registry integration (6-tool AC fix, full-cycle graph e2e, integration tests, offline bind_tools schema check)`

## Deviations from spec (deliberate, documented)

| Spec says | Done | Why |
|---|---|---|
| BACKLOG4: `get_registered_tools()` в `app/tools/__init__.py` | `get_tools()` в `app/core/tools.py` | PROMPT_MVP §3.3/§4 — фазовый документ (precedent M-07/M-09); шов живёт в core, `app/tools/__init__.py` реэкспортирует tool-объекты |
| BACKLOG4: `.bind_tools()` в `get_llm()`/`get_chat_model()` | bind в `graph.py::_bind_tools` (M-07) | LLM-seam (M-01) не знает о tools — Forbidden §9; модель конструируется один раз, биндится per-graph |
| BACKLOG4: `get_registered_tools()` возвращает 5 tools | `get_tools()` → **6** tools (`[read, write, edit, bash, grep, glob])` | M-11 precedent (glob отдельный tool); AC в PROMPT_MVP обновлён на 6 (§1, §3.3, §6, §9-демо) — follow-up из M-11-plan |
| AC: `model.ainvoke("read README.md")` → ToolCall (реальный LLM, сеть) | fake-model graph-e2e + офлайн-bind реальной моделью через `get_llm()` | CI без API-ключей; тесты не ходят в сеть (construct — network-free по docstring `get_llm`) |
| AC: session_id-фильтрация | параметр зарезервирован (`del session_id`), список глобальный | MVP не имеет per-session tool-config; v7 BETA — `CapabilityRegistry.filter(tools, context)` (инвариант #3) |
| BACKLOG5: «M-12 включает CacheWrapper из M-21» | Не в этом тикете | Кэш-сема (M-07) уже в `app/core/cache.py`; pre-search кэш + write-hook — работа M-21 (M-11-plan: follow-up для M-12 = только AC на 6 tools) |

## Result

- `tests/integration/test_tools_integration.py` (new, BACKLOG4-suggested path) — 5 тестов:
  - registry contract: `get_tools()` → ровно 6 `BaseTool` в порядке `[read, write, edit, bash, grep, glob]`, непустые descriptions, input-schema на каждый tool;
  - каждый tool сериализуется в валидную OpenAI-function-схему (`convert_to_openai_function`) с корректными `required` (`path`/`content`/`old_string`/`command`/`pattern`);
  - **full-cycle e2e** (AC BACKLOG4): один разговор через `build_graph(get_tools(), model)` — `write → read → edit → bash → grep → glob → final answer`; ассертит реальные побочные эффекты (файл изменён, read видит pre-edit контент, bash/grep/glob — структурированный JSON);
  - **офлайн-bind реальной моделью**: `get_llm("deepseek", "deepseek-chat", api_key=...)` (construct без сети) → `bind_tools(get_tools())` → все 6 схем в `bound.kwargs["tools"]` + `build_graph` собирается.
- `tests/unit/test_tools.py` — +1 тест: `test_graph_executes_glob_tool_end_to_end` (mock rg; паритет с e2e остальных 5 tools); секция registry перекачёвана «partial M-12» → «M-12».
- `app/core/tools.py` — docstring: M-12 завершён (six-tool list покрыт integration-тестами); `session_id` зарезервирован под per-session filtering (M-13+/v7 BETA).
- `analytics/PROMPT_MVP.md` — AC обновлён 5→6 tools в 5 местах: §1 (goals), §3.3 (M-12 ticket), §6 (DoD), §9 (демо недели 2, demo checklist).
- README — intro-список тикетов расширен до M-12; Phase Progress: ✅ M-12.
- `.opencode/plans/M-12-registry.md` — этот файл.

## Verified

- `uv run pytest tests/integration/test_tools_integration.py` — 5 passed.
- `make lint` (ruff check + format --check) + полный `make test` — см. ниже.

## Follow-up

- **M-21 (CacheWrapper):** pre-search кэш для grep/glob требует write-hook (инвалидация без запуска rg) — сейчас кэшируется только post-search (ключ по max-mtime matched files).
- **M-13 (permissions):** `interrupt_before` на `write`/`edit`/`bash` из того же реестра; glob — всегда ALLOW (read-only).
- **v7 BETA:** `CapabilityRegistry.filter(tools, context)` поверх `get_tools()` (инвариант #3 не меняется).
