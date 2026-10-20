# Дополнительный анализ конкурентов

**Документ:** competitors-extra
**Дата:** 20 октября 2026
**Статус:** Draft v0.1
**Связанные документы:** [agents-architect.md](../agents-architect.md), [product/personas.md](product/personas.md)

---

## 0. Назначение

[`agents-architect.md`](../agents-architect.md) детально разобрал 5 architecture-line: Claude Code, OpenCode, Kilo Code, DeepSeek Harness, MiMoCode. Но рынок coding-агентов шире. Этот документ дополняет картину 6-ю продуктами, которые имеют принципиально другие архитектурные подходы или занимают разные ниши:

1. **Cursor** — IDE-native подход
2. **Aider** — git-oriented workflow
3. **Continue.dev** — open-source IDE extension
4. **Cline** (бывший Claude Dev) — VS Code extension на базе Roo Code
5. **GitHub Copilot Workspace** — cloud-first, SaaS
6. **Devin** (Cognition) — autonomous agent SaaS
7. **Codex CLI** (OpenAI) — terminal-first competitor

Понимание этих 7 подходов критично для позиционирования OryaAgent.

## 1. Cursor — IDE-native подход

### 1.1 Краткое описание

Cursor — fork VS Code (на базе Electron) с интегрированным AI-ассистентом. Не отдельный агент, а IDE с AI-фичами: inline-комплит, chat в sidebar, agent-mode с файловыми правками.

### 1.2 Архитектурные особенности

- **IDE-first:** весь опыт — внутри редактора. Нет CLI, нет TUI.
- **Proprietary core:** закрытый код, open-source только часть extensions.
- **Tight coupling с VS Code API:** uses VS Code's extension host, language servers, file watchers.
- **Local + cloud:** часть inference локально (small models для compleition), часть — cloud (Claude, GPT-4o).
- **Tab-autocomplete:** специализированный fast-model (Cursor Tab) для inline-комплита. Отдельная модель, не chat.
- **Composer mode:** multi-file edits через UI-spec, выполняется в фоне.

### 1.3 Сильные стороны

- **UX polish** — IDE-native, всё работает «из коробки», без переключения контекста
- **Inline-комплит** — низкий friction, высокая частота использования
- **Multi-file edits через Composer** — решает реальную боль (большие рефакторинги)
- **Context awareness** — знает о cursor position, open tabs, recent edits
- **Fast iteration** —YC-backed, быстро развивается

### 1.4 Слабые стороны

- **Proprietary** — не open-source, не self-hostable
- **Data privacy concerns** — код отправляется на Cursor servers
- **Pricing** — $20/month за Pro, не для всех
- **VS Code lock-in** — не работает в JetBrains, Neovim, Zed
- **No CLI** — нельзя использовать в CI, scripts, SSH sessions

### 1.5 Что OryaAgent может позаимствовать

- **Composer-like multi-file edits** — v2, как skill или subagent-mode
- **Context awareness** — git-статус, recent edits, open files — в system prompt (уже в MVP-плане)
- **Inline-комплит** — out of scope для OryaAgent (мы не IDE), но интересная идея для отдельного режима

### 1.6 Где OryaAgent сильнее

- **Open-source** — full control, no lock-in, privacy
- **CLI-first** — для разработчиков, которые не хотят покидать терминал
- **Provider-agnostic** — любой LLM, не привязан к Cursor Tab model
- **CI/scripts integration** — `orya --auto` для автоматизации

## 2. Aider — git-oriented workflow

### 2.1 Краткое описание

Aider — open-source CLI-агент, глубоко интегрированный с git. Каждый edit автоматически коммитится, история изменений — в git log. Поддерживает voice-ввод, dozens of LLM-провайдеров.

### 2.2 Архитектурные особенности

- **CLI-first** — pure terminal experience, no TUI complexity
- **Git-as-source-of-truth** — каждое изменение = git commit, undo = git revert
- **Repo map** — автоматически строит tree of files и symbols для контекста
- **Architect mode** — separates planning (один LLM-call) от execution (другой)
- **Multi-file edits** — через unified diff format
- **Watch files** — auto-reload при изменении внешним редактором

