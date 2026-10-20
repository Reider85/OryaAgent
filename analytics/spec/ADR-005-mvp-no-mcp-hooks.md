# ADR-005: Отказ от MCP и hooks в MVP

**Дата:** 2026-10-20
**Статус:** Accepted
**Decision makers:** core team

---

## Контекст

[`agents-architect.md`](../agents-architect.md) показывает, что все 5 рассмотренных кодинг-агентов (Claude Code, OpenCode, Kilo Code, DeepSeek Harness, MiMoCode) имеют расширяемость через MCP (Model Context Protocol) и hooks (pre/post tool execution). Это мощные механизмы расширения, но они добавляют complexity:

- **MCP-клиент** — управление жизненным циклом external processes, OAuth, tool-list caching, transport (stdio/SSE/HTTP)
- **Hooks** — event-based extension points, требуется модель execution (sync/async, fail-fast или best-effort), приоритизация, error handling

[`self-agent.md`](../self-agent.md) явно откладывает MCP и hooks на v2: «MCP-клиент. Полезно, но не блокирует базовую работу. MCP-серверы — внешние процессы, требуют управления жизненным циклом, OAuth, кэширования tool-list. Это v2.»

Для OryaAgent нужно было решить: включать MCP и hooks в MVP (v0.1.0) или отложить (v0.2.0+).

## Рассмотренные альтернативы

### Вариант A: MCP + hooks в MVP

- **Плюсы:**
  - Паритет с Claude Code, OpenCode, dsh, MiMo, Kilo — feature-complete с первого дня
  - Community может добавлять инструменты через MCP-серверы без форка
  - Hooks позволяют customization (audit, telemetry, custom security policies)
  - Совместимость с ecosystem MCP-серверов (filesystem, git, browser, etc.)
- **Минусы:**
  - Significant complexity (~30% от размера ядра)
  - Жизненный цикл external processes — edge-cases (crashes, zombies, timeouts)
  - MCP-transport (stdio/SSE/HTTP) — три разные имплементации
  - Hooks execution model — нетривиальные trade-offs (sync vs async, ordering)
  - Документация — нужно специфицировать hook API, MCP-конфиг, troubleshooting
  - Тестирование — VCR-cassettes для MCP-серверов, mock subprocess lifecycle
  - Дистрибуция — MCP-серверы часто требуют своих зависимостей (Python, Node, Go)

### Вариант B: Отложить MCP и hooks на v2

- **Плюсы:**
  - MVP остаётся minimal — 8 модулей, ~5k LOC
  - Faster time-to-release (на 1-2 месяца раньше)
  - Cleaner abstraction — без внешних processes и event-subscribers
  - Проще тестировать и поддерживать
  - Документация — focused, без MCP-hook руководств
- **Минусы:**
  - Не паритет с конкурентами на MVP
  - Community не может расширить через MCP — только fork или plugin (если будет)
  - Пользователи, привыкшие к Claude Code MCP-экосистеме — отрезаны
  - Enterprise-расширения (custom audit, telemetry) — требуют fork

### Вариант C: MCP в MVP, hooks на v2

- **Плюсы:**
  - Паритет с Claude Code, OpenCode по MCP
  - Community-расширяемость через инструменты
- **Минусы:**
  - Significant complexity (MCP alone — ~20% ядра)
  - Hooks все ещё нужны для audit/telemetry — workaround через audit-log
  - Время до релиза +1 месяц

### Вариант D: Custom plugin system (lightweight MCP-аналог)

- **Плюсы:**
  - Проще MCP — Python-only, in-process
  - Community может добавлять через `~/.orya/plugins/*.py`
- **Минусы:**
  - Не совместим с MCP-экосистемой
  - In-process execution — security risk (plugin может всё)
  - Fragmentation — ещё один plugin-формат, не совместимый с другими агентами

## Решение

**Вариант B: Отказ от MCP и hooks в MVP (v0.1.0).**

MCP-клиент и hooks-система — отложены на v0.2.0 (по roadmap из README).

В MVP расширяемость ограничена:
- **5 базовых инструментов** — hardcoded в `tool_registry`
- **Audit log** — для observability (а не для extension)
- **Configuration** — через YAML-файлы (а не через плагины)
- **Custom LLM-адаптеры** — через Python-модули (custom subclass of `LLMProvider`), но без dynamic loading в MVP

## Обоснование

1. **Принцип 20/80.** [`self-agent.md`](../self-agent.md) явно применяет Pareto: 8 модулей дают 80% ценности. MCP и hooks — в числе отложенных 80% усилий для 20% ценности на старте.

2. **Вывод №4 из `agents-architect.md`:** «Автономность надстраивается над циклом, а не встраивается в него.» Это же применимо к расширяемости: hooks — это extension layer над циклом. Сначала стабильный цикл, потом расширяемость.

3. **Время до релиза критично.** Pre-alpha проект без кода — это specs и ADR-ы. Каждый месяц промедления — потерянные пользователи, ушедшие к конкурентам. MCP и hooks добавляют 1-2 месяца к development timeline.

4. **MCP — external processes complexity.** Управление subprocess-ами (старт, остановка, restart при crash, timeout, OAuth-flow для auth) — это subsystem сама по себе. Это не «feature в ядре», это отдельный модуль с своей архитектурой.

5. **Hooks — execution model неочевидна.** Sync vs async? Fail-fast или best-effort? Ordering? Visibility of failures? Все эти design-решения требуют feedback от пользователей. Делать hooks наугад — рискованно.

