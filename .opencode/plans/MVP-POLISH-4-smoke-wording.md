# Plan: MVP-POLISH-4 — Reconcile M-18 smoke parametrization vs DoD wording

**Status:** executed
**Commit message:** `MVP-POLISH-4: reconcile M-18 smoke spec wording (fake-model suite; providers -> integration)`
**User decisions:** план не запрашивался (полиш-тикет — документная правка); реализация smoke не меняется, правится только `analytics/PROMPT_MVP.md`.

## Problem

`analytics/PROMPT_MVP.md` (канонический спек) противоречил исполненной реальности M-18 (`.opencode/plans/M-18-smoke-tests.md`, строка 14 — задокументированное отклонение):

- §10 (структура): `test_smoke.py # M-18: 5 эталонных задач (параметризованный по провайдерам)` — фактически параметризации нет: отдельные именованные тесты на scripted `FakeMessagesListChatModel` (Forbidden pattern BACKLOG4: real LLM запрещены в smoke).
- §6 DoD: «smoke-тест проходит минимум на 5 провайдерах» и «Smoke-тесты 5/5 проходят на default провайдере (Anthropic)» — smoke никогда не ходил во внешние API; live-провайдерпокрытие живёт в `tests/integration/test_provider_*.py` (7 файлов, skip через `require_env` из `tests/integration/_helpers.py`).
- Счётчик «5/5» устарел: после M-25..M-27 suite = 10 тестов (5 canonical + 3 BACKLOG5 + 2 M-27).

## Result (правки только в `analytics/PROMPT_MVP.md`)

| Место | Было | Стало |
|---|---|---|
| §3.6 M-18 | 5 сценариев + «проверки /learn, /memory/stats…» | детерминированный fake-model suite без параметризации по провайдерам; 5 canonical + 3 v5-проверки + 2 memory-проверки = 10 тестов; провайдеры → integration |
| §5 NFR | `Smoke-тестов проходит \| 5/5` | `10/10 (5 эталонных задач + 5 расширенных)` |
| §6 DoD, мультипровайдерность | smoke проходит на 5 провайдерах; `skipif(DEEPSEEK_API_KEY)` | live-проверка tool-calling ≥5 провайдеров в `tests/integration/test_provider_*.py` через `require_env`; smoke real LLM не вызывает |
| §6 DoD, smoke | 5/5 на default провайдере (Anthropic) | 10/10 детерминированно без API-ключа (fake model) |
| §8 Риски | «тесты на 5+ провайдерах в smoke»; «skip-флаг для external-providers в CI» | провайдерпокрытие → integration; smoke flakiness mitigation = fake model, без внешних API |
| §10 дерево | «5 эталонных задач (параметризованный по провайдерам)» | «5 эталонных задач + 3 v5-проверки + 2 memory-проверки (fake model; провайдеры — в integration)» |
| §12 Exit criteria | «README + 5 smoke-тестов в CI green» | «README + smoke-тесты в CI green (10/10 …)» |

Не тронуто (сознательно): «5 эталонных задач» как метрика canonical-сценариев (§1, §9 Forbidden, §11 неделя 3.5) — она соответствует реальности; строка «4 файла» L0 в §12 относится к MVP-POLISH-6.

## Verified

- `uv run pytest tests/smoke -q` → **10 passed in 7.47s** (подтверждает 10/10 из новой формулировки DoD).
- Код и тесты не менялись → lint-гейт не применим (нет Python-диффа).
