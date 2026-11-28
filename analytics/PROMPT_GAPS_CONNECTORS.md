# ПРОМПТЫ: ЗАКРЫТИЕ ПРОБЕЛОВ СИЛЬНОГО АГЕНТА — OryaAgent v7 (аудит + промпты)

> **Версия документа:** 1.0
> **Дата:** 28 ноября 2026
> **База аудита:** репозиторий `Reider85/OryaAgent` (ветка main, коммит da931a4), файлы `app/mcp/client.py`, `app/mcp/oriahs_mcp.py`, `app/mcp/lsp_mcp.py`, `app/mcp/ukb_mcp.py`, `app/core/lsp/bus.py`, `app/core/lsp/config.py`, `app/tools/` (полный реестр), `app/core/` (структура), `app/api/` (маршруты). Продолжает нумерацию `PROMPT_PRODUCTION.md` (P-00…P-26 + P-27 из Приложения A).
> **Формат:** та же конвенция, что и PROD-промпт: id тикета, Context / Goal / Constraints / Acceptance Criteria / Forbidden patterns / Suggested files, конвенции `AGENTS.md` обязательны (uv, ruff 88, `get_tools()` + `EXPECTED_NAMES`, `validate_path()`, `asyncio.to_thread`, docstring с id тикета, `format → lint → test`).

---

## 0. Резюме аудита: что есть и чего не хватает

### 0.1. Текущее состояние (подтверждено по коду)

| Компонент | Статус в репо | Где |
|---|---|---|
| B-24 DFC | есть | `app/core/dfc/` |
| B-25 Tri-Model | есть | `app/core/workflow/tri_model.py` |
| B-26 LSP-native | есть, **с критическим дефектом транспорта** (см. §1.3) | `app/core/lsp/bus.py`, `app/tools/lsp.py`, `app/mcp/lsp_mcp.py` |
| B-27 UKB, B-28 RetrievalOrchestrator, B-29 CapabilityRegistry | есть | `app/core/ukb/`, `app/core/retrieval/`, `app/core/capability/` |
| MCP-серверы (OriaHS, LSP, UKB) | есть: `mcp.server.Server` SDK + stdio + собственный HTTP-фасад | `app/mcp/oriahs_mcp.py` и др. |
| MCP-клиент | есть, **но это не MCP-протокол** (см. §1.1) | `app/mcp/client.py` |
| ACP (Agent Client Protocol) | **отсутствует полностью** (см. §2) | — |
| PROD-тикети P-20…P-26 (batch, tournament, judge-mcp, memory_search и т.д.) | не реализованы (ожидаемо — репо в BETA) | отсутствуют `app/batch/`, `app/mcp/judge_mcp.py`, `app/tools/memory.py`, `app/core/retrieval/rerank_policy.py` |
| AGENTS.md loader (P-27) | промпт есть в Приложении A, в репо не реализован (`app/core/agents_md/` отсутствует) | — |

### 0.2. Главные пробелы «сильного агента» (кратко)

1. **MCP-клиент — не MCP.** `app/mcp/client.py` говорит по собственному REST-контракту (`GET /health`, `GET /tools`, `POST /call`), а не по протоколу MCP (JSON-RPC 2.0, handshake `initialize`, capabilities, транспорта stdio/SSE/streamable-HTTP). Следствие: агент **не может подключать внешние MCP-серверы** — экосистемный разрыв, главный пробел коннекторов.
2. **ACP отсутствует.** Ни файла, ни упоминания Agent Client Protocol. Агента нельзя вести из Zed/других ACP-редакторов.
3. **LSP-клиент сломан на транспорте.** `bus.py` шлёт JSON с `\n`-делимитером, а LSP требует фрейминг `Content-Length: N\r\n\r\n`. Против реальных серверов (pyright, rust-analyzer, gopls, jdtls, typescript-language-server) клиент не заработает — приёмка B-26, судя по всему, прошла на моках. Плюс: server→client-запросы теряются, push-диагностика не слушается, capabilities не объявлены.
4. **LSP-покрытие языков: 6 из ~30+ популярных.** Нет C/C++ (clangd), C#, Ruby, PHP, Kotlin, Swift, Bash, YAML/JSON/HTML/CSS (при том что `frontend`-конфиг заявляет `.css`/`.html`, которые typescript-language-server не обслуживает) и др. Полная таблица — §3.
5. **Нет web-инструментов** (`web_search`/`web_fetch`) — агент изолирован от интернета.
6. **Нет planning/todo-инструмента и generic-субагентов** (Task-делегирование с изолированным DFC-snapshot) — Tournament (P-23) закрывает только качество исполнения, но не параллельную декомпозицию задач.
7. **Мелочи-ред flags:** глобальный `asyncio.Lock` в `MCPClient.call_tool` сериализует ВСЕ вызовы инструментов; process-wide singleton `_mcp_client_instance` нарушает собственную конвенцию репо (ср. `clear_settings_cache()`); конфиги LSP дублированы в `bus.py` и `config.py` (два источника правды); Redis-«переиспользование» LSP-серверов — заглушка (пишет pid, подключиться к процессу не может).

