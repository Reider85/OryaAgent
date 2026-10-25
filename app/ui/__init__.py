"""UI components (M-15/M-16/M-17, M-24): Chainlit over the FastAPI SSE API."""

from app.ui.chainlit_app import (
    on_chat_start,
    on_message,
    on_new_session,
    on_settings_update,
    on_switch_session,
)
from app.ui.interrupt import ask_permission, get_pending_interrupt
from app.ui.sessions import SessionInfo, enrich_titles_from_db, list_sessions
from app.ui.settings import UISettings, load_settings, model_choices, save_settings

__all__ = [
    # Chainlit handlers
    "on_chat_start",
    "on_message",
    "on_settings_update",
    "on_new_session",
    "on_switch_session",
    # Interrupt
    "ask_permission",
    "get_pending_interrupt",
    # Sessions
    "SessionInfo",
    "list_sessions",
    "enrich_titles_from_db",
    # Settings
    "UISettings",
    "load_settings",
    "save_settings",
    "model_choices",
]
