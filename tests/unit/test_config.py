"""Unit tests for M-02 — app.core.config Settings + yaml fallback merge."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
import yaml
from pydantic import SecretStr, ValidationError

from app.core.config import (
    Settings,
    clear_settings_cache,
    get_settings,
    is_unresolved,
    llm_block,
    load_expanded_user_config,
    provider_block,
    user_config_path,
)

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


def _write_config(data: dict, tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


# --- defaults ------------------------------------------------------------


def test_defaults():
    s = get_settings()
    assert s.llm_provider == "anthropic"
    assert s.llm_model == "claude-sonnet-3.5"
    assert s.llm_api_key is None
    assert s.llm_base_url is None
    assert s.llm_temperature == 0.0
    assert s.llm_max_tokens == 8192
    assert s.llm_timeout_s == 120.0
    assert s.database_url == (
        "postgresql://orya:orya_password@localhost:5432/orya_sessions"
    )
    assert s.database_pool_size == 5
    assert s.database_max_overflow == 10
    assert s.redis_url == "redis://localhost:6379"
    assert s.permission_policy == "strict"
    assert s.recursion_limit == 25
    assert s.log_level == "INFO"
    assert s.memory_dir == Path.home() / ".orya" / "memory"
    # Future-phase placeholders
    assert s.auth_algorithm == "HS256"
    assert s.oriahs_timeout_s == 30.0
    assert s.chainlit_port == 8000
    assert s.nextjs_port == 3000


def test_get_settings_is_singleton():
    assert get_settings() is get_settings()


def test_module_level_settings_attribute():
    from app.core.config import settings  # noqa: PLC0415

    assert isinstance(settings, Settings)
    assert settings.llm_provider == "anthropic"


# --- env overrides -------------------------------------------------------


def test_env_overrides(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("ORYA_LLM_PROVIDER", "deepseek")
    monkeypatch.setenv("ORYA_LLM_MODEL", "deepseek-chat")
    monkeypatch.setenv("DATABASE_URL", "postgresql://db:5432/x")
    monkeypatch.setenv("ORYA_PERMISSION_POLICY", "permissive")
    monkeypatch.setenv("ORYA_RECURSION_LIMIT", "50")
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
    clear_settings_cache()
    s = get_settings()
    assert s.llm_provider == "deepseek"
    assert s.llm_model == "deepseek-chat"
    assert s.database_url == "postgresql://db:5432/x"
    assert s.permission_policy == "permissive"
    assert s.recursion_limit == 50
    assert s.log_level == "DEBUG"


def test_dotenv_is_read(tmp_path: Path):
    (tmp_path / ".env").write_text(
        "ORYA_LLM_PROVIDER=qwen\nDATABASE_URL=postgresql://from-dotenv:5432/y\n",
        encoding="utf-8",
    )
    clear_settings_cache()
    s = get_settings()
    assert s.llm_provider == "qwen"
    assert s.database_url == "postgresql://from-dotenv:5432/y"


# --- ~/.orya/config.yaml fallback -----------------------------------------


def test_yaml_fallback_default_provider_and_model(tmp_path: Path):
    _write_config(
        {
            "llm": {
                "default_provider": "glm",
                "default_model": "glm-4.5",
            }
        },
        tmp_path,
    )
    clear_settings_cache()
    s = get_settings()
    assert s.llm_provider == "glm"
    assert s.llm_model == "glm-4.5"


def test_env_wins_over_yaml(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    _write_config({"llm": {"default_provider": "glm"}}, tmp_path)
    monkeypatch.setenv("ORYA_LLM_PROVIDER", "deepseek")
    clear_settings_cache()
    assert get_settings().llm_provider == "deepseek"


def test_yaml_top_level_fallbacks(tmp_path: Path):
    _write_config(
        {
            "permission_policy": "permissive",
            "log_level": "WARNING",
            "redis_url": "redis://yaml-host:6379/1",
            "recursion_limit": 40,
            "memory_dir": str(Path("~/.orya/custom-memory").expanduser()),
        },
        tmp_path,
    )
    clear_settings_cache()
    s = get_settings()
    assert s.permission_policy == "permissive"
    assert s.log_level == "WARNING"
    assert s.redis_url == "redis://yaml-host:6379/1"
    assert s.recursion_limit == 40
    assert s.memory_dir == Path.home() / ".orya" / "custom-memory"


def test_yaml_fallback_applies_when_no_yaml(tmp_path: Path):
    # No config.yaml at all -> defaults still work
    clear_settings_cache()
    assert get_settings().llm_provider == "anthropic"
    assert not (tmp_path / "config.yaml").exists()


# --- ${ENV_VAR} expansion -------------------------------------------------


def test_env_var_expansion(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("TEST_API_KEY_XYZ", "sk-expanded")
    cfg = load_expanded_user_config()
    assert cfg == {}  # no config file -> {}
    _write_config(
        {"llm": {"providers": {"deepseek": {"api_key": "${TEST_API_KEY_XYZ}"}}}},
        Path(os.environ["ORYA_CONFIG_PATH"]).parent,
    )
    block = provider_block("deepseek")
    assert block["api_key"] == "sk-expanded"
    assert not is_unresolved(block["api_key"])


def test_unresolved_placeholder_detected(monkeypatch: pytest.MonkeyPatch):
    _write_config(
        {"llm": {"providers": {"deepseek": {"api_key": "${MISSING_VAR_123}"}}}},
        Path(os.environ["ORYA_CONFIG_PATH"]).parent,
    )
    block = provider_block("deepseek")
    assert block["api_key"] == "${MISSING_VAR_123}"
    assert is_unresolved(block["api_key"])
    assert is_unresolved(None)
    assert is_unresolved("")


# --- validation ----------------------------------------------------------


def test_permission_policy_literal_validation():
    with pytest.raises(ValidationError):
        Settings(permission_policy="banana")


def test_secretstr_never_leaked(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("ORYA_LLM_API_KEY", "sk-super-secret-42")
    clear_settings_cache()
    s = get_settings()
    assert isinstance(s.llm_api_key, SecretStr)
    assert "sk-super-secret-42" not in repr(s)
    assert "sk-super-secret-42" not in str(s)
    assert s.llm_api_key.get_secret_value() == "sk-super-secret-42"


def test_memory_dir_tilde_expansion(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("ORYA_MEMORY_DIR", "~/memory-override")
    clear_settings_cache()
    assert get_settings().memory_dir == Path.home() / "memory-override"


# --- helpers / shim -------------------------------------------------------


def test_user_config_path_override(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("ORYA_CONFIG_PATH", "/tmp/custom/orya.yaml")
    assert user_config_path() == Path("/tmp/custom/orya.yaml")
    monkeypatch.delenv("ORYA_CONFIG_PATH")
    assert user_config_path() == Path.home() / ".orya" / "config.yaml"


def test_llm_block_and_provider_block_helpers(tmp_path: Path):
    _write_config({"llm": {"default_provider": "ollama", "providers": {}}}, tmp_path)
    block = llm_block()
    assert block["default_provider"] == "ollama"
    assert provider_block("nope") == {}
    assert llm_block({"llm": "not-a-dict"}) == {}


def test_settings_shim_reexports():
    from app.core.llm import settings as shim

    assert shim.get_settings is get_settings
    assert shim.user_config_path is user_config_path
    assert shim.is_unresolved is is_unresolved
    assert shim.llm_block is llm_block
    assert shim.provider_block is provider_block


def test_clear_settings_cache_resets(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("ORYA_LLM_PROVIDER", "groq")
    clear_settings_cache()
    assert get_settings().llm_provider == "groq"
    monkeypatch.delenv("ORYA_LLM_PROVIDER")
    assert get_settings().llm_provider == "groq"  # still cached
    clear_settings_cache()
    assert get_settings().llm_provider == "anthropic"


def test_factory_seam_still_works_with_merged_settings(tmp_path: Path):
    """M-01 factory must honour config.yaml defaults merged by get_settings()."""
    from app.core.llm import get_llm

    _write_config(
        {"llm": {"default_provider": "ollama", "default_model": "qwen2.5-coder:14b"}},
        tmp_path,
    )
    clear_settings_cache()
    llm = get_llm()
    assert llm.openai_api_base == "http://localhost:11434/v1"
    assert llm.model == "qwen2.5-coder:14b"