### 0.3. Порядок реализации новых тикетов

```
P-31 (LSP transport fix) — СНАЧАЛА, блокер для B-26-инвариантов и P-21
P-28 (MCP-compliant client + реестр внешних серверов)
P-29 (MCP hardening: auth + tracing) → зависит от P-28
P-30 (ACP server) — независимо, можно параллельно с P-28
P-32 (LSP expansion: новые серверы + format/organize_imports) → после P-31; нужен ДО P-21 (Symbolic Shortcut требует lsp.format/lsp.organize_imports)
P-33 (web tools) — независимо
P-34 (planning + subagents) — независимо, DFC-snapshot из B-24
```

Суммарная оценка: **~17–19 дней**. Рекомендация: P-31 и P-32 вставить в BETA как hotfix B-26 (до старта PROD), остальные — в начало фазы PROD.

---

## 1. Аудит MCP-коннекторов

### 1.1. Клиент: `app/mcp/client.py` — собственный REST, а не MCP

Фактический контракт: `GET /health`, `GET /tools`, `POST /call {name, arguments}` поверх httpx. Это работоспособный «внутренний RPC», но:

- нет JSON-RPC 2.0 и handshake `initialize`/`initialized`, нет согласования capabilities;
- нет транспорта stdio — невозможно запустить произвольный внешний MCP-сервер (`npx -y @modelcontextprotocol/server-...`);
- нет ресурсов (`resources/list`, `resources/read`), промптов (`prompts/list`) и sampling;
- нет уведомлений `notifications/tools/list_changed` → кэш инструментов протухает молча;
- нет авторизации по спецификации MCP (OAuth 2.1, RFC 9728 metadata);
- нет `MCP-Trace-Id`/`MCP-Span-Id`/W3C `traceparent` — разрыв трассировки на MCP-границе (прямой конфликт с P-19);
- `call_tool` держит **глобальный** `asyncio.Lock` — все MCP-вызовы выстроены в одну очередь;
- `_mcp_client_instance` — process-wide singleton без механизма сброса, вразрез с конвенцией репозитория о кэшах.

### 1.2. Серверы: `oriahs_mcp.py` / `lsp_mcp.py` / `ukb_mcp.py`

Серверы сделаны правильно (официальный `mcp` SDK, `Server`, stdio-транспорт), но основной путь в compose — **кастомный HTTP-фасад** (`create_http_app`), т.е. MCP-протокол end-to-end фактически не используется. `judge_mcp.py` (P-23) отсутствует — входит в PROD.

### 1.3. Вывод

Коннектор MCP реализован «в одну сторону» (свои серверы — свой клиент). Чего не хватает сильному агенту: **универсального MCP-клиента для внешних серверов** с реестром (`mcp.json`), неймспейсингом инструментов, health/degrade, авторизацией и трассировкой. Закрывают тикеты P-28 и P-29.

---

## 2. Аудит ACP-коннектора

ACP (Agent Client Protocol, агент-клиентский протокол, принятый в Zed) в репозитории отсутствует: нет файлов, конфигов, CLI-точки входа. Для код-агента ACP — самый дешёвый способ получить редактор-хост-интеграцию: JSON-RPC поверх stdio, редактор сам даёт FS/терминал/permissions. Реализация — тикет P-30 (OryaAgent как ACP-**сервер**, редактор — клиент). Опционально на FUTURE+: A2A (agent-to-agent) — межагентный протокол, отдельный домен, не путать с ACP.

---

## 3. Аудит LSP: каких серверов и возможностей не хватает

### 3.1. Поддерживается сейчас (bus.py + config.py)

| Язык | Сервер | Комментарий |
|---|---|---|
| Python | `pyright-langserver --stdio` | ок |
| TypeScript | `typescript-language-server --stdio` | ок |
| Rust | `rust-analyzer` | ок |
| Go | `gopls stdio` | ок |
| Java | `jdtls` | ок |
| Lua | `lua-language-server` | ок |
| «frontend» | `typescript-language-server` | **дефект:** заявлены `.tsx/.jsx/.css/.html`, но TS-сервер не обслуживает CSS/HTML — нужны vscode-langservers-extracted |

### 3.2. Недостающие LSP-серверы (рекомендуемые к добавлению)

**Приоритет 0 (массовые экосистемы, добавлять в первую очередь):**

| Язык | LSP-сервер | Команда | Extensions |
|---|---|---|---|
| C/C++ | clangd | `clangd --background-index` | `.c .h .cpp .hpp .cc` |
| C# | csharp-ls (или OmniSharp) | `csharp-ls` | `.cs` |
| Ruby | ruby-lsp | `ruby-lsp` | `.rb` |
| PHP | intelephense | `intelephense --stdio` | `.php` |
| Kotlin | kotlin-lsp | `kotlin-lsp` | `.kt .kts` |
| Swift | sourcekit-lsp | `sourcekit-lsp` | `.swift` |
| Bash | bash-language-server | `bash-language-server start` | `.sh .bash` |
| CSS/HTML/JSON | vscode-langservers-extracted | `vscode-css-language-server --stdio` / `vscode-html-language-server --stdio` / `vscode-json-language-server --stdio` | `.css .html .json` |

