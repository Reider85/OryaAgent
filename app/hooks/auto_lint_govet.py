"""Auto-lint hook for Go files using go vet (B-30).

This hook automatically lints Go files after write/edit operations
using go vet. It's non-blocking and errors are converted to ToolMessage
warnings.
"""

import logging
import shutil
import subprocess
from pathlib import Path
from typing import Any

from langchain_core.tools import ToolException

from app.core.observability.metrics import get_metric_collector
from app.core.observability.spans import emit_span
from app.tools._validators import validate_path

logger = logging.getLogger(__name__)


def auto_lint_govet(file_path: str | Path, **kwargs: Any) -> dict[str, Any]:
    """Auto-lint Go file using go vet.

    This hook runs go vet on Go files after write/edit operations.
    It's non-blocking and errors are converted to ToolMessage warnings.

    Args:
        file_path: Path to the Go file to lint
        **kwargs: Additional arguments (ignored)

    Returns:
        Dictionary with lint results and warnings

    Raises:
        ToolException: If file validation fails or binary is not found
    """
    emit_span(
        span_type="hook.auto_lint",
        name="auto_lint_govet",
        attributes={"file_path": str(file_path)},
    )

    # Validate file path
    try:
        validated_path = validate_path(file_path)
    except Exception as e:
        raise ToolException(f"Invalid file path: {e}")

    # Check if file is a Go file
    if not validated_path.suffix.lower() == ".go":
        logger.debug(f"Skipping auto-lint for non-Go file: {validated_path}")
        return {
            "success": False,
            "warning": f"File {validated_path} is not a Go file (.go), skipping auto-lint",
        }

    # Check if go is available
    if not shutil.which("go"):
        logger.warning("go not found in PATH")
        return {"success": False, "warning": "go not found in PATH, skipping auto-lint"}

    # Find go.mod to determine module
    go_mod = _find_go_mod(validated_path)
    if not go_mod:
        logger.warning("No go.mod found")
        return {"success": False, "warning": "No go.mod found, skipping auto-lint"}

    # Record metrics
    metrics = get_metric_collector()
    metrics.increment_counter(
        "orya_language_hook_executed_total", {"language": "go", "hook": "auto-lint"}
    )

    try:
        # Run go vet
        cmd = ["go", "vet", "./..."]

        # Change to go module directory
        cwd = go_mod.parent

        logger.info(f"Running auto-lint on {validated_path}")
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=60, cwd=cwd
        )

        if result.returncode == 0:
            logger.info(
                f"Successfully linted {validated_path} - no go vet issues found"
            )
            return {
                "success": True,
                "message": f"File {validated_path} passed go vet validation (no issues found)",
                "file_path": str(validated_path),
                "issues": [],
            }
        else:
            # Parse go vet output for issues
            issues = _parse_govet_output(result.stderr, validated_path)

            logger.info(f"Found {len(issues)} issues in {validated_path}")
            return {
                "success": False,
                "warning": f"Found {len(issues)} go vet issues",
                "file_path": str(validated_path),
                "issues": issues,
                "details": result.stderr,
            }

    except subprocess.TimeoutExpired:
        logger.warning(f"Auto-lint timeout for {validated_path}")
        return {
            "success": False,
            "warning": "Auto-lint timed out after 60 seconds",
            "file_path": str(validated_path),
        }
    except Exception as e:
        logger.error(f"Auto-lint error for {validated_path}: {e}")
        return {
            "success": False,
            "warning": f"Auto-lint failed: {str(e)}",
            "file_path": str(validated_path),
        }


def _find_go_mod(file_path: Path) -> Path | None:
    """Find go.mod file.

    Args:
        file_path: Path to the Go file

    Returns:
        Path to go.mod if found, None otherwise
    """
    # Check current directory
    go_mod = file_path.parent / "go.mod"
    if go_mod.exists():
        return go_mod

    # Check parent directories (up to 5 levels)
    current_dir = file_path.parent
    for _ in range(5):
        parent_dir = current_dir.parent
        if parent_dir == current_dir:  # Reached root
            break

        go_mod = parent_dir / "go.mod"
        if go_mod.exists():
            return go_mod

        current_dir = parent_dir

    return None


def _parse_govet_output(output: str, file_path: Path) -> list[dict[str, Any]]:
    """Parse go vet output to extract issues.

    Args:
        output: go vet output string
        file_path: Original file path for context

    Returns:
        List of issue dictionaries
    """
    issues = []

    # Parse go vet output format
    lines = output.strip().split("\n")

    for line in lines:
        line = line.strip()
        if not line:
            continue

        # Look for go vet issues that mention our file
        if file_path.name in line:
            try:
                # Extract line number and message
                # Format: file.go:123:45: message
                parts = line.split(":")
                if len(parts) >= 3:
                    issue = {
                        "file": parts[0].strip(),
                        "line": int(parts[1].strip()),
                        "column": int(parts[2].strip())
                        if len(parts) > 2 and parts[2].strip().isdigit()
                        else 0,
                        "message": parts[3].strip(),
                        "rule": "govet",
                    }
                    issues.append(issue)
            except (ValueError, IndexError):
                # Skip lines that can't be parsed
                continue

    return issues


def is_go_file(file_path: str | Path) -> bool:
    """Check if file is a Go file.

    Args:
        file_path: Path to check

    Returns:
        True if file is a Go file, False otherwise
    """
    return Path(file_path).suffix.lower() == ".go"


def get_govet_version() -> str | None:
    """Get the version of go vet.

    Returns:
        Version string if available, None otherwise
    """
    try:
        result = subprocess.run(
            ["go", "version"], capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return None
