"""US-110 T-110-05: Auth routes — registration, login, logout endpoints.

FastAPI router mounted at ``/auth/api``.  All endpoints in this router
are exempt from AuthMiddleware (listed in middleware._EXEMPT_PREFIXES).

Endpoints:
    POST /auth/api/register/options  — WebAuthn registration options
    POST /auth/api/register/verify   — verify attestation + store credential
    POST /auth/api/login/options     — WebAuthn authentication options
    POST /auth/api/login/verify      — verify assertion + issue session
    POST /auth/api/logout            — revoke session
"""

from __future__ import annotations

import json
import logging
import os

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from . import models
from . import webauthn
from .middleware import COOKIE_NAME, SESSION_MAX_INACTIVE_S

log = logging.getLogger(__name__)

router = APIRouter(prefix="/auth/api")


def _set_session_cookie(response: JSONResponse, token: str) -> None:
    """Set the session cookie with proper security flags (AC #7)."""
    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        httponly=True,
        secure=True,
        samesite="strict",
        path="/",
        max_age=SESSION_MAX_INACTIVE_S,
    )


def _clear_session_cookie(response: JSONResponse) -> None:
    """Clear the session cookie."""
    response.delete_cookie(
        key=COOKIE_NAME,
        path="/",
        secure=True,
        httponly=True,
        samesite="strict",
    )


# ── Registration ─────────────────────────────────────────────────────

@router.post("/register/options")
async def register_options(request: Request):
    """Generate WebAuthn registration options (AC #3, AC #4).

    Requires a valid invite token.  The invite is consumed immediately
    so it cannot be reused (AC #4: no open registration window).
    """
    body = await request.json()
    invite_token = body.get("invite_token", "")
    device_name = body.get("device_name", "")

    if not invite_token:
        return JSONResponse(
            {"error": "invite_token is required"},
            status_code=400,
        )

    # Consume invite atomically — returns False if invalid/expired/already used.
    valid = await models.consume_invite(invite_token)
    if not valid:
        return JSONResponse(
            {"error": "Invalid or expired invite token"},
            status_code=400,
        )

    # Generate a random user_id for this registration.
    user_id = os.urandom(16)
    user_name = device_name or "device"

    # Get existing credential IDs to exclude (prevent re-registration).
    all_creds = await models.get_all_credentials()
    exclude_ids = [cred["credential_id"] for cred in all_creds]

    options_json = webauthn.make_registration_options(
        user_id=user_id,
        user_name=user_name,
        exclude_credential_ids=exclude_ids or None,
    )

    # Return options + user_id hex so the browser can send it back
    # in the verify step.  The challenge is stored server-side keyed
    # by user_id hex.
    return JSONResponse({
        "options": json.loads(options_json),
        "user_id": user_id.hex(),
        "device_name": device_name,
    })


@router.post("/register/verify")
async def register_verify(request: Request):
    """Verify WebAuthn registration and store credential (AC #3).

    On success: stores credential, creates session, sets cookie.
    """
    body = await request.json()
    credential = body.get("credential")
    user_id_hex = body.get("user_id", "")
    device_name = body.get("device_name", "")

    if not credential or not user_id_hex:
        return JSONResponse(
            {"error": "credential and user_id are required"},
            status_code=400,
        )

    try:
        user_id = bytes.fromhex(user_id_hex)
    except ValueError:
        return JSONResponse(
            {"error": "Invalid user_id format"},
            status_code=400,
        )

    try:
        credential_id, public_key, sign_count = webauthn.verify_registration(
            credential_json=credential,
            user_id=user_id,
        )
    except ValueError as exc:
        log.warning("Registration verification failed: %s", exc)
        return JSONResponse(
            {"error": str(exc)},
            status_code=400,
        )

    # Store credential in DB.
    await models.add_credential(
        user_id=user_id_hex,
        credential_id=credential_id,
        public_key=public_key,
        sign_count=sign_count,
        device_name=device_name,
    )

    # Create session (AC #7).
    token = await models.create_session(credential_id)

    response = JSONResponse({"ok": True})
    _set_session_cookie(response, token)
    return response


# ── Login ────────────────────────────────────────────────────────────

@router.post("/login/options")
async def login_options():
    """Generate WebAuthn authentication options (AC #6).

    No username field — passkeys self-identify via allowCredentials.
    """
    creds = await models.get_all_credentials()
    credential_ids = [cred["credential_id"] for cred in creds]

    options_json = webauthn.make_authentication_options(credential_ids)

    return JSONResponse({
        "options": json.loads(options_json),
    })


@router.post("/login/verify")
async def login_verify(request: Request):
    """Verify WebAuthn authentication assertion (AC #6, AC #7).

    On success: creates NEW session (session fixation prevention),
    sets cookie, updates sign count.
    """
    body = await request.json()
    credential = body.get("credential")

    if not credential:
        return JSONResponse(
            {"error": "credential is required"},
            status_code=400,
        )

    # Extract credential ID from the response to look up the stored key.
    raw_id = credential.get("rawId") or credential.get("id", "")
    if not raw_id:
        return JSONResponse(
            {"error": "credential.rawId or credential.id is required"},
            status_code=400,
        )

    # rawId is base64url-encoded by the browser.
    import base64
    try:
        credential_id = base64.urlsafe_b64decode(raw_id + "==")
    except Exception:
        return JSONResponse(
            {"error": "Invalid credential ID encoding"},
            status_code=400,
        )

    # Look up stored credential.
    stored = await models.get_credential_by_id(credential_id)
    if stored is None:
        return JSONResponse(
            {"error": "Unknown credential"},
            status_code=400,
        )

    try:
        verified_id, new_sign_count = webauthn.verify_authentication(
            credential_json=credential,
            credential_public_key=bytes(stored["public_key"]),
            credential_current_sign_count=stored["sign_count"],
        )
    except ValueError as exc:
        log.warning("Authentication verification failed: %s", exc)
        return JSONResponse(
            {"error": str(exc)},
            status_code=400,
        )

    # Update sign count.
    await models.update_sign_count(credential_id, new_sign_count)

    # AC #7: Generate NEW session token (prevents session fixation).
    # Delete any existing session from cookie first.
    old_token = request.cookies.get(COOKIE_NAME)
    if old_token:
        await models.delete_session(old_token)

    token = await models.create_session(credential_id)

    response = JSONResponse({"ok": True})
    _set_session_cookie(response, token)
    return response


# ── Logout ───────────────────────────────────────────────────────────

@router.post("/logout")
async def logout(request: Request):
    """Sign out — revoke session server-side (AC #8)."""
    token = request.cookies.get(COOKIE_NAME)
    if token:
        await models.delete_session(token)

    response = JSONResponse({"ok": True})
    _clear_session_cookie(response)
    return response
