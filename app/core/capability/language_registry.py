"""LanguageCapability dataclass and LanguageCapabilityRegistry for B-30."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from app.core.observability.spans import emit_span

logger = logging.getLogger(__name__)


class LanguageCapability(BaseModel):
    """Language-specific programming capability configuration.

    Contains all information needed to provide comprehensive programming
    support for a specific language including LSP configuration,
    build/test/lint/format commands, skill-bundles, and hooks.
    """

    language: str = Field(
        ..., description="Language identifier (java, rust, go, javascript, frontend)"
    )
    lsp_server: str = Field(
        ...,
        description="LSP server identifier (jdtls, rust-analyzer, gopls, typescript-language-server)",
    )
    file_extensions: list[str] = Field(
        ..., description="Supported file extensions for this language"
    )
    build_cmd: str = Field(..., description="Build command for this language")
    test_cmd: str = Field(..., description="Test command for this language")
    lint_cmd: str = Field(..., description="Lint command for this language")
    format_cmd: str = Field(..., description="Format command for this language")
    skill_bundle: str = Field(..., description="Skill bundle name for this language")
    hooks: list[str] = Field(..., description="List of hook names for this language")
    init_options: dict[str, Any] = Field(
        default_factory=dict, description="LSP server initialization options"
    )
    refactor_actions: list[str] = Field(
        default_factory=list, description="Available refactor actions"
    )
    description: str = Field(
        "", description="Human-readable description of the language capability"
    )

    def get_build_cmd_with_settings(self) -> str:
        """Get build command with settings override."""
        from app.core.config import get_settings

        settings = get_settings()

        # Override with settings if available
        build_cmd_key = f"ORYA_{self.language.upper()}_BUILD_CMD"
        if hasattr(settings, build_cmd_key):
            return getattr(settings, build_cmd_key)
        return self.build_cmd

    def get_test_cmd_with_settings(self) -> str:
        """Get test command with settings override."""
        from app.core.config import get_settings

        settings = get_settings()

        # Override with settings if available
        test_cmd_key = f"ORYA_{self.language.upper()}_TEST_CMD"
        if hasattr(settings, test_cmd_key):
            return getattr(settings, test_cmd_key)
        return self.test_cmd

    def get_lint_cmd_with_settings(self) -> str:
        """Get lint command with settings override."""
        from app.core.config import get_settings

        settings = get_settings()

        # Override with settings if available
        lint_cmd_key = f"ORYA_{self.language.upper()}_LINT_CMD"
        if hasattr(settings, lint_cmd_key):
            return getattr(settings, lint_cmd_key)
        return self.lint_cmd

    def get_format_cmd_with_settings(self) -> str:
        """Get format command with settings override."""
        from app.core.config import get_settings

        settings = get_settings()

        # Override with settings if available
        format_cmd_key = f"ORYA_{self.language.upper()}_FORMAT_CMD"
        if hasattr(settings, format_cmd_key):
            return getattr(settings, format_cmd_key)
        return self.format_cmd


class LanguageCapabilityRegistry:
    """Registry for language-specific programming capabilities.

    Provides language detection, capability resolution, and management
    of language-specific configurations for B-30 multi-language programming.
    """

    def __init__(self):
        """Initialize the LanguageCapabilityRegistry."""
        self.capabilities: dict[str, LanguageCapability] = {}
        self.extension_map: dict[str, str] = {}
        self._initialize_capabilities()

    def _initialize_capabilities(self) -> None:
        """Initialize language capabilities based on B-30 specification."""

        # Java capability
        java_capability = LanguageCapability(
            language="java",
            lsp_server="jdtls",
            file_extensions=[".java"],
            build_cmd="mvn compile",
            test_cmd="mvn test",
            lint_cmd="checkstyle",
            format_cmd="google-java-format",
            skill_bundle="java-maven",
            hooks=["auto-format-google-java-format", "auto-lint-checkstyle"],
            init_options={
                "settings": {
                    "java": {
                        "configuration": {"runtimes": []},
                        "import": {
                            "maven": {"enabled": True},
                            "gradle": {"enabled": True},
                        },
                    }
                },
                "initializationOptions": {"workspaceFolders": [], "bundles": []},
            },
            refactor_actions=[
                "extract_method",
                "convert_to_record",
                "generate_hashCode_equals",
                "add_missing_interface_methods",
            ],
            description="Java development with Maven/Gradle, jdtls LSP, and Google Java Format",
        )

        # Rust capability
        rust_capability = LanguageCapability(
            language="rust",
            lsp_server="rust-analyzer",
            file_extensions=[".rs"],
            build_cmd="cargo build",
            test_cmd="cargo test",
            lint_cmd="cargo clippy",
            format_cmd="rustfmt",
            skill_bundle="rust-cargo",
            hooks=["auto-format-rustfmt", "auto-lint-clippy"],
            init_options={
                "initializationOptions": {
                    "cargo": {
                        "loadOutDirsFromCheck": True,
                        "procMacro": {"enable": True},
                    },
                    "checkOnSave": {"command": "clippy"},
                    "diagnostics": {"enable": True},
                }
            },
            refactor_actions=[
                "extract_function",
                "convert_to_async",
                "generate_impl_block",
                "fix_clippy_lint",
            ],
            description="Rust development with Cargo, rust-analyzer LSP, and rustfmt",
        )

        # Go capability
        go_capability = LanguageCapability(
            language="go",
            lsp_server="gopls",
            file_extensions=[".go"],
            build_cmd="go build ./...",
            test_cmd="go test ./...",
            lint_cmd="go vet",
            format_cmd="gofmt -w",
            skill_bundle="go-mod",
            hooks=["auto-format-gofmt", "auto-lint-govet"],
            init_options={
                "initializationOptions": {
                    "build": {
                        "staticcheck": True,
                        "buildFlags": [],
                        "go": {"buildTags": ""},
                    },
                    "ui": {"diagnostic": {"staticcheck": True}},
                }
            },
            refactor_actions=[
                "extract_function",
                "convert_to_interface",
                "implement_missing_methods",
                "fix_struct_tag",
            ],
            description="Go development with modules, gopls LSP, and gofmt",
        )

        # JavaScript capability
        js_capability = LanguageCapability(
            language="javascript",
            lsp_server="typescript-language-server",
            file_extensions=[".js", ".mjs", ".cjs"],
            build_cmd="npm run build",
            test_cmd="npm test",
            lint_cmd="eslint",
            format_cmd="prettier --write",
            skill_bundle="javascript-node",
            hooks=["auto-format-prettier", "auto-lint-eslint"],
            init_options={
                "initializationOptions": {
                    "tsserver": {
                        "preferences": {
                            "includePackageJsonAutomaticImports": True,
                            "importModuleSpecifierPreference": "relative",
                        }
                    },
                    "javascript": {"implicitProjectConfig": {"allowJs": True}},
                    "typescript": {
                        "preferences": {"jsxAttributeCompletionStyle": "auto"}
                    },
                }
            },
            refactor_actions=[
                "extract_to_function",
                "convert_to_arrow_function",
                "add_missing_return_type",
                "fix_eslint_rule",
            ],
            description="JavaScript development with Node.js, TypeScript Language Server, and Prettier",
        )

        # Frontend capability
        frontend_capability = LanguageCapability(
            language="frontend",
            lsp_server="typescript-language-server",
            file_extensions=[".tsx", ".jsx", ".css", ".html"],
            build_cmd="npm run build",
            test_cmd="npm test",
            lint_cmd="eslint",
            format_cmd="prettier --write",
            skill_bundle="frontend-tsx",
            hooks=[
                "auto-format-prettier",
                "auto-lint-eslint",
                "accessibility-hint-axe",
            ],
            init_options={
                "initializationOptions": {
                    "tsserver": {
                        "preferences": {
                            "includePackageJsonAutomaticImports": True,
                            "importModuleSpecifierPreference": "relative",
                        }
                    },
                    "javascript": {"implicitProjectConfig": {"allowJs": True}},
                    "typescript": {
                        "jsx": "react",
                        "preferences": {
                            "jsxAttributeCompletionStyle": "auto",
                            "suggest": {"enabled": True},
                        },
                    },
                }
            },
            refactor_actions=[
                "extract_to_component",
                "convert_to_arrow_function",
                "add_missing_return_type",
                "fix_eslint_rule",
                "fix_a11y_violation",
            ],
            description="Frontend development with React/TSX, TypeScript Language Server, Prettier, and accessibility hints",
        )

        # Register capabilities
        self.capabilities = {
            "java": java_capability,
            "rust": rust_capability,
            "go": go_capability,
            "javascript": js_capability,
            "frontend": frontend_capability,
        }

        # Build extension map for quick lookup
        for capability in self.capabilities.values():
            for ext in capability.file_extensions:
                self.extension_map[ext] = capability.language

    def resolve(self, language: str) -> LanguageCapability:
        """Resolve language capability by language name.

        Args:
            language: Language identifier (java, rust, go, javascript, frontend)

        Returns:
            LanguageCapability for the requested language

        Raises:
            ValueError: If language is not supported
        """
        emit_span(
            span_type="language.resolve",
            name="language.resolve",
            attributes={"language": language},
        )

        if language not in self.capabilities:
            supported = list(self.capabilities.keys())
            raise ValueError(
                f"Unsupported language: {language}. Supported: {supported}"
            )

        return self.capabilities[language]

    def detect(self, file_path: str | Path) -> str:
        """Detect language from file path.

        Args:
            file_path: Path to the file to analyze

        Returns:
            Detected language identifier

        Raises:
            ValueError: If language cannot be detected from file extension
        """
        file_path = Path(file_path)
        extension = file_path.suffix.lower()

        if extension in self.extension_map:
            return self.extension_map[extension]

        # Try to detect from known patterns
        if extension == ".py":
            return "python"
        elif extension in [".ts", ".tsx"]:
            return "typescript"
        elif extension == ".lua":
            return "lua"

        raise ValueError(f"Cannot detect language from file extension: {extension}")

    def is_supported(self, language: str) -> bool:
        """Check if language is supported.

        Args:
            language: Language identifier to check

        Returns:
            True if language is supported, False otherwise
        """
        return language in self.capabilities

    def list_supported(self) -> list[str]:
        """List all supported languages.

        Returns:
            List of supported language identifiers
        """
        return list(self.capabilities.keys())

    def get_capability_for_file(self, file_path: str | Path) -> LanguageCapability:
        """Get language capability for a specific file.

        Args:
            file_path: Path to the file to analyze

        Returns:
            LanguageCapability for the file's language
        """
        language = self.detect(file_path)
        return self.resolve(language)


# Global registry instance
_registry: LanguageCapabilityRegistry | None = None


def get_language_capability_registry() -> LanguageCapabilityRegistry:
    """Get the global LanguageCapabilityRegistry instance."""
    global _registry
    if _registry is None:
        _registry = LanguageCapabilityRegistry()
    return _registry


def reset_language_capability_registry() -> None:
    """Reset the global LanguageCapabilityRegistry instance."""
    global _registry
    _registry = None
