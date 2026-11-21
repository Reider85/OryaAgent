"""Auto-format hook for Go files using gofmt (B-30).

This hook automatically formats Go files after write/edit operations
using gofmt. It's non-blocking and errors are converted to ToolMessage
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


def auto_format_gofmt(file_path: str | Path, **kwargs: Any) -> dict[str, Any]:
    """Auto-format Go file using gofmt.

    This hook runs gofmt on Go files after write/edit operations.
    It's non-blocking and errors are converted to ToolMessage warnings.

    Args:
        file_path: Path to the Go file to format
        **kwargs: Additional arguments (ignored)

    Returns:
        Dictionary with format results and warnings

    Raises:
        ToolException: If file validation fails or binary is not found
    """
    emit_span(
        span_type="hook.auto_format",
        name="auto_format_gofmt",
        attributes={"file_path": str(file_path)},
    )

    # Validate file path
    try:
        validated_path = validate_path(file_path)
    except Exception as e:
        raise ToolException(f"Invalid file path: {e}")

    # Check if file is a Go file
    if not validated_path.suffix.lower() == ".go":
        logger.debug(f"Skipping auto-format for non-Go file: {validated_path}")
        return {
            "success": False,
            "warning": f"File {validated_path} is not a Go file (.go), skipping auto-format",
        }

    # Check if gofmt is available
    if not shutil.which("gofmt"):
        logger.warning("gofmt not found in PATH")
        return {
            "success": False,
            "warning": "gofmt not found in PATH, skipping auto-format",
        }

    # Record metrics
    metrics = get_metric_collector()
    metrics.increment_counter(
        "orya_language_hook_executed_total", {"language": "go", "hook": "auto-format"}
    )

    try:
        # Run gofmt
        cmd = ["gofmt", "-w", str(validated_path)]

        logger.info(f"Running auto-format on {validated_path}")
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)

        if result.returncode == 0:
            logger.info(f"Successfully formatted {validated_path}")
            return {
                "success": True,
                "message": f"File {validated_path} has been auto-formatted using gofmt",
                "file_path": str(validated_path),
            }
        else:
            logger.warning(f"gofmt failed for {validated_path}: {result.stderr}")
            return {
                "success": False,
                "warning": f"Auto-format failed: {result.stderr}",
                "file_path": str(validated_path),
            }

    except subprocess.TimeoutExpired:
        logger.warning(f"Auto-format timeout for {validated_path}")
        return {
            "success": False,
            "warning": "Auto-format timed out after 30 seconds",
            "file_path": str(validated_path),
        }
    except Exception as e:
        logger.error(f"Auto-format error for {validated_path}: {e}")
        return {
            "success": False,
            "warning": f"Auto-format failed: {str(e)}",
            "file_path": str(validated_path),
        }


def is_go_file(file_path: str | Path) -> bool:
    """Check if file is a Go file.

    Args:
        file_path: Path to check

    Returns:
        True if file is a Go file, False otherwise
    """
    return Path(file_path).suffix.lower() == ".go"


def get_gofmt_version() -> str | None:
    """Get the version of gofmt.

    Returns:
        Version string if available, None otherwise
    """
    try:
        result = subprocess.run(
            ["gofmt", "-version"], capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return None