**Приоритет 1 (частые в агентских задачах):**

| Язык | LSP-сервер | Extensions |
|---|---|---|
| Scala | metals | `.scala` |
| Dart/Flutter | dart language-server | `.dart` |
| Elixir | elixir-ls | `.ex .exs` |
| Zig | zls | `.zig` |
| Haskell | haskell-language-server | `.hs` |
| Vue | vue-language-server (Volar) | `.vue` |
| Svelte | svelte-language-server | `.svelte` |
| Terraform | terraform-ls | `.tf` |
| TOML | taplo | `.toml` |
| YAML | yaml-language-server | `.yml .yaml` |
| Protobuf | buf / protobuf-language-server | `.proto` |

**Приоритет 2 (по спросу):** Julia (`julia --startup-file=no --history-file=no --eval "using LanguageServer..."`), OCaml (`ocamllsp`), F# (`fsautocomplete`), R (`R --slave -e languageserver::run()`), Nix (`nil`/`nixd`), Markdown (`marksman`), GraphQL (`graphql-lsp`), SQL (`sqls`), Groovy, Crystal, Solidity.

### 3.3. Дефекты LSP-клиента (вне списка серверов)

1. **Фрейминг транспорта сломан** (см. §0.2 п.3) — блокер.
2. `_handle_message`: сообщения с `id` и `method` (server→client **requests**: `workspace/applyEdit`, `workspace/configuration`, `client/registerCapability`) попадают в ветку «response» и теряются.
3. Гонка `_send_request`: future регистрируется после отправки — ответ, пришедший раньше регистрации, не находит будущего.
4. Диагностика только pull (`textDocument/diagnostic`); rust-analyzer и ряд серверов pull не поддерживают — нужен листенер `textDocument/publishDiagnostics` + `wait_for_diagnostics(timeout)`.
5. `capabilities: {}` — клиентские возможности не объявлены; ответ `initialize` (server capabilities) игнорируется.
6. Нет `textDocument/didSave`, `workspace/didChangeWatchedFiles`, `textDocument/formatting`, organize-imports (codeAction kind `source.organizeImports`), call hierarchy — а P-21 (Symbolic Shortcut) требует `lsp.format` и `lsp.organize_imports`.
7. Дублирование конфигураций между `bus.py::_initialize_server_configs` и `config.py::LANGUAGE_LSP_CONFIGS` — два источника правды.
8. Redis-«cross-process reuse» — заглушка (пишется pid, подключение к чужому процессу невозможно).

Закрывают тикеты P-31 (transport + bidirectional) и P-32 (новые серверы + новые tools).

---

## 4. Промпты-тикети

> Общие правила (наследуются из `AGENTS.md`): спека тикета — grep по `analytics/`; команды `uv sync` / `uv run pytest` / `make lint`; порядок завершения **format → lint → test**; LLM-seam только `app/core/llm/`; `get_tools()` фиксированный порядок + `EXPECTED_NAMES`/`EXPECTED_REQUIRED_ARGS` в `tests/integration/test_tools_integration.py`; FS-инструменты через `validate_path()`; вывод наружу через `wrap_untrusted()`/`detect_injection()`; добавление инструмента = 5 шагов; docstring модуля с id тикета; коммиты `<ID>: ...`.

---

## 4.1. P-28 — MCP-compliant клиент (JSON-RPC + транспорта) и реестр внешних MCP-серверов

> **Dependencies:** нет (независим от PROD-цепочки) | **Estimate:** 3 дня | **TRIZ:** #24 Intermediary
> **Проблема:** `app/mcp/client.py` — собственный REST-контракт (`GET /health`, `GET /tools`, `POST /call`), а не протокол MCP. Агент не может подключать внешние MCP-серверы.

### Goal

1. `app/mcp/mcp_client_v2.py::MCPClientV2` — клиент на официальном SDK `mcp` (`ClientSession`):
   - Транспорта: `stdio_client` (spawn внешнего сервера: `command`, `args`, `env`) и `streamablehttp_client` (SSE-fallback). Выбор — по конфигу сервера.
   - Полный handshake: `initialize` → подтверждение capabilities → `notifications/initialized`.
   - `list_tools()`, `call_tool()` через JSON-RPC; поддержка `resources/list`/`resources/read` и `prompts/list` (read-only, в реестр — отдельным типом).
