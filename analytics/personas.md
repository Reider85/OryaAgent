# Персоны OryaAgent

**Документ:** personas
**Дата:** 20 октября 2026
**Статус:** Draft v0.1
**Связанные документы:** [README.md](../../README.md), [user-stories.md](user-stories.md), [competitors-extra.md](../competitors-extra.md)

---

## 0. Назначение

Архитектура OryaAgent описана в [`self-agent.md`](../self-agent.md) и спецификациях. Но архитектура — это инструмент для решения задач пользователя. Этот документ описывает **для кого** мы строим OryaAgent.

Персоны — это не маркетинговые аватары. Это сжатые описания типичных пользователей с их целями, болями, окружением и context of use. Любое архитектурное решение должно быть обосновано одной или несколькими персонами.

## 1. Список персон

OryaAgent ориентирован на 4 персон:

| # | Персона | Primary? | Pain point |
|---|---|---|---|
| 1 | Senior Backend Developer (Anna) | ✅ | Тратит много времени на рутину, хочет CLI-инструмент |
| 2 | ML/Research Engineer (Dmitry) | ✅ | Работает с кодом и данными, ценит Python-экосистему |
| 3 | DevOps/SRE Lead (Maria) | ❌ | Нужен audit-trail, security, integration с CI |
| 4 | Enterprise Engineering Manager (Pavel) | ❌ | Compliance, SSO, управляемая конфигурация |

Primary — Anna и Dmitry. Это developers, для которых OryaAgent — daily driver. Maria и Pavel — вторичная аудитория, влияющая на adoption в командах.

---

## 2. Персона 1: Anna — Senior Backend Developer

### 2.1 Профиль

- **Возраст:** 32 года
- **Роль:** Senior Software Engineer в product-компании (50-200 разработчиков)
- **Стек:** Python (Django/FastAPI), PostgreSQL, Docker, Kubernetes
- **Опыт:** 8 лет в разработке
- **Контекст работы:** macOS или Linux, использует Neovim или VS Code, проводит 70% времени в терминале

### 2.2 Цели

- **Делать рутину быстрее:** рефакторинг, написание boilerplate, форматирование, миграция схем
- **Понимать незнакомый код:** быстро разобраться в legacy-модулях
- **Дебаг сложных проблем:** анализировать stack traces, искать root cause
- **Писать тесты:** не тратить время на рутинные unit-тесты
- **Изучать новые технологии:** разбираться в незнакомых библиотеках через код

### 2.3 Боли

- Cursor платный и не работает в её stack (Neovim SSH sessions)
- Claude Code — закрытый код, не хочет завязываться на одного провайдера
- GitHub Copilot — хорош для автокомплита, но не для agentic задач
- Aider — слишком git-centric, не подходит для non-git prototypes
- Continue.dev — хорош, но в VS Code, а она в Neovim

### 2.4 Context of use

- **Утро:** открывает терминал, запускает tmux с проектом, начинает с quick refactor
- **День:** debug production issue через SSH — хочет локального агента, который работает в той же SSH session
- **Вечер:** работает над side-project — хочет free LLM через Ollama для экспериментов

### 2.5 Что Anna ждет от OryaAgent

1. **CLI-native** — `pip install orya`, без IDE plugin
2. **Stream-first** — токены печатаются сразу, не ждёт полные ответы
3. **Provider-agnostic** — переключается между Claude, GPT-4o и Ollama в зависимости от задачи
4. **Permission control** — видит каждую bash-команду перед выполнением
5. **Persistent sessions** — утром продолжила вчерашний рефакторинг
6. **Audit log** — для code review, может показать, что и почему было изменено

### 2.6 Anna не хочет

- Регистрироваться на сервисах
- Отправлять свой код на чужие серверы (без явного согласия)
- Месячные подписки
- Сложный setup с Docker
- IDE plugins (она счастлива в Neovim)

### 2.7 Quote

> «Я не хочу ещё один SAAS. Я хочу инструмент, который уважает мою машину, мой стек и мой кошелёк. Если он open-source — я ещё и поконтрибьючу.»

