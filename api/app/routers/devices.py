from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.dependencies import get_current_user, get_device_from_bearer, require_roles
from app.models.device import Device, ServiceUnit
from app.models.token import ProvisionToken
from app.schemas.device import DeviceCreate, DeviceRead, DeviceUpdate, HeartbeatPayload, ServiceUnitRead
from app.services.audit import write_audit_event
from app.services.token import (
    TokenPayload,
    decode_provision_token,
    generate_device_token,
    hash_token,
)

router = APIRouter(prefix="/devices", tags=["devices"])

# ──────────────────────────────────────────────────────
# Service units (scoped query at /services, not /devices)
# ──────────────────────────────────────────────────────

services_router = APIRouter(prefix="/services", tags=["services"])


@services_router.get("", response_model=list[ServiceUnitRead])
async def list_services(
    device_id: str | None = None,
    state: str | None = None,
    db: AsyncSession = Depends(get_db),
    _user: TokenPayload = Depends(get_current_user),
):
    q = select(ServiceUnit)
    if device_id:
        q = q.where(ServiceUnit.device_id == device_id)
    if state:
        q = q.where(ServiceUnit.state == state)
    result = await db.execute(q)
    return result.scalars().all()


# ──────────────────────────────────────────────────────
# Bulk import — must be registered BEFORE /{device_id} routes
# ──────────────────────────────────────────────────────

@router.post("/bulk", response_model=list[DeviceRead], status_code=status.HTTP_201_CREATED)
async def bulk_import_devices(
    body: list[DeviceCreate],
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: TokenPayload = Depends(require_roles("operator")),
):
    """Import multiple devices at once (Day 0 fleet seeding)."""
    devices: list[Device] = []
    for item in body:
        device = Device(**item.model_dump())
        db.add(device)
        devices.append(device)
    await db.flush()
    await write_audit_event(
        db,
        action="device.bulk_imported",
        actor=user.sub,
        actor_role=user.role,
        target={"type": "device", "ids": [d.device_id for d in devices]},
        payload={"count": len(devices)},
        ip_address=request.client.host if request.client else None,
    )
    return devices


# ──────────────────────────────────────────────────────
# CRUD
# ──────────────────────────────────────────────────────

@router.get("", response_model=list[DeviceRead])
async def list_devices(
    zone_id: str | None = None,
    site_id: str | None = None,
    role: str | None = None,
    ring: int | None = None,
    db: AsyncSession = Depends(get_db),
    user: TokenPayload = Depends(get_current_user),
):
    q = select(Device)
    if zone_id:
        q = q.where(Device.zone_id == zone_id)
    if site_id:
        q = q.where(Device.site_id == site_id)
    if role:
        q = q.where(Device.role == role)
    if ring is not None:
        q = q.where(Device.ring == ring)
    if user.role == "site_manager" and user.site_scope:
        q = q.where(Device.site_id == user.site_scope)
    result = await db.execute(q)
    return result.scalars().all()


@router.get("/{device_id}", response_model=DeviceRead)
async def get_device(
    device_id: str,
    db: AsyncSession = Depends(get_db),
    user: TokenPayload = Depends(get_current_user),
):
    device = await db.get(Device, device_id)
    if device is None:
        raise HTTPException(status_code=404, detail="Device not found")
    if user.role == "site_manager" and user.site_scope != device.site_id:
        raise HTTPException(status_code=403, detail="Access denied")
    return device


@router.post("", response_model=DeviceRead, status_code=status.HTTP_201_CREATED)
async def create_device(
    body: DeviceCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: TokenPayload = Depends(require_roles("operator")),
):
    device = Device(**body.model_dump())
    db.add(device)
    await db.flush()
    await write_audit_event(
        db,
        action="device.created",
        actor=user.sub,
        actor_role=user.role,
        target={"type": "device", "id": device.device_id},
        ip_address=request.client.host if request.client else None,
    )
    return device


@router.put("/{device_id}", response_model=DeviceRead)
async def update_device(
    device_id: str,
    body: DeviceUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: TokenPayload = Depends(require_roles("operator")),
):
    device = await db.get(Device, device_id)
    if device is None:
        raise HTTPException(status_code=404, detail="Device not found")
    for key, val in body.model_dump(exclude_none=True).items():
        setattr(device, key, val)
    await write_audit_event(
        db,
        action="device.updated",
        actor=user.sub,
        actor_role=user.role,
        target={"type": "device", "id": device_id},
        payload=body.model_dump(exclude_none=True),
        ip_address=request.client.host if request.client else None,
    )
    return device


