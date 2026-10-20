# Спецификация формата сессий

**Документ:** 03-session-format
**Дата:** 20 октября 2026
**Статус:** Draft v0.1
**Связанные документы:** [01-module-contracts.md](01-module-contracts.md), [ADR-003](../adr/ADR-003-event-sourced-sessions.md)

---

## 0. Назначение

Сессия — это append-only поток событий. Лог — единственный источник истины: всё, что видела модель и пользователь, восстанавливается из лога. Этот документ фиксирует:
- Структуру событий и их типов
- Формат хранения (JSONL) и миграции между версиями
- Алгоритмы проекции лога в сообщения для LLM
- Стратегии восстановления после crash и partial-write
- Политику retention и vacuum

Без зафиксированного формата миграции между версиями становятся невозможными, а crash-recovery — ненадёжной.

## 1. Принципы проектирования

### 1.1. Append-only

События не изменяются и не удаляются. Любая «правка» — новое событие с маркером `compensation_for: <seq>`. Это позволяет:
- Восстанавливать любое прошлое состояние
- Аудировать все действия (включая отменённые)
- Делать snapshot-ы для fast-replay

### 1.2. Model-visible means logged

Если что-то попало в `LLMRequest.messages` — оно должно быть в логе. Если в логе есть событие, не попавшее в messages — это либо `internal` event, либо projection-баг. Инвариант проверяется тестами.

### 1.3. Versioned schema

Каждое событие имеет `schema_version`. Старые события читаются новыми версиями OryaAgent через миграции. Это позволяет обновлять OryaAgent без потери сессий.

### 1.4. Single writer per session

Только `agent_loop` пишет в session-log. Параллельные сессии — отдельные файлы. Это упрощает concurrency-рассуждения и atomicity.

## 2. Хранение

### 2.1. Каталоги

```
~/.orya/
├── sessions/
│   ├── <session_id>.jsonl              # активная сессия
│   ├── <session_id>.jsonl.backup       # предыдущая версия после vacuum
│   ├── <session_id>.meta.json           # метаданные (для list-views)
│   └── archive/
│       └── <session_id>.jsonl.zst      # архив после 90 дней неактивности
├── sessions.index                       # индекс для быстрого list
└── vacuum.lock                          # блокировка для vacuum-операций
```

### 2.2. Session ID

`<session_id>` — формат `YYYYMMDD-HHMMSS-<short_uuid>`:
- `20261020-143201-a3f2b9c1`
- Сортируется лексикографически = по времени
- `short_uuid` — первые 8 символов `uuid4`, без дефисов

### 2.3. Файл сессии

JSONL-файл, одна строка на событие:

```
{"seq":1,"ts":"2026-10-20T14:32:01.123456Z","schema_version":"1.0","kind":"session_started","session_id":"20261020-143201-a3f2b9c1","payload":{...}}
{"seq":2,"ts":"2026-10-20T14:32:02.789012Z","schema_version":"1.0","kind":"user_message","payload":{"content":"что в README?"}}
{"seq":3,"ts":"2026-10-20T14:32:04.456789Z","schema_version":"1.0","kind":"assistant_message","payload":{"content":"...","tool_calls":[...]}}
...
```

Каждая строка — валидный JSON, заканчивается `\n`. Partial-write последней строки (без trailing `\n`) — детектится при load и отбрасывается с warn-логом.

### 2.4. Atomicity

- **Append:** через `aiofiles.open(..., 'a')` + `await f.write(line + '\n')` + `await f.flush()`. На Linux — это атомарно на уровне OS, если line <PIPE_BUF (4096 байт на Linux). Для больших событий (например, длинный tool-result) — append может быть неатомарным, но это допустимо: детектится при load и отбрасывается partial.
- **Rotation:** при 500 MB — rotate: переименование в `.1`, создание нового. Old-file архивируется в `.zst`.
- **Crash recovery:** при load — read line-by-line, если последняя строка не парсится как JSON — отбросить, записать warn.

### 2.5. Metadata-файл

`<session_id>.meta.json`:

```json
{
  "session_id": "20261020-143201-a3f2b9c1",
  "created_at": "2026-10-20T14:32:01.123456Z",
  "last_activity_at": "2026-10-20T15:14:32.456789Z",
  "title": "что в README?",                       // первые 60 символов первого user-message
  "provider": "anthropic",
  "model": "claude-3-5-sonnet-20241022",
  "events_count": 47,
  "size_bytes": 145823,
  "schema_version": "1.0",
  "tags": ["work", "experiment-3"],                // пользовательские теги
  "archived": false
}
```

