"""Skills UI component (B-07).

Provides Chainlit UI for browsing and managing skills.
"""

import json

import chainlit as cl
import httpx
from chainlit.action import Action
from chainlit.input_widget import Select, Switch, TextInput
# UIMessage not available in this chainlit version
class UIMessage(dict):
    """UI message for skills."""
    
    def __init__(self, content: str = "", **kwargs):
        super().__init__(**kwargs)
        self["content"] = content
        self["author"] = kwargs.get("author", "Assistant")

from app.core.config import get_settings
from app.core.skills import get_skill_registry


class SkillsUI:
    """Skills management UI component."""

    def __init__(self):
        self.registry = get_skill_registry()
        self.settings = get_settings()

    async def show_skills_browser(self):
        """Show the skills browser interface."""
        # Create a skills browser message
        skills_browser = cl.Message(content="", author="Skills")

        # Get all skills
        all_skills = await self._get_all_skills()
        categories = await self._get_categories()

        # Create UI elements
        # Category filter
        category_select = Select(
            id="category_filter",
            label="Filter by Category",
            values=["All"] + categories,
            initial_value="All",
        )

        # Active skills toggle
        active_toggle = Switch(
            id="active_only", label="Active Skills Only", initial_value=False
        )

        # Search input
        search_input = TextInput(
            id="search_query",
            label="Search Skills",
            placeholder="Search by name, description, or tags...",
        )

        # Add widgets to the step
        await skills_browser.add_ui_component(category_select)
        await skills_browser.add_ui_component(active_toggle)
        await skills_browser.add_ui_component(search_input)

        # Add refresh button as an action
        refresh_action = Action(
            name="refresh_skills",
            label="🔄 Refresh Skills",
            payload={"action": "refresh"},
        )
        await refresh_action.send(skills_browser.id)

        # Add skills list
        await self._display_skills_list(skills_browser, all_skills)

        # Set up event handlers
        self._setup_event_handlers()

        # Update the message
        await skills_browser.update()

    async def _get_all_skills(self) -> list[dict]:
        """Get all skills from the API."""
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"{self.settings.orya_api_url}/skills/", timeout=10.0
                )
                response.raise_for_status()
                return response.json()
        except Exception as e:
            cl.logger.error(f"Error fetching skills: {e}")
            return []

    async def _get_categories(self) -> list[str]:
        """Get all skill categories from the API."""
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"{self.settings.orya_api_url}/skills/categories", timeout=10.0
                )
                response.raise_for_status()
                return response.json()
        except Exception as e:
            cl.logger.error(f"Error fetching categories: {e}")
            return []

    async def _display_skills_list(self, message: cl.Message, skills: list[dict]):
        """Display the skills list in the UI."""
        if not skills:
            message.content += "\n\nNo skills found."
            return

        skills_content = "\n\n## Available Skills\n\n"

        for skill in skills:
            # Skill header with skill name for action reference
            skill_name = skill["name"]
            skills_content += f"### {skill_name}\n\n"
            skills_content += f"**Description:** {skill['description']}\n\n"
            skills_content += (
                f"**Version:** {skill['version']} | **Author:** {skill['author']}\n\n"
            )
            skills_content += f"**Category:** {skill['category']} | **Status:** {'Active' if skill.get('is_active', False) else 'Inactive'}\n\n"

            # Tags
            if skill.get("tags"):
                skills_content += f"**Tags:** {', '.join(skill['tags'])}\n\n"

            # Tools
            if skill.get("tools"):
                skills_content += f"**Tools:** {', '.join(skill['tools'])}\n\n"

            # Actions
            skills_content += "**Actions:** "

            # Note: Action buttons are handled separately through the Action system
            action_text = "Deactivate" if skill.get("is_active", False) else "Activate"
            skills_content += f"[{action_text}] (Click to {action_text.lower()})"

            skills_content += "\n\n---\n\n"

        message.content += skills_content

    def _setup_event_handlers(self):
        """Set up event handlers for the skills UI."""

        @cl.on_message
        async def on_message(message: cl.Message):
            """Handle incoming messages."""
            if message.content.startswith("/skills"):
                await self._handle_skills_command(message)

        @cl.on_action
        async def on_action(action):
            """Handle action events."""
            action_name = action.get("name")

            if action_name == "refresh_skills":
                await self._handle_refresh(action)
            elif action_name == "activate_skill":
                skill_name = action.get("payload", {}).get("skill_name")
                if skill_name:
                    await self._activate_skill(skill_name, None)
            elif action_name == "deactivate_skill":
                skill_name = action.get("payload", {}).get("skill_name")
                if skill_name:
                    await self._deactivate_skill(skill_name, None)

    async def _handle_skills_command(self, message: cl.Message):
        """Handle the /skills command."""
        parts = message.content.split()
        if len(parts) == 1:
            # Just /skills - show browser
            await self.show_skills_browser()
        elif len(parts) == 3 and parts[1] == "activate":
            skill_name = parts[2]
            await self._activate_skill(skill_name, message)
        elif len(parts) == 3 and parts[1] == "deactivate":
            skill_name = parts[2]
            await self._deactivate_skill(skill_name, message)
        elif len(parts) == 3 and parts[1] == "info":
            skill_name = parts[2]
            await self._show_skill_info(skill_name, message)
        else:
            await message.reply(
                "Usage: /skills [activate|deactivate|info] <skill_name>"
            )

    async def _activate_skill(self, skill_name: str, message: cl.Message):
        """Activate a skill."""
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.settings.orya_api_url}/skills/activate",
                    json={"skill_name": skill_name, "activate": True},
                    timeout=10.0,
                )
                response.raise_for_status()
                result = response.json()
                await message.reply(f"✅ {result['message']}")

                # Update the skill with action buttons
                skill_name = result.get("skill_name", skill_name)
                is_active = result.get("is_active", False)
                await self._update_skill_with_actions(skill_name, is_active)

        except Exception as e:
            await message.reply(f"❌ Error activating skill: {e}")

    async def _deactivate_skill(self, skill_name: str, message: cl.Message):
        """Deactivate a skill."""
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.settings.orya_api_url}/skills/activate",
                    json={"skill_name": skill_name, "activate": False},
                    timeout=10.0,
                )
                response.raise_for_status()
                result = response.json()
                await message.reply(f"✅ {result['message']}")

                # Update the skill with action buttons
                skill_name = result.get("skill_name", skill_name)
                is_active = result.get("is_active", False)
                await self._update_skill_with_actions(skill_name, is_active)

        except Exception as e:
            await message.reply(f"❌ Error deactivating skill: {e}")

    async def _show_skill_info(self, skill_name: str, message: cl.Message):
        """Show detailed information about a skill."""
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"{self.settings.orya_api_url}/skills/{skill_name}", timeout=10.0
                )
                response.raise_for_status()
                skill = response.json()

                info_content = f"\n\n## Skill: {skill['name']}\n\n"
                info_content += f"**Description:** {skill['description']}\n\n"
                info_content += f"**Version:** {skill['version']} | **Author:** {skill['author']}\n\n"
                info_content += f"**Category:** {skill['category']} | **Status:** {'Active' if skill.get('is_active', False) else 'Inactive'}\n\n"

                if skill.get("tags"):
                    info_content += f"**Tags:** {', '.join(skill['tags'])}\n\n"

                if skill.get("tools"):
                    info_content += f"**Tools:** {', '.join(skill['tools'])}\n\n"

                if skill.get("hooks"):
                    info_content += f"**Hooks:** {', '.join(skill['hooks'])}\n\n"

                if skill.get("dependencies"):
                    info_content += (
                        f"**Dependencies:** {', '.join(skill['dependencies'])}\n\n"
                    )

                if skill.get("metadata"):
                    info_content += f"**Metadata:**\n```json\n{json.dumps(skill['metadata'], indent=2)}\n```\n\n"

                await message.reply(info_content)

        except Exception as e:
            await message.reply(f"❌ Error getting skill info: {e}")

    async def _handle_category_filter(self, component: UIMessage):
        """Handle category filter change."""
        category = component.get("value")
        active_only = component.get("active_only", False)

        # Fetch filtered skills
        try:
            async with httpx.AsyncClient() as client:
                params = {}
                if category != "All":
                    params["category"] = category
                if active_only:
                    params["active_only"] = True

                response = await client.get(
                    f"{self.settings.orya_api_url}/skills/", params=params, timeout=10.0
                )
                response.raise_for_status()
                skills = response.json()

                # Find and update the skills browser message
                for message in cl.user_session.get("messages", []):
                    if "Skills Browser" in message.content:
                        message.content = ""
                        await self._display_skills_list(message, skills)
                        await message.update()
                        break

        except Exception as e:
            cl.logger.error(f"Error filtering skills: {e}")

    async def _handle_active_toggle(self, component: UIMessage):
        """Handle active skills toggle."""
        active_only = component.get("value", False)

        # Fetch filtered skills
        try:
            async with httpx.AsyncClient() as client:
                params = {"active_only": active_only}
                response = await client.get(
                    f"{self.settings.orya_api_url}/skills/", params=params, timeout=10.0
                )
                response.raise_for_status()
                skills = response.json()

                # Find and update the skills browser message
                for message in cl.user_session.get("messages", []):
                    if "Skills Browser" in message.content:
                        message.content = ""
                        await self._display_skills_list(message, skills)
                        await message.update()
                        break

        except Exception as e:
            cl.logger.error(f"Error filtering skills: {e}")

    async def _handle_search(self, component: UIMessage):
        """Handle search query."""
        query = component.get("value", "")

        if not query:
            return

        # Search for skills
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"{self.settings.orya_api_url}/skills/search",
                    params={"query": query},
                    timeout=10.0,
                )
                response.raise_for_status()
                skills = response.json()

                # Find and update the skills browser message
                for message in cl.user_session.get("messages", []):
                    if "Skills Browser" in message.content:
                        message.content = ""
                        await self._display_skills_list(message, skills)
                        await message.update()
                        break

        except Exception as e:
            cl.logger.error(f"Error searching skills: {e}")

    async def _handle_refresh(self, action):
        """Handle refresh button click."""
        await self.show_skills_browser()

    async def _create_skill_action_buttons(self, skill_name: str, is_active: bool):
        """Create action buttons for a skill."""
        # Create action buttons
        action_buttons = []

        # Activate/Deactivate button
        action_text = "Deactivate" if is_active else "Activate"
        action_name = "deactivate_skill" if is_active else "activate_skill"
        action_label = f"🔄 {action_text}"

        action = Action(
            name=action_name, label=action_label, payload={"skill_name": skill_name}
        )
        action_buttons.append(action)

        return action_buttons

    async def _update_skill_with_actions(self, skill_name: str, is_active: bool):
        """Update a skill message with action buttons."""
        # Find the skills browser message
        for message in cl.user_session.get("messages", []):
            if "Skills Browser" in message.content:
                # Create action buttons
                action_buttons = await self._create_skill_action_buttons(
                    skill_name, is_active
                )

                # Send action buttons
                for action in action_buttons:
                    await action.send(message.id)
                break


# Global skills UI instance
_skills_ui = None


def get_skills_ui() -> SkillsUI:
    """Get the global skills UI instance."""
    global _skills_ui
    if _skills_ui is None:
        _skills_ui = SkillsUI()
    return _skills_ui


# Chainlit event handlers
@cl.on_chat_start
async def on_chat_start():
    """Initialize the chat session."""
    # Add a help message about skills
    help_message = cl.Message(
        content="""
        🎯 **Skills Management**

        Use `/skills` to browse available skills and manage them.

        **Commands:**
        - `/skills` - Show skills browser
        - `/skills activate <skill_name>` - Activate a skill
        - `/skills deactivate <skill_name>` - Deactivate a skill
        - `/skills info <skill_name>` - Show detailed skill information

        **Browser Features:**
        - Filter by category
        - Show active skills only
        - Search by name, description, or tags
        - Refresh skills list
        """,
        author="System",
    )
    await help_message.send()
