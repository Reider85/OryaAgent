"""Importers for migrating provider configs from other coding agents.

Supported sources:
- OpenCode  (sst/opencode):      ``~/.config/opencode/auth.json``
- Continue.dev:                  ``~/.continue/config.json``
- Aider:                         ``~/.aider.conf.yml``

Importers never copy plaintext API keys into ``~/.orya/config.yaml`` —
they write ``${ENV_VAR}`` placeholders (forbidden pattern: no plaintext
credentials in config) and report which env vars the user must export.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

from app.core.config import user_config_path
from app.core.llm.registry import load_providers

# Foreign-agent provider names -> OryaAgent provider keys.
# Unknown names are kept as-is when they exist in providers.yaml.
_PROVIDER_ALIASES = {
    "google_generative-studio": "google",
    "google_genai": "google",
    "gemini": "google",
    "vertexai": "google",
    "llamafile": "llamacpp",
    "mistral": "openrouter",  # no native mistral provider in MVP — route via aggregator
    "togetherai": "together",
    "nvidia_nim": "nvidia",
}


class ImportReport(BaseModel):
    """Result of an import run."""

    source: str
    source_path: str
    config_path: str
    found_providers: list[str] = Field(default_factory=list)
    written_providers: list[str] = Field(default_factory=list)
    missing_env_vars: list[str] = Field(default_factory=list)
    default_provider: str | None = None
    default_model: str | None = None
    notes: list[str] = Field(default_factory=list)


def _map_provider(name: str) -> str | None:
    """Map a foreign provider name to ours; None if unknown to the registry."""
    candidates = [name, _PROVIDER_ALIASES.get(name, "")]
    for candidate in candidates:
        if candidate and candidate in load_providers():
            return candidate
    return None


def _extract_key(entry: Any) -> str | None:
    """Tolerantly pull an API key out of a foreign config entry."""
    if isinstance(entry, str):
        return entry if entry.strip() else None
    if isinstance(entry, dict):
        for field in ("apiKey", "api_key", "key", "token"):
            value = entry.get(field)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return None


def _merge_config(config_path: Path, llm_updates: dict[str, Any]) -> None:
    """Deep-merge ``llm_updates`` into the llm block of config_path (atomic)."""
    existing: dict[str, Any] = {}
    if config_path.exists():
        with config_path.open(encoding="utf-8") as fh:
            existing = yaml.safe_load(fh) or {}

    llm_block = existing.get("llm") if isinstance(existing.get("llm"), dict) else {}
    providers_block = (
        llm_block.get("providers")
        if isinstance(llm_block.get("providers"), dict)
        else {}
    )

    new_providers = llm_updates.get("providers", {})
    merged_providers = dict(providers_block)
    for name, entry in new_providers.items():
        current = (
            merged_providers.get(name)
            if isinstance(merged_providers.get(name), dict)
            else {}
        )
        merged_providers[name] = {**current, **entry}

    merged_llm = {
        **llm_block,
        **{k: v for k, v in llm_updates.items() if k != "providers"},
    }
    merged_llm["providers"] = merged_providers
    existing["llm"] = merged_llm

    config_path.parent.mkdir(parents=True, exist_ok=True)
    # Atomic write: dump to a temp file in the same dir, then os.replace.
    fd, tmp_name = tempfile.mkstemp(
        dir=str(config_path.parent), prefix=".config-", suffix=".yaml"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            yaml.safe_dump(existing, fh, allow_unicode=True, sort_keys=False)
        os.replace(tmp_name, config_path)
    except BaseException:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)
        raise


def _finalize(
    source: str,
    source_path: Path,
    config_path: Path,
    found: dict[str, str | None],
    default_provider: str | None,
    default_model: str | None,
    extra_notes: list[str] | None = None,
) -> ImportReport:
    """Write provider placeholders into config.yaml and build the report."""
    providers_cfg: dict[str, dict[str, Any]] = {}
    missing: list[str] = []
    notes: list[str] = list(extra_notes or [])
    registry = load_providers()
    written: list[str] = []

    for name in sorted(found):
        spec = registry[name]
        entry: dict[str, Any] = {
            "api_key": f"${{{spec.env_var}}}" if spec.env_var else "local"
        }
        if spec.base_url:
            entry["base_url"] = spec.base_url
        if spec.default_model:
            entry["default_model"] = spec.default_model
        providers_cfg[name] = entry
        written.append(name)
        if spec.env_var:
            if os.environ.get(spec.env_var):
                notes.append(f"{spec.env_var} is already set in this environment.")
            else:
                missing.append(spec.env_var)

    llm_updates: dict[str, Any] = {"providers": providers_cfg}
    if default_provider and default_provider in found:
        llm_updates["default_provider"] = default_provider
        if default_model:
            llm_updates["default_model"] = default_model

    _merge_config(config_path, llm_updates)

    if found:
        notes.append(
            "API keys detected in the source config are NOT copied to "
            f"{config_path} (no plaintext credentials). Export the env vars "
            "listed in missing_env_vars to activate the providers."
        )

    return ImportReport(
        source=source,
        source_path=str(source_path),
        config_path=str(config_path),
        found_providers=sorted(found),
        written_providers=written,
        missing_env_vars=missing,
        default_provider=default_provider,
        default_model=default_model,
        notes=notes,
    )


def import_opencode(
    auth_path: str | Path | None = None,
    config_path: str | Path | None = None,
) -> ImportReport:
    """Import providers from OpenCode ``auth.json``.

    Parses both flat (``{"anthropic": {"apiKey": "..."}}``) and nested
    (``{"provider": {"anthropic": {...}}}``) layouts, writes ``${ENV}``
    placeholders into ``~/.orya/config.yaml``.
    """
    src = (
        Path(auth_path)
        if auth_path
        else Path.home() / ".config" / "opencode" / "auth.json"
    )
    dst = Path(config_path) if config_path else user_config_path()

    if not src.exists():
        raise FileNotFoundError(
            f"OpenCode auth file not found: {src}. Expected ~/.config/opencode/auth.json"
        )
    with src.open(encoding="utf-8") as fh:
        data = json.load(fh)

    raw_entries: dict[str, Any] = {}
    if isinstance(data.get("provider"), dict):
        raw_entries.update(data["provider"])
    for key, value in data.items():
        if key in ("provider", "theme", "$schema"):
            continue
        raw_entries[key] = value

    found: dict[str, str | None] = {}
    unknown: list[str] = []
    for name, entry in raw_entries.items():
        mapped = _map_provider(name)
        if mapped is None:
            unknown.append(name)
            continue
        found[mapped] = _extract_key(entry)

    notes = []
    if unknown:
        notes.append(f"Skipped unknown providers in auth.json: {', '.join(unknown)}")

    default_provider = next(iter(found), None)
    default_model = (
        load_providers()[default_provider].default_model if default_provider else None
    )
    return _finalize(
        source="opencode",
        source_path=src,
        config_path=dst,
        found=found,
        default_provider=default_provider,
        default_model=default_model,
        extra_notes=notes,
    )


def import_continue(
    continue_path: str | Path | None = None,
    config_path: str | Path | None = None,
) -> ImportReport:
    """Import models from Continue.dev ``config.json`` (models[].apiBase/apiKey)."""
    src = (
        Path(continue_path)
        if continue_path
        else Path.home() / ".continue" / "config.json"
    )
    dst = Path(config_path) if config_path else user_config_path()

    if not src.exists():
        raise FileNotFoundError(
            f"Continue config not found: {src}. Expected ~/.continue/config.json"
        )
    with src.open(encoding="utf-8") as fh:
        data = json.load(fh)

    models = data.get("models") if isinstance(data, dict) else None
    if not isinstance(models, list):
        raise ValueError(f"{src} has no 'models' list — nothing to import")

    found: dict[str, str | None] = {}
    notes: list[str] = []
    default_provider: str | None = None
    default_model: str | None = None

    for item in models:
        if not isinstance(item, dict):
            continue
        provider_name = str(item.get("provider", "")).strip()
        mapped = _map_provider(provider_name)
        if mapped is None:
            notes.append(f"Skipped unknown provider '{provider_name}' in {src}")
            continue
        found[mapped] = _extract_key(item)
        if default_provider is None:
            default_provider = mapped
            model = item.get("model")
            if isinstance(model, str) and model:
                default_model = model

    return _finalize(
        source="continue",
        source_path=src,
        config_path=dst,
        found=found,
        default_provider=default_provider,
        default_model=default_model,
        extra_notes=notes,
    )


def import_aider(
    aider_path: str | Path | None = None,
    config_path: str | Path | None = None,
) -> ImportReport:
    """Import from ``~/.aider.conf.yml`` (LiteLLM-convention model names)."""
    src = Path(aider_path) if aider_path else Path.home() / ".aider.conf.yml"
    dst = Path(config_path) if config_path else user_config_path()

    if not src.exists():
        raise FileNotFoundError(
            f"Aider config not found: {src}. Expected ~/.aider.conf.yml"
        )
    with src.open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    if not isinstance(data, dict):
        raise ValueError(f"{src} must contain a YAML mapping")

    model = data.get("model") or data.get("model-settings")
    if isinstance(model, dict):
        model = model.get("name")
    if not isinstance(model, str) or "/" not in model:
        raise ValueError(
            f"{src}: no LiteLLM-convention model (e.g. 'deepseek/deepseek-chat') "
            "found — cannot infer provider"
        )

    provider_part, _, model_part = model.partition("/")
    mapped = _map_provider(provider_part)
    if mapped is None:
        raise ValueError(
            f"{src}: provider '{provider_part}' from model '{model}' is not "
            f"supported by OryaAgent"
        )

    found = {mapped: None}
    notes = [
        "Aider configs reference env vars rather than storing keys — "
        "ensure the provider env var is exported."
    ]
    return _finalize(
        source="aider",
        source_path=src,
        config_path=dst,
        found=found,
        default_provider=mapped,
        default_model=model_part or None,
        extra_notes=notes,
    )


IMPORTERS = {
    "opencode": import_opencode,
    "continue": import_continue,
    "aider": import_aider,
}
