"""Auth: stateless JWT issuance/verification (A-00).

Single seam for the FastAPI auth middleware — encode/decode HS256 tokens
signed with ``settings.auth_secret_key``. No user store: the token's ``sub``
claim *is* the identity (``request.state.user_id``), which A-01's rate
limiter consumes.

Settings are read through ``get_settings()`` inside each call — never bind
an instance at import time (tests sandbox the env and call
``clear_settings_cache()``).
"""

from __future__ import annotations

import time

import jwt

from app.core.config import Settings, get_settings

__all__ = ["AuthError", "create_token", "decode_token"]


class AuthError(Exception):
    """Token rejected: missing secret, malformed, expired or wrong signature."""


def create_token(user_id: str, *, ttl_s: int | None = None) -> str:
    """Mint a signed JWT for ``user_id`` (A-00).

    TTL defaults to ``settings.auth_token_ttl_s``; ``sub``/``iat``/``exp``
    claims are always present. Raises :class:`AuthError` when no secret is
    configured.
    """
    settings = get_settings()
    secret = _secret(settings)
    ttl = ttl_s if ttl_s is not None else settings.auth_token_ttl_s
    now = int(time.time())
    payload = {"sub": user_id, "iat": now, "exp": now + ttl}
    try:
        return jwt.encode(payload, secret, algorithm=settings.auth_algorithm)
    except Exception as exc:  # pragma: no cover - defensive
        raise AuthError(f"token signing failed: {exc}") from exc


def decode_token(token: str) -> str:
    """Verify ``token`` and return its ``sub`` claim (A-00).

    Raises :class:`AuthError` on any failure — expired, tampered, signed
    with another secret, or carrying no ``sub``.
    """
    settings = get_settings()
    secret = _secret(settings)
    try:
        claims = jwt.decode(token, secret, algorithms=[settings.auth_algorithm])
    except jwt.PyJWTError as exc:
        raise AuthError(str(exc)) from exc
    sub = claims.get("sub")
    if not sub:
        raise AuthError("token has no sub claim")
    return str(sub)


def _secret(settings: Settings) -> str:
    secret = settings.auth_secret_key
    if secret is None or not secret.get_secret_value():
        raise AuthError("AUTH_SECRET_KEY is not configured (required to verify JWTs)")
    return secret.get_secret_value()
