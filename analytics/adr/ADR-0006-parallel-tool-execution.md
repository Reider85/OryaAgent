# ADR-0006: Parallel Tool Execution with Bounded Concurrency

**Дата:** 2026-10-18
**Статус:** Proposed
**Связанные ADR:** ADR-0002 (LSP), ADR-0003 (tri-model), ADR-0012 (caching)

## Контекст

Все 5 SOTA-агентов выполняют tool-calls преимущественно последовательно. Даже когда модель выдаёт несколько tool-calls в одном ответе, харнесс часто выполняет их по одному (или с очень слабым параллелизмом). Это значит:

- Если executor запросил 4 файла и 3 LSP-запроса, время выполнения = сумма, а не максимум.
- Latency-tool-execution часто доминирует над LLM-latency на задачах с большим контекстом.
- LSP-серверы (см. ADR-0002) могут обрабатывать запросы параллельно (JSON-RPC batch / multiple in-flight requests), но агент не использует это.

Пример: executor хочет прочитать сигнатуру функции, её references и definition. Это три независимых LSP-запроса. Последовательно: 3 × 5 ms = 15 ms. Параллельно: max(5, 5, 5) = 5 ms. На 10 подобных запросов за ход — разница 100 ms vs 50 ms, но на больших задачах с десятками tool-calls — секунды.

**Противоречие (ТРИЗ):** tool execution должен быть **быстрым** (параллельным), и tool execution должен быть **предсказуемым и безопасным** (последовательные зависимости).

## Решение

Ввести **параллельный tool-executor с bounded concurrency**:

### Правила

1. **Все tool-calls в одном LLM-ответе выполняются параллельно** по умолчанию.
2. **Bounded concurrency:** лимит одновременно выполняющихся tool-calls (по умолчанию 8; настраивается). Если модель запросила 20 — выполняются пачками по 8.
3. **Зависимости — через явные барьеры.** Если ход требует «сначала прочитай X, потом отредактируй на основе X», модель делает это в **двух отдельных LLM-итерациях** (executor → tool-results → executor). Это явно моделируется, а не прячется в scheduler.
4. **Идемпотентные tools** (`read`, `grep`, `symbol.hover`, `symbol.def`, `symbol.refs`, `semantic.search`) — безусловно параллельны.
5. **Side-effect tools** (`write`, `edit`, `bash`, `rename`) — по умолчанию последовательны в пределах хода, если модель явно не пометила `parallel: true` в tool-call (для safe-operations типа `write` в разные файлы).

### Реализация

```typescript
async function executeToolCalls(calls: ToolCall[], ctx: ToolContext): Promise<ToolResult[]> {
  // 1. Group by parallel-safety
  const groups = groupByParallelSafety(calls);
  
  // 2. Within each group, run in parallel with bounded concurrency
  const results: ToolResult[] = [];
  for (const group of groups) {
    const chunked = chunk(group, ctx.config.maxConcurrency); // default 8
    for (const chunk of chunked) {
      const chunkResults = await Promise.all(
        chunk.map(c => executeSingle(c, ctx).catch(e => toErrorResult(c, e)))
      );
      results.push(...chunkResults);
    }
  }
  return results;
}
```

### LSP batch

Для LSP-запросов — использовать **JSON-RPC batch** где возможно (LSP spec поддерживает). Один round-trip для N запросов вместо N round-trips. Не все LSP-серверы поддерживают batch одинаково хорошо; fallback — параллельные individual requests с bounded concurrency.

### Tool-call streaming

Модель стримит tool-calls. Как только мы распознали полный tool-call в stream, мы **немедленно запускаем его выполнение**, не дожидаясь завершения генерации. Это особенно полезно для planner-фазы (которая стримит prefetch-hints — см. ADR-0004) и для executor'а, который может выдать 5–10 tool-calls в одном ответе.

## Положительные последствия

- **Latency на tool-heavy ходах падает в 3–8 раз.** 10 параллельных LSP-запросов = max latency одного, а не сумма.
- **LSP-сервер используется эффективнее.** gopls/rust-analyzer уже оптимизированы под parallel requests.
- **Streaming-start:** первый tool-call стартует до завершения генерации модели — экономит 200–800 ms на больших tool-batches.
- **Predictable concurrency:** bounded limit предотвращает fork-bomb (модель может выдать 50 tool-calls — мы это переживём).

## Отрицательные последствия

- **Race conditions на side-effects.** Если модель ошибочно пометила `write` в один и тот же файл как `parallel: true` — будет потеря данных. Решение: static-analysis на tool-calls перед execution — конфликты по path автоматически переводятся в sequential.
- **Сложность отладки.** Параллельные tool-calls труднее читать в логах. Решение: каждый tool-call имеет monotonic ID; в логе — ordered by start-time, с явной пометкой parallel-group.
- **Не все инструменты хорошо параллелятся.** Например, `bash` с state (cd, env) — sequential по природе. Решение: tool-declared concurrency-class.

## Альтернативы

1. **Полностью последовательное выполнение** (как многие SOTA). Отвергнуто: теряем 3–8× на tool-heavy ходах.
2. **Неограниченный parallelism.** Отвергнуто: fork-bomb риск, и LLM-провайдеры всё равно имеют rate-limits.
3. **Автоматическое определение зависимостей.** Идея: статически анализировать tool-calls, строить DAG, выполнять топологически. Отвергнуто как over-engineering: модель сама должна декомпозировать (через две LLM-итерации), это её работа.
4. **Только LSP batch, не общий parallel.** Отвергнуто:.read и grep тоже хорошо параллелятся.

## Применённый ТРИЗ-принцип

- **Principle 20 — Continuity of Useful Action.** Никаких простоев: пока один tool выполняется, другие тоже выполняются.
- **Principle 10 — Preliminary Action.** Tool-call стартует до завершения генерации — мы «предварительно» начинаем выполнение.
- **Principle 35 — Parameter Change.** Смена режима: parallel для idempotent, sequential для side-effects — параметризация по tool-class.
- **Principle 11 — Beforehand Cushioning.** Bounded concurrency — заранее ограниченный ресурс, защищающий от перегрузки.

## Идеальный финальный результат (IFR)

Все независимые tool-calls выполняются за время самого медленного, а не за сумму. Модель не ждёт tools — tools не ждут друг друга (если независимы).
