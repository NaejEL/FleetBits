"""Reusable FastAPI dependencies for authentication and authorization."""

from fastapi import Depends, HTTPException, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models.device import Device
from app.services.token import TokenPayload, decode_token, hash_token

_bearer = HTTPBearer(auto_error=True)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Security(_bearer),
) -> TokenPayload:
    try:
        return decode_token(credentials.credentials)
    except JWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


def require_roles(*roles: str):
    """Dependency factory: raise 403 if the current user's role is not in `roles`."""

    async def _check(user: TokenPayload = Depends(get_current_user)) -> TokenPayload:
        if user.role not in roles:
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
