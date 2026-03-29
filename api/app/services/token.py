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
import uuid
from datetime import UTC, datetime, timedelta

import jwt
from jwt.exceptions import PyJWTError as JWTError
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
    iat: int | None = None
    jti: str | None = None


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

    issued_at = datetime.now(UTC)
    expire = issued_at + expires_delta
    payload = {
        "sub": sub,
        "role": role,
        "iat": issued_at,
        "exp": expire,
        "jti": str(uuid.uuid4()),
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
        "iat": datetime.now(UTC),
        "jti": str(uuid.uuid4()),
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


# ───────────────────────────────────────────────────
# Per-device MQTT credentials
# ───────────────────────────────────────────────────

def generate_mqtt_credentials(device_id: str) -> tuple[str, str]:
    """Generate per-device MQTT username and password.

    Returns:
        (mqtt_username, mqtt_password_plaintext)
        Store hash_mqtt_password(mqtt_password_plaintext) in DB.
    """
    # Username: device_<device_id>
    mqtt_username = f"device_{device_id}"
    # Password: random 24-byte URL-safe string
    mqtt_password = secrets.token_urlsafe(24)
    return mqtt_username, mqtt_password


def hash_mqtt_password(password: str) -> str:
    """Hash MQTT password using bcrypt (same as user passwords)."""
    from app.services.passwords import hash_password
    return hash_password(password)


def verify_mqtt_password(password: str, hashed: str) -> bool:
    """Verify MQTT password using bcrypt."""
    from app.services.passwords import verify_password
    return verify_password(password, hashed)
