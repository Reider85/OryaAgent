"""CLI: ``orya config show|check`` — effective settings + prod readiness (A-12).

``show`` prints the merged :class:`~app.core.config.Settings` (secrets
redacted) with a best-effort source per field (``env`` / ``.env`` /
``config.yaml`` / ``default``) so operators can verify that production
env-overrides actually took effect (12-factor).

``check`` validates the ``ORYA_ENV=prod`` guardrails and prints the
non-fatal warnings from :meth:`Settings.prod_warnings`; exit code 1 on a
misconfiguration. A guard-violating prod config makes ``get_settings()``
itself raise — the caller prints the aggregated validator message.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from pydantic import AliasChoices, SecretStr, ValidationError

from app.core.config import (
    _YAML_FALLBACKS,
    Settings,
    _dig,
    get_settings,
    load_expanded_user_config,
)


def _env_aliases(field: Any) -> list[str]:
    """Env spellings recognised for a Settings field."""
    alias = field.validation_alias
    if isinstance(alias, AliasChoices):
        return [choice for choice in alias.choices if isinstance(choice, str)]
    return []


def _dotenv_keys() -> set[str]:
    """Keys defined in the ``.env`` file of the current working directory."""
    path = Path(".env")
    if not path.exists():
        return set()
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return set()
    keys: set[str] = set()
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        keys.add(line.split("=", 1)[0].strip())
    return keys


def _field_source(name: str, field: Any, dotenv_keys: set[str], yaml_cfg: dict) -> str:
    """Best-effort origin of the effective value (matches precedence order)."""
    aliases = _env_aliases(field)
    if any(alias in os.environ for alias in aliases):
        return "env"
    if any(alias in dotenv_keys for alias in aliases):
        return ".env"
    entry = _YAML_FALLBACKS.get(name)
    if entry is not None and _dig(yaml_cfg, entry[1]) not in (None, ""):
        return "config.yaml"
    return "default"


def _display_value(value: Any) -> str:
    if isinstance(value, SecretStr):
        return "***" if value.get_secret_value() else "(not set)"
    if value is None:
        return "(not set)"
    return str(value)


def config_show_lines(settings: Settings | None = None) -> list[str]:
    """Redacted effective settings, one ``name = value [source]`` line each."""
    settings = settings if settings is not None else get_settings()
    dotenv_keys = _dotenv_keys()
    yaml_cfg = load_expanded_user_config()
    return [
        f"{name} = {_display_value(getattr(settings, name))} "
        f"[{_field_source(name, field, dotenv_keys, yaml_cfg)}]"
        for name, field in Settings.model_fields.items()
    ]


def run_config_show() -> int:
    """Print the redacted effective settings (always exit 0 when reachable)."""
    for line in config_show_lines():
        print(line)
    return 0


def run_config_check() -> int:
    """Exit 0 when safe; 1 on invalid config / ORYA_ENV=prod violations."""
    try:
        settings = get_settings()
    except ValidationError as exc:
        print(f"FAIL: invalid configuration\n{exc}")
        return 1
    if settings.app_env != "prod":
        print(
            "app_env=dev — production guardrails are OFF "
            "(set ORYA_ENV=prod to enforce them)"
        )
        return 0
    print("app_env=prod — guardrails OK (auth, rate-limit, CORS)")
    for warning in settings.prod_warnings():
        print(f"warning: {warning}")
    return 0
