"""Unit tests for M-17 — app.ui.settings (load/save, model choices, policy).

Tests the UI settings persistence, model choices filtering, and policy
building from settings. No Chainlit runtime needed — pure functions.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import patch

from app.core.config import clear_settings_cache
from app.ui.settings import (
    UISettings,
    load_settings,
    model_choices,
    save_settings,
    settings_path,
)


class TestUISettings:
    """Test UISettings dataclass and serialization."""

    def test_default_settings(self) -> None:
        """Test default settings creation."""
        settings = UISettings.default()
        assert settings.model is None
        assert settings.permission_mode is None
        assert settings.allow_list == []
        assert settings.working_dir is None

    def test_to_dict_from_dict(self) -> None:
        """Test serialization roundtrip."""
        original = UISettings(
            model="claude-sonnet-3.5",
            permission_mode="strict",
            allow_list=["read /tmp/*", "write *.py"],
            working_dir="C:/projects/OryaAgent",
        )

        data = original.to_dict()
        restored = UISettings.from_dict(data)

        assert restored.model == original.model
        assert restored.permission_mode == original.permission_mode
        assert restored.allow_list == original.allow_list
        assert restored.working_dir == original.working_dir

    def test_from_dict_partial(self) -> None:
        """Test from_dict with missing fields (use defaults)."""
        data = {
            "model": "gpt-4o",
            # permission_mode missing (should default to None)
            "allow_list": ["bash *.sh"],
        }

        settings = UISettings.from_dict(data)
        assert settings.model == "gpt-4o"
        assert settings.permission_mode is None
        assert settings.allow_list == ["bash *.sh"]
        assert settings.working_dir is None

    def test_from_dict_invalid(self) -> None:
        """Test from_dict with invalid data (fallback to defaults)."""
        # Invalid type
        settings = UISettings.from_dict("not a dict")
        assert isinstance(settings, UISettings)

        # Missing required fields
        settings = UISettings.from_dict({})
        assert settings.model is None
        assert settings.permission_mode is None
        assert settings.allow_list == []
        assert settings.working_dir is None

    def test_legacy_settings_file_without_working_dir(self) -> None:
        """A settings.json written before working_dir still loads."""
        settings = UISettings.from_dict(
            {"model": "glm-4.5-flash", "permission_mode": "strict", "allow_list": []}
        )
        assert settings.working_dir is None


class TestSettingsFile:
    """Test file-based settings persistence."""

    def test_load_missing_file(self) -> None:
        """Test loading missing file returns defaults."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "missing.json"
            settings = load_settings(path)
            assert settings == UISettings.default()

    def test_load_valid_file(self) -> None:
        """Test loading valid JSON file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "settings.json"
            data = {
                "model": "claude-haiku-3.5",
                "permission_mode": "permissive",
                "allow_list": ["read /tmp/*", "edit *.py"],
            }

            with path.open("w", encoding="utf-8") as fh:
                json.dump(data, fh)

            settings = load_settings(path)
            assert settings.model == "claude-haiku-3.5"
            assert settings.permission_mode == "permissive"
            assert settings.allow_list == ["read /tmp/*", "edit *.py"]

    def test_load_corrupt_file(self) -> None:
        """Test loading corrupt JSON file returns defaults."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "corrupt.json"
            path.write_text("not json {")

            settings = load_settings(path)
            assert settings == UISettings.default()

    def test_save_file(self) -> None:
        """Test saving settings to file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "settings.json"
            settings = UISettings(
                model="gpt-4o-mini",
                permission_mode="strict",
                allow_list=["bash test.sh"],
            )

            save_settings(settings, path)

            # Verify file contents
            assert path.exists()
            data = json.loads(path.read_text(encoding="utf-8"))
            assert data == settings.to_dict()

    def test_save_create_directory(self) -> None:
        """Test save creates parent directories."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "subdir" / "settings.json"
            settings = UISettings.default()

            save_settings(settings, path)
            assert path.exists()


class TestModelChoices:
    """Test model choices filtering."""

    @patch("app.ui.settings.load_models")
    def test_model_choices_filter(self, mock_load_models) -> None:
        """Test that only tool-supporting models are returned."""
        mock_load_models.return_value = {
            "claude-sonnet-3.5": type("Mock", (), {"supports_tools": True})(),
            "o1": type("Mock", (), {"supports_tools": False})(),
            "gpt-4o": type("Mock", (), {"supports_tools": True})(),
            "reasoning-model": type("Mock", (), {"supports_tools": False})(),
        }

        choices = model_choices()
        assert len(choices) == 2
        assert "claude-sonnet-3.5" in choices
        assert "gpt-4o" in choices
        assert "o1" not in choices
        assert "reasoning-model" not in choices

    @patch("app.ui.settings.load_models")
    def test_model_choices_sorted(self, mock_load_models) -> None:
        """Test that choices are sorted alphabetically."""
        mock_load_models.return_value = {
            "z-model": type("Mock", (), {"supports_tools": True})(),
            "a-model": type("Mock", (), {"supports_tools": True})(),
            "m-model": type("Mock", (), {"supports_tools": True})(),
        }

        choices = model_choices()
        assert choices == ["a-model", "m-model", "z-model"]


class TestSettingsPath:
    """The settings file location comes from the config (M-24 bugfix)."""

    def test_settings_path_uses_ui_settings_path(
        self, monkeypatch, tmp_path: Path
    ) -> None:
        monkeypatch.setenv("ORYA_UI_SETTINGS_PATH", str(tmp_path / "settings.json"))
        clear_settings_cache()
        try:
            assert settings_path() == tmp_path / "settings.json"
            # Missing file must yield defaults ? before M-24 this raised
            # AttributeError (``Settings`` had no ``home_dir``).
            assert load_settings() == UISettings.default()
        finally:
            clear_settings_cache()
