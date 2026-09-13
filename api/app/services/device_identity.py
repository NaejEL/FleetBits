"""Build the device identity file handed to an enrolling device.

Single producer for the "server path" of the contract declared in
``app.contracts.device_identity``. The host names and paths below are the ones
actually exposed by ``FleetBits-platform/docker/caddy/Caddyfile``; changing one
without the other breaks ``tests/test_device_identity_contract.py``.
"""

from __future__ import annotations

from app.contracts.device_identity import render

#: Caddy site blocks that terminate TLS for the telemetry ingest endpoints.
METRICS_HOST_PREFIX = "metrics."
LOGS_HOST_PREFIX = "logs."
#: Path matchers declared inside those Caddy site blocks.
METRICS_PATH = "/api/v1/write"
LOGS_PATH = "/loki/api/v1/push"

#: Defaults for fields the control plane does not yet individualise per device.
DEFAULT_MQTT_BROKER_HOST = "mosquitto"
DEFAULT_MQTT_BROKER_PORT = "1883"
DEFAULT_SCRAPE_INTERVAL = "30s"


def metrics_url(fleet_domain: str) -> str:
    return f"https://{METRICS_HOST_PREFIX}{fleet_domain}{METRICS_PATH}"


def logs_url(fleet_domain: str) -> str:
    return f"https://{LOGS_HOST_PREFIX}{fleet_domain}{LOGS_PATH}"


def build_identity_values(
    *,
    device_id: str,
    site_id: str,
    zone_id: str,
    device_role: str,
    profile: str | None,
    ring: int | None,
    environment: str,
    fleet_api_url: str,
    fleet_domain: str,
    fleet_agent_token: str,
    repo_basic_token: str,
    mqtt_username: str,
    mqtt_password: str,
    headscale_preauth_key: str = "",
) -> dict[str, str]:
    """Return the full contract mapping for one device."""
    return {
        "DEVICE_ID": device_id,
        "SITE_ID": site_id,
        "ZONE_ID": zone_id,
        "DEVICE_ROLE": device_role,
        "PROFILE": profile or "",
        "ENVIRONMENT": environment,
        "RING": str(ring if ring is not None else 0),
        "FLEET_API_URL": fleet_api_url.rstrip("/"),
        "FLEET_METRICS_URL": metrics_url(fleet_domain),
        "FLEET_LOGS_URL": logs_url(fleet_domain),
        "FLEET_AGENT_TOKEN": fleet_agent_token,
        "REPO_BASIC_TOKEN": repo_basic_token,
        "HEADSCALE_PREAUTH_KEY": headscale_preauth_key,
        "MQTT_BROKER_HOST": DEFAULT_MQTT_BROKER_HOST,
        "MQTT_BROKER_PORT": DEFAULT_MQTT_BROKER_PORT,
        "MQTT_USERNAME": mqtt_username,
        "MQTT_PASSWORD": mqtt_password,
        "ENABLE_MQTT_EXPORTER": "false",
        "ENABLE_PROCESS_EXPORTER": "false",
        "SCRAPE_INTERVAL": DEFAULT_SCRAPE_INTERVAL,
    }


def render_identity_file(**kwargs: object) -> str:
    """Build and serialise the identity file in one step."""
    return render(build_identity_values(**kwargs))  # type: ignore[arg-type]
