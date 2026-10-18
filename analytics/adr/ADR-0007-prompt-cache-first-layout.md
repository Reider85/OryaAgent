# ADR-0007: Prompt-cache-first Layout — дисциплина контекста для prompt-cache

**Дата:** 2026-10-18
**Статус:** Proposed
**Связанные ADR:** ADR-0001 (DFC), ADR-0010 (compaction), ADR-0013 (diffs)

## Контекст

Современные LLM-провайдеры (Anthropic, OpenAI, Google, DeepSeek) поддерживают **prompt caching**: стабильный prefix запроса кэшируется на стороне провайдера, и при повторном использовании стоит в 5–25× дешевле и обрабатывается быстрее. На длинных сессиях это даёт 60–95% экономии.

Но cache работает только при **точно совпадающем** prefix. Любое изменение в начале `messages[]` инвалидирует весь cache. Существующие агенты регулярно теряют cache из-за:

- Динамических timestamp в system prompt.
- Изменения состава инструментов между ходами.
- Вставки «live context» (git status, time, pwd) в начало сообщений.
- Компакции, переписывающей середину истории.

OpenCode Context Epoch — лучшее из существующих решений: неизменяемый базовый prefix. Но даже там нет дисциплины о том, **что именно** кладётся в cacheable-зону vs dynamic-зону.

**Противоречие (ТРИЗ):** контекст должен быть **стабильным** (для cache), и контекст должен быть **свежим** (содержать актуальные данные).

## Решение

Принять **строгую дисциплину layout'а контекста**, разделяющую его на 4 зоны с разной стабильностью:

```
+-------------------------------------------------+
| Zone A: ETERNAL PREFIX (cacheable, never changes)
|   - identity (who am I)
|   - tool schemas (registry)
|   - global policies (permissions, language)
|-------------------------------------------------|
| Zone B: SESSION PREFIX (cacheable, per-session)
|   - project summary (LSP snapshot at session start)
|   - user preferences (memory.md)
|   - coding style guide
|-------------------------------------------------|
| Zone C: EPOCH PREFIX (cacheable, per-epoch)
|   - mid-conversation system message (compacted)
|   - active plan (current task decomposition)
|   - success criteria
|-------------------------------------------------|
| Zone D: DYNAMIC TAIL (not cached, per-turn)
|   - HOT context (current symbols/diffs)
|   - latest user message
|   - latest tool results
+-------------------------------------------------+
```

### Правила дисциплины

1. **Zone A — константна внутри major version агента.** Меняется только при обновлении кода агента. Cache hit: 100% внутри сессии.
2. **Zone B — константна внутри сессии.** Устанавливается при старте сессии (snapshot LSP, prefs). Cache hit: 100% после первого хода.
3. **Zone C — обновляется на границах epoch'ов** (см. ADR-0010). Внутри epoch'а — константна. Cache hit: 80–95% внутри epoch'а.
4. **Zone D — полностью динамическая.** Cache hit: 0% по определению. Это «хвост» запроса.

### Cache-breakpoint placement

Используем `cache_control: { type: 'ephemeral' }` (Anthropic-style) или эквивалент на других провайдерах:

- После Zone A: breakpoint 1.
- После Zone B: breakpoint 2.
- После Zone C: breakpoint 3.
- Zone D — без breakpoint.

При следующем ходе, если Zone C не изменилась — breakpoint 3 остаётся валидным, и зона D — единственное, что пересчитывается.

### Что НЕ кладём в cacheable зоны

- Timestamp / current time / current date — только в Zone D.
- Git status / git diff — только в Zone D (меняется каждый ход).
- LSP diagnostics — только в Zone D (меняется при каждом didSave).
- Active plan — в Zone C, но только как compact representation; при изменении plan — новый epoch.
- HOT context — всегда Zone D.

### Mid-conversation system message

В конце каждого хода (после tester-фазы) компактор формирует **summary** того, что сделано в этом ходе, и кладёт его как **mid-conversation system message** с `cache_control: ephemeral`. На следующем ходе этот summary — часть Zone C. Когда Zone C накапливает 4–8 K токенов — компактор сжимает её снова (старые summaries → новый summary), открывая новый epoch.

## Положительные последствия

- **Cache hit 80–95%** на типичной сессии (vs 20–40% у SOTA).
- **Cost reduction 5–20×** на input tokens (cache hit дешевле).
- **Latency reduction 2–4×** на input processing (провайдеры обрабатывают cached prefix быстрее).
- **Predictable cost** — легко считать бюджет сессии заранее.

## Отрицательные последствия

- **Дисциплина.** Разработчик инструмента или hook'а не должен вставлять динамические данные в Zone A/B/C. Решение: lint на dev-time, проверяющий placement.
- **Compaction как edge case.** Если компактор меняет Zone C в середине хода (не на границе) — cache инвалидируется. Решение: компакция только на границах ходов (см. ADR-0010).
- **Multi-provider нюансы.** Разные провайдеры — разные cache-механизмы (Anthropic `cache_control`, OpenAI automatic, DeepSeek automatic). Решение: provider-seam абстрагирует; но semantics — близкие.

## Альтернативы

1. **Без дисциплины** (как многие SOTA). Отвергнуто: cache hit 20–40% — это даром потерянные деньги и latency.
2. **Только Zone A + Zone D** (нет Zone B/C). Отвергнуто: теряем cache на project-specific data.
3. **Auto-cache без layout-дисциплины** (полагаемся на auto-cache провайдера). Отвергнуто: auto-cache работает хуже явного placement'а; нет контроля.
4. **Compaction в середине хода.** Отвергнуто: ломает cache; только на границах.

## Применённый ТРИЗ-принцип

- **Principle 17 — Another Dimension.** Контекст имеет измерение «стабильность» — четыре зоны с разной изменчивостью.
- **Principle 15 — Dynamicity.** Динамические данные изолированы в Zone D; статичные — в A/B/C.
- **Principle 32 — Optical Changes.** Mid-conversation system message меняет «оптические» свойства контекста (cache-breakpoint location) без изменения семантики.
- **Principle 2 — Taking Out.** Динамические данные «вынесены» в конец запроса, не смешаны со статичными.

## Идеальный финальный результат (IFR)

Cache hit → 100% для всего, кроме того, что действительно изменилось в этом ходе. Cost и latency масштабируются только с изменениями, а не с размером сессии.
