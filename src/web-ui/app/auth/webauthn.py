"""US-110: WebAuthn registration and authentication ceremony helpers.

Wraps py-webauthn for:
- Registration: option generation + attestation verification (T-110-03)
- Authentication: option generation + assertion verification (T-110-03)

Keeps challenge state in-memory (single-worker uvicorn).

Configuration via environment variables:
    PI4AUDIO_RP_ID      Relying Party ID (default: mugge.local)
    PI4AUDIO_RP_NAME    Relying Party display name (default: mugge)
    PI4AUDIO_RP_ORIGIN  Expected origin(s), comma-separated
                        (default: https://<RP_ID>:8080)
"""

from __future__ import annotations

import logging
import os
import time
from typing import Optional

from webauthn import (
    generate_authentication_options,
    generate_registration_options,
    options_to_json,
    verify_authentication_response,
    verify_registration_response,
)
from webauthn.helpers.structs import (
    AttestationConveyancePreference,
    AuthenticatorSelectionCriteria,
    PublicKeyCredentialDescriptor,
    ResidentKeyRequirement,
    UserVerificationRequirement,
)

log = logging.getLogger(__name__)

# ── Configuration ─────────────────────────────────────────────────────

RP_ID = os.environ.get("PI4AUDIO_RP_ID", "mugge.local")
RP_NAME = os.environ.get("PI4AUDIO_RP_NAME", "mugge")

def _get_expected_origins() -> list[str]:
    """Parse expected origins from env or derive from RP_ID."""
    raw = os.environ.get("PI4AUDIO_RP_ORIGIN", "")
    if raw:
        return [o.strip() for o in raw.split(",") if o.strip()]
    return [f"https://{RP_ID}:8080"]

EXPECTED_ORIGINS = _get_expected_origins()

# ── In-memory challenge store ─────────────────────────────────────────
# Challenges are short-lived (60s) and this is single-worker uvicorn,
# so in-memory storage is sufficient.  No DB persistence needed.

_challenges: dict[str, tuple[bytes, float]] = {}  # key -> (challenge, timestamp)
_CHALLENGE_TTL = 120  # seconds — generous to allow slow authenticators


def store_challenge(key: str, challenge: bytes) -> None:
    """Store a challenge for later verification."""
    _gc_challenges()
    _challenges[key] = (challenge, time.monotonic())


def get_challenge(key: str) -> Optional[bytes]:
    """Retrieve and consume a stored challenge.  Returns None if expired/missing."""
    entry = _challenges.pop(key, None)
    if entry is None:
        return None
    challenge, ts = entry
    if time.monotonic() - ts > _CHALLENGE_TTL:
        return None
    return challenge


def _gc_challenges() -> None:
    """Remove expired challenges to prevent memory leak."""
    now = time.monotonic()
    expired = [k for k, (_, ts) in _challenges.items()
               if now - ts > _CHALLENGE_TTL]
    for k in expired:
        del _challenges[k]


# ── Registration ──────────────────────────────────────────────────────

def make_registration_options(
    user_id: bytes,
    user_name: str,
    exclude_credential_ids: list[bytes] | None = None,
) -> str:
    """Generate WebAuthn registration options as JSON string.

    Returns the JSON string ready to send to the browser.
    The challenge is stored in-memory for verification.
    """
    exclude_credentials = None
    if exclude_credential_ids:
        exclude_credentials = [
            PublicKeyCredentialDescriptor(id=cid)
            for cid in exclude_credential_ids
        ]

    options = generate_registration_options(
        rp_id=RP_ID,
        rp_name=RP_NAME,
        user_name=user_name,
        user_id=user_id,
        attestation=AttestationConveyancePreference.NONE,
        authenticator_selection=AuthenticatorSelectionCriteria(
            resident_key=ResidentKeyRequirement.PREFERRED,
            user_verification=UserVerificationRequirement.PREFERRED,
        ),
        exclude_credentials=exclude_credentials,
        timeout=60000,
    )

    # Store challenge keyed by user_id hex for retrieval during verification.
    challenge_key = user_id.hex()
    store_challenge(challenge_key, options.challenge)

    return options_to_json(options)


def verify_registration(
    credential_json: str | dict,
    user_id: bytes,
) -> tuple[bytes, bytes, int]:
    """Verify a registration response from the browser.

    Args:
        credential_json: The credential response from navigator.credentials.create()
        user_id: The user_id used during registration option generation

    Returns:
        (credential_id, credential_public_key, sign_count)

    Raises:
        ValueError: If challenge is missing/expired or verification fails
    """
    challenge_key = user_id.hex()
    challenge = get_challenge(challenge_key)
    if challenge is None:
        raise ValueError("Registration challenge expired or not found")

    try:
        verification = verify_registration_response(
            credential=credential_json,
            expected_challenge=challenge,
            expected_rp_id=RP_ID,
            expected_origin=EXPECTED_ORIGINS,
            require_user_verification=False,
        )
    except Exception as exc:
        raise ValueError(f"Registration verification failed: {exc}") from exc

    return (
        verification.credential_id,
        verification.credential_public_key,
        verification.sign_count,
    )


# ── Authentication ───────────────────────────────────────────────────

_AUTH_CHALLENGE_KEY = "__auth__"


def make_authentication_options(
    credential_ids: list[bytes],
) -> str:
    """Generate WebAuthn authentication options as JSON string.

    Args:
        credential_ids: All registered credential IDs from the DB.
            Passed as allowCredentials so the authenticator knows which
            credentials to offer.  AC #6: no username field — passkeys
            self-identify via allowCredentials.

    Returns the JSON string ready to send to the browser.
    The challenge is stored in-memory for verification.
    """
    allow_credentials = [
        PublicKeyCredentialDescriptor(id=cid)
        for cid in credential_ids
    ] if credential_ids else None

    options = generate_authentication_options(
        rp_id=RP_ID,
        allow_credentials=allow_credentials,
        user_verification=UserVerificationRequirement.PREFERRED,
        timeout=60000,
    )

    store_challenge(_AUTH_CHALLENGE_KEY, options.challenge)

    return options_to_json(options)


def verify_authentication(
    credential_json: str | dict,
    credential_public_key: bytes,
    credential_current_sign_count: int,
) -> tuple[bytes, int]:
    """Verify an authentication response from the browser.

    Args:
        credential_json: The credential response from
            navigator.credentials.get()
        credential_public_key: The stored public key for this credential
        credential_current_sign_count: The stored sign count for this
            credential

    Returns:
        (credential_id, new_sign_count)

    Raises:
        ValueError: If challenge is missing/expired or verification fails
    """
    challenge = get_challenge(_AUTH_CHALLENGE_KEY)
    if challenge is None:
        raise ValueError("Authentication challenge expired or not found")

    try:
        verification = verify_authentication_response(
            credential=credential_json,
            expected_challenge=challenge,
            expected_rp_id=RP_ID,
            expected_origin=EXPECTED_ORIGINS,
            credential_public_key=credential_public_key,
            credential_current_sign_count=credential_current_sign_count,
            require_user_verification=False,
        )
    except Exception as exc:
        raise ValueError(f"Authentication verification failed: {exc}") from exc

    return (
        verification.credential_id,
        verification.new_sign_count,
    )
