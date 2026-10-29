"""Middleware: request-id, Bearer-JWT auth, CORS (A-00).

Pure-ASGI wrappers (not ``BaseHTTPMiddleware``) so the SSE endpoints
(`/sessions/{id}/messages?stream=true`) stream through unbuffered.
Settings are read per request via ``get_settings()`` — tests sandbox the
env, call ``clear_settings_cache()`` and get enforcement on/off without
rebuilding the app.

Registration order in ``install_middleware`` matters: Starlette's
``add_middleware`` makes the *last* added the outermost layer, so auth is
added first (innermost of the three), then CORS (preflights must bypass
auth), then request-id (outermost — it stamps even 401 rejections).
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import TYPE_CHECKING

from starlette.datastructures import Headers
from starlette.middleware.cors import CORSMiddleware
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.auth import AuthError, decode_token
from app.core.config import get_settings

if TYPE_CHECKING:  # pragma: no cover
    from fastapi import FastAPI

__all__ = [
    "AuthMiddleware",
    "RequestIdMiddleware",
    "SettingsCorsMiddleware",
    "install_middleware",
]

logger = logging.getLogger(__name__)


def _is_public(path: str, public_prefixes: list[str]) -> bool:
    """True for ``/health`` and children like ``/health/observability``."""
    for prefix in public_prefixes:
        if path == prefix or path.startswith(prefix.rstrip("/") + "/"):
            return True
    return False


def _bearer_token(headers: Headers) -> str | None:
    value = headers.get("authorization")
    if not value:
        return None
    scheme, _, token = value.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        return None
    return token.strip()


async def _reject(send: Send, detail: str) -> None:
    """Send a minimal 401 JSON body with ``WWW-Authenticate: Bearer``."""
    body = json.dumps({"detail": detail}).encode("utf-8")
    await send(
        {
            "type": "http.response.start",
            "status": 401,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode("latin-1")),
                (b"www-authenticate", b"Bearer"),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})


class RequestIdMiddleware:
    """Echo or mint ``X-Request-ID`` and expose it as ``request.state.request_id``."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        request_id = Headers(scope=scope).get("x-request-id") or uuid.uuid4().hex
        scope.setdefault("state", {})["request_id"] = request_id

        async def send_with_request_id(message: Message) -> None:
            if message["type"] == "http.response.start":
                message.setdefault("headers", []).append(
                    (b"x-request-id", request_id.encode("latin-1"))
                )
            await send(message)

        await self.app(scope, receive, send_with_request_id)


class AuthMiddleware:
    """Enforce ``Authorization: Bearer <JWT>`` unless the path is public (A-00).

    ``ORYA_AUTH_ENABLED=false`` (default) passes everything through. On
    success the ``sub`` claim lands in ``request.state.user_id`` for A-01's
    per-user rate limiter. The Chainlit UI does not send a bearer yet —
    enabling auth gates it out until the UI login flow lands (separate
    ticket); that is why the kill-switch defaults to off for dev.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        settings = get_settings()
        if not settings.auth_enabled:
            await self.app(scope, receive, send)
            return
        path = scope.get("path", "")
        # OPTIONS is CORS preflight — handled by the CORS layer above us.
        if scope.get("method") == "OPTIONS" or _is_public(
            path, settings.auth_public_path_list
        ):
            await self.app(scope, receive, send)
            return
        token = _bearer_token(Headers(scope=scope))
        if token is None:
            logger.debug("auth: no bearer token for %s", path)
            await _reject(send, "missing bearer token")
            return
        try:
            user_id = decode_token(token)
        except AuthError as exc:
            logger.debug("auth: rejected %s: %s", path, exc)
            await _reject(send, "invalid or expired token")
            return
        scope.setdefault("state", {})["user_id"] = user_id
        await self.app(scope, receive, send)


class SettingsCorsMiddleware:
    """CORSMiddleware with origins re-read whenever settings change.

    ``Starlette`` builds its middleware stack once per app; tests toggle
    ``ORYA_CORS_ORIGINS`` + ``clear_settings_cache()`` between cases, so the
    wrapper rebuilds the underlying CORSMiddleware only when the origin list
    actually differs.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app
        self._origins: tuple[str, ...] | None = None
        self._impl: CORSMiddleware | None = None

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        origins = tuple(get_settings().cors_origin_list)
        if self._impl is None or origins != self._origins:
            self._impl = CORSMiddleware(
                self.app,
                allow_origins=list(origins),
                allow_credentials=True,
                allow_methods=["*"],
                allow_headers=["*"],
            )
            self._origins = origins
        await self._impl(scope, receive, send)


def install_middleware(app: FastAPI) -> None:
    """Wire the A-00 middleware stack: auth, CORS, request-id."""
    app.add_middleware(AuthMiddleware)
    app.add_middleware(SettingsCorsMiddleware)
    app.add_middleware(RequestIdMiddleware)
