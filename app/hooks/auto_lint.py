"""Auto-lint hooks for various programming languages (B-05).

These hooks automatically run linters after write/edit operations.
"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path
from typing import Any

from app.core.hooks import HookContext, HookResult, PostToolHook, get_hook_registry
from app.tools._validators import validate_path

logger = logging.getLogger(__name__)


class AutoLintHook(PostToolHook):
    """Base class for auto-lint hooks."""

    @property
    def name(self) -> str:
        return "auto_lint"

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def description(self) -> str:
        return f"Auto-lint hook for {self.language}"

    @property
    def language(self) -> str:
        """Return the language this hook handles."""
        raise NotImplementedError

    @property
    def file_extensions(self) -> list[str]:
        """Return the file extensions this hook handles."""
        raise NotImplementedError

    @property
    def lint_command(self) -> str:
        """Return the lint command."""
        raise NotImplementedError

    async def execute(self, context: HookContext, result: HookResult) -> HookResult:
        """Execute auto-linting after write/edit operations."""
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

            # Execute the lint command
            lint_result = await self._lint_file(resolved_path)

            if lint_result.has_issues:
                logger.warning(
                    f"Lint issues found in {resolved_path}: {lint_result.issues}"
                )
                return HookResult(
                    success=True,
                    data=result.data,
                    message=f"{result.message}\nLint issues: {lint_result.issues}",
                )

            logger.info(
                f"Auto-linted {self.language} file: {resolved_path} (no issues)"
            )

            # Return the original result
            return result

        except Exception as e:
            logger.warning(f"Auto-lint failed for {resolved_path}: {e}")
            # Return the original result but add a warning
            return HookResult(
                success=True,
                data=result.data,
                message=f"{result.message}\nAuto-lint warning: {str(e)}",
            )

    async def _lint_file(self, file_path: Path) -> "LintResult":
        """Lint a specific file and return the result."""
        cmd = self.lint_command.format(file_path=str(file_path))

        # Run the lint command
        process = await subprocess.run(
            cmd,
            shell=True,
            check=False,  # Don't raise exception on lint failures
            capture_output=True,
            text=True,
        )

        issues = []
        if process.returncode != 0:
            # Parse the output to extract issues
            if process.stderr:
                issues.extend(self._parse_lint_output(process.stderr))
            if process.stdout:
                issues.extend(self._parse_lint_output(process.stdout))

        return LintResult(has_issues=len(issues) > 0, issues=issues)

    def _parse_lint_output(self, output: str) -> list[str]:
        """Parse lint output to extract issues."""
        # This is a simple implementation - in practice, you'd want more sophisticated parsing
        # for specific linters
        issues = []
        for line in output.split("\n"):
            line = line.strip()
            if line and not line.startswith("[") and ":" in line:
                issues.append(line)
        return issues


class LintResult:
    """Result of a lint operation."""

    def __init__(self, has_issues: bool, issues: list[str]):
        self.has_issues = has_issues
        self.issues = issues


class CheckstyleHook(AutoLintHook):
    """Auto-lint hook for Java using Checkstyle."""

    @property
    def language(self) -> str:
        return "java"

    @property
    def file_extensions(self) -> list[str]:
        return [".java"]

    @property
    def lint_command(self) -> str:
        # Use a standard checkstyle configuration
        return "checkstyle -c /google_checks.xml {file_path}"


class ClippyHook(AutoLintHook):
    """Auto-lint hook for Rust using Clippy."""

    @property
    def language(self) -> str:
        return "rust"

    @property
    def file_extensions(self) -> list[str]:
        return [".rs"]

    @property
    def lint_command(self) -> str:
        return "cargo clippy --message-format=short {file_path}"


class GovetHook(AutoLintHook):
    """Auto-lint hook for Go using go vet."""

    @property
    def language(self) -> str:
        return "go"

    @property
    def file_extensions(self) -> list[str]:
        return [".go"]

    @property
    def lint_command(self) -> str:
        return "go vet {file_path}"


class EslintHook(AutoLintHook):
    """Auto-lint hook for JavaScript/TypeScript using ESLint."""

    @property
    def language(self) -> str:
        return "javascript"

    @property
    def file_extensions(self) -> list[str]:
        return [".js", ".mjs", ".cjs", ".jsx", ".ts", ".tsx"]

    @property
    def lint_command(self) -> str:
        return "eslint --format=compact {file_path}"


# Register the auto-lint hooks
def register_auto_lint_hooks() -> None:
    """Register all auto-lint hooks."""
    registry = get_hook_registry()

    # Register hooks for write and edit operations
    registry.register_post_hook("write", CheckstyleHook())
    registry.register_post_hook("edit", CheckstyleHook())

    registry.register_post_hook("write", ClippyHook())
    registry.register_post_hook("edit", ClippyHook())

    registry.register_post_hook("write", GovetHook())
    registry.register_post_hook("edit", GovetHook())

    registry.register_post_hook("write", EslintHook())
    registry.register_post_hook("edit", EslintHook())

    logger.info("Auto-lint hooks registered")


def clear_auto_lint_hooks() -> None:
    """Clear auto-lint hooks."""
    registry = get_hook_registry()

    # Unregister specific hooks
    registry.unregister_hooks("write")
    registry.unregister_hooks("edit")

    logger.info("Auto-lint hooks cleared")
