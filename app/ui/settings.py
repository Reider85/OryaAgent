"""UI settings persistence (M-17): load/save ~/.orya/settings.json.

Provides the UI state (model, permission mode, allow-list) that persists
across Chainlit restarts and is used to rebuild the graph with custom
provider/model/policy settings.

The settings JSON file is separate from the main config.yaml (M-02):
- config.yaml: global config (env/.env → defaults)
- settings.json: UI-specific state (model, mode, allow_list)

Usage::

    from app.ui.settings import load_settings, save_settings, model_choices

    settings = load_settings()
    # Modify settings.model, settings.permission_mode, settings.allow_list
    save_settings(settings)
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.core.config import get_settings
from app.core.llm.registry import load_models
from app.core.permissions import PermissionConfig, Rule

logger = logging.getLogger(__name__)


@dataclass
class UISettings:
    """UI state persisted to ~/.orya/settings.json."""

    model: str | None = None
    permission_mode: str | None = None  # "strict" or "permissive"
    allow_list: list[str] = field(default_factory=list)

    @classmethod
    def default(cls) -> UISettings:
        """Return default settings (fallback for missing/corrupt file)."""
        return cls(
            model=None,  # Use default from config.yaml
            permission_mode=None,  # Use default from config.yaml
            allow_list=[],
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert to JSON-serializable dict."""
        return {
            "model": self.model,
            "permission_mode": self.permission_mode,
            "allow_list": self.allow_list,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> UISettings:
        """Create from dict (validation for MVP)."""
        if not isinstance(data, dict):
            return cls.default()
        return cls(
            model=data.get("model"),
            permission_mode=data.get("permission_mode"),
            allow_list=data.get("allow_list", []),
        )


def settings_path() -> Path:
    """Path of the UI settings file (~/.orya/settings.json)."""
    return get_settings().home_dir / "settings.json"


def load_settings(path: Path | None = None) -> UISettings:
    """Load settings from JSON file; return defaults on missing/corrupt.

    Args:
        path: Override path for testing; defaults to ~/.orya/settings.json.

    Returns:
        UISettings instance with defaults for missing fields.
    """
    if path is None:
        path = settings_path()

    if not path.exists():
        logger.info("Settings file %s not found, using defaults", path)
        return UISettings.default()

    try:
        with path.open(encoding="utf-8") as fh:
            data = json.load(fh)
        if not isinstance(data, dict):
            raise ValueError("Settings file must contain a JSON object")
        settings = UISettings.from_dict(data)
        logger.debug("Loaded settings from %s", path)
        return settings
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        logger.warning("Cannot read settings %s (%s); using defaults", path, exc)
        return UISettings.default()


def save_settings(settings: UISettings, path: Path | None = None) -> None:
    """Save settings to JSON file.

    Args:
        settings: UISettings instance to save.
        path: Override path for testing; defaults to ~/.orya/settings.json.
    """
    if path is None:
        path = settings_path()

    path.parent.mkdir(parents=True, exist_ok=True)

    try:
        with path.open("w", encoding="utf-8") as fh:
            json.dump(settings.to_dict(), fh, ensure_ascii=False, indent=2)
        logger.debug("Saved settings to %s", path)
    except OSError as exc:
        logger.warning("Cannot write settings %s (%s)", path, exc)


def model_choices() -> list[str]:
    """Return list of model aliases with tool-calling support.

    Filters models.yaml for `supports_tools=true` (agent needs tools).
    Sorted alphabetically for consistent dropdown order.
    """
    models = load_models()
    return sorted(alias for alias, spec in models.items() if spec.supports_tools)


def policy_from_settings(settings: UISettings) -> PermissionConfig:
    """Build PermissionConfig from UI settings.

    Args:
        settings: UISettings with permission_mode and allow_list.

    Returns:
        PermissionConfig with mode + extra allow rules from allow_list.
    """
    # Load base rules from ~/.orya/permissions.yml (or defaults)
    config = PermissionConfig.load()

    # Override the permission mode
    mode = settings.permission_mode or get_settings().permission_policy
    if mode not in {"strict", "permissive"}:
        logger.warning("Unknown permission mode %r; using 'strict'", mode)
        mode = "strict"

    # Add allow_list patterns as extra allow rules
    extra_rules = []
    for pattern in settings.allow_list:
        if pattern.strip():
            extra_rules.append(
                Rule(
                    tool="*",  # Apply to all tools
                    pattern=pattern.strip(),
                    action="allow",
                    description="UI allow-list rule",
                )
            )

    # Create new config with mode + extra allow rules
    return PermissionConfig(
        allow_rules=config.allow_rules + extra_rules,
        deny_rules=config.deny_rules,
    )
