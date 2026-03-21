import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import get_db
from app.dependencies import get_current_user, require_roles
from app.models.deployment import Deployment
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


@router.get("", response_model=list[DeploymentRead])
async def list_deployments(
    status_filter: str | None = Query(None, alias="status"),
    rollout_mode: str | None = None,
    db: AsyncSession = Depends(get_db),
    _user: TokenPayload = Depends(get_current_user),
):
    q = select(Deployment).order_by(Deployment.started_at.desc())
    if status_filter:
        q = q.where(Deployment.status == status_filter)
    if rollout_mode:
        q = q.where(Deployment.rollout_mode == rollout_mode)
    result = await db.execute(q)
    return result.scalars().all()


@router.get("/{deployment_id}", response_model=DeploymentRead)
async def get_deployment(
    deployment_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _user: TokenPayload = Depends(get_current_user),
):
    deployment = await db.get(Deployment, deployment_id)
    if deployment is None:
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
