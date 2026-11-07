"""Tool: oriahs_index - incremental code indexing through MCP (B-03).

Contract: oriahs_index(path, recursive=False) -> str

Behaviour:
* Incremental file/directory indexing through OriaHS MCP server
* Git-aware filtering for directory indexing (skip ignored files)
* Path validation and security checks
* Caching for repeated indexing operations
* Error handling for MCP server unavailability
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import time
from pathlib import Path
from typing import Annotated, Any

from langchain_core.tools import InjectedToolArg, ToolException, tool
from langgraph.prebuilt import ToolRuntime

from app.core.cache import build_cache_key, from_cache_result, get_cache
from app.core.mcp_config import get_mcp_config
from app.core.observability.metrics import (
    MCPMetricsContext,
    increment_mcp_connection_error,
    set_mcp_server_health,
)
from app.core.observability.spans import emit_mcp_span
from app.core.security import (
    check_injection,
    injection_warning,
    sanitize_untrusted,
    session_id_from_config,
)
from app.mcp.client import get_mcp_client
from app.tools._validators import validate_path

logger = logging.getLogger(__name__)


def _get_git_ignored_files(directory: Path) -> set[str]:
    """Get files ignored by git in the given directory."""
    ignored_files = set()

    try:
        # Change to directory and run git status
        original_cwd = os.getcwd()
        os.chdir(directory)

        # Get ignored files from git status
        result = subprocess.run(
            ["git", "status", "--porcelain", "--ignored"],
            capture_output=True,
            text=True,
            timeout=10,
        )

        if result.returncode == 0:
            for line in result.stdout.strip().split("\n"):
                if line and "!!" in line:
                    # Extract file path from git status output
                    file_path = line.split("!!", 1)[1].strip()
                    ignored_files.add(file_path)

    except (
        subprocess.TimeoutExpired,
        subprocess.CalledProcessError,
        FileNotFoundError,
    ) as e:
        logger.warning(f"Failed to get git ignored files: {e}")
    except Exception as e:
        logger.error(f"Unexpected error getting git ignored files: {e}")
    finally:
        # Restore original working directory
        if "original_cwd" in locals():
            os.chdir(original_cwd)

    return ignored_files


def _should_index_file(file_path: Path, ignored_files: set[str]) -> bool:
    """Check if a file should be indexed (not ignored, valid extension)."""
    # Convert to relative path from git perspective
    try:
        relative_path = str(file_path.relative_to(file_path.parent))
    except ValueError:
        relative_path = str(file_path)

    # Check if file is ignored by git
    if relative_path in ignored_files:
        return False

    # Check file extension (basic validation)
    valid_extensions = {
        ".py",
        ".js",
        ".ts",
        ".tsx",
        ".jsx",
        ".java",
        ".go",
        ".rs",
        ".cpp",
        ".c",
        ".h",
        ".hpp",
        ".cs",
        ".php",
        ".rb",
        ".swift",
        ".kt",
        ".scala",
        ".m",
        ".sh",
        ".bash",
        ".zsh",
        ".fish",
        ".ps1",
        ".bat",
        ".cmd",
        ".sql",
        ".html",
        ".css",
        ".scss",
        ".less",
        ".json",
        ".xml",
        ".yaml",
        ".yml",
        ".md",
        ".txt",
        ".toml",
        ".ini",
        ".cfg",
        ".conf",
        ".dockerfile",
        ".makefile",
        ".cmake",
        ".gradle",
        ".pom.xml",
        ".requirements.txt",
        ".package.json",
        ".pyproject.toml",
        ".cargo.toml",
        ".go.mod",
    }

    return file_path.suffix.lower() in valid_extensions


def _format_indexing_results(results: list[dict[str, Any]]) -> str:
    """Format OriaHS indexing results for LLM consumption."""
    if not results:
        return "No files were indexed."

    formatted = []
    for i, result in enumerate(results, 1):
        status = result.get("status", "unknown")
        file_path = result.get("path", "unknown")
        message = result.get("message", "")

        status_icon = "✅" if status == "success" else "❌"
        formatted.append(
            f"{status_icon} [{i}] {file_path}\n"
            f"   Status: {status}\n"
            f"   Message: {message}\n"
        )
    return "\n".join(formatted)


@tool
async def oriahs_index(
    path: Annotated[str, "Path to file or directory to index"],
    recursive: Annotated[bool, "Index directories recursively"] = False,
    runtime: Annotated[ToolRuntime | None, InjectedToolArg] = None,
) -> str:
    """Incrementally index a file or directory through OriaHS MCP server.

    For files: indexes the single file.
    For directories: indexes all files with git-aware filtering.

    Args:
        path: File or directory path to index
        recursive: If True and path is directory, index all subdirectories
        runtime: Tool runtime for caching (injected)

    Returns:
        Status message with indexing results

    Raises:
        ToolException: For invalid paths, MCP errors, or indexing failures
    """
    mcp_config = get_mcp_config()

    # Validate inputs
    if not path.strip():
        raise ToolException("Path cannot be empty")

    # Validate path
    try:
        validated_path = validate_path(path)
    except ToolException as e:
        raise ToolException(f"Invalid path: {e}")

    # Check if path exists
    if not validated_path.exists():
        raise ToolException(f"Path does not exist: {path}")

    # Build cache key
    cache_key = build_cache_key(
        "oriahs_index",
        {"path": str(validated_path), "recursive": recursive},
        str(validated_path),  # File-based caching
    )

    # Check cache first
    cache = get_cache()
    cached_result = await cache.get(cache_key)
    if cached_result is not None:
        result = from_cache_result(
            cached_result,
            name="oriahs_index",
            tool_call_id=getattr(runtime, "tool_call_id", None),
        )
        emit_mcp_span(
            tool_name="index_file" if validated_path.is_file() else "index_directory",
            server_url=mcp_config.server_url,
            status="success",
            source="cache",
        )
        return result

    # Use metrics context for automatic metric collection
    with MCPMetricsContext(
        "index_file" if validated_path.is_file() else "index_directory",
        mcp_config.server_url,
    ) as mcp_context:
        try:
            # Get MCP client
            mcp_client = get_mcp_client()

            # Check MCP server health first
            health_check_start = time.time()
            is_healthy = await mcp_client.health_check()
            health_check_duration = (time.time() - health_check_start) * 1000

            set_mcp_server_health(mcp_config.server_url, is_healthy)

            if not is_healthy:
                increment_mcp_connection_error(
                    mcp_config.server_url, "health_check_failed"
                )
                raise ToolException("OriaHS MCP server is not available")

            # Execute indexing based on path type
            if validated_path.is_file():
                # Single file indexing
                results = await _index_file(mcp_client, validated_path)
            else:
                # Directory indexing with git-aware filtering
                results = await _index_directory(mcp_client, validated_path, recursive)

            # Format results
            formatted_results = _format_indexing_results(results)

            # Apply security checks
            injection_check = check_injection(formatted_results, source="oriahs_index")
            has_injection = False
            if injection_check and injection_warning in injection_check:
                has_injection = True
                # Add injection warning to results
                formatted_results += f"\n{injection_check}"

            # Apply untrusted content framing
            sanitized_results = sanitize_untrusted(
                formatted_results,
                source="oriahs_index",
                session_id=session_id_from_config(getattr(runtime, "config", None)),
            )

            # Cache results
            await cache.set(cache_key, sanitized_results, ttl=3600)  # 1 hour TTL

            # Update metrics with final status
            mcp_context.status = "success"
            mcp_context.duration_ms = health_check_duration

            # Emit spans
            emit_mcp_span(
                tool_name="index_file"
                if validated_path.is_file()
                else "index_directory",
                server_url=mcp_config.server_url,
                status="success",
                has_injection=has_injection,
                duration_ms=health_check_duration,
            )

            return sanitized_results

        except Exception as e:
            # Log the error for debugging
            logger.error(f"Indexing failed: {e}")

            # Update metrics with error
            mcp_context.status = "error"

            # Fall back to helpful message if MCP fails
            if "not available" in str(e).lower() or "connection" in str(e).lower():
                increment_mcp_connection_error(
                    mcp_config.server_url, "server_unavailable"
                )
                raise ToolException(
                    f"Indexing unavailable: {str(e)}. "
                    "Please check OriaHS server availability."
                )
            else:
                increment_mcp_connection_error(mcp_config.server_url, "operation_error")
                raise ToolException(f"Indexing failed: {str(e)}")


async def _index_file(mcp_client, file_path: Path) -> list[dict[str, Any]]:
    """Index a single file through MCP."""
    try:
        results = await mcp_client.call_tool(
            "index_file",
            {"file_path": str(file_path)},
        )

        # Parse results
        parsed_results = []
        for result in results:
            try:
                if isinstance(result, dict):
                    parsed_results.append(result)
                elif isinstance(result, str):
                    # Parse JSON string result
                    parsed = json.loads(result)
                    if isinstance(parsed, dict):
                        parsed_results.append(parsed)
            except (json.JSONDecodeError, TypeError):
                logger.warning(f"Failed to parse indexing result: {result}")
                continue

        return parsed_results

    except Exception as e:
        logger.error(f"Failed to index file {file_path}: {e}")
        return [{"path": str(file_path), "status": "error", "message": str(e)}]


async def _index_directory(
    mcp_client, directory_path: Path, recursive: bool
) -> list[dict[str, Any]]:
    """Index a directory with git-aware filtering through MCP."""
    try:
        # Get git ignored files
        ignored_files = _get_git_ignored_files(directory_path)

        # Collect files to index
        files_to_index = []
        if recursive:
            # Recursive directory traversal
            for file_path in directory_path.rglob("*"):
                if file_path.is_file() and _should_index_file(file_path, ignored_files):
                    files_to_index.append(file_path)
        else:
            # Only immediate files
            for file_path in directory_path.iterdir():
                if file_path.is_file() and _should_index_file(file_path, ignored_files):
                    files_to_index.append(file_path)

        # Batch index files
        results = []
        for file_path in files_to_index:
            try:
                file_result = await _index_file(mcp_client, file_path)
                results.extend(file_result)
            except Exception as e:
                logger.error(f"Failed to index {file_path}: {e}")
                results.append(
                    {"path": str(file_path), "status": "error", "message": str(e)}
                )

        return results

    except Exception as e:
        logger.error(f"Failed to index directory {directory_path}: {e}")
        return [{"path": str(directory_path), "status": "error", "message": str(e)}]
