"""Skills UI for B-19: browse + activate skills."""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.core.skills import get_skill_registry
from app.core.security import get_current_user
from app.core.observability.spans import emit_span

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/ui/skills", tags=["skills-ui"])
templates = Jinja2Templates(directory="app/ui/templates")


@router.get("/", response_class=HTMLResponse)
async def skills_list_ui(
    request: Request,
    category: str = None,
    tag: str = None,
    current_user: str = Depends(get_current_user),
):
    """Skills list UI page."""
    try:
        registry = await get_skill_registry()

        # Get all skills
        all_skills = registry.list_skills()

        # Filter by category if specified
        if category:
            skills = registry.get_skills_by_category(category)
        # Filter by tag if specified
        elif tag:
            skills = registry.get_skills_by_tag(tag)
        else:
            skills = all_skills

        # Get available categories and tags
        categories = registry.get_skill_categories()
        tags = registry.get_skill_tags()

        return templates.TemplateResponse(
            "skills/list.html",
            {
                "request": request,
                "skills": skills,
                "all_skills": all_skills,
                "categories": categories,
                "tags": tags,
                "current_category": category,
                "current_tag": tag,
                "current_user": current_user,
            },
        )

    except Exception as e:
        logger.error(f"Error in skills list UI: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to load skills list: {str(e)}"
        )


@router.get("/browse", response_class=HTMLResponse)
async def skills_browse_ui(
    request: Request,
    search_query: str = None,
    category: str = None,
    tag: str = None,
    current_user: str = Depends(get_current_user),
):
    """Skills browse UI page with search functionality."""
    try:
        registry = await get_skill_registry()

        # Get all skills
        all_skills = registry.list_skills()

        # Filter skills based on search, category, and tag
        filtered_skills = all_skills

        if search_query:
            filtered_skills = [
                skill
                for skill in filtered_skills
                if search_query.lower() in skill.name.lower()
                or search_query.lower() in skill.description.lower()
                or any(search_query.lower() in tag.lower() for tag in skill.tags)
            ]

        if category:
            filtered_skills = registry.get_skills_by_category(category)

        if tag:
            filtered_skills = registry.get_skills_by_tag(tag)

        # Get available categories and tags
        categories = registry.get_skill_categories()
        tags = registry.get_skill_tags()

        return templates.TemplateResponse(
            "skills/browse.html",
            {
                "request": request,
                "skills": filtered_skills,
                "all_skills": all_skills,
                "categories": categories,
                "tags": tags,
                "search_query": search_query,
                "current_category": category,
                "current_tag": tag,
                "current_user": current_user,
            },
        )

    except Exception as e:
        logger.error(f"Error in skills browse UI: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to load skills browse: {str(e)}"
        )


@router.get("/detail/{skill_name}", response_class=HTMLResponse)
async def skills_detail_ui(
    request: Request,
    skill_name: str,
    current_user: str = Depends(get_current_user),
):
    """Skills detail UI page."""
    try:
        registry = await get_skill_registry()
        skill = registry.get_skill(skill_name)

        if not skill:
            raise HTTPException(status_code=404, detail="Skill not found")

        # Get validation status
        validation_result = await registry.validate_skill(skill_name)

        # Get dependencies
        dependencies = await registry.get_skill_dependencies(skill_name)

        return templates.TemplateResponse(
            "skills/detail.html",
            {
                "request": request,
                "skill": skill,
                "validation_result": validation_result,
                "dependencies": dependencies,
                "current_user": current_user,
            },
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in skills detail UI: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to load skills detail: {str(e)}"
        )


@router.post("/activate/{skill_name}")
async def skills_activate_ui(
    request: Request,
    skill_name: str,
    current_user: str = Depends(get_current_user),
):
    """Activate a skill via UI."""
    try:
        registry = await get_skill_registry()

        # Validate skill first
        validation_result = await registry.validate_skill(skill_name)
        if not validation_result.get("valid", False):
            raise HTTPException(
                status_code=400,
                detail=f"Skill validation failed: {validation_result.get('issues', ['Unknown error'])}",
            )

        # Activate skill
        activated_items = await registry.activate_skill(skill_name)

        # Redirect to skills list with success message
        return RedirectResponse("/ui/skills/", status_code=303)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error activating skill: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to activate skill: {str(e)}"
        )


