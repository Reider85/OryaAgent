# Спецификация LLM-адаптера

**Документ:** 02-llm-adapter-spec
**Дата:** 20 октября 2026
**Статус:** Draft v0.1
**Связанные документы:** [01-module-contracts.md](01-module-contracts.md), [ADR-002](../adr/ADR-002-llm-seam.md), [07-observability-spec.md](07-observability-spec.md)

---

## 0. Назначение

LLM-шов — единственный невосполнимый архитектурный шов. Эта спецификация фиксирует:
- Канонический формат запроса/ответа, не зависящий от провайдера
- Семантику stream-событий
- Контракты адаптеров для OpenAI-compat и Anthropic
- Стратегии prompt-cache, retry, cost-tracking
- Edge-cases, которые ломают наивные имплементации

Без этого документа любой адаптер превращается в спагетти из `if provider == 'anthropic'`.

## 1. Принципы проектирования

### 1.1. Канонический формат — истина

Все взаимодействия с `agent_loop` идут через канонические типы:
- `LLMRequest` — вход
- `AsyncIterable[StreamEvent]` — поток
- `LLMResponse` — финальное состояние после потребления потока

Канонические типы — Pydantic-модели. Они не содержат никаких полей, специфичных для провайдера. Если адаптеру нужно отправить `anthropic-version` заголовок — это internal деталь адаптера, не `LLMRequest`.

### 1.2. Stream-first

Нет метода `complete_sync`. Все ответы — `AsyncIterable[StreamEvent]`. Если провайдер не поддерживает streaming (редкость в 2026) — адаптер эмулирует: ждёт полный ответ, отдаёт одним пакетом. Это упрощает consumer-логику в `agent_loop`.

### 1.3. Провайдер-нейтральность

Ни одно поле в каноническом формате не называет провайдера. Адаптер сам решает, как конвертировать:
- `messages: list[Message]` → OpenAI `messages` или Anthropic `messages` + отдельный `system`
- `tools: list[ToolSpec]` → OpenAI `functions` или Anthropic `tools`
- `tool_calls` в ответе → единый `list[ToolCall]` для потребителя

### 1.4. Cost visibility

Каждый `LLMResponse` содержит `usage` с token-counts и estimated cost. Это инвариант: если адаптер не возвращает usage — это баг.

## 2. Канонические типы

### 2.1. `LLMRequest`

```python
class LLMRequest(BaseModel):
    model: str  # "claude-3-5-sonnet-20241022" или "gpt-4o"
    messages: list[Message]  # канонический формат
    tools: list[ToolSpec] | None = None  # Pydantic-схемы инструментов
    system: str | None = None  # системный промпт
    system_cacheable_prefix: str | None = None  # маркер для prompt-cache
    temperature: float = 0.0
    max_tokens: int = 4096
    stop_sequences: list[str] = []
    stream: bool = True  # всегда True в MVP
    user_id: str | None = None  # для OpenAI abuse-detection
    metadata: dict[str, Any] = {}  # provider-agnostic tags
```

### 2.2. `Message`

Каноническое сообщение — то, что хранится в сессии и передаётся LLM:

```python
class Message(BaseModel):
    role: Literal["user", "assistant", "tool"]
    content: str | list[ContentBlock]


class ContentBlock(BaseModel):
    kind: Literal["text", "tool_call", "tool_result", "image"]
    # для text:
    text: str | None = None
    # для tool_call:
    tool_call_id: str | None = None
    tool_name: str | None = None
    tool_input: dict[str, Any] | None = None
    # для tool_result:
    tool_call_id_ref: str | None = None  # ссылка на tool_call
    content: str | None = None
    is_error: bool = False
    # для image (v2):
    image_url: str | None = None
    media_type: str | None = None
```

Замечания:
- `assistant` может содержать смесь `text` + `tool_call` блоков — это нормальный случай, когда модель пишет текст и одновременно вызывает инструмент.
- `tool` роль — только для результатов. Входной tool-call живёт в `assistant.content[tool_call]`.
- `image` — для v2 (vision-модели). Сейчас в MVP — ошибка валидации.

