# Спецификация контрактов модулей MVP

**Документ:** 01-module-contracts
**Дата:** 20 октября 2026
**Статус:** Draft v0.1 — открыто для ревью сообщества
**Связанные документы:** [self-agent.md](../self-agent.md), [02-llm-adapter-spec.md](02-llm-adapter-spec.md), [03-session-format.md](03-session-format.md), [04-tool-contracts.md](04-tool-contracts.md)

---

## 0. Назначение документа

Этот документ фиксирует **концептуальные контракты** между 8 модулями MVP OryaAgent: зону ответственности, ключевые абстракции, точки взаимодействия, границы и инварианты. Это не справочник по API (он будет автогенерироваться из кода через mkdocs+griffe), а **архитектурная карта**: где проходит граница между модулями, какие данные пересекают эти границы, какие гарантии даёт каждый модуль.

После ревью этого документа начинается фаза 0 разработки — каркас пакетов с заглушками, удовлетворяющими контрактам. Любая имплементация, нарушающая контракт, — баг архитектуры.

## 1. Карта модулей и зависимостей

```
                    ┌───────────────────────┐
                    │   cli / tui (rich)     │
                    └───────────┬───────────┘
                                │
                    ┌───────────▼───────────┐
                    │      agent_loop        │
                    └─┬───────┬───────┬─────┘
                      │       │       │
              ┌───────▼──┐ ┌──▼────┐ ┌▼──────────┐
              │   llm    │ │session│ │ context_  │
              │  _seam   │ │ _log  │ │ manager   │
              └───────┬──┘ └──┬────┘ └───────────┘
                     │       │
                     │       │ (events)
                     │       │
              ┌──────▼───────▼──┐
              │      tools      │
              │     registry    │
              └────────┬────────┘
                       │
              ┌────────▼────────┐
              │   permissions   │
              └─────────────────┘
```

**Принцип зависимостей:** только `agent_loop` знает о существовании других модулей. `llm_seam`, `session_log`, `tools_registry`, `permissions` — это **порт-интерфейсы**, в которые `agent_loop` внедряется через DI. `cli` — единственный composition root.

## 2. Структура пакетов

```
src/orya/
├── __init__.py
├── __main__.py               # python -m orya
├── cli/
│   ├── __init__.py
│   ├── app.py                # entry point: orya
│   ├── repl.py               # REPL-цикл
│   ├── render.py             # rendering ответов (rich)
│   └── commands.py           # /exit, /model, /sessions
├── core/
│   ├── __init__.py
│   ├── loop.py               # agent_loop
│   ├── prompt.py             # system_prompt_builder
│   ├── context.py            # context_manager
│   ├── session.py            # session_log + проекция
│   └── events.py             # доменные события
├── llm/
│   ├── __init__.py
│   ├── base.py               # LLMProvider Protocol
│   ├── openai_compat.py      # OpenAI, Ollama, vLLM, OpenRouter
│   ├── anthropic.py          # Anthropic
│   └── registry.py           # провайдер-factory по конфигу
├── tools/
│   ├── __init__.py
│   ├── base.py               # Tool Protocol
│   ├── registry.py           # tool registry
│   ├── read.py
│   ├── write.py
│   ├── edit.py
│   ├── bash.py
│   └── grep.py
├── permissions/
│   ├── __init__.py
│   ├── engine.py             # permission engine
│   ├── policies.py           # ask / auto / allow-list
│   └── store.py              # ~/.orya/permissions.yml
└── config.py                 # загрузка конфигов
```

Composition root — `cli/app.py`. Никаких `import orya.core.loop` вне `cli/`.

## 3. Модуль: `llm_seam`

### Зона ответственности

Скрывает различия между LLM-провайдерами. Принимает канонический запрос (сообщения + инструменты + системный промпт), возвращает канонический ответ (текст + tool-calls) или stream токенов. Любая специфика провайдера (Anthropic `tool_use` vs OpenAI `function_call`, разные форматы system-prompt, prompt-cache аннотации) — внутреннее дело адаптера.

### Ключевые абстракции