### 2.3 Сильные стороны

- **Git integration** — best-in-class, история всех изменений
- **Transparent** — каждое изменение закоммичено, ничего «теряется»
- **Lightweight** — pure Python, минимальные dependencies
- **Fast** — нет TUI overhead, всё в терминале
- **Multi-LLM** — больше 60 провайдеров из коробки
- **Repo map** — эффективный context для больших проектов

### 2.4 Слабые стороны

- **Git-centric UX** — не для проектов без git
- **Single-shot workflow** — нет persistent sessions как у Claude Code
- **No tools** (в Claude Code смысле) — нет grep, read, bash как отдельных инструментов. Aider работает через file-edit operations
- **No subagents** — нет делегирования задач
- **Limited permission model** — auto-commit всё, что может быть рискованно

### 2.5 Что OryaAgent может позаимствовать

- **Git auto-commit** — v2: опциональный auto-commit после каждого tool-edit, с configurable message
- **Repo map** — semantic tree of files + symbols (LSP-based), как часть system-prompt
- **Architect mode** — v2: два LLM-call-а — первый планирует, второй выполняет
- **Voice input** — v3: через Whisper или аналог

### 2.6 Где OryaAgent сильнее

- **Full tool-suite** — read/write/edit/bash/grep, не только file-edits
- **Subagents** (v3) — параллельные задачи
- **Better security model** — permission-engine, ask-mode по умолчанию
- **Session persistence** — append-only лог, восстановление после crash
- **Stream-first** — токены печатаются немедленно

## 3. Continue.dev — open-source IDE extension

### 3.1 Краткое описание

Continue — open-source VS Code и JetBrains extension, AI-ассистент для разработки. Поддерживает любые LLM (local + cloud), MCP, custom commands.

### 3.2 Архитектурные особенности

- **IDE extension** — не standalone, работает внутри VS Code/JetBrains
- **Open-source** (Apache 2.0), полностью self-hostable
- **Config-as-code** — `config.json` в проекте, version-controlled
- **Custom commands** — slash-commands через YAML
- **Provider-agnostic** — любая модель, любой провайдер
- **MCP support** — first-class, ecosystem of MCP-servers
- **RAG** — индексация codebase через embeddings (configurable backend)

### 3.3 Сильные стороны

- **IDE integration** — inline-комплит, chat sidebar, code actions
- **Open-source** — community-driven, transparency
- **Provider freedom** — любой LLM, including local
- **Config-as-code** — settings в репозитории, team-shared
- **MCP ecosystem** — доступ к множеству tools

### 3.4 Слабые стороны

- **IDE-bound** — не работает без VS Code/JetBrains
- **No CLI** — нельзя использовать в SSH sessions, CI
- **Limited agent loop** — нет полноценного цикла с tool-execution как у Claude Code
- **Performance** — IDE extension overhead, иногда laggy
- **Fragmented features** — chat, edit, autocomplete — разные UX

### 3.5 Что OryaAgent может позаимствовать

- **Config-as-code** — `~/.orya/config.yml` в репозитории (опционально), team-shared
- **Custom slash-commands через YAML** — v2
- **MCP support** — v0.2.0 (по ADR-005)
- **RAG / codebase indexing** — v3 (memory cross-session)

### 3.6 Где OryaAgent сильнее

- **CLI-first** — для terminal-natives
- **Full agent loop** — с permissions, audit-log, session persistence
- **Stream-first rendering** — лучше UX для long-running tasks
- **No IDE lock-in** — работает везде

## 4. Cline (бывший Claude Dev) — VS Code extension на Roo Code

### 4.1 Краткое описание

Cline — VS Code extension (бывший Claude Dev), форк Roo Code. Специализируется на coding agent-ах с tool-execution: read/write/edit/bash/terminal в VS Code.

### 4.2 Архитектурные особенности

- **VS Code extension** — webview UI + extension host
- **Tool-execution architecture** — похожа на Claude Code, но в VS Code
- **Plan/Act modes** — mode для планирования (только reads) vs выполнения (writes/bash)
- **MCP support** — first-class
- **Browser tool** — через Puppeteer, для web-interaction
- **Checkpoint system** — shadow-git snapshots для undo