### 2.3. `ToolSpec`

```python
class ToolSpec(BaseModel):
    name: str
    description: str
    input_schema: dict[str, Any]  # JSON Schema (Pydantic-сгенерированная)
    output_schema: dict[str, Any] | None = None  # опционально, для типизации результата
```

### 2.4. `StreamEvent`

Discriminated union — каждый вариант имеет `kind` поле:

```python
class StreamEvent(BaseModel):
    kind: Literal[
        "assistant_token",  # дельта текста
        "tool_call_start",  # начало tool-call
        "tool_call_delta",  # инкрементальный input (JSON-фрагмент)
        "tool_call_end",  # финализация tool-call
        "usage_update",  # токен-каунтер (может приходить несколько раз)
        "stop",  # финальное событие с stop_reason
    ]
    # для assistant_token:
    text: str | None = None
    # для tool_call_*:
    tool_call_id: str | None = None
    tool_name: str | None = None
    tool_input_delta: str | None = None  # всегда строка, накапливается в JSON
    # для usage_update:
    input_tokens: int | None = None
    output_tokens: int | None = None
    cache_read_tokens: int | None = None
    cache_write_tokens: int | None = None
    # для stop:
    stop_reason: (
        Literal["end_turn", "tool_use", "max_tokens", "stop_sequence", "error"] | None
    ) = None
    error: LLMError | None = None
```

### 2.5. `LLMResponse`

Агрегированное состояние после полного потребления stream:

```python
class LLMResponse(BaseModel):
    text: str  # весь ассистентский текст
    tool_calls: list[ToolCall]  # финализированные calls
    stop_reason: str
    usage: Usage
    raw: dict[str, Any] | None = None  # опционально, для debug


class ToolCall(BaseModel):
    id: str
    name: str
    input: dict[str, Any]  # распарсенный JSON


class Usage(BaseModel):
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    cost_usd: Decimal  # вычисляется в адаптере по прайсу
    duration_ms: int
```

## 3. Protocol адаптера

```python
class LLMProvider(Protocol):
    @property
    def name(self) -> str: ...  # "anthropic", "openai", "ollama"

    @property
    def models(self) -> list[str]: ...  # поддерживаемые модели

    async def complete(self, req: LLMRequest) -> AsyncIterable[StreamEvent]: ...

    async def count_tokens(self, messages: list[Message]) -> int: ...

    async def validate(self) -> bool: ...  # проверка API-key/коннекта

    def estimate_cost(self, usage: Usage) -> Decimal: ...
```

Никаких `__init__`-ов с API-keys в Protocol — это factory-зависимость. Конкретные провайдеры создаются через `LLMRegistry.create(name, config)`.

## 4. OpenAI-compat адаптер

### 4.1. Покрытие

Адаптер работает со всеми OpenAI-совместимыми API:
- **OpenAI** (`api.openai.com`)
- **Azure OpenAI** (отдельный endpoint, разные auth-headers)
- **Ollama** (`localhost:11434`) — локальные модели, бесплатно
- **vLLM** — self-hosted inference
- **OpenRouter** — агрегатор, 200+ моделей
- **Together AI, Anyscale, Replicate** — по необходимости
- **LM Studio** — локальный сервер

### 4.2. Endpoint-резолвинг

```python
provider_config:
  base_url: str = "https://api.openai.com/v1"   # переопределяется
  api_key_env: str = "OPENAI_API_KEY"
  default_headers: dict[str, str] = {}
  default_query: dict[str, str] = {}
```

Ollama — `base_url=http://localhost:11434/v1`. Azure — `base_url=https://{resource}.openai.azure.com/openai/deployments/{deployment}`.

### 4.3. Конвертация канонических типов → OpenAI API