- **`LLMProvider`** — Protocol с единственным методом `complete(req) -> AsyncIterable[StreamEvent]`. Конкретные адаптеры: `OpenAICompatProvider`, `AnthropicProvider`.
- **`LLMRequest`** — Pydantic-модель: model, messages, tools, system, temperature, max_tokens, stream. Конкретная стратегия cacheable-prefix инкапсулирована в адаптере.
- **`StreamEvent`** — discriminated union: `AssistantToken | ToolCallStart | ToolCallDelta | ToolCallEnd | UsageUpdate | Stop`. Это доменная модель потока, не протокол провайдера.
- **`LLMResponse`** — финальное состояние после полного stream consumption: assistant_message + tool_calls + usage + stop_reason.

### Инварианты

- **Провайдер-нейтральность:** ни один модуль вне `llm/` не знает, какой провайдер активен. Переключение провайдера — изменение конфига, не кода.
- **Stream-first:** все ответы стримятся. Синхронный `complete` возвращает `AsyncIterable` из одного элемента — это упрощает consumer-логику.
- **Tool-call семантика:** tool-calls возвращаются как часть потока, не как отдельный «mode». LLM может вернуть текст + tool-calls одновременно (поведение зависит от провайдера — это нормально).
- **Cost tracking:** каждый `LLMResponse` содержит `usage` (input/output/cache tokens + estimated cost). Это инвариант для observability.

### Граница

**Вход:** `LLMRequest` (канонический формат).
**Выход:** `AsyncIterable[StreamEvent]` → агрегируется в `LLMResponse` consumer-ом.

Адаптер **не** знает про: сессии, контекст, разрешения, инструменты как код. Он получает готовый `tools: list[ToolSpec]` и возвращает `tool_calls: list[ToolCall]` — выполнение за рамками шва.

## 4. Модуль: `agent_loop`

### Зона ответственности

Главный цикл агента. Получает пользовательский ввод, собирает полный запрос (системный промпт + контекст + сообщения + инструменты), вызывает LLM, обрабатывает tool-calls (с permission-gate), добавляет результаты в сессию, повторяет, пока LLM не вернёт финальный ответ без tool-calls. Реализует лимит итераций, обработку ошибок, прерывание пользователем.

### Ключевые абстракции

- **`AgentLoop`** — класс с DI-зависимостями: `llm`, `session`, `tools`, `perm`, `sys_prompt`, `ctx_mgr`. Один метод `async run(user_message) -> AsyncIterable[LoopEvent]`.
- **`LoopEvent`** — discriminated union: `AssistantToken | ToolCallRequested | PermissionPrompt | ToolExecuting | ToolResult | AssistantMessage | Error | Stop`. Это **публичный протокол** между ядром и клиентом — cli/tui подписывается на эти события.
- **`LoopState`** — internal state machine: `idle → llm_calling → tool_pending → tool_executing → idle | stopped | error`. Не персистится, восстанавливается из session-log при restart.

### Инварианты

- **One process, one loop.** Не запускаем параллельные loop-ы в одном процессе. Конкуренция — через asyncio, не через потоки.
- **25 итераций max.** После 25 LLM-вызовов в одном `run()` — принудительная остановка с `Stop(limit_exceeded=True)`. Защита от infinite loop.
- **Stream-first consumption:** `run()` — async generator, клиент обязан потреблять ивенты для прогресса.
- **Abortable:** любой `run()` можно прервать через `loop.abort()`. Abort корректно отменяет pending LLM-call, не дожидается завершения tool-execution (но гарантирует, что уже запущенный tool допишет результат в сессию с маркером `aborted`).
- **No side effects beyond session-log.** Все изменения состояния агента — через `session.append()`. Если `session.append()` упал — loop останавливается с `Error(persistence_failed)`.

### Граница

**Вход:** пользовательское сообщение (строка + опциональные аттачменты v2).
**Выход:** `AsyncIterable[LoopEvent]` для клиента.

Loop не знает про: TUI, CLI-команды, формат сессии на диске (только про интерфейс `SessionLog`), формат конфига провайдера (только про `LLMProvider` Protocol).

## 5. Модуль: `system_prompt_builder`

### Зона ответственности

