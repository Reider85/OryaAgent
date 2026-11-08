"""Skills framework for OryaAgent BETA phase.

This module implements the declarative skills framework (B-06) where skills are
defined as YAML files containing tool lists, hooks, and metadata.
"""

import logging
from pathlib import Path
from typing import Any

from app.core.hooks import get_hook_registry
from app.core.sqlite_store import get_sqlite_store
from app.core.tools import get_tools

logger = logging.getLogger(__name__)


class Skill:
    """Represents a skill defined in YAML configuration."""

    def __init__(self, name: str, config: dict[str, Any], is_active: bool = True):
        self.name = name
        self.config = config
        self.description = config.get("description", "")
        self.version = config.get("version", "1.0.0")
        self.author = config.get("author", "")
        self.tools = config.get("tools", [])
        self.hooks = config.get("hooks", [])
        self.dependencies = config.get("dependencies", [])
        self.category = config.get("category", "general")
        self.tags = config.get("tags", [])
        self.metadata = config.get("metadata", {})
        self.is_active = is_active
        self._store_metadata = False

    def __repr__(self):
        return f"Skill(name='{self.name}', version='{self.version}', active={self.is_active})"

    async def save_metadata(self):
        """Save skill metadata to SQLite store."""
        if not self._store_metadata:
            return

        store = get_sqlite_store()
        skill_data = {
            "name": self.name,
            "description": self.description,
            "version": self.version,
            "author": self.author,
            "category": self.category,
            "tags": self.tags,
            "tools": self.tools,
            "hooks": self.hooks,
            "dependencies": self.dependencies,
            "metadata": self.metadata,
            "is_active": self.is_active,
            "validation_status": "valid" if self.is_valid else "unknown",
        }

        await store.add_skill_metadata(skill_data)

    def to_dict(self) -> dict[str, Any]:
        """Convert skill to dictionary representation."""
        return {
            "name": self.name,
            "description": self.description,
            "version": self.version,
            "author": self.author,
            "tools": self.tools,
            "hooks": self.hooks,
            "dependencies": self.dependencies,
            "category": self.category,
            "tags": self.tags,
            "metadata": self.metadata,
            "is_active": self.is_active,
        }

    @property
    def is_valid(self) -> bool:
        """Check if the skill configuration is valid."""
        # Basic validation - in a real implementation, this would be more thorough
        return bool(self.name and self.description)


