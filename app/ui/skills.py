"""Skills UI (B-07/B-19): browse + activate skills over Chainlit 2.x.

Chainlit 2.x has no per-message input widgets — ``Message.add_ui_component``
does not exist and ``Select``/``Switch``/``TextInput`` only live inside
``cl.ChatSettings``, which the settings panel already owns. The browser is
therefore one message updated in place (the sidebar pattern from
:mod:`app.ui.chainlit_app`) carrying ``cl.Action`` buttons: a Refresh plus
one Activate/Deactivate toggle per skill.

Handlers are registered at *import* time: ``config.code.action_callbacks``
is a module-level registry and the ``on_message``/``on_chat_start`` slots
are single-assignment, so registering them from inside a function would
clobber the app's main chat handlers. ``/skills`` itself is parsed in
:func:`app.ui.chainlit_app.on_message` — never from a second ``cl.on_message``.
"""

from __future__ import annotations

import json

import chainlit as cl
import httpx

from app.core.config import get_settings

#: ``cl.user_session`` key holding the single browser message (updated in
#: place so a refresh or a toggle never stacks another window).
_BROWSER_KEY = "skills_message"


class SkillsUI:
    """Skills management UI component."""

    def __init__(self):
        self.settings = get_settings()

    async def show_skills_browser(self) -> None:
        """Send the skills browser, or rewrite it in place if already open."""
        skills = await self._get_all_skills()
        content, actions = self._render(skills)

        message = cl.user_session.get(_BROWSER_KEY)
        if message is None:
            message = cl.Message(content=content, actions=actions)
            cl.user_session.set(_BROWSER_KEY, message)  # before await
            await message.send()
            return

        # The client appends action events by id-less push, so the buttons
        # being replaced have to be removed explicitly or they stack.
        await message.remove_actions()
        message.content = content
        message.actions = actions
        await message.update()

    async def activate_skill(self, skill_name: str) -> None:
        """Activate a skill and refresh the browser when it is open."""
        await self._toggle_skill(skill_name, activate=True)

    async def deactivate_skill(self, skill_name: str) -> None:
        """Deactivate a skill and refresh the browser when it is open."""
        await self._toggle_skill(skill_name, activate=False)

    async def show_skill_info(self, skill_name: str) -> None:
        """Show detailed information about a skill as its own message."""
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"{self._api_base()}/skills/{skill_name}",
                    timeout=10.0,
                )
                response.raise_for_status()
                skill = response.json()
        except Exception as e:
            cl.logger.error(f"Error getting skill info: {e}")
            await cl.Message(content=f"❌ Error getting skill info: {e}").send()
            return

        await cl.Message(content=self._info_markdown(skill)).send()

    async def _toggle_skill(self, skill_name: str, *, activate: bool) -> None:
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self._api_base()}/skills/activate",
                    json={"skill_name": skill_name, "activate": activate},
                    timeout=10.0,
                )
                response.raise_for_status()
                result = response.json()
        except Exception as e:
            verb = "activating" if activate else "deactivating"
            cl.logger.error(f"Error {verb} skill: {e}")
            await cl.Message(content=f"❌ Error {verb} skill: {e}").send()
            return

        verb = "activated" if activate else "deactivated"
        await cl.Message(content=f"✅ {result.get('message', f'Skill {verb}')}").send()
        # Keep the toggle buttons in sync with the new state (no-op when
        # the browser was never opened in this session).
        if cl.user_session.get(_BROWSER_KEY) is not None:
            await self.show_skills_browser()

    async def _get_all_skills(self) -> list[dict]:
        """Get all skills from the API (empty list when it is unreachable)."""
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(f"{self._api_base()}/skills/", timeout=10.0)
                response.raise_for_status()
                return response.json()
        except Exception as e:
            cl.logger.error(f"Error fetching skills: {e}")
            return []

    def _api_base(self) -> str:
        """FastAPI base URL (``ORYA_API_URL``, same seam as ``chainlit_app``)."""
        return str(self.settings.api_url).rstrip("/")

    def _render(self, skills: list[dict]) -> tuple[str, list[cl.Action]]:
        """Build the browser content and its Refresh + per-skill actions."""
        lines = ["## Skills Browser", ""]
        if not skills:
            lines.append("No skills found.")
        for skill in skills:
            lines.extend(self._skill_lines(skill))

        actions: list[cl.Action] = [
            cl.Action(name="refresh_skills", payload={}, label="🔄 Refresh")
        ]
        for skill in skills:
            name = str(skill.get("name") or "")
            if not name:
                continue
            active = bool(skill.get("is_active", False))
            text = "Deactivate" if active else "Activate"
            actions.append(
                cl.Action(
                    name="deactivate_skill" if active else "activate_skill",
                    payload={"skill_name": name},
                    label=f"{'⏸' if active else '✅'} {text} {name}",
                )
            )
        return ("\n".join(lines), actions)

    @staticmethod
    def _skill_lines(skill: dict) -> list[str]:
        """Markdown block for one skill (no fake links — buttons are Actions)."""
        lines = [f"### {skill['name']}", ""]
        lines.append(f"**Description:** {skill['description']}")
        lines.append("")
        lines.append(f"**Version:** {skill['version']} | **Author:** {skill['author']}")
        lines.append("")
        status = "Active" if skill.get("is_active", False) else "Inactive"
        lines.append(f"**Category:** {skill['category']} | **Status:** {status}")
        lines.append("")
        if skill.get("tags"):
            lines.append(f"**Tags:** {', '.join(skill['tags'])}")
            lines.append("")
        if skill.get("tools"):
            lines.append(f"**Tools:** {', '.join(skill['tools'])}")
            lines.append("")
        lines.append("---")
        lines.append("")
        return lines

    @staticmethod
    def _info_markdown(skill: dict) -> str:
        """Markdown body for ``/skills info <name>``."""
        lines = [f"## Skill: {skill['name']}", ""]
        lines.append(f"**Description:** {skill['description']}")
        lines.append("")
        lines.append(f"**Version:** {skill['version']} | **Author:** {skill['author']}")
        lines.append("")
        status = "Active" if skill.get("is_active", False) else "Inactive"
        lines.append(f"**Category:** {skill['category']} | **Status:** {status}")
        lines.append("")
        if skill.get("tags"):
            lines.append(f"**Tags:** {', '.join(skill['tags'])}")
            lines.append("")
        if skill.get("hooks"):
            lines.append(f"**Hooks:** {', '.join(skill['hooks'])}")
            lines.append("")
        if skill.get("dependencies"):
            lines.append(f"**Dependencies:** {', '.join(skill['dependencies'])}")
            lines.append("")
        if skill.get("metadata"):
            lines.append("**Metadata:**")
            lines.append("```json")
            lines.append(json.dumps(skill["metadata"], indent=2))
            lines.append("```")
            lines.append("")
        return "\n".join(lines)


# Global skills UI instance
_skills_ui = None


def get_skills_ui() -> SkillsUI:
    """Get the global skills UI instance."""
    global _skills_ui
    if _skills_ui is None:
        _skills_ui = SkillsUI()
    return _skills_ui


# --- Chainlit action callbacks (registered at import time) -------------------


@cl.action_callback("refresh_skills")
async def _on_refresh_skills(action: cl.Action) -> None:
    """Browser button: re-fetch the list and rewrite the browser in place."""
    await get_skills_ui().show_skills_browser()


@cl.action_callback("activate_skill")
async def _on_activate_skill(action: cl.Action) -> None:
    """Browser button: activate the skill carried in the action payload."""
    skill_name = (action.payload or {}).get("skill_name")
    if skill_name:
        await get_skills_ui().activate_skill(str(skill_name))


@cl.action_callback("deactivate_skill")
async def _on_deactivate_skill(action: cl.Action) -> None:
    """Browser button: deactivate the skill carried in the action payload."""
    skill_name = (action.payload or {}).get("skill_name")
    if skill_name:
        await get_skills_ui().deactivate_skill(str(skill_name))
