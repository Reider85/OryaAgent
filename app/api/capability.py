"""API endpoints for language capabilities (B-30).

This module provides REST API endpoints for managing and querying
language-specific programming capabilities including supported languages,
activation of language capabilities, and current active capabilities.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException, Path
from pydantic import BaseModel, Field

from app.core.capability import get_language_capability_registry, agent_program
from app.core.capability.language_registry import LanguageCapability
from app.core.observability.spans import emit_span

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/capability", tags=["capability"])


class LanguageInfo(BaseModel):
    """Language information model."""
    
    language: str = Field(..., description="Language identifier")
    lsp_server: str = Field(..., description="LSP server identifier")
    file_extensions: List[str] = Field(..., description="Supported file extensions")
    build_cmd: str = Field(..., description="Build command")
    test_cmd: str = Field(..., description="Test command")
    lint_cmd: str = Field(..., description="Lint command")
    format_cmd: str = Field(..., description="Format command")
    skill_bundle: str = Field(..., description="Skill bundle name")
    hooks: List[str] = Field(..., description="List of hook names")
    description: str = Field("", description="Human-readable description")


class ProgramRequest(BaseModel):
    """Request model for activating language capability."""
    
    language: str = Field(..., description="Target language (java, rust, go, javascript, frontend)")
    task: str = Field(..., description="Description of the programming task")


class ProgramResponse(BaseModel):
    """Response model for language capability activation."""
    
    success: bool = Field(..., description="Whether the activation was successful")
    message: str = Field(..., description="Response message")
    language: str = Field(..., description="Activated language")
    lsp_server: str = Field(..., description="LSP server used")
    skill_bundle: str = Field(..., description="Activated skill bundle")
    build_cmd: str = Field(..., description="Build command")
    test_cmd: str = Field(..., description="Test command")


class ActiveCapability(BaseModel):
    """Model for currently active language capability."""
    
    language: str = Field(..., description="Currently active language")
    lsp_server: str = Field(..., description="LSP server in use")
    skill_bundle: str = Field(..., description="Active skill bundle")
    hooks: List[str] = Field(..., description="Active hooks")
    build_cmd: str = Field(..., description="Build command")
    test_cmd: str = Field(..., description="Test command")
    activated_at: str = Field(..., description="Timestamp of activation")


@router.get("/languages", response_model=List[LanguageInfo])
async def get_supported_languages():
    """Get list of supported languages with their capabilities.
    
    Returns:
        List of supported languages with their capabilities
    """
    emit_span(
        span_type="api.capability.languages",
        name="get_supported_languages"
    )
    
    language_registry = get_language_capability_registry()
    supported_languages = language_registry.list_supported()
    
    languages = []
    for lang in supported_languages:
        capability = language_registry.resolve(lang)
        languages.append(LanguageInfo(
            language=capability.language,
            lsp_server=capability.lsp_server,
            file_extensions=capability.file_extensions,
            build_cmd=capability.build_cmd,
            test_cmd=capability.test_cmd,
            lint_cmd=capability.lint_cmd,
            format_cmd=capability.format_cmd,
            skill_bundle=capability.skill_bundle,
            hooks=capability.hooks,
            description=capability.description
        ))
    
    return languages


@router.get("/languages/{language}", response_model=LanguageInfo)
async def get_language_info(
    language: str = Path(..., description="Language identifier (java, rust, go, javascript, frontend)")
):
    """Get detailed information about a specific language capability.
    
    Args:
        language: Language identifier
        
    Returns:
        Detailed language capability information
        
    Raises:
        HTTPException: If language is not supported
    """
    emit_span(
        span_type="api.capability.language_info",
        name="get_language_info",
        attributes={"language": language}
    )
    
    language_registry = get_language_capability_registry()
    
    try:
        capability = language_registry.resolve(language)
        return LanguageInfo(
            language=capability.language,
            lsp_server=capability.lsp_server,
            file_extensions=capability.file_extensions,
            build_cmd=capability.build_cmd,
            test_cmd=capability.test_cmd,
            lint_cmd=capability.lint_cmd,
            format_cmd=capability.format_cmd,
            skill_bundle=capability.skill_bundle,
            hooks=capability.hooks,
            description=capability.description
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/program", response_model=ProgramResponse)
async def activate_language_capability(request: ProgramRequest):
    """Activate language-specific programming capabilities.
    
    This endpoint activates language-specific capabilities including
    skill-bundles, hook-sets, and LSP server initialization.
    
    Args:
        request: Language activation request
        
    Returns:
        Activation response with capability details
        
    Raises:
        HTTPException: If language is not supported
    """
    emit_span(
        span_type="api.capability.program",
        name="activate_language_capability",
        attributes={"language": request.language, "task": request.task[:100] + "..." if len(request.task) > 100 else request.task}
    )
    
    try:
        # Call agent_program function
        message = agent_program(request.language, request.task)
        
        # Get capability details for response
        language_registry = get_language_capability_registry()
        capability = language_registry.resolve(request.language)
        
        return ProgramResponse(
            success=True,
            message=message,
            language=capability.language,
            lsp_server=capability.lsp_server,
            skill_bundle=capability.skill_bundle,
            build_cmd=capability.build_cmd,
            test_cmd=capability.test_cmd
        )
        
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to activate language capability: {e}")
        raise HTTPException(status_code=500, detail="Failed to activate language capability")


@router.get("/active", response_model=ActiveCapability)
async def get_active_capability():
    """Get currently active language capability.
    
    Returns:
        Currently active language capability information
        
    Note:
        This is a simplified implementation that returns basic information.
        In a full implementation, this would track the currently active
        capability per session.
    """
    emit_span(
        span_type="api.capability.active",
        name="get_active_capability"
    )
    
    # For now, return a default capability
    # In a full implementation, this would track the active capability per session
    language_registry = get_language_capability_registry()
    
    # Return the first supported language as default
    supported_languages = language_registry.list_supported()
    if not supported_languages:
        raise HTTPException(status_code=404, detail="No supported languages found")
    
    capability = language_registry.resolve(supported_languages[0])
    
    return ActiveCapability(
        language=capability.language,
        lsp_server=capability.lsp_server,
        skill_bundle=capability.skill_bundle,
        hooks=capability.hooks,
        build_cmd=capability.build_cmd,
        test_cmd=capability.test_cmd,
        activated_at="2024-01-01T00:00:00Z"  # Placeholder timestamp
    )


@router.get("/detect/{file_path}")
async def detect_language(
    file_path: str = Path(..., description="Path to the file to analyze")
):
    """Detect language from file path.
    
    Args:
        file_path: Path to the file to analyze
        
    Returns:
        Detected language information
        
    Raises:
        HTTPException: If language cannot be detected
    """
    emit_span(
        span_type="api.capability.detect",
        name="detect_language",
        attributes={"file_path": file_path}
    )
    
    language_registry = get_language_capability_registry()
    
    try:
        language = language_registry.detect(file_path)
        capability = language_registry.resolve(language)
        
        return {
            "language": language,
            "file_extensions": capability.file_extensions,
            "description": capability.description
        }
        
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/config/{language}")
async def get_language_config(
    language: str = Path(..., description="Language identifier")
):
    """Get language-specific configuration including LSP settings.
    
    Args:
        language: Language identifier
        
    Returns:
        Language-specific configuration
        
    Raises:
        HTTPException: If language is not supported
    """
    emit_span(
        span_type="api.capability.config",
        name="get_language_config",
        attributes={"language": language}
    )
    
    from app.core.lsp.config import get_language_lsp_config
    
    try:
        lsp_config = get_language_lsp_config(language)
        capability = get_language_capability_registry().resolve(language)
        
        return {
            "language": language,
            "lsp_server": lsp_config.server_name,
            "command": lsp_config.command,
            "init_options": lsp_config.init_options,
            "file_extensions": lsp_config.file_extensions,
            "build_cmd": capability.get_build_cmd_with_settings(),
            "test_cmd": capability.get_test_cmd_with_settings(),
            "lint_cmd": capability.get_lint_cmd_with_settings(),
            "format_cmd": capability.get_format_cmd_with_settings(),
            "skill_bundle": capability.skill_bundle,
            "hooks": capability.hooks
        }
        
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/health")
async def get_capability_health():
    """Health check for language capabilities.
    
    Returns:
        Health status of language capabilities
    """
    emit_span(
        span_type="api.capability.health",
        name="get_capability_health"
    )
    
    try:
        language_registry = get_language_capability_registry()
        supported_languages = language_registry.list_supported()
        
        return {
            "status": "healthy",
            "supported_languages": len(supported_languages),
            "languages": supported_languages
        }
        
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return {
            "status": "unhealthy",
            "error": str(e)
        }