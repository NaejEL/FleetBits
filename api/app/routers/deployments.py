import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import get_db
from app.dependencies import get_current_user, require_roles
from app.models.device import Device
from app.models.deployment import Deployment
from app.models.zone import Zone
from app.schemas.deployment import DeploymentCreate, DeploymentRead, TriggerRequest
from app.services import semaphore as sem
from app.services.audit import write_audit_event
from app.services.token import TokenPayload

router = APIRouter(prefix="/deployments", tags=["deployments"])

_SEMAPHORE_STATUS_MAP = {
    "waiting": "deploying",
    "running": "deploying",
    "success": "success",
    "error": "failed",
}


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


async def _can_access_deployment(db: AsyncSession, deployment: Deployment, user: TokenPayload) -> bool:
    if not _is_site_scoped_user(user):
        return True
    site_id = await _resolve_target_scope_site_id(db, deployment.target_scope or {})
    return site_id == user.site_scope


@router.get("", response_model=list[DeploymentRead])
async def list_deployments(
    status_filter: str | None = Query(None, alias="status"),
    rollout_mode: str | None = None,
    db: AsyncSession = Depends(get_db),
    user: TokenPayload = Depends(get_current_user),
):
    q = select(Deployment).order_by(Deployment.started_at.desc())
    if status_filter:
        q = q.where(Deployment.status == status_filter)
    if rollout_mode:
        q = q.where(Deployment.rollout_mode == rollout_mode)
    result = await db.execute(q)
    deployments = result.scalars().all()
    if not _is_site_scoped_user(user):
        return deployments
    visible: list[Deployment] = []
    for dep in deployments:
        if await _can_access_deployment(db, dep, user):
            visible.append(dep)
    return visible


@router.get("/{deployment_id}", response_model=DeploymentRead)
async def get_deployment(
    deployment_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: TokenPayload = Depends(get_current_user),
):
    deployment = await db.get(Deployment, deployment_id)
    if deployment is None:
        raise HTTPException(status_code=404, detail="Deployment not found")
    if not await _can_access_deployment(db, deployment, user):
        raise HTTPException(status_code=404, detail="Deployment not found")

    # Sync status from Semaphore if still deploying
    if deployment.status == "deploying" and deployment.semaphore_job_id:
        try:
            sem_status = await sem.get_task_status(deployment.semaphore_job_id)
            mapped = _SEMAPHORE_STATUS_MAP.get(sem_status, deployment.status)
            if mapped != deployment.status:
                deployment.status = mapped
                if mapped in ("success", "failed"):
                    deployment.ended_at = datetime.now(UTC)
        except sem.SemaphoreError:
            pass  # keep stored status if Semaphore is unreachable

    return deployment


@router.post("", response_model=DeploymentRead, status_code=status.HTTP_201_CREATED)
async def create_deployment(
    body: DeploymentCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: TokenPayload = Depends(require_roles("operator", "ci_bot")),
):
    # ci_bot may only create ring-0 deployments
    if user.role == "ci_bot" and body.rollout_mode != "ring-0":
        raise HTTPException(status_code=403, detail="CI bot may only create ring-0 deployments")
    if _is_site_scoped_user(user):
        site_id = await _resolve_target_scope_site_id(db, body.target_scope)
        if site_id != user.site_scope:
            raise HTTPException(status_code=403, detail="Access denied")

    deployment = Deployment(
        deployment_id=uuid.uuid4(),
        **body.model_dump(),
    )
    db.add(deployment)
    await db.flush()
    await write_audit_event(
        db,
        action="deployment.created",
        actor=user.sub,
        actor_role=user.role,
        target={"type": "deployment", "id": str(deployment.deployment_id)},
        payload=body.model_dump(),
        ip_address=request.client.host if request.client else None,
    )
    return deployment


