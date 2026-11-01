# A-16 — OryaObservability SDK (instrument LangGraph)

> Ticket: `analytics/BACKLOG6.md` §3 A-16 (детальная спека v6) + `analytics/PROMPT_ALPHA.md` §3.1 | Estimate: 1 день | Status: executed

## Spec summary

OryaObservability SDK-интеграция: PII-маскирование в span-атрибутах (fail-closed),
`agent.loop` / `tool.call` / `memory.write` custom spans поверх готового
`emit_span`-шва (A-02/A-03), опциональная установка `agent-obs` из sibling
`../OryaObservability`, kill-switch `AGENT_OBS_ENABLED`.

## Approved decisions (user, 2026-11-01)

1. **Bridge-архитектура.** `agent_obs` подключается компонентами
   (PIIDetector, SpanType-конвенции, атрибуты), НЕ как ObservabilitySDK-pipeline:
   ULID-id SDK несовместимы с нашими W3C-hex (A-06 cross-link + A-15 exporter
   `_to_hex` в `agent_obs/exporters/langfuse_exporter.py:63` интерпретировал бы
   hex как base32). A-15 hand-rolled exporter остаётся путём экспорта.
2. **Sibling pyproject похудеть:** тяжёлые deps (torch/spacy/transformers/
   presidio) → extras `[ml]`/`[storage]`; sampler-образ не затронет
   (`scripts/sampler/Dockerfile:10-15` ставит requirements.txt + COPY).
3. **`agent.plan` / `agent.execute` не эмитить до BETA** — планировщика нет
   (#19), tier появится в A-18. Осознанное отклонение от PROMPT_ALPHA v7-сводки;
   реализуется v6-спека (agent.loop/tool.call/memory.write).

## Deviations from spec

| Спека | Решение |
|---|---|
| `ObservabilitySDK` как пайплайн + `agent_observed`/`llm_call`/`tool_call` CMs | Не используется как пайплайн (решение 1). Наш `emit_span`/`TracedChatModel` остаются. |
| `pip install -e ../OryaObservability` в pyproject | Path-source в `uv.lock` ломает lock на машинах без sibling-checkout → opt-in вручную `uv pip install -e ../OryaObservability`; код — try-import; тесты — `importorskip`. |
| `price_book.yaml` + `agent_obs.cost.compute_cost` | Не дублируем: A-14 уже owns cost через `pricing.yaml` + `price_usd()` (executed plan overrides). |
| AC `tool.input`/`tool.output` | Имена реального SDK: `tool.input_summary` (≤200ч + hash + length, P22) и `tool.output_text` (`agent_obs/observability.py:1914`). |
| `instrument_graph(graph)` | В SDK метода нет — наш registrar: проверяет швы, возвращает graph; эмиссия живёт в нодах/драйвере. |
| Контент в llm.call | A-02-решение сохранено: контент только в `agent.loop.task.input` и tool io, оба маскируются. |
| Span-типы SDK (`agent.reasoning` и т.п.) | Не эмитим — вне спеки A-16. |

## Files

### Sibling (C:\projects\OryaObservability, отдельный коммит)
- `pyproject.toml` — hard deps → лёгкие (httpx, prometheus-client, pyyaml, pyotp, hvac, openpyxl, jsonschema); `[ml]` torch/spacy/transformers/presidio-analyzer; `[storage]` clickhouse-driver/redis/rq/numpy/psutil; `[full]` = ml+storage+openai; CI → `.[dev,full]`.

### OryaAgent
- `app/core/config.py` — `agent_obs_enabled`, `agent_obs_guardrail_enabled`.
- `app/core/observability/spans.py` — `emit_span(start_time=)`, `timed_span` CM.
- `app/core/observability/pii.py` (new) — `mask_text()` через PIIDetector, fail-closed.
- `app/core/observability/sdk.py` (new) — `OryaObservability`, `get_observability()`, `init_observability_sdk()`.
- `app/core/observability/__init__.py` — re-exports.
- `app/core/agent.py` — `agent.loop` span (stream + resume, после `set_turn_trace`, закрытие в `finally`).
- `app/core/graph.py` — `tool.call` span'ы в `tools_node`; `_stamp_tool_messages(..., span_ids=)`; фикс латентного бага batch-refusal (`graph.py:539-541` передаёт несуществующий kwarg `attributes=`).
- `app/api/learn.py` — `emit_memory_write(source="learn")`.
- `app/core/memory/compactor.py` — `emit_memory_write(source="compactor", compacted=true)`.
- `app/api/health.py` — `agent_obs_sdk_available`, `agent_obs_enabled`, `agent_obs_guardrail_enabled`.
- `app/main.py` — `init_observability_sdk()` рядом с `init_exporter()`.
- `.env.example`, `README.md`, `AGENTS.md`.
- `tests/unit/test_observability_sdk.py` (new) + обновления `test_api_health`, `test_readme`, `test_langfuse_exporter`, `test_agent_runtime`, `test_graph`.

## Verification

`ruff format` → `ruff check` → `uv run pytest`; opt-in прогон с
`uv pip install -e ../OryaObservability` (SDK-тесты с real PIIDetector).

## Results (2026-11-01)

- Sibling commit `22ee74c` (`../OryaObservability`): light deps + extras
  `[ml]`/`[storage]`/`[full]`, `agent_obs.eval` lazy (PEP 562) —
  `pip install -e ../OryaObservability` больше не тянет torch/spacy/fastapi;
  sampler-образ не затронут (requirements.txt + COPY).
- OryaAgent: 20 новых тестов (`tests/unit/test_observability_sdk.py`),
  +5 обновлённых (graph stamp, health keys, readme anchors/Phase Progress,
  langfuse OTLP-маппинг A-16-типов).
- Gate: `ruff format`/`check` чисто; полный `uv run pytest` = **1040 passed,
  24 skipped**; opt-in venv с agent-obs = **69 passed, 0 skipped** (реальный
  PIIDetector: email/phone-маски, `[EMAIL:]` в tool.input_summary), после
  `uv pip uninstall agent-obs` venv возвращён в дефолтное состояние.
- Попутный фикс: латентный баг `graph.py` — batch-refusal span эмитился
  с несуществующим kwarg `attributes=` (TypeError молча глотался) → `reason=`.