| Канонический | OpenAI API | Заметки |
|---|---|---|
| `LLMRequest.system` | `messages[0] = {role:"system", content:...}` | Anthropic передаёт отдельно, OpenAI — в messages |
| `Message{role:"user"}` | `{role:"user", content:...}` | Прямое соответствие |
| `Message{role:"assistant", content: [text, tool_call]}` | `{role:"assistant", content:..., tool_calls:[...]}` | OpenAI требует, чтобы text был в content, а tool_calls — отдельное поле |
| `Message{role:"tool", content: [tool_result]}` | `{role:"tool", tool_call_id:..., content:...}` | Каждая `tool_result` — отдельное сообщение |
| `ToolSpec` | `tools: [{type:"function", function:{name, description, parameters}}]` | OpenAI оборачивает в `function` |
| `system_cacheable_prefix` | игнорируется | OpenAI auto-caches, явных маркеров нет (через `cache_control` в v2) |

### 4.4. Stream-парсинг

OpenAI возвращает SSE-stream с `delta`-событиями. Адаптер конвертирует:

```
OpenAI SSE: {"choices":[{"delta":{"content":"Hello"}}]}
  → StreamEvent(kind="assistant_token", text="Hello")

OpenAI SSE: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"call_abc","function":{"name":"bash","arguments":""}}]}}]}
  → StreamEvent(kind="tool_call_start", tool_call_id="call_abc", tool_name="bash")

OpenAI SSE: {"choices":[{"delta":{"tool_calls":[{"index":0,"function":{"arguments":"{\"com"}}]}}]}
  → StreamEvent(kind="tool_call_delta", tool_call_id="call_abc", tool_input_delta="{\"com")

OpenAI SSE: {"choices":[{"delta":{},"finish_reason":"tool_calls"}]}
  → StreamEvent(kind="tool_call_end", tool_call_id="call_abc")  # для каждого pending call
  → StreamEvent(kind="stop", stop_reason="tool_use")

OpenAI SSE: {"usage":{...}} (если включён stream_options.include_usage)
  → StreamEvent(kind="usage_update", input_tokens=..., output_tokens=...)
```

### 4.5. Edge-cases OpenAI

- **`tool_calls` и `content` одновременно:** OpenAI может вернуть `delta` с обоими. Адаптер должен корректно маршрутизировать в два разных stream-события.
- **Multiple tool_calls в одном ответе:** модель может вернуть несколько `tool_calls` (parallel function calling). Каждый — отдельный `tool_call_id`. Stream отправляет `tool_call_start` для каждого, затем дельты по индексу.
- **`argument` — always string:** JSON-фрагмент, может прийти частично. Адаптер накапливает и парсит только при `tool_call_end`.
- **Empty `argument`:** `bash` без аргументов (модель ошиблась) — пустой JSON `{}` или просто `""`. Парсинг: если пусто → `{}`.
- **Malformed JSON:** если после `tool_call_end` JSON не парсится — `StreamEvent(kind="stop", stop_reason="error", error=LLMError(kind="invalid_tool_input"))`. agent_loop решает, retry или показать пользователю.

### 4.6. Retry-стратегия

| HTTP status | Retry? | Backoff |
|---|---|---|
| 429 (rate limit) | ✅ до 3 раз | exponential 1s, 2s, 4s + jitter |
| 500, 502, 503 | ✅ до 3 раз | exponential 1s, 2s, 4s |
| 504 (gateway timeout) | ✅ до 2 раз | linear 2s, 4s |
| 400 (bad request) | ❌ | — |
| 401 (auth) | ❌ | — |
| 403 (forbidden) | ❌ | — |
| 404 (model not found) | ❌ | — |
| 408 (request timeout) | ✅ 1 раз | 5s |
| Network error | ✅ до 3 раз | exponential 1s, 2s, 4s |

Retry происходит прозрачно для consumer-а — он видит задержку в stream, но никаких error-событий. Если все retry исчерпаны — `StreamEvent(kind="stop", stop_reason="error", error=LLMError(kind="retry_exhausted"))`.