2. Реестр внешних серверов: `.orya/mcp.json` (формат совместим с Claude Desktop/Cursor: `{"mcpServers": {"<name>": {"command"/"url", "args", "env"}}}`) + env-override `ORYA_MCP_SERVERS`. Валидация схемой, secrets только через env (`${VAR}`-подстановка, никогда не в файле).
3. Мостинг инструментов в агента: внешние tools попадают в `get_tools()` с неймспейсом `mcp__<server>__<tool>` — **добавляются в конец списка**, `EXPECTED_NAMES`/`EXPECTED_REQUIRED_ARGS` в `tests/integration/test_tools_integration.py` обновляются; описание-схема пробрасывается из `inputSchema` MCP.
4. Lifecycle: per-server health-проверка при старте; недоступный сервер → degrade (его инструменты не добавляются, `mcp.server_degraded=true` в span, UI не показывает ошибку); retry-connect с экспоненциальным backoff (max 3).
5. Убрать глобальный `asyncio.Lock` из `call_tool`: конкурентность per-server (lock на сервер, не на клиент). Убрать process-wide singleton — инжектировать клиент через фабрику с явным сбросом (аналог `clear_settings_cache()`).
6. Обратная совместимость: внутренние HTTP-фасады (`oriahs-mcp` и др.) работают; миграция OriaHS-клиента на V2 — отдельным флагом `ORYA_MCP_CLIENT_V2=true` (default true для внешних серверов).
7. Spans: `mcp.initialize`, `mcp.call` (`mcp.server`, `mcp.tool`, `mcp.duration_ms`). Metrics: `orya_mcp_call_total{server,status}`, `orya_mcp_tool_count{server}`, `orya_mcp_server_up{server}`.

### Acceptance Criteria

- ✅ Подключение реального внешнего сервера: `npx -y @modelcontextprotocol/server-filesystem <dir>` через stdio → `list_tools()` возвращает его инструменты, вызов `mcp__filesystem__read_text_file` работает.
- ✅ Подключение streamable-HTTP сервера (любой публичный reference-сервер) — handshake и call проходят.
- ✅ `.orya/mcp.json` валидируется; битый JSON → ясная ошибка при старте, сессия не падает; отсутствующий сервер → degrade, не exception.
- ✅ 10 параллельных `call_tool` к одному серверу — без deadlock; к двум серверам — реально параллельно (тест по времени).
- ✅ `get_tools()` содержит неймспейсированные инструменты, интеграционный тест зелёный.
- ✅ Format → lint → test зелёные.

### Forbidden patterns

- ❌ Кастомный «почти-MCP» JSON-RPC мимо SDK (если только не обосновано в плане).
- ❌ Глобальная блокировка всех вызовов одним lock.
- ❌ Secrets в `mcp.json` (только `${VAR}`-подстановка).
- ❌ Мутирующий доступ внешних tools к DFC без `validate_path()`-эквивалента (FS-root из конфига сервера).

### Suggested files

`app/mcp/mcp_client_v2.py`, `app/mcp/registry.py`, `app/mcp/bridge.py` (mcp→langchain tools), `.orya/mcp.json.example`, `tests/unit/test_mcp_registry.py`, `tests/integration/test_mcp_client_v2.py`.

---

## 4.2. P-29 — MCP hardening: OAuth 2.1, W3C trace propagation, resilience

> **Dependencies:** P-28 | **Estimate:** 2 дня | **TRIZ:** #11 Beforehand cushioning
> **Проблема:** нет авторизации по спецификации MCP (OAuth 2.1), нет `MCP-Trace-Id`/W3C-пропагации на MCP-границе (конфликт с P-19), нет circuit breaker.

### Goal

1. Авторизация: для HTTP-транспорта — OAuth 2.1 authorization code + PKCE, RFC 9728 protected-resource metadata discovery, refresh-token flow; токены в keyring/env, никогда в логах. Для локальных stdio-серверов — auth не требуется.
2. Trace propagation (интеграция с P-19): `MCPClientV2` инжектит `MCP-Trace-Id`/`MCP-Span-Id`/`MCP-Parent-Span-Id` + W3C `traceparent` в заголовки и в `_meta` JSON-RPC для stdio; `trace-completeness > 95%` проверяется существующим nightly.
3. Resilience: per-server circuit breaker (5 ошибок подряд → open 60 s → half-open probe); timeout policy per tool (default 30 s, конфиг); идемпотентные ретраи только для сетевых ошибок (5xx/timeout), не для `isError=true` ответов.
4. Rate/size limits: max payload 5 MB, max tools per server 200 (защита от раздутых серверов), предупреждение в span при превышении.
5. Notifications: обработка `notifications/tools/list_changed` → инвалидация кэша инструментов сервера (не полный рестарт сессии).

### Acceptance Criteria

- ✅ HTTP-сервер с включённым OAuth 2.1 подключается (тест с локальным stub-authorization-server).
- ✅ Span `mcp.call` содержит `MCP-Trace-Id`, совпадающий с корневым trace; trace-completeness > 95% на e2e-прогоне.
- ✅ Circuit breaker: 5 подряд ошибок → сервер open, вызовы fail-fast с degrade-метрикой, через 60 s half-open.
- ✅ `tools/list_changed` обновляет кэш без перезапуска (тест).

### Forbidden patterns

