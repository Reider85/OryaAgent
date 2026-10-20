# ADR-003: Append-only лог как источник истины для сессий

**Дата:** 2026-10-20
**Статус:** Accepted
**Decision makers:** core team

---

## Контекст

[`agents-architect.md`](../agents-architect.md), вывод №2: «Событийно-ориентированное хранение — стандарт де-факто. OpenCode (SQLite + Context Epoch), dsh (append-only лог с инвариантом 'model-visible means logged') и MiMoCode (наследие OpenCode + FTS5-память) трактуют сессию как восстанавливаемый поток событий, а не строку сообщений.»

Для OryaAgent нужно было решить: как хранить сессии. Варианты:

1. Сообщения в памяти + JSON-snapshot при сохранении
2. SQLite с таблицей messages (как OpenCode)
3. Append-only JSONL-лог с проекцией в сообщения (как dsh)
4. Гибрид: SQLite для метаданных + JSONL для событий

## Рассмотренные альтернативы

### Вариант A: In-memory + JSON snapshot

- **Плюсы:**
  - Простота имплементации
  - Быстрый доступ к сообщениям (нет I/O)
- **Минусы:**
  - Crash = потеря данных (если snapshot не сделан)
  - Нет истории «что было» — только финальное состояние
  - Невозможно восстановить промежуточные состояния
  - Audit-trail отсутствует

### Вариант B: SQLite с messages table

- **Плюсы:**
  - Структурное хранение, query-able
  - Index-ы для быстрого поиска
  - ACID-транзакции
- **Минусы:**
  - Schema migrations при изменении формата — overhead
  - Binary format — не grep-able, не human-readable
  - Все or none: либо вся сессия в SQLite, либо нет
  - Concurrent access — сложнее, чем append-only file
  - Для сессий <1000 событий — overkill

### Вариант C: Append-only JSONL-лог с projection

- **Плюсы:**
  - Append-only — simple crash recovery (отбросить partial последней строки)
  - Human-readable — можно `jq`-ать, `grep`-ать
  - No schema migrations — новые event types — это просто новый `kind` discriminator
  - Portable — текстовый файл, легко копируется/архивируется
  - Natural audit-trail — всё, что произошло, в логе
  - Event sourcing pattern — separation of storage (events) и view (messages)
- **Минусы:**
  - Нет indexing — projection должен сканировать весь лог
  - При 100k+ событий — slow projection (но для MVP — достаточно)
  - No concurrent writers (single writer per session)
  - Large file size (нет compression в MVP)

### Вариант D: SQLite для metadata + JSONL для events

- **Плюсы:**
  - Best of both: structured metadata (для list/search) + append-only events
  - Indexing на metadata (session title, last activity, tags)
  - JSONL для деталей — portable, human-readable
- **Минусы:**
  - Двойное хранение — риск рассинхронизации
  - Сложнее: два формата, две миграции
  - Для MVP — overengineering

## Решение

**Вариант C: Append-only JSONL-лог с projection в сообщения.**

Дополнительно:
- **JSONL-файл** на сессию: `~/.orya/sessions/<session_id>.jsonl`
- **Meta-файл** рядом: `<session_id>.meta.json` — для fast list/search (без чтения всего лога)
- **Projection layer** в `SessionLog.to_messages()` — конвертирует events в `list[Message]` для LLM
- **Schema versioning** — каждое событие имеет `schema_version`, миграции применяются при load

## Обоснование

1. **Вывод №2 из `agents-architect.md`:** event sourcing — стандарт де-факто для зрелых кодинг-агентов. dsh имеет explicit invariant «model-visible means logged» — это сильная гарантия, которую мы наследуем.

2. **Crash recovery.** Append-only JSONL — простейший формат с сильными crash-recovery гарантиями:
   - Partial-write последней строки → отбрасывается (detected by JSON parse error)
   - Crash mid-write → уже записанные события сохранены
   - Kill -9 → file close гарантирует fsync-ed state

3. **Audit-trail бесплатен.** Каждое событие (user message, assistant response, tool call, tool result, permission decision, error) — в логе. Audit log — отдельный файл с filtered events, но исходный лог — full history. Не нужно ничего специально реализовывать.

4. **Human-readable и tooling-friendly.** JSONL — это текст. `jq`, `grep`, `wc -l`, `head`, `tail` — все стандартные tools работают. Пользователь может открыть файл в редакторе и посмотреть, что произошло.

5. **No schema migrations для adding event types.** Discriminated union через `kind` — добавление нового типа события — это просто новый `kind` в Pydantic-модели. Старые события читаются без изменений.

6. **Event sourcing pattern.** Разделение storage (events) и view (messages) — cleaner architecture. Сообщения для LLM — это projection, не первоисточник. Можно иметь несколько projections (для UI, для LLM, для audit) из одного лога.

7. **Meta-файл покрывает indexing для MVP.** Для `orya sessions list` — читаем meta-файлы, не весь лог. Для `orya sessions show <id>` — читаем лог. Простое разделение hot/cold path.