### 4.7. Prompt-cache (v2)

OpenAI auto-caches system prompt при определённой длине. Явного контроля нет. Для Anthropic — explicit `cache_control` breakpoints. MVP не использует явно — полагается на auto-cache. v2 добавит явные маркеры.

## 5. Anthropic адаптер

### 5.1. Особенности API

Anthropic имеет отдельный API-формат:
- `system` передаётся отдельно от `messages`
- `tools` имеют другой формат (без `function` wrapper)
- `tool_use` и `tool_result` — отдельные content-block types
- Поддержка `cache_control` для явных кэш-точек
- Streaming через SSE, но с другим набором событий

### 5.2. Конвертация

| Канонический | Anthropic API | Заметки |
|---|---|---|
| `LLMRequest.system` | `system: [{type:"text", text:..., cache_control:{type:"ephemeral"}}]` | Anthropic требует list of blocks |
| `LLMRequest.system_cacheable_prefix` | `cache_control` breakpoint на последнем block | Anthropic кэширует до breakpoint |
| `Message{role:"user", content:"text"}` | `{role:"user", content:[{type:"text", text:"text"}]}` | Anthropic требует block-list |
| `Message{role:"assistant", content:[text, tool_call]}` | `{role:"assistant", content:[{type:"text", text:...}, {type:"tool_use", id, name, input}]}` | Каждая часть — отдельный block |
| `Message{role:"tool", content:[tool_result]}` | `{role:"user", content:[{type:"tool_result", tool_use_id, content, is_error}]}` | ВАЖНО: tool_result в Anthropic — это user-message с особым блоком! |
| `ToolSpec` | `tools: [{name, description, input_schema}]` | Прямое соответствие |

### 5.3. Stream-парсинг

Anthropic SSE имеет другие event-types:

```
event: message_start
  → (internal: init buffer)

event: content_block_start
  data: {index:0, content_block:{type:"text", text:""}}
  → StreamEvent(kind="assistant_token", text="")  # инициализация

event: content_block_delta
  data: {index:0, delta:{type:"text_delta", text:"Hello"}}
  → StreamEvent(kind="assistant_token", text="Hello")

event: content_block_start
  data: {index:1, content_block:{type:"tool_use", id:"toolu_abc", name:"bash", input:{}}}
  → StreamEvent(kind="tool_call_start", tool_call_id="toolu_abc", tool_name="bash")

event: content_block_delta
  data: {index:1, delta:{type:"input_json_delta", partial_json:"{\"com"}}
  → StreamEvent(kind="tool_call_delta", tool_call_id="toolu_abc", tool_input_delta="{\"com")

event: content_block_stop
  data: {index:1}
  → StreamEvent(kind="tool_call_end", tool_call_id="toolu_abc")

event: message_delta
  data: {delta:{stop_reason:"tool_use"}}
  → (internal: запоминаем stop_reason)

event: message_stop
  → StreamEvent(kind="stop", stop_reason="tool_use")

event: ping (heartbeat)
  → игнорируется
```

### 5.4. Edge-cases Anthropic

- **Tool input как partial JSON:** Anthropic стримит `input` как partial JSON-строку (через `input_json_delta`), не как дельты ключей. Адаптер накапливает, парсит только на `content_block_stop`.
- **Tool use в конце ответа:** Anthropic часто сначала пишет text, потом tool_use. Это значит: stream-события чередуются: `assistant_token*`, `tool_call_start`, `tool_call_delta*`, `tool_call_end`, `stop`. Consumer должен корректно переключаться между режимами.
- **Multiple tool_use blocks:** модель может вернуть несколько `tool_use` в одном ответе (parallel tool calling). Каждый — отдельный `content_block` со своим `index`.
- **Empty text:** Anthropic иногда шлёт `content_block_start` с пустым `text:""`, потом сразу `content_block_stop`. Это норма, не баг.
- **`stop_reason="max_tokens"`:** означает обрыв в середине tool-call. Адаптер должен: финализировать незавершённый `tool_call_end` с `partial=True`, отдать `stop` с `stop_reason="max_tokens"`. agent_loop решает, продолжать или показать пользователю.
- **`is_error: true` в tool_result:** Anthropic передаёт через `tool_result.is_error` флаг. Канонический формат — `tool_result.is_error`. Прямое соответствие.

