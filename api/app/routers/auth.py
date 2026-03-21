"""
Operator authentication.

POST /api/v1/auth/login  — exchange username + password for a signed JWT.

V1 uses a single operator account seeded from environment variables
(OPERATOR_USERNAME / OPERATOR_PASSWORD).  Credentials are compared with
secrets.compare_digest so the check is timing-safe.
"""

import secrets

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from app.config import settings
from app.services.token import create_operator_token

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int  # seconds


@router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest) -> TokenResponse:
    """Validate operator credentials and return a signed JWT."""
    username_ok = secrets.compare_digest(
        body.username.encode(), settings.OPERATOR_USERNAME.encode()
    )
    password_ok = secrets.compare_digest(
        body.password.encode(), settings.OPERATOR_PASSWORD.encode()
    )

    if not (username_ok and password_ok):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
        )

    token = create_operator_token(sub=body.username, role="operator")
    return TokenResponse(
        access_token=token,
        expires_in=settings.FLEET_JWT_EXPIRE_MINUTES * 60,
    )
