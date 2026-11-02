"""Unit tests for A-09 — README v2 section anchors and env-var coverage.

Anchors follow the README rewrite (commit 86bc3c3): emoji top-level
sections, per-topic env tables under Configuration, and the Roadmap
table as the phase-progress ledger.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import AliasChoices

from app.core.config import Settings

README_PATH = Path(__file__).parents[2] / "README.md"


def _readme() -> str:
    return README_PATH.read_text(encoding="utf-8")


REQUIRED_HEADINGS = (
    "Roadmap & Phases",
    "Deployment",
    "Docker Compose v2 (A-10)",
    "Production checklist (A-09 / A-12)",
    "Langfuse OTLP/HTTP JSON export (A-15)",
    "Configuration",
    "Auth (A-00)",
    "Rate limiting (A-01)",
    "Health endpoints (A-04)",
    "Tracing wrapper (A-02)",
    "Session-log encryption at rest (A-05)",
    "JSONL span cross-link (A-06)",
    "One-command start",
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
    "ORYA_ENV",
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


def test_readme_langfuse_section_documents_wiring():
    text = _readme()
    assert "LANGFUSE_HOST" in text
    section = text.split("### Langfuse OTLP/HTTP JSON export", 1)[1]
    assert "A-15" in section, "Langfuse section must reference the export ticket"
    assert "not wired" not in section, "A-15 wired the exporter — drop the old caveat"
    assert "api/public/otel/v1/traces" in section, "OTLP path must be documented"
    assert "ORYA_LANGFUSE_EXPORT_ENABLED" in section, "kill-switch must be documented"


def test_readme_phase_progress_covers_alpha_tickets():
    text = _readme()
    section = text.split("Roadmap & Phases", 1)[1]
    for i in range(21):  # A-00..A-20 (A-19 prompt cache, A-20 connection pool)
        marker = f"`A-{i:02d}`"
        assert marker in section, f"Roadmap is missing {marker}"


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
