"""7 LSP tools for native code intelligence."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from app.core.observability.spans import emit_span
from app.core.lsp.bus import get_lsp_bus
from app.core.tools._validators import validate_path

logger = logging.getLogger(__name__)


class LSPToolException(Exception):
    """Exception for LSP tool errors."""
    
    def __init__(self, message: str, degraded: bool = False):
        super().__init__(message)
        self.degraded = degraded


@emit_span("lsp.hover")
async def lsp_hover(
    file_path: str,
    line: int,
    column: int,
    workspace: str = "."
) -> Dict[str, Any]:
    """Get hover information for a position in a file.
    
    Args:
        file_path: Path to the file
        line: Line number (0-based)
        column: Column number (0-based)
        workspace: Workspace directory
        
    Returns:
        Dictionary containing hover information with signature, type, and documentation
    """
    try:
        # Validate file path
        file_path = validate_path(file_path)
        workspace_path = validate_path(workspace)
        
        # Get LSP bus
        lsp_bus = get_lsp_bus()
        
        # Detect language
        language = lsp_bus.detect_language(file_path)
        if not language:
            raise LSPToolException(f"Unsupported file type: {file_path.suffix}")
        
        # Ensure server is running
        server = await lsp_bus.ensure_server(language, workspace_path)
        
        # Get hover information
        result = await server.hover(
            file_path=file_path,
            position={"line": line, "character": column}
        )
        
        return {
            "success": True,
            "language": language,
            "hover": result,
            "position": {"line": line, "column": column},
            "file_path": str(file_path),
        }
        
    except Exception as e:
        logger.error(f"Error in lsp_hover: {e}")
        raise LSPToolException(f"Hover failed: {str(e)}")


@emit_span("lsp.definition")
async def lsp_definition(
    file_path: str,
    line: int,
    column: int,
    workspace: str = "."
) -> Dict[str, Any]:
    """Get definition location for a symbol at the given position.
    
    Args:
        file_path: Path to the file
        line: Line number (0-based)
        column: Column number (0-based)
        workspace: Workspace directory
        
    Returns:
        Dictionary containing definition location information
    """
    try:
        # Validate file path
        file_path = validate_path(file_path)
        workspace_path = validate_path(workspace)
        
        # Get LSP bus
        lsp_bus = get_lsp_bus()
        
        # Detect language
        language = lsp_bus.detect_language(file_path)
        if not language:
            raise LSPToolException(f"Unsupported file type: {file_path.suffix}")
        
        # Ensure server is running
        server = await lsp_bus.ensure_server(language, workspace_path)
        
        # Get definition
        result = await server.definition(
            file_path=file_path,
            position={"line": line, "column": column}
        )
        
        return {
            "success": True,
            "language": language,
            "definition": result,
            "position": {"line": line, "column": column},
            "file_path": str(file_path),
        }
        
    except Exception as e:
        logger.error(f"Error in lsp_definition: {e}")
        raise LSPToolException(f"Definition lookup failed: {str(e)}")


@emit_span("lsp.references")
async def lsp_references(
    file_path: str,
    line: int,
    column: int,
    include_declaration: bool = True,
    workspace: str = "."
) -> Dict[str, Any]:
    """Get all references to a symbol at the given position.
    
    Args:
        file_path: Path to the file
        line: Line number (0-based)
        column: Column number (0-based)
        include_declaration: Whether to include the declaration itself
        workspace: Workspace directory
        
    Returns:
        Dictionary containing list of reference locations
    """
    try:
        # Validate file path
        file_path = validate_path(file_path)
        workspace_path = validate_path(workspace)
        
        # Get LSP bus
        lsp_bus = get_lsp_bus()
        
        # Detect language
        language = lsp_bus.detect_language(file_path)
        if not language:
            raise LSPToolException(f"Unsupported file type: {file_path.suffix}")
        
        # Ensure server is running
        server = await lsp_bus.ensure_server(language, workspace_path)
        
        # Get references
        result = await server.references(
            file_path=file_path,
            position={"line": line, "column": column},
            context={"includeDeclaration": include_declaration}
        )
        
        return {
            "success": True,
            "language": language,
            "references": result,
            "position": {"line": line, "column": column},
            "include_declaration": include_declaration,
            "file_path": str(file_path),
        }
        
    except Exception as e:
        logger.error(f"Error in lsp_references: {e}")
        raise LSPToolException(f"References lookup failed: {str(e)}")


@emit_span("lsp_symbol_search")
async def lsp_symbol_search(
    query: str,
    workspace: str = ".",
    limit: int = 10
) -> Dict[str, Any]:
    """Search for symbols in the workspace.
    
    Args:
        query: Search query
        workspace: Workspace directory
        limit: Maximum number of results
        
    Returns:
        Dictionary containing list of matching symbols
    """
    try:
        # Validate workspace path
        workspace_path = validate_path(workspace)
        
        # Get LSP bus
        lsp_bus = get_lsp_bus()
        
        # Try each supported language
        all_results = []
        
        for language in lsp_bus.get_supported_languages():
            try:
                server = await lsp_bus.ensure_server(language, workspace_path)
                
                # Search symbols
                results = await server.symbol_search(query, limit)
                
                # Add language information
                for result in results:
                    result["language"] = language
                
                all_results.extend(results)
                
            except Exception as e:
                logger.warning(f"Symbol search failed for {language}: {e}")
                continue
        
        return {
            "success": True,
            "query": query,
            "symbols": all_results[:limit],
            "total_found": len(all_results),
            "workspace": str(workspace_path),
        }
        
    except Exception as e:
        logger.error(f"Error in lsp_symbol_search: {e}")
        raise LSPToolException(f"Symbol search failed: {str(e)}")


@emit_span("lsp_rename")
async def lsp_rename(
    file_path: str,
    line: int,
    column: int,
    new_name: str,
    workspace: str = "."
) -> Dict[str, Any]:
    """Rename a symbol at the given position.
    
    Args:
        file_path: Path to the file
        line: Line number (0-based)
        column: Column number (0-based)
        new_name: New name for the symbol
        workspace: Workspace directory
        
    Returns:
        Dictionary containing rename result with changes
    """
    try:
        # Validate file path
        file_path = validate_path(file_path)
        workspace_path = validate_path(workspace)
        
        # Get LSP bus
        lsp_bus = get_lsp_bus()
        
        # Detect language
        language = lsp_bus.detect_language(file_path)
        if not language:
            raise LSPToolException(f"Unsupported file type: {file_path.suffix}")
        
        # Ensure server is running
        server = await lsp_bus.ensure_server(language, workspace_path)
        
        # Perform rename
        result = await server.rename(
            file_path=file_path,
            position={"line": line, "column": column},
            new_name=new_name
        )
        
        return {
            "success": True,
            "language": language,
            "rename_result": result,
            "old_name": result.get("originalName", "unknown"),
            "new_name": new_name,
            "position": {"line": line, "column": column},
            "file_path": str(file_path),
        }
        
    except Exception as e:
        logger.error(f"Error in lsp_rename: {e}")
        raise LSPToolException(f"Rename failed: {str(e)}")


@emit_span("lsp_diagnostics")
async def lsp_diagnostics(
    file_path: str,
    workspace: str = "."
) -> Dict[str, Any]:
    """Get diagnostics for a file.
    
    Args:
        file_path: Path to the file
        workspace: Workspace directory
        
    Returns:
        Dictionary containing list of diagnostics (errors, warnings, etc.)
    """
    try:
        # Validate file path
        file_path = validate_path(file_path)
        workspace_path = validate_path(workspace)
        
        # Get LSP bus
        lsp_bus = get_lsp_bus()
        
        # Detect language
        language = lsp_bus.detect_language(file_path)
        if not language:
            raise LSPToolException(f"Unsupported file type: {file_path.suffix}")
        
        # Ensure server is running
        server = await lsp_bus.ensure_server(language, workspace_path)
        
        # Get diagnostics
        result = await server.diagnostics(file_path=file_path)
        
        return {
            "success": True,
            "language": language,
            "diagnostics": result,
            "file_path": str(file_path),
            "error_count": len([d for d in result if d.get("severity") == 1]),
            "warning_count": len([d for d in result if d.get("severity") == 2]),
            "info_count": len([d for d in result if d.get("severity") == 3]),
        }
        
    except Exception as e:
        logger.error(f"Error in lsp_diagnostics: {e}")
        raise LSPToolException(f"Diagnostics failed: {str(e)}")


@emit_span("lsp_code_action")
async def lsp_code_action(
    file_path: str,
    line: int,
    column: int,
    workspace: str = "."
) -> Dict[str, Any]:
    """Get available code actions at the given position.
    
    Args:
        file_path: Path to the file
        line: Line number (0-based)
        column: Column number (0-based)
        workspace: Workspace directory
        
    Returns:
        Dictionary containing list of available code actions
    """
    try:
        # Validate file path
        file_path = validate_path(file_path)
        workspace_path = validate_path(workspace)
        
        # Get LSP bus
        lsp_bus = get_lsp_bus()
        
        # Detect language
        language = lsp_bus.detect_language(file_path)
        if not language:
            raise LSPToolException(f"Unsupported file type: {file_path.suffix}")
        
        # Ensure server is running
        server = await lsp_bus.ensure_server(language, workspace_path)
        
        # Get code actions
        result = await server.code_action(
            file_path=file_path,
            range={
                "start": {"line": line, "character": column},
                "end": {"line": line, "character": column}
            }
        )
        
        return {
            "success": True,
            "language": language,
            "code_actions": result,
            "position": {"line": line, "column": column},
            "file_path": str(file_path),
            "action_count": len(result),
        }
        
    except Exception as e:
        logger.error(f"Error in lsp_code_action: {e}")
        raise LSPToolException(f"Code action lookup failed: {str(e)}")


# Tool definitions for LangChain
LSP_TOOLS = [
    {
        "name": "lsp_hover",
        "description": "Get hover information for a position in a file (signature, type, documentation)",
        "parameters": {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Path to the file"
                },
                "line": {
                    "type": "integer",
                    "description": "Line number (0-based)"
                },
                "column": {
                    "type": "integer", 
                    "description": "Column number (0-based)"
                },
                "workspace": {
                    "type": "string",
                    "description": "Workspace directory",
                    "default": "."
                }
            },
            "required": ["file_path", "line", "column"]
        }
    },
    {
        "name": "lsp_definition",
        "description": "Get definition location for a symbol at the given position",
        "parameters": {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Path to the file"
                },
                "line": {
                    "type": "integer",
                    "description": "Line number (0-based)"
                },
                "column": {
                    "type": "integer",
                    "description": "Column number (0-based)"
                },
                "workspace": {
                    "type": "string",
                    "description": "Workspace directory",
                    "default": "."
                }
            },
            "required": ["file_path", "line", "column"]
        }
    },
    {
        "name": "lsp_references",
        "description": "Get all references to a symbol at the given position",
        "parameters": {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Path to the file"
                },
                "line": {
                    "type": "integer",
                    "description": "Line number (0-based)"
                },
                "column": {
                    "type": "integer",
                    "description": "Column number (0-based)"
                },
                "include_declaration": {
                    "type": "boolean",
                    "description": "Whether to include the declaration itself",
                    "default": True
                },
                "workspace": {
                    "type": "string",
                    "description": "Workspace directory",
                    "default": "."
                }
            },
            "required": ["file_path", "line", "column"]
        }
    },
    {
        "name": "lsp_symbol_search",
        "description": "Search for symbols in the workspace",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query"
                },
                "workspace": {
                    "type": "string",
                    "description": "Workspace directory",
                    "default": "."
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of results",
                    "default": 10
                }
            },
            "required": ["query"]
        }
    },
    {
        "name": "lsp_rename",
        "description": "Rename a symbol at the given position",
        "parameters": {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Path to the file"
                },
                "line": {
                    "type": "integer",
                    "description": "Line number (0-based)"
                },
                "column": {
                    "type": "integer",
                    "description": "Column number (0-based)"
                },
                "new_name": {
                    "type": "string",
                    "description": "New name for the symbol"
                },
                "workspace": {
                    "type": "string",
                    "description": "Workspace directory",
                    "default": "."
                }
            },
            "required": ["file_path", "line", "column", "new_name"]
        }
    },
    {
        "name": "lsp_diagnostics",
        "description": "Get diagnostics for a file (errors, warnings, etc.)",
        "parameters": {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Path to the file"
                },
                "workspace": {
                    "type": "string",
                    "description": "Workspace directory",
                    "default": "."
                }
            },
            "required": ["file_path"]
        }
    },
    {
        "name": "lsp_code_action",
        "description": "Get available code actions at the given position",
        "parameters": {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Path to the file"
                },
                "line": {
                    "type": "integer",
                    "description": "Line number (0-based)"
                },
                "column": {
                    "type": "integer",
                    "description": "Column number (0-based)"
                },
                "workspace": {
                    "type": "string",
                    "description": "Workspace directory",
                    "default": "."
                }
            },
            "required": ["file_path", "line", "column"]
        }
    }
]