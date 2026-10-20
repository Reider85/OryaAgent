.PHONY: dev test lint clean install

# Install dependencies
install:
	uv sync

# Development server
dev:
	uv run uvicorn app.main:app --reload --port 8000

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