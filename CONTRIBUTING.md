# Contributing to OryaAgent

Thanks for your interest! This is a short guide. Read [AGENTS.md](./AGENTS.md) for the full architecture conventions.

## Quick start

```bash
git clone https://github.com/Reider85/OryaAgent.git
cd OryaAgent
uv sync
docker compose up -d postgres redis
make db-migrate
make dev          # FastAPI on :8000
# в другом терминале:
make ui           # Chainlit on :8001
```

## Before you commit

```bash
make format       # ruff format .
make lint         # ruff check . && ruff format --check .
make test         # uv run pytest
```

CI прогоняет то же самое на каждый PR — если локально зелёно, скорее всего зелёно и в CI.

## Commit convention

- Ticket-based: `M-13: permissions (fail-closed on missing checkpointer)` или `A-20: connection pool (...)`
- Для не-тикетных правок: `chore: ...`, `docs: ...`, `refactor: ...`, `fix: ...`, `ci: ...`
- Одна логическая change = один коммит

## Code style

- Ruff: line-length 88, double quotes, isort, ignore E501/B904/W191/B008
- Без mypy / pyright — пока не добавили
- Модули начинаются с docstring с ticket id: `"""Tool: write - atomic file writer (M-08).`

## Adding things

- **New tool** — 5 шагов из AGENTS.md (app/tools/<name>.py + __init__ re-export + get_tools() + integration test + unit test)
- **New prompt section** — `*_block()` → append в `build_system_prompt` + тест в `tests/unit/test_prompt.py`
- **New LLM provider** — только YAML в `providers.yaml` / `models.yaml` / `capabilities.yaml` / `pricing.yaml` (это YAML-only по архитектуре)
- **Schema change** — три правки: `schema.sql` + новый `migrations/NNNN_*.sql` + `alembic/versions/NNNN_*.py` wrapper (тесты `test_db_schema.py` + `test_alembic.py` ловят расхождения)

## Tests

| Suite | Что тестирует | Когда запускать |
|---|---|---|
| `tests/unit` | чистая логика, без инфры | всегда |
| `tests/e2e` | round trips с фейковой моделью | всегда |
| `tests/smoke` | канонические задачи | всегда |
| `tests/integration` | postgres/redis | после `docker compose up -d postgres redis` |

## Reporting bugs / features

Используй шаблоны в Issues — они подскажут, какие данные нужны.