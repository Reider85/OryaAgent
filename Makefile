.PHONY: dev ui test lint clean install format check-lint check-format setup db-up db-migrate db-downgrade db-current db-down redis-up redis-down stack-up stack-down

# Install dependencies
install:
	uv sync

# Development server
dev:
	uv run uvicorn app.main:app --reload --port 8000 --loop app.core.loop_factory:selector_loop_factory

# Chainlit UI (M-15) — port 8001 avoids clashing with `make dev` on 8000
ui:
	uv run chainlit run app/ui/chainlit_app.py --port $${CHAINLIT_PORT:-8001}

# Run tests
test:
	uv run pytest

# Lint and format
lint:
	uv run ruff check .
	uv run ruff format --check .

# Format code
format:
	uv run ruff format .

# Clean up
clean:
	rm -rf .venv/
	rm -rf dist/
	rm -rf build/
	find . -type f -name "*.pyc" -delete
	find . -type d -name "__pycache__" -delete
	find . -type d -name "*.egg-info" -exec rm -rf {} +

# Development setup
setup: install
	@echo "Development environment setup complete!"
	@echo "Run 'make dev' to start the development server"

# Quick lint check (no formatting)
check-lint:
	uv run ruff check .

# Quick format check (no linting)
check-format:
	uv run ruff format --check .

# Database (M-03, A-11: alembic-backed)
db-up:
	docker compose up -d postgres

db-migrate:
	uv run python -m app.db.migrate

# Rollback helpers (ROADMAP5 §18.2): make db-downgrade REV=base
db-downgrade:
	uv run python -m app.db.migrate downgrade $(REV)

db-current:
	uv run python -m app.db.migrate current

db-down:
	docker compose down

# Redis tool-cache (M-21)
redis-up:
	docker compose up -d redis

redis-down:
	docker compose stop redis

# Full compose stack (A-10): profiles from COMPOSE_PROFILES in .env
# (app,observability = api + chainlit + langfuse v3 + sampler-proxy)
stack-up:
	docker compose up -d --build

stack-down:
	docker compose --profile app --profile observability down