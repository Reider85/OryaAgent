"""Application settings (M-02) — the single source of typed configuration.

All runtime parameters live here: LLM seam, database, Redis, L0 memory,
permission policy, logging, plus placeholders for future phases (ALPHA:
auth/observability; BETA: UI ports; PROD: OriaHS).

Config sources by priority (highest first):
1. Environment variables (and ``.env`` in the working directory).
2. ``~/.orya/config.yaml`` — multi-provider config with ``${ENV_VAR}``
   substitution (API keys are never stored as plaintext).
3. Field defaults in :class:`Settings`.

The ``~/.orya/config.yaml`` fallback is only applied to fields that were
*not* set explicitly via env vars or ``.env`` — this keeps the M-01 LLM
seam resolution chain (arg -> env -> user config -> registry default)
intact while exposing a single ``get_settings()`` entry point.

Usage::

    from app.core.config import get_settings
    settings = get_settings()
    settings.llm_provider  # "anthropic" (or env/config override)
"""

from __future__ import annotations

import os
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import AliasChoices, Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ENV_VAR_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")

_DEFAULT_DATABASE_URL = "postgresql://orya:orya_password@localhost:5432/orya_sessions"
_DEFAULT_REDIS_URL = "redis://localhost:6379"

# field -> ((accepted env names), (yaml path inside ~/.orya/config.yaml))
# A yaml fallback is applied only when none of the env names are set AND the
# value did not come from a .env file.
_YAML_FALLBACKS: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "llm_provider": (("ORYA_LLM_PROVIDER",), ("llm", "default_provider")),
    "llm_model": (("ORYA_LLM_MODEL",), ("llm", "default_model")),
    "database_url": (
        ("DATABASE_URL", "ORYA_DATABASE_URL"),
        ("database_url",),
    ),
    "redis_url": (("REDIS_URL", "ORYA_REDIS_URL"), ("redis_url",)),
    "memory_dir": (("ORYA_MEMORY_DIR",), ("memory_dir",)),
    "memory_compact_interval_s": (
        ("ORYA_MEMORY_COMPACT_INTERVAL_SECONDS",),
        ("memory_compact_interval_s",),
    ),
    "sessions_dir": (("ORYA_SESSIONS_DIR",), ("sessions_dir",)),
    "permission_policy": (
        ("ORYA_PERMISSION_POLICY", "PERMISSION_POLICY"),
        ("permission_policy",),
    ),
    "permissions_path": (
        ("ORYA_PERMISSIONS_PATH", "PERMISSIONS_PATH"),
        ("permissions_path",),
    ),
    "recursion_limit": (
        ("ORYA_RECURSION_LIMIT", "RECURSION_LIMIT"),
        ("recursion_limit",),
    ),
    "context_max_tokens": (
        ("ORYA_CONTEXT_MAX_TOKENS", "CONTEXT_MAX_TOKENS"),
        ("context_max_tokens",),
    ),
    "log_level": (("LOG_LEVEL", "ORYA_LOG_LEVEL"), ("log_level",)),
}


