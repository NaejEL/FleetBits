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
    profile_id: str | None = None
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
    profile_id: str | None = None
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
    mqtt_username: str | None = None
    mqtt_credentials_issued_at: datetime | None = None


class DeviceRepoKeyUpdate(BaseModel):
    public_key: str
    key_fingerprint: str | None = None


class DeviceRepoKeyRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    device_id: str
    repo_public_key: str | None = None
    repo_key_fingerprint: str | None = None
    repo_key_updated_at: datetime | None = None


class DeviceIdentity(BaseModel):
    """Device identity file (device-identity.conf) with enrollment secrets.
    
    Returned by POST /devices/provision endpoint.
    Written by agent as shell-sourceable env vars during first-boot.
    """
    DEVICE_ID: str
    SITE_ID: str
    ZONE_ID: str
    DEVICE_ROLE: str
    PROFILE: str | None = None
    FLEET_AGENT_TOKEN: str
    # Separate credential scoped exclusively to APT repository access.
    # Stored separately from FLEET_AGENT_TOKEN so APT auth compromise does not
    # grant access to the fleet API and vice versa.
    REPO_BASIC_TOKEN: str
    FLEET_METRICS_URL: str
    FLEET_LOGS_URL: str
    HEADSCALE_PREAUTH_KEY: str | None = None
    MQTT_BROKER_HOST: str = "mosquitto"
    MQTT_BROKER_PORT: int = 1883
    MQTT_USERNAME: str
    MQTT_PASSWORD: str


class HeartbeatPayload(BaseModel):
    """Sent by fleet-agent heartbeat.sh — updates last_seen. All fields optional."""

    agent_version: str | None = None
    # systemd unit states: {unit_name: state}
    service_states: dict[str, str] | None = None
    # Free-form host metrics snapshot — stored in os_info
    os_info: dict | None = None
