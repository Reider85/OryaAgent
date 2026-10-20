"""Minimal LLM configuration slice (M-02 will absorb this into full Settings).

Config sources for the LLM seam, by priority:
1. Environment variables ``ORYA_LLM_PROVIDER``, ``ORYA_LLM_MODEL``,
   ``ORYA_LLM_API_KEY``, ``ORYA_LLM_BASE_URL`` (optionally from a ``.env`` file).
2. ``~/.orya/config.yaml`` — the ``llm:`` block (multi-provider config with
   ``${ENV_VAR}`` substitution; API keys are never stored as plaintext).
3. Declarative defaults from ``providers.yaml`` / ``models.yaml``.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import yaml
from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

ENV_VAR_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


class LLMSettings(BaseSettings):
    """LLM-related settings from env / .env."""

    llm_provider: str | None = None
    llm_model: str | None = None
    llm_api_key: SecretStr | None = None
    llm_base_url: str | None = None

    model_config = SettingsConfigDict(
        env_prefix="ORYA_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


def get_settings() -> LLMSettings:
    """Return LLM settings (reads env + optional .env each call — cheap)."""
    return LLMSettings()


def user_config_path() -> Path:
    """Path of the per-user config file."""
    override = os.environ.get("ORYA_CONFIG_PATH")
    if override:
        return Path(override).expanduser()
    return Path.home() / ".orya" / "config.yaml"


def _expand_env_vars(value: Any) -> Any:
    """Recursively expand ``${ENV_VAR}`` references in strings."""

    if isinstance(value, str):

        def repl(match: re.Match[str]) -> str:
            return os.environ.get(match.group(1), match.group(0))

        return ENV_VAR_PATTERN.sub(repl, value)
    if isinstance(value, dict):
        return {k: _expand_env_vars(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_expand_env_vars(v) for v in value]
    return value


def load_user_config() -> dict:
    """Load ``~/.orya/config.yaml`` (raw, without env expansion). Missing file -> {}."""
    path = user_config_path()
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Config file {path} must contain a YAML mapping")
    return data


def load_expanded_user_config() -> dict:
    """Load user config with ``${ENV_VAR}`` placeholders substituted."""
    return _expand_env_vars(load_user_config())


def llm_block(config: dict | None = None) -> dict:
    """Return the ``llm:`` section of the user config (expanded)."""
    if config is None:
        config = load_expanded_user_config()
    block = config.get("llm")
    return block if isinstance(block, dict) else {}


def provider_block(provider: str, config: dict | None = None) -> dict:
    """Return ``llm.providers.{provider}:`` from the user config (expanded)."""
    block = llm_block(config)
    providers = block.get("providers")
    if not isinstance(providers, dict):
        return {}
    entry = providers.get(provider)
    return entry if isinstance(entry, dict) else {}


def is_unresolved(value: str | None) -> bool:
    """True if value is missing or still contains an unresolved ``${VAR}``."""
    if not value:
        return True
    return bool(ENV_VAR_PATTERN.search(value))
