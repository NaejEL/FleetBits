import uuid
from datetime import datetime

from sqlalchemy import Boolean, Text, func
from sqlalchemy.dialects.postgresql import TIMESTAMP
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

VALID_ROLES = frozenset({"admin", "operator", "technician", "viewer", "ci_bot"})


class User(Base):
    """Platform user with hashed password and RBAC role.

    password_hash stores a bcrypt digest — the plaintext is never stored.
    site_scope restricts operator-role users to a single site.
    """

    __tablename__ = "fleet_user"

    user_id: Mapped[str] = mapped_column(
        Text, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    username: Mapped[str] = mapped_column(Text, nullable=False, unique=True, index=True)
    email: Mapped[str | None] = mapped_column(Text, nullable=True)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    role: Mapped[str] = mapped_column(Text, nullable=False, default="viewer")
    # Non-null for operator-class users scoped to a single site
    site_scope: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )
    # Any JWT with iat < token_valid_after is treated as stale/revoked.
    token_valid_after: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )
    grafana_user_id: Mapped[int | None] = mapped_column(
        nullable=True
    )
