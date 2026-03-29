"""US-110: SQLite credential, session, and invite storage.

Async SQLite via ``aiosqlite``.  Tables are auto-created on first
connection (schema migration: CREATE IF NOT EXISTS).

DB path from ``PI4AUDIO_AUTH_DB`` env var, default
``/var/lib/pi4audio/auth.db``.

Thread safety: aiosqlite runs SQLite on a dedicated background thread
with serialized access — safe for concurrent FastAPI requests.
"""

from __future__ import annotations

import logging
import os
import secrets
import time
from datetime import datetime, timezone
from typing import Optional

import aiosqlite

log = logging.getLogger(__name__)

DB_PATH = os.environ.get("PI4AUDIO_AUTH_DB", "/var/lib/pi4audio/auth.db")

_SCHEMA = """\
CREATE TABLE IF NOT EXISTS credentials (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         TEXT    NOT NULL,
    credential_id   BLOB   NOT NULL UNIQUE,
    public_key      BLOB   NOT NULL,
    sign_count      INTEGER NOT NULL DEFAULT 0,
    device_name     TEXT    NOT NULL DEFAULT '',
    created_at      TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE IF NOT EXISTS sessions (
    token           TEXT    PRIMARY KEY,
    credential_id   BLOB   NOT NULL,
    created_at      TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    last_active     TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE IF NOT EXISTS invites (
    token           TEXT    PRIMARY KEY,
    created_at      TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    expires_at      TEXT    NOT NULL,
    consumed        INTEGER NOT NULL DEFAULT 0
);
"""

# Module-level connection — opened lazily by get_db(), closed by close_db().
_db: Optional[aiosqlite.Connection] = None


async def get_db() -> aiosqlite.Connection:
    """Return the shared DB connection, opening it on first call.

    Auto-creates tables if they don't exist (schema migration).
    """
    global _db
    if _db is None:
        log.info("Opening auth DB at %s", DB_PATH)
        _db = await aiosqlite.connect(DB_PATH)
        _db.row_factory = aiosqlite.Row
        await _db.execute("PRAGMA journal_mode=WAL")
        await _db.execute("PRAGMA foreign_keys=ON")
        await _db.executescript(_SCHEMA)
        await _db.commit()
        log.info("Auth DB ready (tables ensured)")
    return _db


async def close_db() -> None:
    """Close the DB connection.  Safe to call if not open."""
    global _db
    if _db is not None:
        await _db.close()
        _db = None
        log.info("Auth DB closed")


# ── Credentials CRUD ─────────────────────────────────────────────────

async def add_credential(
    user_id: str,
    credential_id: bytes,
    public_key: bytes,
    sign_count: int = 0,
    device_name: str = "",
) -> int:
    """Store a new WebAuthn credential.  Returns the row id."""
    db = await get_db()
    cursor = await db.execute(
        "INSERT INTO credentials (user_id, credential_id, public_key, sign_count, device_name)"
        " VALUES (?, ?, ?, ?, ?)",
        (user_id, credential_id, public_key, sign_count, device_name),
    )
    await db.commit()
    return cursor.lastrowid


async def get_credential_by_id(credential_id: bytes) -> Optional[aiosqlite.Row]:
    """Look up a credential by its WebAuthn credential ID."""
    db = await get_db()
    cursor = await db.execute(
        "SELECT * FROM credentials WHERE credential_id = ?",
        (credential_id,),
    )
    return await cursor.fetchone()


async def get_credentials_for_user(user_id: str) -> list[aiosqlite.Row]:
    """Return all credentials registered for a user."""
    db = await get_db()
    cursor = await db.execute(
        "SELECT * FROM credentials WHERE user_id = ? ORDER BY created_at",
        (user_id,),
    )
    return await cursor.fetchall()


async def get_all_credentials() -> list[aiosqlite.Row]:
    """Return all stored credentials (for allowCredentials list)."""
    db = await get_db()
    cursor = await db.execute(
        "SELECT * FROM credentials ORDER BY created_at",
    )
    return await cursor.fetchall()


async def update_sign_count(credential_id: bytes, new_count: int) -> None:
    """Update the sign count after a successful authentication."""
    db = await get_db()
    await db.execute(
        "UPDATE credentials SET sign_count = ? WHERE credential_id = ?",
        (new_count, credential_id),
    )
    await db.commit()


