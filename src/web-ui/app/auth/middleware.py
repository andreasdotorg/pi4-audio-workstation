"""US-110 T-110-04: Auth middleware — session cookie validation.

Protects all HTTP and WebSocket endpoints except exempt paths.
Localhost bypass for kiosk mode (AC #11).

Integration: add ``app.add_middleware(AuthMiddleware)`` in main.py
AFTER the recovery_guard middleware (recovery runs first, auth second).
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import RedirectResponse, Response
from starlette.websockets import WebSocket

from . import models

log = logging.getLogger(__name__)

COOKIE_NAME = "__Host-pi4audio_session"
SESSION_MAX_INACTIVE_S = 43200  # 12 hours (AC #7)

# Paths exempt from authentication (AC #14).
# Static assets, login/registration pages, and auth API endpoints.
_EXEMPT_PREFIXES = (
    "/auth/login",
    "/auth/register",
    "/auth/api/",
    "/static/",
    "/favicon.ico",
)

# Exact exempt paths (not prefix-matched).
_EXEMPT_EXACT = {
    "/auth/login",
    "/auth/register",
}

_LOCALHOST_ADDRS = {"127.0.0.1", "::1"}


def _is_exempt(path: str) -> bool:
    """Check if a request path is exempt from authentication."""
    for prefix in _EXEMPT_PREFIXES:
        if path.startswith(prefix):
            return True
    # Source map stubs.
    if path.endswith(".map") and path.startswith("/static/"):
        return True
    return False


def _is_localhost(request: Request) -> bool:
    """Check if the request originates from localhost (AC #11).

    Uses the actual TCP peer address — NEVER X-Forwarded-For (AC #11).
    """
    client = request.client
    if client is None:
        return False
    return client.host in _LOCALHOST_ADDRS


async def _validate_session(token: str) -> bool:
    """Validate a session token: exists and not expired (12h sliding window).

    On valid session, touches last_active to extend the sliding window.
    Returns True if the session is valid.
    """
    session = await models.get_session(token)
    if session is None:
        return False

    # Check 12-hour sliding window expiry (AC #7).
    last_active_str = session["last_active"]
    try:
        last_active = datetime.fromisoformat(last_active_str.replace("Z", "+00:00"))
        elapsed = time.time() - last_active.timestamp()
        if elapsed > SESSION_MAX_INACTIVE_S:
            # Expired — clean up.
            await models.delete_session(token)
            return False
    except (ValueError, AttributeError):
        # Malformed timestamp — treat as expired.
        await models.delete_session(token)
        return False

    # Touch session to extend sliding window.
    await models.touch_session(token)
    return True


class AuthMiddleware(BaseHTTPMiddleware):
    """Session cookie validation middleware (US-110 AC #6, #7, #9, #11, #13, #14).

    - Localhost requests bypass auth entirely (AC #11)
    - Exempt paths (static, login, register, auth API) pass through (AC #14)
    - WebSocket upgrade requests: validate cookie, return 403 if invalid (AC #9)
    - HTTP requests: validate cookie, redirect to /auth/login if invalid (AC #6)
    """

    async def dispatch(self, request: Request, call_next):
        # AC #11: Localhost bypass.
        if _is_localhost(request):
            return await call_next(request)

        path = request.url.path

        # AC #14: Exempt paths.
        if _is_exempt(path):
            return await call_next(request)

        # Extract session cookie.
        token = request.cookies.get(COOKIE_NAME)

        # AC #9: WebSocket upgrade — validate before accept.
        # Starlette's BaseHTTPMiddleware doesn't intercept WebSocket
        # connections directly. WebSocket auth is handled by the
        # ws_auth_guard() helper called from each WS endpoint.
        # This middleware handles HTTP requests only.

        if token and await _validate_session(token):
            return await call_next(request)

        # Not authenticated — redirect to login (AC #6).
        next_url = str(request.url.path)
        if request.url.query:
            next_url += f"?{request.url.query}"

        return RedirectResponse(
            url=f"/auth/login?next={next_url}",
            status_code=303,
        )


async def ws_auth_guard(ws: WebSocket) -> bool:
    """Validate WebSocket authentication before accept (AC #9).

    Call this at the start of every WebSocket endpoint handler, BEFORE
    calling ``ws.accept()``.  Returns True if authenticated (proceed
    with accept), False if rejected (connection already closed with 4003).

    Usage::

        @app.websocket("/ws/foo")
        async def ws_foo(ws: WebSocket):
            if not await ws_auth_guard(ws):
                return
            await ws.accept()
            ...
    """
    # AC #11: Localhost bypass.
    client = ws.client
    if client is not None and client.host in _LOCALHOST_ADDRS:
        return True

    # Extract session cookie from the upgrade request headers.
    token = ws.cookies.get(COOKIE_NAME)
    if token and await _validate_session(token):
        return True

    # Reject: close with 4003 (AC #9).
    await ws.close(code=4003, reason="Authentication required")
    return False
