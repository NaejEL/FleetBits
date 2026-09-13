import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.dependencies import get_current_user, require_roles
from app.models.device import Device
from app.models.deployment import Override
from app.models.zone import Zone
from app.schemas.deployment import OverrideCreate, OverrideRead
from app.services.audit import write_audit_event
from app.services.resolver import resolve_manifest
from app.services.token import TokenPayload

router = APIRouter(tags=["overrides & manifest"])


def _is_site_scoped_user(user: TokenPayload) -> bool:
    return user.role != "admin" and bool(user.site_scope)


async def _resolve_override_site_id(db: AsyncSession, scope: str, target_id: str) -> str | None:
    if scope == "site":
        return target_id
    if scope == "zone":
        zone = await db.get(Zone, target_id)
        return zone.site_id if zone else None
    if scope == "device":
        device = await db.get(Device, target_id)
        if device is None:
            return None
        if device.site_id:
            return device.site_id
        if device.zone_id:
            zone = await db.get(Zone, device.zone_id)
            return zone.site_id if zone else None
    return None


async def _can_access_override(db: AsyncSession, override: Override, user: TokenPayload) -> bool:
    if not _is_site_scoped_user(user):
        return True
    site_id = await _resolve_override_site_id(db, override.scope, override.target_id)
    return site_id == user.site_scope


@router.get("/overrides", response_model=list[OverrideRead])
async def list_overrides(
    scope: str | None = None,
    target_id: str | None = None,
    db: AsyncSession = Depends(get_db),
    user: TokenPayload = Depends(get_current_user),
):
    q = select(Override)
    if scope:
        q = q.where(Override.scope == scope)
    if target_id:
        q = q.where(Override.target_id == target_id)
    result = await db.execute(q)
    overrides = result.scalars().all()
    if not _is_site_scoped_user(user):
        return overrides
    visible: list[Override] = []
    for override in overrides:
        if await _can_access_override(db, override, user):
            visible.append(override)
    return visible


@router.post("/overrides", response_model=OverrideRead, status_code=status.HTTP_201_CREATED)
async def create_override(
    body: OverrideCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: TokenPayload = Depends(require_roles("operator")),
):
    if _is_site_scoped_user(user):
        site_id = await _resolve_override_site_id(db, body.scope, body.target_id)
        if site_id != user.site_scope:
            raise HTTPException(status_code=403, detail="Access denied")

    override = Override(override_id=uuid.uuid4(), **body.model_dump())
    db.add(override)
    await db.flush()
    await write_audit_event(
        db,
        action="override.created",
        actor=user.sub,
        actor_role=user.role,
        target={
            "type": "override",
            "id": str(override.override_id),
            "scope": body.scope,
            "targetId": body.target_id,
        },
        payload=body.model_dump(),
        ip_address=request.client.host if request.client else None,
    )
    return override


@router.delete("/overrides/{override_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_override(
    override_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: TokenPayload = Depends(require_roles("operator")),
):
    override = await db.get(Override, override_id)
    if override is None:
        raise HTTPException(status_code=404, detail="Override not found")
    if not await _can_access_override(db, override, user):
        raise HTTPException(status_code=404, detail="Override not found")
    await db.delete(override)
    await write_audit_event(
        db,
        action="override.deleted",
        actor=user.sub,
        actor_role=user.role,
        target={"type": "override", "id": str(override_id)},
        ip_address=request.client.host if request.client else None,
    )


@router.get("/targets/{device_id}/manifest")
async def get_manifest(
    device_id: str,
    db: AsyncSession = Depends(get_db),
    user: TokenPayload = Depends(get_current_user),
):
    """Return the fully resolved component manifest for a device (§5.1)."""
    if _is_site_scoped_user(user):
        device = await db.get(Device, device_id)
        if device is None:
            raise HTTPException(status_code=404, detail="Device not found")
        site_id = device.site_id
        if site_id is None and device.zone_id:
            zone = await db.get(Zone, device.zone_id)
            site_id = zone.site_id if zone else None
        if site_id != user.site_scope:
            raise HTTPException(status_code=404, detail="Device not found")

    manifest = await resolve_manifest(db, device_id=device_id)
    if manifest is None:
        raise HTTPException(status_code=404, detail="Device not found")
    return manifest