---

## 3. Персона 2: Dmitry — ML/Research Engineer

### 3.1 Профиль

- **Возраст:** 28 лет
- **Роль:** ML Engineer в research lab или AI-стартапе
- **Стек:** Python (PyTorch, transformers, langchain), Jupyter, Docker
- **Опыт:** 5 лет, PhD в CS
- **Контекст работы:** Linux workstation с GPU, много SSH в удалённые серверы

### 3.2 Цели

- **Прототипировать быстро:** от идеи к работающему коду за час, не за день
- **Экспериментировать с моделями:** локально запускать Llama, Mistral, Qwen через Ollama
- **Воспроизводить papers:** реализовать алгоритм из arXiv-paper
- **Дебаг training loops:** понимать, почему loss не сходится
- **Писать clean code:** превратить messy research code в production-ready

### 3.3 Боли

- IDE plugins часто не работают в Jupyter / SSH sessions
- AI/ML-инструменты (vector stores, embeddings, tokenizers) — Python-first, но большинство агентов — TS
- Local inference важен (GPU дорогая, не хочется тратить на API-calls для каждой итерации)
- Хочется контрибьютить в инструменты, которые использует

### 3.4 Context of use

- **Утро:** запускает training job, пока агент рефакторит data loading code
- **День:** дебаг failed experiment, агент помогает анализировать tensor shapes
- **Вечер:** пробует новую модель через Ollama, агент помогает писать inference code

### 3.5 Что Dmitry ждет от OryaAgent

1. **Python-native** — если захочет поконтрибьютить, не нужно учить TS
2. **Ollama first-class** — локальные модели как primary option
3. **Custom LLM adapters** — экспериментальные модели через custom subclass
4. **Jupyter integration** — пока не v0.4.0, но важно в перспективе
5. **Token cost tracking** — понимает, сколько GPU-time / API-cost на эксперимент

### 3.6 Дмитрий не хочет

- Платить за API-calls при каждом эксперименте
- Зависеть от cloud LLM (privacy для research)
- Учить TypeScript для контрибьютов
- Сложный setup с docker-compose

### 3.7 Quote

> «Local inference — это не про деньги, это про trust. Я не могу отправить unpublished research на Claude.»

---

## 4. Персона 3: Maria — DevOps/SRE Lead

### 4.1 Профиль

- **Возраст:** 35 лет
- **Роль:** SRE Lead в enterprise-компании (1000+ разработчиков)
- **Стек:** Kubernetes, Terraform, Prometheus, ELK, OpenTelemetry
- **Опыт:** 10 лет, переходила из dev в ops
- **Контекст работы:** macOS, много времени в Zoom/Slack, code review в GitHub

### 4.2 Цели

- **Стандартизировать AI-инструменты в компании** — approved-tools list
- **Обеспечить compliance** — SOC 2, ISO 27001
- **Audit trail** — знать, кто, что и когда делал с production-кодом
- **Cost control** — бюджет на LLM API на команду
- **Security** — prompt injection protection, sensitive file protection

### 4.3 Боли

- Разработчики уже используют Claude Code, Cursor, Copilot — без corporate governance
- Audit-trail отсутствует для AI-driven changes
- Cost непредсказуемый (один developer может потратить $1000 в месяц)
- Compliance-officer требует documentation, которого нет
- Incident response: если AI что-то сломал — forensics невозможен

### 4.4 Context of use

- **Утро:** review overnight alerts, проверяет что AI-изменения не сломали prod
- **День:** policy review с security team
- **Вечер:** weekly report для CTO об AI adoption и cost

### 4.5 Что Maria ждет от OryaAgent

1. **MDM-managed configuration** — `/etc/orya/managed-config.yml`
2. **Audit log forwarding** в SIEM (Splunk, Datadog)
3. **SSO** через corporate identity provider
4. **Cost budgets per team / per user**
5. **Sandbox enforcement** — developers не могут отключить
6. **Permission mode lock** — запрет `--auto` в production repos

### 4.6 Maria не хочет

