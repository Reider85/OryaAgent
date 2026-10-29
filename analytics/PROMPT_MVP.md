# ПРОМПТ ФАЗЫ MVP — OryaAgent v7

> **Версия промпта:** 7.0
> **Дата:** 20 октября 2026
> **Источники:** `ARCHITECT7.md` v7.0 (§0, §18), `ROADMAP7.md` v7.0 (§3), `BACKLOG7.md` v7.0 (§2), `BACKLOG6.md` v6.0 (§2 — M-00..M-27), `ARCHITECT6.md` v6.0 (§3.1, §4, §6.1.1, §6.1.4)
> **Стек:** Python 3.11+, LangChain 0.3+, LangGraph 0.2+, FastAPI, PostgreSQL 16, Redis 7, Chainlit, **мультипровайдерный LLM-seam** (Anthropic, OpenAI, Google Gemini, 6+ китайских провайдеров, OpenRouter, Ollama, LM Studio, vLLM, llama.cpp)
> **Длительность:** 3.5 недели (один разработчик)
> **Объём кода:** ~2700 LOC
> **Статус в v7:** MVP полностью унаследован от v6 без изменений — v7 не добавляет тикетов в MVP, чтобы не нарушать «время до первого работающего агента»

---

## 0. Контекст и роль

Ты — senior Python-разработчик, реализующий **фазу MVP** системы OryaAgent v7. Это базовый, end-to-end работающий кодинг-агент с UI и долговременной памятью.

**Принцип MVP v7:** не нарушать «время до первого работающего агента». MVP v6 (3.5 недели) достаточен для базового code-агента с L0 memory. Добавление v7-фич (DFC, tri-model, LSP-native, tiered-router и т.д.) в MVP замедлит time-to-market без пропорциональной ценности. Все v7-улучшения начинаются с фазы ALPHA.

**Архитектурная инвариантность:** каждая следующая фаза (ALPHA → BETA → PROD) опирается на компоненты MVP, но не модифицирует их контракт. Поэтому MVP должен быть спроектирован как надёжная база: чистые швы (LLM-seam, tool-registry, memory-seam), которые будут расширяться, но не переписываться.

---

## 1. Цели фазы

Доставить end-to-end работающего кодинг-агента с:

1. **Нормальным UI с первого дня** (Chainlit поверх FastAPI) — сессии, настройки, interrupt_before-диалог для permission-prompts.
2. **Базовой долговременной памятью в MD-файлах** (L0: 6 файлов — `PROJECT.md`, `LEARNED.md`, `PREFERENCES.md`, `FACTS.md`, `DECISIONS.md`, `MEMORY_INDEX.md`) с atomic-append.
3. **Командой `/learn`** — пользователь явно добавляет знание в LEARNED.md.
4. **Инструментами кодинга:** `read`, `write`, `edit`, `bash`, `grep`, `glob` — 6 базовых tools.
5. **Permission-policy** — `interrupt_before` для dangerous tools (write/edit/bash) с подтверждением через UI.
6. **Session-log** — каждый ход персистится в PostgreSQL + дублируется в JSONL projection.
7. **CacheWrapper (Redis)** — для `read`/`grep` результатов по hash + mtime-invalidation.
8. **Prompt-injection defense** — untrusted-content markers + sanitization.
9. **Smoke-тесты** — 5 эталонных задач проходят end-to-end.

---

## 2. Технологический стек

| Компонент | Технология | Версия | Назначение |
|---|---|---|---|
| Язык | Python | 3.11+ | основной язык |
| LLM-оркестрация | LangChain | 0.3+ | init_chat_model, BaseMessage, @tool |
| Workflow | LangGraph | 0.2+ | StateGraph, PostgresSaver |
| Web-фреймворк | FastAPI | latest | REST API (sessions, learn, memory) |
| БД (сессии) | PostgreSQL | 16 | orya_sessions, PostgresSaver |
| Кэш/память | Redis | 7 | CacheWrapper, ephemeral state |
| UI | Chainlit | latest | chat-интерфейс, slash-commands, sidebar |
| Настройки | pydantic-settings | latest | конфиг из env + ~/.orya/config.yaml |
| LLM-провайдеры | **Западные:** Anthropic Claude, OpenAI GPT, Google Gemini, xAI Grok · **Китайские:** DeepSeek, Qwen (Alibaba), GLM/Zhipu, Xiaomi MiMo, Moonshot/Kimi, Baichuan, Minimax, StepFun, 01.AI (Yi), iFlyTek Spark, SenseTime, ByteDance Doubao · **Агрегаторы:** OpenRouter, Together AI, Groq, Fireworks AI, SiliconFlow, Higress · **Локальные:** Ollama, LM Studio, vLLM, llama.cpp, TGI, LocalAI | — | init_chat_model + OpenAI-compatible adapters |
| Тесты | pytest + pytest-asyncio | latest | smoke-тесты, unit-тесты |

**Принцип 20/80 (Парето) на уровне библиотек:** LangGraph + LangChain + Chainlit + PostgresSaver + Redis покрывают 80% потребностей. Не вводи новых библиотек без явной необходимости.

---

## 2.1. Реестр поддерживаемых LLM-провайдеров (полный)

MVP проектируется как **провайдерно-агностичная платформа**: ни одна бизнес-логика не должна зависеть от конкретного вендора. Все провайдеры подключаются через единый шов `get_llm(provider, model)` (см. M-01) и должны поддерживать: streaming, tool-calling (function-calling), system-prompt, температуру, max_tokens. Ниже — полный реестр провайдеров, обязательных к поддержке в MVP.

### 2.1.1. Западные провайдеры (Tier-1, production-grade)

| Provider | Класс LangChain | Base URL | Модели (примеры) | Tool-calling | Streaming | Notes |
|---|---|---|---|---|---|---|
| **Anthropic** | `ChatAnthropic` | `api.anthropic.com` | `claude-sonnet-3.5`, `claude-opus-4`, `claude-haiku-3.5` | ✅ native | ✅ | default provider в MVP |
| **OpenAI** | `ChatOpenAI` | `api.openai.com/v1` | `gpt-4o`, `gpt-4-turbo`, `gpt-4o-mini`, `o1`, `o3-mini` | ✅ native | ✅ | reference-implementation |
| **Google Gemini** | `ChatVertexAI` / `ChatGoogleGenerativeAI` | `generativelanguage.googleapis.com` | `gemini-2.0-flash`, `gemini-1.5-pro`, `gemini-1.5-flash` | ✅ native | ✅ | context-caching в ALPHA |
| **xAI Grok** | `ChatOpenAI` (OpenAI-compat) | `api.x.ai/v1` | `grok-2`, `grok-beta`, `grok-vision` | ✅ | ✅ | reasoning-модели |

### 2.1.2. Китайские провайдеры (обязательны в MVP — целевая аудитория OryaAgent)

> **Важно:** все китайские провайдеры (кроме Qwen и GLM через native SDK) реализуются через **OpenAI-compatible API** (LangChain `ChatOpenAI` с кастомным `base_url`). Это унифицирует integration-слой и позволяет переиспользовать code-path: tool-calling, streaming, system-prompt работают идентично.

