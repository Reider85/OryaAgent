"""Unit tests for A-09 — README v2 section anchors and env-var coverage."""

from __future__ import annotations

from pathlib import Path

from pydantic import AliasChoices

from app.core.config import Settings

README_PATH = Path(__file__).parents[2] / "README.md"


def _readme() -> str:
    return README_PATH.read_text(encoding="utf-8")


REQUIRED_HEADINGS = (
    "## Phase: ALPHA",
    "## Deploy guide",
    "### Docker services (today)",
    "### Production checklist",
    "### Langfuse setup (planned",
    "## Environment variables",
    "## Authentication (A-00)",
    "## Rate limiting (A-01)",
    "## Health endpoints (A-04)",
    "## LLM tracing & audit spans (A-02, A-03)",
    "### Encryption at rest (A-05)",
    "### Span cross-link (A-06)",
    "### One-command start",
)

CRITICAL_ENV_VARS = (
    "AUTH_ENABLED",
    "AUTH_SECRET_KEY",
    "RATE_LIMIT_RPM",
    "ORYA_SESSION_LOG_ENCRYPTION_KEY",
    "ORYA_LLM_TRACE_ENABLED",
    "ORYA_SAMPLER_PROXY_URL",
    "DATABASE_URL",
    "REDIS_URL",
    "ORYA_TRUSTED_CLIENTS",
    "LANGFUSE_HOST",
)


def test_readme_has_required_headings():
    text = _readme()
    for heading in REQUIRED_HEADINGS:
        assert heading in text, f"README is missing heading: {heading}"


def test_readme_documents_operator_loop_and_deploy_markers():
    text = _readme()
    assert "orya auth token" in text, "operator loop (CLI token minting) not documented"
    assert "Authorization: Bearer" in text, "Bearer auth curl example missing"
    assert "scripts/start.sh" in text, "one-command start script missing"
    assert "docker compose" in text.lower(), "docker deploy story missing"
    assert "maxmemory" in text, (
        "Redis server-side maxmemory prod note missing (A-07 follow-up)"
    )


def test_readme_langfuse_section_is_forward_looking():
    text = _readme()
    assert "LANGFUSE_HOST" in text
    assert "A-15" in text, "Langfuse section must mark the planned tickets"
    section = text.split("### Langfuse setup", 1)[1]
    assert "not wired yet" in section or "Planned env contract" in section


def test_readme_phase_progress_covers_alpha_tickets():
    text = _readme()
    for i in range(9):
        marker = f"**A-0{i}**"
        assert marker in text, f"Phase Progress is missing {marker}"


def test_readme_documents_critical_env_vars():
    text = _readme()
    for var in CRITICAL_ENV_VARS:
        assert var in text, f"Environment variables section is missing {var}"


def _env_aliases_by_field() -> dict[str, list[str]]:
    """Env spellings recognised per Settings field (AliasChoices + Field(env=...))."""
    out: dict[str, list[str]] = {}
    for name, field in Settings.model_fields.items():
        choices: list[str] = []
        alias = field.validation_alias
        if isinstance(alias, AliasChoices):
            choices.extend(c for c in alias.choices if isinstance(c, str))
        extra = field.json_schema_extra
        if isinstance(extra, dict) and isinstance(extra.get("env"), list):
            choices.extend(str(item) for item in extra["env"])
        if choices:
            out[name] = choices
    return out


def test_readme_documents_every_settings_env_field():
    """Every env-recognised Settings field must appear in the README table."""
    text = _readme()
    missing = sorted(
        field
        for field, aliases in _env_aliases_by_field().items()
        if not any(alias in text for alias in aliases)
    )
    assert not missing, f"Settings fields missing from README env reference: {missing}"
