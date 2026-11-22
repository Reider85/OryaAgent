"""Unit tests for the B-19 skills browser over Chainlit 2.12.

Chainlit 2.x has no ``Message.add_ui_component`` and no ``Message.reply``,
and the ``on_message`` / ``on_chat_start`` slots are single-assignment: the
browser is therefore one message updated in place with ``cl.Action`` buttons
whose callbacks are registered at import time. These tests drive
:class:`app.ui.skills.SkillsUI` against a fake ``cl`` namespace (the
``_FakeCl`` pattern from ``test_chainlit_app``) and an
``httpx.MockTransport`` behind ``httpx.AsyncClient`` — no server, no
websocket, no Chainlit context.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from chainlit.config import config as cl_config

from app.core.config import clear_settings_cache
from app.ui import chainlit_app as ui
from app.ui import skills as skills_mod

# --- sandbox -----------------------------------------------------------------


@pytest.fixture(autouse=True)
def isolated(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """No inherited env, no repo .env, temp config + settings files."""
    for name in list(os.environ):
        if name.startswith("ORYA_") or name in {"DATABASE_URL", "LOG_LEVEL"}:
            monkeypatch.delenv(name, raising=False)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ORYA_CONFIG_PATH", str(tmp_path / "config.yaml"))
    monkeypatch.setenv("ORYA_UI_SETTINGS_PATH", str(tmp_path / "settings.json"))
    clear_settings_cache()
    # The module singleton would otherwise keep settings from an earlier test.
    monkeypatch.setattr(skills_mod, "_skills_ui", None)
    yield
    clear_settings_cache()


# --- fakes -------------------------------------------------------------------


class _SessionStore:
    """Stand-in for ``cl.user_session`` (a plain dict of values)."""

    def __init__(self) -> None:
        self.data: dict[str, Any] = {}

    def set(self, key: str, value: Any) -> None:
        self.data[key] = value

    def get(self, key: str, default: Any = None) -> Any:
        return self.data.get(key, default)


class _FakeMessage:
    def __init__(self, content: str = "", actions: Any = None) -> None:
        self.content = content
        self.actions = list(actions or [])
        self.sent = 0
        self.updated = 0
        self.removed_actions = 0

    async def send(self) -> None:
        self.sent += 1

    async def update(self) -> None:
        self.updated += 1

    async def remove_actions(self) -> None:
        # Mirrors chainlit: drops the sent buttons client-side, keeps
        # ``self.actions`` (the caller replaces the list right after).
        self.removed_actions += 1


class _FakeCl:
    """Minimal Chainlit namespace: messages, session store, action registry."""

    def __init__(self) -> None:
        self.user_session = _SessionStore()
        self.messages: list[_FakeMessage] = []
        self.errors: list[str] = []
        self.logger = SimpleNamespace(error=self._log_error)

    def _log_error(self, message: str, *_args: Any, **_kwargs: Any) -> None:
        self.errors.append(str(message))

    def Message(self, content: str = "", **kwargs: Any) -> _FakeMessage:  # noqa: N802
        message = _FakeMessage(content, actions=kwargs.get("actions"))
        self.messages.append(message)
        return message

    def Action(self, **kwargs: Any) -> Any:  # noqa: N802
        return SimpleNamespace(**kwargs)


@pytest.fixture
def fake_cl(monkeypatch: pytest.MonkeyPatch) -> _FakeCl:
    fake = _FakeCl()
    monkeypatch.setattr(skills_mod, "cl", fake)
    # ``chainlit_app._handle_skills`` sends its usage fallback through its
    # own ``cl`` import — the same namespace must be faked there too.
    monkeypatch.setattr(ui, "cl", fake)
    return fake


# --- skills API stub ---------------------------------------------------------


class _SkillsApi:
    """Stateful ``/skills`` endpoint behind ``httpx.MockTransport``."""

    def __init__(self, skills: list[dict] | None = None) -> None:
        self.skills = skills if skills is not None else [_skill("alpha")]
        self.requests: list[httpx.Request] = []
        self.fail = False

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.fail:
            return httpx.Response(503, json={"detail": "down"})
        path = request.url.path.rstrip("/")
        if request.method == "GET" and path == "/skills":
            return httpx.Response(200, json=self.skills)
        if request.method == "POST" and path == "/skills/activate":
            body = json.loads(request.content)
            for skill in self.skills:
                if skill["name"] == body["skill_name"]:
                    skill["is_active"] = bool(body["activate"])
            return httpx.Response(
                200,
                json={
                    "message": f"Skill {body['skill_name']} updated",
                    "skill_name": body["skill_name"],
                    "is_active": bool(body["activate"]),
                },
            )
        if request.method == "GET" and path.startswith("/skills/"):
            name = path.rsplit("/", 1)[-1]
            for skill in self.skills:
                if skill["name"] == name:
                    return httpx.Response(200, json=skill)
            return httpx.Response(404, json={"detail": "not found"})
        return httpx.Response(404, json={"detail": "unknown route"})

    def post_count(self) -> int:
        return sum(1 for r in self.requests if r.method == "POST")


def _skill(name: str, *, active: bool = False) -> dict[str, Any]:
    return {
        "name": name,
        "description": f"{name} description",
        "version": "1.0.0",
        "author": "orya",
        "category": "development",
        "is_active": active,
        "tags": ["test"],
        "tools": ["read"],
    }


def _patch_api(monkeypatch: pytest.MonkeyPatch, api: _SkillsApi) -> None:
    """Route every ``httpx.AsyncClient`` the skills module opens to ``api``."""
    transport = httpx.MockTransport(api)
    real_client = httpx.AsyncClient

    def factory(*args: Any, **kwargs: Any) -> httpx.AsyncClient:
        kwargs["transport"] = transport
        return real_client(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", factory)


# --- tests -------------------------------------------------------------------


async def test_browser_sends_one_message_with_refresh_and_toggle_actions(
    fake_cl: _FakeCl, monkeypatch: pytest.MonkeyPatch
) -> None:
    api = _SkillsApi([_skill("alpha", active=True), _skill("beta")])
    _patch_api(monkeypatch, api)

    await skills_mod.get_skills_ui().show_skills_browser()

    assert len(fake_cl.messages) == 1
    message = fake_cl.messages[0]
    assert message.sent == 1
    assert "## Skills Browser" in message.content
    assert "alpha" in message.content and "beta" in message.content
    # Refresh first, then one toggle per skill with the right payload.
    assert [a.name for a in message.actions] == [
        "refresh_skills",
        "deactivate_skill",
        "activate_skill",
    ]
    assert message.actions[1].payload == {"skill_name": "alpha"}
    assert message.actions[2].payload == {"skill_name": "beta"}
    # Fake links are gone — the list is markdown plus real buttons only.
    assert "[Activate]" not in message.content


async def test_browser_updates_in_place_on_repeat(
    fake_cl: _FakeCl, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_api(monkeypatch, _SkillsApi())
    ui_api = skills_mod.get_skills_ui()

    await ui_api.show_skills_browser()
    await ui_api.show_skills_browser()

    assert len(fake_cl.messages) == 1  # never stacks a second window
    message = fake_cl.messages[0]
    assert message.sent == 1
    assert message.updated == 1
    assert message.removed_actions == 1


async def test_browser_without_skills_renders_the_empty_state(
    fake_cl: _FakeCl, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_api(monkeypatch, _SkillsApi([]))

    await skills_mod.get_skills_ui().show_skills_browser()

    message = fake_cl.messages[0]
    assert "No skills found." in message.content
    assert [a.name for a in message.actions] == ["refresh_skills"]


async def test_activate_skill_posts_and_refreshes_the_open_browser(
    fake_cl: _FakeCl, monkeypatch: pytest.MonkeyPatch
) -> None:
    api = _SkillsApi([_skill("alpha")])
    _patch_api(monkeypatch, api)
    skills_ui = skills_mod.get_skills_ui()

    await skills_ui.show_skills_browser()
    await skills_ui.activate_skill("alpha")

    assert api.post_count() == 1
    post = next(r for r in api.requests if r.method == "POST")
    assert json.loads(post.content) == {"skill_name": "alpha", "activate": True}
    # Feedback message + the browser rewritten in place with the new state.
    assert len(fake_cl.messages) == 2
    assert "✅" in fake_cl.messages[1].content
    browser = fake_cl.messages[0]
    assert browser.updated == 1
    assert browser.actions[1].name == "deactivate_skill"  # now active


async def test_toggle_without_an_open_browser_only_sends_feedback(
    fake_cl: _FakeCl, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_api(monkeypatch, _SkillsApi([_skill("alpha")]))

    await skills_mod.get_skills_ui().deactivate_skill("alpha")

    assert len(fake_cl.messages) == 1
    assert "✅" in fake_cl.messages[0].content


async def test_toggle_failure_reports_an_error_message(
    fake_cl: _FakeCl, monkeypatch: pytest.MonkeyPatch
) -> None:
    api = _SkillsApi()
    api.fail = True
    _patch_api(monkeypatch, api)

    await skills_mod.get_skills_ui().activate_skill("alpha")

    assert len(fake_cl.messages) == 1
    assert "❌" in fake_cl.messages[0].content
    assert fake_cl.errors  # logged as well


async def test_show_skill_info_sends_the_detail_message(
    fake_cl: _FakeCl, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_api(monkeypatch, _SkillsApi([_skill("alpha")]))

    await skills_mod.get_skills_ui().show_skill_info("alpha")

    assert len(fake_cl.messages) == 1
    content = fake_cl.messages[0].content
    assert "## Skill: alpha" in content
    assert "**Category:** development" in content


async def test_refresh_action_callback_rewrites_the_browser(
    fake_cl: _FakeCl, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_api(monkeypatch, _SkillsApi())
    await skills_mod.get_skills_ui().show_skills_browser()

    await skills_mod._on_refresh_skills(SimpleNamespace(payload={}))

    assert len(fake_cl.messages) == 1
    assert fake_cl.messages[0].updated == 1


def test_handlers_are_registered_at_import_and_never_clobber_chat_slots() -> None:
    """Callbacks live in the import-time registry; no second on_message."""
    callbacks = cl_config.code.action_callbacks
    assert {"refresh_skills", "activate_skill", "deactivate_skill"} <= set(callbacks)
    for name in ("refresh_skills", "activate_skill", "deactivate_skill"):
        assert callable(callbacks[name])
    # Registering a handler from inside a function would overwrite the app's
    # single-slot chat handlers — the module must not define its own.
    assert not hasattr(skills_mod, "on_chat_start")
    assert not hasattr(skills_mod, "on_message")


async def test_handle_skills_routes_through_the_browser(
    fake_cl: _FakeCl, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``chainlit_app._handle_skills`` drives the rewritten SkillsUI API."""
    _patch_api(monkeypatch, _SkillsApi())

    await ui._handle_skills("/skills")

    assert len(fake_cl.messages) == 1
    assert "## Skills Browser" in fake_cl.messages[0].content


async def test_handle_skills_usage_fallback(
    fake_cl: _FakeCl, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_api(monkeypatch, _SkillsApi())

    await ui._handle_skills("/skills frobnicate")

    assert len(fake_cl.messages) == 1
    assert "Usage: /skills" in fake_cl.messages[0].content
