from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.dependencies import get_current_user, get_device_from_bearer, require_roles
from app.models.device import Device, ServiceUnit
from app.models.token import ProvisionToken
from app.schemas.device import (
    DeviceCreate,
    DeviceIdentity,
    DeviceRead,
    DeviceRepoKeyRead,
    DeviceRepoKeyUpdate,
    DeviceUpdate,
    HeartbeatPayload,
    ServiceUnitRead,
)
from app.services.audit import write_audit_event
from app.services.token import (
    TokenPayload,
    decode_provision_token,
    generate_device_token,
    hash_token,
    generate_mqtt_credentials,
    hash_mqtt_password,
)

router = APIRouter(prefix="/devices", tags=["devices"])

# ──────────────────────────────────────────────────────
# Service units (scoped query at /services, not /devices)
# ──────────────────────────────────────────────────────

services_router = APIRouter(prefix="/services", tags=["services"])


def _is_site_scoped_user(user: TokenPayload) -> bool:
    return user.role != "admin" and bool(user.site_scope)


def _apply_device_scope(query, user: TokenPayload):
    if _is_site_scoped_user(user):
        return query.where(Device.site_id == user.site_scope)
    return query


async def _get_scoped_device(db: AsyncSession, device_id: str, user: TokenPayload) -> Device | None:
    q = select(Device).where(Device.device_id == device_id)
    q = _apply_device_scope(q, user)
    result = await db.execute(q)
    return result.scalar_one_or_none()


def _is_valid_ssh_public_key(value: str) -> bool:
    parts = value.strip().split()
    if len(parts) < 2:
        return False
    return parts[0] in {"ssh-ed25519", "ssh-rsa", "ecdsa-sha2-nistp256", "ecdsa-sha2-nistp384"}


@services_router.get("", response_model=list[ServiceUnitRead])
async def list_services(
    device_id: str | None = None,
    state: str | None = None,
    db: AsyncSession = Depends(get_db),
    user: TokenPayload = Depends(get_current_user),
):
    q = select(ServiceUnit).join(Device, ServiceUnit.device_id == Device.device_id)
    if device_id:
        q = q.where(ServiceUnit.device_id == device_id)
    if state:
        q = q.where(ServiceUnit.state == state)
    q = _apply_device_scope(q, user)
    result = await db.execute(q)
    return result.scalars().all()


# ──────────────────────────────────────────────────────
# Device provisioning — called by firstboot.sh during enrollment
# ──────────────────────────────────────────────────────

_provision_bearer = HTTPBearer(auto_error=True)


