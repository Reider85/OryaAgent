"""Unit tests for M-17 — app.ui.settings (load/save, model choices, policy).

Tests the UI settings persistence, model choices filtering, and policy
building from settings. No Chainlit runtime needed — pure functions.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import patch

from app.ui.settings import (
    UISettings,
    load_settings,
    model_choices,
    policy_from_settings,
    save_settings,
)


class TestUISettings:
    """Test UISettings dataclass and serialization."""

    def test_default_settings(self) -> None:
        """Test default settings creation."""
        settings = UISettings.default()
        assert settings.model is None
        assert settings.permission_mode is None
        assert settings.allow_list == []

    def test_to_dict_from_dict(self) -> None:
        """Test serialization roundtrip."""
        original = UISettings(
            model="claude-sonnet-3.5",
            permission_mode="strict",
            allow_list=["read /tmp/*", "write *.py"],
        )

        data = original.to_dict()
        restored = UISettings.from_dict(data)

        assert restored.model == original.model
        assert restored.permission_mode == original.permission_mode
        assert restored.allow_list == original.allow_list

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


class TestPolicyFromSettings:
    """Test building PermissionConfig from UI settings."""

    def test_policy_from_settings_basic(self) -> None:
        """Test basic policy building with mode."""
        from app.core.permissions import PermissionConfig, Rule

        settings = UISettings(
            model="claude-sonnet-3.5",
            permission_mode="strict",
            allow_list=[],
        )
        base = PermissionConfig(
            allow_rules=[Rule(tool="read", pattern="*.md", action="allow")],
            deny_rules=[],
        )

        with (
            patch.object(PermissionConfig, "load", return_value=base),
            patch("app.ui.settings.get_settings") as mock_gs,
        ):
            mock_gs.return_value.permission_policy = "strict"
            result = policy_from_settings(settings)

        # Base rules preserved, no extra rules added
        assert len(result.allow_rules) == 1
        assert result.allow_rules[0].pattern == "*.md"
        assert result.deny_rules == []

    def test_policy_from_settings_with_allow_list(self) -> None:
        """Test policy building with allow_list rules."""
        from app.core.permissions import PermissionConfig

        settings = UISettings(
            model="gpt-4o",
            permission_mode="permissive",
            allow_list=["read /tmp/*", "write *.py"],
        )
        base = PermissionConfig(allow_rules=[], deny_rules=[])

        with (
            patch.object(PermissionConfig, "load", return_value=base),
            patch("app.ui.settings.get_settings") as mock_gs,
        ):
            mock_gs.return_value.permission_policy = "permissive"
            result = policy_from_settings(settings)

        # Should have original rules + allow_list rules
        assert len(result.allow_rules) == 2
        assert result.allow_rules[0].pattern == "read /tmp/*"
        assert result.allow_rules[0].tool == "*"
        assert result.allow_rules[1].pattern == "write *.py"
        assert result.allow_rules[1].tool == "*"

    def test_policy_from_settings_mode_fallback(self) -> None:
        """Test mode fallback to config default."""
        from app.core.permissions import PermissionConfig

        settings = UISettings(
            model="claude-haiku-3.5",
            permission_mode=None,  # Use default
            allow_list=[],
        )
        base = PermissionConfig(allow_rules=[], deny_rules=[])

        with (
            patch.object(PermissionConfig, "load", return_value=base),
            patch("app.ui.settings.get_settings") as mock_gs,
        ):
            mock_gs.return_value.permission_policy = "permissive"
            result = policy_from_settings(settings)

        assert result.allow_rules == []
        assert result.deny_rules == []

    def test_policy_from_settings_invalid_mode(self) -> None:
        """Test invalid mode falls back to strict."""
        from app.core.permissions import PermissionConfig

        settings = UISettings(
            model="gpt-4o-mini",
            permission_mode="invalid_mode",  # Should fallback to strict
            allow_list=[],
        )
        base = PermissionConfig(allow_rules=[], deny_rules=[])

        with (
            patch.object(PermissionConfig, "load", return_value=base),
            patch("app.ui.settings.get_settings") as mock_gs,
        ):
            mock_gs.return_value.permission_policy = "strict"
            result = policy_from_settings(settings)

        assert result.allow_rules == []
        assert result.deny_rules == []
