"""
Device and operator token utilities.

Three token kinds:
- Operator/CI JWT  — HS256, carries role + site_scope claim
- Provision JWT    — HS256, short-lived, carries allowed_device_ids + "provision" role
- Device token     — opaque random string; SHA-256 hash stored in ProvisionToken table
                     (devices authenticate heartbeats with this token)
"""

import hashlib
import secrets
from datetime import UTC, datetime, timedelta

from jose import JWTError, jwt
from pydantic import BaseModel

from app.config import settings

_ALGORITHM = settings.FLEET_JWT_ALGORITHM
_SECRET = settings.FLEET_JWT_SECRET


# ───────────────────────────────────────────────────
# Payload model shared by operator + provision tokens
# ───────────────────────────────────────────────────

class TokenPayload(BaseModel):
    sub: str
    role: str
    site_scope: str | None = None          # non-null for site_manager role
    allowed_device_ids: list[str] | None = None  # non-null for provision tokens
    exp: int


# ───────────────────────────────────────────────────
# Operator / CI token
# ───────────────────────────────────────────────────

def create_operator_token(
    sub: str,
    role: str,
    site_scope: str | None = None,
    expires_delta: timedelta | None = None,
) -> str:
    """Issue a signed JWT for a human operator, site manager, or CI bot."""
    if expires_delta is None:
        expires_delta = timedelta(minutes=settings.FLEET_JWT_EXPIRE_MINUTES)

    expire = datetime.now(UTC) + expires_delta
    payload = {
        "sub": sub,
        "role": role,
        "exp": expire,
    }
    if site_scope is not None:
        payload["site_scope"] = site_scope

    return jwt.encode(payload, _SECRET, algorithm=_ALGORITHM)


def decode_token(token: str) -> TokenPayload:
    """Decode and validate a JWT. Raises jose.JWTError on failure."""
    data = jwt.decode(token, _SECRET, algorithms=[_ALGORITHM])
    return TokenPayload(**data)


# ───────────────────────────────────────────────────
# Provision token (technician single-use)
# ───────────────────────────────────────────────────

def create_provision_token(
    created_by: str,
    allowed_device_ids: list[str],
    ttl_hours: int = 72,
) -> tuple[str, datetime]:
    """Create a short-lived provision JWT.

    Returns:
        (raw_token, expires_at) — store hash_token(raw_token) in DB, not the raw token.
    """
    expires_at = datetime.now(UTC) + timedelta(hours=ttl_hours)
    payload = {
        "sub": created_by,
        "role": "technician",
        "allowed_device_ids": allowed_device_ids,
        "exp": expires_at,
    }
    raw = jwt.encode(payload, _SECRET, algorithm=_ALGORITHM)
    return raw, expires_at


def decode_provision_token(token: str) -> TokenPayload:
    """Decode a provision JWT. Raises JWTError if expired or invalid."""
    data = jwt.decode(token, _SECRET, algorithms=[_ALGORITHM])
    if data.get("role") != "technician":
        raise JWTError("Not a provision token")
    return TokenPayload(**data)


# ───────────────────────────────────────────────────
# Opaque device token (heartbeat authentication)
# ───────────────────────────────────────────────────

def generate_device_token() -> str:
    """Generate a cryptographically random opaque token for a device.

    The token is URL-safe base64, 48 bytes = 64-character string.
    Only the SHA-256 hash is stored in the database.
    """
    return secrets.token_urlsafe(48)


def hash_token(raw_token: str) -> str:
    """Return SHA-256 hex digest of a raw token for safe storage."""
    return hashlib.sha256(raw_token.encode()).hexdigest()
