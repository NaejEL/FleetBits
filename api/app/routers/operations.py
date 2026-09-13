import re

from pydantic import BaseModel, field_validator

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import get_db
from app.dependencies import require_roles
from app.models.device import Device
from app.models.zone import Zone
from app.services import semaphore as sem
from app.services.audit import write_audit_event
from app.services.token import TokenPayload

router = APIRouter(prefix="/operations", tags=["operations"])

# Permit only safe device ID characters to prevent Ansible inventory injection
_DEVICE_ID_RE = re.compile(r"^[a-z0-9\-_.]{1,128}$")
# Permit only safe systemd unit name characters (including @ for template units)
_UNIT_NAME_RE = re.compile(r"^[a-zA-Z0-9\-_.@:\\]{1,256}$")


def _is_site_scoped_user(user: TokenPayload) -> bool:
    return user.role != "admin" and bool(user.site_scope)


async def _get_scoped_device(db: AsyncSession, device_id: str, user: TokenPayload) -> Device | None:
    result = await db.execute(select(Device).where(Device.device_id == device_id))
    device = result.scalar_one_or_none()
    if device is None:
        return None
    if not _is_site_scoped_user(user):
        return device

    site_id = device.site_id
    if site_id is None and device.zone_id:
        zone = await db.get(Zone, device.zone_id)
        site_id = zone.site_id if zone else None

    if site_id != user.site_scope:
        return None
    return device


class RestartServiceRequest(BaseModel):
    device_id: str
    unit_name: str
    change_id: str | None = None
    requested_by: str

    @field_validator("device_id")
    @classmethod
    def check_device_id(cls, v: str) -> str:
        if not _DEVICE_ID_RE.match(v):
            raise ValueError("device_id contains invalid characters (a-z, 0-9, hyphen, underscore, dot only)")
        return v

    @field_validator("unit_name")
    @classmethod
    def check_unit_name(cls, v: str) -> str:
        if not _UNIT_NAME_RE.match(v):
            raise ValueError("unit_name contains invalid characters")
        return v


class RunDiagnosticsRequest(BaseModel):
    device_id: str
    requested_by: str

    @field_validator("device_id")
    @classmethod
    def check_device_id(cls, v: str) -> str:
        if not _DEVICE_ID_RE.match(v):
            raise ValueError("device_id contains invalid characters (a-z, 0-9, hyphen, underscore, dot only)")
        return v


_SINCE_RE = re.compile(r"^\d{1,6}[smhd]$")  # e.g. "2h", "30m", "7d"


class CollectLogsRequest(BaseModel):
    device_id: str
    since: str | None = "2h"
    requested_by: str

    @field_validator("device_id")
    @classmethod
    def check_device_id(cls, v: str) -> str:
        if not _DEVICE_ID_RE.match(v):
            raise ValueError("device_id contains invalid characters (a-z, 0-9, hyphen, underscore, dot only)")
        return v

    @field_validator("since")
    @classmethod
    def check_since(cls, v: str | None) -> str | None:
        if v is not None and not _SINCE_RE.match(v):
            raise ValueError("since must be a positive integer followed by s/m/h/d (e.g. 2h, 30m)")
        return v


@router.post("/restart-service")
async def restart_service(
    body: RestartServiceRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: TokenPayload = Depends(require_roles("operator")),
):
    device = await _get_scoped_device(db, body.device_id, user)
    if device is None:
        raise HTTPException(status_code=404, detail="Device not found")

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
    device = await _get_scoped_device(db, body.device_id, user)
    if device is None:
        raise HTTPException(status_code=404, detail="Device not found")

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
    device = await _get_scoped_device(db, body.device_id, user)
    if device is None:
        raise HTTPException(status_code=404, detail="Device not found")

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