async def delete_credential(credential_id: bytes) -> bool:
    """Delete a credential.  Returns True if a row was deleted."""
    db = await get_db()
    cursor = await db.execute(
        "DELETE FROM credentials WHERE credential_id = ?",
        (credential_id,),
    )
    await db.commit()
    return cursor.rowcount > 0


# ── Sessions CRUD ────────────────────────────────────────────────────

async def create_session(credential_id: bytes) -> str:
    """Create a new session token for an authenticated credential."""
    token = secrets.token_urlsafe(32)
    db = await get_db()
    await db.execute(
        "INSERT INTO sessions (token, credential_id) VALUES (?, ?)",
        (token, credential_id),
    )
    await db.commit()
    return token


async def get_session(token: str) -> Optional[aiosqlite.Row]:
    """Look up a session by token.  Returns None if not found."""
    db = await get_db()
    cursor = await db.execute(
        "SELECT * FROM sessions WHERE token = ?",
        (token,),
    )
    return await cursor.fetchone()


async def touch_session(token: str) -> None:
    """Update last_active timestamp for a session."""
    db = await get_db()
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    await db.execute(
        "UPDATE sessions SET last_active = ? WHERE token = ?",
        (now, token),
    )
    await db.commit()


async def delete_session(token: str) -> bool:
    """Delete a session (logout).  Returns True if a row was deleted."""
    db = await get_db()
    cursor = await db.execute(
        "DELETE FROM sessions WHERE token = ?",
        (token,),
    )
    await db.commit()
    return cursor.rowcount > 0


async def delete_sessions_for_credential(credential_id: bytes) -> int:
    """Delete all sessions for a credential.  Returns count deleted."""
    db = await get_db()
    cursor = await db.execute(
        "DELETE FROM sessions WHERE credential_id = ?",
        (credential_id,),
    )
    await db.commit()
    return cursor.rowcount


async def cleanup_expired_sessions(max_age_seconds: int = 86400 * 30) -> int:
    """Delete sessions inactive for longer than max_age_seconds.

    Default: 30 days.  Returns count deleted.
    """
    db = await get_db()
    cutoff = datetime.fromtimestamp(
        time.time() - max_age_seconds, tz=timezone.utc
    ).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    cursor = await db.execute(
        "DELETE FROM sessions WHERE last_active < ?",
        (cutoff,),
    )
    await db.commit()
    return cursor.rowcount


# ── Invites CRUD ─────────────────────────────────────────────────────

async def create_invite(expires_in_seconds: int = 3600) -> str:
    """Create a new invite token.  Default expiry: 1 hour.

    Uses secrets.token_urlsafe(32) for 256 bits of entropy.
    """
    token = secrets.token_urlsafe(32)
    expires_at = datetime.fromtimestamp(
        time.time() + expires_in_seconds, tz=timezone.utc
    ).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    db = await get_db()
    await db.execute(
        "INSERT INTO invites (token, expires_at) VALUES (?, ?)",
        (token, expires_at),
    )
    await db.commit()
    return token


async def consume_invite(token: str) -> bool:
    """Mark an invite as consumed.  Returns True if valid and consumed.

    An invite is valid if it exists, has not expired, and has not been
    consumed yet.
    """
    db = await get_db()
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    cursor = await db.execute(
        "UPDATE invites SET consumed = 1"
        " WHERE token = ? AND consumed = 0 AND expires_at > ?",
        (token, now),
    )
    await db.commit()
    return cursor.rowcount > 0


async def get_invite(token: str) -> Optional[aiosqlite.Row]:
    """Look up an invite by token."""
    db = await get_db()
    cursor = await db.execute(
        "SELECT * FROM invites WHERE token = ?",
        (token,),
    )
    return await cursor.fetchone()


async def cleanup_expired_invites() -> int:
    """Delete expired or consumed invites.  Returns count deleted."""
    db = await get_db()
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    cursor = await db.execute(
        "DELETE FROM invites WHERE consumed = 1 OR expires_at < ?",
        (now,),
    )
    await db.commit()
    return cursor.rowcount
