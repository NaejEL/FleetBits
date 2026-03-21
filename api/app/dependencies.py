"""Reusable FastAPI dependencies for authentication and authorization."""

from datetime import UTC, datetime

from fastapi import Depends, HTTPException, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models.api_key import ApiKey
from app.models.device import Device
from app.services.token import TokenPayload, decode_token, hash_token

_bearer = HTTPBearer(auto_error=True)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Security(_bearer),
    db: AsyncSession = Depends(get_db),
) -> TokenPayload:
    """Authenticate a human user: tries JWT first, then opaque API key."""
    raw = credentials.credentials

    # ── Try as JWT ──────────────────────────────────────────────────────
    try:
        return decode_token(raw)
    except JWTError:
        pass  # may be an opaque API key — fall through

    # ── Try as opaque API key ───────────────────────────────────────────
    token_hash = hash_token(raw)
    result = await db.execute(select(ApiKey).where(ApiKey.token_hash == token_hash))
    api_key: ApiKey | None = result.scalar_one_or_none()

    if (
        api_key is not None
        and api_key.is_active
        and (api_key.expires_at is None or api_key.expires_at > datetime.now(UTC))
    ):
        # Track last-used without blocking the request
        api_key.last_used_at = datetime.now(UTC)
        return TokenPayload(
            sub=api_key.key_name,
            role=api_key.role,
            site_scope=api_key.site_scope,
            exp=int(api_key.expires_at.timestamp()) if api_key.expires_at else 9999999999,
        )

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired token",
        headers={"WWW-Authenticate": "Bearer"},
    )


def require_roles(*roles: str):
    """Dependency factory: raise 403 if the current user's role is not in `roles`.

    The 'admin' role always passes regardless of which roles are listed.
    """
    allowed = frozenset(roles) | {"admin"}

    async def _check(user: TokenPayload = Depends(get_current_user)) -> TokenPayload:
        if user.role not in allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient role"
            )
        return user

    return _check


async def get_device_from_bearer(
    credentials: HTTPAuthorizationCredentials = Security(_bearer),
    db: AsyncSession = Depends(get_db),
) -> Device:
    """Authenticate a device using its long-lived opaque bearer token.

    The token value is never stored — only its SHA-256 hex digest lives in device.device_token_hash.
    """
    token_hash = hash_token(credentials.credentials)
    result = await db.execute(select(Device).where(Device.device_token_hash == token_hash))
    device = result.scalar_one_or_none()
    if device is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid device token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return device
