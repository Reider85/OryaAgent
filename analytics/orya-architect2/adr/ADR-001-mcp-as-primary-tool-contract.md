# ADR-001: MCP как первичный контракт расширения инструментов self-agent

**Status:** Proposed
**Date:** 2026-10-19
**Authors:** Vasiliy Zhila (Reider85)
**Supersedes:** пункт «MCP-клиент откладывается на v2» из `analytics/self-agent.md` §2
**Related:** ADR-002, ADR-007

---

## 1. Context (Контекст)

В `analytics/self-agent.md` зафиксировано архитектурное решение MVP: MCP-клиент откладывается на v2, в ядре остаются 5 базовых инструментов (read/write/edit/bash/grep) как типизированные функции в `tool-registry`. Обоснование было прагматичным — «не блокирует базовую работу», «требует управления жизненным циклом внешних процессов, OAuth, кэширования tool-list». На момент MVP это разумная экономия, но она создаёт три структурных долга:

1. **Жёсткая граница инструментов.** Любой новый capability (web-search, retrieval, jira-тикет, database-query) требует правки кода ядра, регистрации в `tool-registry`, обновления `ToolSpec`-схемы, перекомпиляции. Это противоречит выводу №3 из `agents-architect.md`: «три философии расширяемости — детерминированные гейты, открытые JS-хуки, полная инверсия контроля». MVP сейчас не принадлежит ни к одной — он просто не имеет контракта расширения.
2. **Изолированность OriaHS.** Гибридный поиск (`OriaHS`) существует как отдельный FastAPI-сервис. Чтобы self-agent мог им пользоваться, нужен клиентский SDK в ядре — а это связывание ядра с конкретным сервисом. Параллельно тот же поиск нужен IDE-плагину, batch-eval джобе, cron-задаче — каждое использование будет плодить свои SDK.
3. **Отсутствие tool-discovery.** LLM видит фиксированный список инструментов, скомпонованный на старте сессии. Динамическое подключение инструментов в зависимости от фазы задачи (например, доступ к jira только на этапе triage) невозможно без перезапуска.

Параллельно в индустрии сложился стандарт **Model Context Protocol (MCP)** — открытый JSON-RPC-протокол поверх stdio/SSE/HTTP, который определяет:
- `tools/list`, `tools/call` — динамический реестр инструментов;
- `resources/list`, `resources/read` — статические данные;
- `prompts/list`, `prompts/get` — переиспользуемые промпт-шаблоны;
- `notifications/*`, `sampling/*` — обратные вызовы от сервера к клиенту.

MCP уже поддерживают Claude Code (как клиент), OpenCode (stdio/HTTP, OAuth), Kilo, MiMo, dsh — все четыре открытых архитектуры из обзора. Это де-факто стандарт расширения агентских ядер.

---

## 2. Decision (Решение)

**MCP назначается первичным контрактом расширения инструментов self-agent, начиная с v0.2.**

Конкретные подпункты:

1. **`tool-registry` становится гибридным.** Пять базовых инструментов (`read`, `write`, `edit`, `bash`, `grep`) остаются in-process функциями ядра — это сохраняет производительность и нулевую задержку. Любой новый capability обязан быть MCP-сервером (stdio или HTTP).
2. **`MCPClient` — новый модуль ядра**, ответственный за:
   - запуск/останов stdio-MCP-серверов (subprocess-менеджмент);
   - HTTP/SSE-подключения к удалённым MCP-серверам с retry и OAuth;
   - кэширование `tools/list` с TTL (по умолчанию 60s);
   - проксирование `tools/call` в `tool-registry` через адаптер;
   - health-checks и graceful degradation при падении сервера.
