"""
Operator authentication and user management.

POST /api/v1/auth/login                        — exchange username + password for a signed JWT
GET  /api/v1/auth/users/me                     — current user info
POST /api/v1/auth/change-password              — self: change own password
POST /api/v1/auth/users                        — admin: create user
GET  /api/v1/auth/users                        — admin: list all users
PATCH /api/v1/auth/users/{user_id}             — admin: update role / site_scope / is_active / email
POST /api/v1/auth/users/{user_id}/reset-password — admin: set new password without knowing old
"""

import secrets
import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import get_db
from app.dependencies import get_current_user, require_roles
from app.models.api_key import ApiKey
from app.models.user import User
from app.schemas.user import (
    AdminPasswordReset,
    ApiKeyCreate,
    ApiKeyCreated,
    ApiKeyRead,
    PasswordChange,
    UserCreate,
    UserRead,
    UserUpdate,
)
from app.services.audit import write_audit_event
from app.services.passwords import hash_password, verify_password
from app.services.token import TokenPayload, create_operator_token, hash_token

router = APIRouter(prefix="/auth", tags=["auth"])


# ──────────────────────────────────────────────────────────────────
# Login
# ──────────────────────────────────────────────────────────────────

class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int  # seconds


@router.post("/login", response_model=TokenResponse)
async def login(
    body: LoginRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> TokenResponse:
    """Validate credentials and return a signed JWT."""
    result = await db.execute(select(User).where(User.username == body.username))
    user: User | None = result.scalar_one_or_none()

    # Always run bcrypt verify to prevent user-enumeration via timing side-channel.
    # When user doesn't exist we verify against a dummy hash (same cost, doomed to fail).
    # Verify against dummy hash when user not found to prevent timing-based user enumeration
    _DUMMY_HASH = "$2b$12$KIXxRn5HoO/8HmPOj7sGaeJhH/ylbRnzFSInMBpGmJd7WUjZFJgZi"  # noqa: S105
    candidate_hash = user.password_hash if user else _DUMMY_HASH
    password_ok = verify_password(body.password, candidate_hash)

    if not user or not user.is_active or not password_ok:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
        )

    token = create_operator_token(
        sub=user.username,
        role=user.role,
        site_scope=user.site_scope,
    )

    await write_audit_event(
        db,
        action="auth.login",
        actor=user.username,
        actor_role=user.role,
        target={"type": "user", "id": user.user_id},
        ip_address=request.client.host if request.client else None,
    )

    return TokenResponse(
        access_token=token,
        expires_in=settings.FLEET_JWT_EXPIRE_MINUTES * 60,
    )


# ──────────────────────────────────────────────────────────────────
# Self — current user info + password change
# ──────────────────────────────────────────────────────────────────

@router.get("/users/me", response_model=UserRead)
async def get_me(
    db: AsyncSession = Depends(get_db),
    current_user: TokenPayload = Depends(get_current_user),
) -> UserRead:
    result = await db.execute(select(User).where(User.username == current_user.sub))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    return user


@router.post("/change-password", status_code=status.HTTP_204_NO_CONTENT)
async def change_own_password(
    body: PasswordChange,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: TokenPayload = Depends(get_current_user),
) -> None:
    result = await db.execute(select(User).where(User.username == current_user.sub))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")

    if not verify_password(body.current_password, user.password_hash):
        raise HTTPException(status_code=400, detail="Current password is incorrect")

    user.password_hash = hash_password(body.new_password)
    user.updated_at = datetime.now(UTC)

    await write_audit_event(
        db,
        action="auth.password_changed",
        actor=current_user.sub,
        actor_role=current_user.role,
        target={"type": "user", "id": user.user_id},
        ip_address=request.client.host if request.client else None,
    )


# ──────────────────────────────────────────────────────────────────
# User management — admin only
# ──────────────────────────────────────────────────────────────────

@router.get("/users", response_model=list[UserRead])
async def list_users(
    db: AsyncSession = Depends(get_db),
    _admin: TokenPayload = Depends(require_roles("admin")),
) -> list[UserRead]:
    result = await db.execute(select(User).order_by(User.created_at))
    return list(result.scalars().all())


@router.post("/users", response_model=UserRead, status_code=status.HTTP_201_CREATED)
async def create_user(
    body: UserCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: TokenPayload = Depends(require_roles("admin")),
) -> UserRead:
    existing = await db.scalar(
        select(func.count()).select_from(User).where(User.username == body.username)
    )
    if existing:
        raise HTTPException(status_code=409, detail="Username already taken")

    user = User(
        user_id=str(uuid.uuid4()),
        username=body.username,
        email=body.email,
        password_hash=hash_password(body.password),
        role=body.role,
        site_scope=body.site_scope,
        is_active=True,
    )
    db.add(user)
    await db.flush()

    await write_audit_event(
        db,
        action="auth.user_created",
        actor=admin.sub,
        actor_role=admin.role,
        target={"type": "user", "id": user.user_id, "username": user.username},
        payload={"role": user.role},
        ip_address=request.client.host if request.client else None,
    )
    return user


