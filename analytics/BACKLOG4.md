# BACKLOG4 — Бэклог задач OryaAgent v4 (Python + LangChain + LangGraph)

> **Версия документа:** 4.0
> **Дата:** 19 октября 2026
> **Источники:** `ARCHITECT4.md` v4.0, `ROADMAP4.md` v4.0
> **Стек:** Python 3.11+, LangChain 0.3+, LangGraph 0.2+, FastAPI, PostgreSQL 16, Redis 7, Chainlit, OriaHS
> **Формат:** spec-driven тикеты (Context / Goal / Constraints / Acceptance Criteria / Forbidden patterns / Suggested files)
> **Гранулярность:** 1 тикет = 1 задача (~2 часа – 2 дня работы)
> **Статус:** готов к реализации; финальная TRIZ-проверка — в `BACKLOG5.md`

---

## Содержание

0. Как пользоваться этим документом
1. Фаза MVP (M-00 … M-19)
2. Фаза ALPHA (A-00 … A-12)
3. Фаза BETA (B-00 … B-15)
4. Фаза PROD (P-00 … P-15)
5. Фаза EXTENSION-PROD (E-00 … E-10)
6. Фаза FUTURE (F-00 … F-08)
7. Сводная матрица тикетов × фаз
8. Карта зависимостей между тикетами

---

## 0. Как пользоваться этим документом

### 0.1. Порядок выполнения

Тикеты пронумерованы с префиксом фазы: `M-` (MVP), `A-` (ALPHA), `B-` (BETA), `P-` (PROD), `E-` (EXTENSION-PROD), `F-` (FUTURE). Внутри фазы тикеты упорядочены по зависимостям.

**Рекомендуемый порядок выполнения фазы MVP:**
1. **M-00** (Bootstrap) — обязательно первым.
2. Параллельно: **M-01** (LLM-шов) + **M-02** (config) + **M-03** (DB-схема).
3. Последовательно: **M-04** (LangGraph core) → **M-05** (system-prompt) → **M-06** (context-manager).
4. Параллельно: **M-07**…**M-11** (5 базовых tools).
5. **M-12** (tool-registry integration) — после всех tools.
6. **M-13** (permissions) — параллельно с M-12.
7. **M-14** (session-log + JSONL projection).
8. **M-15** (Chainlit UI: on_chat_start, on_message, streaming).
9. **M-16** (Chainlit UI: ask-prompt для interrupt_before).
10. **M-17** (Chainlit UI: sidebar сессий, settings).
11. **M-18** (smoke-тесты 5 эталонных задач).
12. **M-19** (README + ARCHITECT4/ROADMAP4 cross-links).

### 0.2. Структура тикета

```
### {ID} — {Title}
> Component: {ARCHITECT4 §ref} | Dependencies: {IDs} | Estimate: {days/hours}
#### Context
{почему эта задача нужна}
#### Goal
{что сделать}
#### Constraints
{жёсткие ограничения}
#### Acceptance Criteria
- {проверяемое условие 1}
- {проверяемое условие 2}
#### Forbidden patterns
{что нельзя делать}
#### Suggested files
- {file1}
- {file2}
```

### 0.3. Глобальные правила для агента-исполнителя

1. **Перед стартом каждого тикета** прочитать соответствующие §ref из `ARCHITECT4.md` и `ROADMAP4.md`.
2. **Не выходить за рамки фазы.** Любые фичи из следующих фаз — запрещены.
3. **TRIZ-gates встраиваются с первого дня.** Их нельзя «отложить на потом» (см. ROADMAP4 §12).
4. **Все env-dependent параметры** — через `pydantic-settings`, никаких хардкодов.
5. **Все SQL-миграции** — через Alembic, идемпотентные, с `downgrade()`.
6. **Self-check перед завершением тикета:**
   - `ruff check app/ tests/` — без ошибок.
   - `mypy app/` — без ошибок (strict-режим для нового кода).
   - `pytest tests/unit/test_*.py` — зелёный.
   - Если тикет добавляет endpoint или UI-фичу: smoke-проверка вручную.
7. **После завершения тикета** — краткий отчёт: что создано, какие §ref закрыты, отклонения от спеки (если есть) и почему.

### 0.4. Соглашения по структуре репозитория

```
.
├── ARCHITECT4.md                # источник истины
├── ROADMAP4.md                  # источник фаз
├── BACKLOG4.md                  # этот документ
├── docker-compose.yml           # M-00
├── pyproject.toml               # M-00
├── .env.example                 # M-00
├── alembic.ini                  # M-00
├── alembic/versions/            # M-03, M-14, …
├── app/
│   ├── __init__.py
│   ├── config.py                # M-02
│   ├── main.py                  # M-00 (FastAPI app factory для BETA+)
│   ├── core/
│   │   ├── llm.py               # M-01
│   │   ├── graph.py             # M-04
│   │   ├── prompt.py            # M-05
│   │   ├── context.py           # M-06
│   │   ├── session.py           # M-14
│   │   └── policy.py            # M-13
│   ├── tools/
│   │   ├── __init__.py          # M-12 (registry)
│   │   ├── file_ops.py          # M-07, M-08, M-09
│   │   ├── bash.py              # M-10
│   │   ├── search.py            # M-11
│   │   └── oriahs.py            # P-01 (PROD)
│   ├── ui/
│   │   └── chainlit_app.py      # M-15, M-16, M-17
│   ├── api/
│   │   ├── deps.py              # M-00
│   │   └── routes/              # B-08 (BETA)
│   ├── db/
│   │   ├── session.py           # M-00
│   │   ├── models/              # M-03
│   │   └── queries/             # M-14
│   └── observability/
│       ├── metrics.py           # A-04
│       └── logging.py           # A-04
├── tests/
│   ├── unit/
│   ├── integration/
│   └── e2e/
│       └── test_smoke.py        # M-18
└── scripts/
    └── run_eval.sh              # A-05
```

---

## 1. Фаза MVP (M-00 … M-19)

### M-00 — Bootstrap проекта

> **Component:** ARCHITECT4 §5, §13 | **Dependencies:** — | **Estimate:** 4 часа

#### Context
Проект начинается с нуля. Нужен рабочий `docker-compose up` (Postgres + Redis), skeleton `app/`, базовый конфиг, чтобы все последующие тикеты опирались на готовую инфраструктуру.

#### Goal
Создать минимальный рабочий репозиторий: `docker-compose.yml` (postgres, redis), `pyproject.toml` со всеми зависимостями, skeleton `app/` с FastAPI app factory, `pydantic-settings`-конфиг, `.env.example`, `alembic init alembic/`.

#### Constraints
- PostgreSQL 16 + расширения `pgcrypto`, `pgvector` (для BETA+).
- Redis 7 (для cache и rate-limits).
- Python 3.11+.
- Пакетный менеджер — `uv`.
- Все порты вынести в `.env`: `POSTGRES_PORT=5433`, `REDIS_PORT=6379`, `API_PORT=8000`, `CHAINLIT_PORT=8000`.
- `pydantic-settings` читает из `.env` + из окружения (priority: env > .env).
- `app/main.py` — FastAPI app factory (`create_app() -> FastAPI`), не глобальный `app = FastAPI()`.
- Health-endpoints пока заглушки (наполним в A-04).

#### Acceptance Criteria
- `docker compose up -d` поднимает 2 контейнера (postgres, redis), оба проходят healthcheck.
- `uv sync` устанавливает все зависимости без ошибок.
- `uvicorn app.main:app --reload` стартует; `GET /` возвращает `{"status": "ok"}`.
- `alembic upgrade head` выполняется без ошибок (пока без миграций — `alembic init` создаёт пустую `alembic/versions/`).
- `ruff check app/` — зелёный.
- `mypy app/` — зелёный (минимальная конфигурация, strict на новых файлах).
- `pytest` — зелёный (один smoke-тест на `create_app()`).
- `.env.example` содержит все переменные из `app/config.py` с примерами значений.

#### Forbidden patterns
- Не использовать глобальные `app = FastAPI()` — только factory.
- Не хардкодить хосты/порты — только через `pydantic-settings`.
- Не использовать `requirements.txt` — только `pyproject.toml` с `uv`.
- Не добавлять фичи из ALPHA+ (auth, rate-limits, observability).

#### Suggested files
- `docker-compose.yml`
- `pyproject.toml`
- `.env.example`
- `alembic.ini`
- `alembic/env.py`
- `alembic/script.py.mako`
- `app/__init__.py`
- `app/main.py`
- `app/config.py`
- `app/api/deps.py`
- `app/db/session.py`
- `tests/conftest.py`
- `tests/test_smoke.py`
- `README.md`

---

### M-01 — LLM-provider-seam (LangChain init_chat_model)

> **Component:** ARCHITECT4 §6.1 | **Dependencies:** M-00 | **Estimate:** 4 часа

#### Context
LLM-шов — единственный невосполнимый архитектурный шов. Не делается с первого дня → переписывание ядра. LangChain `init_chat_model()` даёт 60+ адаптеров из коробки.

#### Goal
Реализовать `app/core/llm.py` с функцией `get_chat_model()`, которая через `init_chat_model()` создаёт `BaseChatModel` по конфигу. Поддержка двух провайдеров: `anthropic:claude-3-5-sonnet-latest` и `openai:gpt-4o`.