@router.delete("/{device_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_device(
    device_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: TokenPayload = Depends(require_roles("operator")),
):
    device = await db.get(Device, device_id)
    if device is None:
        raise HTTPException(status_code=404, detail="Device not found")
    await db.delete(device)
    await write_audit_event(
        db,
        action="device.deleted",
        actor=user.sub,
        actor_role=user.role,
        target={"type": "device", "id": device_id},
        ip_address=request.client.host if request.client else None,
    )


# ──────────────────────────────────────────────────────
# Heartbeat — called by fleet-agent heartbeat.sh, device token auth
# ──────────────────────────────────────────────────────

@router.post("/{device_id}/heartbeat", status_code=status.HTTP_204_NO_CONTENT)
async def device_heartbeat(
    device_id: str,
    body: HeartbeatPayload,
    db: AsyncSession = Depends(get_db),
    device: Device = Depends(get_device_from_bearer),
):
    """Update last_seen and optionally sync service states.

    The device authenticates with its long-lived opaque bearer token.
    The `device_id` path param must match the token's device record.
    """
    if device.device_id != device_id:
        raise HTTPException(status_code=403, detail="Token device_id mismatch")

    device.last_seen = datetime.now(UTC)
    if body.agent_version:
        device.agent_version = body.agent_version
    if body.os_info:
        device.os_info = {**(device.os_info or {}), **body.os_info}

    # Update known service unit states
    if body.service_states:
        for unit_name, state in body.service_states.items():
            service_id = f"{device_id}:{unit_name}"
            unit = await db.get(ServiceUnit, service_id)
            if unit is None:
                unit = ServiceUnit(
                    service_id=service_id,
                    device_id=device_id,
                    unit_name=unit_name,
                )
                db.add(unit)
            unit.state = state
            unit.updated_at = datetime.now(UTC)
            if state == "failed":
                unit.last_failure = datetime.now(UTC)
                unit.restart_count = (unit.restart_count or 0) + 1


# ──────────────────────────────────────────────────────
# Device token issuance — called by firstboot.sh after using provision token
# ──────────────────────────────────────────────────────

_provision_bearer = HTTPBearer(auto_error=True)


@router.post("/{device_id}/token")
async def issue_device_token(
    device_id: str,
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(_provision_bearer),
    db: AsyncSession = Depends(get_db),
):
    """Issue a long-lived opaque device token.

    Authentication: provision JWT (technician) OR operator JWT.
    - Provision JWT: single-use, device_id must be in allowed_device_ids.
    - Operator JWT: idempotent, can re-issue at any time.
    """
    from jose import JWTError
    from app.services.token import decode_token

    raw_token = credentials.credentials

    # Determine caller identity
    caller_sub = "unknown"
    is_provision_token = False
    provision_token_hash: str | None = None

    try:
        payload = decode_token(raw_token)
        caller_sub = payload.sub
        if payload.role == "technician":
            is_provision_token = True
            if device_id not in (payload.allowed_device_ids or []):
                raise HTTPException(
                    status_code=403,
                    detail=f"Provision token not scoped to device {device_id}",
                )
            provision_token_hash = hash_token(raw_token)
        elif payload.role not in ("operator",):
            raise HTTPException(status_code=403, detail="Insufficient role")
    except JWTError as exc:
        raise HTTPException(status_code=401, detail="Invalid token") from exc

    # Verify device exists
    device = await db.get(Device, device_id)
    if device is None:
        raise HTTPException(status_code=404, detail="Device not found")

    # If provision token: validate it exists in DB, not used, not expired
    if is_provision_token and provision_token_hash:
        pt = await db.get(ProvisionToken, provision_token_hash)
        if pt is None:
            raise HTTPException(status_code=401, detail="Provision token not found")
        if pt.used_at is not None:
            raise HTTPException(status_code=409, detail="Provision token already used")
        if pt.expires_at < datetime.now(UTC):
            raise HTTPException(status_code=401, detail="Provision token expired")
        pt.used_at = datetime.now(UTC)

    # Generate new device token
    new_token = generate_device_token()
    device.device_token_hash = hash_token(new_token)

    await write_audit_event(
        db,
        action="device.token_issued",
        actor=caller_sub,
        target={"type": "device", "id": device_id},
        ip_address=request.client.host if request.client else None,
    )

    return {"device_id": device_id, "device_token": new_token}
