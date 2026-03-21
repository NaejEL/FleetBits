from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.dependencies import get_current_user, require_roles
from app.models.profile import Profile
from app.schemas.profile import ProfileCreate, ProfileRead, ProfileUpdate
from app.services.audit import write_audit_event
from app.services.token import TokenPayload

router = APIRouter(prefix="/profiles", tags=["profiles"])


@router.get("", response_model=list[ProfileRead])
async def list_profiles(
    db: AsyncSession = Depends(get_db),
    _user: TokenPayload = Depends(get_current_user),
):
    result = await db.execute(select(Profile))
    return result.scalars().all()


@router.get("/{profile_id}", response_model=ProfileRead)
async def get_profile(
    profile_id: str,
    db: AsyncSession = Depends(get_db),
    _user: TokenPayload = Depends(get_current_user),
):
    profile = await db.get(Profile, profile_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="Profile not found")
    return profile


@router.post("", response_model=ProfileRead, status_code=status.HTTP_201_CREATED)
async def create_profile(
    body: ProfileCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: TokenPayload = Depends(require_roles("operator")),
):
    profile = Profile(**body.model_dump())
    db.add(profile)
    await db.flush()
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
