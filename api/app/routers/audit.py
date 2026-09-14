from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.dependencies import get_current_user
from app.models.audit import AuditEvent
from app.routers._scope import require_site_scope
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

    Callers confined to a site are automatically scoped to it via target JSONB fields.
    """
    site_scope = require_site_scope(user)
    q = select(AuditEvent).order_by(AuditEvent.created_at.desc()).limit(limit).offset(offset)

    if actor:
        q = q.where(AuditEvent.actor == actor)
    if action:
        q = q.where(AuditEvent.action == action)
    if since:
        q = q.where(AuditEvent.created_at >= since)
    if until:
        q = q.where(AuditEvent.created_at <= until)

    # A confined caller only sees the events of its own site.
    if site_scope is not None:
        q = q.where(
            or_(
                AuditEvent.target["site"].astext == site_scope,
                AuditEvent.target["siteId"].astext == site_scope,
            )
        )

    result = await db.execute(q)
    return result.scalars().all()
