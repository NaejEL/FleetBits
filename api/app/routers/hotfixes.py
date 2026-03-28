from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import get_db
from app.dependencies import get_current_user, require_roles
from app.models.device import Device
from app.models.deployment import Hotfix
from app.models.zone import Zone
from app.schemas.deployment import HotfixCreate, HotfixRead
from app.services import semaphore as sem
from app.services.audit import write_audit_event
from app.services.token import TokenPayload

router = APIRouter(prefix="/hotfixes", tags=["hotfixes"])


def _is_site_scoped_user(user: TokenPayload) -> bool:
    return user.role != "admin" and bool(user.site_scope)


async def _resolve_target_scope_site_id(db: AsyncSession, target_scope: dict) -> str | None:
    site_id = target_scope.get("siteId")
    if site_id:
        return site_id

    zone_id = target_scope.get("zoneId")
    if zone_id:
        zone = await db.get(Zone, zone_id)
        return zone.site_id if zone else None

    device_id = target_scope.get("deviceId")
    if device_id:
        device = await db.get(Device, device_id)
        if device is None:
            return None
        if device.site_id:
            return device.site_id
        if device.zone_id:
            zone = await db.get(Zone, device.zone_id)
            return zone.site_id if zone else None
    return None


async def _can_access_hotfix(db: AsyncSession, hotfix: Hotfix, user: TokenPayload) -> bool:
    if not _is_site_scoped_user(user):
        return True
    site_id = await _resolve_target_scope_site_id(db, hotfix.target_scope or {})
    return site_id == user.site_scope


class SshReconcileRequest(BaseModel):
    executed_by: str
    executed_at: datetime
    command_summary: list[str]
    evidence: dict | None = None


@router.get("", response_model=list[HotfixRead])
async def list_hotfixes(
    reconciled: bool | None = None,
    db: AsyncSession = Depends(get_db),
    user: TokenPayload = Depends(get_current_user),
):
    q = select(Hotfix).order_by(Hotfix.created_at.desc())
    if reconciled is not None:
        q = q.where(Hotfix.reconciled == reconciled)
    result = await db.execute(q)
    hotfixes = result.scalars().all()
    if not _is_site_scoped_user(user):
        return hotfixes
    visible: list[Hotfix] = []
    for hotfix in hotfixes:
        if await _can_access_hotfix(db, hotfix, user):
            visible.append(hotfix)
    return visible


@router.get("/{hotfix_id}", response_model=HotfixRead)
async def get_hotfix(
    hotfix_id: str,
    db: AsyncSession = Depends(get_db),
    user: TokenPayload = Depends(get_current_user),
):
    hotfix = await db.get(Hotfix, hotfix_id)
    if hotfix is None:
        raise HTTPException(status_code=404, detail="Hotfix not found")
    if not await _can_access_hotfix(db, hotfix, user):
        raise HTTPException(status_code=404, detail="Hotfix not found")
    return hotfix


@router.post("", response_model=HotfixRead, status_code=status.HTTP_201_CREATED)
async def create_hotfix(
    body: HotfixCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: TokenPayload = Depends(require_roles("operator")),
):
    if _is_site_scoped_user(user):
        site_id = await _resolve_target_scope_site_id(db, body.target_scope)
        if site_id != user.site_scope:
            raise HTTPException(status_code=403, detail="Access denied")

    hotfix = Hotfix(**body.model_dump())
    db.add(hotfix)

    # Immediately trigger the Semaphore job
    scope = body.target_scope
    extra_vars = {
        "artifact_type": body.artifact_type,
        "artifact_ref": body.artifact_ref,
        "hotfix_id": body.hotfix_id,
        "reason": body.reason,
    }
    try:
        job_id = await sem.trigger_job(
            template_id=settings.SEMAPHORE_DEPLOY_TEMPLATE_ID,
            limit=scope.get("deviceId", scope.get("zoneId", "")),
            extra_vars=extra_vars,
        )
        hotfix.semaphore_job_id = job_id
        hotfix.status = "applied"
    except sem.SemaphoreError as exc:
        raise HTTPException(status_code=502, detail=f"Semaphore error: {exc}") from exc

    await db.flush()
    await write_audit_event(
        db,
        action="hotfix.created",
        actor=user.sub,
        actor_role=user.role,
        target={"type": "hotfix", "id": body.hotfix_id},
        payload=body.model_dump(),
        ip_address=request.client.host if request.client else None,
    )
    return hotfix


