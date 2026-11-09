## Summary

<!-- 1-2 sentences: what does this PR do? -->

## Type of change

- [ ] Bug fix (non-breaking)
- [ ] New feature (non-breaking)
- [ ] Breaking change (fix or feature that would cause existing functionality to not work as expected)
- [ ] Documentation
- [ ] Refactor / chore

## Checklist

- [ ] `make lint` passes (`ruff check . && ruff format --check .`)
- [ ] `make test` passes (`uv run pytest tests/unit tests/e2e tests/smoke`)
- [ ] If schema change: updated `schema.sql` + new `migrations/NNNN_*.sql` + `alembic/versions/NNNN_*.py` wrapper
- [ ] If new tool: 5 steps from AGENTS.md (app/tools/<name>.py + __init__ + get_tools() + integration test + unit test)
- [ ] If new LLM provider: only YAML in `providers.yaml` / `models.yaml` / `capabilities.yaml` / `pricing.yaml`
- [ ] Commits follow `M-NN: <subject>` or `A-NN: <subject>` convention from AGENTS.md

## Related

<!-- Issues, tickets, plans. Example: Closes #42. Plan: .opencode/plans/A-21-*.md -->