- ❌ Токены/секреты в логах, span-атрибутах и results.
- ❌ Ретраи неидемпотентных вызовов «на всякий случай».
- ❌ Хардкод trace-заголовков мимо propagation-хелпера (P-19).

### Suggested files

`app/mcp/auth.py`, `app/mcp/resilience.py`, `app/mcp/mcp_client_v2.py` (update), `tests/unit/test_mcp_resilience.py`, `tests/integration/test_mcp_oauth.py`.

---

## 4.3. P-30 — ACP-сервер (Agent Client Protocol): OryaAgent как ACP-агент для редакторов

> **Dependencies:** нет (граф агента из B-25/DFC) | **Estimate:** 3 дня | **TRIZ:** #6 Universality
> **Проблема:** ACP отсутствует полностью; агента нельзя вести из Zed и других ACP-совместимых хостов.

### Goal

1. `app/acp/server.py::ACPServer` — JSON-RPC 2.0 поверх stdio (фрейминг LSP-совместимый `Content-Length`), реализующий роль **agent**:
   - `initialize` → capabilities (loadSession: true/false, promptCapabilities: embed, meta);
   - `session/new` (cwd, mcpServers от хоста) → `session/update` стрим;
   - `session/load` (resume), `session/prompt` (блоки текста/embeddedResource), `session/cancel`;
   - нотификации `session/update`: `agent_message_chunk` (стрим токенов), `tool_call` / `tool_call_update` (pending → in_progress → completed/failed, kind: read/edit/delete/move/search/execute/think/fetch/other), `plan` (entries с priority/status), `current_mode`;
   - `session/request_permission` → мост в существующую permission-ноду (M-16, `app/core/permissions.py`, fail-closed);
   - callbacks `fs/read_text_file`, `fs/write_text_file` → мост в read/write-инструменты (`validate_path()` сохраняется); `terminal/*` → мост в sandbox-bash (bwrap, P-08 если реализован, иначе per-OS allowlist).
2. Адаптер: ACP-сессия оборачивает существующий LangGraph-граф; стриминг через `astream_events` v2 → `agent_message_chunk`; ходы tri-model маппятся в plan-entries (planner/executor/tester).
3. CLI: `orya acp` (точка входа в `app/cli/`) — запуск ACP-сервера над workspace; документация подключения к Zed (в `docs/acp.md`).
4. MCP-серверы, переданные хостом в `session/new`, добавляются в реестр P-28 на время сессии (неймспейс `acp__<name>__<tool>`).
5. Spans: `acp.session`, `acp.prompt`, `acp.permission`. Metrics: `orya_acp_session_total`, `orya_acp_message_chunks_total`, `orya_acp_permission_total{decision}`.

### Constraints

- ACP-сервер не мутирует глобальные настройки; per-session DFC snapshot (конвенция приоритетного промпта PROD: immutable snapshot).
- Никаких error-баннеров в хост: ошибки хода → `session/update` с `tool_call_update status=failed` + текстовый итог.
- JSON-RPC id строго коррелируются; входящие server→client-запросы не теряются (урок из LSP-аудита §3.3 п.2).

### Acceptance Criteria

- ✅ `echo '{"jsonrpc":"2.0","id":1,"method":"initialize",...}' | orya acp` — корректный ответ с capabilities.
- ✅ E2E со скриптом-клиентом: session/new → session/prompt «создай файл hello.py» → стрим chunks + tool_call(edit) + request_permission → completed.
- ✅ Cancel: `session/cancel` останавливает ход ≤ 500 ms.
- ✅ Подключение из Zed (ручная проверка по `docs/acp.md`) — агентовая сессия отвечает в редакторе.
- ✅ Фрейминг `Content-Length` — юнит-тест на fragmentation (сообщение, разбитое на несколько chunk-ов чтения).

### Forbidden patterns

- ❌ ACP-сервер с правами шире permission-модели агента (request_permission обязателен для write/execute).
- ❌ newline-delimited JSON вместо Content-Length фрейминга.
- ❌ Потеря server→client requests (id+method).

### Suggested files

`app/acp/__init__.py`, `app/acp/server.py`, `app/acp/protocol.py` (фрейминг, переиспользуемый P-31), `app/acp/adapter.py`, `app/cli/acp.py`, `docs/acp.md`, `tests/unit/test_acp_protocol.py`, `tests/e2e/test_acp_session.py`.

---

## 4.4. P-31 — HOTFIX LSP-транспорта: Content-Length фрейминг + bidirectional-запросы

> **Dependencies:** нет | **Estimate:** 2 дня | **Приоритет:** блокер B-26 и P-21
> **Проблема:** `app/core/lsp/bus.py` шлёт newline-delimited JSON; LSP требует `Content-Length: N\r\n\r\n`. Против реальных серверов клиент не работает (приёмка B-26 прошла на моках). Server→client-запросы теряются; гонка регистрации future; push-диагностика не слушается.

### Goal

