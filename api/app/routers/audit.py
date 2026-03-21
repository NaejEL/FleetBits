from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.dependencies import get_current_user
from app.models.audit import AuditEvent
from app.schemas.audit import AuditEventRead
from app.services.token import TokenPayload

router = APIRouter(prefix="/audit", tags=["audit"])


@router.get("", response_model=list[AuditEventRead])
async def list_audit_events(
    actor: str | None = None,
    action: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    limit: int = Query(default=100, le=1000),
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
    user: TokenPayload = Depends(get_current_user),
):
    """Query the append-only audit log.

    site_manager role is automatically scoped to their site via target JSONB containment.
    """
    q = select(AuditEvent).order_by(AuditEvent.created_at.desc()).limit(limit).offset(offset)

    if actor:
        q = q.where(AuditEvent.actor == actor)
    if action:
        q = q.where(AuditEvent.action == action)
    if since:
        q = q.where(AuditEvent.created_at >= since)
    if until:
        q = q.where(AuditEvent.created_at <= until)

    # site_manager: restrict to events whose target JSON contains their site
    if user.role == "site_manager" and user.site_scope:
        q = q.where(AuditEvent.target["site"].astext == user.site_scope)

    result = await db.execute(q)
    return result.scalars().all()