@router.post("/{device_id}/provision", response_model=DeviceIdentity)
async def provision_device(
    device_id: str,
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(_provision_bearer),
    db: AsyncSession = Depends(get_db),
):
    """Issue device-identity.conf during first-boot enrollment.

    Authentication: provision JWT (technician) with device_id in allowed_device_ids.
    
    Returns all environment variables needed for /etc/fleet/device-identity.conf,
    including MQTT credentials generated at provisioning time.
    """
    from jose import JWTError
    from app.services.token import decode_token

    raw_token = credentials.credentials

    # Validate provision token — JWT claims + DB single-use check
    try:
        payload = decode_token(raw_token)
        if payload.role != "technician":
            raise HTTPException(status_code=403, detail="Invalid token role")
        if device_id not in (payload.allowed_device_ids or []):
            raise HTTPException(
                status_code=403,
                detail=f"Provision token not scoped to device {device_id}",
            )
    except JWTError as exc:
        raise HTTPException(status_code=401, detail="Invalid provision token") from exc

    # Single-use enforcement: look up (and consume) the ProvisionToken DB record
    provision_token_hash = hash_token(raw_token)
    pt = await db.get(ProvisionToken, provision_token_hash)
    if pt is None:
        raise HTTPException(status_code=401, detail="Provision token not found")
    if pt.used_at is not None:
        raise HTTPException(status_code=409, detail="Provision token already used")
    if pt.expires_at < datetime.now(UTC):
        raise HTTPException(status_code=401, detail="Provision token expired")
    pt.used_at = datetime.now(UTC)

    # Fetch device
    device = await db.get(Device, device_id)
    if device is None:
        raise HTTPException(status_code=404, detail="Device not found")

    # Fetch zone and site for identity
    zone_id = device.zone_id or "default"
    site_id = device.site_id or "default"

    # Get observability URLs from config
    from app.config import settings
    metrics_url = f"https://prometheus.{settings.FLEET_DOMAIN}"
    logs_url = f"https://loki.{settings.FLEET_DOMAIN}"

    # Generate MQTT credentials for this device
    mqtt_username, mqtt_password = generate_mqtt_credentials(device_id)

    # Store MQTT credentials in device record (will be finalized by token endpoint)
    device.mqtt_username = mqtt_username
    device.mqtt_password_hash = hash_mqtt_password(mqtt_password)
    device.mqtt_credentials_issued_at = datetime.now(UTC)

    await write_audit_event(
        db,
        action="device.provisioned",
        actor=payload.sub,
        actor_role="technician",
        target={"type": "device", "id": device_id},
        ip_address=request.client.host if request.client else None,
    )

    # Generate a temporary bearer token for the agent to use when calling /token endpoint.
    # Store the hash so the agent can authenticate immediately; /token will replace this.
    temp_bearer_token = generate_device_token()
    device.device_token_hash = hash_token(temp_bearer_token)

    return DeviceIdentity(
        DEVICE_ID=device_id,
        SITE_ID=site_id,
        ZONE_ID=zone_id,
        DEVICE_ROLE=device.role,
        PROFILE=device.profile_id,
        FLEET_AGENT_TOKEN=temp_bearer_token,
        FLEET_METRICS_URL=metrics_url,
        FLEET_LOGS_URL=logs_url,
        HEADSCALE_PREAUTH_KEY=None,  # To be filled by operator portal
        MQTT_BROKER_HOST="mosquitto",
        MQTT_BROKER_PORT=1883,
        MQTT_USERNAME=mqtt_username,
        MQTT_PASSWORD=mqtt_password,
    )


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
    q = _apply_device_scope(q, user)
    result = await db.execute(q)
    return result.scalars().all()


@router.get("/{device_id}", response_model=DeviceRead)
async def get_device(
    device_id: str,
    db: AsyncSession = Depends(get_db),
    user: TokenPayload = Depends(get_current_user),
):
    device = await _get_scoped_device(db, device_id, user)
    if device is None:
        raise HTTPException(status_code=404, detail="Device not found")
    return device


@router.post("", response_model=DeviceRead, status_code=status.HTTP_201_CREATED)
async def create_device(
    body: DeviceCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: TokenPayload = Depends(require_roles("operator")),
):
    if _is_site_scoped_user(user) and user.site_scope != body.site_id:
        raise HTTPException(status_code=403, detail="Access denied")

    device = Device(**body.model_dump())
    db.add(device)
    try:
        await db.flush()
    except IntegrityError as exc:
        raise HTTPException(status_code=409, detail=f"Device {body.device_id} already exists") from exc
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
    device = await _get_scoped_device(db, device_id, user)
    if device is None:
        raise HTTPException(status_code=404, detail="Device not found")

    if _is_site_scoped_user(user) and body.site_id and body.site_id != user.site_scope:
        raise HTTPException(status_code=403, detail="Access denied")

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
    device = await _get_scoped_device(db, device_id, user)
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