### 5.5. Prompt-cache

Anthropic поддерживает явные cache-control breakpoints:

```python
system: [
    {"type": "text", "text": "<identity>", "cache_control": {"type": "ephemeral"}},
    {"type": "text", "text": "<tools_schema>"},
    {
        "type": "text",
        "text": "<user_prefs>",
        "cache_control": {"type": "ephemeral"},
    },  # breakpoint here
    {"type": "text", "text": "<dynamic_context>"},  # не кэшируется
]
```

Брейкпоинт означает: всё, что до него (включая этот блок), кэшируется на 5 минут. Anthropic возвращает `cache_read_tokens` и `cache_write_tokens` в `usage`.

**Стратегия для OryaAgent:**
- `cacheable_prefix` → блок с `cache_control` в конце
- `dynamic_suffix` → отдельный блок без cache_control
- Если cacheable_prefix изменился (новый tool добавлен) — cache invalidates, полный `cache_write`. Это нормально.

Cache экономия: 90% на стабильных сессиях, 50% на умеренно меняющихся.

### 5.6. Pricing

Anthropic pricing per million tokens (актуальные цены — в `pricing/anthropic.json`, обновляется автоматически):

```python
def estimate_cost(self, usage: Usage) -> Decimal:
    rates = self._rates_for_model(self.model)
    cost = (
        usage.input_tokens * rates.input_per_1m
        + usage.output_tokens * rates.output_per_1m
        + usage.cache_read_tokens * rates.cache_read_per_1m
        + usage.cache_write_tokens * rates.cache_write_per_1m
    ) / 1_000_000
    return cost.quantize(Decimal("0.000001"))
```

`cache_write` стоит дороже обычного `input` (1.25x), но окупается на 2-м запросе: `cache_read` дешевле в 10x.

## 6. Ollama — special case

Ollama — локальный сервер, не требует API-key, не требует internet. Это делает его идеальным для:
- Разработки без cost
- Private inference (без data leakage)
- CI/тестирования

### 6.1. Особенности

- `base_url: http://localhost:11434/v1` (OpenAI-compat endpoint) или `/api/chat` (native)
- MVP использует OpenAI-compat endpoint — один адаптер покрывает Ollama
- `api_key` — любая строка (Ollama игнорирует, но требует header)
- Models list: `GET /api/tags` → возвращает установленные модели

### 6.2. Discovery

При запуске `orya` — probe `localhost:11434`. Если отвечает — добавляет все установленные модели в registry. Пользователь может явно указать модель:

```yaml
providers:
  ollama:
    base_url: http://localhost:11434/v1
    api_key: dummy
    model: llama3.1:70b
```

### 6.3. Ограничения

- Нет streaming partial tool-input у некоторых моделей (llama3.1, qwen2.5 — есть, другие могут не поддерживать). Адаптер эмулирует: ждёт полный ответ, отдаёт одним `tool_call_start` + `tool_call_end`.
- Cost всегда 0 (local).
- Token-count: через `tiktoken` (approximation, Ollama не возвращает точный).

## 7. Локальный провайдер: LM Studio

Аналог Ollama, но с GUI. API: OpenAI-compat на `http://localhost:1234/v1`. Поддерживается автоматически через OpenAI-compat адаптер с правильным `base_url`.

## 8. Token-counting

### 8.1. Стратегии

```python
class TokenCounter(Protocol):
    def count(self, text: str) -> int: ...
    def count_messages(self, messages: list[Message]) -> int: ...
```