| Provider | Base URL (OpenAI-compat) | API Key env-var | Модели (примеры) | Tool-calling | Streaming | Notes |
|---|---|---|---|---|---|---|
| **DeepSeek** | `https://api.deepseek.com/v1` | `DEEPSEEK_API_KEY` | `deepseek-chat` (V3), `deepseek-reasoner` (R1), `deepseek-coder` | ✅ | ✅ | best cost/quality для code; R1 — reasoning (Chain-of-Thought) |
| **Qwen (Alibaba)** | `https://dashscope.aliyuncs.com/compatible-mode/v1` | `DASHSCOPE_API_KEY` (или `QWEN_API_KEY`) | `qwen-max`, `qwen-plus`, `qwen-turbo`, `qwen2.5-72b-instruct`, `qwen3-235b-a22b`, `qwen3-coder-plus` | ✅ | ✅ | Qwen3-Coder — сильнейший code-модель 2025; DashScope OpenAI-compat |
| **GLM / Zhipu AI** | `https://open.bigmodel.cn/api/paas/v4` | `ZHIPUAI_API_KEY` (или `GLM_API_KEY`) | `glm-4-plus`, `glm-4.5`, `glm-4-air`, `glm-4-flash`, `glm-4-airx`, `glm-zero-preview` | ✅ | ✅ | GLM-4.5 — reasoning model; free-tier через `glm-4-flash` |
| **Xiaomi MiMo** | `https://api.mimo.xiaomi.com/v1` (OpenAI-compat) | `MIMO_API_KEY` | `mimo-7b-rl`, `mimo-7b-base`, `mimo-vl-7b-instruct` | ⚠️ partial | ✅ | Xiaomi MiMo-7B-RL — reasoning для code/agent tasks |
| **Moonshot / Kimi** | `https://api.moonshot.cn/v1` | `MOONSHOT_API_KEY` | `moonshot-v1-8k`, `moonshot-v1-32k`, `moonshot-v1-128k`, `kimi-k2`, `kimi-k1.5` | ✅ | ✅ | Kimi K2 — long-context (200K+), agent-optimized |
| **Baichuan AI** | `https://api.baichuan-ai.com/v1` | `BAICHUAN_API_KEY` | `baichuan4-turbo`, `baichuan4-air`, `baichuan3-turbo` | ✅ | ✅ | Chinese-specific optimizations |
| **Minimax** | `https://api.minimax.chat/v1` | `MINIMAX_API_KEY` | `abab6.5-chat`, `abab6.5s-chat`, `MiniMax-Text-01` | ✅ | ✅ | MiniMax-Text-01 — 1M context window |
| **StepFun** | `https://api.stepfun.com/v1` | `STEPFUN_API_KEY` | `step-1-8k`, `step-1-32k`, `step-1-128k`, `step-1-flash`, `step-2-16k` | ✅ | ✅ | step-2 — reasoning model |
| **01.AI (Yi)** | `https://api.lingyiwanwu.com/v1` | `YI_API_KEY` (или `LINGYI_API_KEY`) | `yi-large`, `yi-medium`, `yi-large-turbo`, `yi-lightning` | ✅ | ✅ | yi-large — strong code/reasoning |
| **iFlyTek Spark** | `https://spark-api-open.xf-yun.com/v1` | `IFLYTEK_API_KEY` (+ `IFLYTEK_API_SECRET`) | `generalv3.5`, `general`, `spark-v4` | ✅ | ✅ | WS / HTTP OpenAI-compat; требует `APISecret` |
| **SenseTime SenseNova** | `https://api.sensenova.cn/compatible-mode/v1` | `SENSENOVA_API_KEY` | `SenseChat-5`, `SenseChat-Turbo` | ✅ | ✅ | OpenAI-compat |
| **ByteDance Doubao** | `https://ark.cn-beijing.volces.com/api/v3` | `ARK_API_KEY` (Volcengine) | `doubao-pro-32k`, `doubao-pro-128k`, `doubao-lite-32k`, `doubao-1.5-pro` | ✅ | ✅ | Volcengine Ark; endpoint-by-model-id |
| **Tencent Hunyuan** | `https://api.hunyuan.cloud.tencent.com/v1` | `HUNYUAN_API_KEY` | `hunyuan-pro`, `hunyuan-standard`, `hunyuan-lite`, `hunyuan-code` | ✅ | ✅ | hunyuan-code — специализированный для code-gen |
| **Baidu ERNIE (Wenxin)** | `https://qianfan.baidubce.com/v2` | `ERNIE_API_KEY` (+ `ERNIE_SECRET_KEY`) | `ernie-4.0-turbo-8k`, `ernie-4.0-8k-latest`, `ernie-3.5-8k`, `ernie-speed-128k`, `ernie-x1` | ✅ | ✅ | Qianfan platform OpenAI-compat; ernie-x1 — reasoning |
| **SiliconFlow** | `https://api.siliconflow.cn/v1` | `SILICONFLOW_API_KEY` | агрегатор: `deepseek-ai/DeepSeek-V3`, `Qwen/Qwen2.5-72B-Instruct`, `meta-llama/Llama-3.3-70B-Instruct` | ✅ | ✅ | китайский аналог OpenRouter; бесплатный tier |
| **Higress / Aliyun Bailian** | `https://dashscope.aliyuncs.com/compatible-mode/v1` (через DashScope) | `DASHSCOPE_API_KEY` | то же что Qwen + hosted open-source модели | ✅ | ✅ | gateway для self-hosted китайских моделей |

### 2.1.3. Агрегаторы (OpenAI-compatible, один API key — доступ ко всем моделям)

| Provider | Base URL | API Key env-var | Покрывает | Notes |
|---|---|---|---|---|
| **OpenRouter** | `https://openrouter.ai/api/v1` | `OPENROUTER_API_KEY` | Anthropic, OpenAI, Google, Meta Llama, Mistral, DeepSeek, Qwen, GLM, Yi, + 300 других | единый billing, routing по model-id; `HTTP_REFERRER` для ranking |
| **Together AI** | `https://api.together.xyz/v1` | `TOGETHER_API_KEY` | Llama, Qwen, DeepSeek, Mixtral, DBRX, + 200 OSS моделей | fast inference (240+ TPS) |
| **Groq** | `https://api.groq.com/openai/v1` | `GROQ_API_KEY` | Llama-3.3-70B, Llama-3.1-8B, Mixtral, Gemma, DeepSeek-R1 (distill) | LPU-ускорение, 500+ TPS |
| **Fireworks AI** | `https://api.fireworks.ai/inference/v1` | `FIREWORKS_API_KEY` | Llama, Qwen, DeepSeek, Mistral, + 100 OSS | serverless + fine-tuning |
| **SiliconFlow** | (см. §2.1.2) | `SILICONFLOW_API_KEY` | китайский агрегатор (DeepSeek, Qwen, GLM, Llama, и др.) | бесплатный tier, низкие цены для китайских моделей |
| **NVIDIA NIM** | `https://integrate.api.nvidia.com/v1` | `NVIDIA_API_KEY` | Llama, Mistral, Qwen, DeepSeek, Gemma | 1000 бесплатных запросов при регистрации |
| **Cerebras** | `https://api.cerebras.ai/v1` | `CEREBRAS_API_KEY` | Llama-3.1-8B, Llama-3.3-70B | CS-3 wafer-scale; 1500+ TPS |
| **SambaNova** | `https://api.sambanova.ai/v1` | `SAMBANOVA_API_KEY` | Llama, DeepSeek, Qwen | RDU-ускорение |

### 2.1.4. Локальные провайдеры (для air-gapped / privacy / dev-тестирования)

