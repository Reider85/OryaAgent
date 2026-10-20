# ADR-002: LLM-провайдер как сменяемый шов с первого дня

**Дата:** 2026-10-20
**Статус:** Accepted
**Decision makers:** core team

---

## Контекст

[`agents-architect.md`](../agents-architect.md) анализ показал: **5 из 5 зрелых кодинг-агентов** имеют архитектурный «шов» (seam) для LLM-провайдера, кроме Claude Code. Claude Code сознательно завязан на Anthropic API — это ко-эволюция харнесса с моделью (prompt-cache, thinking-blocks). Для остальных — LLM-провайдер сменяем.

[`self-agent.md`](../self-agent.md), вывод №6: «Claude Code остаётся архитектурным изолятом именно потому, что отказался от шва. Все четыре остальных архитектуры ставят шов с первого дня. Цена отсутствия шва — переписывание ядра.»

Для OryaAgent нужно было решить: делать шов с первого дня, или оптимизировать под одну модель (например, Claude 3.5 Sonnet) для глубины интеграции.

## Рассмотренные альтернативы

### Вариант A: Hardcoded Anthropic API (как Claude Code)

- **Плюсы:**
  - Глубокая интеграция с prompt-cache, thinking-blocks, computer-use
  - Меньше кода (один adapter вместо registry)
  - Prompt-cache оптимизация — без компромиссов
- **Минусы:**
  - Завязка на одного провайдера — рискованно стратегически
  - Цена отсутствия шва — переписывание ядра, если понадобится сменить провайдера
  - Пользователи без Anthropic-access (например, в корпоративных сетях без Anthropic) — отрезаны
  - Local inference (Ollama, LM Studio) — невозможен
  - Конкурентное преимущество исчезнет, если Anthropic поднимет цены или поменяет ToS

### Вариант B: LLMProvider Protocol с первого дня (как OpenCode, dsh, MiMo)

- **Плюсы:**
  - Сменяемость — ключевая ценность open-source
  - Поддержка local inference (Ollama, LM Studio) — privacy-conscious users
  - Поддержка нескольких cloud-провайдеров (OpenAI, Anthropic, Cohere, Mistral)
  - Стратегическая гибкость: можно добавить собственный gateway
- **Минусы:**
  - Больше кода (registry + 2 адаптера минимум)
  - Prompt-cache оптимизация — работает только для Anthropic, для других — degraded
  - Tool-call format conversion — overhead на каждом LLM-call
  - Testing complexity — VCR-cassettes для каждого провайдера

### Вариант C: LLM-agnostic, но с одной reference implementation

- **Плюсы:**
  - Protocol определён, но только Anthropic adapter — полностью функционален
  - Другие adapters — community-contributed
- **Минусы:**
  - По факту — Вариант B с неполным покрытием
  - Community-адаптеры — часто low-quality, ломаются при API changes
  - Разработчики core-team несут ответственность за все адаптеры, но контролируют только один

## Решение

**Вариант B: LLMProvider Protocol с первого дня, с двумя reference адаптерами:**

1. **OpenAI-compat адаптер** — покрывает:
   - OpenAI (`api.openai.com`)
   - Azure OpenAI
   - Ollama (local)
   - vLLM (self-hosted)
   - OpenRouter (200+ моделей)
   - Together AI, Anyscale, Replicate
   - LM Studio (local)
   - Любой другой OpenAI-compat endpoint

2. **Anthropic адаптер** — покрывает:
   - Anthropic API (`api.anthropic.com`)
   - AWS Bedrock (Anthropic models)
   - GCP Vertex AI (Anthropic models)

Эти два адаптера дают ~95% покрытия рынка LLM-провайдеров на 2026 год.

## Обоснование

1. **Вывод №6 из `agents-architect.md` — прямой:** все зрелые open-source агенты ставят шов с первого дня. Цена отсутствия — переписывание ядра. Это не speculation, это эмпирический вывод из 4 команд (OpenCode, Kilo, dsh, MiMo).

2. **Open-source ценности.** OryaAgent — open-source. Принуждение пользователя к конкретному cloud-провайдеру противоречит этому. Local inference (Ollama) — первая-class поддержка.

3. **Стратегическая гибкость.** Anthropic может поднять цены, изменить ToS, выпустить модель с худшим качеством. OryaAgent с швом — пользователи могут переключиться без переписывания своих workflow.

4. **Enterprise адаптация.** Корпоративные пользователи часто требуют self-hosted inference (vLLM) или корпоративный gateway. С швом — это конфигурация, не fork.

5. **Cost-awareness.** Разные модели имеют разный pricing. Пользователь должен иметь возможность выбрать дешёвую модель (gpt-4o-mini) для простых задач и дорогую (Claude Opus) для сложных. Шов делает это прозрачным.

