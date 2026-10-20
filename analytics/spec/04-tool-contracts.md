# Спецификация контрактов инструментов

**Документ:** 04-tool-contracts
**Дата:** 20 октября 2026
**Статус:** Draft v0.1
**Связанные документы:** [01-module-contracts.md](01-module-contracts.md), [05-security-model.md](05-security-model.md)

---

## 0. Назначение

5 базовых инструментов (`read`, `write`, `edit`, `bash`, `grep`) — проверенное ядро, одинаковое у всех 5 архитектур из [agents-architect.md](../agents-architect.md). Этот документ фиксирует:
- Контракт каждого инструмента: вход, выход, edge-cases
- Политику ошибок и таймаутов
- Поведение на больших файлах и больших репозиториях
- Специфику платформ (Linux/macOS/Windows)
- Безопасность: какие данные чувствительны, как защищаются

Наивная имплементация `read` или `bash` ломает агент на первом же edge-case. Эти контракты — результат анализа 5 зрелых кодинг-агентов, не догадки.

## 1. Общий Protocol

```python
class Tool(Protocol):
    @property
    def name(self) -> str: ...
    
    @property
    def description(self) -> str: ...  # для LLM
    
    @property
    def input_schema(self) -> type[BaseModel]: ...  # Pydantic-класс
    
    @property
    def output_schema(self) -> type[BaseModel]: ...
    
    @property
    def default_timeout(self) -> float: ...  # в секундах
    
    @property
    def is_destructive(self) -> bool: ...  # для permission-engine
    
    async def execute(self, input: BaseModel, ctx: ToolContext) -> ToolResult: ...
```

### 1.1. ToolContext

Передаётся в каждый `execute`:

```python
class ToolContext(BaseModel):
    working_dir: Path  # cwd, никогда не None
    abort_signal: asyncio.Event  # для отмены long-running
    logger: structlog.BoundLogger
    audit: AuditBridge  # writes to ~/.orya/audit.jsonl
    config: ToolConfig  # tool-specific overrides
    session_id: str
    call_id: str
    timeout_override: float | None = None
```

### 1.2. ToolResult

```python
class ToolResult(BaseModel):
    outcome: Literal["success", "error", "denied", "aborted", "timeout"]
    content: str  # для LLM
    metadata: dict[str, Any] = {}  # tool-specific
    error_kind: str | None = None
    error_message: str | None = None
    content_truncated: bool = False
    content_original_size: int | None = None
    duration_ms: int
```

### 1.3. Error taxonomy

| `error_kind` | Когда | `retryable` |
|---|---|---|
| `invalid_input` | Pydantic-валидация упала | False |
| `not_found` | Файл/директория не существует | False |
| `permission_denied` | OS-level: ENOACCESS | False |
| `io_error` | Диск полный, I/O error | True |
| `timeout` | Timeout exceeded | True |
| `aborted` | AbortSignal.set() | False |
| `tool_specific` | Особая ошибка инструмента (bash exit code != 0) | зависит |

`tool_specific` — для bash: `exit_code != 0`. Не retryable в общем случае (LLM должен адаптировать команду), но LLM может решить повторить.

## 2. `read` — чтение файла

### 2.1. Контракт

```python
class ReadInput(BaseModel):
    path: str  # relative to working_dir или absolute
    start_line: int = 1  # 1-indexed
    limit: int | None = None  # max lines to read, None = до конца


class ReadOutput(BaseModel):
    path: str
    content: str  # text content, построчно
    total_lines: int
    returned_lines: int
    is_binary: bool
    encoding: str | None = None
    sha256: str  # для аудита
```

### 2.2. Поведение

- **Пагинация:** `start_line=10, limit=50` → строки 10..59 включительно.
- **Без limit:** чтение до конца файла, но не более `max_lines` (default=2000).
- **Бинарные файлы:** детектится по наличию null-byte в первых 8 KB. Возвращает `is_binary: true`, content = `"<binary file, X bytes, sha256: ...>"`. Не пытается декодировать.
- **Кодировка:** пробует UTF-8, fallback на `chardet` (или `charset-normalizer`). `encoding` в output.
- **Символические ссылки:** следует по symlink-ам, но `path` в output — original (не resolved).
- **Специальные файлы** (`/dev/null`, `/proc/cpuinfo`): читаются как обычные файлы, но без sha256 (потоковые).
- **Directories:** `IsADirectoryError` → `ToolResult.error(kind="invalid_input", message="path is a directory, use 'bash ls' instead")`.

