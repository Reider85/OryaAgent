"""Auto-lint hook for Rust files using Clippy (B-30).

This hook automatically lints Rust files after write/edit operations
using Clippy. It's non-blocking and errors are converted to ToolMessage
warnings.
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


def auto_lint_clippy(
    file_path: str | Path,
    **kwargs: Any
) -> Dict[str, Any]:
    """Auto-lint Rust file using Clippy.
    
    This hook runs Clippy on Rust files after write/edit operations.
    It's non-blocking and errors are converted to ToolMessage warnings.
    
    Args:
        file_path: Path to the Rust file to lint
        **kwargs: Additional arguments (ignored)
        
    Returns:
        Dictionary with lint results and warnings
        
    Raises:
        ToolException: If file validation fails or binary is not found
    """
    emit_span(
        span_type="hook.auto_lint",
        name="auto_lint_clippy",
        attributes={"file_path": str(file_path)}
    )
    
    # Validate file path
    try:
        validated_path = validate_path(file_path)
    except Exception as e:
        raise ToolException(f"Invalid file path: {e}")
    
    # Check if file is a Rust file
    if not validated_path.suffix.lower() == ".rs":
        logger.debug(f"Skipping auto-lint for non-Rust file: {validated_path}")
        return {
            "success": False,
            "warning": f"File {validated_path} is not a Rust file (.rs), skipping auto-lint"
        }
    
    # Check if cargo is available
    if not shutil.which("cargo"):
        logger.warning("cargo not found in PATH")
        return {
            "success": False,
            "warning": "cargo not found in PATH, skipping auto-lint"
        }
    
    # Find Cargo.toml to determine workspace
    cargo_toml = _find_cargo_toml(validated_path)
    if not cargo_toml:
        logger.warning("No Cargo.toml found")
        return {
            "success": False,
            "warning": "No Cargo.toml found, skipping auto-lint"
        }
    
    # Record metrics
    metrics = get_metric_collector()
    metrics.increment_counter("orya_language_hook_executed_total", {"language": "rust", "hook": "auto-lint"})
    
    try:
        # Run clippy
        cmd = ["cargo", "clippy", "--message-format=short", str(validated_path)]
        
        # Change to cargo directory
        cwd = cargo_toml.parent
        
        logger.info(f"Running auto-lint on {validated_path}")
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=120,
            cwd=cwd
        )
        
        if result.returncode == 0:
            logger.info(f"Successfully linted {validated_path} - no clippy warnings found")
            return {
                "success": True,
                "message": f"File {validated_path} passed Clippy validation (no warnings found)",
                "file_path": str(validated_path),
                "warnings": []
            }
        else:
            # Parse clippy output for warnings
            warnings = _parse_clippy_output(result.stderr, validated_path)
            
            logger.info(f"Found {len(warnings)} warnings in {validated_path}")
            return {
                "success": False,
                "warning": f"Found {len(warnings)} Clippy warnings",
                "file_path": str(validated_path),
                "warnings": warnings,
                "details": result.stderr
            }
            
    except subprocess.TimeoutExpired:
        logger.warning(f"Auto-lint timeout for {validated_path}")
        return {
            "success": False,
            "warning": "Auto-lint timed out after 120 seconds",
            "file_path": str(validated_path)
        }
    except Exception as e:
        logger.error(f"Auto-lint error for {validated_path}: {e}")
        return {
            "success": False,
            "warning": f"Auto-lint failed: {str(e)}",
            "file_path": str(validated_path)
        }


def _find_cargo_toml(file_path: Path) -> Optional[Path]:
    """Find Cargo.toml file.
    
    Args:
        file_path: Path to the Rust file
        
    Returns:
        Path to Cargo.toml if found, None otherwise
    """
    # Check current directory
    cargo_toml = file_path.parent / "Cargo.toml"
    if cargo_toml.exists():
        return cargo_toml
    
    # Check parent directories (up to 5 levels)
    current_dir = file_path.parent
    for _ in range(5):
        parent_dir = current_dir.parent
        if parent_dir == current_dir:  # Reached root
            break
            
        cargo_toml = parent_dir / "Cargo.toml"
        if cargo_toml.exists():
            return cargo_toml
        
        current_dir = parent_dir
    
    return None


def _parse_clippy_output(output: str, file_path: Path) -> List[Dict[str, Any]]:
    """Parse Clippy output to extract warnings.
    
    Args:
        output: Clippy output string
        file_path: Original file path for context
        
    Returns:
        List of warning dictionaries
    """
    warnings = []
    
    # Parse clippy output format
    lines = output.strip().split('\n')
    
    for line in lines:
        line = line.strip()
        if not line:
            continue
            
        # Look for clippy warnings that mention our file
        if file_path.name in line and ("warning:" in line or "error:" in line):
            try:
                # Extract line number and message
                parts = line.split(":")
                if len(parts) >= 3:
                    warning = {
                        "file": parts[0].strip(),
                        "line": int(parts[1].strip()),
                        "column": int(parts[2].strip()) if len(parts) > 2 and parts[2].strip().isdigit() else 0,
                        "message": parts[3].strip(),
                        "rule": "clippy"
                    }
                    warnings.append(warning)
            except (ValueError, IndexError):
                # Skip lines that can't be parsed
                continue
    
    return warnings


def is_rust_file(file_path: str | Path) -> bool:
    """Check if file is a Rust file.
    
    Args:
        file_path: Path to check
        
    Returns:
        True if file is a Rust file, False otherwise
    """
    return Path(file_path).suffix.lower() == ".rs"


def get_clippy_version() -> Optional[str]:
    """Get the version of Clippy.
    
    Returns:
        Version string if available, None otherwise
    """
    try:
        result = subprocess.run(
            ["cargo", "clippy", "--version"],
            capture_output=True,
            text=True,
            timeout=10
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return None