1. `app/acp/protocol.py` → `app/core/lsp/protocol.py::LSPBaseProtocol` (общий с ACP, P-30):
   - Отправка: `Content-Length: N\r\n\r\n<body>`; чтение: парсер заголовков с буферизацией, устойчивый к fragmentation/partial reads (тест: тело разбито на 3 chunk-а).
   - Заменить `buffer.split("\n", 1)` на фрейм-парсер; `json.loads` только на полном фрейме.
2. Bidirectional-обработка в `_handle_message`:
   - сообщение с `id` + `method` — это **запрос сервера**: отвечай результатом/ошибкой; роутинг `workspace/applyEdit` (применить WorkspaceEdit атомарно через write-инструмент), `workspace/configuration` (вернуть секции из init_options), `client/registerCapability`, `window/workDoneProgress/create`;
   - сообщение с `id` без `method` — response: resolve future **по id**; исправь гонку — регистрируй future до отправки.
3. Client capabilities в `initialize`: `textDocument` (hover, definition, references, rename, codeAction, diagnostic, publishDiagnostics), `workspace` (applyEdit, symbol, configuration, didChangeWatchedFiles, workspaceFolders). Парси ответ сервера: если capability отсутствует — помечай метод недоступным (`server.supports(method) -> bool`), не шли запрос.
4. Диагностика: слушай `textDocument/publishDiagnostics` (кэш per-file + `asyncio.Event`); `diagnostics()` = pull (если сервер поддерживает) с merge push-кэша; добавь `wait_for_diagnostics(file, timeout=10)`.
5. Фикс `_initialize`: `didOpen` для всех уже открытых файлов workspace при старте (limit 100), `didSave` после edit-инструментов (seam в `app/tools/edit.py::after_edit`).
6. Redis-reuse: честно пометить как FUTURE+ (убрать заглушку записи pid) или реализовать через отдельный LSP-gateway-процесс; сейчас — удалить вводящий в заблуждение код и `lsp.redis_reuse=false` в settings.
7. Регрессионные тесты против **реальных** серверов (integration, инфра-условные): pyright — hover/diagnostic; mock-server с фреймингом — все методы. Unit: fragmentation, серверный запрос applyEdit, публикация diagnostics, гонка ответов (ответ до регистрации future).

### Acceptance Criteria

- ✅ `pytest tests/integration/test_lsp_pyright.py` — зелёный против реального pyright-langserver (hover возвращает содержимое).
- ✅ Fragmentation-тест: JSON разрезан на 3 записи чтения — парсер собирает.
- ✅ `workspace/applyEdit` от сервера применяется атомарно; тест с mock-сервером.
- ✅ `wait_for_diagnostics` получает push-диагностику от rust-analyzer (у которого pull отсутствует) — integration-тест, инфра-условный.
- ✅ `lsp_diagnostics` на файле с ошибкой возвращает ошибки < 100 ms после didOpen.

### Forbidden patterns

- ❌ Накаких readline-парсеров по `\n` для LSP/ACP транспорта.
- ❌ Игнорирование server-capabilities (запросы методов, которые сервер не объявил).
- ❌ Mock-only тесты для транспортного слоя (минимум один integration с реальным сервером).

### Suggested files

`app/core/lsp/protocol.py`, `app/core/lsp/bus.py` (update), `app/core/lsp/diagnostics.py`, `tests/unit/test_lsp_protocol.py`, `tests/integration/test_lsp_pyright.py`, `tests/integration/test_lsp_rust_analyzer.py`.

---

## 4.5. P-32 — LSP expansion: 9 новых серверов + lsp.format / lsp.organize_imports / lsp_call_hierarchy

> **Dependencies:** P-31 | **Estimate:** 3 дня | **TRIZ:** #5 Merging
> **Проблема:** 6 языков из ~30+ популярных; `frontend`-конфиг заявляет `.css/.html`, которые typescript-language-server не обслуживает; нет tools форматирования и organize-imports, необходимых P-21 (Symbolic Shortcut).

### Goal

1. Единый источник правды: `bus.py::_initialize_server_configs` удаляется, `LSPBus` читает `LANGUAGE_LSP_CONFIGS` из `config.py`; маппинг расширений не пересекается (один extension → один сервер; `.h` → clangd, конфликт с C++ решается detection по содержимому — опц.).
2. Новые серверы (Приоритет 0 из §3.2): clangd (C/C++), csharp-ls, ruby-lsp, intelephense, kotlin-lsp, sourcekit-lsp, bash-language-server, yaml-language-server, vscode-css/html/json-language-server (`vscode-langservers-extracted`); `frontend` разбивается на `frontend-ts` (ts/tsx/js/jsx), `frontend-css`, `frontend-html`.
3. Ленивый старт + idle- reap: сервер запускается на первый запрос языка (не все 15 сразу); после 10 мин бездействия — shutdown (configurable); max одновременно работающих серверов 6 (LRU-вытеснение).
4. Capability detection при старте сессии: бинарник сервера есть в PATH → язык enabled; нет → degraded-режим (fallback read+grep), `lsp.language_disabled{language}` метрика; в system prompt — заметка какие LSP-возможности доступны.
5. Новые инструменты (полные 5 шагов конвенции): `lsp_format` (`textDocument/formatting` + range-форматирование), `lsp_organize_imports` (codeAction kind `source.organizeImports` + applyEdit через P-31), `lsp_call_hierarchy` (prepare/incoming/outgoing calls). Read-only`lsp_format`? — нет: это write → permission-allowlist не добавлять; `lsp_organize_imports` — write; `lsp_call_hierarchy` — read-only.
6. `docker-compose.yml` / `deploy/`: опциональный профиль `lsp-full` с установленными серверами; базовый образ — pyright+typescript (как сейчас).
7. Spans `lsp.call{language,method}`; metrics `orya_lsp_tool_total{tool,language,status}`, `orya_lsp_server_uptime_seconds{language}`.

