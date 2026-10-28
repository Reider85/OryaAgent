"""Importers for migrating provider configs from other coding agents.

Supported sources:
- OpenCode  (sst/opencode):      ``~/.config/opencode/auth.json``
- Continue.dev:                  ``~/.continue/config.json``
- Aider:                         ``~/.aider.conf.yml``
- Cline / Roo Code:              VS Code globalStorage ``state.vscdb``
  (``<editor>/User/globalStorage/<extension-id>/state.vscdb``, SQLite,
  ``ItemTable`` -> ``storage.json`` -> JSON with ``apiConfiguration``)

Importers never copy plaintext API keys into ``~/.orya/config.yaml`` —
they write ``${ENV_VAR}`` placeholders (forbidden pattern: no plaintext
credentials in config) and report which env vars the user must export.
"""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
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
    "vertex": "google",
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
    overrides: dict[str, dict[str, Any]] | None = None,
) -> ImportReport:
    """Write provider placeholders into config.yaml and build the report.

    ``overrides`` optionally patches per-provider config fields (e.g. a
    custom ``base_url`` detected in the source agent's config).
    """
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
        for key, value in (overrides or {}).get(name, {}).items():
            entry[key] = value
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


# Cline and Roo Code (VS Code extensions) keep their API config in the
# editor's global storage: ``<editor>/User/globalStorage/<extension-id>/``
# with a SQLite database ``state.vscdb`` — table ``ItemTable``, key
# ``storage.json`` -> JSON blob containing an ``apiConfiguration`` block.
_CLINE_DB_FILENAME = "state.vscdb"
_CLINE_EXTENSION_IDS = (
    "saoudrizwan.claude-dev",  # Cline (ex Claude Dev)
    "rooveterinaryinc.roo-cline",  # Roo Code
    "roo-cline.roo-cline",  # Roo Code (older installs)
)
_CLINE_EDITORS = ("Code", "Code - Insiders", "VSCodium", "Cursor")

# Cline's apiConfiguration uses per-provider field names. Keys/models/base
# URLs live in provider-specific fields; ``apiKey`` is the common fallback.
_CLINE_KEY_FIELDS = {
    "anthropic": ("apiKey",),
    "openai": ("apiKey",),
    "openrouter": ("apiKey",),
    "deepseek": ("apiKey",),
    "qwen": ("qwenApiKey", "apiKey"),
    "google": ("geminiApiKey", "apiKey"),
    "ollama": (),
    "lmstudio": (),
}
_CLINE_MODEL_FIELDS = {
    "anthropic": "anthropicModelId",
    "openai": "openAIModelId",
    "openrouter": "openRouterModelId",
    "deepseek": "deepSeekModelId",
    "qwen": "qwenModelId",
    "google": "geminiModelId",
    "ollama": "ollamaModelId",
    "lmstudio": "lmStudioModelId",
}
_CLINE_BASE_URL_FIELDS = {
    "anthropic": "anthropicBaseUrl",
    "openai": "openAIBaseUrl",
    "openrouter": "openRouterBaseUrl",
    "deepseek": "deepSeekBaseUrl",
    "qwen": "qwenApiBaseUrl",
    "ollama": "ollamaBaseUrl",
    "lmstudio": "lmStudioBaseUrl",
}


def _vscode_global_storage_dirs() -> list[Path]:
    """Candidate ``<editor>/User/globalStorage`` dirs across platforms."""
    bases: list[Path] = []
    appdata = os.environ.get("APPDATA")
    if appdata:  # Windows
        bases.append(Path(appdata))
    bases.append(Path.home() / "Library" / "Application Support")  # macOS
    bases.append(Path.home() / ".config")  # Linux
    return [
        base / editor / "User" / "globalStorage"
        for base in bases
        for editor in _CLINE_EDITORS
    ]


def _find_cline_db() -> Path | None:
    """First existing Cline/Roo Code ``state.vscdb`` in known editor storages."""
    for base in _vscode_global_storage_dirs():
        for ext_id in _CLINE_EXTENSION_IDS:
            candidate = base / ext_id / _CLINE_DB_FILENAME
            if candidate.exists():
                return candidate
    return None


def _query_state_vscdb(db_path: Path) -> str | None:
    """Return the ``storage.json`` blob from ItemTable, or None if absent.

    Raises ``sqlite3.Error`` when the database is locked/unreadable — the
    caller falls back to reading a copy.
    """
    conn = sqlite3.connect(f"{db_path.as_uri()}?mode=ro", uri=True)
    try:
        row = conn.execute(
            "SELECT value FROM ItemTable WHERE key = 'storage.json'"
        ).fetchone()
    finally:
        conn.close()
    if row is None or row[0] is None:
        return None
    value = row[0]
    return value.decode("utf-8") if isinstance(value, bytes) else str(value)


