"""Importers: opencode / continue / aider / cline -> ~/.orya/config.yaml (M-01)."""

import json
import sqlite3

import pytest
import yaml

from app.core.llm.importers import (
    import_aider,
    import_cline,
    import_continue,
    import_opencode,
)


@pytest.fixture()
def config_path(tmp_path):
    return tmp_path / ".orya" / "config.yaml"


def test_import_opencode_flat_format(tmp_path, config_path):
    auth = tmp_path / "auth.json"
    auth.write_text(
        json.dumps(
            {
                "anthropic": {"type": "api_key", "apiKey": "sk-ant-secret"},
                "deepseek": {"type": "api_key", "apiKey": "sk-secret"},
                "openrouter": {"type": "api_key", "apiKey": "sk-or-secret"},
            }
        ),
        encoding="utf-8",
    )

    report = import_opencode(auth_path=auth, config_path=config_path)

    assert report.source == "opencode"
    assert set(report.found_providers) >= {"anthropic", "deepseek", "openrouter"}
    assert config_path.exists()

    written = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    providers = written["llm"]["providers"]
    assert providers["anthropic"]["api_key"] == "${ANTHROPIC_API_KEY}"
    assert providers["deepseek"]["api_key"] == "${DEEPSEEK_API_KEY}"
    # No plaintext keys anywhere in the written config
    raw = config_path.read_text(encoding="utf-8")
    assert "sk-ant-secret" not in raw
    assert "sk-secret" not in raw
    # Missing env vars reported
    assert "ANTHROPIC_API_KEY" in report.missing_env_vars


def test_import_opencode_nested_format(tmp_path, config_path):
    auth = tmp_path / "auth.json"
    auth.write_text(
        json.dumps(
            {
                "theme": "dark",
                "provider": {
                    "openai": {"type": "api_key", "apiKey": "sk-openai"},
                    "unknown-thing": {"apiKey": "x"},
                },
            }
        ),
        encoding="utf-8",
    )

    report = import_opencode(auth_path=auth, config_path=config_path)

    assert report.found_providers == ["openai"]
    assert any("unknown-thing" in note for note in report.notes)


def test_import_opencode_missing_file_raises(tmp_path, config_path):
    with pytest.raises(FileNotFoundError):
        import_opencode(auth_path=tmp_path / "nope.json", config_path=config_path)


def test_import_continue(tmp_path, config_path):
    cfg = tmp_path / "config.json"
    cfg.write_text(
        json.dumps(
            {
                "models": [
                    {
                        "title": "DS Coder",
                        "provider": "deepseek",
                        "model": "deepseek-chat",
                        "apiBase": "https://api.deepseek.com/v1",
                        "apiKey": "sk-secret",
                    },
                    {
                        "title": "GPT-4o",
                        "provider": "openai",
                        "model": "gpt-4o",
                        "apiKey": "sk-openai",
                    },
                ]
            }
        ),
        encoding="utf-8",
    )

    report = import_continue(continue_path=cfg, config_path=config_path)

    assert report.found_providers == ["deepseek", "openai"]
    assert report.default_provider == "deepseek"
    assert report.default_model == "deepseek-chat"

    written = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    assert written["llm"]["default_provider"] == "deepseek"
    assert written["llm"]["default_model"] == "deepseek-chat"
    assert "sk-secret" not in config_path.read_text(encoding="utf-8")


def test_import_continue_missing_models_list(tmp_path, config_path):
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({"themes": []}), encoding="utf-8")
    with pytest.raises(ValueError, match="models"):
        import_continue(continue_path=cfg, config_path=config_path)


def test_import_aider(tmp_path, config_path):
    conf = tmp_path / ".aider.conf.yml"
    conf.write_text("model: deepseek/deepseek-chat\n", encoding="utf-8")

    report = import_aider(aider_path=conf, config_path=config_path)

    assert report.found_providers == ["deepseek"]
    assert report.default_provider == "deepseek"
    assert report.default_model == "deepseek-chat"

    written = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    assert written["llm"]["providers"]["deepseek"]["api_key"] == "${DEEPSEEK_API_KEY}"


def test_import_aider_unsupported_provider(tmp_path, config_path):
    conf = tmp_path / ".aider.conf.yml"
    conf.write_text("model: nonsense/model-v9\n", encoding="utf-8")
    with pytest.raises(ValueError, match="not supported"):
        import_aider(aider_path=conf, config_path=config_path)


def test_import_merges_with_existing_config(tmp_path, config_path):
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        yaml.safe_dump(
            {
                "llm": {
                    "default_provider": "ollama",
                    "providers": {"ollama": {"default_model": "llama3.3:70b"}},
                },
                "other_section": {"keep": True},
            }
        ),
        encoding="utf-8",
    )

    auth = tmp_path / "auth.json"
    auth.write_text(json.dumps({"deepseek": {"apiKey": "sk-x"}}), encoding="utf-8")
    import_opencode(auth_path=auth, config_path=config_path)

    written = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    # Existing entries preserved
    assert written["llm"]["providers"]["ollama"]["default_model"] == "llama3.3:70b"
    assert written["other_section"]["keep"] is True
    # New provider merged in
    assert written["llm"]["providers"]["deepseek"]["api_key"] == "${DEEPSEEK_API_KEY}"


