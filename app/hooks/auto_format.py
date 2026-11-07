from __future__ import annotations

"""Auto-format hooks for various programming languages (B-05).

These hooks automatically format code after write/edit operations.
"""

import logging
import subprocess
from pathlib import Path

from app.core.hooks import HookContext, HookResult, PostToolHook, get_hook_registry
from app.tools._validators import validate_path

logger = logging.getLogger(__name__)


class AutoFormatHook(PostToolHook):
    """Base class for auto-format hooks."""

    @property
    def name(self) -> str:
        return "auto_format"

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def description(self) -> str:
        return f"Auto-format hook for {self.language}"

    @property
    def language(self) -> str:
        """Return the language this hook handles."""
        raise NotImplementedError

    @property
    def file_extensions(self) -> list[str]:
        """Return the file extensions this hook handles."""
        raise NotImplementedError

    @property
    def format_command(self) -> str:
        """Return the format command."""
        raise NotImplementedError

    async def execute(self, context: HookContext, result: HookResult) -> HookResult:
        """Execute auto-formatting after write/edit operations."""
        if not result.success:
            return result

        # Check if the tool was a write or edit operation
        if context.tool_name not in ["write", "edit"]:
            return result

        # Get the file path from tool arguments
        path_arg = context.tool_args.get("path", "")
        if not path_arg:
            return result

        try:
            # Validate and resolve the path
            resolved_path = validate_path(path_arg)

            # Check if file has the right extension
            if not any(
                str(resolved_path).endswith(ext) for ext in self.file_extensions
            ):
                return result

            # Check if the file exists and is not empty
            if not resolved_path.exists() or resolved_path.stat().st_size == 0:
                return result

            # Execute the format command
            await self._format_file(resolved_path)

            logger.info(f"Auto-formatted {self.language} file: {resolved_path}")

            # Update the result message to indicate formatting occurred
            return HookResult(
                success=True,
                data=result.data,
                message=f"{result.message} (auto-formatted)",
            )

        except Exception as e:
            logger.warning(f"Auto-format failed for {resolved_path}: {e}")
            # Return the original result but add a warning
            return HookResult(
                success=True,
                data=result.data,
                message=f"{result.message} (auto-format warning: {str(e)})",
            )

    async def _format_file(self, file_path: Path) -> None:
        """Format a specific file."""
        cmd = self.format_command.format(file_path=str(file_path))

        # Run the format command
        process = await subprocess.run(
            cmd,
            shell=True,
            check=True,
            capture_output=True,
            text=True,
        )

        if process.stdout:
            logger.debug(f"Format output: {process.stdout}")

        if process.stderr:
            logger.warning(f"Format warnings: {process.stderr}")


class GoogleJavaFormatHook(AutoFormatHook):
    """Auto-format hook for Java using google-java-format."""

    @property
    def language(self) -> str:
        return "java"

    @property
    def file_extensions(self) -> list[str]:
        return [".java"]

    @property
    def format_command(self) -> str:
        return "google-java-format -i {file_path}"


class RustfmtHook(AutoFormatHook):
    """Auto-format hook for Rust using rustfmt."""

    @property
    def language(self) -> str:
        return "rust"

    @property
    def file_extensions(self) -> list[str]:
        return [".rs"]

    @property
    def format_command(self) -> str:
        return "rustfmt --edition 2021 {file_path}"


class GofmtHook(AutoFormatHook):
    """Auto-format hook for Go using gofmt."""

    @property
    def language(self) -> str:
        return "go"

    @property
    def file_extensions(self) -> list[str]:
        return [".go"]

    @property
    def format_command(self) -> str:
        return "gofmt -w {file_path}"


class PrettierHook(AutoFormatHook):
    """Auto-format hook for JavaScript/TypeScript/CSS/HTML using Prettier."""

    @property
    def language(self) -> str:
        return "javascript"

    @property
    def file_extensions(self) -> list[str]:
        return [".js", ".mjs", ".cjs", ".jsx", ".ts", ".tsx", ".css", ".html"]

    @property
    def format_command(self) -> str:
        return "prettier --write {file_path}"


# Register the auto-format hooks
def register_auto_format_hooks() -> None:
    """Register all auto-format hooks."""
    registry = get_hook_registry()

    # Register hooks for write and edit operations
    registry.register_post_hook("write", GoogleJavaFormatHook())
    registry.register_post_hook("edit", GoogleJavaFormatHook())

    registry.register_post_hook("write", RustfmtHook())
    registry.register_post_hook("edit", RustfmtHook())

    registry.register_post_hook("write", GofmtHook())
    registry.register_post_hook("edit", GofmtHook())

    registry.register_post_hook("write", PrettierHook())
    registry.register_post_hook("edit", PrettierHook())

    logger.info("Auto-format hooks registered")


# Register auto-format hooks automatically when the module is imported
register_auto_format_hooks()


def clear_auto_format_hooks() -> None:
    """Clear auto-format hooks."""
    registry = get_hook_registry()

    # Unregister specific hooks
    registry.unregister_hooks("write")
    registry.unregister_hooks("edit")

    logger.info("Auto-format hooks cleared")