Metadata обновляется при каждом append (не при каждом событии — батчем раз в 30 секунд или при закрытии сессии). Если metadata-файл отсутствует — регенерируется из JSONL при первом обращении.

### 2.6. Индекс

`sessions.index` — TSV-файл для быстрого list:

```
session_id                created_at                       title                       last_activity                    events  size
20261020-143201-a3f2b9c1  2026-10-20T14:32:01.123456Z     что в README?              2026-10-20T15:14:32.456789Z     47      145823
20261019-091532-b8d4e1f2  2026-10-19T09:15:32.111111Z     refactor auth module       2026-10-19T11:42:01.222222Z     124     892111
```

Индекс регенерируется при `orya sessions list`. Опционально — кэшируется в памяти процесса.

## 3. Типы событий

### 3.1. Taxonomy

```python
SessionEvent = Annotated[
    Union[
        SessionStarted,
        SessionResumed,
        UserMessage,
        AssistantMessage,
        ToolCall,
        ToolResult,
        PermissionDecision,
        Error,
        CompactionSummary,  # v2
        SessionAborted,
        SessionClosed,
    ],
    Field(discriminator="kind"),
]
```

### 3.2. SessionStarted

Первое событие в новой сессии. Создаётся при `orya` без `--resume`.

```python
class SessionStarted(BaseModel):
    kind: Literal["session_started"] = "session_started"
    session_id: str
    schema_version: str  # "1.0"
    orya_version: str  # "0.1.0"
    provider: str  # "anthropic"
    model: str  # "claude-3-5-sonnet-20241022"
    working_dir: str  # cwd на момент старта
    platform: str  # "linux-x86_64"
    config_hash: str  # hash от ~/.orya/config.yml для аудита
```

### 3.3. SessionResumed

При `orya --resume <id>`. Не запускает новую сессию, а продолжает старую.

```python
class SessionResumed(BaseModel):
    kind: Literal["session_resumed"] = "session_resumed"
    session_id: str
    resumed_at: datetime
    resumed_from_seq: int  # seq последнего валидного события
    dropped_partial: bool  # была ли partial-write строка отброшена
    schema_version_migrated: str | None  # "0.9" → "1.0", если была миграция
```

### 3.4. UserMessage

```python
class UserMessage(BaseModel):
    kind: Literal["user_message"] = "user_message"
    content: str  # текст пользовательского ввода
    attachments: list[Attachment] = []  # файлы, drag-n-drop (v2)
    source: Literal["repl", "piped", "slash_command"] = "repl"


class Attachment(BaseModel):
    path: str
    kind: Literal["file", "image", "url"]
    sha256: str  # для file — хэш
    size_bytes: int
```

### 3.5. AssistantMessage

Сообщение от LLM. Может содержать text и/или tool_calls.

```python
class AssistantMessage(BaseModel):
    kind: Literal["assistant_message"] = "assistant_message"
    content: list[ContentBlock]  # text + tool_call блоки
    stop_reason: str  # "end_turn", "tool_use", "max_tokens"
    usage: UsageRecord  # токены и стоимость
    llm_response_id: str | None  # ID ответа от провайдера (для дебага)
    duration_ms: int  # время от request до full response


class UsageRecord(BaseModel):
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    cost_usd: Decimal
    provider: str
    model: str
```

### 3.6. ToolCall

Запись о вызове инструмента. Это лог-запись, не сам вызов. Реальный вызов происходит синхронно с созданием этого события.

```python
class ToolCall(BaseModel):
    kind: Literal["tool_call"] = "tool_call"
    call_id: str  # уникальный ID (генерирует agent_loop)
    tool_name: str  # "bash", "read", etc.
    input: dict[str, Any]  # Pydantic-валидированный input
    input_hash: str  # SHA256 от canonical JSON
    source: Literal[
        "llm", "user"
    ]  # кто инициировал (LLM через tool_call или пользователь через slash)
    approved_by: (
        str | None
    )  # "user" если был ask-mode, "auto" если allow-list, None если auto-mode
```