### 4.3 Сильные стороны

- **VS Code integration** — best UX для VS Code users
- **MCP ecosystem** — доступ ко всем MCP-серверам
- **Plan/Act modes** — separation of concerns
- **Browser tool** — уникальная фича
- **Open-source** (Apache 2.0)

### 4.4 Слабые стороны

- **VS Code only** — не работает в других IDE
- **No CLI** — нельзя использовать без VS Code
- **Webview overhead** — медленнее, чем native CLI
- **Limited session management** — нет persistent sessions как у Claude Code
- **Fragmented fork history** — Roo Code → Cline, наследие complexity

### 4.5 Что OryaAgent может позаимствовать

- **Plan/Act modes** — v2: `--plan` режим для exploration без writes
- **Browser tool** — v3, через Playwright
- **Checkpoint system** — v2: shadow-git snapshots для undo

### 4.6 Где OryaAgent сильнее

- **CLI-first** — no IDE dependency
- **Cleaner architecture** — без webview/extension host overhead
- **Cross-platform** — работает в Linux/macOS/Windows одинаково
- **Persistent sessions** — append-only лог, восстановление

## 5. GitHub Copilot Workspace — cloud-first SaaS

### 5.1 Краткое описание

Copilot Workspace — cloud-based AI agent от GitHub, работает в браузере. Получает issue или task, генерирует план, редактирует файлы в web-редакторе, открывает PR.

### 5.2 Архитектурные особенности

- **Cloud-first** — все вычисления на GitHub servers
- **Issue → PR workflow** — интегрирован с GitHub flow
- **Web IDE** — Monaco editor в браузере, не native IDE
- **Spec-driven** — сначала генерирует spec, потом implementation
- **Multi-step plan** — разбивает задачу на шаги, выполняет по одному

### 5.3 Сильные стороны

- **GitHub integration** — deep, native
- **No setup** — всё в браузере, не нужно ничего устанавливать
- **Collaborative** — можно делиться workspace с командой
- **Spec-driven** — снижает риск misunderstanding задачи
- **PR-first** — результат сразу готов к review

### 5.4 Слабые стороны

- **No local code** — не работает с приватными репозиториями offline
- **Limited LLM choice** — только GitHub Copilot models (Claude, GPT-4)
- **Web UX** — не для terminal-native developers
- **Pricing** — $10-39/month за Copilot subscription
- **Privacy concerns** — код в cloud

### 5.5 Что OryaAgent может позаимствовать

- **Spec-driven workflow** — v3: skills для генерации specs из issues
- **Multi-step plan** — v2: agent_loop с явной фазой планирования (как Architect mode в Aider)
- **PR-first workflow** — v2: `orya pr <issue>` — генерирует branch, commits, открывает PR

### 5.6 Где OryaAgent сильнее

- **Local execution** — код не покидает машину
- **Open-source** — full control
- **CLI-native** — для terminal workflows
- **Provider-agnostic** — любой LLM
- **Privacy** — privacy-conscious users, enterprise with strict policies

## 6. Devin (Cognition) — autonomous agent SaaS

### 6.1 Краткое описание

Devin — autonomous AI software engineer от Cognition. Получает задачу в natural language, автономно: планирует, кодит, тестирует, дебажит. Длительные сессии (часы), пока задача не выполнена.

### 6.2 Архитектурные особенности

- **Cloud-first** — все вычисления на Cognition servers
- **Autonomous mode** — пользователь даёт задачу, агент работает сам
- **Long-running sessions** — часы, не минуты
- **Multi-tool integration** — browser, terminal, code editor, IDE
- **Self-debugging** — при ошибках, агент сам их исправляет
- **Team collaboration** —能看到 agent's work, вмешаться

### 6.3 Сильные стороны

- **Truly autonomous** — minimal user supervision
- **Long-running** — может делать большие задачи
- **Multi-tool** — browser, terminal, IDE — всё интегрировано
- **Self-debugging** — closure loop без user intervention

### 6.4 Слабые стороны

