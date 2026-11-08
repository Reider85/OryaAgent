"""Skills API endpoints (B-07).

Provides REST API endpoints for browsing, activating, and managing skills.
"""

from typing import List, Optional
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel

from app.core.skills import get_skill_registry, Skill

router = APIRouter(prefix="/skills", tags=["skills"])


class SkillInfo(BaseModel):
    """Skill information model."""

    name: str
    description: str
    version: str
    author: str
    category: str
    tags: List[str]
    tools: List[str]
    hooks: List[str]
    dependencies: List[str]
    metadata: dict


class SkillActivationRequest(BaseModel):
    """Skill activation request model."""

    skill_name: str
    activate: bool = True


@router.get("/categories", response_model=List[str])
async def list_categories():
    """List all available skill categories."""
    registry = get_skill_registry()
    return registry.get_skill_categories()


@router.get("/tags", response_model=List[str])
async def list_tags():
    """List all available skill tags."""
    registry = get_skill_registry()
    return registry.get_skill_tags()


@router.get("/search", response_model=List[SkillInfo])
async def search_skills(
    query: str, category: Optional[str] = None, tag: Optional[str] = None
):
    """Search for skills by name, description, or tags."""
    registry = get_skill_registry()
    all_skills = registry.list_skills()

    # Filter by category if specified
    if category:
        all_skills = registry.get_skills_by_category(category)

    # Filter by tag if specified
    if tag:
        all_skills = registry.get_skills_by_tag(tag)

    # Simple text search
    query_lower = query.lower()
    matching_skills = []

    for skill in all_skills:
        if (
            query_lower in skill.name.lower()
            or query_lower in skill.description.lower()
            or any(query_lower in t.lower() for t in skill.tags)
        ):
            matching_skills.append(skill)

    return [
        SkillInfo(
            name=skill.name,
            description=skill.description,
            version=skill.config.get("version", "1.0.0"),
            author=skill.config.get("author", "Unknown"),
            category=skill.config.get("category", "general"),
            tags=skill.config.get("tags", []),
            tools=skill.config.get("tools", []),
            hooks=skill.config.get("hooks", []),
            dependencies=skill.config.get("dependencies", []),
            metadata=skill.config.get("metadata", {}),
        )
        for skill in matching_skills
    ]


@router.get("/active", response_model=List[SkillInfo])
async def list_active_skills():
    """List all currently active skills."""
    return await list_skills(active_only=True)


@router.get("/validate/{skill_name}", response_model=dict)
async def validate_skill(skill_name: str):
    """Validate a skill's configuration and dependencies."""
    registry = get_skill_registry()

    skill = registry.get_skill(skill_name)
    if not skill:
        raise HTTPException(status_code=404, detail=f"Skill '{skill_name}' not found")

    validation_result = registry.validate_skill(skill_name)
    return {
        "skill_name": skill_name,
        "is_valid": validation_result.get("valid", False),
        "message": validation_result.get("message", "Validation completed"),
    }


@router.get("/", response_model=List[SkillInfo])
async def list_skills(
    category: Optional[str] = None, tag: Optional[str] = None, active_only: bool = False
):
    """List all available skills, optionally filtered by category or tag."""
    registry = get_skill_registry()
    skills = registry.list_skills()

    if category:
        skills = registry.get_skills_by_category(category)

    if tag:
        skills = registry.get_skills_by_tag(tag)

    if active_only:
        skills = [skill for skill in skills if skill.is_active]

    return [
        SkillInfo(
            name=skill.name,
            description=skill.description,
            version=skill.config.get("version", "1.0.0"),
            author=skill.config.get("author", "Unknown"),
            category=skill.config.get("category", "general"),
            tags=skill.config.get("tags", []),
            tools=skill.config.get("tools", []),
            hooks=skill.config.get("hooks", []),
            dependencies=skill.config.get("dependencies", []),
            metadata=skill.config.get("metadata", {}),
        )
        for skill in skills
    ]


@router.get("/{skill_name}", response_model=SkillInfo)
async def get_skill(skill_name: str):
    """Get detailed information about a specific skill."""
    registry = get_skill_registry()
    skill = registry.get_skill(skill_name)

    if not skill:
        raise HTTPException(status_code=404, detail=f"Skill '{skill_name}' not found")

    return SkillInfo(
        name=skill.name,
        description=skill.description,
        version=skill.config.get("version", "1.0.0"),
        author=skill.config.get("author", "Unknown"),
        category=skill.config.get("category", "general"),
        tags=skill.config.get("tags", []),
        tools=skill.config.get("tools", []),
        hooks=skill.config.get("hooks", []),
        dependencies=skill.config.get("dependencies", []),
        metadata=skill.config.get("metadata", {}),
    )


@router.post("/activate", response_model=dict)
async def activate_skill(request: SkillActivationRequest):
    """Activate or deactivate a skill."""
    registry = get_skill_registry()

    try:
        if request.activate:
            registry.activate_skill(request.skill_name)
            return {
                "message": f"Skill '{request.skill_name}' activated",
                "skill_name": request.skill_name,
            }
        else:
            registry.deactivate_skill(request.skill_name)
            return {
                "message": f"Skill '{request.skill_name}' deactivated",
                "skill_name": request.skill_name,
            }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/validate/{skill_name}", response_model=dict)
async def validate_skill(skill_name: str):
    """Validate a skill's configuration and dependencies."""
    registry = get_skill_registry()

    try:
        validation_result = registry.validate_skill(skill_name)
        return {
            "skill_name": skill_name,
            "is_valid": validation_result.get("valid", False),
            "message": validation_result.get("message", "Validation completed"),
        }
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
