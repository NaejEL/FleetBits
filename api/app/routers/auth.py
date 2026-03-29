"""
Operator authentication and user management.

POST /api/v1/auth/login                        — exchange username + password for a signed JWT
POST /api/v1/auth/logout                       — revoke current JWT immediately (SEC-P0-07)
GET  /api/v1/auth/users/me                     — current user info
POST /api/v1/auth/change-password              — self: change own password
POST /api/v1/auth/users                        — admin: create user
GET  /api/v1/auth/users                        — admin: list all users
PATCH /api/v1/auth/users/{user_id}             — admin: update role / site_scope / is_active / email
POST /api/v1/auth/users/{user_id}/reset-password — admin: set new password without knowing old
"""

import asyncio
import secrets
import uuid
from collections import defaultdict, deque
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import get_db
from app.dependencies import get_current_user, require_roles
from app.models.api_key import ApiKey
from app.models.token import RevokedJWT
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
from app.services.grafana_provisioner import deprovision_user as grafana_deprovision
from app.services.grafana_provisioner import provision_user as grafana_provision
from app.services.passwords import hash_password, verify_password
from app.services.token import TokenPayload, create_operator_token, decode_token, hash_token

router = APIRouter(prefix="/auth", tags=["auth"])


# ──────────────────────────────────────────────────────────────────
# Grafana SSO — forward_auth endpoint for Caddy
# ──────────────────────────────────────────────────────────────────

