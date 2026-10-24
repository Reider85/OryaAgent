# Plan: M-13 — Permissions (interrupt-driven ask + policy)

**Status:** executed
**Commit message:** `M-13: permissions (PermissionPolicy, allow/deny rules, interrupt-driven ask)` (`9015929`)
**User decisions:** доверстка (README + план) поверх уже закоммиченного кода; README-секция «Permissions (M-13)» с примером YAML.

## Deviations from spec (deliberate, documented)

| Spec says | Done | Why |
|---|---|---|
| BACKLOG4: `compile(interrupt_before=['tools'] if policy.ask_mode else [])` | Динамический `interrupt()` внутри `human`-node (`build_human_node`), маршрут `agent → human → tools \| agent` | Статический `interrupt_before` паузил бы каждый вызов tools; динамическая пауза — только при `ask` (allow-rules/session-allowlist проходят без prompt'а). AC PROMPT_MVP (§3.4) требует «interrupt на write/edit/bash», а не на каждый tools-вызов |
| BACKLOG4: `policy.review(tool_calls) -> Decision`, `mode: ask\|auto` | `check(tool_call, session_state) -> Decision` per-call + `record_session_allow(tool)`; modes `strict\|permissive` | PROMPT_MVP §3.4/§3.2 (`permission_policy: strict\|permissive`) — фазовый документ (precedent M-07/M-12); per-call check даёт batch-семантику: один refuse — отказ всего батча |
| BACKLOG4: DENY → `ToolMessage("Denied by user")` | Три причины: `Denied by policy: {reason}` (rule), `Denied by user` (resume deny), `Denied: another call in this batch was refused`; ровно один `ToolMessage` на каждый tool-call id | Провайдеры (OpenAI/Anthropic) десинхронизируют историю при частичном батче; раздельные причины — диагностика в UI (M-16) |
| PROMPT_MVP: allow_rules + два mode | + built-in deny-list (ADR-004: `rm -rf /`, fork bomb, `dd` на диск, `mkfs`, piped remote script) и session allowlist; deny-wins над session | ADR-004 `analytics/spec/ADR-004-permissions-default-ask.md` — deny-list обязателен, иначе «don't ask again» делает `rm -rf /` без prompt'а |
| BACKLOG4 allow-rule `bash: ls *` | Anchored regexes (`^ls(\s+|$).*`, `^git\s+(status\|diff\|log\|branch)...`), `re.search` c `^`/`$` | Forbidden patterns BACKLOG4: unanchored `re.match` матчит «echo ls» как «ls» — тест `test_allow_list_is_anchored` |
| BACKLOG4 YAML: `mode`, `allow:` | `allow_rules:` / `deny_rules:` в `~/.orya/permissions.yml`; mode — только из env/settings (`ORYA_PERMISSION_POLICY`, `Settings.permission_policy`) | Mode — глобальная настройка приложения (config M-02), файл правил — per-user override; ключ-секция пустой списка заменяет built-in (не merge) |
| «interrupt_before hook» (PROMPT_MVP M-04 §3.1) без деталей | Без checkpointer — `ask` → deny (fail-closed), лог + `Denied: permission prompting unavailable` | `interrupt()` требует checkpointer; silent-allow деструктивного вызова недопустим |

## Result

- `app/core/permissions.py` (new) — `Rule` (compiled regex, wildcard tool `*`), `PermissionConfig` (defaults + YAML load с degradation на invalid entries), `PermissionPolicy` (`check` / `should_interrupt` / `record_session_allow`), `get_policy()` entry-point; trusted-команды `learn`, `memory/*` (PROMPT_MVP §3.4).
- `app/core/graph.py` — `PolicyLike`/`DecisionLike` протоколы, `route_after_agent` → `human` при наличии policy, `build_human_node` (interrupt-driven ask, batch-refusal, fail-closed), `resume_command("approve"|"deny"|"always")`; `_APPROVE_STRINGS` — unknown → deny.
- `app/core/config.py` — `permission_policy: Literal["strict","permissive"]`, `permissions_path` (default `~/.orya/permissions.yml`, tilde-expansion); `.env.example`: `ORYA_PERMISSION_POLICY`.
- `tests/unit/test_permissions.py` (new, 53 tests) — mode matrix, anchored allow-list, deny-wins, trusted-команды, session-allowlist, YAML-loading edge cases (invalid regex, non-mapping, per-section replace).
- `tests/unit/test_graph.py` (+350 lines) — human-node unit-тесты + e2e с реальным `PermissionPolicy` + `InMemorySaver`: approve исполняет, deny — отказ без исполнения, read без паузы, deny-rule без interrupt, `always` в session-allowlist, unknown-answer fail-closed.
- `tests/integration/test_graph_postgres.py` — ask-policy поверх реального `AsyncPostgresSaver`: пауза → `resume_command("approve")` → продолжение.
- `README.md` (доверстка) — intro-список тикетов + Phase Progress: ✅ M-13; секция «Permissions (M-13)»: precedence deny→session→allow→mode, trusted-команды, batch-семантика, fail-closed, пример `~/.orya/permissions.yml`.
- `.opencode/plans/M-13-permissions.md` — этот файл.

## Verified

- `uv run pytest tests/unit/test_permissions.py tests/unit/test_graph.py -q` — **78 passed**.
- Полный `uv run pytest -q` — **306 passed, 16 skipped** (integration: PostgreSQL/API-ключи недоступны — skip-норма M-05…M-12).
- `uv run ruff check .` + `uv run ruff format --check .` — чисто.

## Follow-up

- **M-16 (UI interrupt):** Chainlit ask-prompt «Tool `{tool}` wants to run with args: `{args}`» → кнопки Approve / Deny / Approve & don't ask again → `resume_command("approve"|"deny"|"always")`.
- **M-17 (sidebar/settings):** dropdown permission-policy в settings (сейчас только env/`Settings`).
- **M-20 (/sessions):** endpoint resume для interrupted-run (`POST /sessions/{id}/resume`) — внешним клиентам нужен тот же `resume_command`-контракт.
- **v7 BETA:** LSP-rename safety-check — дополнительный deny-rule поверх того же `check()`-шва (инвариант не меняется).