class Settings(BaseSettings):
    """Typed application settings (pydantic-settings v2)."""

    # --- LLM seam (M-01/M-02) -------------------------------------------
    llm_provider: str = Field(
        default="anthropic",
        validation_alias=AliasChoices("ORYA_LLM_PROVIDER"),
        description="Default LLM provider key from providers.yaml",
    )
    llm_model: str = Field(
        default="claude-sonnet-3.5",
        validation_alias=AliasChoices("ORYA_LLM_MODEL"),
        description="Default model alias (models.yaml) or raw model_id",
    )
    llm_api_key: SecretStr | None = Field(
        default=None,
        validation_alias=AliasChoices("ORYA_LLM_API_KEY"),
        description="Override API key; usually provider-specific env vars win",
    )
    llm_base_url: str | None = Field(
        default=None,
        validation_alias=AliasChoices("ORYA_LLM_BASE_URL"),
        description="Endpoint override for OpenAI-compatible providers",
    )
    llm_temperature: float = Field(
        default=0.0,
        validation_alias=AliasChoices("ORYA_LLM_TEMPERATURE"),
    )
    llm_max_tokens: int = Field(
        default=8192,
        validation_alias=AliasChoices("ORYA_LLM_MAX_TOKENS"),
    )
    llm_timeout_s: float = Field(
        default=120.0,
        validation_alias=AliasChoices("ORYA_LLM_TIMEOUT_S"),
    )

    # --- Database (M-03) -------------------------------------------------
    database_url: str = Field(
        default=_DEFAULT_DATABASE_URL,
        validation_alias=AliasChoices("DATABASE_URL", "ORYA_DATABASE_URL"),
    )
    database_pool_size: int = Field(
        default=5,
        validation_alias=AliasChoices("DATABASE_POOL_SIZE", "ORYA_DATABASE_POOL_SIZE"),
    )
    database_max_overflow: int = Field(
        default=10,
        validation_alias=AliasChoices(
            "DATABASE_MAX_OVERFLOW", "ORYA_DATABASE_MAX_OVERFLOW"
        ),
    )

    # --- Redis (M-21) ----------------------------------------------------
    redis_url: str = Field(
        default=_DEFAULT_REDIS_URL,
        validation_alias=AliasChoices("REDIS_URL", "ORYA_REDIS_URL"),
    )
    cache_ttl_seconds: float = Field(
        default=300.0,
        validation_alias=AliasChoices("ORYA_CACHE_TTL_SECONDS", "CACHE_TTL_SECONDS"),
        description="Tool-result cache TTL (BACKLOG5 M-21: 5 minutes)",
    )
    cache_backend: Literal["auto", "memory", "redis"] = Field(
        default="auto",
        validation_alias=AliasChoices("ORYA_CACHE_BACKEND", "CACHE_BACKEND"),
        description=(
            "auto: probe Redis and fall back to memory; "
            "redis: require Redis at startup; memory: never use Redis"
        ),
    )

    # --- L0 memory (M-25, M-27) -------------------------------------------
    memory_dir: Path = Field(
        default=Path.home() / ".orya" / "memory",
        validation_alias=AliasChoices("ORYA_MEMORY_DIR"),
    )
    memory_compact_interval_s: int = Field(
        default=86400,
        validation_alias=AliasChoices("ORYA_MEMORY_COMPACT_INTERVAL_SECONDS"),
        description="L0 compaction period in seconds (M-27); 0 disables the worker",
    )

    # --- Session log (M-14) ----------------------------------------------
    sessions_dir: Path = Field(
        default=Path.home() / ".orya" / "sessions",
        validation_alias=AliasChoices("ORYA_SESSIONS_DIR"),
        description="JSONL projection directory ({session_id}.jsonl + .meta.json)",
    )

    # --- UI (M-15/M-17, M-24) ---------------------------------------------
    api_url: str = Field(
        default="http://127.0.0.1:8000",
        validation_alias=AliasChoices("ORYA_API_URL"),
        description="FastAPI base URL the Chainlit UI calls over HTTP/SSE (M-24)",
    )
    ui_settings_path: Path = Field(
        default=Path.home() / ".orya" / "settings.json",
        validation_alias=AliasChoices("ORYA_UI_SETTINGS_PATH"),
        description="Settings-panel state: model, permission mode, allow-list (M-17)",
    )

    # --- Security (M-13) -------------------------------------------------
    permission_policy: Literal["strict", "permissive"] = Field(
        default="strict",
        validation_alias=AliasChoices("ORYA_PERMISSION_POLICY", "PERMISSION_POLICY"),
    )
    permissions_path: Path = Field(
        default=Path.home() / ".orya" / "permissions.yml",
        validation_alias=AliasChoices("ORYA_PERMISSIONS_PATH", "PERMISSIONS_PATH"),
        description="User allow/deny rule overrides (ADR-004); absent -> defaults",
    )

    # --- Agent loop (M-04) ------------------------------------------------
    recursion_limit: int = Field(
        default=25,
        validation_alias=AliasChoices("ORYA_RECURSION_LIMIT", "RECURSION_LIMIT"),
        description="Max agent-loop iterations (LangGraph recursion_limit)",
    )

    # --- Failure recovery (M-28) ------------------------------------------
    recovery_max_rounds: int = Field(
        default=3,
        validation_alias=AliasChoices(
            "ORYA_RECOVERY_MAX_ROUNDS", "RECOVERY_MAX_ROUNDS"
        ),
        description="How many times a failed tool batch may trigger the "
        "recover node (alternatives requested from the LLM)",
    )
    recovery_variants: int = Field(
        default=5,
        validation_alias=AliasChoices("ORYA_RECOVERY_VARIANTS", "RECOVERY_VARIANTS"),
        description="How many alternative approaches the recover nudge asks "
        "the model to enumerate (one is attempted per round)",
    )
    llm_retry_attempts: int = Field(
        default=3,
        validation_alias=AliasChoices("ORYA_LLM_RETRY_ATTEMPTS", "LLM_RETRY_ATTEMPTS"),
        description="Total attempts of one LLM provider call incl. the "
        "first one (1 = no retry)",
    )
    llm_retry_backoff_seconds: float = Field(
        default=1.0,
        validation_alias=AliasChoices(
            "ORYA_LLM_RETRY_BACKOFF_SECONDS", "LLM_RETRY_BACKOFF_SECONDS"
        ),
        description="Base delay for the exponential LLM retry backoff "
        "(1s, 2s, 4s, ... capped at 30s)",
    )

    # --- Context manager (M-06) -------------------------------------------
    context_max_tokens: int = Field(
        default=120_000,
        validation_alias=AliasChoices("ORYA_CONTEXT_MAX_TOKENS", "CONTEXT_MAX_TOKENS"),
        description="Context-window budget; conversation history is trimmed to fit",
    )

    # --- Logging ---------------------------------------------------------
    log_level: str = Field(
        default="INFO",
        validation_alias=AliasChoices("LOG_LEVEL", "ORYA_LOG_LEVEL"),
    )

    # --- Future phases (placeholders, unused in MVP) ---------------------
    # ALPHA: auth
    auth_secret_key: SecretStr | None = Field(
        default=None,
        validation_alias=AliasChoices("AUTH_SECRET_KEY", "ORYA_AUTH_SECRET_KEY"),
    )
    auth_algorithm: str = Field(
        default="HS256",
        validation_alias=AliasChoices("AUTH_ALGORITHM", "ORYA_AUTH_ALGORITHM"),
    )
    # ALPHA: observability
    langsmith_api_key: SecretStr | None = Field(
        default=None,
        validation_alias=AliasChoices("LANGSMITH_API_KEY", "ORYA_LANGSMITH_API_KEY"),
    )
    otel_exporter_otlp_endpoint: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "OTEL_EXPORTER_OTLP_ENDPOINT",
            "ORYA_OTEL_EXPORTER_OTLP_ENDPOINT",
        ),
    )
    # PROD: OriaHS
    oriahs_url: str | None = Field(
        default=None,
        validation_alias=AliasChoices("ORIAHS_URL", "ORYA_ORIAHS_URL"),
    )
    oriahs_timeout_s: float = Field(
        default=30.0,
        validation_alias=AliasChoices("ORIAHS_TIMEOUT_S", "ORYA_ORIAHS_TIMEOUT_S"),
    )
    # BETA: UI ports (M-15: chainlit on 8001 — 8000 is the API server)
    chainlit_port: int = Field(
        default=8001,
        validation_alias=AliasChoices("CHAINLIT_PORT", "ORYA_CHAINLIT_PORT"),
    )
    nextjs_port: int = Field(
        default=3000,
        validation_alias=AliasChoices("NEXTJS_PORT", "ORYA_NEXTJS_PORT"),
    )

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        populate_by_name=True,
        extra="ignore",
    )

    @field_validator(
        "memory_dir",
        "permissions_path",
        "sessions_dir",
        "ui_settings_path",
        mode="before",
    )
    @classmethod
    def _expand_paths(cls, value: Any) -> Any:
        """Expand ``~`` in path fields (env values arrive as plain strings)."""
        if isinstance(value, str):
            return Path(value).expanduser()
        return value


