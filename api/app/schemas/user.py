from datetime import datetime

from pydantic import BaseModel, ConfigDict, field_validator

from app.models.user import VALID_ROLES


class UserCreate(BaseModel):
    username: str
    password: str  # plaintext — hashed before storage
    email: str | None = None
    role: str = "viewer"
    site_scope: str | None = None

    @field_validator("role")
    @classmethod
    def role_must_be_valid(cls, v: str) -> str:
        if v not in VALID_ROLES:
            raise ValueError(f"role must be one of: {sorted(VALID_ROLES)}")
        return v


class UserUpdate(BaseModel):
    """Fields an admin can patch on any user."""

    email: str | None = None
    role: str | None = None
    site_scope: str | None = None
    is_active: bool | None = None

    @field_validator("role", mode="before")
    @classmethod
    def role_must_be_valid(cls, v: object) -> object:
        if v is not None and v not in VALID_ROLES:
            raise ValueError(f"role must be one of: {sorted(VALID_ROLES)}")
        return v


class PasswordChange(BaseModel):
    """Body for self-service password change."""

    current_password: str
    new_password: str


class AdminPasswordReset(BaseModel):
    """Body for admin-initiated password reset (no old password required)."""

    new_password: str


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    user_id: str
    username: str
    email: str | None = None
    role: str
    site_scope: str | None = None
    is_active: bool
    created_at: datetime
    updated_at: datetime | None = None


# ── API Key schemas ────────────────────────────────────────────────────────────

class ApiKeyCreate(BaseModel):
    key_name: str
    role: str = "ci_bot"
    site_scope: str | None = None
    expires_days: int | None = None  # None = never expires

    @field_validator("role")
    @classmethod
    def role_must_be_valid(cls, v: str) -> str:
        if v not in VALID_ROLES:
            raise ValueError(f"role must be one of: {sorted(VALID_ROLES)}")
        return v


class ApiKeyRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    key_id: str
    key_name: str
    role: str
    site_scope: str | None = None
    expires_at: datetime | None = None
    last_used_at: datetime | None = None
    is_active: bool
    created_by: str
    created_at: datetime


class ApiKeyCreated(ApiKeyRead):
    """Returned once at creation — includes the raw token (never stored)."""
    raw_token: str
