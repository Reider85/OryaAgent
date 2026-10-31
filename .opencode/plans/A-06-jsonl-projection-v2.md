# A-06 — JSONL projection v2 (with span-ids)

> Ticket: `PROMPT_ALPHA.md` §3.1 (A-06) | Estimate: 4 часа | Status: executed

## Spec summary

«JSONL projection v2 (with span-ids) | 4 часа | cross-link с Langfuse traces» —
одна строка в таблице тикетов PROMPT_ALPHA.md:77 (детальной секции для A-06
в PROMPT_ALPHA/BACKLOG6 нет; BACKLOG6 §3 содержит только A-16/A-17).
Legacy A-06 «Secret-management» из BACKLOG4/5 — устаревшая нумерация
v4/v5, к v6/v7 ALPHA отношения не имеет. Расшифровка: события JSONL-проеции
получают observability id (`trace_id`/`span_id`), по которым session-log
строка джойнится с Langfuse trace/span (A-15/A-16 экспортёры используют
те же id из `SpanRecord`).

## Deviations & decisions

1. **Корреляция — штамп на сообщениях, а не чтение span-буфера.**
   Span-ids пишутся в `BaseMessage.additional_kwargs["orya_span"]` в точках
   происхождения (LLM-шов, tools-node). `additional_kwargs` сериализуется
   LangGraph-checkpointer'ом, поэтому id переживают персистентность, а
   delta-проекция (M-14) подхватывает их при обычном обходе checkpoint'ов.
   Альтернатива (дрейн in-process буфера воркером) отвергнута: буфер
   ограничен (1000) и живёт в процессе, а воркер проецирует через 30 сек.
2. **Turn-trace contextvar = Langfuse trace.** `set_turn_trace` в
   `stream_graph_events`/`resume_graph_events` (agent.py) — один свежий
   `trace_id` на ход; `_new_ids()` всех span-создателей (A-02 llm.call,
   A-03 agent.permission) переиспует его как `trace_id`. Вне хода
   поведение прежнее (уникальный случайный trace на span).
3. **Разделение ролей ключей:** ai-события — полный штамп
   `{trace_id, span_id}` (из TracedChatModel); user/tool-события — только
   корень хода `{trace_id}` (штамп в agent.py на HumanMessage и в
   graph.py на ToolMessage после ToolNode). `span_id` tool-событий
   придёт с A-16 (`agent.tool` spans) — follow-up.
4. **Reset contextvar'а — запись `None`, не токен** (паттерн
   `_stream_in_workspace`, sessions.py): SSE-стрим может гоняться из
   нескольких task-контекстов.
5. **Формат v2 — только additive.** Top-level опциональные ключи
   `trace_id`/`span_id`; v1-события и все читатели (`learn.load_events`,
   `ui/sessions`) не меняются (везде `.get()`). Валидация ключа —
   `isinstance(dict)` (мусорный штамп игнорируется).
6. **Ноль новой конфигурации.** Ни одного нового env: штамп существует
   ровно тогда, когда включены A-02 (`ORYA_LLM_TRACE_ENABLED`, default on)
   и/или A-03 (`ORYA_PERMISSION_AUDIT_ENABLED`). Kill-switch off →
   raw-модель → штампа нет — как и раньше.
7. **Схема БД не меняется** — JSONL/`.meta.json` форматы прежние по
   структуре; дрейф-тест schema.sql не затронут.
8. **tools-node — тонкая обёртка** (`raw_tool_node.ainvoke` →
   `_stamp_tool_messages`): ToolNode остаётся исполнителем M-12/M-28
   (`handle_tool_errors=tool_error_text`), обёртка только штампует
   возвращённые ToolMessage до checkpoint'инга.
9. **Аннотация `config: Optional[RunnableConfig]` в tools_node** — не
   стилистика, а требование langgraph: при `from __future__ import
   annotations` сканер сигнатур матчит *строку* аннотации, и
   `"RunnableConfig | None"` в список допустимых не входит (только
   `"RunnableConfig"` / `"Optional[RunnableConfig]"`) — иначе config не
   инжектится в ноду (`# noqa: UP045` на месте).

## Files

- `app/core/observability/spans.py` — `_turn_trace_id` ContextVar,
  `set_turn_trace` / `current_turn_trace_id` / `new_trace_id`;
  `_new_ids()` переиспует turn trace; `ORYA_SPAN_KEY = "orya_span"`.
- `app/core/llm/tracing.py` — `_stamp_span()`; вызов в
  `TracedChatModel.invoke`/`ainvoke` после `_attach_usage`.
- `app/core/agent.py` — `set_turn_trace(new_trace_id())` + `_stamp_turn()`
  на HumanMessage в `stream_graph_events`; bind в `resume_graph_events`;
  reset `None` в `finally`.
- `app/core/graph.py` — `_stamp_tool_messages()` + `tools_node`-обёртка
  вокруг `ToolNode`.
- `app/db/session_log.py` — `_span_stamp()`; `_message_event()` (v2)
  пишет top-level `trace_id`/`span_id`; docstring описывает v2.
- `tests/unit/test_turn_trace.py` (new) — contextvar-контракт.
- `tests/unit/test_llm_tracing.py` — штамп ai-сообщений, turn-trace
  reuse, не-Message скипается; fixture чистит turn trace.
- `tests/unit/test_session_log.py` — v2-ключи в проекции, v1-совместимость,
  `_span_stamp` edge-cases.
- `tests/unit/test_permission_audit.py` — permission-span наследует
  turn trace.
- `tests/unit/test_graph.py` — ToolMessage штампуется внутри хода,
  без turn trace — v1-форма.
- `tests/unit/test_agent_runtime.py` — bind/clear turn trace в
  `stream_graph_events`/`resume_graph_events`, штамп HumanMessage.
- `tests/unit/test_api_health.py` — drive-by: autouse-фикстура чистит
  span-буфер (прецедент на main: smoke/e2e оставляли 10 span'ов, и
  `span_buffer_size == 0` падал в полном прогоне — воспроизводится и без
  правок A-06).
- `.opencode/plans/A-06-jsonl-projection-v2.md` (this file).

## Verification

`make format` → `make lint` → `uv run pytest`.

## DoD coverage

- ✅ Каждое ai-событие JSONL несёт `trace_id`+`span_id` llm.call span'а.
- ✅ Каждое user/tool-событие хода несёт общий `trace_id` (джойн всего
  хода с одним Langfuse trace'ом).
- ✅ Все span'ы одного хода (llm.call, agent.permission) делят один
  `trace_id`; вне хода — прежнее поведение.
- ✅ v1-события/файлы читаются без изменений; у нештампованных сообщений
  новых ключей нет.
- ✅ Ноль новой конфигурации; поведение при выключенных kill-switch'ах
  не меняется.
- ✅ `make format` → `make lint` → `uv run pytest` pass.

## Follow-ups

- A-16 `agent.tool` spans: ToolMessage получит и `span_id`.
- Экспортёры (A-15/A-16) обязаны публиковать `SpanRecord.trace_id/span_id`
  как есть — иначе cross-link разрывается.
- System-сообщения permission-log (sessions.py) — кросс-линк с
  agent.permission span'ом отдельным тикетом.
- Периодический trim JSONL / file permissions 0600 (лежит в A-05 follow-ups).
