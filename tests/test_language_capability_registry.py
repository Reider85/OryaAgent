"""Test suite for LanguageCapabilityRegistry (B-30)."""

from pathlib import Path

import pytest

from app.core.capability.language_registry import (
    LanguageCapabilityRegistry,
    get_language_capability_registry,
    reset_language_capability_registry,
)


class TestLanguageCapability:
    """Test cases for LanguageCapability dataclass."""

    def test_java_capability(self):
        """Test Java language capability."""
        registry = LanguageCapabilityRegistry()
        java_cap = registry.resolve("java")

        assert java_cap.language == "java"
        assert java_cap.lsp_server == "jdtls"
        assert ".java" in java_cap.file_extensions
        assert java_cap.skill_bundle == "java-maven"
        assert "auto-format-google-java-format" in java_cap.hooks
        assert "auto-lint-checkstyle" in java_cap.hooks

    def test_rust_capability(self):
        """Test Rust language capability."""
        registry = LanguageCapabilityRegistry()
        rust_cap = registry.resolve("rust")

        assert rust_cap.language == "rust"
        assert rust_cap.lsp_server == "rust-analyzer"
        assert ".rs" in rust_cap.file_extensions
        assert rust_cap.skill_bundle == "rust-cargo"
        assert "auto-format-rustfmt" in rust_cap.hooks
        assert "auto-lint-clippy" in rust_cap.hooks

    def test_go_capability(self):
        """Test Go language capability."""
        registry = LanguageCapabilityRegistry()
        go_cap = registry.resolve("go")

        assert go_cap.language == "go"
        assert go_cap.lsp_server == "gopls"
        assert ".go" in go_cap.file_extensions
        assert go_cap.skill_bundle == "go-mod"
        assert "auto-format-gofmt" in go_cap.hooks
        assert "auto-lint-govet" in go_cap.hooks

    def test_javascript_capability(self):
        """Test JavaScript language capability."""
        registry = LanguageCapabilityRegistry()
        js_cap = registry.resolve("javascript")

        assert js_cap.language == "javascript"
        assert js_cap.lsp_server == "typescript-language-server"
        assert ".js" in js_cap.file_extensions
        assert js_cap.skill_bundle == "javascript-node"
        assert "auto-format-prettier" in js_cap.hooks
        assert "auto-lint-eslint" in js_cap.hooks

    def test_frontend_capability(self):
        """Test Frontend language capability."""
        registry = LanguageCapabilityRegistry()
        frontend_cap = registry.resolve("frontend")

        assert frontend_cap.language == "frontend"
        assert frontend_cap.lsp_server == "typescript-language-server"
        assert ".tsx" in frontend_cap.file_extensions
        assert frontend_cap.skill_bundle == "frontend-tsx"
        assert "auto-format-prettier" in frontend_cap.hooks
        assert "auto-lint-eslint" in frontend_cap.hooks
        assert "accessibility-hint-axe" in frontend_cap.hooks

    def test_build_cmd_with_settings(self):
        """Test build command with settings override."""
        registry = LanguageCapabilityRegistry()
        java_cap = registry.resolve("java")

        # Test default command
        assert "mvn compile" in java_cap.get_build_cmd_with_settings()

        # Test settings override (mock)
        from unittest.mock import patch

        with patch("app.core.config.get_settings") as mock_settings:
            mock_settings.return_value.ORYA_JAVA_BUILD_CMD = "custom build"
            assert java_cap.get_build_cmd_with_settings() == "custom build"

    def test_test_cmd_with_settings(self):
        """Test test command with settings override."""
        registry = LanguageCapabilityRegistry()
        rust_cap = registry.resolve("rust")

        # Test default command
        assert "cargo test" in rust_cap.get_test_cmd_with_settings()

        # Test settings override (mock)
        from unittest.mock import patch

        with patch("app.core.config.get_settings") as mock_settings:
            mock_settings.return_value.ORYA_RUST_TEST_CMD = "custom test"
            assert rust_cap.get_test_cmd_with_settings() == "custom test"

    def test_lint_cmd_with_settings(self):
        """Test lint command with settings override."""
        registry = LanguageCapabilityRegistry()
        go_cap = registry.resolve("go")

        # Test default command
        assert "go vet" in go_cap.get_lint_cmd_with_settings()

        # Test settings override (mock)
        from unittest.mock import patch

        with patch("app.core.config.get_settings") as mock_settings:
            mock_settings.return_value.ORYA_GO_LINT_CMD = "custom lint"
            assert go_cap.get_lint_cmd_with_settings() == "custom lint"

    def test_format_cmd_with_settings(self):
        """Test format command with settings override."""
        registry = LanguageCapabilityRegistry()
        js_cap = registry.resolve("javascript")

        # Test default command
        assert "prettier --write" in js_cap.get_format_cmd_with_settings()

        # Test settings override (mock)
        from unittest.mock import patch

        with patch("app.core.config.get_settings") as mock_settings:
            mock_settings.return_value.ORYA_JAVASCRIPT_FORMAT_CMD = "custom format"
            assert js_cap.get_format_cmd_with_settings() == "custom format"