@router.post("/{hotfix_id}/promote", response_model=HotfixRead)
async def promote_hotfix(
    hotfix_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: TokenPayload = Depends(require_roles("operator")),
):
    """Reconcile hotfix as promoted to baseline."""
    hotfix = await db.get(Hotfix, hotfix_id)
    if hotfix is None:
        raise HTTPException(status_code=404, detail="Hotfix not found")
    if not await _can_access_hotfix(db, hotfix, user):
        raise HTTPException(status_code=404, detail="Hotfix not found")
    if hotfix.reconciled:
        raise HTTPException(status_code=409, detail="Hotfix already reconciled")
    hotfix.reconciled = True
    hotfix.recon_policy = "promote"
    hotfix.status = "promoted"
    await write_audit_event(
        db,
        action="hotfix.promoted",
        actor=user.sub,
        actor_role=user.role,
        target={"type": "hotfix", "id": hotfix_id},
        ip_address=request.client.host if request.client else None,
    )
    return hotfix


@router.post("/{hotfix_id}/revert", response_model=HotfixRead)
async def revert_hotfix(
    hotfix_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: TokenPayload = Depends(require_roles("operator")),
):
    """Revert the hotfix — triggers rollback Semaphore job."""
    hotfix = await db.get(Hotfix, hotfix_id)
    if hotfix is None:
        raise HTTPException(status_code=404, detail="Hotfix not found")
    if not await _can_access_hotfix(db, hotfix, user):
        raise HTTPException(status_code=404, detail="Hotfix not found")
    if hotfix.reconciled:
        raise HTTPException(status_code=409, detail="Hotfix already reconciled")

    scope = hotfix.target_scope
    try:
        await sem.trigger_job(
            template_id=settings.SEMAPHORE_ROLLBACK_TEMPLATE_ID,
            limit=scope.get("deviceId", scope.get("zoneId", "")),
            extra_vars={"hotfix_id": hotfix_id},
        )
    except sem.SemaphoreError as exc:
        raise HTTPException(status_code=502, detail=f"Semaphore error: {exc}") from exc

    hotfix.reconciled = True
    hotfix.recon_policy = "revert"
    hotfix.status = "reverted"
    await write_audit_event(
        db,
        action="hotfix.reverted",
        actor=user.sub,
        actor_role=user.role,
        target={"type": "hotfix", "id": hotfix_id},
        ip_address=request.client.host if request.client else None,
    )
    return hotfix


@router.post("/{hotfix_id}/reconcile-ssh", response_model=HotfixRead)
async def reconcile_ssh(
    hotfix_id: str,
    body: SshReconcileRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: TokenPayload = Depends(require_roles("operator")),
):
    """Record SSH break-glass reconciliation (§6.5)."""
    hotfix = await db.get(Hotfix, hotfix_id)
    if hotfix is None:
        raise HTTPException(status_code=404, detail="Hotfix not found")
    if not await _can_access_hotfix(db, hotfix, user):
        raise HTTPException(status_code=404, detail="Hotfix not found")
    hotfix.reconciled = True
    hotfix.status = "reconciled-ssh"
    await write_audit_event(
        db,
        action="hotfix.reconciled_ssh",
        actor=user.sub,
        actor_role=user.role,
        target={"type": "hotfix", "id": hotfix_id},
        payload={
            "executedBy": body.executed_by,
            "executedAt": body.executed_at.isoformat(),
            "commandSummary": body.command_summary,
            "evidence": body.evidence,
        },
        ip_address=request.client.host if request.client else None,
    )
    return hotfix
