# ADR-0005: Semantic Project Index — инкрементальный индекс символов и embeddings

**Дата:** 2026-10-18
**Статус:** Proposed
**Связанные ADR:** ADR-0002 (LSP), ADR-0001 (DFC)

## Контекст

Для retrieval из ICE-слоя (см. ADR-0001) нужен быстрый доступ к символам и семантике всего проекта. LSP (ADR-0002) даёт `workspace/symbol` — но это поиск по имени, не по семантике; и для больших проектов (10–100 K файлов) он не покрывает cross-file связи.

Существующие подходы в SOTA:
- **kilo-indexing** — семантический поиск по коду, но закрытая реализация, нет публичных деталей.
- **MiMo memory** — FTS5 по `MEMORY.md` и заметкам, но не по коду.
- **Claude Code / OpenCode / dsh** — только `grep`/`glob`, нет индекса.

Потребность: агент должен находить символы по **семантическому** запросу («где у нас логика авторизации?») за миллисекунды, а не секунды; и это должно работать инкрементально — при изменении файла не перестраивать весь индекс.

**Противоречие (ТРИЗ):** индекс должен быть **свежим** (отражать текущее состояние кода), и индекс должен быть **дешёвым в поддержке** (не перестраивать всё на каждое изменение).

## Решение

Построить **трёхслойный индекс**, обновляемый инкрементально через LSP file-watcher:

### Слой A — Symbol index (через LSP)

- При старте сессии: drain `workspace/symbol('*')` по всем LSP-серверам. Кэшируем в trie по FQN (fully-qualified name).
- На `didOpen` / `didChange` / `didSave`: обновляем только изменённые символы через `documentSymbol` для затронутого файла.
- Хранение: trie в памяти + persistence в SQLite (для быстрого старта следующей сессии).
- Lookup: O(len(name)) для точного имени, O(K) для префикса.

### Слой B — Embeddings index

- AST-aware chunking: каждый чанк = одна функция/метод/класс (через LSP `documentSymbol` для разбиения).
- Embeddings: модель типа `nomic-embed-code` или `jina-embeddings-v3` (512–768 dim).
- Хранение: SQLite + sqlite-vec (или LanceDB для больших проектов) — гибрид exact+ANN search.
- На `didSave`: переcчёт embeddings только для изменённых чанков; инкрементальный upsert.
- Background: embeddings считаются в отдельном worker-процессе, не блокируют ход.

### Слой C — References graph

- Из LSP `references` строится граф вызовов: symbol → [callers, callees].
- Используется для:
  - «Кто вызывает эту функцию?» — мгновенный ответ, без grep.
  - Boost в retrieval: символы с большим числом callers получают +score (это «важные» символы).
  - Impact analysis: при edit функции сразу видно, кто может сломаться.

### Гибридный retrieval

При `semantic.search(query)`:

1. **Lexical:** trie-lookup по токенам запроса → top-K кандидатов.
2. **Semantic:** embedding-lookup → top-K кандидатов.
3. **LSP-aware boost:** кандидаты с большим числом references получают +score.
4. **Reranker:** cross-encoder (small, ~100 ms) переранжирует top-K.
5. Возвращается top-K (по умолчанию 5) symbol-описаний — не файлы.

## Положительные последствия

- **Sub-ms lookup** по имени символа; <200 ms semantic search.
- **Инкрементальность:** изменение одного файла обновляет только его чанки в индексе — нет перестройки.
- **Cross-file связи:** references graph даёт агенту понимание impact, недоступное grep'у.
- **Гибридность:** lexical + semantic + reference-boost покрывают все типы запросов (точное имя / семантика / важность).

## Отрицательные последствия

- **Memory footprint.** Embeddings на 100 K строк кода ~50–200 MB. На 1 M строк — 0.5–2 GB. Решение: mmap, ленивая загрузка.
- **Cold start индекса.** Первый запуск на большом проекте — 30–180 s на embeddings. Решение: persistence + incremental на следующих запусках; pre-warm в фоне.
- **Embedding model.** Нужна локальная модель (для приватности) или API (для скорости). Решение: локальная по умолчанию, опционально API.
- **Chunking quality.** AST-aware chunking зависит от LSP `documentSymbol` — для языков без хорошего LSP чанки будут плохими. Решение: fallback на line-based chunking.

## Альтернативы

1. **Только LSP `workspace/symbol`.** Отвергнуто: нет semantic search; не покрывает «где у нас логика авторизации?».
2. **Только embeddings (без LSP).** Отвергнуто: плохая точность для имён; нет references graph.
3. **LSIF/SCIP indexer** (Sourcegraph). Рассматривается как опция для очень больших монорепо (>500 K файлов) — offline-индекс в CI, агент читает готовый. Для типичных проектов — overkill.
4. **ripgrep + embeddings без symbol layer.** Отвергнуто: теряется структура; chunking хуже.

## Применённый ТРИЗ-принцип

- **Principle 10 — Preliminary Action.** Индекс строится заранее, до того, как понадобится.
- **Principle 15 — Dynamicity.** Индекс инкрементально обновляется, не статичен.
- **Principle 17 — Another Dimension.** Три слоя (symbol / embedding / references) — три ортогональных измерения поиска.
- **Principle 24 — Intermediary.** Индекс — посредник между кодом и моделью.
- **Principle 40 — Composite Materials.** Гибридный retrieval — композиция трёх методов.

## Идеальный финальный результат (IFR)

Агент находит любой символ в проекте любого размера за <10 ms по имени, <200 ms по семантике. Размер проекта не влияет на latency retrieval — только на cold-start индекса.
