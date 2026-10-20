"""Deprecated shim — the implementation moved to :mod:`app.core.config` (M-02).

Kept so that existing ``from app.core.llm import settings`` imports (M-01
factory, importers) continue to work. New code should import from
``app.core.config`` directly.
"""

from app.core.config import (
    ENV_VAR_PATTERN,
    clear_settings_cache,
    get_settings,
    is_unresolved,
    llm_block,
    load_expanded_user_config,
    load_user_config,
    provider_block,
    user_config_path,
)

__all__ = [
    "ENV_VAR_PATTERN",
    "clear_settings_cache",
    "get_settings",
    "is_unresolved",
    "llm_block",
    "load_expanded_user_config",
    "load_user_config",
    "provider_block",
    "user_config_path",
]
