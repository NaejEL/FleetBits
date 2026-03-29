"""Authenticated telemetry ingest proxy.

This router receives edge-device telemetry over public endpoints (via Caddy rewrite),
authenticates the device bearer token, rewrites authoritative identity labels from
the Device DB record, then forwards payloads to internal Prometheus/Loki.
"""

import logging
import re
from typing import Final, Mapping

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.dependencies import get_current_user, get_device_from_bearer
from app.db import get_db
from app.models.device import Device
from app.services.telemetry_rewrite import (
    TelemetryRewriteUnavailable,
    rewrite_loki_payload,
    rewrite_prometheus_payload,
)
from app.services.token import TokenPayload, hash_token

logger = logging.getLogger(__name__)

router = APIRouter(tags=["telemetry"])

_ALLOWED_FORWARD_HEADERS = {
    "content-type",
    "content-encoding",
    "x-prometheus-remote-write-version",
    "user-agent",
}


def _extract_forward_headers(headers: Mapping[str, str]) -> dict[str, str]:
    """Return a sanitized subset of inbound headers for upstream forwarding."""
    return {
        key: value
        for key, value in headers.items()
        if key.lower() in _ALLOWED_FORWARD_HEADERS
    }


def _build_upstream_response(resp: httpx.Response) -> Response:
    """Build a FastAPI response preserving upstream status/body/content-type."""
    content_type = resp.headers.get("content-type")
    return Response(
        content=resp.content,
        status_code=resp.status_code,
        media_type=content_type,
    )


async def _authenticate_ingest_device_or_401(request: Request, db: AsyncSession) -> Device | None:
    """Authenticate a telemetry ingest request from Authorization: Bearer <device-token>."""
    if not settings.TELEMETRY_AUTH_REQUIRED:
        return None

    auth_header = request.headers.get("authorization")
    if not auth_header or not auth_header.lower().startswith("bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    raw_token = auth_header.split(" ", 1)[1].strip()
    token_hash = hash_token(raw_token)

    result = await db.execute(select(Device).where(Device.device_token_hash == token_hash))
    device = result.scalar_one_or_none()
    if device is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid device token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return device


@router.api_route("/telemetry/authz", methods=["GET", "POST", "HEAD"])
async def telemetry_authz(device: Device = Depends(get_device_from_bearer)):
    """Authorization endpoint for edge telemetry requests.

    Can be used by reverse proxies for forward-auth and by operators for diagnostics.
    """
    return {
        "ok": True,
        "device_id": device.device_id,
        "site_id": device.site_id,
        "zone_id": device.zone_id,
    }


@router.post("/telemetry/metrics/write")
async def ingest_metrics(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Authenticated proxy for Prometheus remote_write payloads.

    Identity labels are canonicalized from the Device DB record before
    the payload is forwarded to Prometheus.
    """
    device = await _authenticate_ingest_device_or_401(request, db)

    payload = await request.body()

    if device is not None:
        try:
            payload = rewrite_prometheus_payload(
                payload,
                device.device_id,
                device.site_id,
                device.zone_id,
                device.hostname,
            )
        except TelemetryRewriteUnavailable as exc:
            logger.error("Prometheus telemetry rewrite unavailable: %s", exc)
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Telemetry label rewrite unavailable; check server dependencies",
            )
        except ValueError as exc:
            logger.warning(
                "Prometheus label rewrite failed for device %s: %s",
                device.device_id,
                exc,
            )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid or unrecognised telemetry payload format",
            )

    headers = _extract_forward_headers(request.headers)

    async with httpx.AsyncClient(timeout=settings.TELEMETRY_PROXY_TIMEOUT_SECONDS) as client:
        resp = await client.post(
            f"{settings.PROMETHEUS_URL}/api/v1/write",
            content=payload,
            headers=headers,
        )

    if resp.status_code >= status.HTTP_500_INTERNAL_SERVER_ERROR:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Prometheus ingest upstream error {resp.status_code}",
        )

    return _build_upstream_response(resp)


@router.post("/telemetry/logs/push")
async def ingest_logs(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Authenticated proxy for Loki push payloads.

    Stream identity labels are canonicalized from the Device DB record
    before the payload is forwarded to Loki.
    """
    device = await _authenticate_ingest_device_or_401(request, db)

    payload = await request.body()

    if device is not None:
        try:
            payload = rewrite_loki_payload(
                payload,
                request.headers.get("content-type", ""),
                request.headers.get("content-encoding", ""),
                device.device_id,
                device.site_id,
                device.zone_id,
                device.hostname,
            )
        except TelemetryRewriteUnavailable as exc:
            logger.error("Loki telemetry rewrite unavailable: %s", exc)
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Telemetry label rewrite unavailable; check server dependencies",
            )
        except ValueError as exc:
            logger.warning(
                "Loki label rewrite failed for device %s: %s",
                device.device_id,
                exc,
            )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid or unrecognised telemetry payload format",
            )

    headers = _extract_forward_headers(request.headers)

    async with httpx.AsyncClient(timeout=settings.TELEMETRY_PROXY_TIMEOUT_SECONDS) as client:
        resp = await client.post(
            f"{settings.LOKI_URL}/loki/api/v1/push",
            content=payload,
            headers=headers,
        )

    if resp.status_code >= status.HTTP_500_INTERNAL_SERVER_ERROR:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Loki ingest upstream error {resp.status_code}",
        )

    return _build_upstream_response(resp)


