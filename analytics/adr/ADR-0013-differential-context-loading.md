# ADR-0013: Differential Context Loading — symbol-level diffs вместо целых файлов

**Дата:** 2026-10-18
**Статус:** Proposed
**Связанные ADR:** ADR-0001 (DFC), ADR-0002 (LSP), ADR-0007 (prompt-cache)

## Контекст

В типичном SOTA-агенте, когда модель работает с одним и тем же файлом в нескольких ходах, файл попадает в контекст **целиком** каждый раз. Это значит:

- Если в ходе N мы прочитали `user_service.py` (2000 строк), в ходе N+1 мы снова читаем его целиком, чтобы проверить свою правку.
- Latency и token cost растут линейно с числом ходов и размером файла.
- Модель «знает» файл, но всё равно видит его весь снова — это не нужно.

OpenCode Context Epoch решает это для system prompt, но не для рабочих файлов. MiMo checkpoint-writer делает snapshot состояния, но не symbol-level diffs.

LSP (ADR-0002) уже даёт symbol-level доступ — `symbol.hover` возвращает сигнатуру, `documentSymbol` возвращает outline. Но этого недостаточно, когда модель хочет **тело функции** для анализа.

**Противоречие (ТРИЗ):** модель должна видеть **актуальный код** (для точности), и модель не должна видеть **одно и то же** повторно (для экономии).

## Решение

Ввести **differential context loading** — в HOT попадают только **изменившиеся** символы + ссылки на неизменённые.

### Принцип

Для каждого символа в HOT хранится:
- **Symbol descriptor** (FQN, location, signature) — компактный.
- **Body** (полный текст символа) — только если он ** изменился с прошлого хода** или **впервые попал в HOT**.
- **Reference to body** (location + mtime) — если тело не изменилось.

Когда модель запрашивает `symbol.body(FQN)`:
- Если body уже в HOT → вернуть из HOT (cache hit).
- Если body не изменился с прошлого хода, но не в HOT → вернуть reference: «см. user_service.py:45-80, body не изменился с хода N-1».
- Если body изменился → вернуть полный body + diff vs предыдущей версии.

### Diff representation

Когда модель должна увидеть изменения, HOT содержит не «новый файл целиком», а:

```
File: src/user_service.py (modified in this turn)

Symbol: UserService.create
  Status: modified
  Diff:
    -  async def create(self, name: str) -> User:
    +  async def create(self, name: str, email: str | None = None) -> User:
         ...body unchanged...
    +      if email:
    +          user.email = email
```

Это в 5–20 раз компактнее, чем полный файл.

### Symbol-level mtime tracking

LSP file-watcher обновляет `documentSymbol` при didSave. Для каждого символа мы знаем:
- location (range в файле).
- content hash (быстрый hash тела).
- last-modified turn (в какой ход агент менял этот символ).

При следующем ходе, если content hash не изменился — тело не пересылается.

### Что делать, если модель хочет полный файл

Модель может явно запросить `file.read(path)`. Но:
1. Это дорогой tool-call (большой output).
2. Мы поощряем `symbol.body(FQN)` вместо `file.read(path)` через описание в tool-schema: «Prefer symbol.body over file.read for specific symbols; file.read only for new files or full-context understanding».
3. Если модель всё же читает файл целиком — он кэшируется (ADR-0012), повторные read'ы бесплатные.

### Workspace snapshot в Zone B (session prefix)

При старте сессии — снимаем snapshot всех файлов в рабочей директории (через LSP documentSymbol + content hash). Этот snapshot — часть Zone B (cacheable, не меняется внутри сессии). На каждый ход мы знаем:
- Какие символы существовали на старте.
- Какие были изменены (агентом или пользователем).
- Какие新增ы/удалены.

Это даёт основу для differential loading.

## Положительные последствия

- **Token cost на работу с большими файлами падает в 5–20 раз.** Только diff, не полный файл.
- **Latency retrieval стабильна.** Symbol.body — это O(symbol size), не O(file size).
- **Cache-friendly.** Неизменённые символы — в cacheable Zone B (workspace snapshot); только diffs в dynamic Zone D.
- **Better focus.** Модель видит «что изменилось», не отвлекается на неизменный контекст.

## Отрицательные последствия

- **Сложность tracking.** Нужно поддерживать per-symbol mtime + content hash. Решение: LSP `documentSymbol` даёт ranges; hash — это SHA1 тела.
- **Риск «я не помню контекст»**. Если модель видит только diff, она может забыть, как выглядит остальной файл. Решение: workspace snapshot в Zone B всегда доступен; модель может сделать `file.read(path)` при необходимости.
- **Edit conflicts.** Если агент и пользователь одновременно правят файл — mtime tracking может запутаться. Решение: file-watcher приоритетен; на каждый didSave — re-hash affected symbols.
- **Multi-symbol edits.** Если ход меняет 5 символов в одном файле — 5 diffs. Решение: file-level diff как fallback, если символов > N.

## Альтернативы

1. **Всегда полный файл** (как SOTA). Отвергнуто: дорого, не нужно.
2. **Line-based diffs** (как git diff). Отвергнуто: less semantic; не понимает границ символов.
3. **Snapshot + grep по запросу.** Отвергнуто: теряет structured view; нет symbol-aware retrieval.
4. **No caching, всегда ре-read.** Отвергнуто: трата IO + tokens.

## Применённый ТРИЗ-принцип

- **Principle 17 — Another Dimension.** Контекст имеет измерение «изменчивость»: изменённые символы в Zone D, неизменённые — в Zone B (snapshot).
- **Principle 32 — Optical Changes.** Diff меняет «оптическое» представление кода — модель видит изменения, не весь файл.
- **Principle 10 — Preliminary Action.** Workspace snapshot делается при старте сессии — заранее.
- **Principle 15 — Dynamicity.** Per-symbol mtime — динамический tracking изменений.
- **Principle 2 — Taking Out.** Полный файл «вынесен» из контекста — оставлен только diff.

## Идеальный финальный результат (IFR)

Модель видит только то, что изменилось. Неизменный код — это «фон», доступный по требованию, но не занимающий окно. Token cost на работу с большими файлами — O(изменения), не O(размер файла).