| Provider | Base URL (OpenAI-compat) | Запуск | Модели (примеры) | Notes |
|---|---|---|---|---|
| **Ollama** | `http://localhost:11434/v1` | `ollama serve` | `qwen2.5:7b`, `qwen2.5-coder:14b`, `deepseek-r1:14b`, `llama3.3:70b`, `glm4:9b`, `mistral:7b` | default для dev; auto-pull моделей |
| **LM Studio** | `http://localhost:1234/v1` | LM Studio app → Local Server | любая GGUF-модель (Qwen, DeepSeek, Llama, GLM, Phi) | GUI для model-management; OpenAI-compat |
| **vLLM** | `http://localhost:8000/v1` | `vllm serve --model Qwen/Qwen2.5-7B-Instruct --api-server` | любая HF-модель | production-grade serving; поддерживает OpenAI + Anthropic-compat |
| **llama.cpp server** | `http://localhost:8080/v1` | `llama-server -m model.gguf --port 8080` | любая GGUF | минимальный footprint; edge-deploy |
| **TGI (HuggingFace)** | `http://localhost:8090/v1` | `text-generation-launcher --model-id ...` | любая HF-модель | OpenAI-compat с v1.0+ |
| **LocalAI** | `http://localhost:8081/v1` | docker-compose | любая (GGUF, GPTQ, GGML) | drop-in replacement для OpenAI; multi-backend |
| **Jan** | `http://localhost:1337/v1` | Jan app | любая GGUF | GUI-first альтернатива LM Studio |
| **Ollama-compatible: GPT4All** | `http://localhost:4891/v1` | GPT4All app | GGUF models | desktop-class local inference |

### 2.1.5. Совместимость с open-source code-агентами (для re-use провайдеров)

OryaAgent MVP должен уметь читать конфиги провайдеров, которые используют популярные open-source агенты — это упрощает миграцию пользователей и стандартизирует env-vars:

