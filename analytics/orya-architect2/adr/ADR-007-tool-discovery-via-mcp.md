# ADR-007: Tool discovery и capability registry через MCP

**Status:** Proposed
**Date:** 2026-10-19
**Authors:** Vasiliy Zhila (Reider85)
**Depends on:** ADR-001
**Related:** ADR-002

---

## 1. Context (Контекст)

В MVP `analytics/self-agent.md` §4.4 `tool-registry` — статичный: 5 базовых инструментов регистрируются на старте, их список передаётся в LLM в `ToolSpec[]`. Это работает, пока инструментов 5-10. Но после ADR-001 (MCP-контракт) и ADR-002 (OriaHS как MCP-сервер) инструмент становится десятки — и они **не все нужны в каждом turn'е**:

| Категория | Примеры | Когда нужны |
|---|---|---|
| Базовые FS/shell | read, write, edit, bash, grep | всегда |
| Retrieval | hybrid_search, lexical_search, retrieve_facets | когда нужен context |
| Memory | memory_list, memory_forget, memory_remember | редко, по команде |
| External integrations | github_issue_create, jira_ticket_update, slack_post | по задаче |
| Code intelligence | symbol_lookup, find_references, rename_symbol | при рефакторинге |
| File-specific | docker_build, kubectl_apply, terraform_plan | по стеку проекта |

Если передать в LLM все 30+ инструментов сразу:
- **Token waste**: 2000-5000 токенов на tool-specs, даже если они не нужны.
- **Decision fatigue**: LLM хуже выбирает инструмент, когда их много (известная проблема long-tool-list).
- **Permission bloat**: пользователь не может адекватно approve'ить инструменты, которых не видит.

Параллельно MCP-протокол поддерживает `tools/list` — динамический discovery. Это ещё не использовано в ADR-001: там `MCPClient.listTools()` кэшируется на 60s и отдаёт всё. Нужно следующее решение: **когда и какие инструменты показывать LLM**.

---

## 2. Decision (Решение)

**Вводится `capability-registry` — надстройка над `tool-registry`, реализующая динамический discovery и контекстную фильтрацию инструментов для LLM.**

### 2.1. Уровни инструментов