- Ещё один ungoverned AI tool в компании
- Cloud-only решение (data sovereignty)
- Отсутствие enterprise support
- Закрытый код (security audit невозможен)

### 4.7 Quote

> «Я не против AI в разработке, я против ungoverned AI. Дайте мне audit-trail и policy-control — и я разрешу командам использовать.»

---

## 5. Персона 4: Pavel — Enterprise Engineering Manager

### 5.1 Профиль

- **Возраст:** 42 года
- **Роль:** Engineering Manager в крупной enterprise-компании (5000+ разработчиков)
- **Стек:** Jira, Confluence, GitHub Enterprise, Jenkins
- **Опыт:** 15+ лет, бывший developer
- **Контекст работы:** Windows laptop, много meetings, code review в web UI

### 5.2 Цели

- **Ускорить delivery** — больше features per sprint
- **Снизить defect rate** — AI для test generation, code review
- **Стандартизировать tools** — все команды используют approved stack
- **Управлять cost** — KPI на engineering efficiency
- **Compliance** — audits, ISO, SOC 2

### 5.3 Боли

- Developers просят AI tools, IT-security блокирует
- Existing solutions (Copilot for Business) — limited, не agentic
- Cursor Business — не соответствует procurement policies
- ROI непонятный — «платим $20/seat, но что получаем?»

### 5.4 Context of use

- **Утро:** sprint planning, смотрит velocity metrics
- **День:** 1:1 с team leads, обсуждение blockers
- **Вечер:** quarterly review для CTO

### 5.5 Что Pavel ждет от OryaAgent

1. **Self-hosted deployment** — on-premise или private cloud
2. **SSO + RBAC** — corporate identity
3. **Cost dashboard per team** — accountability
4. **Audit reports для compliance** — SOC 2 evidence
5. **Integration с Jira/Confluence** — workflow
6. **Enterprise support** — SLA, dedicated CSM

### 5.6 Pavel не хочет

- Data leave corporate network
- Dependency от startup, которая может закрыться
- Custom contracts с multiple vendors
- Hidden costs (storage, compute, support)

### 5.7 Quote

> «Open-source — это не про бесплатно, это про контроль и audit. Если я могу self-host и аудировать код — я готов платить за enterprise support.»

---

## 6. Сводная таблица персон

| Параметр | Anna | Dmitry | Maria | Pavel |
|---|---|---|---|---|
| **Primary** | ✅ | ✅ | ❌ | ❌ |
| **Возраст** | 32 | 28 | 35 | 42 |
| **Stack** | Python, Django | Python, PyTorch | K8s, Terraform | Jira, GitHub Ent |
| **ОС** | macOS, Linux | Linux | macOS | Windows |
| **Editor** | Neovim | VS Code/Jupyter | VS Code | Web GitHub |
| **Decision role** | User | User | Influencer | Decision-maker |
| **Budget** | Personal | Lab budget | Team budget | Company budget |
| **Willingness to pay** | $0-20/mo | $0-50/mo | $20-50/seat/mo | $50-200/seat/mo |
| **LLM preference** | Claude + GPT-4o | Ollama + Claude | Anthropic Bedrock | Any (cost-driven) |
| **Key feature need** | CLI + provider-agnostic | Python-native + Ollama | Audit + governance | SSO + on-premise |

## 7. Принципы для personas

### 7.1 Не для кого мы НЕ строим

- **Для junior developers без опыта в терминале** — OryaAgent требует CLI-навыков, мы не упрощаем
- **Для non-technical users** — это developer tool, не consumer product
- **Для designers, PM, marketers** — не наш ICP
- **Для competition programming** — это нишевый use case, не наш фокус

### 7.2 Для кого мы строим, но не primary

- **QA engineers** — могут использовать для test generation, но не daily driver
- **Data engineers** — Python-native, но их стек (Airflow, dbt) не наш фокус
- **DevRel engineers** — для documentation и demos, secondary use case

### 7.3 Принцип design decisions

Любая design decision в OryaAgent должна отвечать на вопрос: «какой персоне это помогает?» Если ответ «никому конкретно» — фича откладывается. Если «всем понемногу» — это плохо, нужно выбрать primary persona.

