"""Skills UI: browse + activate (B-19) - list skills, toggle.

Provides web interface for browsing and managing skills.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from app.core.skills import get_skill_registry

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ui/api", tags=["nextjs-web-ui"])


class SkillModel(BaseModel):
    """Skill model."""
    name: str
    description: str
    version: str
    author: str
    category: str
    tags: List[str]
    tools: List[str]
    hooks: List[str]
    dependencies: List[str]
    metadata: Dict[str, Any]
    is_active: bool
    validation_status: str


class SkillFilter(BaseModel):
    """Skill filter model."""
    category: Optional[str] = None
    tag: Optional[str] = None
    search: Optional[str] = None
    active_only: bool = False
    limit: int = 50
    offset: int = 0


class SkillActivationRequest(BaseModel):
    """Skill activation request."""
    skill_name: str
    activate: bool = True


class SkillsUI:
    """UI for managing skills."""

    def __init__(self):
        self.skill_registry = get_skill_registry()

    async def list_skills(self, filter: SkillFilter) -> Dict[str, Any]:
        """List skills with filtering."""
        try:
            # Get all skills
            all_skills = self.skill_registry.list_skills()
            
            # Apply category filter
            if filter.category:
                all_skills = self.skill_registry.get_skills_by_category(filter.category)
            
            # Apply tag filter
            if filter.tag:
                all_skills = self.skill_registry.get_skills_by_tag(filter.tag)
            
            # Apply search filter
            if filter.search:
                search_term = filter.search.lower()
                filtered_skills = []
                for skill in all_skills:
                    if (search_term in skill.name.lower() or 
                        search_term in skill.description.lower() or
                        any(search_term in tag.lower() for tag in skill.tags)):
                        filtered_skills.append(skill)
            else:
                filtered_skills = all_skills
            
            # Apply active filter
            if filter.active_only:
                filtered_skills = [skill for skill in filtered_skills if skill.is_active]
            
            # Sort by name
            filtered_skills.sort(key=lambda x: x.name.lower())
            
            # Apply pagination
            total_count = len(filtered_skills)
            paginated_skills = filtered_skills[filter.offset : filter.offset + filter.limit]
            
            # Format skill models
            skill_models = []
            for skill in paginated_skills:
                validation_result = self.skill_registry.validate_skill(skill.name)
                skill_models.append(SkillModel(
                    name=skill.name,
                    description=skill.description,
                    version=skill.version,
                    author=skill.author,
                    category=skill.category,
                    tags=skill.tags,
                    tools=skill.tools,
                    hooks=skill.hooks,
                    dependencies=skill.dependencies,
                    metadata=skill.metadata,
                    is_active=skill.is_active,
                    validation_status="valid" if validation_result.get("valid") else "invalid",
                ))
            
            return {
                "skills": skill_models,
                "total_count": total_count,
                "filtered_count": len(filtered_skills),
                "limit": filter.limit,
                "offset": filter.offset,
                "categories": self.skill_registry.get_skill_categories(),
                "tags": self.skill_registry.get_skill_tags(),
            }

        except Exception as e:
            logger.error(f"Failed to list skills: {e}")
            raise HTTPException(status_code=500, detail=f"Failed to list skills: {str(e)}")

    async def get_skill_info(self, skill_name: str) -> SkillModel:
        """Get detailed information about a skill."""
        try:
            skill = self.skill_registry.get_skill(skill_name)
            if not skill:
                raise HTTPException(status_code=404, detail="Skill not found")
            
            validation_result = self.skill_registry.validate_skill(skill.name)
            
            return SkillModel(
                name=skill.name,
                description=skill.description,
                version=skill.version,
                author=skill.author,
                category=skill.category,
                tags=skill.tags,
                tools=skill.tools,
                hooks=skill.hooks,
                dependencies=skill.dependencies,
                metadata=skill.metadata,
                is_active=skill.is_active,
                validation_status="valid" if validation_result.get("valid") else "invalid",
            )

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Failed to get skill info: {e}")
            raise HTTPException(status_code=500, detail=f"Failed to get skill info: {str(e)}")

    async def activate_skill(self, request: SkillActivationRequest) -> Dict[str, Any]:
        """Activate or deactivate a skill."""
        try:
            skill = self.skill_registry.get_skill(request.skill_name)
            if not skill:
                raise HTTPException(status_code=404, detail="Skill not found")
            
            if request.activate:
                # Activate skill
                activated_items = self.skill_registry.activate_skill(request.skill_name)
                return {
                    "skill_name": request.skill_name,
                    "action": "activated",
                    "activated_items": activated_items,
                    "message": f"Skill '{request.skill_name}' activated successfully",
                }
            else:
                # Deactivate skill
                deactivated_items = self.skill_registry.deactivate_skill(request.skill_name)
                return {
                    "skill_name": request.skill_name,
                    "action": "deactivated",
                    "deactivated_items": deactivated_items,
                    "message": f"Skill '{request.skill_name}' deactivated successfully",
                }

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Failed to activate skill: {e}")
            raise HTTPException(status_code=500, detail=f"Failed to activate skill: {str(e)}")

    async def validate_skill(self, skill_name: str) -> Dict[str, Any]:
        """Validate a skill."""
        try:
            validation_result = self.skill_registry.validate_skill(skill_name)
            
            # Add additional validation details
            skill = self.skill_registry.get_skill(skill_name)
            if skill:
                validation_result["skill_info"] = {
                    "name": skill.name,
                    "description": skill.description,
                    "tools": skill.tools,
                    "hooks": skill.hooks,
                    "dependencies": skill.dependencies,
                }
            
            return validation_result

        except Exception as e:
            logger.error(f"Failed to validate skill: {e}")
            raise HTTPException(status_code=500, detail=f"Failed to validate skill: {str(e)}")

    async def get_skill_dependencies(self, skill_name: str) -> Dict[str, Any]:
        """Get skill dependencies."""
        try:
            skill = self.skill_registry.get_skill(skill_name)
            if not skill:
                raise HTTPException(status_code=404, detail="Skill not found")
            
            dependencies = self.skill_registry.get_skill_dependencies(skill_name)
            resolved_dependencies = self.skill_registry.resolve_skill_dependencies(skill_name)
            
            return {
                "skill_name": skill_name,
                "dependencies": dependencies,
                "resolved_dependencies": resolved_dependencies,
                "dependency_tree": self._build_dependency_tree(skill_name),
            }

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Failed to get skill dependencies: {e}")
            raise HTTPException(status_code=500, detail=f"Failed to get skill dependencies: {str(e)}")

    async def get_skill_statistics(self) -> Dict[str, Any]:
        """Get skill statistics."""
        try:
            all_skills = self.skill_registry.list_skills()
            active_skills = [skill for skill in all_skills if skill.is_active]
            
            # Count by category
            category_counts = {}
            for skill in all_skills:
                category = skill.category
                category_counts[category] = category_counts.get(category, 0) + 1
            
            # Count by tag
            tag_counts = {}
            for skill in all_skills:
                for tag in skill.tags:
                    tag_counts[tag] = tag_counts.get(tag, 0) + 1
            
            # Count tools and hooks
            total_tools = set()
            total_hooks = set()
            for skill in all_skills:
                total_tools.update(skill.tools)
                total_hooks.update(skill.hooks)
            
            return {
                "total_skills": len(all_skills),
                "active_skills": len(active_skills),
                "inactive_skills": len(all_skills) - len(active_skills),
                "categories": category_counts,
                "tags": tag_counts,
                "unique_tools": len(total_tools),
                "unique_hooks": len(total_hooks),
                "average_tools_per_skill": sum(len(skill.tools) for skill in all_skills) / len(all_skills) if all_skills else 0,
                "average_hooks_per_skill": sum(len(skill.hooks) for skill in all_skills) / len(all_skills) if all_skills else 0,
            }

        except Exception as e:
            logger.error(f"Failed to get skill statistics: {e}")
            raise HTTPException(status_code=500, detail=f"Failed to get skill statistics: {str(e)}")

    def _build_dependency_tree(self, skill_name: str, visited: set = None) -> Dict[str, Any]:
        """Build dependency tree for a skill."""
        if visited is None:
            visited = set()
        
        if skill_name in visited:
            return {"name": skill_name, "cycle": True}
        
        visited.add(skill_name)
        
        skill = self.skill_registry.get_skill(skill_name)
        if not skill:
            return {"name": skill_name, "error": "Skill not found"}
        
        tree = {
            "name": skill_name,
            "description": skill.description,
            "dependencies": [],
        }
        
        for dependency in skill.dependencies:
            tree["dependencies"].append(self._build_dependency_tree(dependency, visited))
        
        return tree

    async def search_skills(self, query: str) -> List[Dict[str, Any]]:
        """Search skills by name, description, or tags."""
        try:
            all_skills = self.skill_registry.list_skills()
            query_lower = query.lower()
            
            results = []
            for skill in all_skills:
                if (query_lower in skill.name.lower() or 
                    query_lower in skill.description.lower() or
                    any(query_lower in tag.lower() for tag in skill.tags)):
                    
                    validation_result = self.skill_registry.validate_skill(skill.name)
                    results.append({
                        "name": skill.name,
                        "description": skill.description,
                        "category": skill.category,
                        "tags": skill.tags,
                        "is_active": skill.is_active,
                        "is_valid": validation_result.get("valid", False),
                        "tools_count": len(skill.tools),
                        "hooks_count": len(skill.hooks),
                    })
            
            return results

        except Exception as e:
            logger.error(f"Failed to search skills: {e}")
            return []


# Global instance
_skills_ui = None


def get_skills_ui() -> SkillsUI:
    """Get the global skills UI instance."""
    global _skills_ui
    if _skills_ui is None:
        _skills_ui = SkillsUI()
    return _skills_ui


@router.get("/skills")
async def list_skills(
    category: Optional[str] = Query(None, description="Filter by category"),
    tag: Optional[str] = Query(None, description="Filter by tag"),
    search: Optional[str] = Query(None, description="Search term"),
    active_only: bool = Query(False, description="Show only active skills"),
    limit: int = Query(50, ge=1, le=100, description="Maximum number of skills"),
    offset: int = Query(0, ge=0, description="Offset for pagination"),
):
    """List skills with optional filtering."""
    filter = SkillFilter(
        category=category,
        tag=tag,
        search=search,
        active_only=active_only,
        limit=limit,
        offset=offset,
    )
    skills_ui = get_skills_ui()
    return await skills_ui.list_skills(filter)


@router.get("/skills/{skill_name}")
async def get_skill_info(skill_name: str):
    """Get detailed information about a skill."""
    skills_ui = get_skills_ui()
    return await skills_ui.get_skill_info(skill_name)


@router.post("/skills/activate")
async def activate_skill(request: SkillActivationRequest):
    """Activate or deactivate a skill."""
    skills_ui = get_skills_ui()
    return await skills_ui.activate_skill(request)


@router.get("/skills/{skill_name}/validate")
async def validate_skill(skill_name: str):
    """Validate a skill."""
    skills_ui = get_skills_ui()
    return await skills_ui.validate_skill(skill_name)


@router.get("/skills/{skill_name}/dependencies")
async def get_skill_dependencies(skill_name: str):
    """Get skill dependencies."""
    skills_ui = get_skills_ui()
    return await skills_ui.get_skill_dependencies(skill_name)


@router.get("/skills/statistics")
async def get_skill_statistics():
    """Get skill statistics."""
    skills_ui = get_skills_ui()
    return await skills_ui.get_skill_statistics()


@router.get("/skills/search")
async def search_skills(q: str):
    """Search skills by name, description, or tags."""
    skills_ui = get_skills_ui()
    return await skills_ui.search_skills(q)


@router.get("/skills/categories")
async def get_skill_categories():
    """Get all skill categories."""
    skills_ui = get_skills_ui()
    return {"categories": skills_ui.skill_registry.get_skill_categories()}


@router.get("/skills/tags")
async def get_skill_tags():
    """Get all skill tags."""
    skills_ui = get_skills_ui()
    return {"tags": skills_ui.skill_registry.get_skill_tags()}