### 2.3. Edge-cases

| Случай | Поведение |
|---|---|
| Path traversal (`../../etc/passwd`) | Разрешён (это ответственность permission-engine, не инструмента) |
| Non-existent file | `error(kind="not_found")` |
| Permission denied (OS) | `error(kind="permission_denied")` |
| File too large (>10 MB) | `error(kind="invalid_input", message="file > 10MB, use 'bash head/tail' or specify start_line+limit")` |
| File modified during read | Возвращается снимок на момент чтения (не блокирует) |
| Encoding не UTF-8 | Пробует Latin-1 как fallback, помечает в `encoding` |
| Empty file | `content: "", total_lines: 0, returned_lines: 0` |
| Line longer than 2000 chars | Truncates to 2000 + `\n... [line truncated] ...` |

### 2.4. Sensitive files

Если path матчит sensitive-pattern (см. [05-security-model.md](05-security-model.md)):

```python
if matches_sensitive_pattern(path):
    return ToolResult(
        outcome="denied",
        content="<sensitive file: requires explicit user permission>",
        error_kind="sensitive_file",
    )
```

Permission-engine обработает: покажет пользователю модалку «read /path/.env? [y/N]».

### 2.5. Performance

- Чтение через `aiofiles` — non-blocking.
- Для больших файлов (>1 MB) — стриминговое чтение по 64 KB chunks, чтобы не загружать всё в память.
- SHA256 считается потоково (hashlib обновляется по chunks).
- Default timeout: 5s (достаточно для локальных SSD, может быть мало для NFS).

## 3. `write` — запись файла

### 3.1. Контракт

```python
class WriteInput(BaseModel):
    path: str
    content: str
    overwrite: bool = False  # если True, overwrite без вопроса
    create_dirs: bool = False  # создать родительские директории


class WriteOutput(BaseModel):
    path: str
    bytes_written: int
    sha256: str
    was_created: bool  # True если новый файл, False если overwrite
```

### 3.2. Atomic write

Запись всегда atomic:

```python
async def execute(input, ctx):
    target = Path(input.path)
    if not input.overwrite and target.exists():
        return ToolResult(outcome="error", error_kind="already_exists", ...)
    
    if input.create_dirs:
        target.parent.mkdir(parents=True, exist_ok=True)
    
    # Atomic write: temp file + rename
    tmp = target.with_suffix(target.suffix + '.orya-tmp')
    async with aiofiles.open(tmp, 'w') as f:
        await f.write(input.content)
        await f.flush()
        os.fsync(f.fileno())
    
    tmp.rename(target)  # atomic на POSIX
    
    return ToolResult(outcome="success", content=f"wrote {len(input.content)} chars to {target}", ...)
```

### 3.3. Edge-cases

| Случай | Поведение |
|---|---|
| File exists, overwrite=False | `error(kind="already_exists")` |
| File exists, overwrite=True | Atomic replace |
| Parent dir doesn't exist, create_dirs=False | `error(kind="invalid_input", message="parent dir doesn't exist, use create_dirs=True")` |
| Permission denied (OS) | `error(kind="permission_denied")` |
| Disk full during write | `error(kind="io_error")`, temp file удаляется |
| Path is directory | `error(kind="invalid_input", message="path is a directory")` |
| Symlink in path | Resolved и пишется по реальному пути |
| Content > 10 MB | `error(kind="invalid_input", message="content > 10MB, use 'bash' with heredoc")` |
| Content contains null-byte | Разрешено, но помечается в metadata |

### 3.4. Sensitive paths

Запись в sensitive-locations (`.env`, `~/.ssh/`, `/etc/`) — `denied` по умолчанию, требует явного permission.

### 3.5. Backup policy

