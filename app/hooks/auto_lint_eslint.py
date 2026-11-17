"""Auto-lint hook for JavaScript/TypeScript/Frontend files using ESLint (B-30).

This hook automatically lints JavaScript, TypeScript, and Frontend files
after write/edit operations using ESLint. It's non-blocking and errors
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


def auto_lint_eslint(
    file_path: str | Path,
    **kwargs: Any
) -> Dict[str, Any]:
    """Auto-lint JavaScript/TypeScript/Frontend file using ESLint.
    
    This hook runs ESLint on JavaScript, TypeScript, and Frontend files
    after write/edit operations. It's non-blocking and errors are converted
    to ToolMessage warnings.
    
    Args:
        file_path: Path to the file to lint
        **kwargs: Additional arguments (ignored)
        
    Returns:
        Dictionary with lint results and warnings
        
    Raises:
        ToolException: If file validation fails or binary is not found
    """
    emit_span(
        span_type="hook.auto_lint",
        name="auto_lint_eslint",
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
        logger.debug(f"Skipping auto-lint for unsupported file type: {validated_path}")
        return {
            "success": False,
            "warning": f"File {validated_path} is not a supported file type for ESLint, skipping auto-lint"
        }
    
    # Check if eslint is available
    if not shutil.which("eslint"):
        logger.warning("eslint not found in PATH")
        return {
            "success": False,
            "warning": "eslint not found in PATH, skipping auto-lint"
        }
    
    # Find ESLint configuration file
    config_file = _find_eslint_config(validated_path)
    if not config_file:
        logger.warning("No ESLint configuration file found")
        return {
            "success": False,
            "warning": "No ESLint configuration file found, skipping auto-lint"
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
    
    metrics.increment_counter("orya_language_hook_executed_total", {"language": language, "hook": "auto-lint"})
    
    try:
        # Run eslint
        cmd = ["eslint", "--format=json", str(validated_path)]
        
        # Add config file if found
        if config_file:
            cmd.extend(["--config", str(config_file)])
        
        # Change to eslint config directory
        cwd = config_file.parent if config_file else validated_path.parent
        
        logger.info(f"Running auto-lint on {validated_path}")
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=60,
            cwd=cwd
        )
        
        if result.returncode == 0:
            logger.info(f"Successfully linted {validated_path} - no ESLint issues found")
            return {
                "success": True,
                "message": f"File {validated_path} passed ESLint validation (no issues found)",
                "file_path": str(validated_path),
                "issues": []
            }
        else:
            # Parse ESLint JSON output
            issues = _parse_eslint_output(result.stdout, validated_path)
            
            logger.info(f"Found {len(issues)} issues in {validated_path}")
            return {
                "success": False,
                "warning": f"Found {len(issues)} ESLint issues",
                "file_path": str(validated_path),
                "issues": issues,
                "details": result.stderr
            }
            
    except subprocess.TimeoutExpired:
        logger.warning(f"Auto-lint timeout for {validated_path}")
        return {
            "success": False,
            "warning": "Auto-lint timed out after 60 seconds",
            "file_path": str(validated_path)
        }
    except Exception as e:
        logger.error(f"Auto-lint error for {validated_path}: {e}")
        return {
            "success": False,
            "warning": f"Auto-lint failed: {str(e)}",
            "file_path": str(validated_path)
        }


def _find_eslint_config(file_path: Path) -> Optional[Path]:
    """Find ESLint configuration file.
    
    Args:
        file_path: Path to the file
        
    Returns:
        Path to ESLint config file if found, None otherwise
    """
    # Look for common ESLint config files in the same directory and parent directories
    config_names = [
        ".eslintrc.js",
        ".eslintrc.cjs",
        ".eslintrc.mjs",
        ".eslintrc.json",
        ".eslintrc.yaml",
        ".eslintrc.yml",
        "eslint.config.js",
        "eslint.config.cjs",
        "eslint.config.mjs",
        "eslint.config.json"
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


def _parse_eslint_output(output: str, file_path: Path) -> List[Dict[str, Any]]:
    """Parse ESLint JSON output to extract issues.
    
    Args:
        output: ESLint JSON output string
        file_path: Original file path for context
        
    Returns:
        List of issue dictionaries
    """
    import json
    
    issues = []
    
    try:
        # Parse JSON output
        eslint_result = json.loads(output)
        
        # Extract issues for our file
        for file_result in eslint_result:
            if file_result["filePath"] == str(file_path):
                for message in file_result["messages"]:
                    issue = {
                        "file": message["line"],
                        "line": message["line"],
                        "column": message["column"],
                        "message": message["message"],
                        "rule": message["ruleId"],
                        "severity": message["severity"],
                        "source": message["source"]
                    }
                    issues.append(issue)
                break
        
    except json.JSONDecodeError:
        # If JSON parsing fails, try to parse plain text output
        lines = output.strip().split('\n')
        for line in lines:
            line = line.strip()
            if not line:
                continue
                
            # Look for issues that mention our file
            if file_path.name in line:
                try:
                    # Basic parsing of line number and message
                    parts = line.split(":")
                    if len(parts) >= 3:
                        issue = {
                            "file": parts[0].strip(),
                            "line": int(parts[1].strip()),
                            "column": int(parts[2].strip()) if len(parts) > 2 and parts[2].strip().isdigit() else 0,
                            "message": parts[3].strip(),
                            "rule": "eslint"
                        }
                        issues.append(issue)
                except (ValueError, IndexError):
                    # Skip lines that can't be parsed
                    continue
    
    return issues


def is_supported_eslint_file(file_path: str | Path) -> bool:
    """Check if file is a supported ESLint file.
    
    Args:
        file_path: Path to check
        
    Returns:
        True if file is a supported ESLint file, False otherwise
    """
    supported_extensions = [".js", ".mjs", ".cjs", ".jsx", ".ts", ".tsx", ".css", ".html"]
    return Path(file_path).suffix.lower() in supported_extensions


def get_eslint_version() -> Optional[str]:
    """Get the version of ESLint.
    
    Returns:
        Version string if available, None otherwise
    """
    try:
        result = subprocess.run(
            ["eslint", "--version"],
            capture_output=True,
            text=True,
            timeout=10
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return None