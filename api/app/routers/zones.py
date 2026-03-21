from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.dependencies import get_current_user, require_roles
from app.models.zone import Zone
from app.schemas.zone import ZoneCreate, ZoneRead, ZoneUpdate
from app.services.audit import write_audit_event
from app.services.token import TokenPayload

router = APIRouter(prefix="/zones", tags=["zones"])


@router.get("", response_model=list[ZoneRead])
async def list_zones(
    site_id: str | None = None,
    profile_id: str | None = None,
    db: AsyncSession = Depends(get_db),
    user: TokenPayload = Depends(get_current_user),
):
    q = select(Zone)
    if site_id:
        q = q.where(Zone.site_id == site_id)
    if profile_id:
        q = q.where(Zone.profile_id == profile_id)
    if user.role == "site_manager" and user.site_scope:
        q = q.where(Zone.site_id == user.site_scope)
    result = await db.execute(q)
    return result.scalars().all()


@router.get("/{zone_id}", response_model=ZoneRead)
async def get_zone(
    zone_id: str,
    db: AsyncSession = Depends(get_db),
    user: TokenPayload = Depends(get_current_user),
):
    zone = await db.get(Zone, zone_id)
    if zone is None:
        raise HTTPException(status_code=404, detail="Zone not found")
    if user.role == "site_manager" and user.site_scope != zone.site_id:
        raise HTTPException(status_code=403, detail="Access denied")
    return zone


@router.post("", response_model=ZoneRead, status_code=status.HTTP_201_CREATED)
async def create_zone(
    body: ZoneCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: TokenPayload = Depends(require_roles("operator")),
):
    zone = Zone(**body.model_dump())
    db.add(zone)
    await db.flush()
    await write_audit_event(
        db,
        action="zone.created",
        actor=user.sub,
        actor_role=user.role,
        target={"type": "zone", "id": zone.zone_id, "siteId": zone.site_id},
        ip_address=request.client.host if request.client else None,
    )
    return zone


@router.put("/{zone_id}", response_model=ZoneRead)
async def update_zone(
    zone_id: str,
    body: ZoneUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: TokenPayload = Depends(require_roles("operator")),
):
    zone = await db.get(Zone, zone_id)
    if zone is None:
        raise HTTPException(status_code=404, detail="Zone not found")
    for key, val in body.model_dump(exclude_none=True).items():
        setattr(zone, key, val)
    await write_audit_event(
        db,
        action="zone.updated",
        actor=user.sub,
        actor_role=user.role,
        target={"type": "zone", "id": zone_id},
        payload=body.model_dump(exclude_none=True),
        ip_address=request.client.host if request.client else None,
    )
    return zone


@router.delete("/{zone_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_zone(
    zone_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: TokenPayload = Depends(require_roles("operator")),
):
    zone = await db.get(Zone, zone_id)
    if zone is None:
        raise HTTPException(status_code=404, detail="Zone not found")
    await db.delete(zone)
    await write_audit_event(
        db,
        action="zone.deleted",
        actor=user.sub,
        actor_role=user.role,
        target={"type": "zone", "id": zone_id},
        ip_address=request.client.host if request.client else None,
    )
