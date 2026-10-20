# ADR-001: Python + asyncio вместо TypeScript/Effect-TS

**Дата:** 2026-10-20
**Статус:** Accepted
**Decision makers:** core team

---

## Контекст

[`agents-architect.md`](../agents-architect.md) показывает, что 4 из 5 рассмотренных кодинг-агентов (Claude Code, OpenCode, Kilo Code, MiMoCode) используют TypeScript + Effect-TS. DeepSeek Harness — TypeScript + Cordis. Python не представлен ни в одном из зрелых решений.

[`self-agent.md`](../self-agent.md) изначально наследовал это решение — TypeScript + Effect-TS + Bun. Однако в репозитории OryaAgent уже лежит `main.py` (Python), что намекает на близость автора к Python-экосистеме. Кроме того, AI/ML-сообщество исторически говорит на Python, и контрибьюторы с навыками ML/Data-инженерии — это потенциальный talent pool.

Нужно было выбрать язык для ядра OryaAgent.

## Рассмотренные альтернативы

### Вариант A: TypeScript + Effect-TS (как в self-agent.md)

- **Плюсы:**
  - Совпадает с 4 из 5 зрелых решений — можно подсматривать паттерны
  - Effect-TS даёт structured concurrency, типобезопасные ошибки, dependency injection
  - Bun-рантайм — fast cold start
  - npm-экосистема — самое большое число пакетов
  - IDE-плагины (VS Code, JetBrains) — нативные для TS-разработки
- **Минусы:**
  - Effect-TS — крутая кривая обучения для контрибьюторов
  - AI/ML-инструменты (tokenizers, embeddings, vector stores) — исторически Python-first
  - Anthropic SDK, OpenAI SDK — часто Python-first-class, TS SDK догоняет
  - Контрибьюторы из AI-сообщества — friction при входе в TS-код

### Вариант B: Python + asyncio + Pydantic

- **Плюсы:**
  - AI/ML-экосистема — native (tokenizers, transformers, langchain как референс)
  - Anthropic SDK, OpenAI SDK — Python-first
  - Pydantic v2 — type-safe validation, comparable с Effect
  - asyncio — native structured concurrency через TaskGroup (3.11+)
  - Контрибьюторы из AI-сообщества — низкий friction
  - `pip install` — стандарт де-факто
  - Лучшая интеграция с Jupyter для experimentation
- **Минусы:**
  - GIL — ограничение для CPU-bound, но не критично для I/O-bound агента
  - Cold start медленнее, чем у Bun (~200ms vs 50ms)
  - Pydantic v2 — медленнее, чем Effect, на hot path
  - Нет нативного TypeScript-интерфейса (для IDE-плагинов v2 — нужен bridge)
  - Windows: PTY-поддержка через `pywin32` менее зрелая

### Вариант C: Rust + tokio

- **Плюсы:**
  - Maximum performance (cold start <20ms, runtime overhead ~0)
  - Memory safety без GC
  - Single static binary — простая дистрибуция
- **Минусы:**
  - Дольше до MVP (язык сложнее)
  - AI-экосистема слабее (no tokenizers, no first-class SDK)
  - Контрибьюторов с Rust-навыком значительно меньше
  - Pydantic-аналога нет (serde — близко, но не то же)

### Вариант D: Go + goroutines

- **Плюсы:**
  - Простой синтаксис, легко контрибьютить
  - Single static binary
  - Goroutines — простая модель concurrency
- **Минусы:**
  - AI-экосистема слабая
  - Generics поздно пришли — library design страдает
  - Pydantic-аналога нет

## Решение

**Python 3.12+ с asyncio + Pydantic v2.**

Структура:
- `asyncio.TaskGroup` для structured concurrency
- `Pydantic v2` для валидации всех внешних данных
- `httpx` для HTTP (async-native)
- `structlog` для structured logging
- `rich` для TUI rendering
- `prompt_toolkit` для REPL input
- `pytest` + `pytest-asyncio` для тестирования

## Обоснование

Выбор Python — стратегический, не тактический. Он снижает friction для ключевой аудитории:

1. **AI-сообщество как talent pool.** Контрибьюторы из LangChain, LlamaIndex, AutoGen, CrewAI — все говорят на Python. OryaAgent, написанный на Python, получает контрибьюшены, недоступные TS-проекту.

2. **SDK parity.** Anthropic Python SDK — feature-complete с day 1. TypeScript SDK часто отстаёт на месяцы. Для cutting-edge features (prompt-cache, computer-use, etc.) Python-first.