При `overwrite=True` — создаётся `.bak` файл с предыдущим содержимым:

```
/path/to/file.py        ← новый контент
/path/to/file.py.orya-bak ← предыдущий
```

`.orya-bak` файлы удаляются при следующем `write` к тому же пути (не накапливаются). На enterprise — configurable (off по умолчанию для disk-экономии).

## 4. `edit` — точечная правка файла

### 4.1. Контракт

```python
class EditInput(BaseModel):
    path: str
    old_string: str  # что заменить (должно быть уникально)
    new_string: str  # на что заменить
    replace_all: bool = False  # если True, заменяет все вхождения


class EditOutput(BaseModel):
    path: str
    replacements_made: int
    content_preview_before: str  # первые 5 строк контекста вокруг замены
    content_preview_after: str
```

### 4.2. Поведение

- **Уникальность `old_string`:** по умолчанию (`replace_all=False`) — должен быть ровно один match. Если 0 — `error(kind="not_found")`. Если >1 — `error(kind="ambiguous_match", message="X occurrences found, use replace_all=True or make old_string more specific")`.
- **Replace_all:** заменяет все вхождения.
- **Atomic write:** как в `write` — temp file + rename.
- **Line endings:** сохраняет существующие line-endings файла (CRLF, LF). Не конвертирует.
- **Whitespace:** точное совпадение, не нормализует. `old_string="foo"` не сматчит `"foo "` (с trailing space).

### 4.3. Edge-cases

| Случай | Поведение |
|---|---|
| File doesn't exist | `error(kind="not_found", message="file doesn't exist, use 'write' instead")` |
| File exists, empty | `error(kind="not_found", message="file is empty, nothing to edit")` |
| old_string not found | `error(kind="not_found")` |
| old_string found multiple times, replace_all=False | `error(kind="ambiguous_match")` |
| old_string == new_string | `error(kind="invalid_input", message="old_string and new_string are identical")` |
| old_string is empty string | `error(kind="invalid_input", message="old_string cannot be empty")` |
| old_string is whitespace-only | `error(kind="invalid_input", message="old_string is whitespace-only, refused")` |
| Binary file | `error(kind="invalid_input", message="cannot edit binary file")` |
| File too large (>10 MB) | `error(kind="invalid_input", message="file > 10MB, use 'bash sed' instead")` |

### 4.4. Context preview

В metadata возвращается preview контекста — 5 строк до и 5 строк после первой замены. Это помогает LLM понять структуру файла без отдельного `read`.

```python
"content_preview_before": "def foo():\n    x = 1\n    y = 2\n    # OLD LINE HERE\n    z = 3\n    return z",
"content_preview_after": "def foo():\n    x = 1\n    y = 2\n    # NEW LINE HERE\n    z = 3\n    return z"
```

### 4.5. Performance

- Чтение файла целиком в память (для поиска). При >10 MB — error.
- Поиск `old_string` через `str.find()` (быстрее regex).
- Atomic write как в `write`.

## 5. `bash` — выполнение shell-команды

### 5.1. Контракт

```python
class BashInput(BaseModel):
    command: str  # команда для выполнения
    timeout: float = 300.0  # seconds, max 600
    cwd: str | None = None  # working dir, None = ctx.working_dir
    env: dict[str, str] | None = None  # доп env переменные


class BashOutput(BaseModel):
    stdout: str
    stderr: str
    exit_code: int
    duration_ms: int
    signal: str | None = None  # если убит сигналом
```

### 5.2. Execution model

- **PTY (pseudo-terminal):** через `asyncio.subprocess` с `pty=True` на POSIX. Это даёт корректную обработку TTY-программ (top, vim, etc.) и ANSI-цветов.
- **Windows:** `asyncio.subprocess` без PTY (Windows не имеет PTY в POSIX-смысле). ConPTY — v2.
- **Shell:** всегда `/bin/bash` на POSIX, `cmd.exe` на Windows. Не `sh` (bash-isms часты).
- **Login shell:** `-l` флаг для загрузки `.bashrc` (пользовательские alias-ы работают).

### 5.3. Stream handling