Конкретные имплементации:
- **`TiktokenCounter`** — для OpenAI-compat (gpt-4o, gpt-3.5-turbo, etc.). Использует `tiktoken.encoding_for_model(model)`.
- **`AnthropicCounter`** — для Anthropic. Использует `anthropic.count_tokens()` API (точный, но требует network call). Для offline — approximation `chars/4`.
- **`ApproximateCounter`** — fallback. `chars/4` для English, `chars/2` для CJK (грубо, но допустимо).

### 8.2. Когда считать

- **Перед LLM-вызовом:** `context_manager` считает tokens для window. Approximation допустим (±10%).
- **После LLM-вызова:** `usage.input_tokens` от провайдера — точный. Сохраняется в session-log для observability.
- **Для UI:** «context: 12.5k/200k tokens» — approximation, обновляется после каждого LLM-call по реальному `usage`.

## 9. Cost tracking

### 9.1. Pricing registry

`src/orya/llm/pricing/` содержит JSON-файлы с актуальными ценами:
- `openai.json`
- `anthropic.json`
- `openrouter.json` (аггрегирует чужие цены + markup)
- `together.json`
- etc.

Формат:
```json
{
  "gpt-4o": {
    "input_per_1m": 2.50,
    "output_per_1m": 10.00,
    "cache_read_per_1m": 1.25,
    "cache_write_per_1m": 2.50
  },
  "gpt-4o-mini": { ... }
}
```

Обновление — через `orya pricing update` (тянет из `https://github.com/orya-agent/pricing-db`). Авто-check при запуске (с cached-результатом на 24 часа).

### 9.2. Session budget

```python
class SessionBudget:
    spent_usd: Decimal = 0
    limit_usd: Decimal | None = None  # из config
    
    def add(self, cost: Decimal):
        self.spent_usd += cost
        if self.limit_usd and self.spent_usd > self.limit_usd:
            raise BudgetExceeded(self.spent_usd, self.limit_usd)
```

При `BudgetExceeded` — agent_loop останавливается с `Stop(reason="budget_exceeded")`. Пользователь видит модалку с подтверждением или может изменить лимит через `/budget`.

## 10. Error handling

### 10.1. Error taxonomy

```python
class LLMError(BaseModel):
    kind: Literal[
        "auth_failed",  # 401/403
        "rate_limited",  # 429
        "server_error",  # 5xx
        "network_error",  # timeout, connection refused
        "model_not_found",  # 404
        "context_overflow",  # input too large
        "invalid_request",  # 400 (other than above)
        "invalid_tool_input",  # malformed JSON в tool_call
        "content_filtered",  # safety filter triggered
        "retry_exhausted",  # все retry исчерпаны
        "unknown",
    ]
    message: str
    provider: str
    retryable: bool
    retry_after_ms: int | None = None
    raw: dict | None = None
```

### 10.2. Mapping HTTP → LLMError

| HTTP | LLMError.kind | retryable |
|---|---|---|
| 401 | auth_failed | False |
| 403 | auth_failed | False |
| 404 | model_not_found | False |
| 400 + "context_length" | context_overflow | False |
| 400 + "content_policy" | content_filtered | False |
| 400 (other) | invalid_request | False |
| 429 | rate_limited | True |
| 500, 502, 503 | server_error | True |
| 504 | server_error | True |
| timeout | network_error | True |
| connection refused | network_error | True |

### 10.3. Behavior в agent_loop

| Error kind | Behavior |
|---|---|
| `auth_failed` | `Stop(reason="error")`, TUI показывает «проверьте API-key» |
| `rate_limited` | Internal retry, если исчерпан — `Stop`, TUI «подождите N секунд» |
| `context_overflow` | `Stop`, agent_loop предлагает `/compact` (v2) или `/clear` |
| `invalid_tool_input` | `Stop`, TUI показывает malformed tool-call для дебага |
| `content_filtered` | `Stop`, TUI показывает причину |
| `network_error` (transient) | Internal retry, потом `Stop` |
| `retry_exhausted` | `Stop` с «провайдер не отвечает, попробуйте через минуту» |
| `budget_exceeded` (не из LLMError) | `Stop`, TUI модалка с лимитом |