3. **Конфигурация MCP-серверов** — декларативная, в `~/.self-agent/mcp.yml`:
   ```yaml
   servers:
     - name: oriahs-retrieval
       transport: http
       url: ${ORIAHS_URL}/mcp
       auth: bearer
       token_env: ORIAHS_TOKEN
       tool_filter: ["search", "retrieve", "facets"]
       cache_ttl: 120s
     - name: filesystem-mcp
       transport: stdio
       command: ["npx", "@modelcontextprotocol/server-filesystem", "${PROJECT_ROOT}"]
   ```
4. **`ToolSpec`-генерация** унифицируется: in-process инструменты и MCP-инструменты приводятся к одному `ToolSpec`-формату перед передачей в LLM. LLM не знает, инструмент локальный или удалённый.
5. **Permission-механизм** расширяется: каждое MCP-правило в `permissions.yml` может запрещать/разрешать конкретный tool на конкретном сервере.

---

## 3. Consequences (Последствия)

### Положительные

- **Расширяемость без правок ядра.** Новый capability = новый MCP-сервер. Ядро не трогается.
- **Переиспользование OriaHS.** Retrieval-сервер поднимается один раз, используется агентом, IDE-плагином, eval-джобой (см. ADR-002).
- **Сообщество MCP-серверов.** Можно подключать готовые серверы из реестра (`modelcontextprotocol/servers`): filesystem, git, postgres, slack, github и др.
- **Tool-discovery во время сессии.** MCP-сервер может сообщать про `resources/list` и `prompts/list` — агент может динамически подгружать релевантные ресурсы.
- **Изоляция сбоев.** Падение MCP-сервера = degraded-режим для его инструментов, ядро не падает.

### Отрицательные

- **Дополнительный слой.** Latency на каждый tool-call удалённого MCP-сервера растёт (network + JSON-RPC + auth).
- **Сложность observability.** Нужно отдельно трейсить MCP-вызовы, latency, error-rate per server.
- **Управление жизненным циклом.** stdio-MCP-серверы нужно запускать, мониторить, перезапускать. Это 200-300 строк кода минимум.
- **Безопасность.** MCP-сервер может выполнить произвольный code (например, `bash` через свой tool). Permission-модель должна покрывать это.
- **OAuth-флоу для HTTP-MCP.** Нужно реализовывать flow device-code или PKCE, что увеличивает поверхность ядра.

### Нейтральные

- **Размер ядра растёт** на ~600-800 строк кода MCP-клиента. Это приемлемая цена за контрактизацию расширений.

---

## 4. Alternatives Considered (Альтернативы)

### A. JS/TS-плагины с хуками (как OpenCode)

Динамическая регистрация инструментов через JS-плагины, исполняемые в ядре.

| Критерий | MCP | JS-плагины |
|---|---|---|
| Изоляция сбоев | ✅ процессная | ❌ падение плагина роняет ядро |
| Язык расширений | любой | только JS/TS |
| Безопасность | ✅sandbox-friendly | ❌ arbitrary code |
| Запуск без правки ядра | ✅ | ✅ |
| Tool-discovery runtime | ✅ через `tools/list` | ✅ через register |
| Запуск стороннего сервера без SDK | ✅ из реестра MCP | ❌ свой плагин |
| Сложность реализации | средняя | низкая |
| Совместимость с OriaHS | ✅ тривиальная | ❌ нужен JS-bridge |

**Выбор:** MCP выигрывает по изоляции и совместимости с OriaHS.

### B. Прямой SDK к OriaHS (без MCP)

Самописный Python/TypeScript-клиент к `http://oriahs/search` и `http://oriahs/retrieve`.

| Критерий | MCP | Прямой SDK |
|---|---|---|
| Связанность с OriaHS | ✅ слабая | ❌ сильная |
| Переиспользование в других агентах | ✅ | ❌ |
| Скорость интеграции | средняя | быстрая |
| Доступ к сторонним tool-серверам | ✅ | ❌ |
| Поддержка tool-discovery | ✅ | ❌ |

**Выбор:** SDK быстрее на старте, но создаёт связанность и закрывает путь к сторонним MCP-серверам.

