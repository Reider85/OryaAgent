# Plan: M-16 — Chainlit UI: ask-prompt для interrupt

**Status:** executed
**Commit message:** `M-16: permission ask-prompt (AskActionMessage, resume streaming, approve/deny/always)` + `M-16: executed ticket plan`
**User decisions:** план утверждён (PROMPT_MVP §3.5 как фазовый источник; M-15 предварительно закоммичен отдельно — `4d90f13`, `c984440`).

## Deviations from spec (deliberate, documented)

| Spec says | Done | Why |
|---|---|---|
| PROMPT_MVP: `ask_permission(tool_name, args) -> bool` | `ask_permission(pending, *, ask=None) -> str` (`approve`\|`deny`\|`always`); `PendingInterrupt(tool, args, reason)` | Три кнопки (см. ниже) не сводятся к bool; строковый контракт — `resume_command` из M-13; payload несет ещё `reason` из `Decision` (M-13-диагностика для UI) |
| PROMPT_MVP: только `app/ui/interrupt.py` | + `resume_graph_events` / `_stream_normalized` / `_render_run` / interrupt-цикл в `chainlit_app.py` | deny ⇒ human-узел продолжает к agent — финальный ответ обязан стримиться; resume через тот же normalized-event шов, что и обычный ход |
| BACKLOG4: `state.next == ('tools',)` → `last_msg.tool_calls` | `state.next == ('human',)` + payload из `state.tasks[*].interrupts[*].value` | M-13: `interrupt()` внутри human-узла; в langgraph 1.2.16 `__interrupt__` отсутствует в `state.values` при `aget_state` (проверено empirically) |
| BACKLOG5: через FastAPI `/sessions/{id}/resume` | напрямую graph (`resume_command` → `astream_events`) | M-20/M-24 не входят в тикет; прецедент — решение пользователя в M-15 (Chainlit → graph напрямую) |
| BACKLOG4: 2 кнопки Allow/Deny (`resume="allow"\|"deny"`) | 3: Approve / Deny / Approve & don't ask again (`approve`\|`deny`\|`always`) | PROMPT_MVP §3.5 фазовый источник; `"allow"` не входит в `_APPROVE_STRINGS` M-13; `"always"` уже записывает session-allowlist |
| — | таймаут `AskActionMessage` (None) и неизвестная кнопка → deny | fail-closed: тот же контракт, что у `_is_approved` в human-узле (M-13) |
| BACKLOG4: e2e 3 сценария на реальном приложении | `tests/e2e/test_ask_prompt.py`: реальный граф + MemorySaver + ask-политика + scripted model; Chainlit-раунд-trip инжектируется (`ask=`) | хендлеры требуют websocket-контекст (M-15-прецедент: маппинг тестируется без рантайма); все три AC (approve/deny/allow-list) проверяются на реальном interrupt/resume-пути |

Известные ограничения (приняты для MVP): батч из N ask-вызовов прерывается по одному (цикл в `on_message`); `_safe_log` пишет решение permission как role=`system` без tool_call_id; при недоступном payload (чужой interrupt) — hint + пауза (fail-closed, без авто-resume).

## Result

- `app/ui/interrupt.py` (new) — `PendingInterrupt`, `get_pending_interrupt(state)` (чтение `state.tasks[*].interrupts[*].value`), `format_prompt` (PROMPT_MVP-формулировка + optional `Reason:`), `permission_actions` (3 `cl.Action`: approve/deny/always), `normalize_answer` (fail-closed deny), `ask_permission` (`cl.AskActionMessage`; инжектируемый `ask=` для тестов).
- `app/ui/chainlit_app.py` (update) — `_stream_normalized` (общий маппинг событий), `stream_graph_events` (обёртка), `resume_graph_events` (payload = `resume_command(answer)`), `_render_run` (общий рендер-проход: токены + шаги), `on_message`: после обычного хода — цикл `while pending → get_pending_interrupt → ask_permission → resume-стрим → recheck` (батч может прерываться несколько раз); `_INTERRUPT_HINT` — fallback при нечитаемом payload; лог + `log_message(role="system")` на каждое решение.
- `tests/unit/test_interrupt.py` (new, 15 tests) — извлечение payload (tool/args/reason, дефолты, garbage-state), format (wording, reason, cap), normalize (fail-closed матрица), ask_permission (маппинг кнопок, timeout→deny, unknown→deny).
- `tests/unit/test_chainlit_app.py` (+8) — `resume_graph_events` шлёт `Command(resume=...)` того же вида/конфига; `_render_run` (токены+шаги, false без токенов) на фейках без Chainlit-контекста.
- `tests/e2e/test_ask_prompt.py` (new, 3 tests) — реальный `build_graph` + `MemorySaver` + `PermissionPolicy(strict)`: approve → tool_end + финальный токен + `state.next == ()`; deny → без tool_end, `ToolMessage("Denied by user")`, agent отвечает; allow-list → interrupt нет, тул исполняется сразу.
- `.opencode/plans/M-16-permission-ask.md` — этот файл.

## Verified

- `uv run ruff format .` + `uv run ruff check .` + `uv run ruff format --check .` — чисто.
- Полный `uv run pytest -q` — **370 passed, 18 skipped** (скипы: Postgres-инfra, live-provider ключи, `rg`; 26 новых тестов M-16 зелёные).

## Follow-up

- **M-17 (sidebar/settings):** dropdown permission-policy в settings; восстановление paused-run после refresh (сейчас thread_id теряется — paused-сессия недостижима из UI).
- **M-20/M-24:** тот же `ask_permission`/`resume_command`-контракт экспортировать на FastAPI `/sessions/{id}/resume` (SSE-event `interrupt`); UI переключится на SSE без изменения interrupt.py.
- **M-14 follow-up:** логировать tool-шаги в `messages` (role=`tool`) — сейчас permission-решение пишется как system-строка.
