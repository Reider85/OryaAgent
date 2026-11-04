# FUTURE7 — Направления развития OryaAgent после полной реализации ROADMAP7

> **Версия документа:** 7.0
> **Дата:** 20 октября 2026
> **Источники:** `ARCHITECT7.md` v7.0, `ROADMAP7.md` v7.0, `BACKLOG7.md` v7.0, `analytics/agents-architect.md` (сравнение 5 SOTA), `ARCHITECT3.md` v0.3 §8 (теоретический максимум), `ARCHITECT.md` v0.1 (IFR), `ARCHITECT2.md` v0.2 (Five Whys)
> **Стек после реализации ROADMAP7:** Python 3.11+, LangChain 0.3+, LangGraph 0.2+, FastAPI, PostgreSQL 16, Redis 7, Chainlit, Next.js, OriaHS, OryaObservability SDK, LSP-серверы (6 языков), Ollama (для small-models), Anthropic/OpenAI/Google providers
> **Статус:** документ описывает направления развития после достижения целевой архитектуры v7 (full PROD реализация)
> **Метод:** 20/80 + ТРИЗ + мысл-эксперименты v0.3 §8.2 (теоретический предел скорости)

---

## Содержание

0. Executive summary
1. Часть I: Архитектурное сравнение — v7 (полная реализация) vs opencode vs kilocode
   1.1. Контекст сравнения
   1.2. Сравнение по 12 характеристикам
   1.3. Где v7 **сильнее** опencode
   1.4. Где v7 **слабее** opencode
   1.5. Где v7 **сильнее** kilocode
   1.6. Где v7 **слабее** kilocode
   1.7. Сводная таблица превосходств
   1.8. Migration paths (opencode/kilocode → v7)
2. Часть II: Направления развития после целевой архитектуры v7
   2.1. Направление A: Predictive User Model (расширение Predictive Planner)
   2.2. Направление B: Task Embedding Index (self-improvement через nearest-neighbor lookup)
   2.3. Направление C: Continuous Planner daemon (требует neuromorphic inference)
   2.4. Направление D: Hierarchical Predictive Prefetch (entire dependency tree)
   2.5. Направление E: Incremental LLM (generate only diff tokens)
   2.6. Направление F: Adaptive Compute / continuous triage
   2.7. Направление G: Federated Predictive Planner (cross-user learning)
   2.8. Направление H: Quantum-style superposition executor (мысл-эксперимент)
   2.9. Направление I: Sub-millisecond LSP через WASM (если не сделано в EXTENSION-PROD)
   2.10. Направление J: Multi-agent memory sharing + collaboration
   2.11. Направление K: Continuous prompt-learning с multi-agent judge
   2.12. Направление L: Real-time memory drift detection
   2.13. Направление M: Cross-user memory sharing (privacy-preserving)
   2.14. Направление N: Voice input + multi-modal (images, PDF)
   2.15. Направление O: Skills-система поверх retrieval (extension of v6 B-15)
3. Часть III: Гиперболизация скорости — теоретический предел
   3.1. Quantum-style superposition executor
   3.2. Neuromorphic inference (Loihi 2 / SpiNNaker 2)
   3.3. Continuous Planner daemon
   3.4. Predictive User Model K=3
   3.5. Pre-trained Task Embeddings (lookup вместо plan)
   3.6. Incremental LLM
   3.7. Hierarchical Predictive Prefetch
   3.8. Adaptive Compute
   3.9. Sub-millisecond LSP
   3.10. Federated Predictive Planner
4. Часть IV: Дорожная карта гиперболизации v8-v10
5. Часть V: Открытые вопросы (TBD) после v7
6. Часть VI: Итог

---

## 0. Executive summary

После полной реализации `ROADMAP7.md` (до PROD) OryaAgent v7 становится production-ready кодинг-агентом с уникальным архитектурным профилем:

- **Скорость:** latency p50 ≤ 800 ms, p95 ≤ 3 s (vs opencode ~5-10 s, vs kilocode ~5-8 s).
- **Cost:** $0.20/session (vs opencode ~$0.5-1.0, vs kilocode ~$0.4-0.8 — kilocode использует gateway без наценки).
- **Self-verification:** 100% ходов через tri-model pipeline (vs opencode 0%, vs kilocode 0% — у них нет встроенного tester).
- **LSP-native:** sub-ms latency на code-facts (vs opencode experimental LSP, vs kilocode нет LSP, только kilo-indexing semantic).
- **Batch pipeline:** 100-400 prompts/hour (vs opencode/kilocode — нет batch pipeline, только интерактив).
- **Long-term memory:** 3-layer (L0 MD + L1 SQLite + L2 Qdrant) + `/learn` (vs opencode CLAUDE.md-style memory, vs kilocode kilo-memory).

**Где v7 слабее:**
- **Ecosystem/community:** opencode 214K+ stars, 75+ providers, огромная база MCP-servers; kilocode — enterprise distribution, kilo-gateway с 500+ моделями без наценки. v7 — niche Python-проект.
- **IDE-integration:** opencode имеет TUI + desktop + VS Code SDK + ACP + web; kilocode — VS Code + JetBrains + Cloud Agent. v7 — Chainlit + Next.js (no native IDE plugins).
- **Enterprise:** kilocode — SSO, audit logs, model policies, sandbox (kilo-sandbox). v7 — single-tenant по умолчанию, EXTENSION-PROD добавляет multi-instance.
- **Provider choice:** opencode — 75+ providers через models.dev; kilocode — 500+ через kilo-gateway. v7 — Anthropic, OpenAI, Ollama, Google Vertex (4 major).

**Главный вывод:** v7 — это **специализированный high-performance кодинг-агент** для Python-проектов с LSP-поддержкой; opencode и kilocode — **универсальные платформы** с широкой экосистемой. Они не конкурируют напрямую; v7 атакует **нишу speed + self-verification + LSP-native**, где опencode/kilocode архитектурно слабы.

После достижения целевой архитектуры v7, развитие идёт по **15 направлениям** (см. Часть II), с **гиперболизацией скорости** как главным long-term вектором (Часть III), и **теоретическим пределом** в виде quantum-style superposition executor (Часть IV).

---

## 1. Часть I: Архитектурное сравнение — v7 (полная реализация) vs opencode vs kilocode

### 1.1. Контекст сравнения

Сравнение проводится по **12 характеристикам** (унаследовано от `analytics/agents-architect.md` §6 + расширено для v7). Включены:

- **opencode** (v2.0, Effect-TS core, по состоянию на конец 2026): клиент-сервер, event-sourced SQLite + Context Epoch, MCP + JS-plugins + skills, 75+ providers через models.dev, experimental LSP, 214K+ GitHub stars, 1046 contributors.
- **kilocode** (гибридная архитектура — ядро opencode + enterprise-надстройка, конец 2026): VS Code + JetBrains + Cloud Agent, kilo-gateway (500+ models без наценки), kilo-indexing (semantic search), kilo-memory, kilo-sandbox, SSO + audit + model policies.
- **OryaAgent v7** (после полной реализации ROADMAP7 до PROD): Python/LangChain/LangGraph, DFC (5 слоёв), Tri-Model Pipeline (plan→execute→test concurrent), LSP-native (6 языков), UKB (5 namespaces), long-term memory 3-layer + /learn, batch pipeline, tournament + judge-mcp, predictive planner, symbolic shortcut, OryaObservability SDK + sampler-proxy.

### 1.2. Сравнение по 12 характеристикам

| Характеристика | opencode | kilocode | OryaAgent v7 |
|---|---|---|---|
| **1. Процессная модель** | клиент-сервер: тонкие клиенты + сервер (Effect-TS) | клиент-сервер на ядре opencode + IDE-хосты | клиент-сервер (FastAPI) + in-process agent-loop |
| **2. Разделение UI и ядра** | да — HTTP API/SSE, OpenAPI-codegen SDK | да — через API ядра opencode | да — FastAPI + Chainlit/Next.js |
| **3. Язык / рантайм** | TypeScript, Bun, Effect-TS | TypeScript, Bun, Effect-TS | Python 3.11, asyncio, LangGraph |
| **4. Хранение сессий** | event-sourced SQLite + снапшоты, Context Epoch | как в opencode (+ kilo-memory) | PostgresSaver (LangGraph) + L0 MD + L1 SQLite FTS5 + L2 Qdrant (3-layer) |
| **5. Механизм расширения** | JS-плагины, события, MCP, skills | всё ядро opencode + hub/маркетплейс + modes | MCP (primary contract, UKB — specialization) + in-process tools |
| **6. Мультиагентность** | general + кастомные агенты, @-упоминания | orchestrator, субагенты, agent-manager, Gastown | Multi-Agent Tournament + judge-mcp, Best-of-N, no general subagents |
| **7. Изоляция / безопасность** | permission-правила по паттернам | kilo-sandbox + enterprise-контур | PermissionPolicy (v5) + LSP-sandbox + sampler-proxy always-keep (incidents) |
| **8. Автономные механизмы** | очередь промптов, GitHub Action | фоновые агенты, цели, ревью-сервис | Predictive Planner (background) + Batch Pipeline (CI) + (FUTURE: cron, goals+judge) |
| **9. LLM-шов** | models.dev, 75+ провайдеров | gateway Kilo, 500+, BYOK, локальные | TieredModelRouter (small/large/tournament) + ConnectionPool + PromptCacheLayout; 4 major providers (Anthropic, OpenAI, Ollama, Vertex) |
| **10. Source of code-facts** | `read`/`grep` + experimental LSP (opt-in) | kilo-indexing (semantic), kilo-memory; no LSP | LSP-native (primary, sub-ms) + UKB (hybrid retrieval, fallback) |
| **11. Self-verification** | нет (нет tester-фазы в цикле) | нет (нет tester-фазы в цикле) | Tri-Model Pipeline (plan→execute→test) с Concurrent Tester (early-abort) |
| **12. Batch / CI-benchmark** | нет (только интерактив) | нет (только интерактив; CI через Cloud Agent) | BatchRunner (prompts.yml → results.jsonl) + BenchmarkComparator |

### 1.3. Где v7 **сильнее** опencode