Собирает системный промпт из секций: identity («ты OryaAgent, версия X»), инструменты (генерируется из схем в `tools_registry`), контекст (рабочий каталог, git-статус, платформа), пользовательские преференсы (`~/.orya/memory.md`), правила безопасности (защита от prompt injection). Поддерживает версионирование и кэширование префикса.

### Ключевые абстракции

- **`SystemPromptBuilder`** — собирает `SystemPrompt` объект: `cacheable_prefix: str` (стабильная часть) + `dynamic_suffix: str` (контекст, git-статус). Конкретное разделение зависит от провайдера (Anthropic поддерживает cache breakpoints, OpenAI — через `cache_control` emulation).
- **`PromptSection`** — Protocol: `name`, `priority`, `cacheable: bool`, `render(ctx) -> str`. Секции регистрируются в builder-е и сортируются по priority перед рендерингом.

### Инварианты

- **Idempotent в пределах сессии.** Один и тот же `(session, tools)` → один и тот же `SystemPrompt` (без учёта dynamic-секций).
- **Cacheable prefix содержит только стабильные данные.** Identity, tool-схемы, user-preferences. Git-статус, время, динамический контекст — в suffix.
- **Token budget.** Общий размер системного промпта не превышает 32k токенов. Если превышает — builder должен drop низкоприоритетные секции (по логу: «dropped sections: X, Y»).

### Граница

**Вход:** `Session`, `ToolRegistry`.
**Выход:** `SystemPrompt{text, cacheable_prefix}`.

Builder не знает про: LLM-провайдера (только про `cacheable_prefix` как маркер), пользовательский ввод, контекстное окно (это забота `context_manager`).

## 6. Модуль: `tool_registry` + 5 базовых инструментов

### Зона ответственности

Реестр инструментов с типизированными Pydantic-схемами входа. Каждый инструмент — это Protocol `Tool` с методом `async execute(input, ctx) -> ToolResult`. Реестр поддерживает регистрацию/удаление, вызов по имени, обработку ошибок и таймаутов. Конкретные инструменты (read/write/edit/bash/grep) — отдельные классы, регистрируемые в composition root.

### Ключевые абстракции

- **`Tool`** — Protocol: `name`, `description`, `input_schema` (Pydantic), `output_schema` (Pydantic), `async execute(input, ctx) -> ToolResult`.
- **`ToolContext`** — передаётся в каждый execute: рабочий каталог, timeout, AbortSignal, logger, audit-bridge.
- **`ToolRegistry`** — Protocol: `register(tool)`, `get(name)`, `specs() -> list[ToolSpec]`, `async execute(call) -> ToolResult`.
- **`ToolResult`** — discriminated union: `Success{content, metadata} | Error{kind, message, retryable} | Denied{reason}`.

### 5 базовых инструментов

Полные контракты — в [04-tool-contracts.md](04-tool-contracts.md). Здесь — зона ответственности:

- **`read`** — чтение файла с пагинацией, обработка бинарников, sensitive-файлов.
- **`write`** — атомарная запись, права доступа, предотвращение overwrite без подтверждения.
- **`edit`** — точечная замена с требованием уникальности `old_string`, обработка multiple-matches.
- **`bash`** — PTY-исполнение, timeout, обработка сигналов, env-фильтрация.
- **`grep`** — обёртка над ripgrep, выходной формат, лимиты.

### Инварианты

- **All tools are async.** Никаких синхронных I/O в hot-path. Синхронные операции (например, `os.stat`) — через `asyncio.to_thread`.
- **Pydantic-валидация на входе.** Некорректный input → `ToolResult.Error(kind=invalid_input, retryable=False)`, без исключения.
- **Audit trail.** Каждый вызов `execute` логируется в audit-bridge с метаданными: tool, input_hash, duration_ms, outcome.
- **Timeouts обязательны.** Каждый инструмент имеет default timeout (read=5s, write=5s, edit=5s, bash=300s, grep=30s). Переданный `timeout` переопределяет.
- **Idempotent execution для read/grep.** Вызов дважды с тем же input — тот же результат (кроме временных штампов в metadata).

### Граница

**Вход:** `ToolCall` (имя + Pydantic-валидированный input).
**Выход:** `ToolResult`.

Registry не знает про: LLM, сессии, контекстное окно, разрешения (permissions — отдельный модуль, вызывается ПЕРЕД registry).