@router.patch("/users/{user_id}", response_model=UserRead)
async def update_user(
    user_id: str,
    body: UserUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: TokenPayload = Depends(require_roles("admin")),
) -> UserRead:
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")

    changes: dict = {}
    for field, value in body.model_dump(exclude_none=True).items():
        setattr(user, field, value)
        changes[field] = value

    if changes:
        user.updated_at = datetime.now(UTC)

    await write_audit_event(
        db,
        action="auth.user_updated",
        actor=admin.sub,
        actor_role=admin.role,
        target={"type": "user", "id": user_id},
        payload=changes,
        ip_address=request.client.host if request.client else None,
    )
    return user


@router.post("/users/{user_id}/reset-password", status_code=status.HTTP_204_NO_CONTENT)
async def admin_reset_password(
    user_id: str,
    body: AdminPasswordReset,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: TokenPayload = Depends(require_roles("admin")),
) -> None:
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")

    user.password_hash = hash_password(body.new_password)
    user.updated_at = datetime.now(UTC)

    await write_audit_event(
        db,
        action="auth.password_reset",
        actor=admin.sub,
        actor_role=admin.role,
        target={"type": "user", "id": user_id},
        ip_address=request.client.host if request.client else None,
    )


# ──────────────────────────────────────────────────────────────────
# API Keys — admin management + self-service list
# ──────────────────────────────────────────────────────────────────

@router.get("/api-keys", response_model=list[ApiKeyRead])
async def list_api_keys(
    db: AsyncSession = Depends(get_db),
    _admin: TokenPayload = Depends(require_roles("admin")),
) -> list[ApiKeyRead]:
    result = await db.execute(select(ApiKey).order_by(ApiKey.created_at))
    return list(result.scalars().all())


@router.post("/api-keys", response_model=ApiKeyCreated, status_code=status.HTTP_201_CREATED)
async def create_api_key(
    body: ApiKeyCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: TokenPayload = Depends(require_roles("admin")),
) -> ApiKeyCreated:
    """Create a named opaque API key.

    The raw token is returned ONCE and never stored again — copy it immediately.
    Token format: flt_<url-safe-base64> (64 chars total).
    """
    existing = await db.scalar(
        select(func.count()).select_from(ApiKey).where(ApiKey.key_name == body.key_name)
    )
    if existing:
        raise HTTPException(status_code=409, detail="Key name already exists")

    raw_token = "flt_" + secrets.token_urlsafe(48)
    token_hash = hash_token(raw_token)
    expires_at = (
        datetime.now(UTC) + timedelta(days=body.expires_days)
        if body.expires_days
        else None
    )

    api_key = ApiKey(
        key_id=str(uuid.uuid4()),
        key_name=body.key_name,
        token_hash=token_hash,
        role=body.role,
        site_scope=body.site_scope,
        expires_at=expires_at,
        is_active=True,
        created_by=admin.sub,
    )
    db.add(api_key)
    await db.flush()

    await write_audit_event(
        db,
        action="auth.api_key_created",
        actor=admin.sub,
        actor_role=admin.role,
        target={"type": "api_key", "id": api_key.key_id, "name": api_key.key_name},
        payload={"role": api_key.role},
        ip_address=request.client.host if request.client else None,
    )

    return ApiKeyCreated(
        key_id=api_key.key_id,
        key_name=api_key.key_name,
        role=api_key.role,
        site_scope=api_key.site_scope,
        expires_at=api_key.expires_at,
        last_used_at=None,
        is_active=True,
        created_by=admin.sub,
        created_at=api_key.created_at,
        raw_token=raw_token,
    )


@router.delete("/api-keys/{key_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_api_key(
    key_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: TokenPayload = Depends(require_roles("admin")),
) -> None:
    api_key = await db.get(ApiKey, key_id)
    if api_key is None:
        raise HTTPException(status_code=404, detail="API key not found")

    api_key.is_active = False

    await write_audit_event(
        db,
        action="auth.api_key_revoked",
        actor=admin.sub,
        actor_role=admin.role,
        target={"type": "api_key", "id": key_id, "name": api_key.key_name},
        ip_address=request.client.host if request.client else None,
    )
