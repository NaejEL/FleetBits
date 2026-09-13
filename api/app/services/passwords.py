"""Password hashing and verification using bcrypt directly (no passlib).

We pre-hash with SHA-256 + base64 before bcrypt so that passwords longer
than bcrypt's 72-byte limit are handled safely.  This is the same approach
used by Django's BCryptSHA256PasswordHasher.
"""

import base64
import hashlib

import bcrypt

_ROUNDS = 12


def _adapt(password: str) -> bytes:
    """SHA-256 prehash → base64 → bytes, always < 72 bytes for bcrypt."""
    digest = hashlib.sha256(password.encode("utf-8")).digest()
    return base64.b64encode(digest)


def hash_password(password: str) -> str:
    """Return a bcrypt hash string suitable for storage."""
    return bcrypt.hashpw(_adapt(password), bcrypt.gensalt(_ROUNDS)).decode("utf-8")


def verify_password(password: str, hashed: str) -> bool:
    """Return True if *password* matches the stored bcrypt *hashed* string."""
    try:
        return bcrypt.checkpw(_adapt(password), hashed.encode("utf-8"))
    except Exception:
        return False