## 11. Observability hooks

Каждый LLM-call логирует:

```json
{
  "ts": "2026-10-20T14:32:01Z",
  "session_id": "abc123",
  "provider": "anthropic",
  "model": "claude-3-5-sonnet-20241022",
  "input_tokens": 12500,
  "output_tokens": 842,
  "cache_read_tokens": 11000,
  "cache_write_tokens": 0,
  "cost_usd": 0.015923,
  "duration_ms": 4231,
  "stop_reason": "tool_use",
  "tool_calls_count": 2,
  "retry_count": 0,
  "outcome": "success"
}
```

Лог пишется в `~/.orya/logs/llm.jsonl`. На enterprise — отгрузка в OTel-collector.

Метрики (см. [07-observability-spec.md](07-observability-spec.md)):
- `orya_llm_tokens_total{provider, model, kind=input|output|cache_read|cache_write}`
- `orya_llm_cost_usd_total{provider, model}`
- `orya_llm_request_duration_seconds{provider, model, outcome}`
- `orya_llm_errors_total{provider, error_kind}`

## 12. Тестирование адаптеров

### 12.1. VCR-cassettes

Все тесты адаптеров используют запись HTTP-ответов (через `vcrpy` или `pytest-vcr`). Никаких live-API-call в CI.

Cassettes хранятся в `tests/fixtures/cassettes/`:
- `anthropic_claude35_text_only.yaml`
- `anthropic_claude35_tool_use.yaml`
- `anthropic_claude35_multiple_tools.yaml`
- `openai_gpt4o_text_only.yaml`
- `openai_gpt4o_tool_call.yaml`
- `openai_429_rate_limit.yaml`
- `openai_500_server_error.yaml`
- etc.

### 12.2. FakeLLMProvider

Для unit-тестов `agent_loop` — `FakeLLMProvider` в `tests/fixtures/llm.py`:

```python
class FakeLLMProvider:
    def __init__(self, responses: list[LLMResponse]):
        self._responses = responses
        self.calls = []  # для assert-ов
    
    async def complete(self, req: LLMRequest) -> AsyncIterable[StreamEvent]:
        self.calls.append(req)
        resp = self._responses.pop(0)
        # эмулирует stream-события из resp
        ...
```

### 12.3. Smoke-тесты с live API

Опциональные smoke-тесты (`tests/smoke/`) с реальными API-вызовами. Запускаются вручную `pytest tests/smoke/ --live-api`. Требуют API-key в env. Запрещены в CI без явного opt-in.

## 13. Открытые вопросы

1. **Streaming images (v2)?** OpenAI vision streaming — частичная поддержка. Anthropic — нет стриминга image-content. Для MVP — images в input игнорируются (только text).

2. **Function calling для Ollama?** Зависит от модели. Llama 3.1, Qwen 2.5 — поддерживают. Старые модели — нет. Адаптер должен детектить по `/api/show` и фолбэчить на prompt-engineering (text-based tool calling). v2.

3. **Provider failover?** Если основной провайдер недоступен — переход на backup (например, OpenAI → Anthropic). Это меняет prompt-format и tool-call-семантику, потенциально ломает session. MVP: нет failover, `Stop(reason="error")`. v2: опциональный failover с пользовательским подтверждением.

4. **Prompt-cache invalidation детект?** Если cache_hit=0 на стабильных данных — это сигнал, что что-то меняется в system prompt (например, dynamic-секция попала в cacheable). v2: alerting на low cache-hit ratio.

---

**Следующие шаги:**

1. Зафиксировать pricing registry обновления (cron? on-startup?)
2. Реализовать Phase 0 — каркас LLMProvider + FakeLLM для тестов
3. Реализовать Phase 1 — OpenAI-compat адаптер с VCR-cassettes
4. Реализовать Anthropic адаптер с cache_control
5. Документировать pricing update strategy
