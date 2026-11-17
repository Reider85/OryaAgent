"""Per-language LSP configurations for B-30 multi-language programming.

This module provides language-specific LSP server configurations including
initialization options, file extensions, build/test/lint/format commands,
 and other language-specific settings.
"""

from __future__ import annotations

from typing import Any, Dict, List

from pydantic import BaseModel, Field


class LanguageLSPConfig(BaseModel):
    """Per-language LSP server configuration for B-30."""
    
    language: str = Field(..., description="Language identifier")
    server_name: str = Field(..., description="LSP server name")
    command: List[str] = Field(..., description="Command to start LSP server")
    init_options: Dict[str, Any] = Field(default_factory=dict, description="LSP initialization options")
    file_extensions: List[str] = Field(..., description="Supported file extensions")
    workspace_args: List[str] = Field(default_factory=list, description="Workspace-specific arguments")
    env_vars: Dict[str, str] = Field(default_factory=dict, description="Environment variables")
    timeout: int = Field(default=30, description="Server startup timeout in seconds")
    max_restarts: int = Field(default=3, description="Maximum restart attempts")
    restart_delay: int = Field(default=5, description="Delay between restarts in seconds")


# Language-specific LSP configurations for B-30
LANGUAGE_LSP_CONFIGS: Dict[str, LanguageLSPConfig] = {
    "java": LanguageLSPConfig(
        language="java",
        server_name="jdtls",
        command=["jdt-langserver"],
        init_options={
            "settings": {
                "java": {
                    "configuration": {
                        "runtimes": []
                    },
                    "import": {
                        "maven": {"enabled": True},
                        "gradle": {"enabled": True}
                    }
                }
            },
            "initializationOptions": {
                "workspaceFolders": [],
                "bundles": []
            }
        },
        file_extensions=[".java"],
        workspace_args=["-data", "{workspace}/.jdtls"],
        env_vars={
            "JAVA_HOME": "/usr/lib/jvm/java-17-openjdk"  # Will be auto-detected
        },
        timeout=60,  # Java projects can be large
        max_restarts=3,
        restart_delay=10
    ),
    
    "rust": LanguageLSPConfig(
        language="rust",
        server_name="rust-analyzer",
        command=["rust-analyzer"],
        init_options={
            "initializationOptions": {
                "cargo": {
                    "loadOutDirsFromCheck": True,
                    "procMacro": {"enable": True}
                },
                "checkOnSave": {
                    "command": "clippy"
                },
                "diagnostics": {
                    "enable": True
                }
            }
        },
        file_extensions=[".rs"],
        workspace_args=["--stdio"],
        env_vars={
            "RUSTUP_TOOLCHAIN": "stable"
        },
        timeout=30,
        max_restarts=3,
        restart_delay=5
    ),
    
    "go": LanguageLSPConfig(
        language="go",
        server_name="gopls",
        command=["gopls"],
        init_options={
            "initializationOptions": {
                "build": {
                    "staticcheck": True,
                    "buildFlags": [],
                    "go": {
                        "buildTags": ""
                    }
                },
                "ui": {
                    "diagnostic": {
                        "staticcheck": True
                    }
                }
            }
        },
        file_extensions=[".go"],
        workspace_args=["stdio"],
        env_vars={
            "GOBIN": "{workspace}/bin"
        },
        timeout=20,
        max_restarts=3,
        restart_delay=3
    ),
    
    "javascript": LanguageLSPConfig(
        language="javascript",
        server_name="typescript-language-server",
        command=["typescript-language-server", "--stdio"],
        init_options={
            "initializationOptions": {
                "tsserver": {
                    "preferences": {
                        "includePackageJsonAutomaticImports": True,
                        "importModuleSpecifierPreference": "relative"
                    }
                },
                "javascript": {
                    "implicitProjectConfig": {
                        "allowJs": True
                    }
                },
                "typescript": {
                    "preferences": {
                        "jsxAttributeCompletionStyle": "auto"
                    }
                }
            }
        },
        file_extensions=[".js", ".mjs", ".cjs"],
        workspace_args=["--stdio"],
        env_vars={
            "NODE_ENV": "development"
        },
        timeout=20,
        max_restarts=3,
        restart_delay=3
    ),
    
    "frontend": LanguageLSPConfig(
        language="frontend",
        server_name="typescript-language-server",
        command=["typescript-language-server", "--stdio"],
        init_options={
            "initializationOptions": {
                "tsserver": {
                    "preferences": {
                        "includePackageJsonAutomaticImports": True,
                        "importModuleSpecifierPreference": "relative"
                    }
                },
                "javascript": {
                    "implicitProjectConfig": {
                        "allowJs": True
                    }
                },
                "typescript": {
                    "jsx": "react",
                    "preferences": {
                        "jsxAttributeCompletionStyle": "auto",
                        "suggest": {"enabled": True}
                    }
                }
            }
        },
        file_extensions=[".tsx", ".jsx", ".css", ".html"],
        workspace_args=["--stdio"],
        env_vars={
            "NODE_ENV": "development"
        },
        timeout=20,
        max_restarts=3,
        restart_delay=3
    ),
    
    "python": LanguageLSPConfig(
        language="python",
        server_name="pyright-langserver",
        command=["pyright-langserver", "--stdio"],
        init_options={
            "settings": {
                "python": {
                    "analysis": {
                        "typeCheckingMode": "standard",
                        "useLibraryCodeForTypes": True
                    }
                }
            }
        },
        file_extensions=[".py"],
        workspace_args=["--stdio"],
        env_vars={
            "PYTHONPATH": "{workspace}"
        },
        timeout=15,
        max_restarts=3,
        restart_delay=3
    ),
    
    "typescript": LanguageLSPConfig(
        language="typescript",
        server_name="typescript-language-server",
        command=["typescript-language-server", "--stdio"],
        init_options={
            "initializationOptions": {
                "tsserver": {
                    "preferences": {
                        "includePackageJsonAutomaticImports": True,
                        "importModuleSpecifierPreference": "relative"
                    }
                },
                "typescript": {
                    "preferences": {
                        "jsxAttributeCompletionStyle": "auto"
                    }
                }
            }
        },
        file_extensions=[".ts"],
        workspace_args=["--stdio"],
        env_vars={
            "NODE_ENV": "development"
        },
        timeout=20,
        max_restarts=3,
        restart_delay=3
    ),
    
    "lua": LanguageLSPConfig(
        language="lua",
        server_name="lua-language-server",
        command=["lua-language-server"],
        init_options={
            "Lua.workspace": {
                "library": [
                    "{workspace}/node_modules/@types/lua/5.1",
                    "/usr/share/lua/5.1"
                ]
            },
            "Lua.runtime": {
                "version": "Lua 5.1"
            }
        },
        file_extensions=[".lua"],
        workspace_args=["--stdio"],
        env_vars={
            "LUA_PATH": "{workspace}/?.lua;{workspace}/?/init.lua"
        },
        timeout=15,
        max_restarts=3,
        restart_delay=3
    )
}


