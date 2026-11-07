"""Next.js Web UI: settings panel (B-13) - LLM-provider, permission-policy.

Provides settings management for the Web UI.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from app.core.config import get_settings
from app.core.permissions import PermissionPolicy
from app.core.skills import get_skill_registry

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ui/api", tags=["nextjs-web-ui"])


class SettingsModel(BaseModel):
    """Settings model."""
    llm_provider: str
    llm_model: str
    temperature: float
    max_tokens: int
    permission_policy: Dict[str, Any]
    active_skills: List[str]


class LLMProviderModel(BaseModel):
    """LLM provider model."""
    name: str
    display_name: str
    models: List[str]
    default_model: str
    description: str


class SettingsPanel:
    """Settings panel for managing application settings."""

    def __init__(self):
        self.settings = get_settings()
        self.skill_registry = get_skill_registry()
        self.permission_policy = PermissionPolicy()

    async def get_settings(self) -> SettingsModel:
        """Get current settings."""
        try:
            # Get LLM settings
            llm_config = getattr(self.settings, 'llm', {})
            
            # Get permission policy
            policy_config = self.permission_policy.get_policy_config()
            
            # Get active skills
            active_skills = []
            skills = self.skill_registry.list_skills()
            for skill in skills:
                if skill.is_active:
                    active_skills.append(skill.name)

            return SettingsModel(
                llm_provider=llm_config.get('provider', 'anthropic'),
                llm_model=llm_config.get('model', 'claude-3-sonnet-20240229'),
                temperature=llm_config.get('temperature', 0.7),
                max_tokens=llm_config.get('max_tokens', 4000),
                permission_policy=policy_config,
                active_skills=active_skills,
            )

        except Exception as e:
            logger.error(f"Failed to get settings: {e}")
            raise HTTPException(status_code=500, detail=f"Failed to get settings: {str(e)}")

    async def update_settings(self, settings: SettingsModel) -> Dict[str, Any]:
        """Update settings."""
        try:
            # Update LLM settings
            if hasattr(self.settings, 'llm'):
                self.settings.llm.provider = settings.llm_provider
                self.settings.llm.model = settings.llm_model
                self.settings.llm.temperature = settings.temperature
                self.settings.llm.max_tokens = settings.max_tokens

            # Update permission policy
            if settings.permission_policy:
                self.permission_policy.update_policy(settings.permission_policy)

            # Update active skills
            for skill_name in settings.active_skills:
                try:
                    self.skill_registry.activate_skill(skill_name)
                except Exception as e:
                    logger.warning(f"Failed to activate skill {skill_name}: {e}")

            return {"success": True, "message": "Settings updated successfully"}

        except Exception as e:
            logger.error(f"Failed to update settings: {e}")
            raise HTTPException(status_code=500, detail=f"Failed to update settings: {str(e)}")

    async def get_llm_providers(self) -> List[LLMProviderModel]:
        """Get available LLM providers."""
        try:
            # This would typically come from configuration
            providers = [
                LLMProviderModel(
                    name="anthropic",
                    display_name="Anthropic",
                    models=[
                        "claude-3-opus-20240229",
                        "claude-3-sonnet-20240229",
                        "claude-3-haiku-20240307",
                    ],
                    default_model="claude-3-sonnet-20240229",
                    description="Anthropic Claude models",
                ),
                LLMProviderModel(
                    name="openai",
                    display_name="OpenAI",
                    models=[
                        "gpt-4o",
                        "gpt-4-turbo",
                        "gpt-4o-mini",
                    ],
                    default_model="gpt-4o",
                    description="OpenAI GPT models",
                ),
                LLMProviderModel(
                    name="google",
                    display_name="Google",
                    models=[
                        "gemini-1.5-pro",
                        "gemini-1.5-flash",
                        "gemini-1.0-pro",
                    ],
                    default_model="gemini-1.5-pro",
                    description="Google Gemini models",
                ),
            ]
            return providers

        except Exception as e:
            logger.error(f"Failed to get LLM providers: {e}")
            raise HTTPException(status_code=500, detail=f"Failed to get LLM providers: {str(e)}")

    async def get_available_skills(self) -> List[Dict[str, Any]]:
        """Get available skills."""
        try:
            skills = self.skill_registry.list_skills()
            return [
                {
                    "name": skill.name,
                    "description": skill.description,
                    "version": skill.version,
                    "category": skill.category,
                    "tags": skill.tags,
                    "is_active": skill.is_active,
                    "tools": skill.tools,
                    "hooks": skill.hooks,
                }
                for skill in skills
            ]

        except Exception as e:
            logger.error(f"Failed to get available skills: {e}")
            raise HTTPException(status_code=500, detail=f"Failed to get available skills: {str(e)}")

    async def get_permission_policy(self) -> Dict[str, Any]:
        """Get current permission policy."""
        try:
            return self.permission_policy.get_policy_config()

        except Exception as e:
            logger.error(f"Failed to get permission policy: {e}")
            raise HTTPException(status_code=500, detail=f"Failed to get permission policy: {str(e)}")

    async def update_permission_policy(self, policy: Dict[str, Any]) -> Dict[str, Any]:
        """Update permission policy."""
        try:
            self.permission_policy.update_policy(policy)
            return {"success": True, "message": "Permission policy updated successfully"}

        except Exception as e:
            logger.error(f"Failed to update permission policy: {e}")
            raise HTTPException(status_code=500, detail=f"Failed to update permission policy: {str(e)}")

    async def validate_settings(self, settings: SettingsModel) -> Dict[str, Any]:
        """Validate settings before applying."""
        try:
            errors = []

            # Validate LLM settings
            if settings.llm_provider not in ["anthropic", "openai", "google"]:
                errors.append("Invalid LLM provider")

            if settings.temperature < 0 or settings.temperature > 2:
                errors.append("Temperature must be between 0 and 2")

            if settings.max_tokens < 1 or settings.max_tokens > 100000:
                errors.append("Max tokens must be between 1 and 100000")

            # Validate skills
            available_skills = [skill.name for skill in self.skill_registry.list_skills()]
            for skill_name in settings.active_skills:
                if skill_name not in available_skills:
                    errors.append(f"Skill not available: {skill_name}")

            if errors:
                return {"valid": False, "errors": errors}
            else:
                return {"valid": True, "message": "Settings are valid"}

        except Exception as e:
            logger.error(f"Failed to validate settings: {e}")
            raise HTTPException(status_code=500, detail=f"Failed to validate settings: {str(e)}")


# Global instance
_settings_panel = None


def get_settings_panel() -> SettingsPanel:
    """Get the global settings panel instance."""
    global _settings_panel
    if _settings_panel is None:
        _settings_panel = SettingsPanel()
    return _settings_panel


@router.get("/settings")
async def get_current_settings():
    """Get current settings."""
    settings_panel = get_settings_panel()
    return await settings_panel.get_settings()


@router.put("/settings")
async def update_settings(settings: SettingsModel):
    """Update settings."""
    settings_panel = get_settings_panel()
    
    # Validate settings first
    validation = await settings_panel.validate_settings(settings)
    if not validation["valid"]:
        raise HTTPException(status_code=400, detail=validation["errors"])
    
    return await settings_panel.update_settings(settings)


@router.get("/settings/llm-providers")
async def get_llm_providers():
    """Get available LLM providers."""
    settings_panel = get_settings_panel()
    return await settings_panel.get_llm_providers()


@router.get("/settings/skills")
async def get_available_skills():
    """Get available skills."""
    settings_panel = get_settings_panel()
    return await settings_panel.get_available_skills()


@router.get("/settings/permission-policy")
async def get_permission_policy():
    """Get current permission policy."""
    settings_panel = get_settings_panel()
    return await settings_panel.get_permission_policy()


@router.put("/settings/permission-policy")
async def update_permission_policy(policy: Dict[str, Any]):
    """Update permission policy."""
    settings_panel = get_settings_panel()
    return await settings_panel.update_permission_policy(policy)


@router.post("/settings/validate")
async def validate_settings(settings: SettingsModel):
    """Validate settings without applying them."""
    settings_panel = get_settings_panel()
    return await settings_panel.validate_settings(settings)