- **Closed-source** — proprietary, no self-hosting
- **Pricing** — enterprise-grade ($500+/month)
- **Trust** — autonomous actions без supervision рискованны
- **No local execution** — код в cloud
- **Limited transparency** — нет audit log в смысле enterprise

### 6.5 Что OryaAgent может позаимствовать

- **Autonomous mode** — v3: `--autonomous` flag с goals+judge model
- **Self-debugging** — v2: при tool-error, retry с адаптацией
- **Long-running sessions** — v2: background tasks через cron
- **Multi-tool** — v2: MCP-серверы для browser, IDE integration

### 6.6 Где OryaAgent сильнее

- **Local execution** — privacy
- **Open-source** — full control
- **CLI-native** — для terminal workflows
- **No subscription** — free для всех
- **Provider-agnostic** — любой LLM

## 7. Codex CLI (OpenAI) — terminal-first competitor

### 7.1 Краткое описание

Codex CLI — open-source terminal agent от OpenAI (выпущен в 2025). Специализация: reasoning models (o1, o3), terminal-first, agentic coding.

### 7.2 Архитектурные особенности

- **Open-source** (Apache 2.0)
- **Rust-based** — fast, single binary
- **Reasoning-models focused** — optimizes для o1/o3 thinking mode
- **Terminal-native** — TUI на ratatui
- **Sandboxed execution** — использует landlock (Linux), sandbox-exec (macOS)
- **Approval modes** — suggests/auto-edit/full-auto
- **MCP support** — first-class

### 7.3 Сильные стороны

- **Performance** — Rust, fast cold start
- **Sandboxing** — proper isolation через landlock/sandbox-exec
- **OpenAI integration** — first-class support для reasoning models
- **Approval modes** — granular control
- **MCP ecosystem** — доступ ко всем MCP-серверам
- **Terminal-native UX** — для CLI-lovers

### 7.4 Слабые стороны

- **OpenAI-focused** — лучше всего работает с OpenAI models, другие — second-class
- **Rust complexity** — harder для community contributions
- **Young ecosystem** — fewer community extensions, чем у Continue
- **Reasoning-model bias** — optimizes для thinking, может быть overkill для простых задач

### 7.5 Что OryaAgent может позаимствовать

- **Approval modes taxonomy** — `suggest` / `auto-edit` / `full-auto` — более granular, чем ask/auto
- **Sandbox via landlock** — v2: native Linux sandbox без Docker
- **Reasoning-models optimization** — v2: явная поддержка thinking-mode через `metadata.reasoning_effort`

### 7.6 Где OryaAgent сильнее

- **Python accessibility** — больше контрибьюторов
- **Provider-agnostic** — не OpenAI-focused
- **Session persistence** — append-only лог, восстановление (Codex — ephemeral sessions)
- **AI/ML integration** — для v3 (memory, semantic search)

## 8. Сводная таблица конкурентов

| Продукт | Тип | Архитектура | Open-Source | CLI | IDE | Cloud | LLM |
|---|---|---|---|---|---|---|---|
| **OryaAgent** | Coding agent | Event-sourced + provider-seam | ✅ Apache 2.0 | ✅ | ❌ | ❌ | Any |
| Claude Code | Coding agent | Monolithic | ❌ | ✅ | ✅ | ❌ | Anthropic |
| OpenCode | Coding platform | Client-server + Effect-TS | ✅ MIT | ✅ | ✅ | ❌ | Any |
| Kilo Code | Coding platform | OpenCode + enterprise layer | ✅ MIT | ✅ | ✅ | ✅ | 500+ via gateway |
| DeepSeek Harness | Agent framework | Cordis plugin-based | ✅ MIT | ✅ | ❌ | ❌ | Any |
| MiMoCode | Coding platform | OpenCode fork + autonomy | ✅ MIT | ✅ | ✅ | ❌ | Any |
| Cursor | IDE | VS Code fork | ❌ | ❌ | ✅ | ❌ | Cursor + Claude + GPT |
| Aider | CLI agent | Git-centric | ✅ Apache 2.0 | ✅ | ❌ | ❌ | 60+ |
| Continue.dev | IDE extension | VS Code/JetBrains plugin | ✅ Apache 2.0 | ❌ | ✅ | ❌ | Any |
| Cline | IDE extension | VS Code (Roo fork) | ✅ Apache 2.0 | ❌ | ✅ | ❌ | Any |
| Copilot Workspace | Cloud SaaS | Cloud-first | ❌ | ❌ | ✅ (web) | ✅ | Copilot |
| Devin | Cloud SaaS | Autonomous agent | ❌ | ❌ | ✅ (web) | ✅ | Cognition |
| Codex CLI | CLI agent | Rust + reasoning-models | ✅ Apache 2.0 | ✅ | ❌ | ❌ | OpenAI-first |

