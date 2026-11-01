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

import json
import os
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlsplit

import yaml
from pydantic import AliasChoices, Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ENV_VAR_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")

_DEFAULT_DATABASE_URL = "postgresql://orya:orya_password@localhost:5432/orya_sessions"
_DEFAULT_REDIS_URL = "redis://localhost:6379"

_ALLOWED_LOG_LEVELS = frozenset({"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"})
_LOCALHOSTS = frozenset({"localhost", "127.0.0.1", "::1"})

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
    llm_trace_enabled: bool = Field(
        default=True,
        validation_alias=AliasChoices("ORYA_LLM_TRACE_ENABLED"),
        description=(
            "A-02: wrap get_llm() models in TracedChatModel so every seam "
            "invocation records an llm.call span; false returns the raw adapter"
        ),
    )
    llm_trace_exporter: Literal["off", "stdout"] = Field(
        default="off",
        validation_alias=AliasChoices("ORYA_LLM_TRACE_EXPORTER"),
        description=(
            "A-02: span transport — off keeps records in the in-process "
            "buffer only; stdout logs them as debug JSON"
        ),
    )
    permission_audit_enabled: bool = Field(
        default=True,
        validation_alias=AliasChoices("ORYA_PERMISSION_AUDIT_ENABLED"),
        description=(
            "A-03: emit agent.permission spans on permission decisions; "
            "false disables span construction (buffer still empty, no overhead)"
        ),
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
    cache_max_entries: int = Field(
        default=1024,
        ge=0,
        validation_alias=AliasChoices("ORYA_CACHE_MAX_ENTRIES", "CACHE_MAX_ENTRIES"),
        description="MemoryCache LRU capacity; 0 = unlimited (default: 1024)",
    )
    redis_pool_max_connections: int = Field(
        default=10,
        ge=1,
        validation_alias=AliasChoices(
            "ORYA_REDIS_POOL_MAX_CONNECTIONS", "REDIS_POOL_MAX_CONNECTIONS"
        ),
        description="Redis client pool max connections",
    )
    redis_socket_timeout_seconds: float = Field(
        default=5.0,
        ge=0.1,
        validation_alias=AliasChoices(
            "ORYA_REDIS_SOCKET_TIMEOUT_SECONDS", "REDIS_SOCKET_TIMEOUT_SECONDS"
        ),
        description="Redis client socket timeout in seconds",
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

    # --- Deployment profile (A-12) ----------------------------------------
    app_env: Literal["dev", "prod"] = Field(
        default="dev",
        validation_alias=AliasChoices("ORYA_ENV"),
        description=(
            "Deployment profile: dev keeps the MVP kill-switch defaults; "
            "prod refuses to boot unless auth, rate-limit and CORS are "
            "production-safe (A-12 fail-fast guard)"
        ),
    )

    # --- Logging ---------------------------------------------------------
    log_level: str = Field(
        default="INFO",
        validation_alias=AliasChoices("LOG_LEVEL", "ORYA_LOG_LEVEL"),
    )

    # --- Future phases (placeholders, unused in MVP) ---------------------
    # ALPHA: auth (A-00)
    auth_secret_key: SecretStr | None = Field(
        default=None,
        validation_alias=AliasChoices("AUTH_SECRET_KEY", "ORYA_AUTH_SECRET_KEY"),
    )
    auth_algorithm: str = Field(
        default="HS256",
        validation_alias=AliasChoices("AUTH_ALGORITHM", "ORYA_AUTH_ALGORITHM"),
    )
    auth_enabled: bool = Field(
        default=False,
        validation_alias=AliasChoices("AUTH_ENABLED", "ORYA_AUTH_ENABLED"),
        description="Kill-switch: Bearer-JWT enforcement on all non-public "
        "endpoints (A-00); off by default so dev/tests keep working",
    )
    auth_token_ttl_s: int = Field(
        default=86_400,
        validation_alias=AliasChoices("AUTH_TOKEN_TTL_S", "ORYA_AUTH_TOKEN_TTL_S"),
        description="Lifetime of tokens minted by create_token()/`orya auth token`",
    )
    auth_public_paths: str = Field(
        default="/health,/docs,/redoc,/openapi.json,/metrics",
        validation_alias=AliasChoices("AUTH_PUBLIC_PATHS", "ORYA_AUTH_PUBLIC_PATHS"),
        description="CSV (or JSON array) of path prefixes exempt from JWT "
        "enforcement when auth is on",
    )
    # ALPHA: CORS (A-00)
    cors_origins: str = Field(
        default="*",
        validation_alias=AliasChoices("CORS_ORIGINS", "ORYA_CORS_ORIGINS"),
        description='Comma-separated allowed origins, or "*" for any',
    )
    # ALPHA: rate-limit (A-01)
    rate_limit_enabled: bool = Field(
        default=False,
        validation_alias=AliasChoices("RATE_LIMIT_ENABLED", "ORYA_RATE_LIMIT_ENABLED"),
        description=(
            "Kill-switch: per-user (60 rpm) + per-endpoint (/learn 10 rpm) "
            "enforcement (A-01); off by default so dev/tests/UI keep working"
        ),
    )
    rate_limit_rpm: int = Field(
        default=60,
        validation_alias=AliasChoices("RATE_LIMIT_RPM", "ORYA_RATE_LIMIT_RPM"),
        description="Per-user requests-per-minute budget on every endpoint",
    )
    rate_limit_learn_rpm: int = Field(
        default=10,
        validation_alias=AliasChoices(
            "RATE_LIMIT_LEARN_RPM", "ORYA_RATE_LIMIT_LEARN_RPM"
        ),
        description="Tighter per-user RPM for the /learn endpoints (anti-abuse)",
    )
    rate_limit_backend: Literal["auto", "memory", "redis"] = Field(
        default="auto",
        validation_alias=AliasChoices("RATE_LIMIT_BACKEND", "ORYA_RATE_LIMIT_BACKEND"),
        description=(
            "auto: probe Redis and fall back to in-memory counters; "
            "redis: require Redis at startup; memory: never use Redis"
        ),
    )
    rate_limit_trusted_clients: str = Field(
        default="",
        validation_alias=AliasChoices(
            "RATE_LIMIT_TRUSTED_CLIENTS", "ORYA_TRUSTED_CLIENTS"
        ),
        description=(
            "CSV/JSON list of user ids or client IPs exempt from "
            "rate limiting (PROMPT_ALPHA §11 whitelist)"
        ),
    )
    # ALPHA: cost-aware model router (A-13)
    cost_router_enabled: bool = Field(
        default=False,
        validation_alias=AliasChoices(
            "COST_ROUTER_ENABLED", "ORYA_COST_ROUTER_ENABLED"
        ),
        description=(
            "Kill-switch: budget-based model degrade (A-13) — at >=70% of the "
            "daily budget the turn runs on the fallback model, at >=100% the "
            "request is refused with 429; off by default so dev/tests/UI keep "
            "working"
        ),
    )
    cost_router_fallback_model: str = Field(
        default="claude-haiku-3.5",
        validation_alias=AliasChoices(
            "COST_ROUTER_FALLBACK_MODEL", "ORYA_COST_ROUTER_FALLBACK_MODEL"
        ),
        description="models.yaml alias used when the budget degrade kicks in",
    )
    cost_budget_default_usd: float = Field(
        default=50.0,
        validation_alias=AliasChoices(
            "COST_BUDGET_DEFAULT_USD", "ORYA_COST_BUDGET_DEFAULT_USD"
        ),
        description=(
            "Daily per-identity budget in USD applied when no admin-set "
            "limit exists (Redis key orya:limit:{identity})"
        ),
    )
    cost_backend: Literal["auto", "memory", "redis"] = Field(
        default="auto",
        validation_alias=AliasChoices("COST_BACKEND", "ORYA_COST_BACKEND"),
        description=(
            "auto: probe Redis and fall back to in-memory spend counters; "
            "redis: require Redis at startup; memory: never use Redis"
        ),
    )
    # ALPHA: session-log encryption at rest (A-05)
    session_log_encryption_enabled: bool = Field(
        default=False,
        validation_alias=AliasChoices(
            "SESSION_LOG_ENCRYPTION_ENABLED",
            "ORYA_SESSION_LOG_ENCRYPTION_ENABLED",
        ),
        description=(
            "Kill-switch: encrypt session-log payload columns "
            "(messages.content, messages.tool_calls) with pgcrypto "
            "pgp_sym_encrypt (A-05); off by default so dev/tests keep working"
        ),
    )
    session_log_encryption_key: SecretStr | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "SESSION_LOG_ENCRYPTION_KEY",
            "ORYA_SESSION_LOG_ENCRYPTION_KEY",
        ),
        description="Symmetric passphrase for pgp_sym_encrypt (>= 16 chars)",
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
    sampler_proxy_url: str = Field(
        default="http://sampler-proxy:4321",
        validation_alias=AliasChoices("ORYA_SAMPLER_PROXY_URL"),
        description="URL of the sampler-proxy service (e.g., http://sampler-proxy:4321)",
    )
    # Langfuse OTLP export (A-15)
    langfuse_host: str | None = Field(
        default=None,
        validation_alias=AliasChoices("LANGFUSE_HOST", "ORYA_LANGFUSE_HOST"),
        description=(
            "A-15: OTLP ingest base — direct Langfuse (http://host:3000) or the "
            "sampler-proxy; spans POST to {host}/api/public/otel/v1/traces "
            "(the A-10 sampler-proxy accepts any path)"
        ),
    )
    langfuse_public_key: SecretStr | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "LANGFUSE_PUBLIC_KEY", "ORYA_LANGFUSE_PUBLIC_KEY"
        ),
        description="A-15: Langfuse public key (Basic auth username)",
    )
    langfuse_secret_key: SecretStr | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "LANGFUSE_SECRET_KEY", "ORYA_LANGFUSE_SECRET_KEY"
        ),
        description="A-15: Langfuse secret key (Basic auth password)",
    )
    langfuse_direct_url: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "LANGFUSE_DIRECT_URL", "ORYA_LANGFUSE_DIRECT_URL"
        ),
        description=(
            "A-15 fail-open fallback: retried once per batch when the primary "
            "export endpoint stays unreachable"
        ),
    )
    langfuse_export_enabled: bool = Field(
        default=True,
        validation_alias=AliasChoices(
            "ORYA_LANGFUSE_EXPORT_ENABLED", "LANGFUSE_EXPORT_ENABLED"
        ),
        description=(
            "A-15 kill-switch: export is effective only when this is true AND "
            "langfuse_host + both keys are set (auto-on when configured)"
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

    @field_validator("log_level", mode="before")
    @classmethod
    def _normalize_log_level(cls, value: Any) -> Any:
        """Uppercase and allow-list LOG_LEVEL (A-12: typo'd levels fail fast)."""
        if isinstance(value, str):
            text = value.strip().upper()
            if text and text not in _ALLOWED_LOG_LEVELS:
                raise ValueError(
                    f"LOG_LEVEL must be one of {sorted(_ALLOWED_LOG_LEVELS)}"
                )
            return text
        return value

    @field_validator("auth_secret_key")
    @classmethod
    def _validate_auth_secret(cls, value: SecretStr | None) -> SecretStr | None:
        """Reject weak JWT secrets (A-00: HS256 secret >= 32 chars, never plain)."""
        if value is not None:
            raw = value.get_secret_value()
            if raw and len(raw) < 32:
                raise ValueError("AUTH_SECRET_KEY must be at least 32 characters")
        return value

    @field_validator("session_log_encryption_key")
    @classmethod
    def _validate_session_log_encryption_key(
        cls, value: SecretStr | None
    ) -> SecretStr | None:
        """Reject weak session-log encryption keys (A-05: >= 16 chars)."""
        if value is not None:
            raw = value.get_secret_value()
            if raw and len(raw) < 16:
                raise ValueError(
                    "SESSION_LOG_ENCRYPTION_KEY must be at least 16 characters"
                )
        return value

    @model_validator(mode="after")
    def _require_secret_when_auth_enabled(self) -> Settings:
        """Fail fast: enforcing JWT without a signing secret is a misconfiguration."""
        if self.auth_enabled and self.auth_secret_key is None:
            raise ValueError("AUTH_ENABLED=true requires AUTH_SECRET_KEY")
        return self

    @model_validator(mode="after")
    def _require_key_when_session_log_encryption_enabled(self) -> Settings:
        """Fail fast: encrypting the session log without a key is a misconfiguration."""
        if (
            self.session_log_encryption_enabled
            and self.session_log_encryption_key is None
        ):
            raise ValueError(
                "SESSION_LOG_ENCRYPTION_ENABLED=true requires SESSION_LOG_ENCRYPTION_KEY"
            )
        return self

    @model_validator(mode="after")
    def _require_prod_safe_settings(self) -> Settings:
        """A-12 fail-fast: ``ORYA_ENV=prod`` rejects dev-default safety knobs.

        Critical checklist items (auth, rate-limit, CORS) block startup with a
        single aggregated error; softer items surface via :meth:`prod_warnings`.
        """
        if self.app_env != "prod":
            return self
        problems: list[str] = []
        if not self.auth_enabled:
            problems.append("AUTH_ENABLED=true (Bearer-JWT enforcement is off)")
        if not self.rate_limit_enabled:
            problems.append(
                "ORYA_RATE_LIMIT_ENABLED=true (per-user rate limiting is off)"
            )
        if "*" in self.cors_origin_list:
            problems.append("CORS_ORIGINS=<ui origins> (wildcard * is dev-only)")
        if problems:
            raise ValueError(
                "ORYA_ENV=prod requires production-safe settings — fix: "
                + "; ".join(problems)
            )
        return self

    @property
    def cors_origin_list(self) -> list[str]:
        """``cors_origins`` as a list (CSV ``a,b`` or JSON ``["a","b"]``)."""
        return parse_env_list(self.cors_origins)

    @property
    def auth_public_path_list(self) -> list[str]:
        """``auth_public_paths`` as a list of path prefixes."""
        return parse_env_list(self.auth_public_paths)

    @property
    def rate_limit_trusted_list(self) -> list[str]:
        """``rate_limit_trusted_clients`` as a list of user ids / client IPs."""
        return parse_env_list(self.rate_limit_trusted_clients)

    def prod_warnings(self) -> list[str]:
        """Non-fatal production-readiness notes (A-12; ``orya config check``).

        Returns [] outside ``app_env="prod"`` — dev keeps kill-switch defaults.
        """
        if self.app_env != "prod":
            return []
        warnings: list[str] = []
        if not self.session_log_encryption_enabled:
            warnings.append(
                "ORYA_SESSION_LOG_ENCRYPTION_ENABLED is off — session-log "
                "messages.content/tool_calls are stored in plaintext (A-05)"
            )
        for name, url in (
            ("DATABASE_URL", self.database_url),
            ("REDIS_URL", self.redis_url),
        ):
            host = _url_host(url)
            if host in _LOCALHOSTS:
                warnings.append(
                    f"{name} points at {host} — acceptable for single-host "
                    "deploys, set an explicit remote URL for multi-host prod"
                )
        return warnings


def parse_env_list(value: str) -> list[str]:
    """Split a list-typed env value: JSON array if it looks like one, else CSV."""
    text = value.strip()
    if not text:
        return []
    if text.startswith("["):
        parsed = json.loads(text)
        return [str(item).strip() for item in parsed if str(item).strip()]
    return [part.strip() for part in text.split(",") if part.strip()]


def _url_host(url: str) -> str:
    """Hostname of a connection URL ("" when absent/unparsable)."""
    try:
        return (urlsplit(url).hostname or "").lower()
    except ValueError:
        return ""


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
