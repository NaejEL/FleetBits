import uuid
from datetime import datetime

from sqlalchemy import Boolean, ForeignKey, Text, func
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class Deployment(Base):
    __tablename__ = "deployment"

    deployment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    artifact_type: Mapped[str] = mapped_column(Text, nullable=False)  # 'deb' | 'git'
    artifact_ref: Mapped[str] = mapped_column(Text, nullable=False)
    resolved_commit: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 'ring-0' | 'ring-1' | 'ring-2' | 'hotfix' | 'rollback'
    rollout_mode: Mapped[str] = mapped_column(Text, nullable=False)
    # {"scope": "ring", "ring": 0} | {"scope": "site", "siteId": "paris"} | etc.
    target_scope: Mapped[dict] = mapped_column(JSONB, nullable=False)
    # 'pending' | 'scheduled' | 'deploying' | 'success' | 'failed' | 'rolled-back'
    status: Mapped[str] = mapped_column(Text, nullable=False, default="pending")
    # Informational: when the operator planned to run it
    scheduled_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    change_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    requested_by: Mapped[str] = mapped_column(Text, nullable=False)
    semaphore_job_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())
    ended_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)


class Hotfix(Base):
    __tablename__ = "hotfix"

    hotfix_id: Mapped[str] = mapped_column(Text, primary_key=True)  # e.g. "HF-2026-00042"
    target_scope: Mapped[dict] = mapped_column(JSONB, nullable=False)
    artifact_type: Mapped[str] = mapped_column(Text, nullable=False)
    artifact_ref: Mapped[str] = mapped_column(Text, nullable=False)
    resolved_commit: Mapped[str | None] = mapped_column(Text, nullable=True)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    requested_by: Mapped[str] = mapped_column(Text, nullable=False)
    change_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    # 'promote' | 'revert' | 'decide-later'
    recon_policy: Mapped[str] = mapped_column(Text, nullable=False, default="decide-later")
    reconciled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # 'open' | 'applied' | 'promoted' | 'reverted'
    status: Mapped[str] = mapped_column(Text, nullable=False, default="open")
    semaphore_job_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())


class Override(Base):
    """Scoped exception in the variant resolution hierarchy (§5.1)."""

    __tablename__ = "override"

    override_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    # 'site' | 'zone' | 'device'
    scope: Mapped[str] = mapped_column(Text, nullable=False)
    target_id: Mapped[str] = mapped_column(Text, nullable=False)
    component: Mapped[str] = mapped_column(Text, nullable=False)
    artifact_type: Mapped[str] = mapped_column(Text, nullable=False)  # 'deb' | 'git'
    artifact_ref: Mapped[str] = mapped_column(Text, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    created_by: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())
    expires_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    reconciled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