- **stdout и stderr** — separate streams, накапливаются в memory.
- **Stripped trailing whitespace** (некоторые команды добавляют extra newlines).
- **ANSI stripping:** optional (default=True для LLM-context). User видит raw output.
- **Encoding:** UTF-8 assumed, fallback на Latin-1.

### 5.4. Limits

| Параметр | Default | Max |
|---|---|---|
| `timeout` | 300s | 600s |
| `stdout` size | 1 MB | 10 MB (truncated) |
| `stderr` size | 256 KB | 2 MB |
| Concurrent bash calls | 1 per session | configurable |

При превышении stdout/stderr limit:
```python
stdout = stdout[:1MB] + f"\n... [truncated, original_size={len(full_stdout)} bytes, see ~/.orya/sessions/{sid}/bash-{call_id}.log] ..."
```

Полный output сохраняется в отдельный файл, в ToolResult.content — truncated.

### 5.5. Timeout handling

```python
async def execute(input, ctx):
    proc = await asyncio.create_subprocess_exec(
        '/bin/bash', '-lc', input.command,
        cwd=input.cwd or ctx.working_dir,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=merged_env,
    )
    
    try:
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(),
            timeout=input.timeout
        )
    except asyncio.TimeoutError:
        proc.terminate()
        try:
            await asyncio.wait_for(proc.wait(), timeout=5)
        except asyncio.TimeoutError:
            proc.kill()
        return ToolResult(outcome="timeout", ...)
```

### 5.6. Abort handling

```python
abort_listener = asyncio.create_task(wait_for_abort(ctx.abort_signal))
proc_task = asyncio.create_task(proc.communicate())

done, pending = await asyncio.wait(
    [proc_task, abort_listener],
    return_when=asyncio.FIRST_COMPLETED
)

if abort_listener in done:
    proc.terminate()
    await asyncio.wait_for(proc.wait(), timeout=5)
    return ToolResult(outcome="aborted", ...)
```

### 5.7. Environment filtering

Запрещённые env-переменные (никогда не передаются в subprocess):
- `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, any `*_API_KEY`
- `AWS_SECRET_ACCESS_KEY`, `AZURE_CLIENT_SECRET`
- `ORYA_SESSION_KEY`, internal Orya keys

Разрешённые по умолчанию:
- `PATH`, `HOME`, `USER`, `LANG`, `LC_ALL`
- `TERM`, `COLUMNS`, `LINES` (для TTY-aware программ)
- Любые явные в `input.env`

### 5.8. Exit code semantics

```python
if exit_code == 0:
    outcome = "success"
elif signal is not None:
    outcome = "error"
    error_kind = "killed_by_signal"
elif exit_code in (124, 137):  # timeout, killed
    outcome = "timeout"
else:
    outcome = "error"
    error_kind = "tool_specific"
```

LLM видит:
```
$ ls /nonexistent
stderr: ls: cannot access '/nonexistent': No such file or directory
exit_code: 2
```

### 5.9. Edge-cases

| Случай | Поведение |
|---|---|
| Background process (`&`) | Разрешён, но `proc.communicate()` ждёт только foreground. Background — leak, документируем «не используйте background в MVP». v2: jobs API. |
| Interactive prompt (password) | Timeout 300s, процесс убит. LLM видит timeout. |
| `cd` command | Не имеет эффекта (subprocess изолирован). Используйте `cwd` параметр. |
| `exit` command | Завершает subprocess, но не OryaAgent. |
| Pipeline (`\|`) | Работает (через shell). |
| Heredoc (`<<EOF`) | Работает. |
| Background + wait (`wait $!`) | Работает в пределах одной команды. |
| Long-running (sleep 1000) | Timeout 300s, killed. |

### 5.10. Audit

Каждый bash-call логирует в audit:
```json
{
  "ts": "...",
  "call_id": "...",
  "command": "ls -la",
  "cwd": "/home/user/project",
  "approved_by": "user",
  "exit_code": 0,
  "duration_ms": 42,
  "stdout_size": 1234,
  "stderr_size": 0,
  "truncated": false
}
```

Полный stdout/stderr — в session-log (если не contains sensitive patterns).

## 6. `grep` — поиск по содержимому файлов

### 6.1. Контракт

```python
class GrepInput(BaseModel):
    pattern: str  # regex или literal
    is_regex: bool = True
    path: str | None = None  # каталог для поиска, None = working_dir
    glob: str | None = None  # файловый фильтр (e.g. "*.py")
    case_insensitive: bool = False
    context_before: int = 0  # -B
    context_after: int = 0  # -A
    max_results: int = 100