3. **Integration с ML tools.** Embedding-и, vector stores (Chroma, Qdrant), retrieval pipelines (LlamaIndex) — Python-native. v3 OryaAgent (memory cross-session, semantic code search) потребует этих инструментов. На Python — тривиально. На TS — обертки поверх Python-бэкендов.

4. **Cold start — acceptable trade-off.** 200ms vs 50ms — заметно, но не критично для interactive REPL. Бенчмарки важнее для batch/CI использования, где время агента = LLM latency, не cold start.

5. **GIL не блокирует.** OryaAgent — I/O-bound (LLM API, FS, subprocess). CPU-bound работы мало (token-counting, JSON-parsing) — это работает через `asyncio.to_thread` без блокировки event loop.

6. **Pydantic v2 — достаточно.** Effect-TS мощнее, но Pydantic v2 + Python type hints + mypy strict покрывают 90% нужд. Оставшиеся 10% (compile-time проверка эффектов) — не критичны для MVP.

Trade-offs, которые мы **осознанно принимаем**:

- **Cold start 200ms.** Документируем. Если станет критичным — v2 можно решить через `python -m orya --preload` с persistent background process.
- **Single binary distribution.** `pip install` вместо `curl | sh`. Решаем через `pipx install orya` (рекомендуемый путь) и `pipx` — стандарт de-facto.
- **Windows PTY.** `node-pty` в TS-мире лучше. На Python — `pywin32` + `asyncio.subprocess` (без PTY на Windows в MVP). ConPTY — v2.

## Последствия

**Позитивные:**

- Доступ к AI/ML-контрибьюторам (potentially x3-5 больше talent pool)
- First-class SDK support от Anthropic, OpenAI, Cohere, Mistral
- Native интеграция с ML-инструментами для v2/v3 (memory, semantic search, embeddings)
- Простой setup для development (один `pip install -e ".[dev]"`)
- `Jupyter`-notebook experimentation для research-задач
- `ruff` и `mypy --strict` — modern linting и type-checking

**Негативные:**

- Cold start медленнее, чем TS (~200ms vs ~50ms)
- Distribution через `pip`/`pipx` — менее polished опыт, чем single binary
- Windows PTY-поддержка менее зрелая (требует `pywin32` + ConPTY в v2)
- Effect-TS-style structured effects и dependency injection — нет прямого аналога (используем simple DI через constructor injection)
- `node-pty`-аналог на Python (`python-pty`?) менее зрелый — bash-инструмент использует `asyncio.subprocess` (без PTY на POSIX для простоты MVP; PTY — v2 если потребуется для интерактивных программ)

**Нейтральные:**

- GIL: не блокирует I/O-bound workload, но если появится CPU-bound (semantic indexing большого кодового репозитория) — потребуется multiprocessing или native extension
- `ruff format` vs `black` — сообщество расходится, мы выбираем `ruff` для унификации linting и formatting
- `mypy` vs `pyright` — выбираем `mypy` для CI (open-source, stable); `pyright` — для IDE (лучший DX)

## Критерии пересмотра решения

Решение пересматривается, если:

1. **Cold start > 500ms** на target-машине, и пользователи жалуются. Решение: precompiled bytecode (`python -O`), persistent daemon, или переход на compiled язык для cold-path.
2. **Контрибьютор-base не растёт** после v0.2.0 — значить, выбор не сработал. Рассмотреть TS-вBridge для IDE-плагинов (v2).
3. **Эффект-ориентированная архитектура** станет критичной (например, для сложной retry/transaction logic) — рассмотреть `effect-py` или переход на Rust.
4. **AI/ML-инструменты, от которых зависим, перестанут быть Python-first** — маловероятно в обозримом будущем.

## Связанные документы

- [self-agent.md](../self-agent.md) — оригинальный MVP-план (был на TS)
- [01-module-contracts.md](../spec/01-module-contracts.md) — обновлённая спецификация модулей на Python
- [02-llm-adapter-spec.md](../spec/02-llm-adapter-spec.md) — Python-имплементация LLM-шва
- [ADR-005](ADR-005-mvp-no-mcp-hooks.md) — почему MCP и hooks отложены (частично из-за сложности в Python-экосистеме)
- [PEP 695](https://peps.python.org/pep-0695/) — type-parameters в Python 3.12
- [PEP 654](https://peps.python.org/pep-0654/) — ExceptionGroups (для `asyncio.TaskGroup`)