## 7. Модуль: `session_log`

### Зона ответственности

Хранение сессии как append-only потока событий. Каждый шаг (пользовательский ввод, ассистентское сообщение, tool-call, tool-result, error, system-event) — отдельное событие с временным штампом. Поверх лога — проекция в массив сообщений для LLM (фильтрация, нормализация, удаление aborted-событий). Лог — источник истины; сообщения для LLM — производная.

Полная спецификация формата — в [03-session-format.md](03-session-format.md).

### Ключевые абстракции

- **`SessionEvent`** — discriminated union с Pydantic-моделями для каждого варианта: `UserMessage | AssistantMessage | ToolCall | ToolResult | PermissionDecision | Error | SystemEvent`. Каждое событие имеет: `id`, `ts`, `session_id`, `seq` (монотонный), `kind`, payload.
- **`SessionLog`** — Protocol: `async append(event)`, `async events() -> AsyncIterable[SessionEvent]`, `async to_messages() -> list[Message]`, `async save(path)`, `async load(path)`.
- **`SessionStore`** — конкретная имплементация: JSONL-файл в `~/.orya/sessions/<id>.jsonl`, atomic append через `aiofiles`.
- **`ProjectionLayer`** — преобразует event-log в `list[Message]` для LLM. Учитывает: фильтрацию aborted-событий, удаление дубликатов tool-result при retry, нормализацию roles.

### Инварианты

- **Append-only.** События не изменяются и не удаляются (кроме явной `vacuum()` в v2 — удаляет старые session-снапшоты). Любая «правка» — новое событие с пометкой `compensation_for`.
- **`model-visible means logged`.** Всё, что LLM увидел, — в логе. Если что-то передано LLM, но не залогировано — это баг архитектуры.
- **Sequential IDs.** `seq` монотонно растёт в пределах сессии. Gap-ы в seq — нормально (если event отменён через compensation, seq сохраняется).
- **Recoverable.** После crash-а или Ctrl+C сессия восстанавливается из JSONL-файла без потерь. Partial-write последней строки — детектится и обрезается при load.
- **Single writer.** Только `agent_loop` пишет в session-log. Другие модули — только читают.

### Граница

**Вход:** `SessionEvent` от `agent_loop`.
**Выход:** `AsyncIterable[SessionEvent]` для чтения, `list[Message]` для LLM через projection.

Session-log не знает про: формат сессии на диске (только `SessionStore`), провайдера, инструменты, контекстное окно.

## 8. Модуль: `context_manager`

### Зона ответственности

Управляет окном контекста: подсчитывает токены, решает, что включать в LLM-запрос, что урезать. В MVP — простая стратегия: системный промпт + последние N сообщений + N последних tool-результатов (с урезанием длинных). Compaction и Context Epoch — v2.

### Ключевые абстракции

- **`ContextManager`** — Protocol: `window(session) -> list[Message]`, `token_count(messages) -> int`, `set_max_tokens(n)`.
- **`TokenCounter`** — strategy-объект: `tiktoken` для OpenAI-compat, approximation `chars/4` для Anthropic (после официального tokenizer в SDK).

### Инварианты

- **Window всегда влезает.** Если суммарный размер (system + window) превышает `max_tokens - reserve` (reserve=2000 на ответ) — manager урезает снизу: сначала длинные tool-results (до 100 строк), потом старые user-сообщения, потом — assistant-сообщения (но не последние 3).
- **System prompt не урезается.** Если system + 1 сообщение > max_tokens — это `Error(context_overflow)`, не тихое урезание.
- **Token count — approximation.** Реальное потребление у провайдера может отличаться на ±10%. Это допустимо для MVP; v2 — точный подсчёт через провайдер-specific tokenizer.

### Граница

**Вход:** `SessionLog` (через `events()`).
**Выход:** `list[Message]` — финальный массив для `LLMRequest.messages`.

Manager не знает про: системный промпт (его добавляет `agent_loop` в финальный `LLMRequest`), tools (не его забота), провайдера (только через TokenCounter).

## 9. Модуль: `cli/tui`

### Зона ответственности