Примеры:

| Decision | Anna | Dmitry | Maria | Pavel |
|---|---|---|---|---|
| Python вместо TS | + (cont ribute) | ++ (ML-ecosystem) | 0 | 0 |
| Ask-mode default | + (safety) | 0 (annoying) | ++ (compliance) | ++ (audit) |
| Ollama first-class | 0 (has API access) | ++ (privacy) | 0 (forbidden) | 0 (forbidden) |
| CLI-only MVP | ++ (daily driver) | + | + (scriptable) | 0 (wants UI) |
| Audit log | 0 (rarely looks) | 0 | ++ (compliance) | ++ (compliance) |
| Enterprise features (SSO, MDM) | 0 | 0 | ++ | ++ |

Когда конфликт между персонами — primary (Anna, Dmitry) побеждает. Enterprise features — optional layers, не core.

## 8. User journey

### 8.1 Anna's journey

```
Discovery: слышит про OryaAgent в podcast / HN
↓
Trial: pip install, пробует на side-project, использует с Anthropic API
↓
Adoption: начинает использовать daily, настраивает allow-list
↓
Expansion: подключает Ollama для experiments, рекомендует коллегам
↓
Contribution: открывает Issue, потом PR с custom LLM adapter
```

### 8.2 Dmitry's journey

```
Discovery: ищет Python-native coding agent
↓
Trial: пробует с Ollama, без API costs
↓
Adoption: использует для prototyping
↓
Expansion: подключает Claude для сложных задач, custom tools для ML pipeline
↓
Contribution: контрибьютит custom ML tool
```

### 8.3 Maria's journey

```
Discovery: читает SECURITY.md, проверяет compliance
↓
Evaluation: pilot в одной команде, audit log forwarding в SIEM
↓
Rollout: corporate policy + MDM, SSO integration
↓
Standardization: OryaAgent в approved-tools list
↓
Enterprise license: обратный feedback, custom features
```

### 8.4 Pavel's journey

```
Discovery: видит enterprise pitch, comparison с Copilot Business
↓
Evaluation: security audit, compliance review
↓
Pilot: 2-3 команды, ROI measurement
↓
Rollout: corporate-wide, SSO, on-premise deployment
↓
Enterprise contract: SLA, dedicated support
```

## 9. Adoption barriers per persona

| Barrier | Anna | Dmitry | Maria | Pavel |
|---|---|---|---|---|
| Setup complexity | pip install — OK | OK | corporate policy | on-premise deployment |
| Performance | cold start <500ms | OK | OK | OK |
| Cost | free OK | OK | team budget | company budget |
| Privacy | OK | critical (local) | OK | critical (on-prem) |
| Compliance | n/a | n/a | critical | critical |
| Support | community OK | community OK | community + docs | enterprise SLA |
| Integration | n/a | custom tools | SIEM, MDM | SSO, Jira |

Mitigation стратегия для каждого barrier — в [distribution-plan.md](../distribution-plan.md) и [enterprise-features.md](../enterprise-features.md).

## 10. Открытые вопросы

1. **Вторая primary persona?** Anna и Dmitry оба primary, но если придётся выбрать одного — кто? Hypothesis: Anna (больше аудитория), но data-driven decision после v0.1.0 release.

2. **Enterprise persona priority?** Maria и Pavel — v1.0.0+. Но если enterprise demand будет strong раньше — ускорить. Monitoring: GitHub Issues с enterprise-tag, Discussions.

3. **Demographic diversity?** Все персоны — tech-savvy, в IT-индустрии. Это целенаправленный выбор (developer tool). Не trying to be everything for everyone.

4. **International personas?** Все персоны — западные / русские имена. Азиатский рынок (China, India) — может потребовать different LLM providers, different compliance. v1.0+.

---

**Вывод:** OryaAgent строится для Anna и Dmitry — senior developers, которые хотят CLI-native, open-source, provider-agnostic coding agent. Maria и Pavel — вторичная аудитория, для которой enterprise layer добавляется поверх core.