def _read_cline_storage(db_path: Path) -> dict[str, Any]:
    """Load storage.json from state.vscdb (falls back to a copy if locked)."""
    try:
        raw = _query_state_vscdb(db_path)
    except sqlite3.Error:
        raw = None
    if raw is None:
        # A running VS Code can hold the db (WAL); read a snapshot copy.
        with tempfile.TemporaryDirectory() as tmp:
            snapshot = Path(tmp) / _CLINE_DB_FILENAME
            try:
                shutil.copyfile(db_path, snapshot)
                raw = _query_state_vscdb(snapshot)
            except (OSError, sqlite3.Error):
                raw = None
    if raw is None:
        raise ValueError(
            f"{db_path}: no 'storage.json' entry in ItemTable — nothing to import"
        )
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{db_path}: storage.json is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"{db_path}: storage.json must contain a JSON object")
    return data


def _cline_api_key(api_config: dict[str, Any], provider: str) -> str | None:
    """Pull the provider's API key out of apiConfiguration (tolerantly)."""
    for field in _CLINE_KEY_FIELDS.get(provider, ("apiKey",)):
        value = api_config.get(field)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def import_cline(
    cline_path: str | Path | None = None,
    config_path: str | Path | None = None,
) -> ImportReport:
    """Import from Cline / Roo Code VS Code globalStorage (``state.vscdb``).

    ``cline_path`` may point at ``state.vscdb`` itself or at the extension's
    globalStorage directory (``state.vscdb`` is appended). When omitted, the
    importer probes common VS Code-family editors (Code, Code Insiders,
    VSCodium, Cursor) for the Cline and Roo Code extension storages.

    Reads the active ``apiConfiguration`` (``apiProvider``, model id, custom
    base url) and writes registry-driven provider entries — API keys stay out
    of the config (``${ENV_VAR}`` placeholders only).
    """
    if cline_path:
        src = Path(cline_path)
        if src.is_dir():
            src = src / _CLINE_DB_FILENAME
    else:
        discovered = _find_cline_db()
        if discovered is None:
            raise FileNotFoundError(
                "Cline/Roo Code state.vscdb not found. Expected "
                "<editor>/User/globalStorage/saoudrizwan.claude-dev/"
                f"{_CLINE_DB_FILENAME} (or rooveterinaryinc.roo-cline) under "
                "%APPDATA%, ~/Library/Application Support or ~/.config. "
                "Pass cline_path explicitly to override."
            )
        src = discovered
    dst = Path(config_path) if config_path else user_config_path()

    if not src.exists():
        raise FileNotFoundError(f"Cline state.vscdb not found: {src}")

    data = _read_cline_storage(src)
    api_config = data.get("apiConfiguration")
    if not isinstance(api_config, dict):
        api_config = data.get("apiConfig")
    if not isinstance(api_config, dict):
        raise ValueError(f"{src}: no 'apiConfiguration' block in storage.json")
    provider_name = str(api_config.get("apiProvider", "")).strip()
    if not provider_name:
        raise ValueError(f"{src}: no 'apiProvider' configured — nothing to import")

    notes: list[str] = []
    found: dict[str, str | None] = {}
    overrides: dict[str, dict[str, Any]] = {}
    default_provider: str | None = None
    default_model: str | None = None

    mapped = _map_provider(provider_name)
    if mapped is None:
        if provider_name in ("vscode-lm", "vscode_lm"):
            notes.append(
                "Skipped 'vscode-lm' (VS Code LM API): it reuses the editor's "
                "built-in Copilot credentials, which cannot be exported."
            )
        else:
            notes.append(f"Skipped unknown Cline apiProvider '{provider_name}'")
    else:
        registry = load_providers()
        found[mapped] = _cline_api_key(api_config, mapped)
        default_provider = mapped
        model_field = _CLINE_MODEL_FIELDS.get(mapped)
        model = api_config.get(model_field) if model_field else None
        if isinstance(model, str) and model.strip():
            default_model = model.strip()

        base_field = _CLINE_BASE_URL_FIELDS.get(mapped)
        custom = api_config.get(base_field) if base_field else None
        if isinstance(custom, str) and custom.strip():
            custom_url = custom.strip().rstrip("/")
            registry_url = (registry[mapped].base_url or "").rstrip("/")
            if custom_url != registry_url:
                overrides[mapped] = {"base_url": custom_url}
                notes.append(
                    f"{mapped}: copied custom base URL {custom_url} from the "
                    "Cline config."
                )

        if found[mapped] is None and registry[mapped].env_var:
            notes.append(
                f"{mapped}: no API key in the Cline config (recent Cline "
                "versions keep keys in the VS Code Keychain) — export the env "
                "var instead."
            )

    return _finalize(
        source="cline",
        source_path=src,
        config_path=dst,
        found=found,
        default_provider=default_provider,
        default_model=default_model,
        extra_notes=notes,
        overrides=overrides,
    )


IMPORTERS = {
    "opencode": import_opencode,
    "continue": import_continue,
    "aider": import_aider,
    "cline": import_cline,
}