class TestLanguageCapabilityRegistry:
    """Test cases for LanguageCapabilityRegistry."""

    def setup_method(self):
        """Setup test environment."""
        reset_language_capability_registry()

    def test_registry_initialization(self):
        """Test registry initialization."""
        registry = LanguageCapabilityRegistry()

        assert len(registry.capabilities) == 5  # java, rust, go, javascript, frontend
        assert len(registry.extension_map) > 0

    def test_resolve_supported_language(self):
        """Test resolving supported languages."""
        registry = LanguageCapabilityRegistry()

        # Test supported languages
        for lang in ["java", "rust", "go", "javascript", "frontend"]:
            capability = registry.resolve(lang)
            assert capability.language == lang

    def test_resolve_unsupported_language(self):
        """Test resolving unsupported language."""
        registry = LanguageCapabilityRegistry()

        with pytest.raises(ValueError, match="Unsupported language: klingon"):
            registry.resolve("klingon")

    def test_detect_language_from_file(self):
        """Test language detection from file path."""
        registry = LanguageCapabilityRegistry()

        # Test Java file
        java_file = Path("src/com/example/Main.java")
        assert registry.detect(java_file) == "java"

        # Test Rust file
        rust_file = Path("src/lib.rs")
        assert registry.detect(rust_file) == "rust"

        # Test Go file
        go_file = Path("cmd/server/main.go")
        assert registry.detect(go_file) == "go"

        # Test JavaScript file
        js_file = Path("src/utils.js")
        assert registry.detect(js_file) == "javascript"

        # Test Frontend file
        frontend_file = Path("src/App.tsx")
        assert registry.detect(frontend_file) == "frontend"

    def test_detect_unsupported_file(self):
        """Test detecting language from unsupported file."""
        registry = LanguageCapabilityRegistry()

        with pytest.raises(
            ValueError, match="Cannot detect language from file extension"
        ):
            registry.detect("unknown.xyz")

    def test_is_supported_language(self):
        """Test checking if language is supported."""
        registry = LanguageCapabilityRegistry()

        # Test supported languages
        for lang in ["java", "rust", "go", "javascript", "frontend"]:
            assert registry.is_supported(lang) is True

        # Test unsupported language
        assert registry.is_supported("klingon") is False

    def test_list_supported_languages(self):
        """Test listing supported languages."""
        registry = LanguageCapabilityRegistry()
        supported = registry.list_supported()

        assert len(supported) == 5
        assert "java" in supported
        assert "rust" in supported
        assert "go" in supported
        assert "javascript" in supported
        assert "frontend" in supported

    def test_get_capability_for_file(self):
        """Test getting capability for a specific file."""
        registry = LanguageCapabilityRegistry()

        # Test Java file
        java_file = Path("src/com/example/Main.java")
        capability = registry.get_capability_for_file(java_file)
        assert capability.language == "java"

        # Test Rust file
        rust_file = Path("src/lib.rs")
        capability = registry.get_capability_for_file(rust_file)
        assert capability.language == "rust"

    def test_global_registry_instance(self):
        """Test global registry instance."""
        # Test getting instance
        registry1 = get_language_capability_registry()
        registry2 = get_language_capability_registry()

        assert registry1 is registry2  # Same instance

        # Test resetting
        reset_language_capability_registry()
        registry3 = get_language_capability_registry()

        assert registry3 is not registry1  # New instance


class TestLanguageCapabilityIntegration:
    """Integration tests for LanguageCapabilityRegistry."""

    def setup_method(self):
        """Setup test environment."""
        reset_language_capability_registry()

    def test_capability_consistency(self):
        """Test that all capabilities are consistent."""
        registry = LanguageCapabilityRegistry()

        for lang in registry.list_supported():
            capability = registry.resolve(lang)

            # Check required fields
            assert capability.language == lang
            assert capability.lsp_server
            assert len(capability.file_extensions) > 0
            assert capability.build_cmd
            assert capability.test_cmd
            assert capability.skill_bundle
            assert len(capability.hooks) > 0

            # Check that hooks are valid
            for hook in capability.hooks:
                assert isinstance(hook, str)
                assert len(hook) > 0

    def test_extension_mapping_consistency(self):
        """Test that extension mapping is consistent."""
        registry = LanguageCapabilityRegistry()

        # Check that all extensions are mapped
        for capability in registry.capabilities.values():
            for ext in capability.file_extensions:
                assert ext in registry.extension_map
                assert registry.extension_map[ext] == capability.language

    def test_capability_for_each_language(self):
        """Test capability details for each language."""
        registry = LanguageCapabilityRegistry()

        # Java
        java_cap = registry.resolve("java")
        assert java_cap.lsp_server == "jdtls"
        assert java_cap.skill_bundle == "java-maven"
        assert "extract_method" in java_cap.refactor_actions

        # Rust
        rust_cap = registry.resolve("rust")
        assert rust_cap.lsp_server == "rust-analyzer"
        assert rust_cap.skill_bundle == "rust-cargo"
        assert "extract_function" in rust_cap.refactor_actions

        # Go
        go_cap = registry.resolve("go")
        assert go_cap.lsp_server == "gopls"
        assert go_cap.skill_bundle == "go-mod"
        assert "extract_function" in go_cap.refactor_actions

        # JavaScript
        js_cap = registry.resolve("javascript")
        assert js_cap.lsp_server == "typescript-language-server"
        assert js_cap.skill_bundle == "javascript-node"
        assert "extract_to_function" in js_cap.refactor_actions

        # Frontend
        frontend_cap = registry.resolve("frontend")
        assert frontend_cap.lsp_server == "typescript-language-server"
        assert frontend_cap.skill_bundle == "frontend-tsx"
        assert "extract_to_component" in frontend_cap.refactor_actions
        assert "fix_a11y_violation" in frontend_cap.refactor_actions
