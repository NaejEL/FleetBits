from datetime import datetime

from pydantic import BaseModel, ConfigDict


class ServiceUnitRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    service_id: str
    device_id: str
    unit_name: str
    current_version: str | None = None
    state: str | None = None
    restart_count: int = 0
    last_failure: datetime | None = None
    updated_at: datetime | None = None


class DeviceBase(BaseModel):
    device_id: str
    zone_id: str | None = None
    site_id: str | None = None
    shared_zones: list[str] | None = None
    role: str
    hostname: str
    local_ip: str | None = None
    headscale_ip: str | None = None
    os_info: dict | None = None
    ring: int | None = None


class DeviceCreate(DeviceBase):
    agent_version: str | None = None


class DeviceUpdate(BaseModel):
    zone_id: str | None = None
    site_id: str | None = None
    shared_zones: list[str] | None = None
    role: str | None = None
    hostname: str | None = None
    local_ip: str | None = None
    headscale_ip: str | None = None
    os_info: dict | None = None
    ring: int | None = None
    agent_version: str | None = None


class DeviceRead(DeviceBase):
    model_config = ConfigDict(from_attributes=True)

    last_seen: datetime | None = None
    agent_version: str | None = None


class HeartbeatPayload(BaseModel):
    """Sent by fleet-agent heartbeat.sh — updates last_seen. All fields optional."""

    agent_version: str | None = None
    # systemd unit states: {unit_name: state}
    service_states: dict[str, str] | None = None
    # Free-form host metrics snapshot — stored in os_info
    os_info: dict | None = None