# ── Telemetry query proxy ─────────────────────────────────────────────────────
# Authenticates human operators (JWT) and enforces site-scope isolation:
# - Admin users (site_scope=None): unrestricted pass-through
# - Site-scoped operators: site label injected into every selector; cross-site
#   selectors are rejected with HTTP 403

# Matches any site label matcher inside a PromQL/LogQL selector
_SITE_SELECTOR_RE: Final = re.compile(r'site\s*(=~?|!=|!~)\s*"([^"]*)"')
# Matches any selector block {...}
_SELECTOR_BLOCK_RE: Final = re.compile(r'\{([^}]*)\}')


def _enforce_site_scope(query: str, site_scope: str | None) -> str:
    """Validate and inject a site scope constraint into a PromQL/LogQL query.

    - If ``site_scope`` is None (admin): returns the query unmodified.
    - Raises HTTP 403 if the query contains a ``site`` label that targets a
      different site or uses a negative matcher (!=, !~).
    - Otherwise injects ``site="<site_scope>"`` into every ``{...}`` selector
      block, or appends ``{site="<site_scope>"}`` if no selector is present.
    """
    if site_scope is None:
        return query

    for m in _SITE_SELECTOR_RE.finditer(query):
        op = m.group(1)
        if op in ("!=", "!~"):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Negative site label selectors are not permitted for scoped users",
            )
        val = m.group(2)
        if val != site_scope:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Cross-site query denied: site={val!r} is outside your scope ({site_scope!r})",
            )

    def _inject(m: re.Match) -> str:
        inner = m.group(1).strip()
        if _SITE_SELECTOR_RE.search(inner):
            return m.group(0)  # site already present — keep as-is
        if inner:
            return f'{{{inner},site="{site_scope}"}}'
        return f'{{site="{site_scope}"}}'

    if _SELECTOR_BLOCK_RE.search(query):
        return _SELECTOR_BLOCK_RE.sub(_inject, query)

    # Bare metric name or function with no selector — append site constraint
    return query + f'{{site="{site_scope}"}}'


@router.get("/telemetry/metrics/query")
async def query_metrics_instant(
    request: Request,
    user: TokenPayload = Depends(get_current_user),
):
    """Prometheus instant-query proxy with site-scope enforcement."""
    params = dict(request.query_params)
    if "query" not in params:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing required 'query' parameter")
    params["query"] = _enforce_site_scope(params["query"], user.site_scope)
    async with httpx.AsyncClient(timeout=settings.TELEMETRY_PROXY_TIMEOUT_SECONDS) as c:
        resp = await c.get(f"{settings.PROMETHEUS_URL}/api/v1/query", params=params)
    return _build_upstream_response(resp)


@router.get("/telemetry/metrics/query_range")
async def query_metrics_range(
    request: Request,
    user: TokenPayload = Depends(get_current_user),
):
    """Prometheus range-query proxy with site-scope enforcement."""
    params = dict(request.query_params)
    if "query" not in params:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing required 'query' parameter")
    params["query"] = _enforce_site_scope(params["query"], user.site_scope)
    async with httpx.AsyncClient(timeout=settings.TELEMETRY_PROXY_TIMEOUT_SECONDS) as c:
        resp = await c.get(f"{settings.PROMETHEUS_URL}/api/v1/query_range", params=params)
    return _build_upstream_response(resp)


@router.get("/telemetry/logs/query")
async def query_logs_instant(
    request: Request,
    user: TokenPayload = Depends(get_current_user),
):
    """Loki instant-query proxy with site-scope enforcement."""
    params = dict(request.query_params)
    if "query" not in params:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing required 'query' parameter")
    params["query"] = _enforce_site_scope(params["query"], user.site_scope)
    async with httpx.AsyncClient(timeout=settings.TELEMETRY_PROXY_TIMEOUT_SECONDS) as c:
        resp = await c.get(f"{settings.LOKI_URL}/loki/api/v1/query", params=params)
    return _build_upstream_response(resp)


@router.get("/telemetry/logs/query_range")
async def query_logs_range(
    request: Request,
    user: TokenPayload = Depends(get_current_user),
):
    """Loki range-query proxy with site-scope enforcement."""
    params = dict(request.query_params)
    if "query" not in params:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing required 'query' parameter")
    params["query"] = _enforce_site_scope(params["query"], user.site_scope)
    async with httpx.AsyncClient(timeout=settings.TELEMETRY_PROXY_TIMEOUT_SECONDS) as c:
        resp = await c.get(f"{settings.LOKI_URL}/loki/api/v1/query_range", params=params)
    return _build_upstream_response(resp)