## 9. Позиционирование OryaAgent

### 9.1 Где OryaAgent уникален

- **Open-source Python CLI agent с event-sourced sessions** — единственный в этом combination
- **Provider-agnostic + ask-by-default permissions** — security-first open-source
- **Local-first + enterprise-ready** — privacy + compliance
- **Audit-trail by default** — все actions логируются, no opt-in

### 9.2 Целевая ниша

Разработчики, которые:
1. **Хотят CLI-агент** (не IDE extension)
2. **Требуют open-source** (для trust, audit, customization)
3. **Privacy-conscious** — local-first, no cloud lock-in
4. **Security-aware** — ask-by-default, audit-trail, sensitive-file protection
5. **Python-native** — для контрибьюторов из AI/ML-сообщества
6. **Provider-agnostic** — используют несколько LLM в зависимости от задачи

### 9.3 Конкурентные преимущества

| vs | Преимущество |
|---|---|
| Claude Code | Open-source, provider-agnostic, не привязан к Anthropic |
| Cursor | CLI-first, open-source, provider-agnostic, no subscription |
| Aider | Full tool-suite (не только file-edits), better security model, session persistence |
| Continue.dev | CLI-native, no IDE dependency, audit-log, better security defaults |
| Cline | CLI-native, cross-platform, no VS Code dependency |
| Copilot Workspace | Local execution, privacy, no subscription, open-source |
| Devin | Local, open-source, no $500/month subscription |
| Codex CLI | Python accessibility (vs Rust), provider-agnostic (vs OpenAI-focused), session persistence |

### 9.4 Конкурентные слабости

- **Нет IDE интеграции** (пока v0.4.0) — Cursor, Continue, Cline — имеют
- **Нет web UI** (нет планов) — Copilot Workspace, Devin — имеют
- **Нет autonomous mode** (v3+) — Devin — имеет
- **Нет inline-комплита** (нет планов) — Cursor, Continue, Copilot — имеют
- **Меньшая community** (пока) — у Aider, Continue — большая

### 9.5 Стратегия

OryaAgent не пытается заменить Cursor или Claude Code для всех. Это **нишевый продукт для terminal-native developers, которые ценят open-source, security и provider-agnostic**. Конкурентное преимущество — в architecture quality (event-sourced, provider-seam, audit-by-default), а не в breadth of features.

## 10. Открытые вопросы

1. **IDE extension v0.4.0 — VS Code or JetBrains first?** Codex CLI, Aider — VS Code-only. Cursor — VS Code fork. Continue — both. Решение: VS Code first (большая аудитория), JetBrains second (enterprise demand).

2. **Web UI — делать или нет?** Copilot Workspace, Devin — SaaS. OryaAgent — local-first. Если web UI — то self-hostable (как OpenWebUI), не SaaS. v2+.

3. **Inline-комплит — never?** Это принципиально другая модель (fast model, low latency, не agent-loop). Если делать — отдельным режимом, не как часть agent_loop. v3+.

4. **Voice input?** Aider, MiMo — имеют. Для accessibility и hands-free usage. v3.

5. **Mobile app?** Никто из конкурентов не имеет. Out of scope для coding agent.

---

**Вывод:** OryaAgent занимает чёткую нишу — open-source Python CLI coding agent с event-sourced sessions, provider-agnostic design и security-first принципами. Прямые конкуренты (Codex CLI, Aider) имеют trade-offs, которые оставляют пространство для OryaAgent. Главное — не пытаться делать всё, а делать CLI experience лучше всех.