### 3.7. ToolResult

```python
class ToolResult(BaseModel):
    kind: Literal["tool_result"] = "tool_result"
    call_id: str  # ссылка на ToolCall
    outcome: Literal["success", "error", "denied", "aborted", "timeout"]
    content: str  # результат (stdout для bash, file content для read, etc.)
    content_truncated: bool  # если True — был превышен лимит
    content_original_size: int  # размер до truncation
    metadata: dict[str, Any]  # tool-specific: exit_code, files_changed, etc.
    error_kind: str | None  # если outcome=error: "invalid_input", "io_error", etc.
    duration_ms: int
    compensation_for: int | None  # если это повтор после compensation — seq оригинала
```

### 3.8. PermissionDecision

```python
class PermissionDecision(BaseModel):
    kind: Literal["permission_decision"] = "permission_decision"
    call_id: str  # ссылка на ToolCall
    decision: Literal["allow", "deny", "ask"]
    decided_by: Literal["allow_list", "auto_mode", "user"]
    user_response: Literal["yes", "no", "always_for_tool", "always_for_pattern"] | None
    rule_applied: str | None  # если allow_list — pattern, который сматчился
    duration_ms: int  # сколько пользователь думал
```

### 3.9. Error

Любая ошибка в цикле. Восстанавливаемая (LLM timeout) — логируется, цикл продолжается. Критичная (session write failed) — цикл останавливается.

```python
class Error(BaseModel):
    kind: Literal["error"] = "error"
    error_kind: str  # "llm_timeout", "tool_io_error", "permission_denied", etc.
    message: str
    recoverable: bool
    context: dict[str, Any]  # tool_name, call_id, etc. — для дебага
    stack_trace: str | None  # для unexpected exceptions
```

### 3.10. CompactionSummary (v2)

Когда `context_manager` решает урезать окно — создаётся summary-событие. LLM получает этот summary вместо удалённых сообщений.

```python
class CompactionSummary(BaseModel):
    kind: Literal["compaction_summary"] = "compaction_summary"
    summary: str  # LLM-сгенерированный summary
    compacted_events: list[int]  # seq-номера уплотнённых событий
    tokens_before: int
    tokens_after: int
    compaction_strategy: Literal["simple_truncate", "llm_summarize"]
```

### 3.11. SessionAborted

При Ctrl+C или SIGTERM во время выполнения.

```python
class SessionAborted(BaseModel):
    kind: Literal["session_aborted"] = "session_aborted"
    aborted_at: datetime
    aborted_at_seq: int  # seq последнего завершённого события
    pending_tool_calls: list[str]  # call_id-ы незавершённых
    reason: Literal["user_interrupt", "signal", "crash"]
```

### 3.12. SessionClosed

При `/exit` или корректном завершении.

```python
class SessionClosed(BaseModel):
    kind: Literal["session_closed"] = "session_closed"
    closed_at: datetime
    total_events: int
    total_cost_usd: Decimal
    duration_seconds: int
```

## 4. Схема события (общая)

Каждое событие имеет общий envelope:

```python
class EventEnvelope(BaseModel):
    seq: int  # монотонно растущий, с gaps
    ts: datetime  # ISO 8601 UTC с микросекундами
    schema_version: str  # "1.0"
    kind: str  # discriminator
    session_id: str  # для cross-file queries
    payload: SessionEvent  # конкретный тип
```

В JSONL хранится как плоский объект (не вложенный `payload`):

```json
{"seq":1,"ts":"...","schema_version":"1.0","kind":"session_started","session_id":"...","or ya_version":"0.1.0","provider":"anthropic","model":"...","working_dir":"...","platform":"...","config_hash":"..."}
```

Все поля `payload` поднимаются на верхний уровень. Это упрощает grep/jq-фильтрацию.

## 5. Версионирование и миграции

### 5.1. Schema versions

- `1.0` — MVP-схема (этот документ)
- `1.1`, `1.2`, ... — обратно-совместимые расширения (новые optional поля, новые kind-ы)
- `2.0` — breaking change (изменение существующих полей, удаление kind-ов)

### 5.2. Migration framework

При загрузке старой сессии OryaAgent применяет миграции:

```python
MIGRATIONS = [
    Migration(from_version="0.9", to_version="1.0", migrator=migrate_0_9_to_1_0),
    Migration(from_version="1.0", to_version="1.1", migrator=migrate_1_0_to_1_1),
    # ...
]


def migrate(events: list[dict], current_version: str) -> tuple[list[dict], str]:
    for m in MIGRATIONS:
        if m.from_version == current_version:
            events = m.migrator(events)
            current_version = m.to_version
    return events, current_version
```

Миграции:
- **Read-only** — не модифицируют исходный файл, создают `.migrated.jsonl` рядом
- **Idempotent** — повторная миграция не должна что-то ломать
- **Logged** — каждое преобразование события логируется в audit-log

### 5.3. Migration testing

Каждая миграция имеет:
- Golden-test: известный input → ожидаемый output
- Property-test: для случайных событий старой версии — миграция не падает
- Round-trip-test: миграция туда-обратно (где возможно) сохраняет данные

## 6. Projection layer

`SessionLog.to_messages()` — возвращает `list[Message]` для LLM. Это не тупое «выдай все assistant + user» — это thoughtful projection.

### 6.1. Алгоритм projection

```python
def to_messages(events: Iterable[SessionEvent]) -> list[Message]:
    messages = []
    pending_tool_results = {}  # call_id → result

    for event in events:
        match event:
            case UserMessage(content=c):
                messages.append(Message(role="user", content=c))

            case AssistantMessage(content=blocks):
                # Конвертируем blocks в Message
                msg_content = []
                for block in blocks:
                    if block.kind == "text":
                        msg_content.append(TextBlock(text=block.text))
                    elif block.kind == "tool_call":
                        msg_content.append(
                            ToolCallBlock(
                                id=block.id, name=block.tool_name, input=block.input
                            )
                        )
                messages.append(Message(role="assistant", content=msg_content))

            case ToolResult(call_id=cid, content=c, outcome=o):
                # Накапливаем, отправляем как отдельное Message{role:"tool"}
                messages.append(
                    Message(
                        role="tool",
                        content=[
                            ToolResultBlock(
                                tool_call_id=cid, content=c, is_error=(o != "success")
                            )
                        ],
                    )
                )

            case Error(error_kind="permission_denied", context={"call_id": cid}):
                # Пропускаем — permission-denied tool не должен попасть в LLM context
                # (он не был реально выполнен)
                pass

            case (
                SessionAborted() | SessionClosed() | SessionStarted() | SessionResumed()
            ):
                # Системные события — не в LLM context
                pass

            case CompactionSummary(summary=s):
                # Заменяет все предыдущие сообщения одним summary
                messages = [
                    Message(role="user", content=f"[Previous context summary]\n{s}")
                ]

    return messages
```

### 6.2. Фильтрация

События, которые **не попадают** в projection:
- `SessionStarted`, `SessionResumed`, `SessionAborted`, `SessionClosed` — мета-события
- `PermissionDecision` — это meta-info, не для LLM
- `Error` с `recoverable=True` — LLM не должен видеть, что был timeout и retry
- `ToolCall` без соответствующего `ToolResult` — был отменён, не попал в execution

События, которые **попадают** в projection:
- `UserMessage`
- `AssistantMessage` (включая tool_calls)
- `ToolResult` (как Message{role:"tool"})
- `Error` с `recoverable=False` (например, `tool_io_error`) — LLM должен знать, что tool упал
- `CompactionSummary` — заменяет предыдущие сообщения

### 6.3. Дедупликация

При retry (`compensation_for`):
- Если есть `ToolResult{compensation_for: 5}` — в projection попадает только этот result, не оригинальный seq=5.

Реализация: при обработке `ToolResult` проверяем `compensation_for`. Если есть — оригинал исключается из messages.

### 6.4. Truncation

Длинные `ToolResult.content` урезаются при projection:
- Строки > 100 → `первые 50 + "\n... [N lines truncated] ...\n" + последние 50`
- Размер > 50 KB → `первые 25 KB + "\n... [truncated, original_size=X KB] ...\n" + последние 25 KB`

Truncation выполняется **в projection**, не в логе. Лог содержит полный результат; LLM видит урезанный.

## 7. Recovery и crash-resilience

### 7.1. Partial-write detection

При load:

```python
async def load(path: Path) -> list[SessionEvent]:
    events = []
    async with aiofiles.open(path, "r") as f:
        async for line_no, line in enumerate(f, 1):
            line = line.rstrip("\n")
            if not line:
                continue
            try:
                data = json.loads(line)
                event = parse_event(data)
                events.append(event)
            except (json.JSONDecodeError, ValidationError) as e:
                if line_no == last_line_no:
                    logger.warning(f"discarding partial write at line {line_no}: {e}")
                    break  # последняя строка — partial, отбрасываем
                else:
                    raise CorruptedSessionError(f"line {line_no}: {e}")
    return events
```

Partial-write может быть только в **последней** строке. Если partial в середине — это corruption, поднимаем exception.

### 7.2. Crash recovery flow

```
1. Пользователь запускает `orya` (без --resume)
2. App: проверяет ~/.orya/sessions/ на наличие "incomplete" сессий
   (по отсутствию SessionClosed-события)
3. Если есть — спрашивает: "Resume session X started at Y? [Y/n]"
4. Если Y: orya --resume X
5. Если N: создаёт новую сессию, оставляет старую в "incomplete" статусе
```

### 7.3. Atomic operations

| Операция | Atomicity |
|---|---|
| `session.append(event)` | Single JSON-line write + flush. Atomic на OS level (line < 4KB) |
| `session.save()` (sync to disk) | fsync(fd). Гарантирует persistence до crash |
| `session.rotate()` | rename(old, old.1) + open(new, 'w'). Atomic rename |
| `session.archive()` | compress to .zst + unlink original. Не atomic — partial archive оставляет both |

## 8. Vacuum и retention

### 8.1. Vacuum

Periodic cleanup старых сессий:

- Сессии > 90 дней без активности → архивируются (compress to `.zst`)
- Архивы > 1 года → удаляются (если нет explicit pin)
- Vacuum запускается автоматически при `orya` start, если последний vacuum был > 7 дней назад

```python
def vacuum(sessions_dir: Path):
    cutoff_archive = datetime.utcnow() - timedelta(days=90)
    cutoff_delete = datetime.utcnow() - timedelta(days=365)
    
    for meta in sessions_dir.glob("*.meta.json"):
        s = SessionMeta.parse_file(meta)
        if s.archived:
            continue
        if s.last_activity_at < cutoff_archive:
            archive_session(s.session_id)
        elif s.last_activity_at < cutoff_delete and not s.pinned:
            delete_session(s.session_id)
```

Vacuum логирует все операции в `~/.orya/logs/vacuum.jsonl`.

### 8.2. Pinning

Пользователь может «закрепить» сессию:
```bash
orya sessions pin <session_id>
```

Pinned-сессии не удаляются и не архивируются. Используется для важных сессий (debug, proof-of-work, etc.).

### 8.3. Manual export

```bash
orya sessions export <session_id> --format=markdown > session.md
orya sessions export <session_id> --format=json > session.json
```

Экспорт — снимок сессии в human-readable или machine-readable формате. Для архивации вне `~/.orya/`, для шеринга, для баг-репортов (с sanitization secrets).

## 9. Конкурентный доступ

### 9.1. Single-writer invariant

Только один процесс OryaAgent может писать в сессию. Если два процесса пытаются открыть одну сессию на запись — второй получает `SessionLockError`.

Реализация через `fcntl.flock` (Linux/macOS) или `msvcrt.locking` (Windows):

```python
async def acquire_session_lock(path: Path):
    f = await aiofiles.open(path.with_suffix(".lock"), "w")
    try:
        fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        raise SessionLockError(f"Session {path.stem} is locked by another process")
    return f
```

### 9.2. Concurrent readers

Multiple процессы могут **читать** сессию (например, `orya sessions show <id>`), пока другой процесс пишет. Это безопасно — partial-line детектится и отбрасывается.

### 9.3. Cross-session parallelism

Каждая сессия — отдельный файл. Пользователь может запустить `orya` в двух терминалах с разными сессиями — это нормально, никакой блокировки.

## 10. Observability

### 10.1. Session metrics

Каждая сессия имеет computed метрики (в `.meta.json`):

```json
{
  "metrics": {
    "duration_seconds": 2456,
    "events_count": 47,
    "user_messages_count": 8,
    "assistant_messages_count": 7,
    "tool_calls_count": 23,
    "tool_calls_by_name": {"read": 12, "bash": 8, "edit": 3},
    "errors_count": 2,
    "total_cost_usd": 0.142,
    "total_tokens": {"input": 145000, "output": 8500, "cache_read": 120000}
  }
}
```