class SkillRegistry:
    """Registry for managing skills loaded from YAML files."""

    def __init__(self):
        self._skills: dict[str, Skill] = {}
        self._skill_paths: dict[str, Path] = {}
        self._hook_registry = get_hook_registry()
        self._skills_dir = Path(__file__).parent.parent / "skills"
        self._store = get_sqlite_store()

    async def _load_skills_from_store(self):
        """Load skills metadata from SQLite store."""
        try:
            skills_metadata = await self._store.get_skills_metadata()
            for metadata in skills_metadata:
                # Create skill from metadata
                skill = Skill(
                    name=metadata["name"],
                    config={
                        "description": metadata["description"],
                        "version": metadata["version"],
                        "author": metadata["author"],
                        "tools": metadata["tools"],
                        "hooks": metadata["hooks"],
                        "dependencies": metadata["dependencies"],
                        "category": metadata["category"],
                        "tags": metadata["tags"],
                        "metadata": metadata["metadata"],
                    },
                    is_active=metadata["is_active"],
                )
                skill._store_metadata = True
                self.register_skill(skill)
        except Exception as e:
            logger.warning(f"Failed to load skills from store: {e}")

    def register_skill(self, skill: Skill, path: Path | None = None) -> None:
        """Register a skill in the registry."""
        self._skills[skill.name] = skill
        if path:
            self._skill_paths[skill.name] = path
        logger.info(f"Registered skill: {skill.name} v{skill.version}")

    def unregister_skill(self, skill_name: str) -> None:
        """Unregister a skill from the registry."""
        if skill_name in self._skills:
            del self._skills[skill_name]
            if skill_name in self._skill_paths:
                del self._skill_paths[skill_name]
            logger.info(f"Unregistered skill: {skill_name}")

    def get_skill(self, skill_name: str) -> Skill | None:
        """Get a skill by name."""
        return self._skills.get(skill_name)

    def list_skills(self) -> list[Skill]:
        """List all registered skills."""
        return list(self._skills.values())

    def list_skill_names(self) -> list[str]:
        """List all skill names."""
        return list(self._skills.keys())

    def get_skills_by_category(self, category: str) -> list[Skill]:
        """Get skills by category."""
        return [skill for skill in self._skills.values() if skill.category == category]

    def get_skills_by_tag(self, tag: str) -> list[Skill]:
        """Get skills by tag."""
        return [skill for skill in self._skills.values() if tag in skill.tags]

    async def load_skills_from_directory(
        self, directory: str | Path | None = None
    ) -> None:
        """Load all skills from a directory containing YAML files."""
        # First load from store
        await self._load_skills_from_store()

        skills_dir = Path(directory) if directory else self._skills_dir

        if not skills_dir.exists():
            logger.warning(f"Skills directory not found: {skills_dir}")
            return

        logger.info(f"Loading skills from: {skills_dir}")

        for yaml_file in skills_dir.glob("*.yaml"):
            try:
                skill = self.load_skill_from_yaml(yaml_file)
                # Save to store
                await skill.save_metadata()
            except Exception as e:
                logger.error(f"Failed to load skill from {yaml_file}: {e}")

    def load_skill_from_yaml(self, yaml_file: str | Path) -> Skill:
        """Load a skill from a YAML file."""
        import yaml

        yaml_path = Path(yaml_file)
        if not yaml_path.exists():
            raise FileNotFoundError(f"Skill file not found: {yaml_path}")

        with open(yaml_path, encoding="utf-8") as f:
            config = yaml.safe_load(f)

        if not config or "name" not in config:
            raise ValueError(f"Invalid skill file: {yaml_path} - missing 'name' field")

        skill = Skill(config["name"], config)
        skill._store_metadata = True
        self.register_skill(skill, yaml_path)
        return skill

    async def activate_skill(self, skill_name: str) -> list[str]:
        """Activate a skill by registering its tools and hooks."""
        skill = self.get_skill(skill_name)
        if not skill:
            raise ValueError(f"Skill not found: {skill_name}")

        # Set the skill as active
        skill.is_active = True

        # Update in store
        if skill._store_metadata:
            await self._store.update_skill_activation(skill_name, True)
            await skill.save_metadata()

        activated_tools = []
        activated_hooks = []

        # Get all available tools
        all_tools = get_tools()

        # Activate tools
        for tool_name in skill.tools:
            # Find tool in available tools
            tool_found = False
            for tool in all_tools:
                if tool.name == tool_name:
                    # In a real implementation, we would bind this tool to the current session
                    activated_tools.append(tool_name)
                    tool_found = True
                    break

            if not tool_found:
                logger.warning(f"Tool '{tool_name}' not found for skill '{skill_name}'")

        # Activate hooks
        for hook_name in skill.hooks:
            # In a real implementation, we would register these hooks
            activated_hooks.append(hook_name)

        logger.info(
            f"Activated skill '{skill_name}': {len(activated_tools)} tools, {len(activated_hooks)} hooks"
        )
        return activated_tools + activated_hooks

    async def deactivate_skill(self, skill_name: str) -> list[str]:
        """Deactivate a skill by unregistering its tools and hooks."""
        skill = self.get_skill(skill_name)
        if not skill:
            raise ValueError(f"Skill not found: {skill_name}")

        # Set the skill as inactive
        skill.is_active = False

        # Update in store
        if skill._store_metadata:
            await self._store.update_skill_activation(skill_name, False)
            await skill.save_metadata()

        deactivated_tools = []
        deactivated_hooks = []

        # Deactivate tools
        for tool_name in skill.tools:
            # In a real implementation, we would unbind this tool from the current session
            deactivated_tools.append(tool_name)

        # Deactivate hooks
        for hook_name in skill.hooks:
            # In a real implementation, we would unregister these hooks
            deactivated_hooks.append(hook_name)

        logger.info(
            f"Deactivated skill '{skill_name}': {len(deactivated_tools)} tools, {len(deactivated_hooks)} hooks"
        )
        return deactivated_tools + deactivated_hooks

    async def validate_skill(self, skill_name: str) -> dict[str, Any]:
        """Validate a skill configuration."""
        skill = self.get_skill(skill_name)
        if not skill:
            return {"valid": False, "error": f"Skill not found: {skill_name}"}

        issues = []

        # Check if tools exist
        all_tools = get_tools()
        available_tool_names = {tool.name for tool in all_tools}

        for tool_name in skill.tools:
            if tool_name not in available_tool_names:
                issues.append(f"Tool '{tool_name}' not available")

        # Check if hooks exist (basic check)
        for _hook_name in skill.hooks:
            # In a real implementation, we would check if the hook exists
            pass

        is_valid = len(issues) == 0
        validation_status = "valid" if is_valid else "invalid"

        # Update validation status in store
        if skill._store_metadata:
            await self._store.update_skill_validation_status(
                skill_name, validation_status
            )
            await skill.save_metadata()

        if issues:
            return {
                "valid": False,
                "issues": issues,
                "validation_status": validation_status,
            }

        return {
            "valid": True,
            "message": "Skill configuration is valid",
            "validation_status": validation_status,
        }

    async def get_skill_dependencies(self, skill_name: str) -> list[str]:
        """Get the dependency tree for a skill."""
        skill = self.get_skill(skill_name)
        if not skill:
            return []

        # Try to get from store first
        try:
            store = get_sqlite_store()
            deps = await store.get_skill_dependencies(skill_name)
            return [dep["dependency_name"] for dep in deps]
        except Exception:
            # Fallback to in-memory calculation
            dependencies = []
            for dep in skill.dependencies:
                dependencies.append(dep)
                dependencies.extend(await self.get_skill_dependencies(dep))

            return dependencies

    def resolve_skill_dependencies(self, skill_name: str) -> list[str]:
        """Resolve skill dependencies in order."""
        visited = set()
        resolved = []

        async def visit(skill_name: str):
            if skill_name in visited:
                return
            visited.add(skill_name)

            skill = self.get_skill(skill_name)
            if skill:
                for dep in skill.dependencies:
                    await visit(dep)
                resolved.append(skill_name)

        # Run async function
        import asyncio

        asyncio.run(visit(skill_name))
        return resolved

    def export_skills(self, output_file: str | Path) -> None:
        """Export all skills to a YAML file."""
        import yaml

        skills_data = {skill.name: skill.to_dict() for skill in self._skills.values()}

        with open(output_file, "w", encoding="utf-8") as f:
            yaml.dump(skills_data, f, default_flow_style=False, indent=2)

        logger.info(f"Exported {len(skills_data)} skills to: {output_file}")

    def get_skill_categories(self) -> list[str]:
        """Get all available skill categories."""
        categories = set()
        for skill in self._skills.values():
            categories.add(skill.category)
        return sorted(list(categories))

    def get_skill_tags(self) -> list[str]:
        """Get all available skill tags."""
        tags = set()
        for skill in self._skills.values():
            tags.update(skill.tags)
        return sorted(list(tags))

    def get_skills_by_category(self, category: str) -> list[Skill]:
        """Get skills by category."""
        return [skill for skill in self._skills.values() if skill.category == category]

    def get_skills_by_tag(self, tag: str) -> list[Skill]:
        """Get skills by tag."""
        return [skill for skill in self._skills.values() if tag in skill.tags]