6. **Tool-call conversion overhead — manageable.** Канонический формат → OpenAI/Anthropic API — это O(1) per message, не hot path. На typical LLM-call (5s), overhead <1ms. Незаметно.

7. **Prompt-cache optimization — partial.** Anthropic adapter получает full cache benefits. OpenAI-compat — auto-cache (без явных маркеров). Это acceptable degradation — пользователи OpenAI не теряют функциональность, только оптимизацию.

## Последствия

**Позитивные:**

- Сменяемость провайдера одной строкой конфига (`providers.yml`)
- Поддержка local inference (privacy-conscious, offline usage)
- Enterprise-friendly (gateway, BYOK, audit)
- Community может добавлять адаптеры (Cohere, Mistral, Gemini — через PR)
- Cost optimization — пользователь выбирает модель под задачу

**Негативные:**

- Двойная реализация edge-cases (Anthropic `tool_use` vs OpenAI `function_call`)
- Prompt-cache работает только для Anthropic (для OpenAI — implicit, не управляем)
- VCR-cassettes — maintenance burden (нужно обновлять, когда API меняется)
- Тестирование двух адаптеров вместо одного — больше test-suite

**Нейтральные:**

- Provider-specific features (Anthropic thinking, OpenAI function calling parallelism) — optional через `metadata` поле, не breaking Protocol
- Cost tracking — каждый adapter отвечает за свой pricing
- Token counting — adapter-specific (tiktoken для OpenAI, approximation для Anthropic)

## Реализация (детали)

### LLMProvider Protocol

```python
class LLMProvider(Protocol):
    @property
    def name(self) -> str: ...
    @property
    def models(self) -> list[str]: ...
    
    async def complete(self, req: LLMRequest) -> AsyncIterable[StreamEvent]: ...
    async def count_tokens(self, messages: list[Message]) -> int: ...
    async def validate(self) -> bool: ...
    def estimate_cost(self, usage: Usage) -> Decimal: ...
```

См. [02-llm-adapter-spec.md](../spec/02-llm-adapter-spec.md) раздел 3 для деталей.

### Канонический формат

- `LLMRequest`, `Message`, `ToolSpec`, `StreamEvent`, `LLMResponse` — Pydantic-модели
- Никаких provider-specific полей в канонических типах
- Конверсия — internal дело адаптера

### Registry

```python
class LLMRegistry:
    def __init__(self, config: dict[str, ProviderConfig]):
        self._providers: dict[str, LLMProvider] = {}
    
    def get(self, name: str) -> LLMProvider:
        if name not in self._providers:
            self._providers[name] = self._create(name)
        return self._providers[name]
    
    def _create(self, name: str) -> LLMProvider:
        if name == "anthropic":
            return AnthropicProvider(...)
        elif name == "openai":
            return OpenAICompatProvider(...)
        else:
            raise UnknownProviderError(name)
```

### Provider config

`~/.orya/providers.yml`:

```yaml
default: anthropic
providers:
  anthropic:
    api_key_env: ANTHROPIC_API_KEY
    model: claude-3-5-sonnet-20241022
    max_tokens: 4096
  openai:
    api_key_env: OPENAI_API_KEY
    model: gpt-4o
    base_url: https://api.openai.com/v1
  ollama:
    base_url: http://localhost:11434/v1
    api_key: dummy
    model: llama3.1:70b
  openrouter:
    api_key_env: OPENROUTER_API_KEY
    model: anthropic/claude-3.5-sonnet
    base_url: https://openrouter.ai/api/v1
```

### Switching mid-session

Через `/model` slash-command:

```
> /model openai gpt-4o
Switched to OpenAI gpt-4o. Next LLM-call will use this provider.

> продолжи
```

Session-log записывает `model_change` event, чтобы projection знал, какой провайдер использовался для каждого assistant-message.

## Критерии пересмотра решения

1. **Один из ключевых провайдеров** изменит tool-call формат breaking-way, и конверсия станет невозможна — пересмотреть канонический формат.
2. **Anthropic выпустит feature**, которая делает hardcoded-интеграцию стратегически важной (например, computer-use, требующий tight coupling с моделью) — рассмотреть гибрид: hardcoded Anthropic + LLMProvider Protocol для остальных.
3. **Cost overhead от конверсии** превысит 5% latency — оптимизировать hot-path или рассмотреть provider-specific fast-path.

## Связанные документы

- [02-llm-adapter-spec.md](../spec/02-llm-adapter-spec.md) — полная спецификация шва
- [agents-architect.md](../agents-architect.md) — анализ 5 архитектур (вывод №6)
- [self-agent.md](../self-agent.md) — вывод №3: «LLM-шов обязателен как точка сменяемости»
- [07-observability-spec.md](../spec/07-observability-spec.md) — метрики по провайдерам
- [OpenAI API reference](https://platform.openai.com/docs/api-reference)
- [Anthropic API reference](https://docs.anthropic.com/en/api)