@router.post("/{device_id}/repo-key/self", response_model=DeviceRepoKeyRead)
async def register_device_repo_key_self(
    device_id: str,
    body: DeviceRepoKeyUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    device: Device = Depends(get_device_from_bearer),
):
    """Register/rotate the device repository public key using device-token auth."""
    if device.device_id != device_id:
        raise HTTPException(status_code=403, detail="Token device_id mismatch")

    key = body.public_key.strip()
    if not _is_valid_ssh_public_key(key):
        raise HTTPException(status_code=400, detail="Invalid SSH public key format")

    device.repo_public_key = key
    device.repo_key_fingerprint = body.key_fingerprint
    device.repo_key_updated_at = datetime.now(UTC)

    await write_audit_event(
        db,
        action="device.repo_key_registered",
        actor=device.device_id,
        actor_role="device",
        target={"type": "device", "id": device.device_id},
        payload={
            "key_fingerprint": body.key_fingerprint,
            "source": "device-self",
        },
        ip_address=request.client.host if request.client else None,
    )

    return DeviceRepoKeyRead(
        device_id=device.device_id,
        repo_public_key=device.repo_public_key,
        repo_key_fingerprint=device.repo_key_fingerprint,
        repo_key_updated_at=device.repo_key_updated_at,
    )


@router.get("/{device_id}/repo-key", response_model=DeviceRepoKeyRead)
async def get_device_repo_key(
    device_id: str,
    db: AsyncSession = Depends(get_db),
    user: TokenPayload = Depends(require_roles("operator")),
):
    device = await _get_scoped_device(db, device_id, user)
    if device is None:
        raise HTTPException(status_code=404, detail="Device not found")

    return DeviceRepoKeyRead(
        device_id=device.device_id,
        repo_public_key=device.repo_public_key,
        repo_key_fingerprint=device.repo_key_fingerprint,
        repo_key_updated_at=device.repo_key_updated_at,
    )


# ──────────────────────────────────────────────────────
# Device token issuance — called by firstboot.sh after using provision token
# ──────────────────────────────────────────────────────

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
        elif payload.role not in ("operator", "admin"):
            raise HTTPException(status_code=403, detail="Insufficient role")
    except JWTError as exc:
        raise HTTPException(status_code=401, detail="Invalid token") from exc

    # Verify device exists and enforce site scoping for operator/admin callers.
    if payload.role in ("operator", "admin"):
        device = await _get_scoped_device(db, device_id, payload)
    else:
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
    
    # Generate per-device MQTT credentials
    mqtt_username, mqtt_password = generate_mqtt_credentials(device_id)
    device.mqtt_username = mqtt_username
    device.mqtt_password_hash = hash_mqtt_password(mqtt_password)
    device.mqtt_credentials_issued_at = datetime.now(UTC)

    await write_audit_event(
        db,
        action="device.token_issued",
        actor=caller_sub,
        target={"type": "device", "id": device_id},
        ip_address=request.client.host if request.client else None,
    )

    return {
        "device_id": device_id,
        "device_token": new_token,
        "mqtt_username": mqtt_username,
        "mqtt_password": mqtt_password,
    }


# ──────────────────────────────────────────────────────
# MQTT broker ACL management — called by mosquitto bootstrap
# ──────────────────────────────────────────────────────

@router.get("/mqtt/acl", response_model=dict)
async def get_mqtt_acl(
    db: AsyncSession = Depends(get_db),
    user: TokenPayload = Depends(require_roles("operator", "admin")),
):
    """Get MQTT ACL rules for all active devices.
    
    Returns a dict mapping mqtt_username -> list of allowed topics.
    Used by Mosquitto bootstrap to generate acl_file.
    
    Format:
        {
            "device_<device_id>": ["device/<device_id>/#", "$SYS/broker/clients/connected"],
            "fleet_exporter": ["$SYS/#"],
        }
    """
    q = select(Device).where(Device.mqtt_username.isnot(None))
    result = await db.execute(q)
    devices = result.scalars().all()
    
    acl = {}
    for device in devices:
        # Each device is restricted to its own topic namespace only.
        # The device/+/heartbeat wildcard was removed — it broke per-device isolation.
        acl[device.mqtt_username] = [
            f"device/{device.device_id}/#",
        ]

    # Exporter gets read-only access to $SYS
    acl["fleet_exporter"] = ["$SYS/#"]
    
    return acl