6. **Community пока нет.** Зачем MCP-совместимость, если нет MCP-серверов, специфичных для OryaAgent? Когда community вырастет — MCP будет обоснован.

7. **Enterprise-расширения — через audit-log + config.** Большинство enterprise use cases (audit forwarding, custom telemetry, MDM policies) можно решить через configuration + audit-log forwarding, без hooks. См. [enterprise-features.md](enterprise-features.md).

8. **Migration path определён.** Когда MCP-клиент будет добавлен (v0.2.0), его API будет совместим с Model Context Protocol стандартом — community MCP-серверы будут работать из коробки. Migration cost — нулевой для пользователей (не было MCP до v0.2.0, появился — opt-in).

## Последствия

**Позитивные:**

- MVP — minimal (8 модулей, ~5k LOC)
- Faster time-to-release (на 1-2 месяца раньше, чем с MCP+hooks)
- Cleaner architecture — без event-subscribers и subprocess-management
- Simpler documentation — фокус на базовой функциональности
- Easier testing — без mock subprocess lifecycle
- Stable core к моменту, когда community начнёт просить MCP

**Негативные:**

- Не паритет с Claude Code, OpenCode по расширяемости
- Community не может добавить свои инструменты без fork
- Пользователи, у которых уже есть MCP-серверы — отрезаны
- Enterprise-расширения (custom audit, security policies) — через fork или config-only

**Нейтральные:**

- Custom LLM-адаптеры — через Python subclass (advanced users)
- Custom tools — через Python subclass (advanced users)
- Configuration — через YAML, без dynamic loading
- v0.2.0 добавит MCP — migration path определён

## Что будем делать вместо MCP/hooks в MVP

### Custom LLM-адаптеры

```python
# ~/.orya/providers/custom_provider.py
from orya.llm import LLMProvider, LLMRequest, StreamEvent


class CustomProvider(LLMProvider):
    @property
    def name(self) -> str:
        return "custom"

    async def complete(self, req: LLMRequest) -> AsyncIterable[StreamEvent]:
        # custom implementation
        ...
```

В `providers.yml`:
```yaml
providers:
  custom:
    module: ~/.orya/providers/custom_provider.py
    class: CustomProvider
    config:
      api_key_env: CUSTOM_API_KEY
```

Dynamic loading через `importlib` при первом обращении. Это NOT MCP, но позволяет расширяемость для advanced users.

### Custom tools (для internal enterprise use)

```python
# ~/.orya/tools/custom_tool.py
from orya.tools import Tool, ToolResult


class DeployTool(Tool):
    name = "deploy"
    description = "Deploy to staging"

    async def execute(self, input, ctx) -> ToolResult:
        # custom deploy logic
        ...
```

В `config.yml`:
```yaml
custom_tools:
  - module: ~/.orya/tools/deploy_tool.py
    class: DeployTool
```

Это для internal enterprise use — custom tools, не предназначенные для publication. Для public tools — ждём MCP в v0.2.0.

### Audit log forwarding (вместо hooks для audit)

```yaml
audit:
  forward_to:
    - endpoint: https://siem.corp.example.com/otel
      format: otel
    - endpoint: syslog://siem.corp.example.com:514
      format: rfc5424
```

Audit-log forwarding покрывает 80% enterprise use case для audit (без hooks).

### Configuration-driven telemetry (вместо hooks для telemetry)

```yaml
telemetry:
  metrics:
    - name: llm_calls_total
      export_to: otel://collector:4317
      interval: 60s
  traces:
    - name: agent_loop
      export_to: otel://collector:4317
      sample_rate: 0.1
```

Configuration-driven telemetry — без hooks. Только predefined metrics и traces, не arbitrary code execution.

## Критерии пересмотра решения

1. **Community requests MCP массово** (>30 Issues/Disussions) — рассмотреть ускорение MCP в roadmap.
2. **Enterprise customers требуют custom tools/hooks** — расширить custom tools API (Python subclass).
3. **MCP-экосистема станет стандартом де-факто** (если все major AI tools его примут) — приоритизировать MCP над другими v2 features.
4. **Stable core к v0.2.0** — green light для добавления MCP без destabilization риска.

## Migration path к v0.2.0

Когда MCP добавляется в v0.2.0:

1. **MCP-клиент** реализует Model Context Protocol (transport: stdio, SSE, HTTP)
2. **MCP-серверы** из ecosystem (filesystem, git, browser, slack, github) работают out-of-the-box
3. **Custom tools** (Python subclasses) — продолжают работать, параллельно с MCP
4. **MCP-конфиг** в `~/.orya/mcp.yml`:
   ```yaml
   servers:
     filesystem:
       transport: stdio
       command: npx
       args: ["-y", "@modelcontextprotocol/server-filesystem", "/path"]
     github:
       transport: stdio
       command: npx
       args: ["-y", "@modelcontextprotocol/server-github"]
       env:
         GITHUB_TOKEN: env:GITHUB_TOKEN
   ```
5. **Hooks (v0.3.0)** — после MCP, если stable

## Связанные документы

- [self-agent.md](../self-agent.md) — пункт «Что сознательно НЕ делаем в MVP»
- [agents-architect.md](../agents-architect.md) — вывод №4 «автономность надстраивается над циклом»
- [01-module-contracts.md](../spec/01-module-contracts.md) — текущий MVP scope
- [enterprise-features.md](enterprise-features.md) — enterprise extension через config + audit
- [Model Context Protocol](https://modelcontextprotocol.io/) — official spec
- [Anthropic MCP introduction](https://www.anthropic.com/news/model-context-protocol)