def user_config_path() -> Path:
    """Path of the per-user config file (``ORYA_CONFIG_PATH`` override)."""
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
    """Load ``~/.orya/config.yaml`` (raw, without env expansion). Missing -> {}."""
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


def _dig(data: dict, path: tuple[str, ...]) -> Any:
    """Nested dict lookup; None when any level is missing."""
    current: Any = data
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _dotenv_only_differs(field: str) -> bool:
    """True when the field's value differs between env-only and env+.env."""
    env_only = Settings(_env_file=None)
    with_dotenv = Settings()
    return getattr(with_dotenv, field) != getattr(env_only, field)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the application settings singleton.

    Env vars / ``.env`` win; ``~/.orya/config.yaml`` fills fields that were
    not explicitly configured through the environment.
    """
    base = Settings()
    yaml_cfg = load_expanded_user_config()

    overrides: dict[str, Any] = {}
    for field, (env_names, yaml_path) in _YAML_FALLBACKS.items():
        if any(name in os.environ for name in env_names):
            continue
        if _dotenv_only_differs(field):
            continue
        yaml_value = _dig(yaml_cfg, yaml_path)
        if yaml_value is not None and yaml_value != "":
            overrides[field] = yaml_value

    if not overrides:
        return base
    return Settings(**overrides)


def clear_settings_cache() -> None:
    """Drop the settings singleton (used by tests that mutate the env)."""
    get_settings.cache_clear()


def __getattr__(name: str) -> Any:
    """Lazy module-level ``settings`` attribute (PEP 562).

    Enables ``from app.core.config import settings`` without binding a stale
    instance at import time.
    """
    if name == "settings":
        return get_settings()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