def get_language_lsp_config(language: str) -> LanguageLSPConfig:
    """Get LSP configuration for a specific language.
    
    Args:
        language: Language identifier
        
    Returns:
        LanguageLSPConfig for the requested language
        
    Raises:
        ValueError: If language is not supported
    """
    if language not in LANGUAGE_LSP_CONFIGS:
        supported = list(LANGUAGE_LSP_CONFIGS.keys())
        raise ValueError(f"Unsupported language: {language}. Supported: {supported}")
    
    return LANGUAGE_LSP_CONFIGS[language]


def get_supported_languages() -> List[str]:
    """Get list of supported languages for LSP configuration.
    
    Returns:
        List of supported language identifiers
    """
    return list(LANGUAGE_LSP_CONFIGS.keys())


def detect_language_from_file(file_path: str) -> str:
    """Detect language from file path.
    
    Args:
        file_path: Path to the file
        
    Returns:
        Detected language identifier
        
    Raises:
        ValueError: If language cannot be detected from file extension
    """
    from pathlib import Path
    
    path = Path(file_path)
    extension = path.suffix.lower()
    
    for language, config in LANGUAGE_LSP_CONFIGS.items():
        if extension in config.file_extensions:
            return language
    
    raise ValueError(f"Cannot detect language from file extension: {extension}")


