"""Auto-format hook for Java files using Google Java Format (B-30).

This hook automatically formats Java files after write/edit operations
using Google Java Format. It's non-blocking and errors are converted
to ToolMessage warnings.
"""

import logging
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, Optional

from app.core.tools._validators import validate_path
from app.core.observability.metrics import get_metric_collector
from app.core.observability.spans import emit_span
from app.core.tools import ToolException

logger = logging.getLogger(__name__)


def auto_format_google_java_format(
    file_path: str | Path,
    **kwargs: Any
) -> Dict[str, Any]:
    """Auto-format Java file using Google Java Format.
    
    This hook runs Google Java Format on Java files after write/edit operations.
    It's non-blocking and errors are converted to ToolMessage warnings.
    
    Args:
        file_path: Path to the Java file to format
        **kwargs: Additional arguments (ignored)
        
    Returns:
        Dictionary with format results and warnings
        
    Raises:
        ToolException: If file validation fails or binary is not found
    """
    emit_span(
        span_type="hook.auto_format",
        name="auto_format_google_java_format",
        attributes={"file_path": str(file_path)}
    )
    
    # Validate file path
    try:
        validated_path = validate_path(file_path)
    except Exception as e:
        raise ToolException(f"Invalid file path: {e}")
    
    # Check if file is a Java file
    if not validated_path.suffix.lower() == ".java":
        logger.debug(f"Skipping auto-format for non-Java file: {validated_path}")
        return {
            "success": False,
            "warning": f"File {validated_path} is not a Java file (.java), skipping auto-format"
        }
    
    # Check if google-java-format is available
    if not shutil.which("google-java-format"):
        logger.warning("google-java-format not found in PATH")
        return {
            "success": False,
            "warning": "google-java-format not found in PATH, skipping auto-format"
        }
    
    # Record metrics
    metrics = get_metric_collector()
    metrics.increment_counter("orya_language_hook_executed_total", {"language": "java", "hook": "auto-format"})
    
    try:
        # Run google-java-format
        cmd = ["google-java-format", "-i", str(validated_path)]
        
        logger.info(f"Running auto-format on {validated_path}")
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30
        )
        
        if result.returncode == 0:
            logger.info(f"Successfully formatted {validated_path}")
            return {
                "success": True,
                "message": f"File {validated_path} has been auto-formatted using Google Java Format",
                "file_path": str(validated_path)
            }
        else:
            logger.warning(f"google-java-format failed for {validated_path}: {result.stderr}")
            return {
                "success": False,
                "warning": f"Auto-format failed: {result.stderr}",
                "file_path": str(validated_path)
            }
            
    except subprocess.TimeoutExpired:
        logger.warning(f"Auto-format timeout for {validated_path}")
        return {
            "success": False,
            "warning": "Auto-format timed out after 30 seconds",
            "file_path": str(validated_path)
        }
    except Exception as e:
        logger.error(f"Auto-format error for {validated_path}: {e}")
        return {
            "success": False,
            "warning": f"Auto-format failed: {str(e)}",
            "file_path": str(validated_path)
        }


def is_java_file(file_path: str | Path) -> bool:
    """Check if file is a Java file.
    
    Args:
        file_path: Path to check
        
    Returns:
        True if file is a Java file, False otherwise
    """
    return Path(file_path).suffix.lower() == ".java"


def get_google_java_format_version() -> Optional[str]:
    """Get the version of google-java-format.
    
    Returns:
        Version string if available, None otherwise
    """
    try:
        result = subprocess.run(
            ["google-java-format", "--version"],
            capture_output=True,
            text=True,
            timeout=10
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return None