"""Auto-format hook for JavaScript/TypeScript/Frontend files using Prettier (B-30).

This hook automatically formats JavaScript, TypeScript, and Frontend files
after write/edit operations using Prettier. It's non-blocking and errors
are converted to ToolMessage warnings.
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


def auto_format_prettier(
    file_path: str | Path,
    **kwargs: Any
) -> Dict[str, Any]:
    """Auto-format JavaScript/TypeScript/Frontend file using Prettier.
    
    This hook runs Prettier on JavaScript, TypeScript, and Frontend files
    after write/edit operations. It's non-blocking and errors are converted
    to ToolMessage warnings.
    
    Args:
        file_path: Path to the file to format
        **kwargs: Additional arguments (ignored)
        
    Returns:
        Dictionary with format results and warnings
        
    Raises:
        ToolException: If file validation fails or binary is not found
    """
    emit_span(
        span_type="hook.auto_format",
        name="auto_format_prettier",
        attributes={"file_path": str(file_path)}
    )
    
    # Validate file path
    try:
        validated_path = validate_path(file_path)
    except Exception as e:
        raise ToolException(f"Invalid file path: {e}")
    
    # Check if file is a supported file type
    supported_extensions = [".js", ".mjs", ".cjs", ".jsx", ".ts", ".tsx", ".css", ".html"]
    if validated_path.suffix.lower() not in supported_extensions:
        logger.debug(f"Skipping auto-format for unsupported file type: {validated_path}")
        return {
            "success": False,
            "warning": f"File {validated_path} is not a supported file type for Prettier, skipping auto-format"
        }
    
    # Check if prettier is available
    if not shutil.which("prettier"):
        logger.warning("prettier not found in PATH")
        return {
            "success": False,
            "warning": "prettier not found in PATH, skipping auto-format"
        }
    
    # Record metrics
    metrics = get_metric_collector()
    
    # Determine language for metrics
    if validated_path.suffix.lower() in [".js", ".mjs", ".cjs"]:
        language = "javascript"
    elif validated_path.suffix.lower() in [".jsx"]:
        language = "frontend"
    elif validated_path.suffix.lower() in [".ts"]:
        language = "typescript"
    elif validated_path.suffix.lower() in [".tsx"]:
        language = "frontend"
    elif validated_path.suffix.lower() in [".css"]:
        language = "frontend"
    elif validated_path.suffix.lower() in [".html"]:
        language = "frontend"
    else:
        language = "unknown"
    
    metrics.increment_counter("orya_language_hook_executed_total", {"language": language, "hook": "auto-format"})
    
    try:
        # Run prettier
        cmd = ["prettier", "--write", str(validated_path)]
        
        # Add config file if it exists
        config_files = [
            "prettier.config.js",
            "prettier.config.cjs",
            "prettier.config.mjs",
            ".prettierrc",
            ".prettierrc.json",
            ".prettierrc.yml",
            ".prettierrc.yaml"
        ]
        
        for config_file in config_files:
            config_path = validated_path.parent / config_file
            if config_path.exists():
                cmd.extend(["--config", str(config_path)])
                break
        
        logger.info(f"Running auto-format on {validated_path}")
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=60
        )
        
        if result.returncode == 0:
            logger.info(f"Successfully formatted {validated_path}")
            return {
                "success": True,
                "message": f"File {validated_path} has been auto-formatted using Prettier",
                "file_path": str(validated_path)
            }
        else:
            logger.warning(f"Prettier failed for {validated_path}: {result.stderr}")
            return {
                "success": False,
                "warning": f"Auto-format failed: {result.stderr}",
                "file_path": str(validated_path)
            }
            
    except subprocess.TimeoutExpired:
        logger.warning(f"Auto-format timeout for {validated_path}")
        return {
            "success": False,
            "warning": "Auto-format timed out after 60 seconds",
            "file_path": str(validated_path)
        }
    except Exception as e:
        logger.error(f"Auto-format error for {validated_path}: {e}")
        return {
            "success": False,
            "warning": f"Auto-format failed: {str(e)}",
            "file_path": str(validated_path)
        }


def is_supported_prettier_file(file_path: str | Path) -> bool:
    """Check if file is a supported Prettier file.
    
    Args:
        file_path: Path to check
        
    Returns:
        True if file is a supported Prettier file, False otherwise
    """
    supported_extensions = [".js", ".mjs", ".cjs", ".jsx", ".ts", ".tsx", ".css", ".html"]
    return Path(file_path).suffix.lower() in supported_extensions


def get_prettier_version() -> Optional[str]:
    """Get the version of Prettier.
    
    Returns:
        Version string if available, None otherwise
    """
    try:
        result = subprocess.run(
            ["prettier", "--version"],
            capture_output=True,
            text=True,
            timeout=10
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return None