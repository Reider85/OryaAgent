# User Stories OryaAgent

**Документ:** user-stories
**Дата:** 20 октября 2026
**Статус:** Draft v0.1
**Связанные документы:** [personas.md](personas.md), [self-agent.md](../self-agent.md), [01-module-contracts.md](../spec/01-module-contracts.md)

---

## 0. Назначение

User stories — это компактные описания функциональности с точки зрения пользователя. Формат: «As a <persona>, I want <feature>, so that <benefit>». Этот документ:

- Связывает персоны с конкретными features
- Даёт приоритет каждой story (MoSCoW: Must / Should / Could / Won't)
- Привязывает stories к roadmap-версиям (v0.1.0, v0.2.0, ...)
- Даёт acceptance criteria для каждой story

Это bridge между продуктовой командой и engineering-спецификациями. Любая спецификация в `spec/` должна быть обоснована хотя бы одной user story.

## 1. Соглашения

### 1.1 Формат

```
### US-NNN: <Title>

**As a** <persona>  
**I want** <feature>  
**So that** <benefit>

**Priority:** Must | Should | Could | Won't  
**Version:** v0.1.0 | v0.2.0 | v1.0.0 | Backlog  
**Persona:** Anna | Dmitry | Maria | Pavel  

**Acceptance criteria:**
- [ ] ...
- [ ] ...

**Spec reference:** [01-module-contracts.md#...](...)
```

### 1.2 Приоритеты

- **Must** — MVP не релизится без этой story
- **Should** — важно, но можно отложить на следующую версию
- **Could** — nice-to-have, если есть время
- **Won't** — осознанно не делаем

## 2. MVP (v0.1.0) — Must-have stories

### US-001: Базовый запрос-ответ через LLM

**As a** Anna  
**I want** отправить natural-language запрос и получить осмысленный ответ от LLM  
**So that** я могу задавать вопросы о коде и получать ответы

**Priority:** Must  
**Version:** v0.1.0  
**Persona:** Anna, Dmitry  

**Acceptance criteria:**
- [ ] Пользователь вводит текст в REPL, получает ответ от LLM
- [ ] Ответ стримится посимвольно (не ждёт полного ответа)
- [ ] Поддержка streaming для OpenAI и Anthropic
- [ ] При обрыве stream — корректная обработка (retry или error)
- [ ] Можно прервать LLM-call через Ctrl+C

**Spec reference:** [02-llm-adapter-spec.md](../spec/02-llm-adapter-spec.md), [01-module-contracts.md#4-agent_loop](../spec/01-module-contracts.md)

---

### US-002: Чтение файлов

**As a** Anna  
**I want** попросить агента прочитать файл и ответить по его содержимому  
**So that** я могу быстро понять, что в файле, не открывая редактор

**Priority:** Must  
**Version:** v0.1.0  
**Persona:** Anna, Dmitry  

**Acceptance criteria:**
- [ ] LLM может вызвать tool `read` с path
- [ ] Поддержка relative и absolute paths
- [ ] Пагинация: `start_line`, `limit` параметры
- [ ] Бинарные файлы — детектятся, не выводятся как текст
- [ ] Большие файлы (>10MB) — error с понятным сообщением
- [ ] Permission: read внутри working dir — allow, вне — ask

**Spec reference:** [04-tool-contracts.md#2-read](../spec/04-tool-contracts.md)

---

### US-003: Запись новых файлов

**As a** Dmitry  
**I want** попросить агента создать новый файл с указанным содержимым  
**So that** я могу быстро создать boilerplate без переключения контекста

**Priority:** Must  
**Version:** v0.1.0  
**Persona:** Anna, Dmitry  

**Acceptance criteria:**
- [ ] LLM может вызвать tool `write` с path + content
- [ ] Atomic write (temp + rename)
- [ ] При existing file — error, если `overwrite=False`
- [ ] Создание parent-dirs через `create_dirs=True`
- [ ] Permission: всегда ask, кроме allow-list

**Spec reference:** [04-tool-contracts.md#3-write](../spec/04-tool-contracts.md)

---

### US-004: Редактирование файлов

**As a** Anna  
**I want** попросить агента отредактировать конкретный кусок файла  
**So that** я могу делать точечные правки без ручного поиска

**Priority:** Must  
**Version:** v0.1.0  
**Persona:** Anna, Dmitry  

**Acceptance criteria:**
- [ ] LLM может вызвать tool `edit` с `old_string` + `new_string`
- [ ] Уникальность `old_string` (1 match), иначе error
- [ ] `replace_all=True` для multiple matches
- [ ] Atomic write (temp + rename)
- [ ] Возвращает preview контекста вокруг замены
- [ ] Бинарные файлы — error

**Spec reference:** [04-tool-contracts.md#4-edit](../spec/04-tool-contracts.md)

---

### US-005: Выполнение bash-команд

**As a** Dmitry  
**I want** попросить агента запустить bash-команду и показать вывод  
**So that** я могу запускать тесты, собирать проект, проверять git status

**Priority:** Must  
**Version:** v0.1.0  
**Persona:** Anna, Dmitry  

**Acceptance criteria:**
- [ ] LLM может вызвать tool `bash` с command
- [ ] Возвращает stdout, stderr, exit_code
- [ ] Timeout: 300s default, configurable до 600s
- [ ] Прерывание через Ctrl+C
- [ ] Truncation: stdout > 1MB обрезается с маркером
- [ ] Permission: всегда ask, кроме allow-list (`ls`, `cat`, `git status`, etc.)

**Spec reference:** [04-tool-contracts.md#5-bash](../spec/04-tool-contracts.md)

---

### US-006: Поиск по содержимому файлов

**As a** Anna  
**I want** попросить агента найти строку/regex в проекте  
**So that** я могу быстро находить usage функций, классов

**Priority:** Must  
**Version:** v0.1.0  
**Persona:** Anna, Dmitry  

**Acceptance criteria:**
- [ ] LLM может вызвать tool `grep` с pattern
- [ ] Поддержка regex и literal
- [ ] Фильтр по glob (`*.py`)
- [ ] Контекстные строки (`-A`, `-B`)
- [ ] max_results: 100 default
- [ ] Использует ripgrep (быстро)

**Spec reference:** [04-tool-contracts.md#6-grep](../spec/04-tool-contracts.md)

---

### US-007: Сменяемость LLM-провайдера

**As a** Dmitry  
**I want** переключаться между LLM-провайдерами одной строкой конфига  
**So that** я могу использовать Ollama для экспериментов и Claude для production-quality

**Priority:** Must  
**Version:** v0.1.0  
**Persona:** Anna, Dmitry  

**Acceptance criteria:**
- [ ] Конфиг в `~/.orya/providers.yml`
- [ ] Поддержка: OpenAI, Anthropic, Ollama, OpenRouter
- [ ] Переключение через `/model` slash-command mid-session
- [ ] Migration: одна и та же сессия работает с разными провайдерами
- [ ] Cost tracking per provider

**Spec reference:** [02-llm-adapter-spec.md](../spec/02-llm-adapter-spec.md), [ADR-002](../adr/ADR-002-llm-seam.md)

---

### US-008: Безопасность по умолчанию

**As a** Anna  
**I want** чтобы опасные действия (bash, write, edit) спрашивали подтверждение  
**So that** я случайно не удалила важные файлы

**Priority:** Must  
**Version:** v0.1.0  
**Persona:** Anna, Dmitry  

**Acceptance criteria:**
- [ ] Default mode: `ask`
- [ ] Allow-list для безопасных команд (`ls`, `cat`, `git status`)
- [ ] Deny-list для опасных (`rm -rf /`, fork bomb)
- [ ] Sensitive files (`.env`, `*.pem`) — всегда ask
- [ ] Audit log: каждое permission decision
- [ ] Auto-mode: opt-in через `--auto` flag для CI

**Spec reference:** [05-security-model.md](../spec/05-security-model.md), [ADR-004](../adr/ADR-004-permissions-default-ask.md)

---

### US-009: Сохранение и восстановление сессий

**As a** Anna  
**I want** продолжить сессию после закрытия терминала или crash  
**So that** не терять контекст работы

**Priority:** Must  
**Version:** v0.1.0  
**Persona:** Anna, Dmitry  

**Acceptance criteria:**
- [ ] Все события логируются в JSONL
- [ ] `orya --resume <session_id>` продолжает сессию
- [ ] Crash recovery: partial-write последней строки отбрасывается
- [ ] `orya sessions list` показывает недавние сессии
- [ ] `orya sessions show <id>` показывает содержимое
- [ ] Восстановление: последние N сообщений видны как контекст

**Spec reference:** [03-session-format.md](../spec/03-session-format.md), [ADR-003](../adr/ADR-003-event-sourced-sessions.md)

---

### US-010: Stream-first rendering

**As a** Anna  
**I want** видеть токены ответа по мере их генерации  
**So that** не ждать 10 секунд для длинного ответа

**Priority:** Must  
**Version:** v0.1.0  
**Persona:** Anna, Dmitry  

**Acceptance criteria:**
- [ ] Токены печатаются немедленно при получении
- [ ] Tool-calls показываются как compact-карточки
- [ ] Permission prompts — модальные окна
- [ ] Latency: <50ms между LLM-token и render

**Spec reference:** [01-module-contracts.md#9-cli-tui](../spec/01-module-contracts.md)

## 3. v0.2.0 — Should-have stories

### US-011: HTTP/SSE-сервер

**As a** Dmitry  
**I want** запускать OryaAgent как HTTP-сервер  
**So that** могу подключить свой custom UI или integration

**Priority:** Should  
**Version:** v0.2.0  
**Persona:** Dmitry, Maria  

**Acceptance criteria:**
- [ ] `orya serve --port 8080` запускает HTTP-сервер
- [ ] OpenAPI-спецификация автогенерируется
- [ ] SSE-streaming для LLM-ответов
- [ ] Multiple sessions через API
- [ ] Auth: API key (basic), token (v2.1)

**Spec reference:** [01-module-contracts.md](../spec/01-module-contracts.md) (v2 расширение)

---

### US-012: MCP-клиент

**As a** Dmitry  
**I want** подключить MCP-серверы для расширения инструментов  
**So that** могу использовать filesystem, git, browser tools из экосистемы MCP

**Priority:** Should  
**Version:** v0.2.0  
**Persona:** Dmitry  

**Acceptance criteria:**
- [ ] Конфиг MCP-серверов в `~/.orya/mcp.yml`
- [ ] Transport: stdio, SSE, HTTP
- [ ] Автоматическое discovery tools
- [ ] Tool-caching (обновляется при изменении)
- [ ] OAuth для auth-required MCP-servers

**Spec reference:** [ADR-005](../adr/ADR-005-mvp-no-mcp-hooks.md) — migration path

---

### US-013: Slash-команды

**As a** Anna  
**I want** использовать slash-команды для частых действий  
**So that** не набирать длинные natural-language запросы

**Priority:** Should  
**Version:** v0.2.0  
**Persona:** Anna  

**Acceptance criteria:**
- [ ] `/exit`, `/clear`, `/help`, `/model`, `/sessions` — базовые
- [ ] `/compact` — компакция контекста
- [ ] `/export` — экспорт сессии
- [ ] `/budget` — установка budget limit
- [ ] `/permissions` — управление allow/deny list
- [ ] Custom slash-commands через YAML (v0.3.0)

**Spec reference:** [01-module-contracts.md#9-cli-tui](../spec/01-module-contracts.md)

---

### US-014: Context compaction

**As a** Anna  
**I want** чтобы агент автоматически компактил длинные сессии  
**So that** не падать от context overflow

**Priority:** Should  
**Version:** v0.2.0  
**Persona:** Anna, Dmitry  

**Acceptance criteria:**
- [ ] При подходе к лимиту контекста — автоматическая компакция
- [ ] LLM-сгенерированный summary заменяет старые сообщения
- [ ] Compaction log event в session
- [ ] `/compact` slash-command для ручной компакции
- [ ] Configurable: auto / manual / disabled

**Spec reference:** [03-session-format.md#compaction-summary](../spec/03-session-format.md) (v2)

---

### US-015: Skills-система

**As a** Anna  
**I want** сохранять повторяющиеся workflows как «skills»  
**So that** не описывать каждый раз одно и то же

**Priority:** Should  
**Version:** v0.2.0  
**Persona:** Anna  

**Acceptance criteria:**
- [ ] `~/.orya/skills/*.md` — skill-definitions
- [ ] Skill = system prompt + tool sequence
- [ ] `/skill <name>` активирует skill
- [ ] Built-in skills: refactor, test-gen, debug, doc-gen
- [ ] Community skills через `orya skills install`

**Spec reference:** Будущая спецификация

---

### US-016: Локальная Ollama-интеграция

**As a** Dmitry  
**I want** использовать локальные модели через Ollama без API costs  
**So that** экспериментировать без budget worries

**Priority:** Should  
**Version:** v0.2.0 (improved from v0.1.0 basic)  
**Persona:** Dmitry  

**Acceptance criteria:**
- [ ] Auto-discovery: при запуске OryaAgent находит Ollama
- [ ] Список установленных моделей
- [ ] Cost: всегда $0
- [ ] Token-counting через approximation
- [ ] При отсутствующей модели — подсказка `ollama pull <name>`

**Spec reference:** [02-llm-adapter-spec.md#6-ollama](../spec/02-llm-adapter-spec.md)

---

### US-017: Audit log и observability

**As a** Maria  
**I want** полный audit-trail всех действий агента  
**So that** отвечать на compliance-запросы

**Priority:** Should  
**Version:** v0.2.0  
**Persona:** Maria, Pavel  

**Acceptance criteria:**
- [ ] `~/.orya/audit.jsonl` — все permission decisions
- [ ] Все tool executions с metadata
- [ ] Все LLM-calls с cost
- [ ] `orya audit show` — query interface
- [ ] Export: OTel, syslog, JSON Lines

**Spec reference:** [07-observability-spec.md](../spec/07-observability-spec.md), [05-security-model.md#7-audit-log](../spec/05-security-model.md)

## 4. v0.3.0 — Could-have stories

### US-018: Subagents и Task-делегирование

**As a** Anna  
**I want** чтобы агент мог делегировать подзадачи субагентам  
**So that** сложные задачи разбивались на parallel work

**Priority:** Could  
**Version:** v0.3.0  
**Persona:** Anna, Dmitry  

**Acceptance criteria:**
- [ ] `Task` tool в tool-registry
- [ ] Параллельное выполнение subagent-ов
- [ ] Subagent имеет свой system-prompt
- [ ] Subagent изолирован от main session (своя сессия)
- [ ] Result возвращается в main session

**Spec reference:** [self-agent.md](../self-agent.md) (отложено на v3)

---

### US-019: Cron и autonomous mode

**As a** Maria  
**I want** планировать агента на recurring tasks  
**So that** ночные проверки и cleanup выполнялись автоматически

**Priority:** Could  
**Version:** v0.3.0  
**Persona:** Maria  

**Acceptance criteria:**
- [ ] Cron-формат в `~/.orya/cron.yml`
- [ ] Background execution без TUI
- [ ] Goal + judge-model: проверка достижения цели
- [ ] Notification: email, webhook при завершении
- [ ] Auto-retry при failure

**Spec reference:** [self-agent.md](../self-agent.md) (v3)

---

### US-020: Memory cross-session

**As a** Anna  
**I want** чтобы агент помнил мои преференции между сессиями  
**So that** не повторять каждый раз «используй ruff для форматирования»

**Priority:** Could  
**Version:** v0.3.0  
**Persona:** Anna, Dmitry  

**Acceptance criteria:**
- [ ] `~/.orya/memory.md` — user preferences
- [ ] `~/.orya/projects/<id>/memory.md` — project-specific
- [ ] Semantic search через embeddings (v2)
- [ ] Auto-extraction: agent сам обновляет memory
- [ ] Privacy: memory не отгружается externally

**Spec reference:** [self-agent.md](../self-agent.md) (v3)

---

### US-021: Sandbox (изоляция)

**As a** Maria  
**I want** изолировать выполнение bash-команд от host-системы  
**So that** минимизировать damage при ошибке или attack

**Priority:** Could  
**Version:** v0.3.0  
**Persona:** Maria, Pavel  

**Acceptance criteria:**
- [ ] `--sandbox` flag или config
- [ ] Linux: bubblewrap
- [ ] macOS: sandbox-exec
- [ ] Windows: Windows Sandbox (or Docker fallback)
- [ ] В sandbox-mode: auto-permissions (sandbox = trust boundary)

**Spec reference:** [05-security-model.md#8-sandbox](../spec/05-security-model.md)

---

### US-022: Custom slash-commands

**As a** Anna  
**I want** создавать свои slash-команды через YAML  
**So that** автоматизировать team-specific workflows

**Priority:** Could  
**Version:** v0.3.0  
**Persona:** Anna  

**Acceptance criteria:**
- [ ] `~/.orya/commands/*.yml` — definitions
- [ ] YAML: name, description, system_prompt, default_args
- [ ] Project-level: `.orya/commands/*.yml` в репозитории
- [ ] Sharing через git
- [ ] Built-in: /deploy, /test, /lint, /review

**Spec reference:** Future spec

## 5. v0.4.0 — IDE integration

### US-023: VS Code extension

**As a** Anna  
**I want** OryaAgent как VS Code extension  
**So that** коллеги, не любящие CLI, тоже могли использовать

**Priority:** Could  
**Version:** v0.4.0  
**Persona:** Anna (secondary)  

**Acceptance criteria:**
- [ ] Extension подключается к running `orya serve`
- [ ] Chat sidebar в VS Code
- [ ] Inline-diff для edit operations
- [ ] Permission prompts в VS Code UI
- [ ] Same features as CLI

**Spec reference:** Depends on US-011 (HTTP-сервер)

---

### US-024: JetBrains plugin

**As a** Pavel  
**I want** OryaAgent как JetBrains plugin  
**So that** enterprise developers в IntelliJ/Rider могли использовать

**Priority:** Could  
**Version:** v0.4.0  
**Persona:** Pavel  

**Acceptance criteria:**
- [ ] Plugin для IntelliJ, PyCharm, WebStorm
- [ ] Same features as VS Code extension
- [ ] SSO integration через corporate IdP

**Spec reference:** Depends on US-011

## 6. v1.0.0 — Production-grade

### US-025: SSO (SAML, OIDC)

**As a** Pavel  
**I want** SSO через corporate identity provider  
**So that** developers используют corporate credentials

**Priority:** Could  
**Version:** v1.0.0  
**Persona:** Pavel, Maria  

**Acceptance criteria:**
- [ ] SAML 2.0 support
- [ ] OIDC support
- [ ] Kerberos (optional)
- [ ] Token management в OS keychain
- [ ] Audit: who, when, from which IP

**Spec reference:** [enterprise-features.md](../enterprise-features.md)

---

### US-026: MDM-managed configuration

**As a** Maria  
**I want** corporate-managed конфигурацию  
**So that** developers не могли менять security policies

**Priority:** Could  
**Version:** v1.0.0  
**Persona:** Maria, Pavel  

**Acceptance criteria:**
- [ ] `/etc/orya/managed-config.yml` — Linux
- [ ] `/Library/Application Support/OryaAgent/managed-config.plist` — macOS
- [ ] Group Policy — Windows
- [ ] Override user-config
- [ ] Audit: config changes

**Spec reference:** [enterprise-features.md](../enterprise-features.md)

---

### US-027: Enterprise support и SLA

**As a** Pavel  
**I want** enterprise support с SLA  
**So that** иметь гарантию response time для critical issues

**Priority:** Could  
**Version:** v1.0.0  
**Persona:** Pavel  

**Acceptance criteria:**
- [ ] Enterprise license option
- [ ] SLA: critical — 4h response, high — 1 business day
- [ ] Dedicated CSM
- [ ] Custom feature requests prioritized
- [ ] On-premise support

**Spec reference:** [enterprise-features.md](../enterprise-features.md)

## 7. Won't-have (Backlog / Not doing)

### US-W1: Inline-комплит (как Copilot)

**Status:** Won't  
**Reason:** Принципиально другая модель (fast-model, low-latency, не agent-loop). Если делать — отдельным режимом, не как часть MVP. v3+ если будет demand.

---

### US-W2: Web UI (SaaS)

**Status:** Won't  
**Reason:** OryaAgent — local-first. Если web UI — то self-hostable (как OpenWebUI), не SaaS. Out of scope для core team. Community fork может сделать.

---

### US-W3: Mobile app

**Status:** Won't  
**Reason:** Coding agent — не для mobile. Out of scope принципиально.

---

### US-W4: Voice input

**Status:** Won't (v1.0.0+)  
**Reason:** Полезно для accessibility, но не MVP. Через Whisper — v3+.

---

### US-W5: Multi-agent teams (как dsh)

**Status:** Won't (v1.0.0+)  
**Reason:** Experimental даже у авторов. v3+.

---

### US-W6: `dream` / `distill` (как MiMo)

**Status:** Won't (v1.0.0+)  
**Reason:** Контур самоулучшения — последняя фаза. v4+.

---

### US-W7: Computer-use (как Claude Computer Use)

**Status:** Won't  
**Reason:** Out of scope для coding agent. Использовать Claude Code или специализированные tools.

---

### US-W8: Image generation

**Status:** Won't  
**Reason:** Не coding task. Out of scope принципиально.

## 8. Приоритеты и dependencies

### 8.1 v0.1.0 — MVP Must-haves

- US-001: LLM запрос-ответ
- US-002: read
- US-003: write
- US-004: edit
- US-005: bash
- US-006: grep
- US-007: Provider switching
- US-008: Permissions (ask-mode)
- US-009: Sessions (append-only + recovery)
- US-010: Stream-first rendering

### 8.2 v0.2.0 — Should-haves

- US-011: HTTP-сервер
- US-012: MCP-клиент
- US-013: Slash-команды
- US-014: Compaction
- US-015: Skills
- US-016: Ollama improvements
- US-017: Audit log + observability

### 8.3 v0.3.0 — Could-haves

- US-018: Subagents
- US-019: Cron
- US-020: Memory
- US-021: Sandbox
- US-022: Custom slash-commands

### 8.4 v0.4.0 — IDE integration

- US-023: VS Code
- US-024: JetBrains

### 8.5 v1.0.0 — Production-grade

- US-025: SSO
- US-026: MDM
- US-027: Enterprise support

### 8.6 Dependencies

```
US-023 (VS Code) ← US-011 (HTTP-сервер)
US-024 (JetBrains) ← US-011
US-025 (SSO) ← US-026 (MDM)
US-019 (Cron) ← US-018 (Subagents)
US-020 (Memory) ← US-014 (Compaction)
US-015 (Skills) ← US-013 (Slash-commands)
```

## 9. Метрики успеха per story

| US | Metric | Target |
|---|---|---|
| US-001 | LLM call success rate | >99% |
| US-002 | read tool latency | <50ms |
| US-005 | bash tool latency | <100ms overhead |
| US-007 | Provider switch time | <1s |
| US-008 | Permission ask rate | <30% of bash calls |
| US-009 | Crash recovery success | 100% |
| US-010 | Token-to-render latency | <50ms |
| US-011 | API response time | <100ms overhead |
| US-017 | Audit log completeness | 100% of permission decisions |

## 10. Открытые вопросы

1. **Story prioritization:** US-013 (slash-commands) — Must или Should? Hypothesis: Should (можно жить без них в MVP, но user experience хуже).

2. **IDE integration timeline:** v0.4.0 — realistic? Если enterprise demand раньше — ускорить.

3. **Enterprise features in v1.0.0:** Realistic? Если pre-alpha продлится долго — enterprise может стать v2.0.0.

4. **Community feedback loop:** Как собирать feedback на user stories? GitHub Discussions? Survey после v0.1.0?

---

**Вывод:** 27 user stories покрывают весь roadmap от MVP (v0.1.0) до production-grade (v1.0.0). Каждая story связана с персоной и спецификацией. Приоритизация основана на personas и архитектурных решениях из ADR.