### C. Гибрид: in-process только для performance-critical, MCP для остальных

Это и есть решение (см. §2 п.1). Альтернативы A/B — это крайние случаи.

---

## 5. Metrics (Метрики оценки)

| Метрика | Целевое значение | Способ измерения |
|---|---|---|
| Time-to-first-new-tool | < 1 час от идеи до рабочего tool-call | end-to-end замер на эталонной задаче |
| MCP tool-call latency (p95) | < 250 ms (HTTP), < 50 ms (stdio) | trace в `app/observability/metrics.py` |
| MCP server uptime | > 99.5% | health-check polling |
| Tool-call error rate | < 1% | `mcp_tool_call_errors_total` |
| Деградированный режим recovery time | < 5s | от падения сервера до пометки инструментов как unavailable |
| Доля MCP-инструментов в общем tool-call volume | > 60% к v0.5 | счётчики в registry |

---

## 6. Implementation Notes (Заметки по реализации)

### 6.1. Минимальный интерфейс `MCPClient`

```typescript
interface MCPClient {
  start(config: MCPServerConfig[]): Promise<void>;
  stop(): Promise<void>;
  listTools(): ToolSpec[];                    // агрегация со всех серверов
  callTool(name: string, input: unknown): Promise<ToolResult>;
  onServerEvent(handler: (e: ServerEvent) => void): void;
}

type ServerEvent =
  | { kind: 'server_up'; server: string }
  | { kind: 'server_down'; server: string; reason: string }
  | { kind: 'tools_changed'; server: string; added: string[]; removed: string[] }
  | { kind: 'resource_updated'; server: string; uri: string };
```

### 6.2. Встраивание в `agent-loop`

```typescript
// существующий цикл не меняется — tool-registry просто отдаёт больше инструментов
const tools = [...inProcessTools, ...mcpClient.listTools()];
const stream = await llm.complete({ model, system, messages: ctx, tools });
```

### 6.3. Стартовый набор MCP-серверов для self-agent

| MCP-сервер | Назначение | Transport | ADR |
|---|---|---|---|
| `oriahs-mcp` | retrieval, facets, hybrid search | HTTP | ADR-002 |
| `session-memory-mcp` | cross-session memory | stdio | ADR-005 |
| `filesystem-mcp` | расширенные операции с ФС | stdio | — |
| `git-mcp` | git-операции как инструменты | stdio | — |

### 6.4. Migration path

1. **v0.2.0** — каркас `MCPClient`, stdio-transport, 1 тестовый сервер.
2. **v0.3.0** — HTTP-transport, OAuth, `oriahs-mcp` подключается.
3. **v0.4.0** — `resources/*` и `prompts/*` support, dynamic tool discovery.
4. **v0.5.0** — permission-интеграция, audit-log всех MCP-вызовов.

---

## 7. Risks (Риски)

| Риск | Вероятность | Влияние | Митигация |
|---|---|---|---|
| MCP-спецификация меняется (несовместимо) | средняя | высокое | pin версии протокола, adapter-слой |
| Latency HTTP-MCP убивает UX | средняя | среднее | local cache, prefetch, stdio для горячих путей |
| MCP-сервер утечка прав | низкая | высокое | sandboxing stdio-серверов, scope-bearer tokens |
| Конфигурационный взрыв `mcp.yml` | высокая | низкое | profiles + import из директорий |
| Сторонний MCP-сервер исчезает | средняя | среднее | health-check + fallback на встроенные инструменты |

---

## 8. References (Ссылки)

- `analytics/self-agent.md` §2 — пункт «MCP-клиент откладывается на v2»
- `analytics/agents-architect.md` §1.2 — MCP-клиенты Claude Code (stdio/SSE/HTTP, OAuth)
- `analytics/agents-architect.md` §2.2 — MCP в OpenCode
- Model Context Protocol specification: https://modelcontextprotocol.io
- `modelcontextprotocol/servers` — реестр готовых MCP-серверов
