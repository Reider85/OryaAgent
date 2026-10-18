# ADR-0009: Streaming + Early Exit — стриминг токенов и прерывание по тестам

**Дата:** 2026-10-18
**Статус:** Proposed
**Связанные ADR:** ADR-0003 (tri-model), ADR-0006 (parallel tools), ADR-0011 (batch)

## Контекст

В типичном SOTA-агенте пользовательский опыт выглядит так: пользователь пишет промпт → ждёт 5–30 секунд без обратной связи → видит результат. Это плохо по двум причинам:

1. **Perceived latency >> actual latency.** Мозг воспринимает «ожидание без обратной связи» как более долгое, чем то же время с прогрессом.
2. **Трата cycles.** Если агент уже понял, что задача провалена (тесты не прошли, lint упал), он всё равно продолжает генерировать ответ — тратя токены и время.

Существующие агенты делают streaming-output (токены печатаются по мере генерации) — но не делают **early-exit**. Early-exit — это прерывание генерации, когда:
- Тесты уже упали и нет смысла продолжать.
- Executor уже выдал валидный tool-call — можно запустить его выполнение параллельно с продолжением генерации (если модель умеет выдавать несколько tool-calls).
- Пользователь уже видит достаточно ответа и нажал «stop».

**Противоречие (ТРИЗ):** модель должна **додумывать до конца** (для полноты ответа), и модель должна **прерываться** (для экономии, когда продолжение бесполезно).

## Решение

Ввести **трёхуровневый streaming + early-exit**:

### Уровень 1 — Token streaming (UX)

Каждый токен от модели стримится в TUI немедленно. Пользователь видит прогресс с первого токена (~200 ms после старта фазы). Это базовый UX, есть у многих SOTA.

### Уровень 2 — Tool-call streaming (parallelism)

Как только в stream'е распознан **полный tool-call** (модель завершила генерировать аргументы), мы:
1. **Немедленно запускаем его выполнение** (см. ADR-0006) — не дожидаясь остальных tool-calls или завершения генерации.
2. Продолжаем парсить stream — следующие tool-calls тоже стартуют сразу.
3. Когда модель завершила генерацию — все tool-calls уже в полёте.

Это экономит 200–1500 ms на типичном ходе с 3–5 tool-calls.

### Уровень 3 — Early-exit на test-pass / test-fail (cost saver)

В tri-model pipeline (ADR-0003), после executor'а идёт tester. Но tester может запуститься **до завершения executor'а**, если:

- Executor уже выдал **итоговый diff** через специальный tool-call `submit_diff(diff)` — это явный сигнал «я закончил».
- Executor вызвал `bash(run tests)` и тесты **упали** — мы знаем, что ход провален, можно прервать генерацию (если она ещё идёт).
- Executor вызвал `bash(run tests)` и тесты **прошли** — можно прервать «додумывание» и сразу перейти к tester-фазе.

**AbortController** на каждой фазе:
- Planner: abort по Ctrl+C пользователем.
- Executor: abort по Ctrl+C / по test-fail / по явному `submit_diff`.
- Tester: abort по Ctrl+C.

```typescript
async function runExecutor(plan, hot, signal: AbortSignal): Promise<Diff> {
  const stream = llm.complete({ ..., signal });
  for await (const event of stream) {
    if (signal.aborted) throw new AbortError();
    
    if (event.type === 'tool_call') {
      const result = await executeTool(event.call);
      
      // Early-exit triggers
      if (event.call.name === 'submit_diff') {
        return event.call.args.diff;  // exit immediately
      }
      if (event.call.name === 'bash' && result.isTestRun && result.failed) {
        signal.abort();  // stop generation, go to tester with what we have
        return partialDiff();
      }
    }
  }
}
```

### Streaming в batch pipeline

В batch-режиме (ADR-0011) early-exit ещё ценнее: если 100 промптов в очереди и 20 из них провалились на раннем тесте — мы не тратим cycles на их «додумывание».

## Положительные последствия

- **Perceived latency падает.** Пользователь видит первый токен за 200 ms, не за 5 s.
- **Cost на проваленных ходах падает на 30–70%.** Мы не «додумываем» то, что уже провалилось.
- **Parallelism tool-execution максимален.** Tool-calls стартуют до завершения генерации.
- **UX:** пользователь может прервать в любой момент, не дожидаясь конца.

## Отрицательные последствия

- **Сложность stream-парсинга.** Нужно надёжно распознавать конец tool-call в stream'е. Решение: форматированный output (function-call protocol) у большинства провайдеров это уже даёт.
- **Partial-diff в tester.** Если мы прервали executor по test-fail, tester получает partial-diff — нужно корректно это обработать. Решение: tester знает, что diff может быть partial, и проверяет только то, что есть.
- **Abort не мгновенный.** LLM-провайдер может держать connection ещё 100–500 ms после abort. Решение: клиентский AbortController прерывает stream немедленно, server-side cleanup — в фоне.

## Альтернативы

1. **Без streaming** (дождаться финала, показать весь ответ). Отвергнуто: perceived latency 5–30 s без обратной связи.
2. **Streaming без early-exit.** Отвергнуто: тратим cycles на проваленных ходах.
3. **Early-exit только по Ctrl+C.** Отвергнуто: теряем automatic early-exit на test-fail.
4. **Always wait for full generation, then test.** Отвергнуто: latency + cost без причины.

## Применённый ТРИЗ-принцип

- **Principle 20 — Continuity of Useful Action.** Никаких простоев: tool-calls стартуют, пока модель генерирует.
- **Principle 21 — Skipping.** Early-exit «перепрыгивает» через остаток генерации, когда он бесполезен.
- **Principle 9 — Preliminary Anti-Action.** Abort на test-fail — предварительная анти-действие против траты cycles.
- **Principle 15 — Dynamicity.** Динамический контроль: abort может сработать в любой момент, не только в конце.

## Идеальный финальный результат (IFR)

Модель работает ровно столько, сколько нужно. Первый токен — мгновенно. Last token — как только задача реально решена или провалена. Никаких «додумываний для галочки».
