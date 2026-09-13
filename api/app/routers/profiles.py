from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.dependencies import get_current_user, require_roles
from app.models.device import Device
from app.models.profile import Profile
from app.models.zone import Zone
from app.schemas.profile import ProfileCreate, ProfileRead, ProfileUpdate
from app.services.audit import write_audit_event
from app.services.token import TokenPayload

router = APIRouter(prefix="/profiles", tags=["profiles"])


def _is_site_scoped_user(user: TokenPayload) -> bool:
    return user.role != "admin" and bool(user.site_scope)


async def _site_profile_ids(db: AsyncSession, site_id: str) -> set[str]:
    zone_result = await db.execute(select(Zone.profile_id).where(Zone.site_id == site_id, Zone.profile_id.is_not(None)))
    device_result = await db.execute(
        select(Device.profile_id).where(Device.site_id == site_id, Device.profile_id.is_not(None))
    )
    ids = {pid for (pid,) in zone_result.all()}
    ids.update(pid for (pid,) in device_result.all())
    return ids


@router.get("", response_model=list[ProfileRead])
async def list_profiles(
    db: AsyncSession = Depends(get_db),
    user: TokenPayload = Depends(get_current_user),
):
    if not _is_site_scoped_user(user):
        result = await db.execute(select(Profile))
        return result.scalars().all()

    profile_ids = await _site_profile_ids(db, user.site_scope)
    if not profile_ids:
        return []
    result = await db.execute(select(Profile).where(Profile.profile_id.in_(profile_ids)))
    return result.scalars().all()


@router.get("/{profile_id}", response_model=ProfileRead)
async def get_profile(
    profile_id: str,
    db: AsyncSession = Depends(get_db),
    user: TokenPayload = Depends(get_current_user),
):
    profile = await db.get(Profile, profile_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="Profile not found")
    if _is_site_scoped_user(user):
        allowed_ids = await _site_profile_ids(db, user.site_scope)
        if profile.profile_id not in allowed_ids:
            raise HTTPException(status_code=404, detail="Profile not found")
    return profile


@router.post("", response_model=ProfileRead, status_code=status.HTTP_201_CREATED)
async def create_profile(
    body: ProfileCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: TokenPayload = Depends(require_roles("operator")),
):
    if _is_site_scoped_user(user):
        raise HTTPException(status_code=403, detail="Access denied")

    profile = Profile(**body.model_dump())
    db.add(profile)
    try:
        await db.flush()
    except IntegrityError as exc:
        raise HTTPException(status_code=409, detail=f"Profile {body.profile_id} already exists") from exc
    await write_audit_event(
        db,
        action="profile.created",
        actor=user.sub,
        actor_role=user.role,
        target={"type": "profile", "id": profile.profile_id},
        ip_address=request.client.host if request.client else None,
    )
    return profile


@router.put("/{profile_id}", response_model=ProfileRead)
async def update_profile(
    profile_id: str,
    body: ProfileUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: TokenPayload = Depends(require_roles("operator")),
):
    if _is_site_scoped_user(user):
        raise HTTPException(status_code=403, detail="Access denied")

    profile = await db.get(Profile, profile_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="Profile not found")
    for key, val in body.model_dump(exclude_none=True).items():
        setattr(profile, key, val)
    await write_audit_event(
        db,
        action="profile.updated",
        actor=user.sub,
        actor_role=user.role,
        target={"type": "profile", "id": profile_id},
        payload=body.model_dump(exclude_none=True),
        ip_address=request.client.host if request.client else None,
    )
    return profile


@router.delete("/{profile_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_profile(
    profile_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: TokenPayload = Depends(require_roles("operator")),
):
    if _is_site_scoped_user(user):
        raise HTTPException(status_code=403, detail="Access denied")

    profile = await db.get(Profile, profile_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="Profile not found")
    await db.delete(profile)
    await write_audit_event(
        db,
        action="profile.deleted",
        actor=user.sub,
        actor_role=user.role,
        target={"type": "profile", "id": profile_id},
        ip_address=request.client.host if request.client else None,
    )