| Агент | Формат конфига | Что re-use'ить |
|---|---|---|
| **OpenCode** (sst/opencode) | `~/.config/opencode/auth.json` или `opencode.json` с `providers[].api_key` | env-vars `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `OPENROUTER_API_KEY`; поддержка произвольных OpenAI-compat endpoints через `baseUrl` |
| **KiloCode** (kilocode/kilo) | VS Code settings / MCP servers | env-vars `OPENROUTER_API_KEY`, `DEEPSEEK_API_KEY`, `QWEN_API_KEY`; MCP-server protocol |
| **Cline / RooCode** | VS Code settings | env-vars `DEEPSEEK_API_KEY`, `QWEN_API_KEY`, `OPENROUTER_API_KEY`; `apiProvider` field |
| **Aider** | `~/.aider.conf.yml` | env-vars; `-model deepseek/deepseek-chat` через LiteLLM convention |
| **Continue.dev** | `~/.continue/config.json` | `models[].apiBase`, `models[].apiKey` fields |

**MVP реализует importer** для `opencode.json` и `~/.continue/config.json` (см. M-02) — пользователь может мигрировать с этих агентов одним `orya import --from opencode`.

### 2.1.6. Принципы проектирования LLM-seam для мультипровайдерности

1. **OpenAI-compat-first:** ~90% провайдеров (включая все китайские, кроме Qwen-native и GLM-native) реализуются через один и тот же code-path: `ChatOpenAI(base_url=..., api_key=..., model=...)`. Это снижает support-burden и унифицирует observability.
2. **Native SDK только при необходимости:** Qwen (`dashscope` SDK) и GLM (`zhipuai` SDK) можно подключить через native SDK для расширенных фич (multimodal, embeddings, async-batch), но базовый chat+tools работает через OpenAI-compat endpoint — поэтому в MVP только OpenAI-compat.
3. **Capability-detection:** при инициализации провайдера проверяем 3 capability: `supports_tool_calling`, `supports_streaming`, `supports_system_prompt`. Если хотя бы одна отсутствует — fail-fast с понятным сообщением. Реестр capabilities хранится в `app/core/llm/capabilities.yaml`.
4. **Provider-agnostic tool-format:** все провайдеры приводятся к LangChain `bind_tools()` interface (LangChain сам маппит OpenAI-function-calling ↔ Anthropic-tools ↔ Gemini-function-declarations). В MVP не должно быть `if provider == "anthropic"` в бизнес-логике.
5. **Model-alias registry:** `app/core/llm/models.yaml` — declarative mapping `alias → (provider, model_id, capabilities, context_window, pricing)`. Например `qwen-coder` → `(qwen, qwen3-coder-plus, tools+streaming, 256K, $0.002/1K)`. В ALPHA этот registry станет основой для `TieredModelRouter` (small/large/tournament).
6. **Pricing registry:** `app/core/llm/pricing.yaml` — `input_per_1k`, `output_per_1k` per model — нужно для cost-tracking (ALPHA A-14).
7. **No vendor lock-in:** любая бизнес-логика MVP (`graph.py`, `prompt.py`, `tools.py`) не должна импортировать `langchain_anthropic` или `langchain_openai` напрямую — только через `get_llm()`.

---

## 3. Полный список тикетов фазы (M-00 … M-27)

Все 28 тикетов унаследованы от v6 (см. `BACKLOG6.md` §2). v7 не добавляет и не меняет ни одного тикета в MVP.

### 3.1. Bootstrap и конфигурация (M-00 … M-03)

**M-00 — Bootstrap проекта**
- Структура: `app/`, `app/core/`, `app/tools/`, `app/api/`, `app/ui/`, `tests/`, `pyproject.toml`, `README.md`, `.env.example`.
- `pyproject.toml` с зависимостями: langchain, langgraph, fastapi, uvicorn, chainlit, asyncpg, redis, pydantic-settings, pytest, pytest-asyncio.
- Makefile: `make dev`, `make test`, `make lint`.

**M-01 — LLM-provider-seam (LangChain init_chat_model + OpenAI-compatible adapters)**
- `app/core/llm.py::get_llm(provider: str, model: str, **kwargs) -> BaseChatModel`.
- **Архитектура шва:**
  - Если `provider` ∈ {`anthropic`, `openai`, `google`, `vertexai`} → используем `langchain.chat_models.init_chat_model` с native LangChain-классом (`ChatAnthropic`, `ChatOpenAI`, `ChatVertexAI`).
  - Если `provider` — любой из списка §2.1.2–2.1.4 (китайские, агрегаторы, локальные) → используем `ChatOpenAI(base_url=settings.base_url, api_key=settings.api_key, model=model)` (OpenAI-compatible path).
  - Один экзотический fallback: `provider="openrouter"` → `ChatOpenAI(base_url="https://openrouter.ai/api/v1", api_key=..., model="anthropic/claude-3.5-sonnet", extra_headers={"HTTP-Referer": "...", "X-Title": "OryaAgent"})`.
- **Реестр провайдеров** (declarative): `app/core/llm/providers.yaml` — каждая запись: `{name, base_url, env_var, langchain_class, capabilities, default_model}`. См. полный список в §2.1.
- **Реестр моделей** (declarative): `app/core/llm/models.yaml` — `{alias, provider, model_id, context_window, supports_tools, supports_streaming, pricing}`.
- **Поддерживаемые провайдеры в MVP (20+):**
  - **Западные (4):** `anthropic`, `openai`, `google`, `xai`.
  - **Китайские (14):** `deepseek`, `qwen` (Alibaba DashScope), `glm` (Zhipu), `mimo` (Xiaomi), `moonshot` (Kimi), `baichuan`, `minimax`, `stepfun`, `yi` (01.AI), `iflytek` (Spark), `sensenova`, `doubao` (Volcengine), `hunyuan` (Tencent), `ernie` (Baidu Qianfan).
  - **Агрегаторы (7):** `openrouter`, `together`, `groq`, `fireworks`, `siliconflow`, `nvidia`, `cerebras`, `sambanova`.
  - **Локальные (8):** `ollama`, `lmstudio`, `vllm`, `llamacpp`, `tgi`, `localai`, `jan`, `gpt4all`.
- **Capability-detection при init:** `get_llm()` проверяет `supports_tools` и `supports_streaming` для выбранной модели (через `models.yaml`). Если не поддерживает — `ValueError` с понятным сообщением (например: "DeepSeek R1 (deepseek-reasoner) не поддерживает tool-calling — выберите deepseek-chat или подключите провайдер через адаптер").
- **Config sources (приоритет):** env (`ORYA_LLM_PROVIDER`, `ORYA_LLM_MODEL`, `ORYA_LLM_API_KEY`, `ORYA_LLM_BASE_URL`) → `~/.orya/config.yaml` → `models.yaml` alias → fail-fast.
- **Импорт из других агентов:** `app/core/llm/importers.py` — `import_opencode()`, `import_continue()`, `import_aider()` — читают `~/.config/opencode/auth.json`, `~/.continue/config.json`, `~/.aider.conf.yml` и заполняют `~/.orya/config.yaml`.
- **Default в MVP:** `provider=anthropic`, `model=claude-sonnet-3.5` (как в v6 baseline). Все остальные провайдеры — опциональны, но code-path должен быть готов к ним с первого дня.
- Это **главный архитектурный шов** — он будет расширен в ALPHA (TieredModelRouter с tier=small/large/tournament, PromptCacheLayout, ConnectionPool), но его интерфейс `get_llm(provider, model, **kwargs) -> BaseChatModel` остаётся неизменным. TieredModelRouter в ALPHA будет выбирать между, например, `deepseek-chat` (tier=small), `claude-sonnet-3.5` (tier=large), и tournament из 3 моделей (deepseek-r1 + qwen3-coder + glm-4.5).

**M-02 — pydantic-settings конфиг + multi-provider registry**
- `app/core/config.py::Settings(BaseSettings)` — все настройки приложения.
- Источники (приоритет): `.env` → env vars → `~/.orya/config.yaml`.
- Поля (поля провайдеров — см. ниже):
  - `llm_provider: str = "anthropic"` (default).
  - `llm_model: str = "claude-sonnet-3.5"`.
  - `llm_api_key: SecretStr | None` (если None — берётся из провайдер-specific env-var).
  - `llm_base_url: str | None` (для OpenAI-compat override; если None — из `providers.yaml`).
  - `database_url`, `redis_url`, `memory_dir` (default `~/.orya/memory/`), `permission_policy` (`strict`/`permissive`), `log_level`.
- **Multi-provider config block** в `~/.orya/config.yaml`:
  ```yaml
  llm:
    default_provider: anthropic
    default_model: claude-sonnet-3.5
    providers:
      anthropic:
        api_key: ${ANTHROPIC_API_KEY}
        default_model: claude-sonnet-3.5
      deepseek:
        api_key: ${DEEPSEEK_API_KEY}
        base_url: https://api.deepseek.com/v1
        default_model: deepseek-chat
      qwen:
        api_key: ${DASHSCOPE_API_KEY}
        base_url: https://dashscope.aliyuncs.com/compatible-mode/v1
        default_model: qwen3-coder-plus
      glm:
        api_key: ${ZHIPUAI_API_KEY}
        base_url: https://open.bigmodel.cn/api/paas/v4
        default_model: glm-4.5
      mimo:                          # Xiaomi MiMo
        api_key: ${MIMO_API_KEY}
        base_url: https://api.mimo.xiaomi.com/v1
        default_model: mimo-7b-rl
      moonshot:                      # Kimi
        api_key: ${MOONSHOT_API_KEY}
        base_url: https://api.moonshot.cn/v1
        default_model: kimi-k2
      openrouter:
        api_key: ${OPENROUTER_API_KEY}
        base_url: https://openrouter.ai/api/v1
        default_model: anthropic/claude-3.5-sonnet
        extra_headers:
          HTTP-Referer: https://github.com/Reider85/OryaAgent
          X-Title: OryaAgent
      ollama:                        # local
        base_url: http://localhost:11434/v1
        default_model: qwen2.5-coder:14b
        api_key: "ollama"            # placeholder, any non-empty
      lmstudio:                      # local
        base_url: http://localhost:1234/v1
        default_model: qwen2.5-coder-7b-instruct
        api_key: "lm-studio"
      vllm:                          # local production-grade
        base_url: http://localhost:8000/v1
        default_model: Qwen/Qwen2.5-7B-Instruct
        api_key: "vllm"
    # ... (full list — см. providers.yaml)
  ```
- **Capability registry:** `app/core/llm/capabilities.yaml` — `{provider: {model: {supports_tools, supports_streaming, supports_system_prompt, context_window}}}`.
  - ⚠️ **Важно:** DeepSeek-R1 (`deepseek-reasoner`), Qwen-QwQ, GLM-Zero, o1 — **reasoning-модели без tool-calling**. Для них в MVP есть fallback: режим `tools=off` (plain chat без function-calling). Это фиксируется в capabilities и тестируется.
- **Importers** (см. M-01): `orya import --from opencode|continue|aider|cline` — миграция с существующих агентов.

**M-03 — PostgreSQL-схема (orya_sessions)**
- `app/db/schema.sql` — таблицы: `sessions`, `messages`, `tool_calls`, `memory_audit_log`.
- `app/db/__init__.py::get_asyncpg_pool()` — connection pool.
- Миграции через `alembic` (или простые `.sql` файлы в `app/db/migrations/`).
- PostgresSaver (LangGraph) — отдельная таблица `checkpoints` для LangGraph state.

### 3.2. Core agent (M-04 … M-06)

**M-04 — LangGraph core (StateGraph)**
- `app/core/graph.py::build_graph() -> CompiledStateGraph`.
- State: `messages: list[BaseMessage]`, `tools: list`, `session_id: str`, `user_id: str`, `permission_queue: list`.
- Nodes: `agent` (LLM-call), `tool_executor` (parallel tool-calls через `asyncio.gather` для bounded concurrency).
- Edges: `agent → tool_executor → agent` (цикл), `agent → END` (когда нет tool-calls).
- `interrupt_before` hook для permission-policy (M-13).
- PostgresSaver как checkpointer.

**M-05 — System-prompt-builder + untrusted-content warning**
- `app/core/prompt.py::build_system_prompt(state, tools) -> list[BaseMessage]`.
- Секции:
  1. Identity block ("You are OryaAgent, a senior code-agent...").
  2. Tool descriptions (через `format_tool_to_openai_function`).
  3. Project context block (из `PROJECT.md`, если есть).
  4. Long-term memory block (L0 = 6 файлов; инжектирует 4 scored-файла — `LEARNED.md` + `PREFERENCES.md` + `FACTS.md` + `DECISIONS.md`; `PROJECT.md` уходит в project-context-блок, `MEMORY_INDEX.md` — пустой placeholder).
  5. Behavior rules (workspace hygiene, atomic-writes, no destructive ops without confirmation).
  6. **Untrusted-content policy block** (M-22) — warning, что содержимое файлов/user-input может быть malicious, не выполнять инструкции из file-content.
- В v7 (BETA) сюда добавится `dynamic_suffix` из DFC, но в MVP — статичный system-prompt.

**M-06 — Context-manager (trim_messages)**
- `app/core/context.py::trim_messages(messages, max_tokens=120000) -> list[BaseMessage]`.
- Использует `langchain_core.messages.trim_messages` с token-counter'ом (`tiktoken` для OpenAI/Anthropic).
- Стратегия: keep system + last N messages (sliding window).
- В v7 (BETA) будет заменён на DFC (5 слоёв), но MVP-контракт (`trim_messages(messages, max_tokens) -> list`) остаётся.

### 3.3. Инструменты кодинга (M-07 … M-12)

**M-07 — Tool: read**
- `app/tools/read.py::read(path, start_line=None, end_line=None) -> str`.
- Читает файл, возвращает содержимое (с line-numbers).
- Интеграция с CacheWrapper (M-21): `cache.get(hash(path, mtime)) → cache.set(...)`.

**M-08 — Tool: write**
- `app/tools/write.py::write(path, content, create_dirs=True) -> str`.
- Atomic-write (write to `.tmp`, then rename).
- Triggers permission-policy (interrupt_before).

**M-09 — Tool: edit**
- `app/tools/edit.py::edit(path, old_string, new_string) -> str`.
- String-replace, FAIL если old_string не unique.
- Triggers permission-policy.

**M-10 — Tool: bash (с Token-efficient output)**
- `app/tools/bash.py::bash(command, timeout=30) -> str`.
- `asyncio.create_subprocess_exec`, capturing stdout/stderr.
- **Token-efficient output (M-23):** JSON-structure (`{"stdout": "...", "stderr": "...", "exit_code": 0, "duration_ms": 123, "truncated": false}`); stream > 5000 chars → head 2500 + `... [N chars truncated] ...` + tail 2500; ≥100 identical consecutive lines → `... [N identical lines] ...` (dedup before truncation).
- Triggers permission-policy.

**M-11 — Tool: grep/glob (с Token-efficient output)**
- `app/tools/grep.py::grep(pattern, path, glob_pattern="*") -> list[dict]`.
- `app/tools/glob.py::glob(pattern, path) -> list[str]`.
- Использует `ripgrep` (subprocess) — fast, .gitignore-aware.
- **Token-efficient output (M-23):** structured JSON (`{"matches": [{"file": "...", "line": N, "content": "..."}], "count": N, "truncated": false}`; glob → `{"files": [...], "count", "truncated"}`), max 500 matches per call (`max_matches`).
- Интеграция с CacheWrapper.

**M-12 — Tool-registry integration**
- `app/core/tools.py::get_tools(session_id) -> list[BaseTool]`.
- Все 6 tools (read, write, edit, bash, grep, glob) зарегистрированы и привязаны к LangGraph через `graph.bind_tools(tools)`.
- Готовность к расширению: v6 BETA добавит `oriahs_search`, v7 BETA — `lsp_*` (7 tools) и `ukb.lookup`.

### 3.4. Безопасность и persistence (M-13 … M-14, M-21, M-22)

**M-13 — Permissions (interrupt_before + policy)**
- `app/core/permissions.py::PermissionPolicy`.
- `should_interrupt(tool_name, args, session_state) -> bool`.
- `strict` policy: interrupt на `write`, `edit`, `bash`.
- `permissive` policy: interrupt только на `bash` с `rm`/`mv`/`sudo`.
- `/learn` и `/memory/*` — без interrupt (trust user explicit command, см. v6 M-13).
- В v7: сохраняется как есть; v7 BETA добавит LSP-rename safety-check.

**M-14 — Session-log (PostgresSaver + JSONL projection)**
- `app/db/session_log.py::log_message(session_id, role, content, tool_calls)`.
- PostgresSaver для LangGraph state checkpoints.
- Дополнительная таблица `messages` (typed) для query-friendly логов.
- JSONL projection: `~/.orya/sessions/{session_id}.jsonl` — append-only log для replay/debug.

**M-21 — CacheWrapper (Redis для read/grep)**
- `app/core/cache.py::CacheWrapper(redis: Redis)`.
- `get(key) -> str | None`, `set(key, value, ttl=3600)`.
- Key = `sha256(serialized(args) + mtime(path))` для read/grep.
- Invalidation: TTL + mtime-change (на следующем call перечитывает).
- В v7 ALPHA будет расширен до PromptCacheLayout (provider-side prompt-caching).

**M-22 — Prompt injection defense**
- `app/core/security.py::sanitize_untrusted(content) -> str`.
- Markers: `[UNTRUSTED_CONTENT_START]` ... `[UNTRUSTED_CONTENT_END]` вокруг file-content / user-prompt-внутри-system-prompt.
- Detect: `<!-- ignore previous instructions -->`, `system:`, `<|im_start|>`, role-overriding паттерны.
- Log suspected injections в `memory_audit_log` (security.incident).
- В v7 ALPHA: span attribute `security.incident=true` через OryaObservability.

### 3.5. UI (M-15 … M-17)

**M-15 — Chainlit UI: on_chat_start, on_message (через FastAPI)**
- `app/ui/chainlit_app.py`.
- `@cl.on_chat_start`: init session, load `PROJECT.md`, build system-prompt.
- `@cl.on_message`: invoke LangGraph, stream response, render tool-calls.
- FastAPI backend (отдельный process или embedded через `chainlit.run`).
- В v5/v6: M-24 обновил M-15 — Chainlit работает **через FastAPI** (не напрямую с LangGraph).

**M-16 — Chainlit UI: ask-prompt для interrupt_before**
- `app/ui/interrupt.py::ask_permission(tool_name, args) -> bool`.
- При `interrupt_before` → Chainlit prompt: "Tool `{tool_name}` wants to run with args: `{args}`. Approve?".
- Buttons: `Approve` / `Deny` / `Approve & don't ask again for this tool in session`.

**M-17 — Chainlit UI: sidebar сессий, settings**
- Sidebar: list of sessions (load from `sessions` table), "New session" button.
- Settings panel: LLM-provider/model, permission-policy, theme.
- `/learn` slash-command (см. M-26).
- `/memory/stats` slash-command (см. M-27).
- `/memory/compact` slash-command (см. M-27).

### 3.6. Тесты и документация (M-18, M-19, M-20)

**M-18 — Smoke-тесты 5 эталонных задач (расширенные)**
- `tests/smoke/test_smoke.py` — детерминированные: scripted `FakeMessagesListChatModel`, **без real LLM-вызовов и без параметризации по провайдерам** (Forbidden pattern BACKLOG4 M-18). Мультипровайдерность проверяют integration-тесты `tests/integration/test_provider_*.py` (skip через `require_env`, если нет API-ключа).
- 5 эталонных сценариев:
  1. Read + explain a Python file.
  2. Edit a function signature + call-site (atomic).
  3. Run `bash("pytest tests/")` and parse output.
  4. `grep` for a symbol across the project + report matches.
  5. `/learn` a fact → use it in next turn (memory persistence; раскомментирован после M-25..M-27).
- + 3 проверки v5 (BACKLOG5): cache-hit на повторном read, injection-warning в ToolMessage, bash → JSON-документ.
- + проверки `/memory/stats` и atomic-append durability (см. v6 M-18; закрыты M-27). Итого 10 тестов.

**M-19 — README + cross-links**
- `README.md`: что это, как запустить (`make dev`), как настроить LLM-provider, как добавить свой tool.
- Cross-links на `ARCHITECT7.md`, `ROADMAP7.md`, `BACKLOG7.md` для контекста.
- `CONTRIBUTING.md`: стиль кода, тесты, PR-flow.

**M-20 — FastAPI /sessions endpoints**
- `app/api/sessions.py`:
  - `POST /sessions` — create new.
  - `GET /sessions/{id}` — get metadata + messages.
  - `POST /sessions/{id}/messages` — send message (для non-UI клиентов).
  - `DELETE /sessions/{id}` — delete (soft-delete).
- Используется Chainlit'ом и внешними клиентами (CI, batch в PROD).

### 3.7. L0 Memory (M-25, M-26, M-27) — новые в v6, сохранены в v7

**M-25 — MDStore: L0 MD-файлы + atomic-append**
- `app/core/memory/md_store.py::MDStore` (+ `models.py::MemoryItem`, `audit.py::record_memory_op`).
- 6 файлов в `~/.orya/memory/` (бюджеты из `MAX_BYTES` / `DEFAULT_MAX_BYTES` = 8 KB):
  - `PROJECT.md` (8 KB) — проект-контекст (mission, stack, conventions); читается в `project_context_block`, не в memory-блоке.
  - `LEARNED.md` (4 KB) — выученные факты (через `/learn`).
  - `PREFERENCES.md` (2 KB) — предпочтения пользователя (стиль кода, tone).
  - `FACTS.md` (2 KB) — критические факты о проекте.
  - `DECISIONS.md` (2 KB) — короткие ADR-выжимки.
  - `MEMORY_INDEX.md` (8 KB) — auto-generated индекс L1/L2 memory (пустой placeholder в MVP, full в BETA+).
- `append(file, content) -> None` — один `os.write` в fd с `O_APPEND` + `fsync` под per-file `threading.Lock` (`fcntl.flock` — best-effort только на POSIX, на Windows no-op). tmp + `os.replace` — только для rewrite при compaction (M-27), не для append.
- `read(file) -> str`.
- `read_all() -> dict[str, str]` — 6 ключей (= `FILES`).
- `mtime(file) -> float` (для cache-invalidation).
- `stats()` — bytes / entries / last_write / over_limit для каждого файла.

**M-26 — `/learn` endpoint + Chainlit slash-command**
- `app/api/learn.py::POST /learn`:
  - Body: `{"content": str, "category": "fact|preference|project"}`.
  - Action: append по `category` → файл: `fact` → `FACTS.md`, `preference` → `PREFERENCES.md`, `project` → `LEARNED.md`.
  - Return: `{"status", "learned_id", "file", "compacted", "line_count"}`.
- Chainlit: `@cl.on_slash_command("learn")` — prompt for content, call API.
- После `/learn` — обновляется `format_memory_block()` в `build_system_prompt` (на следующем turn'е LLM видит новый факт).

**M-27 — Compactor + `/memory/compact`, `/memory/stats`**
- `app/core/memory/compactor.py::Compactor`.
- `compact() -> None` — L0 → L1 placeholder (просто подсчёт строк/токенов, без embeddings). В v6 BETA (B-21) будет full L1 SQLiteStore.
- Triggers: раз в 24 часа (через APScheduler) или manual `/memory/compact`.
- `POST /memory/compact` — запуск compaction.
- `GET /memory/stats` — `{"files": [...], "line_counts": {...}, "token_counts": {...}, "last_compacted": "..."}`.
- `memory_audit_log` таблица — каждое `append` / `compact` логируется (who, when, what, why).

---

## 4. Архитектурные инварианты (не нарушать в MVP)

Эти инварианты заложены в MVP, потому что v7 ALPHA/BETA/PROD будут их расширять, не переписывая:

1. **LLM-seam (M-01):** функция `get_llm(provider, model, **kwargs) -> BaseChatModel` остаётся с тем же интерфейсом. v7 ALPHA обернёт её в `TieredModelRouter.select(tier, user_id)` и `ConnectionPool.acquire(provider)`, но `get_llm` останется точкой входа. **Реестр провайдеров `providers.yaml` и моделей `models.yaml`** — declarative, расширяется без изменения кода (новый провайдер = новая запись в YAML). TieredModelRouter в ALPHA будет комбинировать модели из разных провайдеров (например, `small=deepseek-chat`, `large=claude-sonnet-3.5`, `tournament=[qwen3-coder, glm-4.5, deepseek-r1]`).

2. **System-prompt-builder (M-05):** сигнатура `build_system_prompt(state, tools) -> list[BaseMessage]`. v7 BETA добавит параметр `dfc: DFC` и будет инжектировать dynamic_suffix, но текущий контракт сохранится (через default-arg `dfc=None`).

3. **Tool-registry (M-12):** `get_tools(session_id) -> list[BaseTool]`. v7 BETA обернёт список через `CapabilityRegistry.filter(tools, context)` — но `get_tools` останется источником полного tool-list.

4. **Context-manager (M-06):** `trim_messages(messages, max_tokens) -> list[BaseMessage]`. v7 BETA DFC заменит реализацию, но сигнатура останется (или будет адаптер `dfc.assemble_hot(plan)` для system-prompt-части).

5. **Memory-seam:** `MDStore` (M-25) имеет интерфейс `append(file, content)`, `read(file)`, `mtime(file)`. v6 BETA добавит `SQLiteStore` (L1) и `QdrantStore` (L2) — но MDStore останется L0.

6. **CacheWrapper (M-21):** `get(key)`, `set(key, value, ttl)`. v7 ALPHA добавит `PromptCacheLayout` (provider-side), но CacheWrapper останется для tool-results.

---

## 5. Целевые NFR (Non-Functional Requirements)

| Параметр | Целевое значение |
|---|---|
| Time-to-first-token | ≤ 1300 ms |
| Latency p50 (простой ход) | ≤ 3 s |
| Tokens per turn (avg) | 30-60 K |
| Cost per session (30 ходов) | ≤ $0.45 |
| Smoke-тестов проходит | 10/10 (5 эталонных задач + 5 расширенных) |
| Prompt-injection detected | 100% (fail-closed) |
| Session-log durability | 100% (PostgresSaver + JSONL dual-write) |

---

## 6. Definition of Done (DoD)

- ✅ `make dev` запускает Chainlit UI на http://localhost:8000.
- ✅ Первый чат создаёт сессию, персистит в PostgreSQL, виден в sidebar.
- ✅ LLM-call проходит через `get_llm()` seam (default: Anthropic claude-sonnet-3.5).
- ✅ **Мультипровайдерность:** live-проверка tool-calling минимум на 5 провайдерах (Anthropic + DeepSeek + Qwen + GLM + Ollama local) — `tests/integration/test_provider_*.py` c skip-флагом `require_env("<PROVIDER>_API_KEY")`. Остальные 15+ провайдеров — те же integration tests с тем skip-механизмом. Smoke-тесты (M-18) real LLM не вызывают (детерминированы fake-моделью).
- ✅ **Capability-detection:** `get_llm(provider="deepseek", model="deepseek-reasoner")` — выдаёт понятную ошибку "Reasoning model without tool-calling — используйте deepseek-chat".
- ✅ **Provider-picker в UI:** Chainlit sidebar показывает dropdown с 20+ провайдерами и их моделями (из `providers.yaml` + `models.yaml`).
- ✅ **`/llm/health/{provider}`** endpoint возвращает status 200 если провайдер доступен.
- ✅ **`/llm/providers`** и **`/llm/models`** endpoints возвращают declarative registries.
- ✅ **Importers:** `orya import --from opencode` читает `~/.config/opencode/auth.json` и заполняет `~/.orya/config.yaml`.
- ✅ Все 6 tools (read, write, edit, bash, grep, glob) работают на всех поддерживаемых провайдерах с tool-calling:
  - `read` возвращает file-content.
  - `write` создаёт/обновляет файл atomically.
  - `edit` делает string-replace с uniqueness-check.
  - `bash` выполняет команду, возвращает structured-output для длинных логов.
  - `grep` ищет по проекту через ripgrep, возвращает structured JSON.
- ✅ Permission-policy: write/edit/bash → interrupt_before → Chainlit ask-prompt.
- ✅ Session-log: каждый ход в PostgreSQL + JSONL projection.
- ✅ CacheWrapper: повторный `read` того же файла (с тем же mtime) → cache-hit.
- ✅ Prompt-injection defense: системная инструкция с `<!-- ignore previous -->` → detected, logged.
- ✅ 6 MD-файлов L0 создаются при первом запуске (если их нет; существующие не трuncate-ятся).
- ✅ `/learn` slash-command → append в LEARNED.md → виден в следующем turn'е.
- ✅ `/memory/stats` → JSON с file-sizes/line-counts/last-modified.
- ✅ `/memory/compact` → запускает Compactor (placeholder в MVP: подсчёт метрик без embeddings).
- ✅ `memory_audit_log` пишется на каждое memory-operation.
- ✅ Smoke-тесты 10/10 проходят детерминированно, без API-ключа (fake model): 5 эталонных задач + 3 v5-проверки (cache/injection/JSON) + 2 memory-проверки (`/memory/stats`, atomic-append).
- ✅ README объясняет, как запустить и расширить (включая секцию «Как подключить новый провайдер»).

---

## 7. TRIZ-gates фазы

| Gate | Принцип | Что встроено |
|---|---|---|
| LLM-provider seam | ТРИЗ #15 Dynamicity + #24 Intermediary | init_chat_model, расширяем без rewrite |
| Tool-registry | ТРИЗ #15 Dynamicity + #25 Self-service | tools регистрируются декларативно |
| Permission-policy | ТРИЗ #9 Preliminary anti-action | interrupt_before — confirm перед destructive op |
| CacheWrapper | ТРИЗ #11 Beforehand + #19 Periodic | Redis cache для read/grep, mtime-invalidation |
| L0 MD-memory | ТРИЗ #21 Rushing + #25 Self-service | atomic-append, user-controlled через /learn |
| Atomic-writes (write/edit) | ТРИЗ #9 Preliminary anti-action | write to .tmp → rename (no partial state) |
| Smoke-тесты | ТРИЗ #28 Mechanics substitution | auto-тесты заменяют manual verification |
| Token-efficient output | ТРИЗ #16 Partial effect + #35 Parameter changes | truncate large bash/grep output |
| Untrusted-content markers | ТРИЗ #9 Preliminary anti-action | mark file-content как untrusted в system-prompt |
| PostgresSaver + JSONL dual-write | ТРИЗ #40 Composite materials | DB for query + JSONL for replay/debug |
| Memory audit log | ТРИЗ #35 Parameter changes | every memory-op logged с who/what/why |

---

## 8. Риски фазы и mitigations

| Риск | Mitigation |
|---|---|
| LLM-provider API key не настроен | Fail-fast на старте с понятным сообщением; список возможных env-vars в error; `orya providers list` для диагностики |
| Reasoning-модель (DeepSeek-R1, o1, Qwen-QwQ) не поддерживает tool-calling | Capability-detection в `get_llm()`; fallback на plain-chat-mode; warning в logs |
| Китайский провайдер geo-blocked (DeepSeek/Qwen/GLM недоступны из ЕС/US без VPN) | Health-check `GET /llm/health/{provider}` перед использованием; авто-fallback на OpenRouter-equivalent |
| OpenRouter rate-limit (403/429 на free tier) | Retry с exponential-backoff (3 попытки); fallback на direct provider |
| Token-blowup на reasoning-моделях (R1/o1 эмитят `<think>...</think>`) | `trim_thinking()` post-processor в `app/core/llm.py`; метрика `llm.call.thinking_tokens` |
| Локальный Ollama не запущен | `GET http://localhost:11434/api/tags` health-check; понятная ошибка «Запустите `ollama serve`» |
| LM Studio модель не загружена | `GET http://localhost:1234/v1/models` check; warning «Загрузите модель в LM Studio» |
| vLLM с длинным контекстом OOM | Передавать `max_model_len` через `extra_body`; auto-shrink context window |
| Китайский провайдер возвращает 400 на `cache_control` | Provider-capability detection; PromptCacheLayout (ALPHA) fallback на plain SystemMessage |
| Разные форматы tool-calling (Anthropic vs OpenAI-compat) | LangChain `bind_tools()` сам маппит; тесты на 5+ провайдерах в integration (`tests/integration/test_provider_*.py`) |
| Prompt-injection через file-content | Markers + sanitization + audit log (M-22) |
| Token-blowup на больших файлах | `read` с start_line/end_line, `bash` с token-efficient output (M-23) |
| Concurrent session writes в MD-файлы | `fcntl.flock` file-lock в MDStore |
| PostgresSaver checkpoint corruption | JSONL projection как fallback для replay |
| Smoke-тесты flaky на CI | Изолированные test-fixtures, deterministic test data (scripted fake model, без внешних API); external-providers только в integration со skip без ключей |

---

## 9. Forbidden patterns

- ❌ Использовать LLM-call напрямую без `get_llm()` seam.
- ❌ Импортировать `langchain_anthropic` / `langchain_openai` / `langchain_google_vertexai` в бизнес-логике (`graph.py`, `prompt.py`, `tools.py`) — только в `app/core/llm.py`.
- ❌ Хардкодить `if provider == "anthropic"` в любом файле кроме `app/core/llm.py` и `app/core/llm/providers.yaml` — все провайдер-специфичные настройки живут в declarative registry.
- ❌ Хардкодить model names в коде — через `models.yaml` alias (например, `qwen-coder`, а не `qwen3-coder-plus`).
- ❌ Хардкодить base_url провайдера в коде — только в `providers.yaml` или env.
- ❌ Использовать reasoning-модели (DeepSeek-R1, o1, Qwen-QwQ, GLM-Zero) с `bind_tools()` без capability-check — будет runtime error у пользователя.
- ❌ Зависеть от OpenAI-only фич (например, `response_format: {type: "json_object"}`) — только через LangChain `with_structured_output()`, который сам выбирает supported format per provider.
- ❌ Хардкодить tool-list в `build_graph()` — через `get_tools(session_id)`.
- ❌ Делать destructive op без `interrupt_before` (кроме `/learn`, `/memory/*` — explicit user command).
- ❌ Хранить PII (API keys, secrets) в MD-файлах L0 — только knowledge, не credentials.
- ❌ Хранить API-keys в `~/.orya/config.yaml` plaintext — только через `${ENV_VAR}` подстановку.
- ❌ Использовать `eval()` / `exec()` для tool-output parsing — только json.loads / ast.literal_eval.
- ❌ Блокировать event-loop в tool-executor — `asyncio.to_thread` для CPU-bound, `subprocess` для shell.
- ❌ Дублировать logic между Chainlit UI и FastAPI endpoints — общий `app/core/` layer.
- ❌ Не писать smoke-тесты — 5 эталонных задач обязательны (M-18).
- ❌ Пропускать `memory_audit_log` на любой memory-operation.
- ❌ Использовать `print()` — только `logging` через `app/core/log.py`.

---

## 10. Структура файлов

```
app/
├── __init__.py
├── main.py                    # FastAPI app entry-point
├── core/
│   ├── __init__.py
│   ├── config.py              # M-02: pydantic-settings + multi-provider config
│   ├── llm.py                 # M-01: get_llm() seam (OpenAI-compat-first)
│   ├── llm/
│   │   ├── __init__.py
│   │   ├── providers.yaml     # declarative registry: 20+ провайдеров
│   │   ├── models.yaml        # declarative registry: model aliases + capabilities
│   │   ├── capabilities.yaml   # supports_tools / supports_streaming / context_window
│   │   ├── pricing.yaml        # input_per_1k / output_per_1k per model
│   │   ├── importers.py        # import_opencode(), import_continue(), import_aider()
│   │   └── adapters/
│   │       ├── __init__.py
│   │       ├── anthropic.py   # ChatAnthropic wrapper
│   │       ├── openai_compat.py  # ChatOpenAI(base_url=...) — universal adapter
│   │       ├── gemini.py       # ChatVertexAI / ChatGoogleGenerativeAI
│   │       └── local.py       # Ollama / LM Studio / vLLM / llama.cpp / TGI / LocalAI
│   ├── graph.py               # M-04: LangGraph build_graph()
│   ├── prompt.py              # M-05: build_system_prompt()
│   ├── context.py             # M-06: trim_messages() + trim_thinking() for reasoning models
│   ├── tools.py               # M-12: get_tools()
│   ├── permissions.py         # M-13: PermissionPolicy
│   ├── security.py            # M-22: sanitize_untrusted()
│   ├── cache.py               # M-21: CacheWrapper (Redis)
│   ├── log.py                 # logging setup
│   └── memory/
│       ├── __init__.py
│       ├── md_store.py         # M-25: MDStore L0 (6 файлов)
│       ├── models.py           # M-25: MemoryItem (записи §3.1.1)
│       ├── audit.py            # M-25: record_memory_op → memory_audit_log
│       └── compactor.py        # M-27: Compactor L0→L1 placeholder
├── tools/
│   ├── __init__.py
│   ├── read.py                # M-07
│   ├── write.py               # M-08
│   ├── edit.py                # M-09
│   ├── bash.py                # M-10
│   ├── grep.py                # M-11
│   └── glob.py                # M-11
├── api/
│   ├── __init__.py
│   ├── sessions.py            # M-20: /sessions
│   ├── learn.py               # M-26: /learn
│   ├── memory.py              # M-27: /memory/stats, /memory/compact
│   └── llm.py                 # /llm/health/{provider}, /llm/providers, /llm/models
├── db/
│   ├── __init__.py            # get_asyncpg_pool()
│   ├── schema.sql             # M-03
│   └── session_log.py         # M-14
└── ui/
    ├── __init__.py
    ├── chainlit_app.py        # M-15, M-24
    ├── interrupt.py           # M-16: ask_permission()
    └── sidebar.py             # M-17: sessions, settings, provider-picker

tests/
├── conftest.py
├── unit/
│   ├── test_llm_seam.py           # get_llm() для всех 20+ провайдеров (mocked)
│   ├── test_llm_providers_yaml.py # валидность providers.yaml
│   ├── test_llm_models_yaml.py    # валидность models.yaml
│   ├── test_capabilities.py        # capability-detection для reasoning vs chat
│   ├── test_importers.py           # import_opencode, import_continue, import_aider
│   ├── test_tools.py
│   ├── test_cache.py
│   ├── test_permissions.py
│   ├── test_md_store.py
│   ├── test_memory_models.py   # MemoryItem: формат §3.1.1, ids, парсер
│   └── test_compactor.py
├── integration/
│   ├── test_provider_anthropic.py     # real API call (skip в CI если нет ключа)
│   ├── test_provider_deepseek.py
│   ├── test_provider_qwen.py
│   ├── test_provider_glm.py
│   ├── test_provider_openrouter.py
│   ├── test_provider_ollama.py         # local, always-run
│   └── test_provider_lmstudio.py
└── smoke/
    └── test_smoke.py          # M-18: 5 эталонных задач + 3 v5-проверки + 2 memory-проверки (fake model; провайдеры — в integration)

~/.orya/
├── config.yaml                # M-02: multi-provider config
├── memory/                    # M-25 (6 файлов)
│   ├── PROJECT.md             # ≤ 8 KB — project context (project-context-блок)
│   ├── LEARNED.md             # ≤ 4 KB — факты через /learn
│   ├── PREFERENCES.md         # ≤ 2 KB — предпочтения
│   ├── FACTS.md               # ≤ 2 KB — критические факты
│   ├── DECISIONS.md           # ≤ 2 KB — ADR-выжимки
│   └── MEMORY_INDEX.md        # ≤ 8 KB — индекс L1/L2 (пустой placeholder)
└── sessions/                  # M-14
    └── {session_id}.jsonl
```

---

## 11. Порядок реализации (рекомендуемый)

1. **Неделя 1:** M-00 (bootstrap), M-02 (config), M-03 (DB schema), M-01 (LLM-seam), M-04 (graph skeleton), M-07 (read), M-12 (tool-registry). Демонстрация: LLM-call с одним tool.
2. **Неделя 2:** M-05 (system-prompt), M-06 (context-manager), M-08 (write), M-09 (edit), M-10 (bash), M-11 (grep/glob), M-13 (permissions), M-14 (session-log). Демонстрация: 6 tools работают, session-log пишется.
3. **Неделя 3:** M-15 (Chainlit UI), M-16 (interrupt), M-17 (sidebar), M-20 (FastAPI /sessions), M-21 (CacheWrapper), M-22 (prompt-injection defense). Демонстрация: end-to-end UI с permissions.
4. **Неделя 3.5:** M-25 (MDStore L0), M-26 (/learn), M-27 (Compactor + /memory/stats, /memory/compact), M-18 (smoke-тесты), M-19 (README). Демонстрация: /learn работает, smoke-тесты 5/5.

---

## 12. Exit criteria (переход MVP → ALPHA)

- ✅ L0 MD-память работает: 6 файлов, atomic-append, /learn, /memory/stats.
- ✅ Memory-audit log пишется.
- ✅ Periodic compaction запускается раз в 24 часа (через APScheduler).
- ✅ Smoke-тест: /learn после успешного tool-call sequence → запись в LEARNED.md → видна в следующем turn'е.
- ✅ Все 6 tools работают end-to-end в UI.
- ✅ Permission-policy работает (interrupt_before на write/edit/bash).
- ✅ Session-log восстанавливается после restart.
- ✅ README + smoke-тесты в CI green (10/10: 5 эталонных задач + 5 расширенных).

---

## 13. Ссылки на исходные документы

- `ARCHITECT7.md` §0 (executive summary), §18 (связь с фазами) — MVP = v6 MVP без изменений.
- `ROADMAP7.md` §3 (Фаза MVP) — полностью ссылается на `ROADMAP6.md` §3.
- `BACKLOG7.md` §2 (Фаза MVP) — полностью ссылается на `BACKLOG6.md` §2 (M-00..M-27).
- `BACKLOG6.md` §2 — полные описания 28 тикетов MVP.
- `ARCHITECT6.md` §3.1, §4, §6.1.1, §6.1.4 — детали L0 memory, MDStore, Compactor.

---

**Готов к реализации.** После завершения MVP переходи к фазе ALPHA (`PROMPT_ALPHA.md`) — там добавятся TieredModelRouter, PromptCacheLayout, ConnectionPool.