Точка входа пользователя. REPL: чтение ввода (с поддержкой multi-line, history, autosuggest), передача в `agent_loop`, рендер ответов (stream-токены, tool-call карточки, permission-промпты), обработка slash-команд (`/exit`, `/clear`, `/model`, `/sessions`, `/help`).

### Ключевые абстракции

- **`App`** — composition root: создаёт все модули из конфига, передаёт в `AgentLoop`, запускает REPL.
- **`Renderer`** — подписан на `LoopEvent`, рисует в терминале через `rich`. Stream-токены — посимвольно, tool-calls — compact-карточками `[bash] $ ls -la`, permission-промпты — модальным окном.
- **`CommandRegistry`** — slash-команды, each как `Command` Protocol: `name`, `description`, `async execute(args, ctx)`.

### Инварианты

- **One-shot start.** `python -m orya` запускается без аргументов — это REPL. С аргументами (`-p`, `--prompt`) — one-shot режим для CI/scripts.
- **Ctrl+C обрабатывается.** First Ctrl+C прерывает текущий LLM-вызов. Second — выходит из REPL. Поведение аналогично Claude Code.
- **Stream-first rendering.** Токены печатаются немедленно при получении, не ждут полного ответа.
- **History persistent.** Последние 1000 команд сохраняются в `~/.orya/history`. Multi-line и slash-команды — отдельно.

### Граница

**Вход:** пользовательский ввод (строка).
**Выход:** рендер в терминал.

CLI — единственный composition root: только он знает, как связать все модули. Никакая бизнес-логика в CLI не живёт.

## 10. Модуль: `permissions`

### Зона ответственности

Контроль перед вызовом инструмента. В MVP — два режима: `ask` (по умолчанию) и `auto` (для CI). Статический allow-list по паттернам (`bash: ls *` разрешён без подтверждения). Не делает песочницу (v2), не делает MDM (enterprise-фичи).

Полная спецификация — в [05-security-model.md](05-security-model.md).

### Ключевые абстракции

- **`PermissionEngine`** — Protocol: `check(call) -> Decision`, `set_mode(mode)`, `add_rule(tool, pattern)`.
- **`Decision`** — discriminated union: `Allow | Deny{reason} | Ask{prompt}`. `Ask` означает, что engine не принял решения, и клиент (cli) должен показать пользовательский промпт.
- **`Rule`** — Pydantic: `tool: str`, `pattern: str` (regex), `action: allow | deny`. Хранится в `~/.orya/permissions.yml`.

### Инварианты

- **Deny by default.** Если нет разрешающего правила и mode=auto → deny. Если mode=ask → ask.
- **Allow-list превыше всего.** Если правило разрешает — режим не имеет значения.
- **Explicit deny-list.** Пользователь может явно запретить паттерн (например, `bash: rm -rf *`). Deny-list проверяется ПЕРВЫМ.
- **Audit.** Каждое решение (allow/deny/ask + final user choice) логируется в audit-log.

### Граница

**Вход:** `ToolCall`.
**Выход:** `Decision`.

Permissions не знает про: как выполняется инструмент, что он возвращает, контекстное окно, LLM. Это чисто gate.

## 11. Контракты взаимодействий (sequence-схемы)

### 11.1. Базовый цикл запрос-ответ

```
User → cli: "что в README?"
cli → agent_loop: run("что в README?")
agent_loop → session: append(UserMessage)
agent_loop → sys_prompt: build(session, tools)
agent_loop → ctx_mgr: window(session)
agent_loop → llm: complete(req) → StreamEvent*
  agent_loop потребляет stream, накапливает assistant_message
  → cli: AssistantToken* (для рендера)
agent_loop → session: append(AssistantMessage{text, tool_calls?})
agent_loop → cli: AssistantMessage
если tool_calls:
  for each call:
    agent_loop → perm: check(call)
    если Ask → cli: PermissionPrompt → user → yes/no
    если Allow → tools: execute(call) → ToolResult
    agent_loop → session: append(ToolCall, ToolResult)
    agent_loop → cli: ToolResult (для рендера)
  повторить цикл с обновлённым session
если нет tool_calls → Stop
```

### 11.2. Прерывание по Ctrl+C

