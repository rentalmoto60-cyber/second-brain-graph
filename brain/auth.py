"""HTTP Basic Auth + session cookie for the single-user backend.

Disabled automatically when APP_USERNAME or APP_PASSWORD_HASH is not set,
so dev and CI keep working without configuration.
"""
from __future__ import annotations

import base64
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Iterable

import bcrypt
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response


COOKIE_NAME = "session_token"
SESSION_TTL_DAYS = 30
REALM = "Second Brain"
BCRYPT_ROUNDS = 12
BCRYPT_MAX_PASSWORD_BYTES = 72


def hash_password(plain: str) -> str:
    """Return a bcrypt hash. Truncates inputs > 72 bytes (bcrypt limit)."""
    pw = plain.encode("utf-8")[:BCRYPT_MAX_PASSWORD_BYTES]
    return bcrypt.hashpw(pw, bcrypt.gensalt(BCRYPT_ROUNDS)).decode("ascii")


def verify_password(plain: str, hashed: str) -> bool:
    if not plain or not hashed:
        return False
    pw = plain.encode("utf-8")[:BCRYPT_MAX_PASSWORD_BYTES]
    try:
        return bcrypt.checkpw(pw, hashed.encode("ascii"))
    except (ValueError, TypeError):
        return False


def _check_basic_header(header: str, username: str, password_hash: str) -> bool:
    if not header or not header.lower().startswith("basic "):
        return False
    try:
        decoded = base64.b64decode(header[6:].strip(), validate=True).decode("utf-8")
    except (ValueError, UnicodeDecodeError):
        return False
    if ":" not in decoded:
        return False
    user, _, pw = decoded.partition(":")
    expected_user = username.encode("utf-8")
    user_bytes = user.encode("utf-8")
    user_ok = (
        len(user_bytes) == len(expected_user)
        and secrets.compare_digest(user_bytes, expected_user)
    )
    pw_ok = verify_password(pw, password_hash)
    return user_ok and pw_ok


class SessionStore:
    """In-memory token store. Rotates on restart — fine for a single-user app."""

    def __init__(self, ttl: timedelta = timedelta(days=SESSION_TTL_DAYS)) -> None:
        self._tokens: dict[str, datetime] = {}
        self._ttl = ttl

    def create(self) -> str:
        token = secrets.token_urlsafe(32)
        self._tokens[token] = datetime.now(timezone.utc) + self._ttl
        return token

    def is_valid(self, token: str | None) -> bool:
        if not token:
            return False
        expiry = self._tokens.get(token)
        if expiry is None:
            return False
        if datetime.now(timezone.utc) > expiry:
            self._tokens.pop(token, None)
            return False
        return True

    def force_expire(self, token: str) -> None:
        if token in self._tokens:
            self._tokens[token] = datetime.now(timezone.utc) - timedelta(seconds=1)


def credentials_from_env() -> tuple[str | None, str | None]:
    return os.environ.get("APP_USERNAME"), os.environ.get("APP_PASSWORD_HASH")


class BasicAuthMiddleware(BaseHTTPMiddleware):
    """Gate HTTP requests behind Basic Auth, then mint a session cookie.

    WebSocket upgrades bypass BaseHTTPMiddleware — auth for /ws is enforced
    inside the websocket handler.
    """

    def __init__(
        self,
        app,
        *,
        username: str,
        password_hash: str,
        sessions: SessionStore,
        exempt_paths: Iterable[str] = (),
    ) -> None:
        super().__init__(app)
        self.username = username
        self.password_hash = password_hash
        self.sessions = sessions
        self.exempt = set(exempt_paths)

    async def dispatch(self, request: Request, call_next):
        if request.url.path in self.exempt:
            return await call_next(request)

        cookie_token = request.cookies.get(COOKIE_NAME)
        if self.sessions.is_valid(cookie_token):
            return await call_next(request)

        auth_header = request.headers.get("authorization", "")
        if _check_basic_header(auth_header, self.username, self.password_hash):
            response = await call_next(request)
            token = self.sessions.create()
            response.set_cookie(
                COOKIE_NAME,
                token,
                httponly=True,
                secure=request.url.scheme == "https",
                samesite="strict",
                max_age=int(timedelta(days=SESSION_TTL_DAYS).total_seconds()),
                path="/",
            )
            return response

        return Response(
            content="Unauthorized",
            status_code=401,
            headers={"WWW-Authenticate": f'Basic realm="{REALM}"'},
        )


def websocket_authorized(websocket, sessions: SessionStore) -> bool:
    """Cookie check for WebSocket handshake."""
    return sessions.is_valid(websocket.cookies.get(COOKIE_NAME))