class GrepOutput(BaseModel):
    matches: list[GrepMatch]
    total_matches: int
    truncated: bool
    files_searched: int


class GrepMatch(BaseModel):
    path: str
    line_number: int
    line: str
    context_before: list[str] = []
    context_after: list[str] = []
```

### 6.2. Реализация

Использует **ripgrep** (`rg`) как backend — вездесущ, быстр, уважает `.gitignore`.

```python
async def execute(input, ctx):
    cmd = ['rg', '--json']
    if not input.is_regex:
        cmd.append('--fixed-strings')
    if input.case_insensitive:
        cmd.append('-i')
    if input.context_before:
        cmd.extend(['-B', str(input.context_before)])
    if input.context_after:
        cmd.extend(['-A', str(input.context_after)])
    if input.glob:
        cmd.extend(['-g', input.glob])
    cmd.extend(['--max-count', str(input.max_results)])
    cmd.append(input.pattern)
    cmd.append(input.path or '.')
    
    proc = await asyncio.create_subprocess_exec(
        *cmd, cwd=ctx.working_dir,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)
    
    matches = parse_rg_json(stdout)
    return ToolResult(outcome="success", content=render_matches(matches), ...)
```

### 6.3. Output rendering

Для LLM — текстовый формат (compact):
```
src/orya/loop.py:42:5:    if self.iterations < MAX_ITER:
src/orya/loop.py:58:2:        self.iterations += 1
src/orya/loop.py:71:4:    raise IterationsExceeded(self.iterations)

Found 3 matches in 1 file
```

Для UI — структурированный (для кликабельных ссылок).

### 6.4. Edge-cases

| Случай | Поведение |
|---|---|
| Pattern not found | `success` с `total_matches=0`, content="No matches found" |
| Invalid regex | `error(kind="invalid_input", message="regex error: ...")` |
| Path doesn't exist | `error(kind="not_found")` |
| Path is file, not directory | Ищет в этом файле (rg поддерживает) |
| Binary files | Пропускаются (rg default) |
| `.gitignore` respected | Да (rg default) |
| Hidden files (`.env`) | Пропускаются по умолчанию; `--hidden` через config |
| max_results exceeded | `truncated: true`, content="... and N more matches not shown" |
| Large codebase (>100k files) | Timeout 30s; если упал — fallback на `--max-filesize 1M` |

### 6.5. Performance

- ripgrep — fast, но на очень больших репозиториях (monorepos с >1M файлов) может быть медленным.
- При timeout — LLM видит «search timed out, narrow your search with glob/path».
- File count в output помогает LLM понять масштаб.

## 7. `glob` — поиск файлов по имени

### 7.1. Контракт

```python
class GlobInput(BaseModel):
    pattern: str  # glob-pattern, e.g. "**/*.py"
    path: str | None = None
    max_results: int = 1000


class GlobOutput(BaseModel):
    files: list[str]
    total_files: int
    truncated: bool