def _make_cline_db(path, storage):
    """Create a fake Cline/Roo Code state.vscdb with one storage.json entry."""
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    with conn:
        conn.execute("CREATE TABLE ItemTable (key TEXT PRIMARY KEY, value BLOB)")
        conn.execute(
            "INSERT INTO ItemTable (key, value) VALUES (?, ?)",
            ("storage.json", json.dumps(storage)),
        )
    conn.close()
    return path


def test_import_cline_deepseek(tmp_path, config_path):
    db = _make_cline_db(
        tmp_path / "state.vscdb",
        {
            "apiConfiguration": {
                "apiProvider": "deepseek",
                "apiKey": "sk-secret",
                "deepSeekModelId": "deepseek-chat",
                # Matches the registry base_url -> must NOT be an override
                "deepSeekBaseUrl": "https://api.deepseek.com/v1",
            }
        },
    )

    report = import_cline(cline_path=db, config_path=config_path)

    assert report.source == "cline"
    assert report.found_providers == ["deepseek"]
    assert report.default_provider == "deepseek"
    assert report.default_model == "deepseek-chat"

    written = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    providers = written["llm"]["providers"]
    assert providers["deepseek"]["api_key"] == "${DEEPSEEK_API_KEY}"
    raw = config_path.read_text(encoding="utf-8")
    assert "sk-secret" not in raw
    assert "DEEPSEEK_API_KEY" in report.missing_env_vars
    assert not any("custom base URL" in note for note in report.notes)


def test_import_cline_custom_base_url(tmp_path, config_path):
    db = _make_cline_db(
        tmp_path / "state.vscdb",
        {
            "apiConfiguration": {
                "apiProvider": "ollama",
                "ollamaModelId": "llama3.3:70b",
                "ollamaBaseUrl": "http://localhost:11500/v1",
            }
        },
    )

    report = import_cline(cline_path=db, config_path=config_path)

    assert report.found_providers == ["ollama"]
    written = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    assert (
        written["llm"]["providers"]["ollama"]["base_url"] == "http://localhost:11500/v1"
    )
    assert any("custom base URL" in note for note in report.notes)
    # Local provider without env_var -> nothing to export
    assert report.missing_env_vars == []


def test_import_cline_qwen_qwen_api_key_field(tmp_path, config_path):
    db = _make_cline_db(
        tmp_path / "state.vscdb",
        {
            "apiConfiguration": {
                "apiProvider": "qwen",
                "qwenApiKey": "sk-dash-secret",
                "qwenModelId": "qwen3-coder-plus",
            }
        },
    )

    report = import_cline(cline_path=db, config_path=config_path)

    assert report.found_providers == ["qwen"]
    assert "DASHSCOPE_API_KEY" in report.missing_env_vars
    assert "sk-dash-secret" not in config_path.read_text(encoding="utf-8")


def test_import_cline_vscode_lm_skipped(tmp_path, config_path):
    db = _make_cline_db(
        tmp_path / "state.vscdb",
        {"apiConfiguration": {"apiProvider": "vscode-lm"}},
    )

    report = import_cline(cline_path=db, config_path=config_path)

    assert report.found_providers == []
    assert any("vscode-lm" in note for note in report.notes)


def test_import_cline_resolves_extension_directory(tmp_path, config_path):
    # Directory (not file) path, named after the Roo Code extension id
    ext_dir = tmp_path / "globalStorage" / "rooveterinaryinc.roo-cline"
    _make_cline_db(
        ext_dir / "state.vscdb",
        {
            "apiConfiguration": {
                "apiProvider": "anthropic",
                "apiKey": "sk-ant-secret",
                "anthropicModelId": "claude-sonnet-3.5",
            }
        },
    )

    report = import_cline(cline_path=ext_dir, config_path=config_path)

    assert report.found_providers == ["anthropic"]
    assert report.default_model == "claude-sonnet-3.5"
    written = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    assert written["llm"]["providers"]["anthropic"]["api_key"] == "${ANTHROPIC_API_KEY}"


def test_import_cline_missing_file_raises(tmp_path, config_path):
    with pytest.raises(FileNotFoundError):
        import_cline(
            cline_path=tmp_path / "nope" / "state.vscdb", config_path=config_path
        )


def test_import_cline_no_api_provider_raises(tmp_path, config_path):
    db = _make_cline_db(tmp_path / "state.vscdb", {"apiConfiguration": {}})
    with pytest.raises(ValueError, match="apiProvider"):
        import_cline(cline_path=db, config_path=config_path)
