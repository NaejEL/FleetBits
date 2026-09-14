"""Observability proxy — forwards queries to Prometheus, Loki, and Alertmanager."""

import re
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, Path, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import get_db
from app.dependencies import get_current_user
from app.models.device import Device
from app.models.zone import Zone
from app.routers._scope import require_site_scope
from app.services.token import TokenPayload

router = APIRouter(tags=["observability"])

# Strict label validation to prevent PromQL/LogQL injection
# ``\Z`` and not ``$``: ``$`` also matches just before a trailing newline, so
# ``site-a\n`` would pass this check and be interpolated into a server-built
# expression with the newline still on it.
_LABEL_VALUE_RE = re.compile(r"^[a-zA-Z0-9_.:-]{1,128}\Z")


def _validate_label_value(value: str, field_name: str) -> str:
    if not _LABEL_VALUE_RE.match(value):
        raise HTTPException(status_code=400, detail=f"Invalid {field_name} format")
    return value


def _scoped_site(user: TokenPayload) -> str | None:
    """Return the caller's confining site, validated as a label value.

    ``site_scope`` reaches this module from the token, and the token from
    ``users.site_scope``, an unconstrained ``Text`` column. Every server-built
    PromQL/LogQL expression below interpolates that string between double
    quotes, so a scope such as ``site-a",job=~".*`` would close the selector
    early and widen the expression to the whole fleet — exactly the injection
    ``_validate_label_value`` already prevents on a client-supplied ``site``.

    A scope that is not a well-formed label value is therefore refused here,
    before any expression is built, rather than trusted for being server-side.
    """
    scope = require_site_scope(user)
    if scope is not None:
        _validate_label_value(scope, "site scope")
    return scope


async def _get_scoped_device(db: AsyncSession, device_id: str, user: TokenPayload) -> Device | None:
    scope = _scoped_site(user)
    result = await db.execute(select(Device).where(Device.device_id == device_id))
    device = result.scalar_one_or_none()
    if device is None:
        return None
    if scope is None:
        return device
    site_id = device.site_id
    if site_id is None and device.zone_id:
        zone = await db.get(Zone, device.zone_id)
        site_id = zone.site_id if zone else None
    if site_id != scope:
        return None
    return device


async def _get_scoped_zone(db: AsyncSession, zone_id: str, user: TokenPayload) -> Zone | None:
    scope = _scoped_site(user)
    zone = await db.get(Zone, zone_id)
    if zone is None:
        return None
    if scope is not None and zone.site_id != scope:
        return None
    return zone

# ──────────────────────────────────────────────────────
# Prometheus proxy helpers
# ──────────────────────────────────────────────────────

async def _upstream_get(upstream: str, url: str, params: dict, timeout: float) -> Any:
    """GET an observability backend and normalise every failure to 502.

    A backend that is unreachable, times out, or resets the connection is a
    *gateway* failure, not a server fault of this API: httpx raises
    ``httpx.RequestError`` in those cases and, left uncaught, it escapes the
    route as an unhandled exception (a raw 500 in production, and a propagated
    ``ConnectError`` under the test transport). Mapping it here keeps a single
    contract for callers: any upstream trouble is a 502.
    """
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.get(url, params=params)
    except httpx.RequestError as exc:
        raise HTTPException(
            status_code=502, detail=f"{upstream} unreachable: {type(exc).__name__}"
        ) from exc
    if resp.status_code != 200:
        raise HTTPException(status_code=502, detail=f"{upstream} error {resp.status_code}")
    return resp.json()


async def _prom_query(query: str, timeout: float = 10.0) -> dict:
    return await _upstream_get(
        "Prometheus",
        f"{settings.PROMETHEUS_URL}/api/v1/query",
        {"query": query},
        timeout,
    )


async def _prom_query_range(query: str, start: str, end: str, step: str = "60s") -> dict:
    return await _upstream_get(
        "Prometheus",
        f"{settings.PROMETHEUS_URL}/api/v1/query_range",
        {"query": query, "start": start, "end": end, "step": step},
        30.0,
    )


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
    scope = _scoped_site(user)
    filters = 'state="failed"'
    scoped_site: str | None = None
    if scope is not None:
        if site and site != scope:
            raise HTTPException(status_code=404, detail="Site not found")
        scoped_site = scope
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
    scope = _scoped_site(user)
    filters = []
    if device_id:
        device = await _get_scoped_device(db, device_id, user)
        if device is None:
            raise HTTPException(status_code=404, detail="Device not found")
        filters.append(f'device_id="{device_id}"')
    if service:
        filters.append(f'service="{service}"')
    if scope is not None:
        filters.append(f'site="{scope}"')
    label_selector = "{" + ",".join(filters) + "}" if filters else "{}"
    logql = label_selector

    return await _upstream_get(
        "Loki",
        f"{settings.LOKI_URL}/loki/api/v1/query_range",
        {"query": logql, "since": since, "limit": 200},
        15.0,
    )


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
    scope = _scoped_site(user)

    # Settle the scope *before* reaching Alertmanager. The predicate already ran
    # above, but the cross-site rejection used to run after the fetch, so a
    # site-a token asking for ?site=site-b still caused a real upstream request
    # before its 404. Nothing leaked, yet the request was made on behalf of a
    # caller that had no right to the answer; deciding first keeps the rejection
    # free of any upstream side effect.
    if scope is not None:
        if site and site != scope:
            raise HTTPException(status_code=404, detail="Site not found")
        site = scope

    params: dict = {}
    if status == "open":
        params["active"] = "true"
        params["silenced"] = "false"
    elif status == "resolved":
        params["active"] = "false"

    alerts = await _upstream_get(
        "Alertmanager",
        f"{settings.ALERTMANAGER_URL}/api/v2/alerts",
        params,
        10.0,
    )

    # Client-side filter by site label if requested
    if site:
        alerts = [a for a in alerts if a.get("labels", {}).get("site") == site]

    return alerts