**1. Self-verification в каждом ходе (Tri-Model Pipeline + Concurrent Tester).** opencode не имеет tester-фазы как архитектурного шва. Каждый ход opencode — один LLM-call, без встроенной проверки. v7 запускает planner (Haiku, 300 ms) → executor (Sonnet, 2-6 s) → tester (Haiku, 300 ms, concurrent с последними токенами executor'а). Tester проверяет критерии, заданные planner'ом — узкий контекст → маленькая модель → +0.5% cost. Это даёт **self-verifying loop из коробки**: если tester ловит fail, planner replan'ит (bounded N=2), вместо того чтобы показывать пользователю неверный ответ. opencode полагается на пользователя: «ошибся? попроси переделать». v7 — на 1-3 итерации autonomous replan'ов меньше.

**2. LSP-native code facts (primary source, sub-ms latency).** opencode имеет experimental LSP tool (opt-in через `OPENCODE_EXPERIMENTAL_LSP_TOOL=true`), но использует его для `goToDefinition`, `findReferences` и т.д. — **не как первичный источник фактов о коде**. v7 ставит LSP-native (pyright, typescript-language-server, rust-analyzer, gopls, jdtls, lua-language-server) как **primary**; `read`/`grep` — fallback. На типичной code-задаче (5 символов для hover + 1 для definition + 3 для references) opencode делает 3-5 LLM round-trips + чтение файлов (2-20K токенов); v7 — 9 LSP-calls × 10 ms = 90 ms + 100-500 токенов на signatures. **Latency win: 30-100×; token win: 10-50×.**

**3. Long-term memory с fast-update mechanism + `/learn`.** opencode имеет AGENTS.md (project context file) + session-log SQLite; kilocode — kilo-memory. Но ни у кого нет:
- 3-layer hybrid memory (L0 MD bootstrap + L1 SQLite FTS5 + L2 Qdrant) — v7 наследует от v6.
- `/learn` команда — capture успешного tool-call sequence в один atomic-append (<1 ms) без перезапуска сессии.
- Compaction flow L0 → L1 → L2 с outbox-pattern (async, не блокирует turn).

opencode AGENTS.md — это **статичный файл**, обновляемый вручную или через `/init`. v7 `LEARNED.md` — **живая память**, пополняемая из работы агента.

**4. Batch Pipeline (prompts.yml → results.jsonl).** opencode — только интерактивный режим. Нельзя прогнать 50 промптов на CI, нельзя сделать built-in benchmark для собственного развития. v7 имеет BatchRunner + BenchmarkComparator: каждый PR может прогнать `prompts.yml` и сравнить метрики с main. Это даёт **self-improvement feedback-loop**: regression-detector, A/B-testing архитектурных решений, continuous evaluation. opencode/kilocode полагаются на **внешние** benchmark (SWE-bench, HumanEval), v7 — на **built-in**.

**5. Predictive Planner с Heat Cache.** opencode и kilocode не прогнозируют следующий промпт пользователя — каждый ход ожидает предыдущий. v7 Predictive Planner (background Qwen-3B / Haiku-3.5) прогнозирует next prompt, prefetcher греет Heat Cache **до** прихода промпта. Когда пользователь посылает промпт, HOT уже собран → **первый токен за <500 ms** (vs opencode ~2-5 s time-to-first-token).

**6. Symbolic Shortcut (LLM bypass для детерминированных задач).** opencode и kilocode вызывают LLM для каждой задачи, включая детерминированные (`rename`, `format`, `organize-imports`). v7 SymbolicClassifier распознаёт intent, LSP делает работу, LLM не вызывается. ~15% ходов без LLM-executor → -2-6 s latency на каждом таком ходе, -90% tokens.

**7. Tournament + judge-mcp для сложных задач.** opencode не имеет parallel-executor mode. kilocode имеет orchestrator + subagents (sequential). v7 TournamentExecutor: 3 parallel executors (different models/temperatures), judge-mcp выбирает лучшего. Latency = max(N), не sum. На сложных задачах с риском провала — **та же latency** с 3× cost, но **-2-3 replan-итераций** (каждая +latency). Net win для power-tasks.

**8. OryaObservability SDK integration (PII-masking, cost-tracking, guardrail, eval).** opencode использует LangSmith/LangFuse через env-переменные (basic observability). v7 интегрирует OryaObservability SDK (production-grade): PII-masking in-process (fail-closed), per-token cost-tracking через `price_book.yaml`, prompt-injection classifier, embedding-drift detection, rule-based + LLM-as-judge eval. + sampler-proxy для динамической sample-rate без рестарта.

**9. DFC (Dynamic Fast Context) — in-window context discipline.** opencode Context Epoch + Mid-Conversation System Messages — это provably-stable prefix, но не дисциплина in-window context. v7 DFC: 5 слоёв (HEAT/HOT/WARM/COLD/ICE), в окно попадает только HOT (4-8K tokens). Остальные — retrievable. На длинной сессии opencode разрастается линейно; v7 держит окно ≤16K.

### 1.4. Где v7 **слабее** opencode

**1. Ecosystem и community.** opencode — 214K+ GitHub stars, 1046 contributors, огромная база MCP-servers (modelcontextprotocol/servers registry), тысячи плагинов, ACP-clients (Zed, любые редакторы). v7 — niche Python-проект с командой из 2 разработчиков. Это означает:
- **Plugin ecosystem:** opencode имеет готовые плагины для любых use-cases (git, slack, linear, github, jira, etc.). v7 — нужно писать своё или оборачивать MCP-servers.
- **Community support:** opencode имеет активный Discord, документацию, talks. v7 — внутренний проект.
- **Tutorials и learning curve:** opencode имеет тысячи туториалов на YouTube. v7 — нужно писать свои.

**2. Provider choice (LLM-шов).** opencode — 75+ провайдеров через models.dev (OpenAI, Anthropic, Google, Azure, Hugging Face, GitHub Copilot, GitLab Duo, etc.). v7 — 4 major providers (Anthropic, OpenAI, Ollama, Google Vertex). Это означает:
- **BYOK:** opencode — Bring-Your-Own-Key для любого провайдера. v7 — тоже, но нужно писать adapter.
- **Local LLMs:** opencode — Ollama, llama.cpp, Atomic Chat, LM Studio. v7 — Ollama (через LangChain ChatOllama).
- **Cloud providers:** opencode — Vertex AI, Azure OpenAI, AWS Bedrock. v7 — только Anthropic/OpenAI/Vertex.

**3. IDE-integration.** opencode имеет TUI (OpenTUI/Solid) + desktop-приложение (macOS/Windows/Linux) + VS Code SDK + ACP (Zed, любые редакторы) + Web client + Slack + GitHub Action. v7 — Chainlit (web chat) + Next.js (BETA+) — **no native IDE plugins**. Это означает:
- **VS Code users:** opencode — native extension. v7 — нужно переключаться на Chainlit/Next.js UI.
- **JetBrains users:** opencode — no native plugin (ACP only). v7 — no native plugin. Одинаково слабо.
- **TUI users:** opencode — rich TUI. v7 — нет TUI (только web UI).

**4. Distribution и packaging.** opencode — `curl -fsSL https://opencode.ai/install | bash` или `npm install -g opencode`, бинарь для macOS/Windows/Linux. v7 — `pip install orya-agent` + `docker-compose up` (нужен PostgreSQL, Redis, OriaHS). Это означает:
- **Time-to-first-run:** opencode — 30 секунд. v7 — 5-10 минут (docker-compose setup).
- **Resource footprint:** opencode — ~100 MB. v7 — ~500 MB (с OriaHS, OryaObservability stack).

**5. Plugin discovery и marketplace.** opencode — JS-плагины (hooks: `tool.execute.*`, события), маркетплейс. v7 — MCP-servers (через UKB), но нет маркетплейса. Это означает:
- **Plugin authoring:** opencode — JS-файл в `.opencode/plugin/`. v7 — MCP-server (Python/TS/anything), сложнее.
- **Plugin discovery:** opencode — маркетплейс. v7 — github search MCP-servers.

**6. Documentation и learning materials.** opencode — обширная документация, MDX-статьи, examples, video-tutorials. v7 — `ARCHITECT7.md`, `ROADMAP7.md`, `BACKLOG7.md`, `FUTURE7.md` — внутренняя документация, не user-friendly.

### 1.5. Где v7 **сильнее** kilocode

**1. LSP-native vs kilo-indexing (semantic only).** kilocode имеет `kilo-indexing` — semantic search по коду (embeddings), но **нет LSP**. Для типичной code-задачи kilocode делает semantic search + read+grep; v7 — LSP hover/def/refs (sub-ms, deterministic, no embedding round-trip). На идентификатор-lookup (`UserService`) kilocode платит ~50-100 ms (Qdrant search); v7 — <10 ms (LSP workspace/symbol). **Latency win: 5-10× на code-facts.**

**2. Self-verification (Tri-Model Pipeline).** kilocode — нет tester-фазы в цикле (как opencode). v7 — Tri-Model + Concurrent Tester (см. §1.3 #1).

**3. Batch Pipeline.** kilocode — только интерактивный (Cloud Agent = web UI, но не batch). v7 — BatchRunner (см. §1.3 #4).

**4. Predictive Planner + Heat Cache.** kilocode — нет predictive planner. v7 — да (см. §1.3 #5).

**5. Symbolic Shortcut.** kilocode — нет LLM bypass для детерминированных задач. v7 — да (см. §1.3 #6).

**6. Long-term memory 3-layer + `/learn`.** kilocode — kilo-memory (без явной 3-layer структуры и без `/learn` команды). v7 — 3-layer + `/learn` (см. §1.3 #3).

**7. Open-source architecture (no vendor lock-in).** kilocode — hybrid (kilo-gateway is proprietary, model policies are enterprise-only). v7 — fully open-source Python/LangChain/LangGraph/OriaHS/OryaObservability. Можно self-host без vendor payments.

### 1.6. Где v7 **слабее** kilocode

**1. Enterprise features.** kilocode — SSO (SAML, OIDC), audit logs, model policies (organization-level, кто может использовать какую модель), enterprise support. v7 — single-tenant по умолчанию, EXTENSION-PROD добавляет multi-instance, но нет enterprise-политик. Это означает:
- **Enterprise adoption:** kilocode — готов для Fortune 500. v7 — нужен significant extension.
- **Compliance:** kilocode — SOC2, HIPAA-ready. v7 — нет compliance certifications.

**2. kilo-sandbox (production-ready isolation).** kilocode — kilo-sandbox (gVisor/firecracker-style, production-grade). v7 — sandbox через LSP-server sandbox (separate process, no FS write) + (FUTURE) bash sandbox. Это означает:
- **Untrusted code execution:** kilocode — может безопасно выполнять untrusted bash. v7 — нет, только trusted workflows.
- **CI/CD pipeline isolation:** kilocode — каждый PR в отдельном sandbox. v7 — нет native sandbox.

**3. kilo-gateway (500+ models без наценки).** kilocode — kilo-gateway прокси к 500+ моделям с единой квотой и без наценки. v7 — 4 major providers (Anthropic, OpenAI, Ollama, Vertex), user платит провайдеру напрямую. Это означает:
- **Cost optimization:** kilocode — без наценки, user платит only for what they use. v7 — наценка провайдеров.
- **Unified billing:** kilocode — один счёт за все модели. v7 — separate bills per provider.

**4. Multi-platform IDE support.** kilocode — VS Code + JetBrains + Cloud Agent + Slack/Linear/GitHub GitLab integration. v7 — Chainlit + Next.js (no native IDE plugins, см. §1.4 #3).

**5. Code review as a service.** kilocode — code review service (PR-comments from agent). v7 — нет native code-review integration.

**6. Voice input + multi-modal.** kilocode — voice input (через browser speech-to-text). v7 — нет (v6 сознательно отклонил multi-modal input, v7 наследует).

### 1.7. Сводная таблица превосходств

| Характеристика | v7 сильнее opencode? | v7 сильнее kilocode? | Примечание |
|---|---|---|---|
| Self-verification (Tri-Model) | ✅ да | ✅ да | v7 уникален — ни у кого нет tester-фазы |
| LSP-native code facts | ✅ да (opencode experimental) | ✅ да (kilocode только kilo-indexing) | v7 — sub-ms; другие — 50-500 ms |
| Long-term memory 3-layer + /learn | ✅ да (opencode только AGENTS.md) | ✅ да (kilocode kilo-memory без /learn) | v7 уникален |
| Batch pipeline + benchmark | ✅ да (opencode только интерактив) | ✅ да (kilocode только Cloud Agent) | v7 уникален |
| Predictive Planner + Heat Cache | ✅ да | ✅ да | v7 уникален |
| Symbolic Shortcut (LLM bypass) | ✅ да | ✅ да | v7 уникален |
| Tournament + judge-mcp | ✅ да | ⚠️ partial (kilocode has subagents, но sequential) | v7 — parallel + judge |
| DFC (in-window context discipline) | ✅ да (opencode Context Epoch, но не DFC) | ✅ да | v7 уникален |
| OryaObservability SDK | ✅ да (opencode basic) | ✅ да (kilocode kilo-telemetry, но без sampler-proxy) | v7 уникален |
| UKB (Unified Knowledge Bus) | ✅ да (opencode fragmented retrieval) | ✅ да (kilocode fragmented retrieval) | v7 уникален |
| Ecosystem/community | ❌ слабее (opencode 214K+ stars) | ❌ слабее (kilocode enterprise distribution) | v7 — niche |
| Provider choice | ❌ слабее (opencode 75+) | ❌ слабее (kilocode 500+ via gateway) | v7 — 4 major |
| IDE-integration | ❌ слабее (opencode TUI/desktop/VS Code/ACP) | ❌ слабее (kilocode VS Code/JetBrains/Cloud Agent) | v7 — Chainlit/Next.js only |
| Distribution/packaging | ❌ слабее (opencode 30s install) | ❌ слабее (kilocode 30s install) | v7 — 5-10 min docker-setup |
| Enterprise features | ⚠️ partial (v7 EXT-PROD multi-instance) | ❌ слабее (kilocode SSO/audit/policies) | v7 — нет enterprise |
| Sandbox | ❌ слабее (v7 only LSP-sandbox) | ❌ слабее (kilocode kilo-sandbox production) | v7 — нет native sandbox |
| Cost optimization | ⚠️ partial (v7 tiered router) | ❌ слабее (kilocode kilo-gateway без наценки) | v7 — pay providers directly |
| Multi-platform IDE | ❌ слабее | ❌ слабее | v7 — нет native IDE plugins |
| Code review as a service | ❌ слабее | ❌ слабее (kilocode имеет) | v7 — нет |
| Voice input + multi-modal | ❌ слабее | ❌ слабее (kilocode voice input) | v7 — нет (сознательно отклонено) |

**Итог:** v7 **сильнее** в 10 из 20 характеристик (архитектурные primitives: self-verification, LSP-native, memory, batch, predictive, symbolic, tournament, DFC, observability, UKB). v7 **слабее** в 8 из 20 (ecosystem, providers, IDE, distribution, enterprise, sandbox, cost, multi-modal). 2 характеристики — partial.

**Стратегический вывод:** v7 атакует **архитектурную нишу** (speed + self-verification + LSP-native + batch), где опencode и kilocode **архитектурно слабы** (они построены как универсальные платформы). v7 не пытается догнать их в ecosystem — v7 предлагает **другую ценность**: production-grade speed + self-correctness без внешних dependencies.

### 1.8. Migration paths (opencode/kilocode → v7)

#### 1.8.1. Migration path: opencode → v7

**Для кого:** пользователи, которые хотят:
- Self-verifying loop (Tri-Model Pipeline).
- LSP-native code-facts (vs experimental LSP).
- Batch pipeline (CI-benchmark).
- Long-term memory с `/learn`.

**Migration steps:**
1. Install v7: `pip install orya-agent && docker-compose up`.
2. Migrate AGENTS.md → v7 `PREFERENCES.md` + `FACTS.md` (manual, ~30 min).
3. Configure providers: settings.yaml (Anthropic, OpenAI, Ollama, Vertex).
4. Configure LSP-servers: auto-detected from project languages.
5. Run first session: `orya chat` (Chainlit UI).
6. Try `/learn` после успешного tool-call sequence.
7. Try batch: `orya batch run --input prompts.yml --output results.jsonl`.

**Что не мигрирует:**
- opencode JS-плагины (нужно переписать как MCP-servers).
- opencode TUI (v7 — нет TUI).
- opencode custom agents `.opencode/agent/*.md` (нужно переписать как LangGraph subgraphs).

#### 1.8.2. Migration path: kilocode → v7

**Для кого:** пользователи, которые хотят:
- LSP-native (vs kilo-indexing semantic only).
- Open-source without vendor lock-in.
- Predictive Planner + Symbolic Shortcut.
- Batch pipeline.

**Migration steps:**
1. Install v7 (см. выше).
2. Migrate kilo-memory → v7 L0+L1+L2 (export из kilo-memory, import в v7 `/memory import`).
3. Migrate kilo-gateway keys → v7 per-provider settings (Anthropic, OpenAI, Ollama, Vertex).
4. Lose kilo-sandbox (v7 не имеет native sandbox — FUTURE).
5. Lose enterprise features (SSO, audit, policies — FUTURE).

**Что не мигрирует:**
- kilo-sandbox (нужно ждать FUTURE).
- kilo-gateway (нужно платить провайдерам directly).
- Enterprise SSO/audit (нужно ждать FUTURE).
- kilo-vscode / kilo-jetbrains extensions (нужно использовать Chainlit/Next.js).

---

## 2. Часть II: Направления развития после целевой архитектуры v7

После полной реализации `ROADMAP7.md` (до PROD) v7 — production-ready. Дальнейшее развитие идёт по **15 направлениям**, сгруппированным по темам:

### 2.1. Направление A: Predictive User Model (расширение Predictive Planner)

**Источник:** ARCHITECT3 §8.2.4 (Predictive User Model).

**Идея:** v7 Predictive Planner (P-22) прогнозирует **следующий 1 промпт** (N=1). Predictive User Model — расширяет до **K=3** следующих промптов с вероятностями. Prefetcher греет HOT для top-K.

**Латентность-предел:** если top-1 hit rate >80% — latency = <500 ms почти всегда. Если top-2/3 hit — latency = <800 ms.

**Реализация в v8+:**
1. Расширить `app/core/workflow/predictive_planner.py::PredictivePlanner` до `PredictiveUserModel`:
   - `_predict_next_k(k=3) -> list[Prediction]`.
   - Top-K prefetch в Heat Cache.
   - Probability scoring для prefetch priority.
2. Embedding-based similarity для prompt classification.
3. Federated learning (см. Направление G).

**Почему не в v7:** нужен датасет пользовательских сессий (минимум 10K сессий). v7 может начать собирать через batch pipeline (P-20).

### 2.2. Направление B: Task Embedding Index (self-improvement через nearest-neighbor lookup)

**Источник:** ARCHITECT3 §8.2.5 (Pre-trained Task Embeddings).

**Идея:** индекс всех задач, которые агент когда-либо видел (через batch pipeline + session-log), в виде task-embeddings. На новом промпте — nearest-neighbor lookup → готовый план.

**Латентность-предел:** planner полностью убирается (lookup <10 ms вместо 300 ms).

**Реализация в v8+:**
1. Qdrant collection `task_embeddings` (new, 1024-dim bge-m3).
2. Pipeline: batch-runner → task-embeddings → Qdrant.
3. UKB namespace `task.lookup`: `ukb.lookup(query, capability="task.lookup")` → nearest-neighbor task + plan.
4. Если similarity > 0.9 — reuse plan; иначе — fallback на planner.

**Почему не в v7:** нужно накопить датасет (минимум 10K задач). v7 может начать собирать через batch pipeline (P-20) и session-log.

### 2.3. Направление C: Continuous Planner daemon (требует neuromorphic inference)

**Источник:** ARCHITECT3 §8.2.3 (Continuous Planner daemon).

**Идея:** planner-процесс работает **непрерывно** в фоне, поддерживая pool готовых планов для вероятных следующих промптов. Когда пользователь посылает промпт — план уже готов.

**Латентность-предел:** -300 ms (planner полностью off critical path).

**Реализация в v10+:** (требует neuromorphic inference, см. Часть III §3.2).
1. Планировщик работает раз в 100 ms (vs раз в ход в v7).
2. Pool из top-K ready plans.
3. Match incoming prompt against pool → instant plan.

**Почему не в v7:** high idle cost (LLM работает даже когда не нужен). Нужен neuromorphic inference (1000× lower energy), ожидается к 2028-2030.

### 2.4. Направление D: Hierarchical Predictive Prefetch (entire dependency tree)

**Источник:** ARCHITECT3 §8.2.7.

**Идея:** когда planner детектирует, что текущая задача — модификация функции X, prefetcher тянет **всю** зависимость X (callers, callees, types, tests) параллельно.

**Латентность-предел:** убирает серию LSP-запросов в одном ходе → -300-800 ms.

**Реализация в v8+:**
1. Расширить `app/core/workflow/prefetcher.py::Prefetcher`:
   - `prefetch_dependency_tree(location, depth=2)`.
   - Параллельно: LSP refs (callers), LSP def (callees), types (через LSP hover), tests (через grep test_*).
2. UKB namespace `lsp.dependency_tree`: `ukb.lookup(location, capability="lsp.dependency_tree")`.

**Почему не в v7:** нужна integration с call-graph analyzer (есть в LSP `textDocument/references`, но не в chain). Можно реализовать как extension B-26 (LSP-native).

### 2.5. Направление E: Incremental LLM (generate only diff tokens)

**Источник:** ARCHITECT3 §8.2.6.

**Идея:** executor генерирует только **diff** между предыдущим состоянием и новым, а не полный ответ. Например, для rename — только изменённые строки.

**Латентность-предел:** -50-80% tokens на типичном ходе с edit-task.

**Реализация в v9+:** (требует изменения LLM-архитектуры).
1. Structured-output + JSON-schema constraints (available in OpenAI/Anthropic).
2. v7 уже частично это делает через Symbolic Shortcut (#23) для детерминированных задач.
3. Для LLM-tasks — использовать constrained generation (например, `outlines` Python package).

**Почему не в v7:** требует изменения LLM-architecture (не все провайдеры поддерживают constrained generation).

### 2.6. Направление F: Adaptive Compute / continuous triage

**Источник:** ARCHITECT3 §8.2.8.

**Идея:** каждые 100 ms — переоценка: «нужно ли продолжать executor? можно ли early-exit? можно ли переключиться на более дешёвую модель?».

**Латентность-предел:** -10-30% cost на ход за счёт раннего переключения.

**Реализация в v9+:**
1. Расширить `app/core/workflow/tri_model.py::_test_concurrent_node` до continuous monitor:
   - Тик раз в 100 ms (vs в v7 — раз в partial-diff batch).
   - Re-evaluate: confidence-aware early-exit, model switch (large → small если task simpler чем expected).
2. Integration с TieredModelRouter (#30).

**Почему не в v7:** нужен confidence-aware streaming inference (провайдеры ещё не дают).

### 2.7. Направление G: Federated Predictive Planner (cross-user learning)

**Источник:** ARCHITECT3 §8.2.10.

**Идея:** Predictive Planner обучается на сессиях **всех** пользователей (с privacy-preserving federated learning), а не только текущего. Датасет в 100-1000× больше → точность >80% (vs 60% на single-user).

**Латентность-предел:** -200-400 ms на ход при accuracy >80% (vs 60% на single-user).

**Реализация в v10+:** (требует federated learning infrastructure).
1. Federated learning loop поверх MemoryStore (v6 B-21 + v6 P-18).
2. Differential privacy guarantees.
3. User opt-in через settings.

**Почему не в v7:** нет federated learning infrastructure для LLM. v6 OQ-5 упоминает это. Privacy risk — high.

### 2.8. Направление H: Quantum-style superposition executor (мысл-эксперимент)

**Источник:** ARCHITECT3 §8.2.1.

**Идея:** N parallel executors в «суперпозиции» — все возможности explored одновременно, judge коллапсирует в лучшего. На классической машине это N× cost; на гипотетическом quantum-inference — 1× cost.

**Латентность-предел:** max(N executors) = latency одного executor'а. Cost-предел (классический): N×. Cost-предел (квантовый): O(log N) через Grover-like amplification.

**Реализация в far-future (post-classical):** когда quantum-inference hardware появится — заменить `parallel_n` executors на **один quantum executor** с `n_branches` в суперпозиции. Никаких других изменений архитектуры.

**Почему не в v7:** нет quantum-inference hardware. v7 Multi-Agent Tournament (P-23) — classical approximation quantum superposition.

### 2.9. Направление I: Sub-millisecond LSP через WASM (если не сделано в EXTENSION-PROD)

**Источник:** ARCHITECT3 §8.2.9.

**Идея:** LSP-серверы живут в одном процессе с ядром (через WASM-компиляцию), а не через stdio. Latency LSP-запроса: <0.1 ms (vs stdio ~10 ms в v7 B-26).

**Латентность-предел:** -100-500 ms на ход с большим числом LSP-запросов.

**Реализация в v8+:** (если не сделано в EXTENSION-PROD E-12).
1. WASM-порты ключевых LSP-серверов (rust-analyzer ✅, typescript ✅, others ❌).
2. In-process WASM runtime (`wasmtime` Python package).

**Почему не в v7:** LSP-серверы — внешние бинарники. WASM-порты есть для некоторых, но не для всех. EXTENSION-PROD E-12 — опциональный first step.

### 2.10. Направление J: Multi-agent memory sharing + collaboration

**Источник:** v6 OQ-2, v7 §17 (NOT doing — FUTURE).

**Идея:** несколько self-agent-инстанцев работают над одним проектом, шарят MemoryStore + Heat Cache. Конфликты записи?

**Реализация в v9+:**
1. v7 EXTENSION-PROD E-13 (multi-instance DFC sync) — first step.
2. Multi-agent collaboration: agent A focuses on backend, agent B on frontend, shared memory.
3. Conflict resolution: timestamp-based, latest wins (v6 E-11).

**Почему не в v7:** v7 — single-tenant по умолчанию. EXTENSION-PROD добавляет multi-instance, но не multi-agent collaboration.

### 2.11. Направление K: Continuous prompt-learning с multi-agent judge

**Источник:** v6 F-09 (continuous prompt-learning).

**Идея:** агент сам улучшает свой system-prompt на основе накопленной памяти. LLM-judge оценивает каждый memory-write; достойные записи добавляются в `BEHAVIOR_RULES.md` (новый L0 файл).

**Реализация в v8+:** (extension of v6 F-09).
1. LLM-judge per memory-write (sampling 5%).
2. `BEHAVIOR_RULES.md` — новый L0 файл.
3. Periodic review (weekly): low-value rules удаляются.
4. A/B-testing обязателен (new rules → 10% traffic → measure).
5. Multi-agent judge: 3 LLM-judges vote на каждое rule (vs single judge в v6 F-09).

**Почему не в v7:** v6 F-09 уже объявлен, v7 не трогает (требует PROD stable). Multi-agent judge — extension.

### 2.12. Направление L: Real-time memory drift detection

**Источник:** v6 §17 (NOT doing — FUTURE).

**Идея:** real-time детекция drift в memory (например, пользователь сменил предпочтения, но старые preferences всё ещё в memory).

**Реализация в v9+:**
1. Embedding-drift detection (через OryaObservability `agent_obs.drift`).
2. KL-divergence monitoring.
3. Auto-supersede старых memory-items при drift.

**Почему не в v7:** дорого; nightly offline-eval достаточно.

### 2.13. Направление M: Cross-user memory sharing (privacy-preserving)

**Источник:** v6 §17 (NOT doing — FUTURE).

**Идея:** память шарится между пользователями (например, «best practices для FastAPI»), с privacy-preserving filtering.

**Реализация в v10+:** (требует federated learning infrastructure, см. Направление G).
1. Memory items помечаются `global=true` явно.
2. Federated sharing через OriaHS.
3. Differential privacy guarantees.

**Почему не в v7:** privacy risk; FUTURE.

### 2.14. Направление N: Voice input + multi-modal (images, PDF)

**Источник:** v6 §17 (NOT doing), v7 §17 (наследует).

**Идея:** voice input (через browser speech-to-text или Whisper API), image input (для design tasks), PDF input (для documentation tasks).

**Реализация в v8+:**
1. Voice: `orya voice` — browser speech-to-text → text prompt.
2. Images: vision-model (GPT-4V / Claude Vision) в TieredModelRouter.
3. PDF: text extraction + RAG.

**Почему не в v7:** v6 сознательно отклонил (80% усилий, <20% ценности для code-агента). v7 наследует.

### 2.15. Направление O: Skills-система поверх retrieval (extension of v6 B-15)

**Источник:** v6 B-15 (Skills), v0.3 OQ-v03-8.

**Идея:** v7 UKB — это retrieval; Skills — это **композиция** из retrieval + LLM-call + tool-call. Например, "skill: refactor_extract_function" = ukb.lookup(lsp.dependency_tree) + planner (LLM) + lsp.rename (symbolic shortcut).

**Реализация в v8+:**
1. Skills-mcp — отдельный MCP-сервер для skill-definitions.
2. Skill format: YAML/MD с steps (retrieval + LLM + tool).
3. `/skill` command — user может определить skill.

**Почему не в v7:** v7 — фокус на architecture primitives; skills — следующий layer composition.

---

## 3. Часть III: Гиперболизация скорости — теоретический предел

(Унаследовано из ARCHITECT3 §8.2 + расширено для v7 post-target)

**Ставим вопрос:** что если убрать **все** лимиты — latency LLM, latency retrieval, cost, разрешение контекста? Какой может быть агент? Этот раздел описывает **теоретический предел скорости** post-v7, какие изменения нужны, чтобы его достичь, и почему это пока нереализуемо.

### 3.1. Quantum-style superposition executor

(см. Направление H)

**Усиление v7 post-target:** когда quantum-inference hardware появится — заменить `parallel_n` executors (P-23 Tournament) на **один quantum executor** с `n_branches` в суперпозиции. Никаких других изменений архитектуры v7.

### 3.2. Neuromorphic inference (Loihi 2 / SpiNNaker 2)

**Идея:** run small-модели (planner, tester, predictive planner, judge) на neuromorphic chip — 1000× lower latency, 100× lower energy. Small-models (Qwen-3B) хорошо ложатся на spiking-neural-network emulation.

**Латентность-предел:**
- Planner: 300 ms → 0.3 ms.
- Tester: 300 ms → 0.3 ms.
- Predictive Planner: 200 ms → 0.2 ms.

**Почему нереализуемо сегодня:** нет production-готового neuromorphic inference для transformer-моделей (только для spiking). Research-active area, ожидается к 2028-2030.

**Усиление v7 post-target:** small-model-component (planner, tester, predictive, judge) — swap to neuromorphic backend через `llm-provider seam` (v7 TieredModelRouter A-18 + ConnectionPool A-20).

### 3.3. Continuous Planner daemon

(см. Направление C)

**Усиление v7 post-target:** Predictive Planner (P-22) → Continuous Planner (одна итерация эволюции). Структура v7 это уже поддерживает — просто повысить частоту работы planner'а с «раз в ход» (v7 PROD) до «раз в 100 ms» (v10+, требует neuromorphic inference для low idle cost).

### 3.4. Predictive User Model K=3

(см. Направление A)

**Усиление v7 post-target:** Predictive Planner (P-22, N=1) → Predictive User Model (N=3). Расширение `app/core/workflow/predictive_planner.py` до K=3.

### 3.5. Pre-trained Task Embeddings (lookup instead of plan)

(см. Направление B)

**Усиление v7 post-target:** добавить TaskEmbeddingIndex как новую capability в UKB (`ukb.lookup(query, capability="task.lookup")`).

### 3.6. Incremental LLM

(см. Направление E)

**Усиление v7 post-target:** Symbolic Shortcut (P-21) уже частично это делает для детерминированных задач. Для LLM-tasks — использовать structured-output + JSON-schema constraints.

### 3.7. Hierarchical Predictive Prefetch

(см. Направление D)

**Усиление v7 post-target:** добавить `lsp.dependency_tree(location, depth=2)` tool в lsp-mcp (extension of B-26).

### 3.8. Adaptive Compute

(см. Направление F)

**Усиление v7 post-target:** Concurrent Tester (P-24) уже частично это делает. Расширить до continuous monitor (тик раз в 100 ms).

### 3.9. Sub-millisecond LSP через WASM

(см. Направление I)

**Усиление v7 post-target:** в v8 — WASM-порты ключевых LSP-серверов в ядро (или EXTENSION-PROD E-12).

### 3.10. Federated Predictive Planner

(см. Направление G)

**Усиление v7 post-target:** в v10+ — federated learning loop поверх MemoryStore (v6 B-21 + v6 P-18).

---

## 4. Часть IV: Дорожная карта гиперболизации v8-v10

```mermaid
flowchart LR
    subgraph V7["v7 (этот документ — целевая архитектура)"]
        A1[DFC + Tri-Model + LSP + UKB]
        A2[Batch + Symbolic + Predictive N=1 + Tournament]
        A3[Concurrent Tester + RerankPolicy + Best-of-N]
    end
    subgraph V8["v8 (3-6 мес после v7 PROD)"]
        B1[Направление A: Predictive User Model K=3]
        B2[Направление D: Hierarchical Predictive Prefetch]
        B3[Направление I: WASM-LSP (если не в EXT-PROD)]
        B4[Направление K: Continuous prompt-learning с multi-agent judge]
        B5[Направление O: Skills-система]
    end
    subgraph V9["v9 (6-12 мес)"]
        C1[Направление B: Task Embedding Index]
        C2[Направление E: Incremental LLM (constrained generation)]
        C3[Направление F: Adaptive Compute (continuous triage)]
        C4[Направление J: Multi-agent memory sharing]
        C5[Направление L: Real-time memory drift detection]
        C6[Направление N: Voice input + multi-modal]
    end
    subgraph V10["v10 (12-24 мес, теор. предел)"]
        D1[Направление C: Continuous Planner daemon (требует neuromorphic)]
        D2[Направление G: Federated Predictive Planner]
        D3[Направление M: Cross-user memory sharing]
    end
    subgraph POSTCLASSICAL["post-classical (far-future)"]
        E1[Направление H: Quantum-style superposition executor]
        E2[Neuromorphic inference для всех small-model-components]
    end
    V7 --> V8 --> V9 --> V10 --> POSTCLASSICAL
    style V7 fill:#e6f0e0
    style V8 fill:#fdf3e0
    style V9 fill:#f6e0e0
    style V10 fill:#f0e6f6
    style POSTCLASSICAL fill:#e0ecf6
```

### 4.1. v8 (3-6 месяцев после v7 PROD)

- **Predictive User Model K=3** (Направление A) — расширение P-22.
- **Hierarchical Predictive Prefetch** (Направление D) — extension B-26.
- **WASM-LSP** (Направление I) — если не в EXTENSION-PROD E-12.
- **Continuous prompt-learning с multi-agent judge** (Направление K) — extension v6 F-09.
- **Skills-система** (Направление O) — composition layer над v7 UKB.

### 4.2. v9 (6-12 месяцев после v7 PROD)

- **Task Embedding Index** (Направление B) — needs 10K+ tasks dataset.
- **Incremental LLM** (Направление E) — requires constrained generation support.
- **Adaptive Compute** (Направление F) — requires confidence-aware streaming inference.
- **Multi-agent memory sharing** (Направление J) — extension EXTENSION-PROD.
- **Real-time memory drift detection** (Направление L) — needs OryaObservability drift.
- **Voice input + multi-modal** (Направление N).

### 4.3. v10 (12-24 месяца, теоретический предел)

- **Continuous Planner daemon** (Направление C) — requires neuromorphic inference.
- **Federated Predictive Planner** (Направление G) — requires federated learning infrastructure.
- **Cross-user memory sharing** (Направление M) — privacy-preserving.

### 4.4. Post-classical (far-future)

- **Quantum-style superposition executor** (Направление H).
- **Neuromorphic inference для всех small-model-components** (planner, tester, predictive, judge).

---

## 5. Часть V: Открытые вопросы (TBD) после v7

(Унаследовано из ARCHITECT3 §12 + расширено для v7)

1. **OQ-v7-1.** Subagents + Task-делегирование (унаследовано из v0.3 OQ-v03-1) — каждый subagent имеет свой UKB-context? Или общий? Нужен отдельный ADR-v08-001.
2. **OQ-v7-2.** Autonomous mode (cron + goals + judge) (унаследовано из v0.3 OQ-v03-2) — как Predictive Planner взаимодействует с cron-задачами?
3. **OQ-v7-3.** Privacy: federated learning для Predictive Planner (Направление G) — как собирать данные пользовательских сессий без передачи в облако?
4. **OQ-v7-4.** Cost optimization: когда переключаться с LLM-based Predictive Planner на локальную модель (Ollama)? Threshold по usage? (v7 уже использует Ollama Qwen-3B по default.)
5. **OQ-v7-5.** Multi-agent scenarios (унаследовано из v0.3 OQ-v03-5) — если несколько self-agent-инстанцев работают над одним проектом, как они шарят MemoryStore + Heat Cache? (Направление J.)
6. **OQ-v7-6.** Compaction + Context Epoch (унаследовано из v0.3 OQ-v03-6) — summarization в WARM-tier vs COLD-tier, как именно? v7 DFC BackgroundCompactor — first iteration.
7. **OQ-v7-7.** IDE-плагины (VS Code, JetBrains) (унаследовано из v0.3 OQ-v03-7) — как использовать UKB из IDE? LSP уже есть, но нужен lsp-mcp как shared server. (Это v7 слабее opencode/kilocode.)
8. **OQ-v7-8.** Skills-система поверх retrieval (Направление O) — как CapabilityRegistry отличает «skill» от «tool»? Нужен ли отдельный skills-mcp?
9. **OQ-v7-9.** Sandbox / изоляция bash (унаследовано из v0.3 OQ-v03-9) — какой sandbox? gVisor, firecracker, или wasmtime? (v7 слабее kilocode.)
10. **OQ-v7-10.** Streaming UI для TUI (унаследовано из v0.3 OQ-v03-10) — v7 не имеет TUI; добавить в v8?
11. **OQ-v7-11.** Multi-provider tournament — TournamentExecutor (P-23) может использовать модели из разных providers; как обрабатывать разный token-counting?
12. **OQ-v7-12.** Predictive Planner + Multi-agent — если несколько агентов в Tournament, каждый имеет свой Predictive Planner? Или общий?
13. **OQ-v7-13.** Batch pipeline + Continuous prompt-learning (v6 F-09 + Направление K) — batch-runner собирает task-embeddings; когда activates Task Embedding Index (Направление B)?
14. **OQ-v7-14.** LSP rename safety (v7 B-26 + P-21) — LSP rename может affect >100 файлов; auto-confirm в PROD?
15. **OQ-v7-15.** Quantum-style superposition executor (Направление H) — когда quantum-inference hardware появится, как мигрировать с classical Tournament (P-23)?

---

## 6. Часть VI: Итог

После полной реализации `ROADMAP7.md` (до PROD) OryaAgent v7 — production-ready кодинг-агент с уникальным архитектурным профилем:

### Что v7 даёт из коробки (после ROADMAP7 PROD)

- **Latency p50 ≤ 800 ms, p95 ≤ 3 s** — быстрее опencode и kilocode в 5-10× на типичных code-задачах.
- **Cost ≤ $0.20/session** — дешевле опencode/kilocode в 2-5×.
- **Self-verifying loop** — Tri-Model Pipeline (plan→execute→test) с Concurrent Tester early-abort. 100% ходов через tester; 0% у опencode/kilocode.
- **LSP-native code facts** — sub-ms latency, 6 языков. У опencode — experimental LSP; у kilocode — нет LSP (только kilo-indexing semantic).
- **Batch pipeline + built-in benchmark** — 100-400 prompts/hour, CI-benchmark, self-improvement feedback-loop. У опencode/kilocode — нет.
- **Long-term memory 3-layer + /learn** — L0 MD + L1 SQLite FTS5 + L2 Qdrant via OriaHS, atomic-append, compaction flow. У опencode — AGENTS.md (static); у kilocode — kilo-memory (no /learn).
- **DFC (Dynamic Fast Context)** — 5 слоёв (HEAT/HOT/WARM/COLD/ICE), в окне только HOT (≤16K tokens). У опencode Context Epoch (но не DFC); у kilocode — нет DFC.
- **UKB (Unified Knowledge Bus)** — единый MCP-контракт над LSP/RAG/Memory/code/KB. У опencode/kilocode — фрагментированные retrieval.
- **Predictive Planner + Heat Cache** — forecast next prompt, prefetch заранее. У опencode/kilocode — нет.
- **Symbolic Shortcut** — LLM bypass для rename/format. ~15% ходов без LLM-executor. У опencode/kilocode — нет.
- **Tournament + judge-mcp** — N parallel executors + judge. У опencode — нет; у kilocode — sequential subagents.
- **OryaObservability SDK + sampler-proxy** — PII-masking, cost-tracking, guardrail, dynamic sample-rate. У опencode — basic LangSmith/LangFuse; у kilocode — kilo-telemetry (но без sampler-proxy).

### Где v7 слабее (после ROADMAP7 PROD)

- **Ecosystem/community** — opencode 214K+ stars, 75+ providers, огромная база MCP-servers.
- **IDE-integration** — opencode TUI/desktop/VS Code SDK/ACP; kilocode VS Code/JetBrains/Cloud Agent. v7 — Chainlit/Next.js only.
- **Enterprise** — kilocode SSO/audit/policies/sandbox. v7 — single-tenant + EXTENSION-PROD multi-instance.
- **Provider choice** — opencode 75+; kilocode 500+ via gateway. v7 — 4 major.
- **Distribution** — opencode/kilocode — 30s install; v7 — 5-10 min docker-setup.
- **Sandbox** — kilocode kilo-sandbox production-ready. v7 — only LSP-sandbox.

### Стратегический вывод

v7 не пытается догнать опencode/kilocode в **универсальности**. v7 атакует **архитектурную нишу** (speed + self-verification + LSP-native + batch), где опencode/kilocode архитектурно слабы. Это ниша **production-grade Python-code-agent** для power-users, которым нужна:
- Максимальная скорость (sub-second latency).
- Self-verifying loop (без «ошибся? переделай»).
- LSP-native (без read+grep overhead).
- Batch pipeline (для CI + self-improvement).
- Long-term memory с `/learn`.

После достижения целевой архитектуры v7, развитие идёт по 15 направлениям (Часть II), с гиперболизацией скорости как главным long-term вектором (Часть III), и теоретическим пределом в виде quantum-style superposition executor (Часть IV).

**Принцип 20/80 на FUTURE7:** из 15 направлений выбраны 5 с highest leverage:
1. **Predictive User Model K=3** (Направление A) — extension of v7 P-22, требует только датасет.
2. **Hierarchical Predictive Prefetch** (Направление D) — extension of v7 B-26, требует только LSP-extension.
3. **Task Embedding Index** (Направление B) — extension of v7 P-20, требует только датасет + Qdrant collection.
4. **Continuous prompt-learning с multi-agent judge** (Направление K) — extension of v6 F-09, требует только multi-agent judge.
5. **Skills-система** (Направление O) — composition layer над v7 UKB, требует только skills-mcp.

Эти 5 направлений — кандидаты на v8 (3-6 месяцев после v7 PROD). Остальные 10 — на v9-v10+.

**Финальный статус:** OryaAgent v7 + FUTURE7 — complete roadmap от MVP до far-future quantum-inference. Реализация v7 (5.5 месяцев на PROD) + v8 (3-6 мес) + v9 (6-12 мес) + v10 (12-24 мес) = **2-3 года full development**, после чего v7-v10+ достигает теоретического предела скорости для классических машин, и переходит в post-classical (quantum + neuromorphic).

---

*Конец документа FUTURE7.md*