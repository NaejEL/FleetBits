from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.dependencies import get_current_user, require_roles
from app.models.site import Site
from app.schemas.site import SiteCreate, SiteRead, SiteUpdate
from app.services.audit import write_audit_event
from app.services.token import TokenPayload

router = APIRouter(prefix="/sites", tags=["sites"])


@router.get("", response_model=list[SiteRead])
async def list_sites(
    db: AsyncSession = Depends(get_db),
    user: TokenPayload = Depends(get_current_user),
):
    result = await db.execute(select(Site))
    sites = result.scalars().all()
    if user.role == "site_manager" and user.site_scope:
        sites = [s for s in sites if s.site_id == user.site_scope]
    return sites


@router.get("/{site_id}", response_model=SiteRead)
async def get_site(
    site_id: str,
    db: AsyncSession = Depends(get_db),
    user: TokenPayload = Depends(get_current_user),
):
    site = await db.get(Site, site_id)
    if site is None:
        raise HTTPException(status_code=404, detail="Site not found")
    if user.role == "site_manager" and user.site_scope != site_id:
        raise HTTPException(status_code=403, detail="Access denied")
    return site


@router.post("", response_model=SiteRead, status_code=status.HTTP_201_CREATED)
async def create_site(
    body: SiteCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: TokenPayload = Depends(require_roles("operator")),
):
    site = Site(**body.model_dump())
    db.add(site)
    await db.flush()
    await write_audit_event(
        db,
        action="site.created",
        actor=user.sub,
        actor_role=user.role,
        target={"type": "site", "id": site.site_id},
        ip_address=request.client.host if request.client else None,
    )
    return site


@router.put("/{site_id}", response_model=SiteRead)
async def update_site(
    site_id: str,
    body: SiteUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: TokenPayload = Depends(require_roles("operator")),
):
    site = await db.get(Site, site_id)
    if site is None:
        raise HTTPException(status_code=404, detail="Site not found")
    for key, val in body.model_dump(exclude_none=True).items():
        setattr(site, key, val)
    await write_audit_event(
        db,
        action="site.updated",
        actor=user.sub,
        actor_role=user.role,
        target={"type": "site", "id": site_id},
        payload=body.model_dump(exclude_none=True),
        ip_address=request.client.host if request.client else None,
    )
    return site


@router.delete("/{site_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_site(
    site_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: TokenPayload = Depends(require_roles("operator")),
):
    site = await db.get(Site, site_id)
    if site is None:
        raise HTTPException(status_code=404, detail="Site not found")
    await db.delete(site)
    await write_audit_event(
        db,
        action="site.deleted",
        actor=user.sub,
        actor_role=user.role,
        target={"type": "site", "id": site_id},
        ip_address=request.client.host if request.client else None,
    )
