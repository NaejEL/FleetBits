"""Observability proxy — forwards queries to Prometheus, Loki, and Alertmanager."""

import re

import httpx
from fastapi import APIRouter, Depends, HTTPException, Path, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import get_db
from app.dependencies import get_current_user
from app.models.device import Device
from app.models.zone import Zone
from app.services.token import TokenPayload

router = APIRouter(tags=["observability"])

# Strict label validation to prevent PromQL/LogQL injection
_LABEL_VALUE_RE = re.compile(r"^[a-zA-Z0-9_.:-]{1,128}$")


def _validate_label_value(value: str, field_name: str) -> str:
    if not _LABEL_VALUE_RE.match(value):
        raise HTTPException(status_code=400, detail=f"Invalid {field_name} format")
    return value


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


async def _get_scoped_zone(db: AsyncSession, zone_id: str, user: TokenPayload) -> Zone | None:
    zone = await db.get(Zone, zone_id)
    if zone is None:
        return None
    if _is_site_scoped_user(user) and zone.site_id != user.site_scope:
        return None
    return zone

# ──────────────────────────────────────────────────────
# Prometheus proxy helpers
# ──────────────────────────────────────────────────────

async def _prom_query(query: str, timeout: float = 10.0) -> dict:
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.get(
            f"{settings.PROMETHEUS_URL}/api/v1/query",
            params={"query": query},
        )
    if resp.status_code != 200:
        raise HTTPException(status_code=502, detail=f"Prometheus error {resp.status_code}")
    return resp.json()


async def _prom_query_range(query: str, start: str, end: str, step: str = "60s") -> dict:
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(
            f"{settings.PROMETHEUS_URL}/api/v1/query_range",
            params={"query": query, "start": start, "end": end, "step": step},
        )
    if resp.status_code != 200:
        raise HTTPException(status_code=502, detail=f"Prometheus error {resp.status_code}")
    return resp.json()


# ──────────────────────────────────────────────────────
# Observability query endpoints
# ──────────────────────────────────────────────────────

@router.get("/query/service-health")
async def query_service_health(
    zone: str | None = None,
    site: str | None = None,
    db: AsyncSession = Depends(get_db),
    user: TokenPayload = Depends(get_current_user),
):
    """Return systemd unit states from Prometheus for a zone or site."""
    filters = 'state="failed"'
    scoped_site: str | None = None
    if _is_site_scoped_user(user):
        if site and site != user.site_scope:
            raise HTTPException(status_code=404, detail="Site not found")
        scoped_site = user.site_scope
    elif site:
        scoped_site = _validate_label_value(site, "site")

    if zone:
        zone = _validate_label_value(zone, "zone")
        zone_obj = await _get_scoped_zone(db, zone, user)
        if zone_obj is None:
            raise HTTPException(status_code=404, detail="Zone not found")
        filters += f',zone="{zone}"'
    if scoped_site:
        filters += f',site="{scoped_site}"'
    prom_query = f"systemd_unit_state{{{filters}}}"
    return await _prom_query(prom_query)


@router.get("/query/device-metrics/{device_id}")
async def query_device_metrics(
    device_id: str = Path(..., description="Device ID", pattern=r"^[a-zA-Z0-9_.:-]{1,128}$"),
    range: str = "1h",
    db: AsyncSession = Depends(get_db),
    user: TokenPayload = Depends(get_current_user),
):
    """Return node exporter metrics for a device over a time range."""
    device = await _get_scoped_device(db, device_id, user)
    if device is None:
        raise HTTPException(status_code=404, detail="Device not found")

    # CPU idle  → CPU usage =  1 - idle rate
    cpu_query = (
        f'100 - (avg by (device_id) '
        f'(rate(node_cpu_seconds_total{{mode="idle",device_id="{device_id}"}}[5m])) * 100)'
    )
    mem_query = (
        f'1 - (node_memory_MemAvailable_bytes{{device_id="{device_id}"}} '
        f'/ node_memory_MemTotal_bytes{{device_id="{device_id}"}})'
    )
    disk_query = (
        f'(node_filesystem_free_bytes{{device_id="{device_id}",mountpoint="/"}} '
        f'/ node_filesystem_size_bytes{{device_id="{device_id}",mountpoint="/"}})'
    )
    cpu = await _prom_query(cpu_query)
    mem = await _prom_query(mem_query)
    disk = await _prom_query(disk_query)
    return {"cpu_usage": cpu, "memory_usage": mem, "disk_free_ratio": disk}


@router.get("/query/recent-logs")
async def query_recent_logs(
    device_id: str | None = Query(None, pattern=r"^[a-zA-Z0-9_.:-]{1,128}$"),
    service: str | None = Query(None, pattern=r"^[a-zA-Z0-9_.:@-]{1,128}$"),
    since: str = "30m",
    db: AsyncSession = Depends(get_db),
    user: TokenPayload = Depends(get_current_user),
):
    """Proxy a LogQL query to Loki."""
    filters = []
    if device_id:
        device = await _get_scoped_device(db, device_id, user)
        if device is None:
            raise HTTPException(status_code=404, detail="Device not found")
        filters.append(f'device_id="{device_id}"')
    if service:
        filters.append(f'service="{service}"')
    if _is_site_scoped_user(user):
        filters.append(f'site="{user.site_scope}"')
    label_selector = "{" + ",".join(filters) + "}" if filters else "{}"
    logql = label_selector

    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(
            f"{settings.LOKI_URL}/loki/api/v1/query_range",
            params={"query": logql, "since": since, "limit": 200},
        )
    if resp.status_code != 200:
        raise HTTPException(status_code=502, detail=f"Loki error {resp.status_code}")
    return resp.json()


# ──────────────────────────────────────────────────────
# Alerts — proxy from Alertmanager
# ──────────────────────────────────────────────────────

@router.get("/alerts")
async def list_alerts(
    status: str | None = Query(None, description="open | resolved"),
    site: str | None = None,
    user: TokenPayload = Depends(get_current_user),
):
    """Proxy active alerts from Alertmanager, optionally filtered by site label."""
    params: dict = {}
    if status == "open":
        params["active"] = "true"
        params["silenced"] = "false"
    elif status == "resolved":
        params["active"] = "false"

    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(
            f"{settings.ALERTMANAGER_URL}/api/v2/alerts",
            params=params,
        )
    if resp.status_code != 200:
        raise HTTPException(status_code=502, detail=f"Alertmanager error {resp.status_code}")

    alerts = resp.json()

    if _is_site_scoped_user(user):
        if site and site != user.site_scope:
            raise HTTPException(status_code=404, detail="Site not found")
        site = user.site_scope

    # Client-side filter by site label if requested
    if site:
        alerts = [a for a in alerts if a.get("labels", {}).get("site") == site]

    return alerts
