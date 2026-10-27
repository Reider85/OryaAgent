"""UI settings persistence (M-17): load/save the settings-panel state.

Provides the UI state (model, permission mode, allow-list) that persists
across Chainlit restarts. Since M-24 the Chainlit UI does not build a
graph itself: it sends this state with every ``POST /sessions/{id}/``
request and the FastAPI layer turns it into the model/policy overrides
(``app.core.permissions.build_policy``).

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
from app.core.llm.registry import load_models, load_providers

logger = logging.getLogger(__name__)


@dataclass
class UISettings:
    """UI state persisted to ``settings.ui_settings_path`` (M-17)."""

    model: str | None = None
    provider: str | None = None  # None = «Auto» (config/env default)
    permission_mode: str | None = None  # "strict" or "permissive"
    allow_list: list[str] = field(default_factory=list)
    working_dir: str | None = None  # the project the session has open

    @classmethod
    def default(cls) -> UISettings:
        """Return default settings (fallback for missing/corrupt file)."""
        return cls(
            model=None,  # Use default from config.yaml
            provider=None,  # «Auto» — provider resolved by the LLM seam
            permission_mode=None,  # Use default from config.yaml
            allow_list=[],
            working_dir=None,  # Tools fall back to the server's cwd
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert to JSON-serializable dict."""
        return {
            "model": self.model,
            "provider": self.provider,
            "permission_mode": self.permission_mode,
            "allow_list": self.allow_list,
            "working_dir": self.working_dir,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> UISettings:
        """Create from dict (validation for MVP)."""
        if not isinstance(data, dict):
            return cls.default()
        return cls(
            model=data.get("model"),
            provider=data.get("provider"),
            permission_mode=data.get("permission_mode"),
            allow_list=data.get("allow_list", []),
            working_dir=data.get("working_dir"),
        )


def settings_path() -> Path:
    """Path of the UI settings file (``ui_settings_path`` setting)."""
    return get_settings().ui_settings_path


def load_settings(path: Path | None = None) -> UISettings:
    """Load settings from JSON file; return defaults on missing/corrupt.

    Args:
        path: Override path for testing; defaults to ``settings.ui_settings_path``.

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
        path: Override path for testing; defaults to ``settings.ui_settings_path``.
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


def provider_choices() -> list[str]:
    """Provider dropdown: «Auto» first, then every providers.yaml entry.

    «Auto» (stored as ``provider=None``) keeps the legacy behavior: the
    provider comes from env/config, and the model dropdown lists every
    tool-capable alias across all providers.
    """
    return ["Auto", *sorted(load_providers())]


def model_choices(provider: str | None = None) -> list[str]:
    """Return list of model aliases with tool-calling support.

    Args:
        provider: When set, only aliases owned by that provider are
            returned (the dependent model combobox). A provider without
            any tool-capable alias falls back to its ``default_model``
            so the dropdown is never empty.

    Filters models.yaml for `supports_tools=true` (agent needs tools).
    Sorted alphabetically for consistent dropdown order.
    """
    models = load_models()
    if provider is None:
        return sorted(alias for alias, spec in models.items() if spec.supports_tools)

    owned = sorted(
        alias
        for alias, spec in models.items()
        if spec.supports_tools and spec.provider == provider
    )
    if owned:
        return owned
    spec = load_providers().get(provider)
    return [spec.default_model] if spec and spec.default_model else ["default"]