### 10.2. Aggregated metrics

`~/.orya/metrics.jsonl` — append-only лог с daily aggregates:

```json
{"date":"2026-10-20","sessions_count":3,"total_cost_usd":0.45,"total_tokens":...,"tool_calls":{...}}
```

Используется для `orya stats` и dashboard в TUI.

## 11. Безопасность

### 11.1. Sensitive data в логах

Tool results могут содержать sensitive data (например, `read` с `.env`). По умолчанию это логируется. Решение для MVP:

- `sensitive_patterns` в config (`~/.orya/sensitive.yml`) — regex-паттерны
- При `session.append(ToolResult)` — если content содержит sensitive-pattern — заменяем на `<REDACTED:sensitive>`
- Полный content логируется только если `permissions.allow_sensitive_logging = true` (по умолчанию false)

### 11.2. File permissions

- `~/.orya/sessions/*.jsonl` — `0600` (rw только для owner)
- `~/.orya/sessions/*.meta.json` — `0644` (для list, без sensitive)
- `~/.orya/` — `0700`

### 11.3. Audit log

`~/.orya/audit.jsonl` — отдельный файл, не часть session-log. Логирует:
- Все PermissionDecision-ы (кто, что, когда подтвердил)
- Все sensitive-file access-ы
- Все сессии (start, resume, close)
- Все config changes (через `orya config set`)

Не подлежит vacuum или auto-deletion. На enterprise — отгрузка в SIEM.

## 12. Тестирование

### 12.1. Property-based tests

```python
@given(events=lists(session_event_strategy(), min_size=1, max_size=100))
def test_projection_round_trip(events):
    log = InMemorySessionLog(events)
    messages = log.to_messages()
    # 1. Все assistant_messages имеют соответствующий Message
    # 2. Все tool_results имеют соответствующий Message{role:"tool"}
    # 3. Нет tool_result без предшествующего tool_call
    # 4. Сумма messages <= len(events)
```

### 12.2. Crash simulation

```python
def test_partial_write_recovery():
    log = FileSessionLog("test.jsonl")
    log.append(Event1())
    log.append(Event2())
    
    # Симулируем partial write
    with open("test.jsonl", "a") as f:
        f.write('{"seq":3,"kind":"user_mess')  # обрезано
    
    log2 = FileSessionLog("test.jsonl")
    events = log2.load()
    assert len(events) == 2
    assert log2.dropped_partial == 1
```

### 12.3. Migration tests

Каждая миграция:
- Golden test: fixture в `tests/fixtures/sessions/v0.9.jsonl` → ожидаемый `v1.0.jsonl`
- Property test: для любого валидного v0.9 event — миграция возвращает валидный v1.0 event
- Backward-compat: новая версия OryaAgent читает старые сессии без ошибок

### 12.4. Performance tests

- `test_large_session_load`: 10k событий — load за < 1s
- `test_concurrent_append`: 100 параллельных append-ов — нет lost writes
- `test_projection_large`: 1k сообщений — projection за < 100ms

## 13. Открытые вопросы

1. **Compression на лету?** JSONL легко читается, но раздувается. Zstd-compressed stream (`.jsonl.zst`) — компактнее в 5-10x, но partial-recovery сложнее. MVP: uncompressed; v2 — опциональный compression для archived sessions.

2. **Multi-file sessions?** При 500 MB — rotate на новый файл. Но индекс и projection усложняются. MVP: max 500 MB на сессию, при превышении — принудительный compaction (v2).

3. **Encrypted sessions?** Для enterprise — encryption-at-rest. Текущая модель: file permissions `0600`. v2: optional AES-256 с key в OS keychain.

4. **Cross-device sync?** Сессии в `~/.orya/sessions/` — если синхронизировать через Dropbox/iCloud, могут быть conflicts. MVP: документируем «не синхронизируйте эту папку». v2: per-session lock-file + conflict-resolution UI.

---

**Следующие шаги:**

1. Зафиксировать migration framework API
2. Реализовать `SessionLog` Protocol + `JSONLSessionStore` для MVP
3. Создать VCR-cassettes для тестов миграций
4. Документировать sensitive-data redaction policy в `security-model.md`