### Acceptance Criteria

- ✅ `get_supported_languages()` возвращает ≥ 14 записей; extension-маппинг без конфликтов (тест).
- ✅ `lsp_format("main.py")` форматирует файл (integration с реальным сервером или black через LSP-шлюз pyright не поддерживает formatting — тогда через `ruff-lsp` опционально; допустимый fallback: файл-локальный форматтер с пометкой в span `lsp.format.fallback=true`).
- ✅ `lsp_organize_imports("src/utils.py")` возвращает применённый WorkspaceEdit (использует P-31 applyEdit).
- ✅ Ленивый старт: 20 запросов только к Python не поднимают остальные серверы (тест по числу процессов).
- ✅ Отсутствие clangd в PATH → язык disabled, ход агента не падает (degraded fallback-тест).
- ✅ `EXPECTED_NAMES` обновлён, `format → lint → test` зелёные.

### Forbidden patterns

- ❌ Дублирование конфигов серверов (второй источник правды запрещён).
- ❌ Запуск всех серверов при старте сессии.
- ❌ Инструменты format/organize_imports без permission-ноды (это write-операции).

### Suggested files

`app/core/lsp/config.py` (update), `app/core/lsp/bus.py` (update), `app/core/lsp/registry.py` (новый: capabilities + lazy lifecycle), `app/tools/lsp.py` (update: +3 tools), `tests/unit/test_lsp_registry.py`, `tests/integration/test_lsp_format.py`.

---

## 4.6. P-33 — Web tools: web_search / web_fetch

> **Dependencies:** нет | **Estimate:** 2 дня | **TRIZ:** #23 Feedback
> **Проблема:** у агента нет доступа к интернету — нет инструментов `web_search` и `web_fetch` в `app/tools/`. Сильный агент вне код-контекста (актуальные доки, версии библиотек, issue-трекеры) слеп.

### Goal

1. `app/tools/web_search.py` — `@tool`, async, `Annotated[str, ...]`: поиск через сконфигурированный провайдер (env `ORYA_WEB_SEARCH_PROVIDER`: `tavily` | `brave` | `serper` | `duckduckgo` (fallback без ключа)); возврат — один JSON-документ (конвенция): `{query, results: [{title, url, snippet}], provider}`; top_k ≤ 10.
2. `app/tools/web_fetch.py` — fetch URL: timeout 15 s, max size 2 MB, HTML→markdown/text extraction (readability-подход), `wrap_untrusted()` на контент + `detect_injection()` (страницы — классический вектор prompt-injection).
3. SSRF-защита: allowlist схем (http/https), запрет private/loopback/link-local CIDR (`ipaddress`), запрет redirect на private, DNS-rebinding — резолв и повторная проверка IP перед запросом; `validate_path()` не применим — вместо него отдельный `validate_url()` в `app/tools/_validators.py`.
4. Кэш: get_cache() для обоих (read-only), TTL 15 мин на URL; инвалидация стандартная.
5. Permission: оба read-only → permission-allowlist; но `web_fetch` доменных исключений — human-нода при отсутствии в allowlist (env `ORYA_WEB_FETCH_ALLOWLIST`).
6. Оба инструмента — в `get_tools()`, `EXPECTED_NAMES`, unit-тесты с моком HTTP (никогда реальный интернет в тестах).

### Acceptance Criteria

- ✅ `web_search("fastapi background tasks")` валидный JSON с ≥ 1 результатом (интеграционный тест помечен infra-условным).
- ✅ SSRF-тесты: `http://127.0.0.1`, `http://169.254.169.254`, redirect на private — все отклонены.
- ✅ Prompt-injection в содержимом страницы детектится (`detect_injection` hit → span-атрибут).
- ✅ `EXPECTED_NAMES` обновлён; `format → lint → test` зелёные.

### Forbidden patterns

- ❌ Fetch без size/timeout лимитов.
- ❌ Контент страницы в контекст без `wrap_untrusted()`.
- ❌ Реальные сетевые вызовы в unit-тестах.

### Suggested files

`app/tools/web_search.py`, `app/tools/web_fetch.py`, `app/tools/_validators.py` (+`validate_url`), `tests/unit/test_web_tools.py`, `tests/integration/test_web_tools_live.py` (infra-conditional).

