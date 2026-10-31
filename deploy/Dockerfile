# syntax=docker/dockerfile:1
# A-10: OryaAgent runtime image — one image, two commands:
#   api       → uvicorn app.main:app (default CMD)
#   chainlit  → chainlit run app/ui/chainlit_app.py (compose overrides `command`)
# Python 3.12 matches the repo venv (pyproject floor is 3.11). ripgrep is a hard
# runtime dependency of the grep/glob tools (app/tools/_rg.py).

FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS builder

WORKDIR /app

ENV UV_FROZEN=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

# Dependency layer first: only pyproject/uv.lock/README change rarely.
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --no-dev --no-install-project

# Project layer: the `app` package (providers YAML included) + console scripts
# + alembic wiring (alembic.ini, alembic/) — the api container runs
# `orya db migrate` on start (A-11).
COPY app ./app
COPY alembic.ini ./
COPY alembic ./alembic
RUN uv sync --no-dev

FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

WORKDIR /app

# ripgrep → grep/glob tools; libpq → psycopg (langgraph-checkpoint-postgres)
# runs the pure-python implementation against the system libpq.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ripgrep libpq5 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /app /app

ENV PATH="/app/.venv/bin:$PATH"

EXPOSE 8000 8001

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