def get_file_extensions_for_language(language: str) -> List[str]:
    """Get file extensions for a specific language.
    
    Args:
        language: Language identifier
        
    Returns:
        List of file extensions supported by the language
    """
    config = get_language_lsp_config(language)
    return config.file_extensions


def get_build_command_for_language(language: str) -> str:
    """Get build command for a specific language.
    
    Args:
        language: Language identifier
        
    Returns:
        Build command for the language
    """
    from app.core.config import get_settings
    
    config = get_language_lsp_config(language)
    settings = get_settings()
    
    # Override with settings if available
    build_cmd_key = f"ORYA_{language.upper()}_BUILD_CMD"
    if hasattr(settings, build_cmd_key):
        return getattr(settings, build_cmd_key)
    
    # Default build commands based on language
    build_commands = {
        "java": "mvn compile",
        "rust": "cargo build",
        "go": "go build ./...",
        "javascript": "npm run build",
        "frontend": "npm run build",
        "python": "python -m py_compile",
        "typescript": "tsc",
        "lua": "luac"
    }
    
    return build_commands.get(language, "")


def get_test_command_for_language(language: str) -> str:
    """Get test command for a specific language.
    
    Args:
        language: Language identifier
        
    Returns:
        Test command for the language
    """
    from app.core.config import get_settings
    
    config = get_language_lsp_config(language)
    settings = get_settings()
    
    # Override with settings if available
    test_cmd_key = f"ORYA_{language.upper()}_TEST_CMD"
    if hasattr(settings, test_cmd_key):
        return getattr(settings, test_cmd_key)
    
    # Default test commands based on language
    test_commands = {
        "java": "mvn test",
        "rust": "cargo test",
        "go": "go test ./...",
        "javascript": "npm test",
        "frontend": "npm test",
        "python": "pytest",
        "typescript": "npm test",
        "lua": "busted"
    }
    
    return test_commands.get(language, "")


def get_lint_command_for_language(language: str) -> str:
    """Get lint command for a specific language.
    
    Args:
        language: Language identifier
        
    Returns:
        Lint command for the language
    """
    from app.core.config import get_settings
    
    config = get_language_lsp_config(language)
    settings = get_settings()
    
    # Override with settings if available
    lint_cmd_key = f"ORYA_{language.upper()}_LINT_CMD"
    if hasattr(settings, lint_cmd_key):
        return getattr(settings, lint_cmd_key)
    
    # Default lint commands based on language
    lint_commands = {
        "java": "checkstyle",
        "rust": "cargo clippy",
        "go": "go vet",
        "javascript": "eslint",
        "frontend": "eslint",
        "python": "flake8",
        "typescript": "eslint",
        "lua": "luacheck"
    }
    
    return lint_commands.get(language, "")


def get_format_command_for_language(language: str) -> str:
    """Get format command for a specific language.
    
    Args:
        language: Language identifier
        
    Returns:
        Format command for the language
    """
    from app.core.config import get_settings
    
    config = get_language_lsp_config(language)
    settings = get_settings()
    
    # Override with settings if available
    format_cmd_key = f"ORYA_{language.upper()}_FORMAT_CMD"
    if hasattr(settings, format_cmd_key):
        return getattr(settings, format_cmd_key)
    
    # Default format commands based on language
    format_commands = {
        "java": "google-java-format -i",
        "rust": "rustfmt",
        "go": "gofmt -w",
        "javascript": "prettier --write",
        "frontend": "prettier --write",
        "python": "black",
        "typescript": "prettier --write",
        "lua": "luafmt"
    }
    
    return format_commands.get(language, "")