| Уровень | Источник | Когда виден LLM | Примеры |
|---|---|---|---|
| **Core** | in-process, всегда загружены | всегда | read, write, edit, bash, grep |
| **Pinned** | MCP-сервера из `mcp.yml` с `pinned: true` | всегда | oriahs-retrieval (нужен retrieval-orchestrator'у) |
| **On-demand** | MCP-сервера с `pinned: false` | по решению capability-registry | github, jira, slack, docker |
| **Discovery** | MCP-сервера, не зарегистрированные статически | по явному `/use <server>` | экспериментальные |

### 2.2. Capability-registry — логика фильтрации

```typescript
interface CapabilityRegistry {
  getVisibleTools(session: SessionLog, opts: FilterOpts): ToolSpec[];
  registerServer(config: MCPServerConfig): Promise<void>;
  pinTool(server: string, tool: string): void;
  unpinTool(server: string, tool: string): void;
  onDemandActivate(server: string, reason: string): Promise<void>;
  onDemandDeactivate(server: string): void;
}

interface FilterOpts {
  maxTools: number;          // default 15
  includePinned: boolean;    // default true
  includeOnDemand: boolean;  // default true (если активированы)
  includeDiscovery: boolean; // default false
}
```

### 2.3. Правила активации on-demand инструментов

Capability-registry анализирует контекст сессии и активирует/деактивирует инструменты:

| Триггер | Активирует | Деактивирует (если не использовался 5 turn'ов) |
|---|---|---|
| В проекте есть `package.json` | npm-tools | — |
| В проекте есть `docker-compose.yml` | docker-tools | — |
| В проекте есть `.github/workflows/` | github-actions-tools | — |
| Пользователь упомянул "jira"/"тикет" | jira-tools | jira-tools |
| В коде есть `kubectl`/`k8s` | kubernetes-tools | kubernetes-tools |
| Команда `/use slack` | slack-tools | slack-tools (по `/unuse`) |
| В сессии есть `terraform` | terraform-tools | terraform-tools |

### 2.4. Механика MCP `tools/list` caching

```typescript
// Capability-registry держит 3 пула:
class CapabilityRegistry {
  private core: ToolSpec[] = [];           // статичные, всегда видны
  private pinned: ToolSpec[] = [];         // MCP pinned, всегда видны
  private onDemand: Map<string, ToolSpec[]> = new Map();  // активированные on-demand
  private discovery: Map<string, ToolSpec[]> = new Map();  // discovery-pool

  // MCPClient.listTools() кэшируется на 60s
  // при изменении tool-list на сервере (notifications/tools/list_changed)
  // кэш инвалидируется и registry перечитывает
}
```

### 2.5. LLM-видимый список

Перед каждым LLM-вызовом:

```typescript
function getVisibleTools(session: SessionLog): ToolSpec[] {
  const visible = [
    ...core,                                                  // 5 базовых
    ...pinned.filter(t => filterByPermissions(t, session)),  // 2-3 pinned
    ...activeOnDemand(session),                               // 3-5 активированных
  ];

  if (visible.length > MAX_VISIBLE_TOOLS) {
    // если всё ещё слишком много — сортируем по expected-usage
    return rankByExpectedUsage(visible, session).slice(0, MAX_VISIBLE_TOOLS);
  }
  return visible;
}
```

### 2.6. Expected-usage ranking

Когда инструментов всё ещё много, capability-registry ранжирует по:
- **Recent usage**: инструменты, использованные в последние 10 turn'ов → +5
- **Project-stack match**: инструмент соответствует stack'у проекта → +3
- **User-pinned**: пользователь явно закрепил → +10
- **Cost**: дорогие инструменты (большой output) → -1
- **Risk**: инструменты с `requires_confirmation: true` → -2

### 2.7. Tool-discovery через `/use` и MCP registry

Пользователь может явно подключать сторонние MCP-серверы в runtime:

```
/use mcp://registry.modelcontextprotocol.io/servers/slack
```

Capability-registry:
1. Загружает manifest MCP-сервера из registry.
2. Спрашивает permission.
3. Запускает (stdio/HTTP), кэширует `tools/list`.
4. Добавляет в discovery-pool, активирует on-demand.
5. Логирует в audit-log.

---

## 3. Consequences (Последствия)

### Положительные

- **Token economy.** LLM видит 10-15 инструментов вместо 30+, экономия 1000-3000 токенов на turn.
- **Decision quality.** Меньше инструментов → LLM точнее выбирает (подтверждено исследованиями long-tool-list).
- **Permission UX.** Пользователь видит только релевантные инструменты в approval-промпте.
- **Dynamic ecosystem.** Сторонние MCP-серверы подключаются в runtime.
- **Stack-awareness.** Агент сам понимает, что нужно для конкретного проекта.

### Отрицательные

- **Дополнительный модуль.** ~400-500 строк кода.
- **Latency активации.** При первом упоминании jira — нужно поднять MCP-сервер (1-3s). Mitigation: prefetch при триггере.
- **Non-determinism.** Один и тот же проект может активировать разные инструменты в разных run'ах (из-за order-of-mention).
- **Risk of misactivation.** Ложное срабатывание триггера → LLM видит ненужный инструмент → может попытаться его использовать.
- **Усложнение тестирования.** Tool-list динамический, тесты должны параметризоваться.

### Нейтральные

- **Discovery-pool** — опциональная фича, в MVP отключена по умолчанию.

---

## 4. Alternatives Considered (Альтернативы)

### A. Static tool-list (текущий MVP + все MCP-pinned)

Все инструменты всегда видны LLM.

| Критерий | Dynamic capability-registry | Static |
|---|---|---|
| Token cost | ✅ низкий | ❌ высокий |
| Decision quality | ✅ | ❌ |
| Predictability | ⚠️ | ✅ |
| Сложность | средняя | низкая |
| Permission UX | ✅ | ❌ |
| Расширяемость | ✅ | ❌ |

**Выбор:** Dynamic — статика не масштабируется.

### B. LLM-as-router: модель сама запрашивает инструменты

LLM видит meta-tool `list_available_tools()`, вызывает его, получает подсписок, потом использует.

| Критерий | Capability-registry | LLM-as-router |
|---|---|---|
| Latency | ✅ deterministic | ❌ +1 LLM-call |
| Token cost | ✅ | ❌ meta-call + результат |
| Determinism | ✅ | ❌ |
| Гибкость | ⚠️ | ✅ |
| Сложность | средняя | низкая (на старте) |

**Выбор:** Capability-registry как дефолт + опциональный `list_available_tools()` для discovery-mode.

### C. Tool-catalog в системном промпте

LLM видит каталог всех инструментов с описаниями, но только pinned-подмножество доступно для вызова.

| Критерий | Capability-registry | Catalog-in-prompt |
|---|---|---|
| Token cost | ✅ | ❌ весь каталог в промпт |
| UX | ✅ seamless | ❌ LLM «видит», но не может вызвать |
| Сложность | средняя | низкая |

**Выбор:** Capability-registry — не вводим LLM в заблуждение «видишь, но не можешь».

### D. Per-task tool-loading (загрузка по фазе задачи)

При `plan`-фазе — planning-tools, при `implement` — coding-tools, при `review` — review-tools.

| Критерий | Context-based activation | Phase-based |
|---|---|---|
| Гибкость | ✅ | ⚠️ жёсткие фазы |
| Зависимость от planner'а | ✅ нет | ❌ нужен planner |
| Соответствие MVP (без planner'а) | ✅ | ❌ |

**Выбор:** Context-based activation — не требует planner'а, который в MVP отложен (вывод №4 из `agents-architect.md`).

---

## 5. Metrics (Метрики оценки)

| Метрика | Целевое значение | Источник |
|---|---|---|
| `visible_tools_per_turn` (avg) | 8-15 | self-agent |
| `tool_spec_tokens_per_turn` | < 1500 | self-agent |
| `tool_selection_accuracy` (LLM выбрала правильный) | > 85% | offline eval |
| `on_demand_activation_count` per session | 0-3 | self-agent |
| `on_demand_activation_precision` (активирован и использован) | > 60% | self-agent |
| `false_activation_rate` (активирован, не использован) | < 30% | self-agent |
| `discovery_pool_usage` (через `/use`) | опционально | self-agent |
| `tool_call_latency_after_activation` (p95) | < 200 ms | self-agent |

---

## 6. Implementation Notes

### 6.1. Triggers-конфиг

```yaml
# ~/.self-agent/capabilities.yml
triggers:
  - name: npm-stack
    files: ["package.json"]
    activate: [npm-tools]
  - name: docker-stack
    files: ["docker-compose.yml", "Dockerfile"]
    activate: [docker-tools]
  - name: github-stack
    files: [".github/workflows/"]
    activate: [github-actions-tools]
  - name: k8s-stack
    content_patterns: ["\\bkubectl\\b", "\\bk8s\\b"]
    activate: [kubernetes-tools]
  - name: jira-mention
    content_patterns: ["\\bjira\\b", "\\bтикет\\b"]
    activate: [jira-tools]
    deactivate_after_idle_turns: 5
```

### 6.2. Stack-detection

```typescript
function detectStack(session: SessionLog): Set<string> {
  const stack = new Set<string>();
  const projectRoot = session.projectRoot;

  // file-based triggers
  for (const trigger of triggers.file) {
    if (trigger.files.some(f => existsSync(join(projectRoot, f)))) {
      trigger.activate.forEach(t => stack.add(t));
    }
  }

  // content-based triggers (по последним N сообщениям)
  const recentContent = lastNMessages(session, 10).map(m => m.content).join('\n');
  for (const trigger of triggers.content) {
    if (trigger.patterns.some(p => p.test(recentContent))) {
      trigger.activate.forEach(t => stack.add(t));
    }
  }

  return stack;
}
```

### 6.3. Integration в `agent-loop`

```typescript
// текущий код
const tools = toolRegistry.spec();

// новый код
const tools = capabilityRegistry.getVisibleTools(session, {
  maxTools: 15,
  includePinned: true,
  includeOnDemand: true,
});

const stream = await llm.complete({ model, system, messages: ctx, tools });
```

### 6.4. Audit log

```jsonl
{"ts":"2026-10-19T10:00:00Z","event":"activate","server":"jira-mcp","reason":"content_pattern","pattern":"\\bjira\\b","session":"abc"}
{"ts":"2026-10-19T10:05:00Z","event":"deactivate","server":"jira-mcp","reason":"idle","idle_turns":5,"session":"abc"}
{"ts":"2026-10-19T10:10:00Z","event":"pin","server":"oriahs-retrieval","user":"explicit"}
```

### 6.5. `/use` flow

```
user: /use mcp://registry.modelcontextprotocol.io/servers/slack
agent: Загружаю manifest slack-mcp...
agent: Slack MCP сервер хочет получить доступ к:
  - чтение каналов (read)
  - отправка сообщений (write)
  - поиск сообщений (read)
Разрешить? [yes/no/scope:read-only]
user: scope:read-only
agent: Slack MCP активирован в read-only режиме.
       Доступные инструменты: slack_list_channels, slack_search, slack_get_message
```

---

## 7. Risks (Риски)

| Риск | Вероятность | Влияние | Митигация |
|---|---|---|---|
| Ложная активация шумовых инструментов | высокая | среднее | deactivation по idle + scoring |
| Latency первого tool-call после активации | средняя | среднее | prefetch при триггере + warm-up |
| Discovery-pool инъекция malware MCP | средняя | критическое | manifest-signing + sandboxing + permission |
| Нестабильность MCP `tools/list_changed` | средняя | низкое | re-fetch + diffing |
| LLM путается в динамическом tool-list | средняя | среднее | cache tool-list на N turn'ов |
| Permission устаревает при deactivation | низкая | среднее | invalidate permission-cache |

---

## 8. References (Ссылки)

- `analytics/self-agent.md` §4.4 — текущий `tool-registry`
- `analytics/agents-architect.md` §2.2 — MCP в OpenCode (включая tool-discovery)
- `analytics/agents-architect.md` §5.2 — MiMo `MCP tool search`
- ADR-001 — MCP как первичный контракт
- ADR-002 — OriaHS как MCP-сервер (pinned по умолчанию)
- MCP Registry: https://github.com/modelcontextprotocol/registry
- Long-tool-list problem (исследование): https://www.anthropic.com/research/swe-bench-sonnet
