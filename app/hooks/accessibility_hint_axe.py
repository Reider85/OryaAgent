"""Accessibility hint hook for frontend files using axe-core (B-30).

This hook provides accessibility hints for frontend files after write/edit
operations using axe-core. It's non-blocking and provides suggestion-only
warnings (not failures).
"""

import json
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


def accessibility_hint_axe(
    file_path: str | Path,
    **kwargs: Any
) -> Dict[str, Any]:
    """Provide accessibility hints for frontend file using axe-core.
    
    This hook runs axe-core on frontend files after write/edit operations.
    It's non-blocking and provides suggestion-only warnings (not failures).
    
    Args:
        file_path: Path to the frontend file to check
        **kwargs: Additional arguments (ignored)
        
    Returns:
        Dictionary with accessibility hints and warnings
        
    Raises:
        ToolException: If file validation fails or axe-core is not available
    """
    emit_span(
        span_type="hook.accessibility_hint",
        name="accessibility_hint_axe",
        attributes={"file_path": str(file_path)}
    )
    
    # Validate file path
    try:
        validated_path = validate_path(file_path)
    except Exception as e:
        raise ToolException(f"Invalid file path: {e}")
    
    # Check if file is a supported frontend file type
    supported_extensions = [".tsx", ".jsx", ".html"]
    if validated_path.suffix.lower() not in supported_extensions:
        logger.debug(f"Skipping accessibility check for unsupported file type: {validated_path}")
        return {
            "success": False,
            "warning": f"File {validated_path} is not a supported frontend file type for axe-core, skipping accessibility check"
        }
    
    # Check if Node.js is available (required for axe-core)
    if not shutil.which("node"):
        logger.warning("Node.js not found in PATH")
        return {
            "success": False,
            "warning": "Node.js not found in PATH, skipping accessibility check"
        }
    
    # Record metrics
    metrics = get_metric_collector()
    metrics.increment_counter("orya_language_hook_executed_total", {"language": "frontend", "hook": "accessibility-hint"})
    
    try:
        # Run axe-core check
        violations = _run_axe_core_check(validated_path)
        
        if violations:
            logger.info(f"Found {len(violations)} accessibility violations in {validated_path}")
            return {
                "success": False,
                "warning": f"Found {len(violations)} accessibility violations (suggestions only)",
                "file_path": str(validated_path),
                "violations": violations,
                "suggestion": "These accessibility issues are suggestions only and won't prevent the file from being processed"
            }
        else:
            logger.info(f"No accessibility violations found in {validated_path}")
            return {
                "success": True,
                "message": f"File {validated_path} passed accessibility check (no violations found)",
                "file_path": str(validated_path),
                "violations": []
            }
            
    except subprocess.TimeoutExpired:
        logger.warning(f"Accessibility check timeout for {validated_path}")
        return {
            "success": False,
            "warning": "Accessibility check timed out after 60 seconds",
            "file_path": str(validated_path)
        }
    except Exception as e:
        logger.error(f"Accessibility check error for {validated_path}: {e}")
        return {
            "success": False,
            "warning": f"Accessibility check failed: {str(e)}",
            "file_path": str(validated_path)
        }


def _run_axe_core_check(file_path: Path) -> List[Dict[str, Any]]:
    """Run axe-core check on a frontend file.
    
    Args:
        file_path: Path to the frontend file
        
    Returns:
        List of accessibility violation dictionaries
    """
    # Create a simple Node.js script to run axe-core
    script = f"""
const axe = require('axe-core');
const fs = require('fs');
const path = require('path');

// Read the file
const filePath = '{file_path}';
const html = fs.readFileSync(filePath, 'utf8');

// Run axe-core check
axe.run(html, {{ runOnly: {{ type: 'rule', values: ['wcag2a', 'wcag2aa', 'wcag21aa'] }} }}, (err, results) => {{
    if (err) {{
        console.error(JSON.stringify({{ error: err.message }}));
        process.exit(1);
    }}
    
    // Format results
    const violations = results.violations.map(violation => ({
        id: violation.id,
        impact: violation.impact,
        description: violation.description,
        help: violation.help,
        helpUrl: violation.helpUrl,
        tags: violation.tags,
        nodes: violation.nodes.map(node => ({
            html: node.html,
            target: node.target,
            failureSummary: node.failureSummary
        }))
    }));
    
    console.log(JSON.stringify({{ violations }}));
}});
"""
    
    # Write temporary script
    temp_script = Path("/tmp/axe_check.js")
    with open(temp_script, 'w') as f:
        f.write(script)
    
    try:
        # Run the script with Node.js
        cmd = ["node", str(temp_script)]
        
        logger.info(f"Running accessibility check on {file_path}")
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=60
        )
        
        if result.returncode == 0:
            # Parse the results
            output = json.loads(result.stdout)
            return output.get("violations", [])
        else:
            # Check for error in output
            try:
                error_output = json.loads(result.stdout)
                if "error" in error_output:
                    logger.error(f"axe-core error: {error_output['error']}")
            except json.JSONDecodeError:
                logger.error(f"axe-core failed: {result.stderr}")
            
            return []
            
    finally:
        # Clean up temporary script
        if temp_script.exists():
            temp_script.unlink()


def _format_axe_violation(violation: Dict[str, Any]) -> str:
    """Format an axe-core violation for display.
    
    Args:
        violation: Axe-core violation dictionary
        
    Returns:
        Formatted violation string
    """
    lines = [
        f"ID: {violation['id']}",
        f"Impact: {violation['impact'].upper()}",
        f"Description: {violation['description']}",
        f"Help: {violation['help']}",
        f"Tags: {', '.join(violation['tags'])}"
    ]
    
    if violation.get('nodes'):
        lines.append("Affected elements:")
        for node in violation['nodes']:
            lines.append(f"  - {node.get('target', 'unknown')}")
            if node.get('failureSummary'):
                lines.append(f"    {node['failureSummary']}")
    
    return "\n".join(lines)


def is_supported_frontend_file(file_path: str | Path) -> bool:
    """Check if file is a supported frontend file.
    
    Args:
        file_path: Path to check
        
    Returns:
        True if file is a supported frontend file, False otherwise
    """
    supported_extensions = [".tsx", ".jsx", ".html"]
    return Path(file_path).suffix.lower() in supported_extensions


def get_axe_core_version() -> Optional[str]:
    """Get the version of axe-core.
    
    Returns:
        Version string if available, None otherwise
    """
    try:
        result = subprocess.run(
            ["npm", "list", "axe-core"],
            capture_output=True,
            text=True,
            timeout=10
        )
        if result.returncode == 0:
            # Extract version from output
            # Format: axe-core@4.8.2
            line = result.stdout.strip()
            if "axe-core@" in line:
                version = line.split("axe-core@")[1].split()[0]
                return version
    except Exception:
        pass
    return None