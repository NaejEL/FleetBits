"""Audit event writer — called by every mutating route."""

import uuid
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import AuditEvent


async def write_audit_event(
    db: AsyncSession,
    *,
    action: str,
    actor: str,
    actor_role: str | None = None,
    target: dict,
    payload: dict | None = None,
    ip_address: str | None = None,
) -> AuditEvent:
    """Insert an AuditEvent row.

    The row is not committed here — the calling route's `get_db` session
    commits everything (model changes + audit row) together at request end.
    """
    event = AuditEvent(
        event_id=uuid.uuid4(),
        action=action,
        actor=actor,
        actor_role=actor_role,
        target=target,
        payload=payload,
        ip_address=ip_address,
        created_at=datetime.now(UTC),
    )
    db.add(event)
    return event