```

### 7.2. Реализация

Через `pathlib.Path.glob()` (нативный Python), без внешних зависимостей. Async — через `asyncio.to_thread`.

### 7.3. Edge-cases

| Случай | Поведение |
|---|---|
| `pattern="**/*.py"` | Все Python-файлы рекурсивно |
| `pattern="*.py"` | Только в текущем каталоге (без `**/`) |
| No matches | `success` с пустым списком |
| Pattern matches >1000 | `truncated: true` |

## 8. Безопасность инструментов

### 8.1. Path safety

Все tools принимают пути как relative-to-working_dir или absolute. Path traversal (`../../etc/passwd`) — **разрешён на уровне инструмента**, но `permission-engine` может его запретить. Разделение ответственности.

### 8.2. Sensitive file patterns

Стандартный список (configurable в `~/.orya/sensitive.yml`):

```yaml
patterns:
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
```

Матчинг — case-insensitive, glob-patterns. Tools проверяют перед доступом.

### 8.3. Audit trail

Все tool-calls логируют в `~/.orya/audit.jsonl`:

```json
{
  "ts": "2026-10-20T14:32:01.123Z",
  "call_id": "abc123",
  "tool": "bash",
  "input_hash": "sha256:...",
  "approved_by": "user",
  "outcome": "success",
  "duration_ms": 42,
  "exit_code": 0,
  "stdout_size": 1234,
  "truncated": false
}
```

`input_hash` — для инструментов с потенциально sensitive input (bash command, file content). Полный input — в session-log, но audit-log содержит только hash для быстрого search.

### 8.4. Resource limits

| Limit | Value | Enforced by |
|---|---|---|
| Max file size read | 10 MB | `read` tool |
| Max file size write | 10 MB | `write` tool |
| Max bash output | 1 MB stdout, 256 KB stderr | `bash` tool |
| Max bash duration | 600s | `bash` tool |
| Max grep results | 100 | `grep` tool |
| Max glob results | 1000 | `glob` tool |
| Max concurrent bash | 1 | `agent_loop` |
| Total session memory | configurable | `agent_loop` (estimate, не strict) |

## 9. Тестирование инструментов

### 9.1. Unit tests

Каждый инструмент — отдельный test-suite:

```
tests/unit/tools/
├── test_read.py
├── test_write.py
├── test_edit.py
├── test_bash.py
├── test_grep.py
└── test_glob.py
```

Минимум 20 тестов на инструмент, покрывают:
- Happy path
- Все edge-cases из таблиц выше
- Error cases (invalid_input, not_found, permission_denied, io_error, timeout)
- Atomicity (для write/edit)
- Truncation behavior
- Sensitive file detection

### 9.2. Property-based tests

```python
@given(file_content=...")
def test_read_write_roundtrip(file_content):
    write to /tmp/test.txt
    content_read = read from /tmp/test.txt
    assert content_read == file_content
```

### 9.3. Integration tests

Инструменты в реальном workflow:

```
tests/integration/
├── test_workflow_read_edit_run.py
├── test_workflow_grep_edit_loop.py
└── test_workflow_bash_pipe.py
```

Используют temporary directory, real file-system, real ripgrep.

### 9.4. Performance tests

```
tests/perf/
├── test_read_large_file.py        # 10 MB file, <1s
├── test_bash_long_output.py       # 1 MB stdout, <5s
├── test_grep_large_repo.py        # 100k files, <10s
```

## 10. Открытые вопросы

1. **Tool versioning?** Каждый инструмент имеет версию в имени (`read@1.0`)? Или только contract-версия в Protocol? MVP: только Protocol-версия. v2: per-tool versions для backwards-compat в расширениях.

2. **Custom tools API?** Пользовательские инструменты через `~/.orya/tools/*.py` — Python-модуль с классом, реализующим Tool Protocol. MVP: hardcoded 5 tools. v2: dynamic loading.

3. **MCP-инструменты?** Внешние MCP-серверы — отдельная категория. Их tools не реализуют Protocol напрямую, а оборачиваются в MCPAdapter. v2.

4. **Streaming tools?** `bash` мог бы стримить stdout в реальном времени в TUI (а не ждать completion). MVP: ждёт completion. v2: streaming для long-running bash.

5. **Tool-specific config overrides?** Каждый tool может иметь user-config: `bash.default_timeout`, `read.max_size`, etc. MVP: hardcoded defaults. v2: configurable.

---

**Следующие шаги:**

1. Зафиксировать Tool Protocol как Protocol-класс
2. Реализовать 5 инструментов в порядке: read → write → edit → grep → bash
3. Создать comprehensive test-suite (минимум 100 тестов на все инструменты)
4. Добавить `sensitive.yml` с дефолтным списком паттернов
