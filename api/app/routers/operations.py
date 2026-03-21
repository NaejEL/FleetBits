from pydantic import BaseModel

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import get_db
from app.dependencies import require_roles
from app.services import semaphore as sem
from app.services.audit import write_audit_event
from app.services.token import TokenPayload

router = APIRouter(prefix="/operations", tags=["operations"])


class RestartServiceRequest(BaseModel):
    device_id: str
    unit_name: str
    change_id: str | None = None
    requested_by: str


class RunDiagnosticsRequest(BaseModel):
    device_id: str
    requested_by: str


class CollectLogsRequest(BaseModel):
    device_id: str
    since: str | None = "2h"  # e.g. "2h", "30m", "1d"
    requested_by: str


@router.post("/restart-service")
async def restart_service(
    body: RestartServiceRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: TokenPayload = Depends(require_roles("operator")),
):
    try:
        job_id = await sem.trigger_job(
            template_id=settings.SEMAPHORE_RESTART_TEMPLATE_ID,
            limit=body.device_id,
            extra_vars={"device_id": body.device_id, "unit_name": body.unit_name},
        )
    except sem.SemaphoreError as exc:
        raise HTTPException(status_code=502, detail=f"Semaphore error: {exc}") from exc

    await write_audit_event(
        db,
        action="operation.restart_service",
        actor=user.sub,
        actor_role=user.role,
        target={"type": "device", "id": body.device_id, "unitName": body.unit_name},
        payload={"semaphore_job_id": job_id, "change_id": body.change_id},
        ip_address=request.client.host if request.client else None,
    )
    return {"semaphore_job_id": job_id, "device_id": body.device_id, "unit_name": body.unit_name}


@router.post("/run-diagnostics")
async def run_diagnostics(
    body: RunDiagnosticsRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: TokenPayload = Depends(require_roles("operator")),
):
    try:
        job_id = await sem.trigger_job(
            template_id=settings.SEMAPHORE_DIAGNOSTICS_TEMPLATE_ID,
            limit=body.device_id,
            extra_vars={"device_id": body.device_id},
        )
    except sem.SemaphoreError as exc:
        raise HTTPException(status_code=502, detail=f"Semaphore error: {exc}") from exc

    await write_audit_event(
        db,
        action="operation.run_diagnostics",
        actor=user.sub,
        actor_role=user.role,
        target={"type": "device", "id": body.device_id},
        payload={"semaphore_job_id": job_id},
        ip_address=request.client.host if request.client else None,
    )
    return {"semaphore_job_id": job_id, "device_id": body.device_id}


@router.post("/collect-logs")
async def collect_logs(
    body: CollectLogsRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: TokenPayload = Depends(require_roles("operator")),
):
    try:
        job_id = await sem.trigger_job(
            template_id=settings.SEMAPHORE_LOGS_TEMPLATE_ID,
            limit=body.device_id,
            extra_vars={"device_id": body.device_id, "since": body.since or "2h"},
        )
    except sem.SemaphoreError as exc:
        raise HTTPException(status_code=502, detail=f"Semaphore error: {exc}") from exc

    await write_audit_event(
        db,
        action="operation.collect_logs",
        actor=user.sub,
        actor_role=user.role,
        target={"type": "device", "id": body.device_id},
        payload={"semaphore_job_id": job_id, "since": body.since},
        ip_address=request.client.host if request.client else None,
    )
    return {"semaphore_job_id": job_id, "device_id": body.device_id}
