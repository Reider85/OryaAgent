"""Unit tests for A-12 — ``orya config show|check`` (app.core.config_cli)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
import yaml

from app.core.config import clear_settings_cache
from app.core.config_cli import config_show_lines, run_config_check, run_config_show

# Env vars that must never leak from the developer machine / CI into tests.
_MANAGED_ENV_VARS = frozenset(
    {
        "DATABASE_URL",
        "REDIS_URL",
        "LOG_LEVEL",
        "PERMISSION_POLICY",
        "DATABASE_POOL_SIZE",
        "DATABASE_MAX_OVERFLOW",
        "AUTH_SECRET_KEY",
        "AUTH_ALGORITHM",
        "AUTH_ENABLED",
        "AUTH_TOKEN_TTL_S",
        "AUTH_PUBLIC_PATHS",
        "CORS_ORIGINS",
        "LANGSMITH_API_KEY",
        "OTEL_EXPORTER_OTLP_ENDPOINT",
        "ORIAHS_URL",
        "ORIAHS_TIMEOUT_S",
        "CHAINLIT_PORT",
        "NEXTJS_PORT",
    }
)


@pytest.fixture(autouse=True)
def isolated_config(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Sandbox every test: no inherited env, no repo .env, temp config.yaml."""
    for name in list(os.environ):
        if name.startswith("ORYA_") or name in _MANAGED_ENV_VARS:
            monkeypatch.delenv(name, raising=False)
    monkeypatch.chdir(tmp_path)  # ignore any project-root .env
    monkeypatch.setenv("ORYA_CONFIG_PATH", str(tmp_path / "config.yaml"))
    clear_settings_cache()
    yield
    clear_settings_cache()


def _write_yaml(data: dict, tmp_path: Path) -> None:
    (tmp_path / "config.yaml").write_text(
        yaml.safe_dump(data, sort_keys=False), encoding="utf-8"
    )


# --- config show -----------------------------------------------------------


def test_show_redacts_secrets_and_reports_env_source(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("ORYA_LLM_API_KEY", "sk-super-secret-42")
    clear_settings_cache()
    text = "\n".join(config_show_lines())
    assert "sk-super-secret-42" not in text
    assert "llm_api_key = *** [env]" in text


def test_show_reports_default_source():
    assert "llm_provider = anthropic [default]" in config_show_lines()


def test_show_reports_dotenv_source(tmp_path: Path):
    (tmp_path / ".env").write_text("ORYA_LLM_PROVIDER=qwen\n", encoding="utf-8")
    clear_settings_cache()
    assert "llm_provider = qwen [.env]" in config_show_lines()


def test_show_reports_config_yaml_source(tmp_path: Path):
    _write_yaml({"llm": {"default_provider": "glm"}}, tmp_path)
    clear_settings_cache()
    assert "llm_provider = glm [config.yaml]" in config_show_lines()


def test_run_config_show_smoke(capsys: pytest.CaptureFixture[str]):
    assert run_config_show() == 0
    out = capsys.readouterr().out
    assert "app_env" in out
    assert "database_url" in out


# --- config check ----------------------------------------------------------


def test_check_dev_prints_guardrails_off(capsys: pytest.CaptureFixture[str]):
    assert run_config_check() == 0
    out = capsys.readouterr().out
    assert "app_env=dev" in out
    assert "ORYA_ENV=prod" in out


def test_check_prod_ok_with_warnings(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv("ORYA_ENV", "prod")
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setenv("AUTH_SECRET_KEY", "s" * 32)
    monkeypatch.setenv("ORYA_RATE_LIMIT_ENABLED", "true")
    monkeypatch.setenv("CORS_ORIGINS", "http://localhost:8001")
    clear_settings_cache()
    assert run_config_check() == 0
    out = capsys.readouterr().out
    assert "guardrails OK" in out
    assert "warning:" in out


def test_check_prod_violation_exits_1(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv("ORYA_ENV", "prod")
    clear_settings_cache()
    assert run_config_check() == 1
    out = capsys.readouterr().out
    assert "FAIL" in out
    assert "AUTH_ENABLED=true" in out
