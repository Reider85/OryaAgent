# ADR-0012: Tool Result Caching — кэширование результатов инструментов с mtime/TTU

**Дата:** 2026-10-18
**Статус:** Proposed
**Связанные ADR:** ADR-0002 (LSP), ADR-0006 (parallel tools)

## Контекст

В типичной сессии агент многократно вызывает одни и те же инструменты с одинаковыми аргументами:

- `read(file)` одного и того же файла в нескольких ходах.
- `grep(pattern)` по одному и тому же паттерну (особенно если planner предлагает одинаковые имена).
- LSP `symbol.hover` для одних и тех же символов.
- `bash(run tests)` — если тесты не поменялись, результат тот же.

Все 5 SOTA-агентов **не кэшируют** tool-results (за исключением ad-hoc in-memory кэшей в некоторых реализациях). Это значит:

- Повторные `read` одного файла = повторная трата IO + вставка в context (потенциально дублирующая).
- Повторные `grep` = 50–500 ms каждый раз.
- На длинных сессиях 30–60% tool-calls — дубликаты предыдущих.

**Противоречие (ТРИЗ):** tool-results должны быть **свежими** (отражать текущее состояние), и tool-results должны быть **быстрыми** (не пересчитывать, если не изменилось).

## Решение

Ввести **двухуровневый кэш tool-results**:

### Уровень 1 — mtime-based cache (для file-backed tools)

Для инструментов, результат которых зависит от файла (`read`, `grep`, `symbol.hover`, `symbol.def`, `symbol.refs`, `documentSymbol`):

- **Ключ:** `(tool_name, args, file_mtime, file_path)`.
- **Значение:** результат выполнения.
- **Инвалидация:** автоматически, если `file_mtime` изменился.

```typescript
async function cachedRead(path: string, range?: Range): Promise<string> {
  const stat = await fs.stat(path);
  const key = `read:${path}:${range?.start || 0}:${range?.end || 'end'}`;
  const cached = cache.get(key);
  if (cached && cached.mtime === stat.mtimeMs) {
    return cached.value;  // hit
  }
  const value = await actualRead(path, range);
  cache.set(key, { mtime: stat.mtimeMs, value });
  return value;
}
```

Для LSP-запросов — mtime берётся из LSP file-watcher'а (LSP-сервер сам инвалидирует свои индексы при didChange).

### Уровень 2 — TTU-based cache (для command-backed tools)

Для инструментов, результат которых не привязан к одному файлу (`bash`, `semantic.search`, `symbol.search` по всему проекту):

- **Ключ:** `(tool_name, args, repo_state_hash)`.
- `repo_state_hash` — быстрый хэш состояния (mtime + size всех отслеживаемых файлов в рабочей директории; обновляется file-watcher'ом).
- **TTU (Time-To-Use):** по умолчанию 5 s для `bash` (чтобы не кэшировать долго), 30 s для `semantic.search` (индекс обновляется медленнее).

```typescript
async function cachedBash(cmd: string): Promise<BashResult> {
  const stateHash = await getRepoStateHash();
  const key = `bash:${cmd}:${stateHash}`;
  const cached = cache.get(key);
  if (cached && Date.now() - cached.ts < 5000) {  // 5s TTU
    return cached.value;
  }
  const value = await actualBash(cmd);
  cache.set(key, { ts: Date.now(), value });
  return value;
}
```

### Что кэшируется — что нет

| Tool | Кэш? | Ключ инвалидации |
|---|---|---|
| `read` | да | file mtime |
| `grep` | да | file mtime + pattern |
| `glob` | да | directory mtime |
| `symbol.hover` | да | file mtime + symbol location |
| `symbol.def` | да | file mtime + symbol |
| `symbol.refs` | да | repo_state_hash |
| `symbol.search` | да | repo_state_hash |
| `semantic.search` | да | repo_state_hash + 30s TTU |
| `bash` (read-only: `ls`, `cat`, `git status`) | да | 5s TTU + repo_state_hash |
| `bash` (with side-effects: `make`, `npm test`) | **нет** | — |
| `write`, `edit` | **нет** (запись) | — |
| `bash` (with mutations: `rm`, `mv`, `git commit`) | **нет** | — |

### Инвалидация при write/edit

Когда модель вызывает `write` или `edit`, кэш для затронутого файла инвалидируется немедленно:
- `read(file)` — все ключи с этим file.
- `grep(pattern)` с glob, включающим этот file — инвалидируется (или помечается stale).
- LSP-запросы для символов из этого file — LSP сам обновит через didChange/didSave.

### Размер кэша

- LRU с лимитом по памяти (по умолчанию 100 MB).
- Hit-rate метрики в TUI (`/cache-stats`).

## Положительные последствия

- **Latency повторных tool-calls → ~0.** Hit — это просто lookup в Map.
- **Token economy.** Если результат уже в HOT (через предыдущий call), повторный call вообще не нужен — модель может не вызывать.
- **CPU economy.** `grep` на 100 K строк — 200 ms один раз, потом 0 ms.
- **LSP cache economy.** LSP-сервер сам кэширует, но наш кэш экономит JSON-RPC round-trip.

## Отрицательные последствия

- **Stale risk.** Если file watcher пропустил изменение (редактор вне нашего контроля, например vim с нестандартной конфигурацией), кэш вернёт устаревший результат. Решение: TTL fallback (даже mtime-based cache обновляется раз в 30 s, если нет явного didSave).
- **Memory.** 100 MB LRU — это заметно на маленьких машинах. Решение: настраиваемый лимит; spill на диск (SQLite) для редких records.
- **Сложность key-construction.** Для `grep` с glob'ом — нужно правильно вычислить, какие файлы релевантны. Решение: conservative — если glob сложный, cache miss.

## Альтернативы

1. **Без кэша** (как SOTA). Отвергнуто: 30–60% дублирующих tool-calls — это трата.
2. **Только in-memory ad-hoc.** Отвергнуто: нет дисциплины инвалидации; риск stale-data высокий.
3. **Persistent cache (SQLite на диск).** Будущая оптимизация для cross-session кэша; в v0.1 — in-process LRU.
4. **Cache только для LSP.** Отвергнуто: `read` и `grep` тоже выгодно кэшировать.

## Применённый ТРИЗ-принцип

- **Principle 10 — Preliminary Action.** Результат вычисляется один раз, переиспользуется.
- **Principle 35 — Parameter Change.** Параметр `mtime` / `state_hash` управляет валидностью кэша.
- **Principle 11 — Beforehand Cushioning.** LRU с лимитом — заранее ограниченный ресурс.
- **Principle 17 — Another Dimension.** Кэш — это «другое измерение» tool-execution: вместо «вычислить сейчас» — «взять готовое».
- **Principle 2 — Taking Out.** Вычисление tool-result «вынесено» из критического пути — если уже было сделано.

## Идеальный финальный результат (IFR)

Tool-call с аргументами, которые уже были — стоит 0 ms и 0 токенов. Repo-state-hash гарантирует, что при любом изменении кэш автоматически корректен. Модель не задумывается, «выполнять или нет» — выполняется всегда, но дёшево.