@router.post("/{deployment_id}/trigger", response_model=DeploymentRead)
async def trigger_deployment(
    deployment_id: uuid.UUID,
    body: TriggerRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: TokenPayload = Depends(require_roles("operator", "ci_bot")),
):
    """Manually gate: call this to actually fire the Ansible job in Semaphore."""
    deployment = await db.get(Deployment, deployment_id)
    if deployment is None:
        raise HTTPException(status_code=404, detail="Deployment not found")
    if not await _can_access_deployment(db, deployment, user):
        raise HTTPException(status_code=404, detail="Deployment not found")
    if deployment.status not in ("pending", "scheduled"):
        raise HTTPException(
            status_code=409,
            detail=f"Cannot trigger a deployment with status '{deployment.status}'",
        )
    if user.role == "ci_bot" and deployment.rollout_mode != "ring-0":
        raise HTTPException(status_code=403, detail="CI bot may only trigger ring-0 deployments")

    if body.scheduled_at:
        deployment.scheduled_at = body.scheduled_at

    # Build Ansible extra vars
    extra_vars = {
        "artifact_type": deployment.artifact_type,
        "artifact_ref": deployment.artifact_ref,
        "deployment_id": str(deployment.deployment_id),
    }
    # Add target from scope
    scope = deployment.target_scope or {}
    if scope.get("siteId"):
        extra_vars["site_id"] = scope["siteId"]
    if scope.get("zoneId"):
        extra_vars["zone_id"] = scope["zoneId"]
    if scope.get("deviceId"):
        extra_vars["device_id"] = scope["deviceId"]

    try:
        job_id = await sem.trigger_job(
            template_id=settings.SEMAPHORE_DEPLOY_TEMPLATE_ID,
            limit=scope.get("deviceId", scope.get("zoneId", "")),
            extra_vars=extra_vars,
        )
        deployment.semaphore_job_id = job_id
        deployment.status = "deploying"
    except sem.SemaphoreError as exc:
        raise HTTPException(status_code=502, detail=f"Semaphore error: {exc}") from exc

    await write_audit_event(
        db,
        action="deployment.triggered",
        actor=user.sub,
        actor_role=user.role,
        target={"type": "deployment", "id": str(deployment_id)},
        payload={"semaphore_job_id": job_id},
        ip_address=request.client.host if request.client else None,
    )
    return deployment


@router.post("/{deployment_id}/rollback", response_model=DeploymentRead)
async def rollback_deployment(
    deployment_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: TokenPayload = Depends(require_roles("operator")),
):
    """Roll back by triggering a new deployment with rollout_mode='rollback'."""
    original = await db.get(Deployment, deployment_id)
    if original is None:
        raise HTTPException(status_code=404, detail="Deployment not found")
    if not await _can_access_deployment(db, original, user):
        raise HTTPException(status_code=404, detail="Deployment not found")
    if original.status not in ("success", "failed"):
        raise HTTPException(
            status_code=409,
            detail="Can only roll back a completed (success or failed) deployment",
        )

    rollback = Deployment(
        deployment_id=uuid.uuid4(),
        artifact_type=original.artifact_type,
        artifact_ref=original.artifact_ref,
        rollout_mode="rollback",
        target_scope=original.target_scope,
        status="pending",
        change_id=original.change_id,
        requested_by=user.sub,
    )
    db.add(rollback)
    await db.flush()
    await write_audit_event(
        db,
        action="deployment.rollback_requested",
        actor=user.sub,
        actor_role=user.role,
        target={"type": "deployment", "id": str(rollback.deployment_id), "originalId": str(deployment_id)},
        ip_address=request.client.host if request.client else None,
    )
    return rollback


_RING_PROGRESSION = {"ring-0": "ring-1", "ring-1": "ring-2"}


@router.post("/{deployment_id}/promote", response_model=DeploymentRead, status_code=status.HTTP_201_CREATED)
async def promote_deployment(
    deployment_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: TokenPayload = Depends(require_roles("operator")),
):
    """Promote a successful ring-N deployment to ring-(N+1).

    Creates a new pending deployment with the next rollout_mode.
    Only ring-0 → ring-1 and ring-1 → ring-2 promotions are allowed.
    """
    original = await db.get(Deployment, deployment_id)
    if original is None:
        raise HTTPException(status_code=404, detail="Deployment not found")
    if not await _can_access_deployment(db, original, user):
        raise HTTPException(status_code=404, detail="Deployment not found")
    if original.status != "success":
        raise HTTPException(
            status_code=409,
            detail=f"Can only promote a successful deployment (current status: '{original.status}')",
        )
    next_mode = _RING_PROGRESSION.get(original.rollout_mode)
    if not next_mode:
        raise HTTPException(
            status_code=409,
            detail=f"Cannot promote from rollout_mode '{original.rollout_mode}' — only ring-0 and ring-1 are promotable",
        )

    promoted = Deployment(
        deployment_id=uuid.uuid4(),
        artifact_type=original.artifact_type,
        artifact_ref=original.artifact_ref,
        rollout_mode=next_mode,
        target_scope=original.target_scope,
        status="pending",
        change_id=original.change_id,
        requested_by=user.sub,
    )
    db.add(promoted)
    await db.flush()
    await write_audit_event(
        db,
        action="deployment.promoted",
        actor=user.sub,
        actor_role=user.role,
        target={
            "type": "deployment",
            "id": str(promoted.deployment_id),
            "fromId": str(deployment_id),
        },
        payload={"from_mode": original.rollout_mode, "to_mode": next_mode},
        ip_address=request.client.host if request.client else None,
    )
    return promoted