@router.get("/grafana-verify")
async def grafana_verify(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Caddy forward_auth endpoint for Grafana Auth Proxy.

    Caddy calls this before forwarding any request to Grafana.
    The endpoint reads the `fleet_access` HttpOnly cookie (set by Fleet UI
    at login), validates the JWT, and returns 200 with X-WEBAUTH-* headers
    that Grafana uses to auto-login the user.

    Returns 401 if the token is missing, expired, or revoked — Caddy then
    responds with 401/redirect instead of forwarding to Grafana.
    """
    # Verify the proxy shared secret to prevent header injection from
    # sources other than Caddy.
    if settings.GRAFANA_PROXY_SECRET:
        incoming = request.headers.get("X-Fleet-Proxy-Secret", "")
        if incoming != settings.GRAFANA_PROXY_SECRET:
            raise HTTPException(status_code=401, detail="Unauthorized")

    token = request.cookies.get("fleet_access")
    if not token:
        raise HTTPException(status_code=401, detail="No session")

    from jose import JWTError
    try:
        payload = decode_token(token)
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")

    # Check revocation
    if payload.jti:
        revoked = await db.get(RevokedJWT, payload.jti)
        if revoked is not None:
            raise HTTPException(status_code=401, detail="Token revoked")

    # Check user still active
    user_result = await db.execute(select(User).where(User.username == payload.sub))
    user = user_result.scalar_one_or_none()
    if user is None or not user.is_active:
        raise HTTPException(status_code=401, detail="User inactive")

    # Check token not invalidated by password change / deactivation
    if user.token_valid_after is not None and payload.iat is not None:
        from datetime import UTC
        from datetime import datetime as _dt
        iat_dt = _dt.fromtimestamp(payload.iat, tz=UTC)
        if iat_dt < user.token_valid_after:
            raise HTTPException(status_code=401, detail="Token invalidated")

    headers = {
        "X-WEBAUTH-USER": user.username,
        "X-WEBAUTH-EMAIL": user.email or f"{user.username}@fleetbits.local",
        "X-WEBAUTH-NAME": user.username,
        "X-WEBAUTH-GROUPS": user.role,
        # Pass site scope so the UI can generate scoped dashboard URLs
        "X-WEBAUTH-SITE-SCOPE": user.site_scope or "",
    }
    return Response(status_code=200, headers=headers)


def _exp_to_datetime(exp: int | None) -> datetime | None:
    if exp is None:
        return None
    try:
        return datetime.fromtimestamp(exp, tz=UTC)
    except (OverflowError, OSError, ValueError):
        return None


async def _revoke_jwt_jti(
    db: AsyncSession,
    jti: str | None,
    sub: str,
    reason: str,
    exp: int | None,
) -> None:
    if not jti:
        return

    # Ensure the row has a valid expiry for cleanup/housekeeping semantics.
    expires_at = _exp_to_datetime(exp) or (datetime.now(UTC) + timedelta(days=7))

    existing = await db.get(RevokedJWT, jti)
    if existing is not None:
        return

    db.add(
        RevokedJWT(
            jti=jti,
            sub=sub,
            reason=reason,
            expires_at=expires_at,
        )
    )


def _invalidate_all_user_tokens(user: User) -> None:
    # Any token issued before this timestamp becomes invalid immediately.
    user.token_valid_after = datetime.now(UTC)


class _LoginGuard:
    """In-memory login failure tracking and temporary lockout.

    This is a baseline protection for single-instance deployments.
    Multi-instance deployments should migrate this state to Redis.
    """

    def __init__(self):
        self._failures: dict[tuple[str, str], deque[datetime]] = defaultdict(deque)
        self._locked_until: dict[tuple[str, str], datetime] = {}
        self._lock = asyncio.Lock()

    async def check_lock(self, username: str, ip_address: str) -> datetime | None:
        key = (username.lower().strip(), ip_address)
        now = datetime.now(UTC)
        async with self._lock:
            until = self._locked_until.get(key)
            if until and until > now:
                return until
            if until and until <= now:
                self._locked_until.pop(key, None)
        return None

    async def record_failure(self, username: str, ip_address: str) -> tuple[int, datetime | None]:
        key = (username.lower().strip(), ip_address)
        now = datetime.now(UTC)
        window_seconds = max(60, settings.LOGIN_FAILURE_WINDOW_SECONDS)
        threshold = max(1, settings.LOGIN_FAILURE_LOCK_THRESHOLD)
        lock_seconds = max(60, settings.LOGIN_FAILURE_LOCK_SECONDS)

        async with self._lock:
            bucket = self._failures[key]
            cutoff = now - timedelta(seconds=window_seconds)
            while bucket and bucket[0] < cutoff:
                bucket.popleft()
            bucket.append(now)
            failures = len(bucket)

            locked_until = None
            if failures >= threshold:
                locked_until = now + timedelta(seconds=lock_seconds)
                self._locked_until[key] = locked_until
                bucket.clear()

            return failures, locked_until

    async def clear(self, username: str, ip_address: str) -> None:
        key = (username.lower().strip(), ip_address)
        async with self._lock:
            self._failures.pop(key, None)
            self._locked_until.pop(key, None)


_login_guard = _LoginGuard()


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
    client_ip = request.client.host if request.client else "unknown"
    lock_until = await _login_guard.check_lock(body.username, client_ip)
    if lock_until is not None:
        await write_audit_event(
            db,
            action="auth.login_locked",
            actor=body.username,
            target={"type": "auth", "username": body.username},
            payload={"locked_until": lock_until.isoformat()},
            ip_address=client_ip,
        )
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many failed login attempts. Try again later.",
        )

    result = await db.execute(select(User).where(User.username == body.username))
    user: User | None = result.scalar_one_or_none()

    # Always run bcrypt verify to prevent user-enumeration via timing side-channel.
    # When user doesn't exist we verify against a dummy hash (same cost, doomed to fail).
    # Verify against dummy hash when user not found to prevent timing-based user enumeration
    _DUMMY_HASH = "$2b$12$KIXxRn5HoO/8HmPOj7sGaeJhH/ylbRnzFSInMBpGmJd7WUjZFJgZi"  # noqa: S105
    candidate_hash = user.password_hash if user else _DUMMY_HASH
    password_ok = verify_password(body.password, candidate_hash)

    if not user or not user.is_active or not password_ok:
        failures, locked_until = await _login_guard.record_failure(body.username, client_ip)
        payload = {"failed_attempts_in_window": failures}
        if locked_until is not None:
            payload["locked_until"] = locked_until.isoformat()

        await write_audit_event(
            db,
            action="auth.login_failed",
            actor=body.username,
            target={"type": "auth", "username": body.username},
            payload=payload,
            ip_address=client_ip,
        )
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
        )

    await _login_guard.clear(body.username, client_ip)

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
        ip_address=client_ip,
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
    _invalidate_all_user_tokens(user)
    await _revoke_jwt_jti(
        db,
        current_user.jti,
        current_user.sub,
        reason="password_changed",
        exp=current_user.exp,
    )

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

    # Provision Grafana account (best-effort — does not block user creation)
    grafana_id = await grafana_provision(
        username=user.username,
        email=user.email or f"{user.username}@fleetbits.local",
        role=user.role,
        site_scope=user.site_scope,
    )
    if grafana_id is not None:
        user.grafana_user_id = grafana_id

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
    security_sensitive_changed = False
    for field, value in body.model_dump(exclude_none=True).items():
        if field in {"role", "site_scope", "is_active"} and getattr(user, field) != value:
            security_sensitive_changed = True
        setattr(user, field, value)
        changes[field] = value

    if changes:
        user.updated_at = datetime.now(UTC)

    if security_sensitive_changed:
        _invalidate_all_user_tokens(user)

    await write_audit_event(
        db,
        action="auth.user_updated",
        actor=admin.sub,
        actor_role=admin.role,
        target={"type": "user", "id": user_id},
        payload=changes,
        ip_address=request.client.host if request.client else None,
    )

    # Re-provision Grafana if role, scope, or active status changed
    if security_sensitive_changed:
        if user.is_active:
            grafana_id = await grafana_provision(
                username=user.username,
                email=user.email or f"{user.username}@fleetbits.local",
                role=user.role,
                site_scope=user.site_scope,
            )
            if grafana_id is not None:
                user.grafana_user_id = grafana_id
        elif not user.is_active and user.grafana_user_id is not None:
            await grafana_deprovision(user.grafana_user_id)
            user.grafana_user_id = None

    return user


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: TokenPayload = Depends(get_current_user),
) -> None:
    """Explicitly revoke the current JWT. The token is unusable immediately."""
    await _revoke_jwt_jti(
        db,
        current_user.jti,
        current_user.sub,
        reason="logout",
        exp=current_user.exp,
    )
    await write_audit_event(
        db,
        action="auth.logout",
        actor=current_user.sub,
        actor_role=current_user.role,
        target={"type": "user", "sub": current_user.sub},
        ip_address=request.client.host if request.client else None,
    )


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
    _invalidate_all_user_tokens(user)

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
    expires_at = datetime.now(UTC) + timedelta(days=body.expires_days)

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
