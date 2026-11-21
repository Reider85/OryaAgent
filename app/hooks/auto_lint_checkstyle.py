"""Auto-lint hook for Java files using Checkstyle (B-30).

This hook automatically lints Java files after write/edit operations
using Checkstyle. It's non-blocking and errors are converted to ToolMessage
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


def auto_lint_checkstyle(file_path: str | Path, **kwargs: Any) -> dict[str, Any]:
    """Auto-lint Java file using Checkstyle.

    This hook runs Checkstyle on Java files after write/edit operations.
    It's non-blocking and errors are converted to ToolMessage warnings.

    Args:
        file_path: Path to the Java file to lint
        **kwargs: Additional arguments (ignored)

    Returns:
        Dictionary with lint results and warnings

    Raises:
        ToolException: If file validation fails or binary is not found
    """
    emit_span(
        span_type="hook.auto_lint",
        name="auto_lint_checkstyle",
        attributes={"file_path": str(file_path)},
    )

    # Validate file path
    try:
        validated_path = validate_path(file_path)
    except Exception as e:
        raise ToolException(f"Invalid file path: {e}")

    # Check if file is a Java file
    if not validated_path.suffix.lower() == ".java":
        logger.debug(f"Skipping auto-lint for non-Java file: {validated_path}")
        return {
            "success": False,
            "warning": f"File {validated_path} is not a Java file (.java), skipping auto-lint",
        }

    # Check if checkstyle is available
    if not shutil.which("checkstyle"):
        logger.warning("checkstyle not found in PATH")
        return {
            "success": False,
            "warning": "checkstyle not found in PATH, skipping auto-lint",
        }

    # Find checkstyle configuration file
    config_file = _find_checkstyle_config(validated_path)
    if not config_file:
        logger.warning("No checkstyle configuration file found")
        return {
            "success": False,
            "warning": "No checkstyle configuration file found, skipping auto-lint",
        }

    # Record metrics
    metrics = get_metric_collector()
    metrics.increment_counter(
        "orya_language_hook_executed_total", {"language": "java", "hook": "auto-lint"}
    )

    try:
        # Run checkstyle
        cmd = ["checkstyle", "-c", str(config_file), str(validated_path)]

        logger.info(f"Running auto-lint on {validated_path}")
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)

        if result.returncode == 0:
            logger.info(f"Successfully linted {validated_path} - no violations found")
            return {
                "success": True,
                "message": f"File {validated_path} passed Checkstyle validation (no violations found)",
                "file_path": str(validated_path),
                "violations": [],
            }
        else:
            # Parse checkstyle output for violations
            violations = _parse_checkstyle_output(result.stderr)

            logger.info(f"Found {len(violations)} violations in {validated_path}")
            return {
                "success": False,
                "warning": f"Found {len(violations)} Checkstyle violations",
                "file_path": str(validated_path),
                "violations": violations,
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


def _find_checkstyle_config(file_path: Path) -> Path | None:
    """Find Checkstyle configuration file.

    Args:
        file_path: Path to the Java file

    Returns:
        Path to checkstyle configuration file if found, None otherwise
    """
    # Look for common checkstyle config files in the same directory and parent directories
    config_names = [
        "checkstyle.xml",
        "checkstyle-config.xml",
        "config/checkstyle.xml",
        ".checkstyle",
        "google_checks.xml",
        "sun_checks.xml",
    ]

    # Check current directory
    for config_name in config_names:
        config_path = file_path.parent / config_name
        if config_path.exists():
            return config_path

    # Check parent directories (up to 5 levels)
    current_dir = file_path.parent
    for _ in range(5):
        parent_dir = current_dir.parent
        if parent_dir == current_dir:  # Reached root
            break

        for config_name in config_names:
            config_path = parent_dir / config_name
            if config_path.exists():
                return config_path

        current_dir = parent_dir

    return None


def _parse_checkstyle_output(output: str) -> list[dict[str, Any]]:
    """Parse Checkstyle output to extract violations.

    Args:
        output: Checkstyle output string

    Returns:
        List of violation dictionaries
    """
    violations = []

    # Parse common checkstyle output format
    lines = output.strip().split("\n")

    for line in lines:
        line = line.strip()
        if not line:
            continue

        # Example format: [ERROR] /path/to/file.java:123:45: Message [RuleName]
        if "[ERROR]" in line or "[WARN]" in line:
            parts = line.split(":")
            if len(parts) >= 3:
                try:
                    violation = {
                        "file": parts[0]
                        .replace("[ERROR]", "")
                        .replace("[WARN]", "")
                        .strip(),
                        "line": int(parts[1].strip()),
                        "column": int(parts[2].strip()),
                        "message": parts[3].strip(),
                        "rule": parts[4].strip() if len(parts) > 4 else "unknown",
                    }
                    violations.append(violation)
                except (ValueError, IndexError):
                    # Skip lines that can't be parsed
                    continue

    return violations


def is_java_file(file_path: str | Path) -> bool:
    """Check if file is a Java file.

    Args:
        file_path: Path to check

    Returns:
        True if file is a Java file, False otherwise
    """
    return Path(file_path).suffix.lower() == ".java"


def get_checkstyle_version() -> str | None:
    """Get the version of Checkstyle.

    Returns:
        Version string if available, None otherwise
    """
    try:
        result = subprocess.run(
            ["checkstyle", "-v"], capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return None