```
user нажимает Ctrl+C
cli → agent_loop: abort()
agent_loop:
  1. cancel pending asyncio.Task llm.complete()
  2. если tool_executing — дождаться completion, но mark ToolResult.outcome=aborted
  3. session.append(SystemEvent{aborted_at_seq})
  4. yield Stop(reason=aborted)
cli: переходит в состояние idle, готов принимать новый ввод
```

### 11.3. Восстановление после crash

```
orya --resume <session-id>
cli → session: load(~/.orya/sessions/<id>.jsonl)
session:
  1. читает все события
  2. детектит partial-write последней строки (нет trailing \n)
  3. отбрасывает partial строку, логирует warn
  4. строит events() iterator
cli → agent_loop: attach(session)
cli: рендерит последние N сообщений как контекст, ждёт пользовательского ввода
```

## 12. Нефункциональные требования

### Производительность

- **Cold start:** <500ms до первого prompt-приглашения (на средней машине, без кэша pip).
- **LLM-call latency overhead:** <50ms между получением первого токена от провайдера и его рендерингом в TUI.
- **Tool execution overhead:** <20ms между `registry.execute(call)` и стартом фактической работы инструмента.
- **Session-log write:** <10ms на append, не блокирует LLM-stream.

### Надёжность

- **Crash recovery:** 100% — все валидные события до crash-а восстанавливаются.
- **Partial-write tolerance:** последняя partial строка JSONL отбрасывается с warn-логом, не валидируется как событие.
- **Concurrent writes:** только один writer (agent_loop) на сессию. Конкуренция — через asyncio.Lock в SessionStore.

### Совместимость

- **Python:** 3.12+ (используем PEP 695 type-parameters, `tomllib`, `asyncio.TaskGroup`).
- **ОС:** Linux (glibc), macOS, Windows 10+. WSL — поддерживается, но не нативно.
- **Архитектуры:** x86_64, arm64 (Apple Silicon, Linux ARM). Other — community-supported.

### Observability

- **Structured logging:** через `structlog`, JSON-формат в `~/.orya/logs/`.
- **Metrics:** локальные counters в `~/.orya/metrics.jsonl` (см. [07-observability-spec.md](07-observability-spec.md)).
- **Tracing:** OpenTelemetry-compatible spans (опционально, через `OTEL_EXPORTER` env).

## 13. Границы изменений

Что считается **совместимым** изменением (без major-версии):

- Добавление нового инструмента в `tools/`.
- Добавление нового LLM-адаптера в `llm/providers/`.
- Добавление новой slash-команды.
- Изменение реализации модуля без изменения Protocol.
- Расширение Pydantic-моделей (новые optional поля).

Что **ломает совместимость** (требует major-версии):

- Изменение `LLMProvider`, `Tool`, `SessionLog`, `PermissionEngine` Protocol.
- Изменение формата JSONL-сессии (требует миграции — см. [03-session-format.md](03-session-format.md)).
- Удаление или переименование tool.
- Изменение семантики `LoopEvent` вариантов.

## 14. Открытые вопросы (на ревью)

1. **Pydantic v2 vs msgspec?** Pydantic v2 — стандар de-facto, но msgspec в 5-10x быстрее на валидации. Для hot-path (session events) это может быть критично. Решение — в [ADR-001](../adr/ADR-001-asyncio.md).
2. **`asyncio.TaskGroup` (3.11+) vs `anyio`?** TaskGroup нативный, anyio — совместимость с trio. Для MVP — TaskGroup, пересмотр если появится реальная потребность в trio.
3. **Один `LLMProvider` на процесс или per-session?** Сейчас — singleton на процесс (проще connection pool). Per-session — если нужно разным сессиям разные провайдеры.
4. **`rich` или `textual`?** `rich` — для статического рендеринга. `textual` — full TUI framework. MVP на rich; если нужны сложные интерактивные элементы (modal для permission с stack-trace) — migrate на textual в v0.2.

---

**Следующие шаги после ревью:**

1. Зафиксировать ответы на открытые вопросы в ADR
2. Создать `pyproject.toml` с зависимостями
3. Создать скелет пакетов с заглушками (Protocol-классы без имплементации)
4. Реализовать Phase 0 — каркас, по roadmap из [self-agent.md](../self-agent.md)