@router.post("/deactivate/{skill_name}")
async def skills_deactivate_ui(
    request: Request,
    skill_name: str,
    current_user: str = Depends(get_current_user),
):
    """Deactivate a skill via UI."""
    try:
        registry = await get_skill_registry()

        # Deactivate skill
        deactivated_items = await registry.deactivate_skill(skill_name)

        # Redirect to skills list with success message
        return RedirectResponse("/ui/skills/", status_code=303)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deactivating skill: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to deactivate skill: {str(e)}"
        )


@router.get("/validation/{skill_name}", response_class=HTMLResponse)
async def skills_validation_ui(
    request: Request,
    skill_name: str,
    current_user: str = Depends(get_current_user),
):
    """Skills validation UI page."""
    try:
        registry = await get_skill_registry()
        skill = registry.get_skill(skill_name)

        if not skill:
            raise HTTPException(status_code=404, detail="Skill not found")

        validation_result = await registry.validate_skill(skill_name)

        return templates.TemplateResponse(
            "skills/validation.html",
            {
                "request": request,
                "skill": skill,
                "validation_result": validation_result,
                "current_user": current_user,
            },
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in skills validation UI: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to load skills validation: {str(e)}"
        )


@router.post("/validate/{skill_name}")
async def skills_validate_post(
    request: Request,
    skill_name: str,
    current_user: str = Depends(get_current_user),
):
    """Validate a skill via UI."""
    try:
        registry = await get_skill_registry()
        validation_result = await registry.validate_skill(skill_name)

        # Redirect to validation page with result
        return RedirectResponse(f"/ui/skills/validation/{skill_name}", status_code=303)

    except Exception as e:
        logger.error(f"Error validating skill: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to validate skill: {str(e)}"
        )


@router.get("/dependencies/{skill_name}", response_class=HTMLResponse)
async def skills_dependencies_ui(
    request: Request,
    skill_name: str,
    current_user: str = Depends(get_current_user),
):
    """Skills dependencies UI page."""
    try:
        registry = await get_skill_registry()
        skill = registry.get_skill(skill_name)

        if not skill:
            raise HTTPException(status_code=404, detail="Skill not found")

        dependencies = await registry.get_skill_dependencies(skill_name)
        resolved_dependencies = registry.resolve_skill_dependencies(skill_name)

        return templates.TemplateResponse(
            "skills/dependencies.html",
            {
                "request": request,
                "skill": skill,
                "dependencies": dependencies,
                "resolved_dependencies": resolved_dependencies,
                "current_user": current_user,
            },
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in skills dependencies UI: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to load skills dependencies: {str(e)}"
        )


@router.get("/export", response_class=HTMLResponse)
async def skills_export_ui(
    request: Request,
    current_user: str = Depends(get_current_user),
):
    """Skills export UI page."""
    try:
        registry = await get_skill_registry()
        skills = registry.list_skills()

        return templates.TemplateResponse(
            "skills/export.html",
            {
                "request": request,
                "skills": skills,
                "current_user": current_user,
            },
        )

    except Exception as e:
        logger.error(f"Error in skills export UI: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to load skills export: {str(e)}"
        )


@router.post("/export")
async def skills_export_post(
    request: Request,
    current_user: str = Depends(get_current_user),
):
    """Export skills via UI."""
    try:
        registry = await get_skill_registry()

        # Export skills to a file
        import tempfile
        import os

        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            temp_file = f.name

        registry.export_skills(temp_file)

        # Read the exported content
        with open(temp_file, "r") as f:
            exported_content = f.read()

        # Clean up temp file
        os.unlink(temp_file)

        return templates.TemplateResponse(
            "skills/export_result.html",
            {
                "request": request,
                "exported_content": exported_content,
                "current_user": current_user,
            },
        )

    except Exception as e:
        logger.error(f"Error exporting skills: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to export skills: {str(e)}"
        )


# Helper function to initialize the UI router
def setup_skills_ui():
    """Setup skills UI routes."""
    return router