8. **SQLite — premature optimization для MVP.** На сессиях <10k событий — JSONL projection работает за <100ms. SQLite даёт indexing, но добавляет complexity. Если 100ms станет проблемой — v2 migration в SQLite. Это легко, потому что JSONL сохранится как backup.

## Последствия

**Позитивные:**

- Strong crash recovery гарантии (отброс partial-write последней строки)
- Audit-trail — бесплатный (все events в логе)
- Portable, human-readable формат
- Easy tooling (`jq`, `grep`, etc.)
- Event sourcing separation of concerns
- No schema migrations для добавления event types
- Easy export (cat the file)

**Негативные:**

- Projection должен сканировать весь лог (O(n) на каждое LLM-call)
- Single writer per session — конкурентный доступ невозможен
- File size растет linearly (нет compression в MVP)
- Meta-файл может рассинхронизироваться с лог-файлом (если update упадёт)
- Memory: projection возвращает полный `list[Message]`, не lazy iterator

**Нейтральные:**

- Session ID как timestamp-based sortable — lexicographic sort = chronological
- Schema versioning — каждый event имеет версию, миграции применяются при load
- Vacuum — periodic archive старых сессий (compress to .zst)
- Sensitive data redaction — перед записью в лог

## Реализация (детали)

### Session log structure

```
~/.orya/sessions/
├── 20261020-143201-a3f2b9c1.jsonl       # события
├── 20261020-143201-a3f2b9c1.meta.json   # метаданные для list
├── 20261020-143201-a3f2b9c1.lock         # file lock (single writer)
└── archive/
    └── 20261015-091532-b8d4e1f2.jsonl.zst  # archived sessions
```

### Event envelope

```python
class EventEnvelope(BaseModel):
    seq: int  # монотонно растущий
    ts: datetime  # ISO 8601 UTC с микросекундами
    schema_version: str  # "1.0"
    kind: str  # discriminator
    session_id: str  # для cross-file queries
    # payload fields добавляются на верхний уровень (плоский JSON)
```

См. [03-session-format.md](../spec/03-session-format.md) раздел 4.

### Projection

```python
class SessionLog(Protocol):
    async def append(self, event: SessionEvent) -> None: ...
    async def events(self) -> AsyncIterable[SessionEvent]: ...
    async def to_messages(self) -> list[Message]: ...  # projection для LLM
    async def save(self, path: Path) -> None: ...
    async def load(self, path: Path) -> None: ...
```

### Crash recovery

```python
async def load(path: Path) -> tuple[list[SessionEvent], bool]:
    """Returns (events, dropped_partial)."""
    events = []
    dropped_partial = False
    async with aiofiles.open(path, "r") as f:
        lines = await f.readlines()

    for line_no, line in enumerate(lines, 1):
        line = line.rstrip("\n")
        if not line:
            continue
        try:
            data = json.loads(line)
            events.append(parse_event(data))
        except (json.JSONDecodeError, ValidationError) as e:
            if line_no == len(lines):  # последняя строка — partial
                logger.warning(f"discarding partial write at line {line_no}: {e}")
                dropped_partial = True
            else:
                raise CorruptedSessionError(f"line {line_no}: {e}")

    return events, dropped_partial
```

### Schema versioning

```python
MIGRATIONS = [
    Migration(from_version="0.9", to_version="1.0", migrator=migrate_0_9_to_1_0),
    # ...
]


def load_with_migrations(path: Path) -> list[SessionEvent]:
    events, _ = load_raw(path)
    current_version = detect_version(events)
    for m in MIGRATIONS:
        if m.from_version == current_version:
            events = m.migrator(events)
            current_version = m.to_version
    return events
```

## Критерии пересмотра решения

1. **Projection > 500ms на типичной сессии** (>10k событий) — пересмотреть SQLite для projection cache.
2. **Concurrent writers потребуются** (например, multi-tab UI в одном session) — пересмотреть SQLite с proper locking.
3. **File size > 500MB на одну сессию** — пересмотреть compression-on-the-fly или per-file rotation.
4. **Cross-session queries** (поиск по всем сессиям) станут частым use case — добавить SQLite index layer поверх JSONL.

## Связанные документы

- [03-session-format.md](../spec/03-session-format.md) — полная спецификация формата
- [agents-architect.md](../agents-architect.md) — вывод №2 о event sourcing
- [self-agent.md](../self-agent.md) — пункт 5 про session-log
- [05-security-model.md](../spec/05-security-model.md) — sensitive data в логах
- [06-testing-strategy.md](../spec/06-testing-strategy.md) — crash recovery тесты
- [Event sourcing introduction](https://martinfowler.com/eaaDev/EventSourcing.html) — Martin Fowler
- [dsh session-logging invariant](https://github.com/deepseek-ai/deepseek-harness) — inspiration для «model-visible means logged»