#### Constraints
- Использовать `langchain.chat_models.init_chat_model`.
- `streaming=True`, `timeout` из конфига (default 60 сек).
- `temperature` и `max_tokens` — из конфига.
- Модель биндится к tool-registry через `bind_tools()` (реестр пока пустой, подключим в M-12).
- API-ключи только из env (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`).
- `pydantic-settings`-поле `llm_model: str = "anthropic:claude-3-5-sonnet-latest"`.

#### Acceptance Criteria
- `get_chat_model()` возвращает `BaseChatModel`-инстанс.
- Переключение провайдера — одной строкой `.env` (`LLM_MODEL=openai:gpt-4o`).
- Streaming работает: `async for chunk in model.astream("hi"): print(chunk.content)` печатает токены.
- Unit-тест: mock `init_chat_model`, проверить что параметры передаются корректно.
- При отсутствии API-ключа в env — понятная ошибка `ValueError("ANTHROPIC_API_KEY not set")`.

#### Forbidden patterns
- Не использовать `langchain_anthropic.ChatAnthropic` напрямую — только через `init_chat_model`.
- Не хардкодить model-name в коде — только в конфиге.
- Не использовать sync-методы (`invoke`, `generate`) — только async (`ainvoke`, `astream`).

#### Suggested files
- `app/core/llm.py`
- `app/core/__init__.py`
- `tests/unit/test_llm.py`

---

### M-02 — pydantic-settings конфиг

> **Component:** ARCHITECT4 §4.3, §13 | **Dependencies:** M-00 | **Estimate:** 3 часа

#### Context
Все env-dependent параметры должны быть в одном месте, типизированы, с дефолтами. `pydantic-settings` — стандарт для Python 3.11+.

#### Goal
Реализовать `app/config.py` с классом `Settings(BaseSettings)`, содержащим все конфиг-параметры для всех фаз (MVP + ALPHA + BETA + PROD). Параметры для будущих фаз — с дефолтами, не используются в MVP.

#### Constraints
- `Settings` наследует `BaseSettings` (pydantic-settings v2).
- Конфиг из `.env` + из env (priority: env > .env).
- Все поля типизированы (`str`, `int`, `float`, `bool`, `HttpUrl`).
- Секция LLM: `llm_model`, `llm_temperature`, `llm_max_tokens`, `llm_timeout_s`.
- Секция DB: `database_url`, `database_pool_size`, `database_max_overflow`.
- Секция Redis: `redis_url`.
- Секция OriaHS (для PROD, но параметр существует): `oriahs_url`, `oriahs_timeout_s`.
- Секция Auth (для ALPHA): `auth_secret_key`, `auth_algorithm`.
- Секция Observability (для ALPHA): `langsmith_api_key`, `otel_exporter_otlp_endpoint`.
- Секция UI: `chainlit_port`, `nextjs_port` (для BETA).
- `Settings()` — singleton через `lru_cache`.

#### Acceptance Criteria
- `from app.config import settings; settings.llm_model` работает.
- Все поля имеют дефолты, кроме `database_url`, `redis_url` (обязательные).
- `.env.example` содержит все поля с примерами значений.
- Unit-тест: переопределение через env-переменные работает (`os.environ["LLM_MODEL"] = "openai:gpt-4o"`).
- `mypy app/config.py` — strict-зелёный.

#### Forbidden patterns
- Не использовать `os.getenv` напрямую — только через `Settings`.
- Не хардкодить дефолты в коде, использующем `Settings` — только в самом классе.
- Не использовать `pydantic.BaseSettings` (v1) — только `pydantic_settings.BaseSettings` (v2).

#### Suggested files
- `app/config.py`
- `.env.example`
- `tests/unit/test_config.py`

---

### M-03 — PostgreSQL-схема (orya_sessions)

> **Component:** ARCHITECT4 §7.1 | **Dependencies:** M-00 | **Estimate:** 1 день

#### Context
Схема `orya_sessions` — отдельная от OriaHS `public`. Содержит таблицы LangGraph `PostgresSaver` (создаются автоматически через `.setup()`) и кастомные таблицы OryaAgent.

#### Goal
Создать Alembic-миграцию `001_initial_schema`, создающую схему `orya_sessions` и таблицы `sessions`, `tool_invocations`, `events` (партиционированную).

#### Constraints
- `CREATE SCHEMA IF NOT EXISTS orya_sessions;`
- Таблица `orya_sessions.sessions`: `thread_id UUID PK`, `user_id UUID` (nullable для MVP), `title TEXT`, `created_at TIMESTAMPTZ`, `updated_at TIMESTAMPTZ`, `metadata JSONB`.
- Таблица `orya_sessions.tool_invocations`: `id BIGSERIAL PK`, `thread_id UUID FK`, `tool_name TEXT`, `args JSONB`, `result JSONB`, `started_at TIMESTAMPTZ`, `finished_at TIMESTAMPTZ`, `status TEXT CHECK (status IN ('running','ok','failed','dead'))`, `error TEXT`.
- Индекс `orya_sessions.tool_invocations_thread_idx (thread_id, started_at DESC)`.
- Таблица `orya_sessions.events` — партиционированная по `created_at` RANGE, с партицией по умолчанию `events_default`.
- Колонки events: `id BIGSERIAL`, `thread_id UUID`, `event_type TEXT`, `payload JSONB`, `created_at TIMESTAMPTZ`, `PRIMARY KEY (id, created_at)`.
- Не создавать таблицы `PostgresSaver` (`checkpoints`, `writes`, …) — их создаст `.setup()` в M-14.
- `downgrade()` — откатывает чисто (DROP TABLE + DROP SCHEMA).

#### Acceptance Criteria
- `alembic upgrade head` создаёт схему и 3 таблицы.
- `\d orya_sessions.sessions` показывает все колонки.
- `\d orya_sessions.tool_invocations` показывает CHECK-constraint на `status`.
- `\d+ orya_sessions.events` показывает `Partitioned table` и партицию `events_default`.
- `alembic downgrade base` — откатывает чисто.
- Unit-тест: вставка + чтение в каждой таблице.

#### Forbidden patterns
- Не использовать `TIMESTAMP` без TZ — только `TIMESTAMPTZ`.
- Не забыть партиционирование `events` (TRIZ-gate).
- Не забыть `CHECK`-constraint на `status` в `tool_invocations` (TRIZ-gate — `dead`-состояние).
- Не создавать таблицы для BETA+ (memory, mcp, skills).

#### Suggested files
- `alembic/versions/001_initial_schema.py`
- `app/db/models/__init__.py`
- `app/db/models/session.py`
- `app/db/models/tool_invocation.py`
- `tests/unit/test_models.py`

---

### M-04 — LangGraph core (StateGraph)

> **Component:** ARCHITECT4 §6.2 | **Dependencies:** M-01, M-02, M-03 | **Estimate:** 1 день

#### Context
Agent-loop — определение агента. LangGraph `StateGraph` даёт цикл «запрос → tools → ответ» с прерываниями и чекпоинтами без кастомного кода.

#### Goal
Реализовать `app/core/graph.py` с функцией `build_graph(tools, model, checkpointer, policy) -> CompiledGraph`. Граф с узлами `agent`, `tools`, `human`.

#### Constraints
- Использовать `langgraph.graph.StateGraph` с `MessagesState`.
- Узел `agent`: вызывает `model.ainvoke([sys_prompt, *state["messages"]])`, возвращает `{"messages": [response]}`.
- Узел `tools`: `langgraph.prebuilt.ToolNode(tools)`.
- Узел `human`: вызывается только при `interrupt_before=['tools']`; вызывает `policy.review()`.
- `add_edge(START, "agent")`.
- `add_conditional_edges("agent", route_after_agent)` — маршрут в `tools` если есть tool_calls, иначе в `END`.
- `add_edge("tools", "agent")`.
- `add_edge("human", "tools")`.
- `compile(checkpointer=checkpointer, interrupt_before=['tools'] if policy.ask_mode else [])`.
- `recursion_limit=25` (параметр compile).

#### Acceptance Criteria
- `build_graph(...)` возвращает `CompiledGraph`-инстанс.
- `graph.ainvoke({"messages": [HumanMessage("hi")]}, config)` возвращает ответ с `ai_message`.
- Без tools: `route_after_agent` идёт в `END`.
- С tools: `route_after_agent` идёт в `tools`, потом обратно в `agent`.
- В `ask`-режиме: `interrupt_before` срабатывает перед `tools`; `graph.aget_state(config).next == ('tools',)`.
- Unit-тест с mock-model и mock-tools проверяет все 3 сценария.

#### Forbidden patterns
- Не использовать `langchain.agents.AgentExecutor` — только LangGraph.
- Не хардкодить `recursion_limit` — из конфига.
- Не встраивать логику cron/goals/workflows — это FUTURE.

#### Suggested files
- `app/core/graph.py`
- `tests/unit/test_graph.py`

---

### M-05 — System-prompt-builder

> **Component:** ARCHITECT4 §6.3 | **Dependencies:** M-04 | **Estimate:** 4 часа

#### Context
System-prompt — основной механизм управления поведением агента. У всех 5 архитектур из `agents-architect.md` есть отдельный модуль для сборки промпта. LangChain `ChatPromptTemplate` даёт кэшируемый префикс для prompt-cache.

#### Goal
Реализовать `app/core/prompt.py` с функцией `build_system_prompt(state, tools) -> list[BaseMessage]`. Использует `ChatPromptTemplate` с секциями: identity, tool-описания, project-context, user-memory, behavior-rules.

#### Constraints
- Использовать `langchain_core.prompts.ChatPromptTemplate`.
- Template — строка с `{placeholders}`.
- Секции:
  - Identity: «You are OryaAgent, a coding agent that helps with software engineering tasks…»
  - Tool-описания: `format_tools(tools)` — список `name: description` для каждого tool.
  - Project-context: `cwd`, `git_status` (если есть `.git/`).
  - User-memory: `~/.orya/memory.md` если существует; иначе пустая строка.
  - Project-memory: `ORYA.md` если существует в cwd; иначе пустая строка.
  - Behavior-rules: 4-5 правил (before bash explain, after edit re-read, outline plan for multi-file, ask if uncertain).
- Возвращать `list[BaseMessage]` — `[SystemMessage(content=...), *state["messages"]]`.
- Cacheable prefix: первые 3 секции (identity + tools + behavior-rules) — стабильные; последние 2 (context + memory) — динамические.

#### Acceptance Criteria
- `build_system_prompt(state, tools)` возвращает список с `SystemMessage` первым.
- `len(messages) == 1 + len(state["messages"])`.
- Если `~/.orya/memory.md` не существует — секция пустая, но не None.
- Если `ORYA.md` не существует — секция пустая.
- `git_status` корректно отображается (через `subprocess.run(["git", "status", "--short"])`).
- Unit-тест: mock `tools`, проверить что `tool_descriptions` содержит имена всех tools.

#### Forbidden patterns
- Не использовать f-strings для шаблонов — только `ChatPromptTemplate`.
- Не хардкодить поведение в шаблоне (например, "always use Python 3.11") — это в user-memory.
- Не вставлять динамические данные в cacheable prefix.

#### Suggested files
- `app/core/prompt.py`
- `tests/unit/test_prompt.py`

---

### M-06 — Context-manager (trim_messages)

> **Component:** ARCHITECT4 §6.6 | **Dependencies:** M-04 | **Estimate:** 3 часа

#### Context
Окно контекста конечно у всех провайдеров. LangChain `trim_messages` даёт стандартные стратегии управления окном.

#### Goal
Реализовать `app/core/context.py` с функцией `trim_state(state, max_tokens=128_000) -> MessagesState`. Использует `langchain_core.messages.trim_messages`.

#### Constraints
- Использовать `langchain_core.messages.trim_messages`.
- `strategy="last"` — оставлять последние N.
- `start_on="human"` — не разрывать посередине turn'а.
- `allow_partial=False` — не разрывать сообщения.
- `include_system=True` — system-prompt всегда в начале.
- `token_counter=lambda msgs: count_tokens(msgs)` — кастомный каунтер через `tiktoken` (для OpenAI/Anthropic) или approximation (`chars/4`).
- Урезание длинных tool-результатов: если `ToolMessage.content` > 5000 символов → первые 100 строк + `... [N lines truncated] ...` + последние 50 строк.
- `max_tokens` из конфига (default 128_000).

#### Acceptance Criteria
- `trim_state(state, max_tokens=10000)` урезает длинную историю до 10000 токенов.
- SystemMessage сохраняется всегда, даже если `max_tokens` маленький.
- Длинный `ToolMessage` (10000 строк) урезается до ~150 строк + truncation-marker.
- Unit-тест: mock `count_tokens`, проверить что `trim_messages` вызывается с правильными параметрами.

#### Forbidden patterns
- Не использовать собственный алгоритм урезания — только `trim_messages`.
- Не удалять SystemMessage никогда.
- Не использовать `tiktoken.encoding_for_model` для unknown моделей — fallback на approximation.

#### Suggested files
- `app/core/context.py`
- `tests/unit/test_context.py`

---

### M-07 — Tool: read

> **Component:** ARCHITECT4 §6.4 | **Dependencies:** M-04 | **Estimate:** 4 часа

#### Context
`read` — самый частый tool. Все 5 архитектур имеют его. Pagination важен для больших файлов.

#### Goal
Реализовать `app/tools/file_ops.py::read` tool через `@tool`-декоратор.

#### Constraints
- `@tool(args_schema=ReadInput)` с Pydantic-схемой.
- `ReadInput`: `path: str`, `start: int | None = None`, `limit: int | None = None`.
- Возвращает строку с line-numbers (`cat -n`-style): `   1\tfirst line\n   2\tsecond line\n...`.
- Binary-detection: если файл содержит `\x00` bytes → возвращать `"Binary file, {size} bytes"`.
- Symlink-resolution через `Path.resolve()`.
- Path-validation через `validate_path()` (в `app/tools/_validators.py`) — должен быть внутри cwd или `~/.orya/`.
- Pagination: `start` (1-indexed) + `limit` (default 2000).
- Max file size: 10MB; если больше — error `"File too large, use grep or read with start/limit"`.

#### Acceptance Criteria
- `await read.ainvoke({"path": "README.md"})` возвращает содержимое с line-numbers.
- `await read.ainvoke({"path": "README.md", "start": 10, "limit": 5})` возвращает строки 10-14.
- `await read.ainvoke({"path": "/etc/passwd"})` падает с `ToolException("Path outside allowed roots")`.
- Binary-файл возвращает `"Binary file, X bytes"`.
- Файл 11MB падает с `ToolException("File too large")`.
- Unit-тест покрывает все сценарии.

#### Forbidden patterns
- Не использовать `open()` sync — только `aiofiles.open` или `pathlib.Path.read_text`.
- Не возвращать bytes — только str.
- Не забывать path-validation.

#### Suggested files
- `app/tools/file_ops.py`
- `app/tools/_validators.py`
- `app/tools/__init__.py`
- `tests/unit/test_tools_file_ops.py`

---

### M-08 — Tool: write

> **Component:** ARCHITECT4 §6.4 | **Dependencies:** M-07 | **Estimate:** 3 часа

#### Context
`write` — атомарная запись файла. Atomicity через temp-file + rename.

#### Goal
Реализовать `app/tools/file_ops.py::write` tool.

#### Constraints
- `@tool(args_schema=WriteInput)`.
- `WriteInput`: `path: str`, `content: str`.
- Атомарность: write to `{path}.tmp.{pid}` → `os.rename` to `{path}`.
- Path-validation.
- Создание родительских директорий: `Path(path).parent.mkdir(parents=True, exist_ok=True)`.
- Backup в dev-режиме (`ORYA_DEV=true`): `{path}.bak` перед записью.
- Возвращает `"Wrote {n} bytes to {path}"`.

#### Acceptance Criteria
- `await write.ainvoke({"path": "test.txt", "content": "hello"})` создаёт файл.
- Повторный вызов с тем же `path` перезаписывает.
- В dev-режиме создаётся `test.txt.bak`.
- Path-validation: `path: "/etc/test"` падает.
- Родительские директории создаются (`path: "subdir/test.txt"`).
- Unit-тест проверяет atomicity (mock `os.rename`, проверить что был вызов).

#### Forbidden patterns
- Не использовать `Path.write_text` напрямую — только temp-file + rename.
- Не перезаписывать без backup в dev-режиме.
- Не забывать path-validation.

#### Suggested files
- `app/tools/file_ops.py` (extend)
- `tests/unit/test_tools_file_ops.py` (extend)

---

### M-09 — Tool: edit

> **Component:** ARCHITECT4 §6.4 | **Dependencies:** M-07 | **Estimate:** 4 часа

#### Context
`edit` — точечная замена. Требует уникальности `old_string` для безопасности.

#### Goal
Реализовать `app/tools/file_ops.py::edit` tool.

#### Constraints
- `@tool(args_schema=EditInput)`.
- `EditInput`: `path: str`, `old_string: str`, `new_string: str`, `replace_all: bool = False`.
- Если `old_string` встречается > 1 раза и `replace_all=False` → `ToolException("old_string is not unique; use replace_all=True or provide more context")`.
- Если `old_string` не найден → `ToolException("old_string not found in {path}")`.
- Atomicity: read → modify in memory → write через temp-file + rename (как в M-08).
- Path-validation.
- Возвращает `"Edited {path}: replaced {n} occurrence(s)"`.

#### Acceptance Criteria
- Уникальный `old_string` → успешно заменяется.
- Неуникальный `old_string` без `replace_all` → `ToolException`.
- `replace_all=True` → все вхождения заменяются.
- Несуществующий `old_string` → `ToolException`.
- Path-validation работает.
- Unit-тест покрывает все сценарии.

#### Forbidden patterns
- Не использовать `str.replace` без проверки уникальности.
- Не забывать atomicity.
- Не использовать regex — только exact match.

#### Suggested files
- `app/tools/file_ops.py` (extend)
- `tests/unit/test_tools_file_ops.py` (extend)

---

### M-10 — Tool: bash

> **Component:** ARCHITECT4 §6.4 | **Dependencies:** M-07 | **Estimate:** 1 день

#### Context
`bash` — самый опасный tool. Ask-mode обязателен. Timeout и abort — критичны.

#### Goal
Реализовать `app/tools/bash.py::bash` tool.

#### Constraints
- `@tool(args_schema=BashInput)`.
- `BashInput`: `command: str`, `timeout: int = 30`.
- Использовать `asyncio.create_subprocess_exec("/bin/bash", "-c", command)`.
- Timeout через `asyncio.wait_for(proc.communicate(), timeout=timeout)`.
- При timeout: `proc.kill()` + `ToolException("Command timed out after {timeout}s")`.
- AbortController: если задача отменена (CancelledError), `proc.kill()`.
- Возвращает `"stdout:\n{stdout}\nstderr:\n{stderr}\nexit: {code}"`.
- Truncate output: если > 10000 символов → первые 5000 + `... [truncated] ...` + последние 5000.
- Env-control: `subprocess_env = {**os.environ, "TERM": "dumb"}`.

#### Acceptance Criteria
- `await bash.ainvoke({"command": "echo hello"})` возвращает `"stdout:\nhello\n..."`.
- `await bash.ainvoke({"command": "sleep 100", "timeout": 1})` падает с timeout.
- Cancelled subprocess корректно kill'ится.
- Long output (>10k chars) урезается.
- Unit-тест с mock `asyncio.create_subprocess_exec`.

#### Forbidden patterns
- Не использовать `subprocess.run` (sync) — только async.
- Не использовать `shell=True` — только `/bin/bash -c`.
- Не забывать kill при timeout/cancel.

#### Suggested files
- `app/tools/bash.py`
- `tests/unit/test_tools_bash.py`

---

### M-11 — Tool: grep/glob

> **Component:** ARCHITECT4 §6.4 | **Dependencies:** M-07 | **Estimate:** 4 часа

#### Context
`grep` — обёртка над ripgrep. Все 5 архитектур используют `rg`.

#### Goal
Реализовать `app/tools/search.py::grep` tool.

#### Constraints
- `@tool(args_schema=GrepInput)`.
- `GrepInput`: `pattern: str`, `glob: str | None = None`, `path: str = "."`, `type: str | None = None`.
- Использовать `rg --json --line-number --with-filename {pattern}`.
- Парсить JSON-output, возвращать `file:line:content` для каждого match.
- Glob: `--glob "{glob}"`.
- Type: `--type {type}` (например, `py`, `js`).
- Path-validation.
- Max matches: 500 (configurable); если больше — truncation marker.
- Возвращает `"Matches in {N} files:\n{file}:{line}:{content}\n..."`.

#### Acceptance Criteria
- `await grep.ainvoke({"pattern": "def test_"})` возвращает matches в `tests/`.
- `glob: "*.py"` фильтрует только Python-файлы.
- `type: "py"` работает аналогично.
- Path-validation: `path: "/etc"` падает.
- > 500 matches → truncation.
- Unit-тест с mock `asyncio.create_subprocess_exec` для `rg`.

#### Forbidden patterns
- Не использовать `re` для search — только `rg` subprocess.
- Не использовать `glob.glob` — только `rg --glob`.
- Не забывать path-validation.

#### Suggested files
- `app/tools/search.py`
- `tests/unit/test_tools_search.py`

---

### M-12 — Tool-registry integration

> **Component:** ARCHITECT4 §6.4 | **Dependencies:** M-07..M-11 | **Estimate:** 3 часа

#### Context
Все 5 tools созданы; нужно собрать их в реестр и подключить к graph.

#### Goal
Реализовать `app/tools/__init__.py` с функцией `get_registered_tools() -> list[BaseTool]` и обновить `app/core/llm.py::get_chat_model()` для использования `bind_tools()`.

#### Constraints
- `get_registered_tools()` возвращает список `[read, write, edit, bash, grep]`.
- Импорт через `from app.tools.file_ops import read, write, edit`, `from app.tools.bash import bash`, `from app.tools.search import grep`.
- В `get_chat_model()` добавить `.bind_tools(get_registered_tools())`.
- В `build_graph()` передавать `get_registered_tools()` в `ToolNode`.

#### Acceptance Criteria
- `get_registered_tools()` возвращает 5 tools.
- `model = get_chat_model()` имеет bound tools.
- `await model.ainvoke("read README.md")` возвращает ToolCall.
- `await graph.ainvoke({"messages": [HumanMessage("read README.md")]})` вызывает `read` tool.
- E2E-тест: полный цикл agent → tools → agent.

#### Forbidden patterns
- Не хардкодить список tools в `graph.py` — только через `get_registered_tools()`.
- Не добавлять MCP/OriaHS tools (это BETA/PROD).

#### Suggested files
- `app/tools/__init__.py`
- `app/core/llm.py` (update)
- `app/core/graph.py` (update)
- `tests/integration/test_tools_integration.py`

---

### M-13 — Permissions (interrupt_before + policy)

> **Component:** ARCHITECT4 §6.8, §12 | **Dependencies:** M-04, M-12 | **Estimate:** 1 день

#### Context
Bash без подтверждения — недопустимо в MVP. LangGraph `interrupt_before` даёт human-in-the-loop без кастомного кода.

#### Goal
Реализовать `app/core/policy.py` с классом `PermissionPolicy` и обновить `build_graph()` для использования `interrupt_before`.

#### Constraints
- `PermissionPolicy` с двумя режимами: `ask` (default) и `auto`.
- `allow_rules: list[dict]` — список `{"tool": "bash", "pattern": "ls *"}`.
- `review(tool_calls: list[dict]) -> Decision`:
  - Если mode == "auto" → ALLOW.
  - Для каждого tool_call: check allow_rules; если match → ALLOW.
  - Если tool в `("read", "grep")` → ALLOW (read-only safe).
  - Иначе → ASK.
- Загрузка конфига из `~/.orya/permissions.yml`:
  ```yaml
  mode: ask
  allow:
    - tool: bash
      pattern: "ls *"
    - tool: bash
      pattern: "git status"
  ```
- В `build_graph()`: `compile(interrupt_before=['tools'] if policy.ask_mode else [])`.
- В `human`-узле графа: вызывать `policy.review(last_msg.tool_calls)`.
- Если DENY → возвращать `ToolMessage(content="Denied by user")`.
- Если ALLOW → `return None` (граф продолжит в `tools`).

#### Acceptance Criteria
- В `ask`-режиме: `graph.ainvoke(...)` прерывается перед `tools`; `graph.aget_state(config).next == ('tools',)`.
- В `auto`-режиме: `tools` вызывается без прерывания.
- Allow-rule `bash: ls *` разрешает `bash ls -la` без ASK.
- `read` и `grep` всегда разрешены.
- `write`, `edit`, `bash` (без allow-rule) → ASK.
- Unit-тест с mock `policy`.

#### Forbidden patterns
- Не использовать `re.match` без `^` и `$` — паттерны должны быть точными.
- Не забыть read-only safe tools.
- Не встраивать sandbox (это PROD).

#### Suggested files
- `app/core/policy.py`
- `app/core/graph.py` (update)
- `~/.orya/permissions.yml` (пример)
- `tests/unit/test_policy.py`

---

### M-14 — Session-log (PostgresSaver + JSONL projection)

> **Component:** ARCHITECT4 §6.5, §7.1 | **Dependencies:** M-03, M-04 | **Estimate:** 1 день

#### Context
Сессия — поток событий. LangGraph `PostgresSaver` даёт ACID-checkpointing. JSONL projection — для аудита и экспорта.

#### Goal
Реализовать `app/core/session.py` с `get_checkpointer()` (возвращает `AsyncPostgresSaver`) и `project_to_jsonl(thread_id)` (воркер, читающий новые checkpoints и дописывающим в JSONL).

#### Constraints
- Использовать `langgraph.checkpoint.postgres.aio.AsyncPostgresSaver`.
- `from_conn_string(settings.database_url)`.
- `await saver.setup()` — создаёт таблицы `checkpoints`, `writes`, … в схеме `orya_sessions` (или public — configurable).
- JSONL projection: отдельный async-воркер, запускаемый при старте приложения.
- Воркер читает `graph.aget_state_history(config)` и дописывает новые events в `~/.orya/sessions/{thread_id}.jsonl`.
- Формат JSONL: одна строка на event, `{"ts": "...", "type": "...", "payload": {...}}`.
- Дедупликация: воркер хранит `last_processed_ts` в `~/.orya/sessions/{thread_id}.meta.json`.
- `~/.orya/sessions/` создаётся при старте, если не существует.

#### Acceptance Criteria
- `await get_checkpointer()` возвращает `AsyncPostgresSaver`-инстанс.
- `await saver.setup()` создаёт таблицы в БД.
- После `graph.ainvoke(...)`: `~/.orya/sessions/{thread_id}.jsonl` содержит ≥ 3 events (user, ai, tool).
- Повторный запуск воркера не дублирует events (дедупликация по `ts`).
- После `Ctrl+C` и рестарта: `graph.aget_state(config)` возвращает последнее состояние.
- Unit-тест с mock `AsyncPostgresSaver`.

#### Forbidden patterns
- Не использовать sync `PostgresSaver` — только async.
- Не забывать `.setup()` перед использованием.
- Не хардкодить путь `~/.orya/sessions/` — из конфига.

#### Suggested files
- `app/core/session.py`
- `tests/unit/test_session.py`

---

### M-15 — Chainlit UI: on_chat_start, on_message, streaming

> **Component:** ARCHITECT4 §6.7.1, §11 | **Dependencies:** M-04, M-12, M-14 | **Estimate:** 1 день

#### Context
UI — «нормальный с первого дня». Chainlit даёт markdown + code-blocks + streaming + tool-step-карточки за один Python-файл.

#### Goal
Реализовать `app/ui/chainlit_app.py` с `@cl.on_chat_start` и `@cl.on_message` handlers. Streaming ответов через `astream_events`.

#### Constraints
- `@cl.on_chat_start`: создать graph, сгенерировать `thread_id = str(uuid4())`, сохранить в `cl.user_session`.
- `@cl.on_message`:
  - Получить graph и thread_id из `cl.user_session`.
  - `config = {"configurable": {"thread_id": thread_id}}`.
  - Если `graph.aget_state(config).next == ('tools',)` → это resume после interrupt (обработаем в M-16).
  - Иначе: `async for event in graph.astream_events({"messages": [HumanMessage(message.content)]}, config, version="v2")`.
  - При `event["event"] == "on_chat_model_stream"`: `await cl.Message(content=token).stream_token()`.
  - При `event["event"] == "on_tool_start"`: `async with cl.Step(name=event["name"]) as step: step.input = event["data"].get("input")`.
  - При `event["event"] == "on_tool_end"`: `step.output = event["data"].get("output")`.
- Markdown и code-blocks — встроены в Chainlit.
- Sidebar с сессиями — Chainlit-нативный `cl.ChatSettings` (простейший список).
- `chainlit run app/ui/chainlit_app.py --port 8000` поднимает UI.

#### Acceptance Criteria
- Открывается `http://localhost:8000`, виден chat-интерфейс.
- Сообщение «прочитай README.md» → агент вызывает `read`, возвращает содержимое с markdown.
- Streaming токенов работает (видно постепенный набор текста).
- Tool-call отображается как step-карточка с input/output.
- После refresh страницы — история сессии восстанавливается.
- Перезапуск `chainlit run` — можно продолжить сессию (по thread_id из URL или sidebar).

#### Forbidden patterns
- Не использовать `cl.Message(content=full_response).send()` (без streaming) — только `stream_token`.
- Не хардкодить `thread_id` — генерировать.
- Не использовать sync graph-методы — только async.

#### Suggested files
- `app/ui/chainlit_app.py`
- `app/ui/__init__.py`
- `tests/e2e/test_chainlit_smoke.py`

---

### M-16 — Chainlit UI: ask-prompt для interrupt_before

> **Component:** ARCHITECT4 §6.7.1, §6.8 | **Dependencies:** M-13, M-15 | **Estimate:** 4 часа

#### Context
`interrupt_before=['tools']` прерывает граф перед tool-execution. Нужно показать пользователю ask-prompt и продолжить граф по решению.

#### Goal
Расширить `app/ui/chainlit_app.py`: при `graph.aget_state(config).next == ('tools',)` показать `cl.AskActionMessage` с кнопками Allow/Deny.

#### Constraints
- В `@cl.on_message`: первой строкой проверить `state = await graph.aget_state(config)`.
- Если `state.next == ('tools',)`:
  - Получить `last_msg = state.values["messages"][-1]`.
  - Получить `tool_calls = last_msg.tool_calls`.
  - Показать `cl.AskActionMessage(content=f"Agent wants to call: {tool_calls}", actions=[{"label":"Allow","value":"allow"},{"label":"Deny","value":"deny"}])`.
  - Если `response == "allow"`: `await graph.ainvoke(None, config, command=Command(resume="allow"))`.
  - Если `response == "deny"`: `await graph.ainvoke(None, config, command=Command(resume="deny"))`.
- Иначе: обычный flow (см. M-15).
- `human`-узел графа (M-13) читает resume-значение и возвращает `ToolMessage("Denied by user")` при deny.

#### Acceptance Criteria
- Сообщение «удали файл test.txt» → агент хочет вызвать `bash rm test.txt`.
- Появляется ask-prompt с кнопками Allow/Deny.
- Allow → tool выполняется.
- Deny → tool возвращает "Denied by user", агент продолжает.
- При allow-rule для `bash: ls *`: `bash ls -la` не вызывает ask-prompt (allow-list работает).
- E2E-тест: 3 сценария (allow, deny, allow-list-skip).

#### Forbidden patterns
- Не блокировать event-loop во время ожидания ответа — `cl.AskActionMessage` async.
- Не забывать Command(resume=...) — иначе граф не продолжит.

#### Suggested files
- `app/ui/chainlit_app.py` (update)
- `tests/e2e/test_ask_prompt.py`

---

### M-17 — Chainlit UI: sidebar сессий, settings

> **Component:** ARCHITECT4 §6.7.1, §11 | **Dependencies:** M-15, M-16 | **Estimate:** 4 часа

#### Context
Нормальный UI включает sidebar с историей сессий и settings-панель.

#### Goal
Расширить `app/ui/chainlit_app.py`: добавить sidebar с историей сессий (из `~/.orya/sessions/*.jsonl`) и settings-панель (model, mode, allow-list).

#### Constraints
- Sidebar: `cl.ChatSettings` с действиями:
  - "New session" — генерирует новый `thread_id`.
  - "Session list" — показывает последние 10 сессий (по `mtime` файлов).
  - При клике на сессию — переключается `thread_id` в `cl.user_session`.
- Settings: `cl.ChatSettings` с полями:
  - `model` (dropdown: `anthropic:claude-3-5-sonnet-latest`, `openai:gpt-4o`).
  - `mode` (dropdown: `ask`, `auto`).
  - `allow_list` (textarea, newline-separated).
- При изменении settings:
  - `model` → пересоздать `graph` с новым `get_chat_model(model=...)`.
  - `mode` → пересоздать `policy` с новым `mode`.
  - `allow_list` → обновить `policy.allow_rules`.
- Сохранение settings в `~/.orya/settings.json`.

#### Acceptance Criteria
- Sidebar показывает последние 10 сессий.
- Клик на сессию — переключение без потери истории.
- Settings-панель доступна; изменения применяются немедленно.
- Settings сохраняются между запусками.
- E2E-тест: переключение между 2 сессиями.

#### Forbidden patterns
- Не хранить settings в БД — только JSON-файл (для MVP).
- Не блокировать UI при загрузке сессий.

#### Suggested files
- `app/ui/chainlit_app.py` (update)
- `app/ui/settings.py`
- `tests/e2e/test_sidebar.py`

---

### M-18 — Smoke-тесты 5 эталонных задач

> **Component:** ROADMAP4 §3.4 | **Dependencies:** M-12, M-15, M-16 | **Estimate:** 4 часа

#### Context
5 эталонных задач — метрика MVP-готовности. Все 5 должны проходить без падения ядра.

#### Goal
Реализовать `tests/e2e/test_smoke.py` с 5 эталонными задачами.

#### Constraints
- 5 задач:
  1. **Read & answer**: «прочитай README.md и скажи, какой стек используется».
  2. **Grep & locate**: «найди все определения функций `test_` в проекте».
  3. **Edit**: «добавь комментарий в начало main.py».
  4. **Bash**: «запусти `pytest --collect-only` и сообщи количество тестов».
  5. **Create file**: «создай файл `hello.py` с функцией `hello()`.
- Каждая задача — отдельный test-case.
- Mock LLM (через `langchain_core.language_models.FakeListChatModel`) для deterministic behaviour.
- Real tools (read, write, edit, bash, grep) — на реальной FS.
- Setup: temp-директория с минимальным проектом (README.md, main.py, tests/).

#### Acceptance Criteria
- Все 5 тестов проходят в CI.
- Каждый тест завершается за ≤ 30 сек.
- При падении — понятный assert-message.
- Тесты можно запустить: `pytest tests/e2e/test_smoke.py`.

#### Forbidden patterns
- Не использовать real LLM-вызовы (денег стоит, non-deterministic).
- Не использовать real Chainlit — только graph-level tests.

#### Suggested files
- `tests/e2e/test_smoke.py`
- `tests/e2e/conftest.py`
- `tests/fixtures/sample_project/`

---

### M-19 — README + cross-links

> **Component:** — | **Dependencies:** все M-00..M-18 | **Estimate:** 2 часа

#### Context
README — лицо проекта. Cross-links между ARCHITECT4/ROADMAP4/BACKLOG4 — для навигации.

#### Goal
Создать `README.md` с quickstart и обновить cross-links в `ARCHITECT4.md`, `ROADMAP4.md`, `BACKLOG4.md`.

#### Constraints
- README.md секции:
  - What is OryaAgent (1 параграф).
  - Quickstart (5 команд: `git clone`, `cd`, `cp .env.example .env`, `uv sync`, `chainlit run`).
  - Architecture (1 параграф + ссылка на `ARCHITECT4.md`).
  - Roadmap (таблица фаз + ссылка на `ROADMAP4.md`).
  - Backlog (ссылка на `BACKLOG4.md`).
  - Development (`ruff check`, `mypy`, `pytest`).
  - License.
- В ARCHITECT4.md §18 (Связь с фазами) — обновить ссылки на ROADMAP4 §N.
- В ROADMAP4.md §1.2 — обновить ссылку на ARCHITECT4 §N.
- В BACKLOG4.md §0.4 — обновить структуру репозитория.

#### Acceptance Criteria
- `README.md` существует, quickstart работает.
- Все cross-links — валидные markdown-ссылки.
- `make readme-check` (или скрипт) проверяет, что все ссылки живые.

#### Forbidden patterns
- Не дублировать содержание ARCHITECT4/ROADMAP4 в README — только short summary + link.

#### Suggested files
- `README.md`
- `ARCHITECT4.md` (update cross-links)
- `ROADMAP4.md` (update cross-links)

---

## 2. Фаза ALPHA (A-00 … A-12)

### A-00 — Auth: local username/password

> **Component:** ROADMAP4 §4.2.1 | **Dependencies:** MVP done | **Estimate:** 1 день

#### Context
Auth — основа production-safe. Chainlit имеет встроенный auth-module.

#### Goal
Реализовать local auth через Chainlit `PasswordAuthProvider`.

#### Constraints
- `cl.PasswordAuthProvider`-наследник.
- Хранение пользователей в таблице `orya_sessions.users` (новая миграция).
- Пароли — bcrypt.
- Session-token — JWT (HS256), срок 24 часа.
- При первом запуске — создать admin-пользователя из env (`ORYA_ADMIN_USER`, `ORYA_ADMIN_PASSWORD`).

#### Acceptance Criteria
- При открытии UI — экран логина.
- Вход с admin-credentials работает.
- Неверный пароль — ошибка.
- После login — JWT в cookie; refresh страницы не требует re-login.
- Logout-кнопка в settings.

#### Forbidden patterns
- Не хранить пароли в plain text — только bcrypt.
- Не использовать weak JWT-secret — из env, ≥ 32 chars.

#### Suggested files
- `app/auth/local_provider.py`
- `app/auth/jwt_utils.py`
- `alembic/versions/002_users.py`
- `app/db/models/user.py`

---

### A-01 — Auth: OAuth (Google, GitHub)

> **Component:** ROADMAP4 §4.2.1 | **Dependencies:** A-00 | **Estimate:** 1 день

#### Context
OAuth — для external users. Chainlit поддерживает OAuth-providers.

#### Goal
Добавить OAuth-providers Google и GitHub через Chainlit `OAuthAuthProvider`.

#### Constraints
- `cl.OAuthAuthProvider` для Google и GitHub.
- Client ID/secret — из env.
- При первом OAuth-login — создавать пользователя в БД с `oauth_provider` + `oauth_id`.
- Связывание existing local-account с OAuth (по email).

#### Acceptance Criteria
- Login через Google работает.
- Login через GitHub работает.
- При первом входе — пользователь создаётся.
- При повторном — вход в тот же аккаунт.

#### Forbidden patterns
- Не хранить OAuth-tokens в БД — только `oauth_id`.
- Не использовать insecure redirect URIs.

#### Suggested files
- `app/auth/oauth_providers.py`
- `app/auth/google_provider.py`
- `app/auth/github_provider.py`

---

### A-02 — Rate-limiting (Redis token-bucket)

> **Component:** ROADMAP4 §4.2.2 | **Dependencies:** A-00 | **Estimate:** 1 день

#### Context
Rate-limit защищает от abuse и cost-overruns. Redis token-bucket — стандарт.

#### Goal
Реализовать `app/middleware/rate_limit.py` с token-bucket per-user.

#### Constraints
- Redis-key: `orya:rate:{user_id}:{hour}` — token-bucket.
- Limits: 100 messages/hour, 100k tokens/hour, $50/day (configurable).
- При достижении limit: `429 Too Many Requests` с `Retry-After` header.
- Token-counter: после каждого LLM-вызова обновлять `tokens_used` в bucket.
- Cost-counter: после каждого LLM-вызова обновлять `cost_usd` в bucket (через pricing-table).
- Hard daily limit: при достижении $50 → account suspension до конца дня.

#### Acceptance Criteria
- 101-е сообщение в час → 429.
- 100001-й токен в час → 429.
- Cost > $50/day → account suspended.
- `Retry-After` корректный (время до reset bucket).

#### Forbidden patterns
- Не использовать in-memory rate-limit (не работает при horizontal-scaling).
- Не забывать cost-limit (только message/token limits недостаточно).

#### Suggested files
- `app/middleware/rate_limit.py`
- `app/middleware/__init__.py`
- `app/core/pricing.py` (таблица model → price per 1k tokens)
- `tests/unit/test_rate_limit.py`

---

### A-03 — Cost-alarm (LangSmith/LangFuse + email)

> **Component:** ROADMAP4 §4.2.5 | **Dependencies:** A-02 | **Estimate:** 4 часа

#### Context
Cost-alarm — раннее предупреждение о cost-overruns.

#### Goal
Реализовать `app/observability/cost_alarm.py` — воркер, проверяющий daily cost per user.

#### Constraints
- Воркер запускается раз в час через `apscheduler`.
- Читает cost из `orya_sessions.tool_invocations` (агрегация по `user_id` и `DATE(started_at)`).
- При 80% от daily-limit → email-уведомление.
- При 100% → suspend-user (через rate-limit middleware).

#### Acceptance Criteria
- При 80% limit — email отправляется.
- При 100% limit — user suspended.
- Воркер логирует каждый запуск.

#### Forbidden patterns
- Не использовать SMTP напрямую — через `aiosmtplib` async.

#### Suggested files
- `app/observability/cost_alarm.py`
- `app/observability/email.py`

---

### A-04 — Observability: LangSmith/LangFuse + OTel + Prometheus

> **Component:** ARCHITECT4 §9, ROADMAP4 §4.2.3 | **Dependencies:** MVP done | **Estimate:** 1 день

#### Context
Три уровня observability — обязательно для production-safe.

#### Goal
Включить LangSmith/LangFuse tracing, инструментировать FastAPI/asyncpg/redis/httpx через OTel, добавить Prometheus `/metrics`.

#### Constraints
- LangSmith: env `LANGCHAIN_TRACING_V2=true`, `LANGCHAIN_API_KEY=...`.
- LangFuse: env `LANGFUSE_PUBLIC_KEY=...`, `LANGFUSE_SECRET_KEY=...`, `LANGFUSE_HOST=...`.
- OTel: `opentelemetry-instrumentation-fastapi`, `asyncpg`, `redis`, `httpx`.
- Export в OTel Collector (env `OTEL_EXPORTER_OTLP_ENDPOINT`).
- Prometheus: `prometheus-fastapi-instrumentator`.
- Метрики: `orya_http_request_duration_seconds_bucket`, `orya_agent_step_duration_seconds`, `orya_tool_calls_total`, `orya_llm_tokens_total`, `orya_llm_cost_usd_total`, `orya_session_active_count`, `orya_interrupt_waiting_count`.
- `/metrics` endpoint.

#### Acceptance Criteria
- LangSmith показывает trace каждой сессии.
- OTel spans видны в Tempo.
- `/metrics` отдаёт все метрики.
- Grafana-дашборд `orya-overview.json` отображает throughput/latency/cost.

#### Forbidden patterns
- Не хардкодить LANGCHAIN_API_KEY — только env.
- Не использовать sync OTel-exporter — только async batch.

#### Suggested files
- `app/observability/__init__.py`
- `app/observability/tracing.py` (OTel setup)
- `app/observability/metrics.py` (Prometheus)
- `app/observability/logging.py` (structured JSON-логи)
- `grafana/provisioning/orya-overview.json`

---

### A-05 — Offline-eval (nightly job)

> **Component:** ROADMAP4 §4.2.4 | **Dependencies:** A-04 | **Estimate:** 1 день

#### Context
Nightly eval — regression-gate. Блокирует релиз при падении quality.

#### Goal
Реализовать eval-pipeline: 50 задач, nightly run, Markdown-отчёт, CI-gate.

#### Constraints
- Eval-датасет: 50 задач в `tests/eval/dataset.yml` (read-only, edit-required, bash-required, multi-step).
- Скрипт `scripts/run_eval.sh` прогоняет все задачи.
- Метрики: success-rate, avg-steps, avg-cost, p95-latency.
- Сравнение с baseline (вчера); алерт при регрессии > 5% success-rate.
- Markdown-отчёт: `tests/eval/reports/{date}.md`.
- CI-gate: GitHub Actions workflow запускает eval nightly; при провале — block merge в main.

#### Acceptance Criteria
- `scripts/run_eval.sh` прогоняет 50 задач за ≤ 30 минут.
- Отчёт содержит метрики + diff vs yesterday.
- При success-rate < 85% — exit code 1.
- GitHub Actions workflow запускается каждый день в 03:00 UTC.

#### Forbidden patterns
- Не использовать real LLM-вызовы (денег стоит) — mock LLM с deterministic responses.
- Не запускать eval на main-ветке — только на PR.

#### Suggested files
- `tests/eval/dataset.yml`
- `scripts/run_eval.sh`
- `tests/eval/runner.py`
- `.github/workflows/eval.yml`

---

### A-06 — Secret-management (env-only + secret-scanning)

> **Component:** ROADMAP4 §4.2.6 | **Dependencies:** — | **Estimate:** 3 часа

#### Context
API-ключи только в env/vault. Secret-scanning в CI — для защиты от утечки.

#### Goal
Добавить `gitleaks` в CI и документировать rotation-policy.

#### Constraints
- `.github/workflows/security.yml` запускает `gitleaks` на каждый PR.
- `CONTRIBUTING.md` — секция «Secret management»: ключи только в env, rotation 90 дней.
- `.env.example` — все ключи с примерами (fake values).
- `.gitignore` — `.env`, `*.key`, `*.pem`.

#### Acceptance Criteria
- PR с real API-key в коде — блокируется gitleaks.
- `CONTRIBUTING.md` содержит rotation-policy.
- `.env.example` не содержит real ключей.

#### Forbidden patterns
- Не коммитить `.env` никогда.

#### Suggested files
- `.github/workflows/security.yml`
- `CONTRIBUTING.md`
- `.gitignore` (update)
- `.env.example` (update)

---

### A-07 — Chainlit: auth UI + cost-widget

> **Component:** ROADMAP4 §4.2.1, §4.2.5 | **Dependencies:** A-00, A-03 | **Estimate:** 4 часа

#### Context
UI должен показывать auth-экран и cost-widget.

#### Goal
Расширить `app/ui/chainlit_app.py`: auth UI (через Chainlit native), cost-widget в settings.

#### Constraints
- Auth UI — Chainlit native (login screen).
- Cost-widget в `cl.ChatSettings`: показывает `tokens_used_today`, `cost_usd_today`, `remaining_budget`.
- Обновление cost-widget после каждого message.

#### Acceptance Criteria
- Login screen появляется при первом открытии.
- После login — redirect в chat.
- Cost-widget показывает корректные числа.
- При 80% budget — yellow-warning; при 100% — red-error.

#### Forbidden patterns
- Не запрашивать cost-update каждое сообщение (debounce 5 сек).

#### Suggested files
- `app/ui/chainlit_app.py` (update)
- `app/ui/cost_widget.py`

---

### A-08 — LLM circuit-breaker

> **Component:** ROADMAP4 §4.3 (TRIZ-gate) | **Dependencies:** A-04 | **Estimate:** 4 часа

#### Context
При деградации LLM-провайдера (5xx, latency > 30 сек) — circuit-breaker переключает на fallback-провайдер.

#### Goal
Реализовать `app/core/circuit_breaker.py` для LLM-вызовов.

#### Constraints
- Если за 1 минуту `error_rate > 5%` ИЛИ `latency_p95 > 30 сек` → circuit opens.
- Open-circuit: запросы идут на fallback-провайдер (configured в `settings.llm_fallback_model`).
- Через 60 сек — half-open: 1 запрос на primary; при успехе → close.
- Метрика `orya_circuit_breaker_state{provider}` (0=closed, 1=open, 2=half-open).

#### Acceptance Criteria
- При инъекции 5xx от primary — circuit opens за ≤ 1 мин.
- Запросы идут на fallback.
- Через 60 сек после восстановления — circuit closes.

#### Forbidden patterns
- Не использовать `tenacity` (нет half-open state) — собственная реализация.

#### Suggested files
- `app/core/circuit_breaker.py`
- `app/core/llm.py` (update — обернуть в circuit-breaker)
- `tests/unit/test_circuit_breaker.py`

---

### A-09 — Structured JSON-логи

> **Component:** ROADMAP4 §4.2.3 | **Dependencies:** A-04 | **Estimate:** 3 часа

#### Context
Structured JSON-логи — для correlation с traces и metrics.

#### Goal
Реализовать `app/observability/logging.py` с structured JSON-логгером.

#### Constraints
- `structlog` с JSON-renderer.
- Каждый log: `timestamp`, `level`, `logger`, `message`, `trace_id`, `user_id`, `thread_id`, `extra`.
- `trace_id` из OTel-context (auto-injected).
- Запись в `~/.orya/logs/orya-agent.log` + stdout.
- Rotation: 100MB per file, 10 files.

#### Acceptance Criteria
- Логи в JSON-формате, парсятся `jq`.
- `trace_id` совпадает в logs и OTel-traces.
- Rotation работает.

#### Forbidden patterns
- Не использовать `logging.Formatter` без JSON — только `structlog`.

#### Suggested files
- `app/observability/logging.py`
- `app/observability/__init__.py` (update)

---

### A-10 — Chainlit: model-selector + settings-panel

> **Component:** ROADMAP4 §16 (UI) | **Dependencies:** M-17, A-00 | **Estimate:** 4 часа

#### Context
Settings-panel — для управления моделью, режимом, allow-list.

#### Goal
Расширить `app/ui/chainlit_app.py` settings: model-selector (dropdown), mode-toggle (ask/auto), allow-list-editor (textarea).

#### Constraints
- Model-selector: dropdown с поддерживаемыми моделями (`anthropic:claude-3-5-sonnet-latest`, `anthropic:claude-3-5-haiku-latest`, `openai:gpt-4o`, `openai:gpt-4o-mini`).
- Mode-toggle: `ask` / `auto`.
- Allow-list-editor: textarea, newline-separated rules; syntax `tool: pattern`.
- Сохранение в `~/.orya/settings.json`.

#### Acceptance Criteria
- Смена модели — применяется немедленно (новый graph).
- Смена mode — применяется немедленно.
- Allow-list — парсится и применяется.

#### Forbidden patterns
- Не требовать restart для применения settings.

#### Suggested files
- `app/ui/chainlit_app.py` (update)
- `app/ui/settings.py` (update)

---

### A-11 — API-key auth для external API-clients

> **Component:** ARCHITECT4 §8.2 | **Dependencies:** A-00 | **Estimate:** 4 часа

#### Context
External API-clients (в BETA+) будут использовать API-keys. Подготовим в ALPHA.

#### Goal
Реализовать `app/auth/api_key_provider.py` — middleware, проверяющая `Authorization: Bearer {api_key}`.

#### Constraints
- API-keys в таблице `orya_sessions.api_keys` (новая миграция).
- Каждая API-key: `id`, `user_id`, `key_hash` (bcrypt), `name`, `created_at`, `last_used_at`, `revoked_at`.
- Middleware: parse `Authorization` header → lookup → attach `user_id` to request state.
- Endpoints `/v1/*` (для external) требуют API-key; `/sessions/*` (для Chainlit) — JWT.

#### Acceptance Criteria
- Создание API-key через UI (settings → "Generate API key").
- Запрос с валидной API-key → 200.
- Запрос без API-key → 401.
- Запрос с revoked API-key → 401.
- `last_used_at` обновляется.

#### Forbidden patterns
- Не хранить API-keys в plain text — только bcrypt.

#### Suggested files
- `app/auth/api_key_provider.py`
- `alembic/versions/003_api_keys.py`
- `app/db/models/api_key.py`
- `app/middleware/auth.py`

---

### A-12 — ALPHA DoD integration test

> **Component:** ROADMAP4 §4.4 | **Dependencies:** все A-00..A-11 | **Estimate:** 4 часа

#### Context
ALPHA DoD — это интеграционный тест, проверяющий все компоненты вместе.

#### Goal
Реализовать `tests/e2e/test_alpha_dod.py` — 7 сценариев, проверяющих DoD-критерии.

#### Constraints
- 7 сценариев:
  1. Local auth login + JWT в cookie.
  2. Rate-limit: 101-е сообщение → 429.
  3. LangSmith trace виден (mock LangSmith API).
  4. Prometheus `/metrics` отдаёт все метрики.
  5. Nightly eval прогоняет 50 задач (mock LLM).
  6. Cost-alarm при 80% budget.
  7. Secret-scanning блокирует PR с ключом.

#### Acceptance Criteria
- Все 7 сценариев проходят.
- CI-gate: блокирует merge при провале.

#### Suggested files
- `tests/e2e/test_alpha_dod.py`
- `scripts/run_alpha_dod_check.sh`

---

## 3. Фаза BETA (B-00 … B-15)

### B-00 — Memory: cross-session via PostgresStore

> **Component:** ARCHITECT4 §17, ROADMAP4 §5.2.1 | **Dependencies:** ALPHA done | **Estimate:** 2 дня

#### Context
Memory — основа «платформенности». Cross-session через LangGraph `BaseStore`.

#### Goal
Реализовать `app/core/memory.py` с `PostgresStore`-backend для cross-session memory.

#### Constraints
- `langgraph.store.postgres.PostgresStore` (или кастомный `BaseStore`).
- Таблица `orya_sessions.memory` (новая миграция): `id UUID PK`, `user_id UUID`, `key TEXT`, `value TEXT`, `embedding VECTOR(1024)`, `created_at`, `updated_at`.
- Auto-summarization после закрытия сессии: отдельный воркер.
- Semantic search: `pgvector` + `bge-m3` (через OriaHS, если доступен; иначе локально).
- Memory injection в system-prompt: top-3 релевантные past-summaries.
- Privacy: per-user isolation.

#### Acceptance Criteria
- После закрытия сессии — summary сохраняется в memory.
- При новой сессии — top-3 summaries инжектируются в system-prompt.
- Memory-search latency ≤ 200 мс.
- Пользователь A не видит memory пользователя B.

#### Forbidden patterns
- Не использовать LangGraph `InMemoryStore` (не persistent).

#### Suggested files
- `app/core/memory.py`
- `alembic/versions/004_memory.py`
- `app/db/models/memory.py`

---

### B-01 — MCP-клиент (langchain-mcp-adapters)

> **Component:** ARCHITECT4 §17, ROADMAP4 §5.2.2 | **Dependencies:** MVP done | **Estimate:** 1 день

#### Context
MCP — стандарт для подключения внешних tools. `langchain-mcp-adapters` даёт готовый client.

#### Goal
Реализовать `app/core/mcp_loader.py` — загрузка MCP-tools из конфига.

#### Constraints
- `langchain-mcp-adapters.ClientSession`.
- Конфиг `~/.orya/mcp.yml`:
  ```yaml
  servers:
    github:
      transport: stdio
      command: npx
      args: ["-y", "@modelcontextprotocol/server-github"]
      env: { GITHUB_TOKEN: "${GITHUB_TOKEN}" }
    slack:
      transport: sse
      url: https://mcp.slack.com/sse
  ```
- При старте сессии: загрузить MCP-tools, добавить в tool-registry с namespace `mcp__{server}__{tool}`.
- MCP-tool-permissions: проходят через тот же `policy.review()`.
- Timeout при подключении к MCP-server: 5 сек.

#### Acceptance Criteria
- MCP-server `github` загружается; его tools появляются в реестре.
- Tool `mcp__github__create_issue` вызывается из агента.
- При недоступности MCP-server — fallback (skip tools, warn user).
- Permissions применяются к MCP-tools.

#### Forbidden patterns
- Не хардкодить MCP-servers в коде — только через конфиг.

#### Suggested files
- `app/core/mcp_loader.py`
- `tests/unit/test_mcp_loader.py`

---

### B-02 — Hooks: pre/post tool

> **Component:** ARCHITECT4 §17, ROADMAP4 §5.2.3 | **Dependencies:** M-12 | **Estimate:** 1 день

#### Context
Hooks — расширение без форка ядра. Pre/post tool hooks.

#### Goal
Реализовать `app/core/hooks.py` с pre/post tool hook-execution.

#### Constraints
- Конфиг `~/.orya/hooks.yml`:
  ```yaml
  hooks:
    post_tool:
      - match: { tool: "write" }
        action: run_bash
        command: "ruff format {args.path}"
  ```
- Pre-tool hooks: async-функции, запускаемые до tool-execution; могут модифицировать args или abort.
- Post-tool hooks: async-функции после tool-execution; могут модифицировать result.
- Built-in hooks: `format-on-write` (ruff/black), `lint-on-edit` (ruff), `reindex-on-write` (PROD+: oriahs_index).
- Hook-execution через `asyncio.create_task` (fire-and-forget для post-tool).

#### Acceptance Criteria
- Post-write hook `ruff format` форматирует файл после `write`.
- Hook-error не валит основной tool-execution.
- Hook-execution time ≤ 5 сек (timeout).

#### Forbidden patterns
- Не блокировать основной tool-execution на hook-execution.

#### Suggested files
- `app/core/hooks.py`
- `app/hooks/__init__.py`
- `app/hooks/format_on_write.py`

---

### B-03 — Skills: markdown-templates

> **Component:** ARCHITECT4 §17, ROADMAP4 §5.2.4 | **Dependencies:** MVP done | **Estimate:** 1 день

#### Context
Skills — переиспользуемые prompt-шаблоны. Markdown с front-matter.

#### Goal
Реализовать `app/core/skills.py` — парсер markdown-skill-файлов и их активацию.

#### Constraints
- Формат: markdown с YAML front-matter.
  ```markdown
  ---
  name: refactor-extract-function
  description: Extract code block into a new function
  tools: [read, edit, grep]
  ---
  # Instructions
  1. Read the file at {path}
  2. Identify the code block at lines {start}-{end}
  3. ...
  ```
- Хранение: `~/.orya/skills/` (user) или `.orya/skills/` (project).
- Активация: пользователь пишет `/skill refactor-extract-function path=main.py start=10 end=20`.
- LangGraph добавляет skill-инструкции в system-prompt на один ход.

#### Acceptance Criteria
- Skill `/skill refactor-extract-function` парсится.
- Skill-инструкции инжектируются в system-prompt.
- После выполнения — skill-инструкции удаляются из prompt.

#### Forbidden patterns
- Не использовать отдельный graph для skills — только инъекция в prompt.

#### Suggested files
- `app/core/skills.py`
- `~/.orya/skills/refactor-extract-function.md` (пример)
- `tests/unit/test_skills.py`

---

### B-04 — Compaction (LangGraph native)

> **Component:** ARCHITECT4 §6.6, ROADMAP4 §5.2.5 | **Dependencies:** M-04, M-06 | **Estimate:** 1 день

#### Context
Compaction — для длинных сессий. LangGraph native + summary-узел.

#### Goal
Добавить `compact`-узел в graph; запускается при `token_count > 80% max`.

#### Constraints
- Узел `compact`: LLM-summarization первых N сообщений.
- Summary сохраняется как `SystemMessage` в начале.
- Полные сообщения переносятся в cold-storage (таблица `orya_sessions.events`).
- Trigger: после каждого `agent`-узла проверять `token_count(state) > 0.8 * max_tokens`.
- User-confirmation перед compact (можно undo через checkpoint).

#### Acceptance Criteria
- При 1000+ сообщениях — compaction срабатывает.
- Agent продолжает работать после compaction.
- Undo через LangGraph checkpoint работает.

#### Forbidden patterns
- Не удалять полные сообщения (только в cold-storage).

#### Suggested files
- `app/core/graph.py` (update — добавить compact-узел)
- `app/core/compaction.py`
- `tests/unit/test_compaction.py`

---

### B-05 — Next.js UI: skeleton + chat-panel

> **Component:** ARCHITECT4 §6.7.2, ROADMAP4 §5.2.6 | **Dependencies:** ALPHA done | **Estimate:** 2 дня

#### Context
Next.js UI — primary с BETA. Skeleton + chat-panel в первом приближении.

#### Goal
Создать Next.js 15+ app с chat-panel, подключённым к FastAPI-SSE.

#### Constraints
- Next.js 15+ (app router), React 19, TypeScript 5.
- FastAPI endpoint `POST /sessions/{thread_id}/messages` возвращает SSE-stream.
- Components: `ChatPanel`, `Message`, `ToolCallCard`, `InputBar`.
- Streaming через `EventSource` API.
- Markdown через `react-markdown` + `react-syntax-highlighter`.
- Auth через cookie (JWT из ALPHA).

#### Acceptance Criteria
- `npm run dev` поднимает Next.js на :3000.
- Сообщение отправляется, SSE-stream принимается.
- Markdown рендерится.
- Code-blocks с подсветкой.
- Auth: без login — redirect на /login.

#### Forbidden patterns
- Не использовать `pages/` router — только `app/` router.
- Не использовать `fetch` для streaming — только `EventSource`.

#### Suggested files
- `frontend/` (new Next.js app)
- `frontend/app/page.tsx`
- `frontend/app/login/page.tsx`
- `frontend/components/ChatPanel.tsx`
- `frontend/components/Message.tsx`
- `frontend/components/ToolCallCard.tsx`
- `app/api/routes/sessions.py` (FastAPI SSE)

---

### B-06 — Next.js UI: code-viewer (Monaco)

> **Component:** ARCHITECT4 §6.7.2 | **Dependencies:** B-05 | **Estimate:** 1 день

#### Context
Code-viewer — для показа файлов, на которые ссылается агент.

#### Goal
Добавить `CodeViewer` (Monaco editor, read-only) в Next.js UI.

#### Constraints
- `@monaco-editor/react`.
- Sidebar с file-tree (через `lucide-react` icons).
- При клике на файл — открыть в CodeViewer.
- Подсветка синтаксиса для Python, JS, TS, Go, Rust, Markdown.
- При `read` tool-call — автоматически открыть файл в CodeViewer.

#### Acceptance Criteria
- File-tree показывает структуру проекта.
- Клик на файл — открывает в CodeViewer.
- Подсветка работает.
- При `read` tool-call — файл открывается автоматически.

#### Forbidden patterns
- Не использовать `textarea` — только Monaco.

#### Suggested files
- `frontend/components/CodeViewer.tsx`
- `frontend/components/FileTree.tsx`

---

### B-07 — Next.js UI: multi-tab sessions

> **Component:** ARCHITECT4 §6.7.2 | **Dependencies:** B-05 | **Estimate:** 1 день

#### Context
Multi-tab — несколько параллельных сессий.

#### Goal
Добавить multi-tab UI.

#### Constraints
- Tabs в top-bar.
- Каждый tab — отдельная сессия (отдельный thread_id).
- State per-tab изолирован.
- New-tab button.

#### Acceptance Criteria
- Можно открыть 2+ tabs.
- Сообщения в tab A не влияют на tab B.
- Close-tab — закрывает сессию (но не удаляет из БД).

#### Forbidden patterns
- Не использовать глобальный state — per-tab.

#### Suggested files
- `frontend/components/SessionTabs.tsx`
- `frontend/app/sessions/[threadId]/page.tsx`

---

### B-08 — FastAPI: /sessions endpoints

> **Component:** ARCHITECT4 §8.1 | **Dependencies:** ALPHA done | **Estimate:** 1 день

#### Context
FastAPI endpoints для Next.js UI.

#### Goal
Реализовать `app/api/routes/sessions.py` с REST endpoints.

#### Constraints
- `POST /sessions` — создать сессию.
- `GET /sessions` — список (с пагинацией).
- `GET /sessions/{thread_id}` — метаданные + последнее состояние.
- `DELETE /sessions/{thread_id}` — архивировать.
- `POST /sessions/{thread_id}/messages` — отправить сообщение; возвращает SSE-stream.
- `POST /sessions/{thread_id}/resume` — подтвердить tool-call.
- `POST /sessions/{thread_id}/cancel` — прервать.
- `GET /sessions/{thread_id}/events` — история событий.
- `GET /tools` — список tools со схемами.
- Auth: JWT middleware.

#### Acceptance Criteria
- Все endpoints работают по OpenAPI-спеке.
- SSE-streaming для messages.
- 401 без auth; 403 при доступе к чужой сессии.

#### Forbidden patterns
- Не использовать sync `def` — только `async def`.

#### Suggested files
- `app/api/routes/sessions.py`
- `app/api/routes/tools.py`
- `app/api/schemas.py`

---

### B-09 — Prompt-версионирование + A/B-basic

> **Component:** ROADMAP4 §5.2.7 | **Dependencies:** M-05 | **Estimate:** 1 день

#### Context
Prompt-versioning — для A/B-тестирования и rollback.

#### Goal
Реализовать `app/core/prompt_versioning.py` — версионирование system-prompt.

#### Constraints
- Каждое изменение system-prompt → новая версия в БД (`orya_sessions.prompt_versions`).
- `prompt_version_id` в каждой сессии.
- A/B: 50% новых сессий → v1, 50% → v2 (sticky по user_id).
- Метрики: success-rate, avg-steps, user-satisfaction (thumbs up/down в UI).
- Sequential testing для statistical significance.

#### Acceptance Criteria
- Можно создать новую prompt-version через UI.
- 50/50 split работает.
- Метрики собираются per-version.

#### Forbidden patterns
- Не использовать `random.random()` для split — sticky hash.

#### Suggested files
- `app/core/prompt_versioning.py`
- `alembic/versions/005_prompt_versions.py`
- `app/db/models/prompt_version.py`

---

### B-10 — Hooks: built-in (format, lint, reindex-stub)

> **Component:** ROADMAP4 §5.2.3 | **Dependencies:** B-02 | **Estimate:** 4 часа

#### Context
Built-in hooks — для типичных сценариев.

#### Goal
Реализовать 3 built-in hooks: `format_on_write`, `lint_on_edit`, `reindex_on_write` (stub для PROD).

#### Constraints
- `format_on_write`: `ruff format {path}` после `write` tool.
- `lint_on_edit`: `ruff check {path}` после `edit` tool; при ошибке — warn в chat.
- `reindex_on_write`: stub, логирует "will reindex in PROD" (реальная индексация — PROD, P-04).

#### Acceptance Criteria
- После `write main.py` — `ruff format main.py` запускается.
- После `edit main.py` — `ruff check main.py` запускается; ошибки видны.
- Stub логируется.

#### Forbidden patterns
- Не блокировать основной tool на hook-execution.

#### Suggested files
- `app/hooks/format_on_write.py`
- `app/hooks/lint_on_edit.py`
- `app/hooks/reindex_on_write.py`

---

### B-11 — Memory injection в system-prompt

> **Component:** ROADMAP4 §5.2.1 | **Dependencies:** B-00, M-05 | **Estimate:** 4 часа

#### Context
Memory injection — top-3 past-summaries в system-prompt.

#### Goal
Обновить `app/core/prompt.py` — добавить секцию `relevant_memory`.

#### Constraints
- После загрузки state: `memory_items = await memory.search(user_id, query=last_user_message, top_k=3)`.
- В template: секция `# Relevant Memory\n{relevant_memory}`.
- Token-budget для memory: ≤ 1000 токенов.
- При отсутствии memory — секция пустая.

#### Acceptance Criteria
- При новой сессии — top-3 past-summaries в system-prompt.
- Token-budget соблюдается.
- При пустой memory — секция отсутствует.

#### Forbidden patterns
- Не вставлять memory в cacheable prefix (она динамическая).

#### Suggested files
- `app/core/prompt.py` (update)
- `tests/unit/test_prompt_with_memory.py`

---

### B-12 — Next.js UI: interrupt-modal

> **Component:** ARCHITECT4 §6.7.2 | **Dependencies:** B-05, B-08 | **Estimate:** 4 часа

#### Context
Interrupt-modal — для ask-mode в Next.js UI.

#### Goal
Добавить `InterruptModal` component.

#### Constraints
- При получении SSE-event `interrupt_before` — показать modal.
- Modal показывает tool-call и кнопки Allow/Deny.
- Allow → POST `/sessions/{id}/resume` с `{"decision": "allow"}`.
- Deny → POST с `{"decision": "deny"}`.

#### Acceptance Criteria
- При ask-mode — modal появляется.
- Allow/Deny работают.
- Modal можно закрыть только кнопкой.

#### Forbidden patterns
- Не блокировать UI при ожидании ответа.

#### Suggested files
- `frontend/components/InterruptModal.tsx`

---

### B-13 — BETA DoD integration test

> **Component:** ROADMAP4 §5.4 | **Dependencies:** все B-00..B-12 | **Estimate:** 4 часа

#### Goal
`tests/e2e/test_beta_dod.py` — 7 сценариев.

#### Constraints
- 7 сценариев:
  1. Memory: закрыть сессию → открыть новую → past-summary в system-prompt.
  2. MCP: подключить github MCP → вызвать tool.
  3. Hook: post-write `ruff format` срабатывает.
  4. Skill: `/skill refactor-extract-function` выполняется.
  5. Compaction: 1000+ сообщений → compaction срабатывает.
  6. Next.js UI: TTI ≤ 2 сек.
  7. A/B-prompt: 50/50 split работает.

#### Suggested files
- `tests/e2e/test_beta_dod.py`

---

### B-14 — MCP: namespace + permissions integration

> **Component:** ROADMAP4 §5.3 (TRIZ-gate) | **Dependencies:** B-01, M-13 | **Estimate:** 4 часа

#### Goal
MCP-tools интегрируются с permissions.

#### Constraints
- Namespace `mcp__{server}__{tool}` предотвращает shadowing.
- `policy.review()` работает с MCP-tools.
- Per-MCP-server permission-rules.

#### Suggested files
- `app/core/policy.py` (update)
- `app/core/mcp_loader.py` (update)

---

### B-15 — Chainlit fallback mode

> **Component:** ARCHITECT4 §6.7.2 | **Dependencies:** B-05 | **Estimate:** 2 часа

#### Goal
Chainlit остаётся как fallback для dev/quick-start.

#### Constraints
- `chainlit run app/ui/chainlit_app.py` работает параллельно с Next.js.
- Тот же backend (FastAPI).

#### Suggested files
- `app/ui/chainlit_app.py` (update — убрать direct graph calls, использовать FastAPI)

---

## 4. Фаза PROD (P-00 … P-15)

### P-00 — PROD bootstrap: OriaHS connection

> **Component:** ARCHITECT4 §10, ROADMAP4 §6.2.1 | **Dependencies:** BETA done | **Estimate:** 1 день

#### Context
OriaHS — внешний сервис. Нужно подключить и проверить healthcheck.

#### Goal
Реализовать `app/tools/oriahs.py` с health-check и base httpx-client.

#### Constraints
- `httpx.AsyncClient` с base_url=`settings.oriahs_url`.
- `oriahs_health()` tool: `GET /health/ready`.
- При недоступности OriaHS — tool `oriahs_search` возвращает fallback-сообщение "service unavailable, use grep".
- `oriahs_health` в `/health/ready` OryaAgent.

#### Suggested files
- `app/tools/oriahs.py`
- `app/core/oriahs_client.py`

---

### P-01 — Tool: oriahs_search

> **Component:** ARCHITECT4 §10.4 | **Dependencies:** P-00 | **Estimate:** 1 день

#### Goal
Реализовать `oriahs_search` tool.

#### Constraints
- `@tool(args_schema=OriasSearchInput)`.
- `POST /search` к OriaHS.
- Параметры: `query`, `top_k`, `filters`, `rerank`, `fusion`, `explain`.
- Возвращает markdown-список с file:line + snippet.
- Timeout 10 сек.

#### Suggested files
- `app/tools/oriahs.py` (extend)

---

### P-02 — Tool: oriahs_index (incremental)

> **Component:** ARCHITECT4 §10.5 | **Dependencies:** P-01 | **Estimate:** 1 день

#### Goal
Реализовать `oriahs_index` tool и post-write hook для автоиндексации.

#### Constraints
- `POST /index` к OriaHS.
- Path → `external_ref = f"{path}:{git_sha}"` (или `path::function_name` для code-chunks).
- Post-write hook (B-10) обновлён: реальная индексация вместо stub.
- Debounce 5 сек (несколько записей в один файл — один index-call).

#### Suggested files
- `app/tools/oriahs.py` (extend)
- `app/hooks/reindex_on_write.py` (update)

---

### P-03 — Code-chunker (tree-sitter)

> **Component:** ARCHITECT4 §10.6 | **Dependencies:** P-02 | **Estimate:** 1 день

#### Context
OriaHS не знает про структуру кода. Code-chunker нарезает файлы на semantic chunks.

#### Goal
Реализовать `app/tools/code_chunker.py` — tree-sitter-based chunker.

#### Constraints
- `tree-sitter-languages` для Python, JS, TS, Go, Rust.
- Chunking: functions, classes, top-level statements.
- Каждый chunk — отдельный документ для OriaHS.
- Metadata: `path`, `symbol_name`, `symbol_type`, `start_line`, `end_line`.

#### Suggested files
- `app/tools/code_chunker.py`
- `tests/unit/test_code_chunker.py`

---

### P-04 — Tool: oriahs_wait_index + oriahs_delete

> **Component:** ARCHITECT4 §10.3 | **Dependencies:** P-02 | **Estimate:** 4 часа

#### Goal
Wait-for-index и delete tools.

#### Constraints
- `oriahs_wait_index(token)`: polling `GET /index/status/{token}` до `done` или `dead`.
- `oriahs_delete(doc_id)`: `DELETE /index/{doc_id}`.
- Cache `path → doc_id` в Redis для delete-after-rm.

#### Suggested files
- `app/tools/oriahs.py` (extend)

---

### P-05 — Tool: reindex_codebase (git-aware)

> **Component:** ARCHITECT4 §10.5 | **Dependencies:** P-02, P-03 | **Estimate:** 1 день

#### Goal
Полный reindex с git-aware diff.

#### Constraints
- `git diff --name-only HEAD~N HEAD` для изменённых файлов.
- Параллельная индексация (asyncio.gather, batch=10).
- Progress-bar в UI.
- Resume при прерывании.

#### Suggested files
- `app/tools/oriahs.py` (extend)

---

### P-06 — Multi-tenant RLS

> **Component:** ARCHITECT4 §12, ROADMAP4 §6.2.2 | **Dependencies:** ALPHA done | **Estimate:** 1 день

#### Goal
Row-level security в PostgreSQL.

#### Constraints
- `tenant_id` в каждой таблице `orya_sessions.*`.
- RLS-policies: `USING (tenant_id = current_setting('app.current_tenant')::uuid)`.
- Per-session `SET app.current_tenant = {tenant_id}`.
- Per-tenant rate-limits, cost-limits.
- Per-tenant LLM-model policies.

#### Suggested files
- `alembic/versions/006_multi_tenant.py`
- `app/db/rls.py`

---

### P-07 — A/B-framework (full)

> **Component:** ROADMAP4 §6.2.3 | **Dependencies:** B-09 | **Estimate:** 1 день

#### Goal
Полноценный A/B-фреймворк с метриками и admin-UI.

#### Constraints
- `experiment_id` в каждой сессии.
- Sticky distribution by user_id.
- Daily metrics: success-rate, avg-cost, avg-steps, user-satisfaction.
- Sequential testing.
- Admin-UI в Next.js: создать/просмотреть эксперимент.

#### Suggested files
- `app/core/experiments.py`
- `frontend/app/admin/experiments/page.tsx`

---

### P-08 — Sandbox: bwrap + egress-filter

> **Component:** ARCHITECT4 §12.3, ROADMAP4 §6.2.4 | **Dependencies:** M-10 | **Estimate:** 1 день

#### Goal
Sandbox для bash в auto-mode.

#### Constraints
- `bwrap` (Linux) / `sandbox-exec` (macOS).
- Egress-filter: whitelist доменов (LLM-API, package-managers).
- CPU/memory limits через cgroups.
- `auto`-mode только в sandbox.

#### Suggested files
- `app/tools/sandbox.py`
- `app/tools/bash.py` (update — использовать sandbox в auto-mode)

---

### P-09 — Context Epoch

> **Component:** ARCHITECT4 §6.6, ROADMAP4 §6.2.5 | **Dependencies:** B-04 | **Estimate:** 1 день

#### Goal
Context Epoch — неизменяемый базовый префикс для prompt-cache.

#### Constraints
- Epoch-boundary: при изменении system-prompt-version → новая epoch.
- Cacheable prefix помечается через `cache_control` (Anthropic).
- Cache-hit-rate метрика; цель ≥ 60%.
- Epoch-invalidation: при добавлении MCP-tool / skill.

#### Suggested files
- `app/core/context.py` (update)
- `app/core/epoch.py`

---

### P-10 — LLM-migration framework

> **Component:** ROADMAP4 §6.2.6 | **Dependencies:** A-08 | **Estimate:** 1 день

#### Goal
Zero-downtime миграция LLM-моделей.

#### Constraints
- Таблица `orya_sessions.llm_models` (новая миграция).
- Канарейка 1% → 5% → 25% → 50% → 100%.
- Rollback при любой аномалии.
- Snapshot сессий перед миграцией.

#### Suggested files
- `alembic/versions/007_llm_models.py`
- `app/core/llm_migration.py`

---

### P-11 — Shadow-traffic

> **Component:** ROADMAP4 §6.2.7 | **Dependencies:** P-07 | **Estimate:** 4 часа

#### Goal
Shadow-режим для новых prompt-versions.

#### Constraints
- Параллельный вызов old + new prompt.
- Логирование обоих.
- Клиенту — только old.

#### Suggested files
- `app/core/shadow_traffic.py`

---

### P-12 — Chaos engineering

> **Component:** ROADMAP4 §6.2.8 | **Dependencies:** P-00, P-08 | **Estimate:** 1 день

#### Goal
Weekly chaos-сценарии в CI.

#### Constraints
- 4 сценария: kill OriaHS, kill PG, delay LLM, fill Redis.
- Postcondition-чеки.
- Sunday 06:00 UTC.

#### Suggested files
- `tests/chaos/test_scenarios.py`
- `.github/workflows/chaos.yml`

---

### P-13 — Backup & DR

> **Component:** ROADMAP4 §6.2.9 | **Dependencies:** — | **Estimate:** 1 день

#### Goal
Backup PostgreSQL + Redis + S3-archive.

#### Constraints
- PITR для PostgreSQL (wal-g или pgBackRest).
- AOF + RDB для Redis.
- S3-archive для old sessions.
- DR-runbook.

#### Suggested files
- `scripts/backup.sh`
- `scripts/restore.sh`
- `docs/DR.md`

---

### P-14 — PROD DoD integration test

> **Component:** ROADMAP4 §6.4 | **Dependencies:** все P-00..P-13 | **Estimate:** 4 часа

#### Suggested files
- `tests/e2e/test_prod_dod.py`

---

### P-15 — Monitoring dashboards (Grafana)

> **Component:** ARCHITECT4 §9.4 | **Dependencies:** A-04, P-07 | **Estimate:** 4 часа

#### Goal
4 Grafana-dashboards: throughput, latency, cost, errors.

#### Suggested files
- `grafana/provisioning/orya-throughput.json`
- `grafana/provisioning/orya-latency.json`
- `grafana/provisioning/orya-cost.json`
- `grafana/provisioning/orya-errors.json`

---

## 5. Фаза EXTENSION-PROD (E-00 … E-10)

### E-00 — Semantic memory (RAG via OriaHS)

> **Component:** ROADMAP4 §7.2.1 | **Dependencies:** PROD done | **Estimate:** 2 дня

#### Goal
Semantic memory через OriaHS.

#### Constraints
- All past-summaries индексируются в OriaHS (tenant `orya_memory`).
- Top-5 релевантных past-summaries инжектируются в system-prompt.
- Per-user isolation.
- Memory-decay: 90 дней → reduced-weight; 1 год → archive.

#### Suggested files
- `app/core/semantic_memory.py`

---

### E-01 — VS Code extension

> **Component:** ROADMAP4 §7.2.2 | **Dependencies:** PROD done | **Estimate:** 1 неделя

#### Goal
VS Code extension с chat-sidebar + inline-completion + diff-apply.

#### Constraints
- TypeScript.
- Backend — FastAPI `/v1/chat/completions` (OpenAI-compatible).
- OAuth через browser.

#### Suggested files
- `ide/vscode/` (new package)

---

### E-02 — JetBrains plugin

> **Component:** ROADMAP4 §7.2.2 | **Dependencies:** E-01 | **Estimate:** 1 неделя

#### Goal
JetBrains plugin (аналогично VS Code).

#### Suggested files
- `ide/jetbrains/` (new package)

---

### E-03 — Parallel subagents (LangGraph Send)

> **Component:** ROADMAP4 §7.2.3 | **Dependencies:** B-04 | **Estimate:** 1 неделя

#### Goal
Parallel subagents через LangGraph `Send`.

#### Constraints
- Subagent — отдельный `StateGraph` без `write` tool.
- Родительский агент делает `write` после review.
- Max parallelism: 5.

#### Suggested files
- `app/core/subagents.py`

---

### E-04 — Horizontal scaling (stateless API)

> **Component:** ROADMAP4 §7.2.4 | **Dependencies:** PROD done | **Estimate:** 1 неделя

#### Goal
Stateless API-instances за load-balancer.

#### Constraints
- PostgresSaver → distributed PostgreSQL (PATRONI).
- Redis-cluster.
- Sticky-session для active-streams.

#### Suggested files
- `docker-compose.prod.yml`
- `k8s/` (Kubernetes manifests)

---

### E-05 — Smart model-routing

> **Component:** ROADMAP4 §7.2.5 | **Dependencies:** A-08 | **Estimate:** 1 день

#### Goal
Smart-routing: простые → Haiku/mini, сложные → Sonnet/Opus.

#### Constraints
- Classification-LLM (Haiku) классифицирует сложность.
- Token-budget per turn.
- Cache для одинаковых промптов.

#### Suggested files
- `app/core/router.py`

---

### E-06 — Advanced analytics (ClickHouse/Metabase)

> **Component:** ROADMAP4 §7.2.6 | **Dependencies:** PROD done | **Estimate:** 1 неделя

#### Goal
ClickHouse + Metabase для аналитики.

#### Suggested files
- `analytics/clickhouse_schema.sql`
- `analytics/metabase_dashboards/`

---

### E-07 — Token-budget per turn

> **Component:** ROADMAP4 §7.3 (TRIZ-gate) | **Dependencies:** E-05 | **Estimate:** 4 часа

#### Goal
Token-budget per turn — защита от cost-overruns.

#### Suggested files
- `app/core/budget.py`

---

### E-08 — IDE: inline-completion

> **Component:** ROADMAP4 §7.2.2 | **Dependencies:** E-01 | **Estimate:** 3 дня

#### Goal
Inline-completion (как Copilot).

#### Suggested files
- `ide/vscode/src/inlineCompletion.ts`

---

### E-09 — IDE: diff-apply

> **Component:** ROADMAP4 §7.2.2 | **Dependencies:** E-01 | **Estimate:** 2 дня

#### Suggested files
- `ide/vscode/src/diffApply.ts`

---

### E-10 — EXTENSION-PROD DoD

> **Component:** ROADMAP4 §7.4 | **Estimate:** 4 часа

#### Suggested files
- `tests/e2e/test_extension_dod.py`

---

## 6. Фаза FUTURE (F-00 … F-08)

### F-00 — Cron / scheduler

> **Component:** ROADMAP4 §8.2.1 | **Estimate:** 1 неделя

#### Suggested files
- `app/core/scheduler.py`

---

### F-01 — Goals + judge-модель

> **Component:** ROADMAP4 §8.2.2 | **Estimate:** 2 недели

#### Suggested files
- `app/core/goals.py`

---

### F-02 — Workflows (LangGraph subgraphs)

> **Component:** ROADMAP4 §8.2.3 | **Estimate:** 2 недели

#### Suggested files
- `app/workflows/`

---

### F-03 — Max Mode (best-of-N)

> **Component:** ROADMAP4 §8.2.4 | **Estimate:** 1 неделя

#### Suggested files
- `app/core/max_mode.py`

---

### F-04 — Multi-agent teams

> **Component:** ROADMAP4 §8.2.5 | **Estimate:** 3 недели

#### Suggested files
- `app/teams/`

---

### F-05 — Voice-input (VAD + ASR)

> **Component:** ROADMAP4 §8.2.6 | **Estimate:** 2 недели

#### Suggested files
- `app/voice/`

---

### F-06 — `/dream` (self-improvement)

> **Component:** ROADMAP4 §8.2.7 | **Estimate:** 2 недели

#### Suggested files
- `app/core/dream.py`

---

### F-07 — `/distill` (auto-skill-creation)

> **Component:** ROADMAP4 §8.2.7 | **Estimate:** 2 недели

#### Suggested files
- `app/core/distill.py`

---

### F-08 — Desktop app (Tauri)

> **Component:** ROADMAP4 §8.2.8 | **Estimate:** 3 недели

#### Suggested files
- `desktop/` (new Tauri app)

---

## 7. Сводная матрица тикетов × фаз

| Фаза | Кол-во тикетов | Суммарная оценка |
|---|---|---|
| MVP | 20 (M-00..M-19) | ~15 дней |
| ALPHA | 13 (A-00..A-12) | ~10 дней |
| BETA | 16 (B-00..B-15) | ~15 дней |
| PROD | 16 (P-00..P-15) | ~15 дней |
| EXTENSION-PROD | 11 (E-00..E-10) | ~5 недель |
| FUTURE | 9 (F-00..F-08) | ~4 месяца |
| **Итого до PROD** | **65** | **~55 дней (~11 недель)** |

---

## 8. Карта зависимостей между тикетами

```
MVP:  M-00 → M-01, M-02, M-03 → M-04 → M-05, M-06
                              ↓
                  M-07, M-08, M-09, M-10, M-11 → M-12
                              ↓
                              M-13 (permissions)
                              ↓
                              M-14 (session-log)
                              ↓
                              M-15 → M-16 → M-17 (UI)
                              ↓
                              M-18 (smoke) → M-19 (README)

ALPHA: A-00 → A-01, A-02, A-11
       A-04 (observability) → A-03, A-05, A-08, A-09
       A-06 (security) — parallel
       A-07, A-10 (UI) → A-12 (DoD)

BETA:  B-00 (memory), B-01 (MCP), B-02 (hooks), B-03 (skills) — parallel
       B-04 (compaction) → B-11 (memory injection)
       B-05 (Next.js) → B-06, B-07, B-12
       B-08 (FastAPI) — parallel
       B-09 (A/B), B-10 (built-in hooks), B-14 (MCP+policy), B-15 (Chainlit fallback)
       B-13 (DoD)

PROD:  P-00 (OriaHS bootstrap) → P-01, P-02, P-04 → P-05 (reindex)
       P-03 (code-chunker) — parallel
       P-06 (multi-tenant), P-07 (A/B full), P-08 (sandbox), P-09 (Epoch), P-10 (LLM-migration), P-11 (shadow), P-12 (chaos), P-13 (backup) — parallel
       P-14 (DoD), P-15 (Grafana)

EXTENSION-PROD: E-00 (semantic memory), E-01 (VS Code) → E-02 (JetBrains), E-08, E-09 (IDE features)
                E-03 (subagents), E-04 (scaling), E-05 (smart-routing) → E-07 (budget)
                E-06 (analytics), E-10 (DoD)

FUTURE: F-00..F-08 — независимы
```

---

## 9. Итог BACKLOG4

BACKLOG4 содержит 85 конкретных тикетов, разбитых по 6 фазам. Каждый тикет имеет:
- Context (почему нужен)
- Goal (что сделать)
- Constraints (жёсткие ограничения)
- Acceptance Criteria (проверяемые условия)
- Forbidden patterns (что нельзя делать)
- Suggested files (стартовая структура)

Принцип 20/80 на уровне тикетов:
- **MVP** — 20 тикетов, ~15 дней. Покрывает 80% базовой функциональности.
- **ALPHA** — 13 тикетов, ~10 дней. Покрывает 80% production-safety.
- **BETA** — 16 тикетов, ~15 дней. Покрывает 80% расширяемости.
- **PROD** — 16 тикетов, ~15 дней. Покрывает 80% enterprise-ready.
- **EXTENSION-PROD** — по триггерам.
- **FUTURE** — по demand.

В `BACKLOG5.md` будет проведён повторный анализ по 20/80 и ТРИЗ для поиска того, что v4 всё ещё упускает.

---

*Конец документа BACKLOG4.md*
