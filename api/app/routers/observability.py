"""Observability proxy — forwards queries to Prometheus, Loki, and Alertmanager."""

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import get_db
from app.dependencies import get_current_user
from app.services.token import TokenPayload

router = APIRouter(tags=["observability"])

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
    _user: TokenPayload = Depends(get_current_user),
):
    """Return systemd unit states from Prometheus for a zone or site."""
    filters = 'state="failed"'
    if zone:
        filters += f',zone="{zone}"'
    if site:
        filters += f',site="{site}"'
    prom_query = f"systemd_unit_state{{{filters}}}"
    return await _prom_query(prom_query)


@router.get("/query/device-metrics/{device_id}")
async def query_device_metrics(
    device_id: str,
    range: str = "1h",
    _user: TokenPayload = Depends(get_current_user),
):
    """Return node exporter metrics for a device over a time range."""
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
    device_id: str | None = None,
    service: str | None = None,
    since: str = "30m",
    _user: TokenPayload = Depends(get_current_user),
):
    """Proxy a LogQL query to Loki."""
    filters = []
    if device_id:
        filters.append(f'device_id="{device_id}"')
    if service:
        filters.append(f'service="{service}"')
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
    _user: TokenPayload = Depends(get_current_user),
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

    # Client-side filter by site label if requested
    if site:
        alerts = [a for a in alerts if a.get("labels", {}).get("site") == site]

    return alerts