---

## 4.7. P-34 — Planning/todo + generic subagents (Task-делегирование)

> **Dependencies:** B-24 (DFC snapshot) | **Estimate:** 2–3 дня | **TRIZ:** #1 Segmentation
> **Проблема:** нет planning/todo-инструмента (план не виден пользователю и не переживает компакцию) и нет generic-механизма субагентов — Tournament (P-23) — это quality-механика одной задачи, а не декомпозиция.

### Goal

1. `app/tools/todo.py` — `todo_write(todo_list)` / `todo_read()`: структура `{id, content, status: pending|in_progress|completed, priority}`; хранится в DFC (Persistence-layer), сериализуется в сессию; UI: Chainlit-панель плана обновляется по `todo_write`-событию; в system prompt — текущий план (динамическая секция, после cacheable prefix).
2. Правило в промпте planner-фазы: многошаговые задачи (> 3 шага) обязаны начинаться с `todo_write`.
3. `app/core/subagents.py::SubagentRunner` + `app/tools/task.py::task` — делегирование подзадачи субагенту:
   - субагент получает **immutable `dfc.snapshot()`** + изолированный result-slot (конвенция приоритетного промпта PROD — никакого общего мутируемого стейта);
   - ограничения: depth ≤ 2 (субагент не может порождать субагентов), max 4 параллельных (`asyncio.Semaphore`), budget per subagent (`max_cost_usd`, default $0.05) — превышение → degrade до запуска, не exception;
   - возврат — строка-отчёт (не раздутый контекст), span `subagent.run{depth, cost_usd, status}`;
   - доступ к инструментам — подмножество (без write/edit по умолчанию; расширение — через permission-ноду).
4. `todo_write`-события и статусы субагентов стримятся в UI как plan-entries (совместимо с ACP `session/update plan` из P-30 — один источник событий).

### Acceptance Criteria

- ✅ `todo_write` с 5 пунктами → план виден в system prompt следующего хода и в UI.
- ✅ Субагент depth 1 возвращает отчёт; мутирование DFC субагентом не видно родителю (тест на snapshot-изоляцию).
- ✅ 4 параллельных субагента — ок; 5-й ждёт семафора; budget-превышение → degrade со span-атрибутом, без exception в UI.
- ✅ Depth 2: субагент, вызвавший `task`, получает ToolException «depth limit».

### Forbidden patterns

- ❌ Общий мутируемый DFC между родителем и субагентами.
- ❌ Unbounded рекурсия делегирования (max depth 2).
- ❌ `raise` budget-ошибки сквозь граф в UI.

### Suggested files

`app/tools/todo.py`, `app/tools/task.py`, `app/core/subagents.py`, `app/core/workflow/state.py` (+todo-секция), `tests/unit/test_todo_tool.py`, `tests/unit/test_subagents.py`.

---

## 5. Сводная таблица

| ID | Title | Estimate | Закрывает пробел |
|---|---|---|---|
| P-28 | MCP-compliant клиент + реестр внешних серверов | 3 д | MCP-коннектор (внешние серверы) |
| P-29 | MCP hardening: OAuth 2.1, trace, resilience | 2 д | MCP-коннектор (прод. готовность) |
| P-30 | ACP-сервер (Agent Client Protocol) | 3 д | ACP-коннектор (отсутствует) |
| P-31 | HOTFIX: LSP Content-Length фрейминг + bidirectional | 2 д | LSP-транспорт (блокер B-26/P-21) |
| P-32 | LSP expansion: 9 серверов + format/imports/hierarchy | 3 д | LSP-покрытие языков |
| P-33 | Web tools (web_search/web_fetch) | 2 д | Доступ к интернету |
| P-34 | Planning/todo + subagents | 3 д | Декомпозиция и видимость плана |
| **Σ** | | **~18 д** | |

Приоритет реализации: **P-31 → P-32 → P-28 → P-30 → P-29 → P-33 → P-34** (P-31 — до PROD, как hotfix BETA). Напоминание: P-27 (AGENTS.md loader, Приложение A PROD-промпта) также не реализован в репо — рекомендуется включить в ту же волну, он независим.

## 6. Ссылки

- Код аудита: `app/mcp/client.py`, `app/mcp/oriahs_mcp.py`, `app/core/lsp/bus.py`, `app/core/lsp/config.py`, `app/core/lsp/README.md`, `app/tools/` (реестр), `app/api/`.
- Документы: `analytics/ARCHITECT.md`, `analytics/BACKLOG.md` (P-20…P-26), `analytics/ROADMAP.md`, `AGENTS.md`, `PROMPT_PRODUCTION.md` (включая Приложение A / P-27).
- Спецификации: Model Context Protocol (JSON-RPC 2.0, stdio/streamable-HTTP, OAuth 2.1 RFC 6750/6749/9728), Agent Client Protocol (initialize/session/prompt/session-update, stdio, Content-Length), LSP 3.17 (Base Protocol, publishDiagnostics).