# Global skill registry instance
_skill_registry = None


async def get_skill_registry() -> SkillRegistry:
    """Get the global skill registry instance."""
    global _skill_registry
    if _skill_registry is None:
        _skill_registry = SkillRegistry()
        # Load skills from the skills directory
        await _skill_registry.load_skills_from_directory()
    return _skill_registry


async def initialize_skill_registry(
    directory: str | Path | None = None,
) -> SkillRegistry:
    """Initialize the skill registry with optional custom directory."""
    global _skill_registry
    _skill_registry = SkillRegistry()
    if directory:
        await _skill_registry.load_skills_from_directory(directory)
    else:
        await _skill_registry.load_skills_from_directory()
    return _skill_registry


# Convenience functions
def list_skills() -> list[Skill]:
    """List all available skills."""
    return get_skill_registry().list_skills()


def get_skill(skill_name: str) -> Skill | None:
    """Get a skill by name."""
    return get_skill_registry().get_skill(skill_name)


async def activate_skill(skill_name: str) -> list[str]:
    """Activate a skill."""
    registry = get_skill_registry()
    return await registry.activate_skill(skill_name)


async def deactivate_skill(skill_name: str) -> list[str]:
    """Deactivate a skill."""
    registry = get_skill_registry()
    return await registry.deactivate_skill(skill_name)


async def validate_skill(skill_name: str) -> dict[str, Any]:
    """Validate a skill configuration."""
    registry = get_skill_registry()
    return await registry.validate_skill(skill_name)


async def get_skill_dependencies(skill_name: str) -> list[str]:
    """Get skill dependencies."""
    registry = get_skill_registry()
    return await registry.get_skill_dependencies(skill_name)
