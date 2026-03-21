"""
Fleet UI — API client.

Thin wrapper around requests that:
  - Reads the operator's JWT from the Flask session.
  - Adds it as a Bearer Authorization header.
  - Raises ApiError on non-2xx responses.
  - Redirects to /login on 401 (token expired or missing).
"""

from __future__ import annotations

import os

import requests
from flask import session

FLEET_API_URL = os.environ.get("FLEET_API_URL", "http://localhost:8000").rstrip("/")


class ApiError(Exception):
    """Raised when the Fleet API returns a non-2xx status code other than 401."""

    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


class Unauthorized(ApiError):
    """Raised on 401 — caller should redirect to /login."""


def _headers() -> dict[str, str]:
    token = session.get("jwt")
    h: dict[str, str] = {"Content-Type": "application/json"}
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


def _check(resp: requests.Response) -> requests.Response:
    if resp.status_code == 401:
        raise Unauthorized(401, "Session expired — please log in again.")
    if not resp.ok:
        try:
            detail = resp.json().get("detail", resp.text)
        except Exception:
            detail = resp.text
        raise ApiError(resp.status_code, detail)
    return resp


# ─── Auth ────────────────────────────────────────────────────────────────────

def login(username: str, password: str) -> str:
    """POST credentials to Fleet API, return raw JWT string."""
    resp = requests.post(
        f"{FLEET_API_URL}/api/v1/auth/login",
        json={"username": username, "password": password},
        timeout=10,
    )
    _check(resp)
    return resp.json()["access_token"]


# ─── Sites ───────────────────────────────────────────────────────────────────

def get_sites() -> list[dict]:
    return _check(requests.get(f"{FLEET_API_URL}/api/v1/sites", headers=_headers(), timeout=10)).json()


def get_site(site_id: str) -> dict:
    return _check(requests.get(f"{FLEET_API_URL}/api/v1/sites/{site_id}", headers=_headers(), timeout=10)).json()


# ─── Zones ───────────────────────────────────────────────────────────────────

def get_zones(site_id: str | None = None) -> list[dict]:
    params = {}
    if site_id:
        params["site_id"] = site_id
    return _check(requests.get(f"{FLEET_API_URL}/api/v1/zones", headers=_headers(), params=params, timeout=10)).json()


def get_zone(zone_id: str) -> dict:
    return _check(requests.get(f"{FLEET_API_URL}/api/v1/zones/{zone_id}", headers=_headers(), timeout=10)).json()


# ─── Devices ─────────────────────────────────────────────────────────────────

def get_devices(zone_id: str | None = None, site_id: str | None = None) -> list[dict]:
    params: dict = {}
    if zone_id:
        params["zone_id"] = zone_id
    if site_id:
        params["site_id"] = site_id
    return _check(requests.get(f"{FLEET_API_URL}/api/v1/devices", headers=_headers(), params=params, timeout=10)).json()


def get_device(device_id: str) -> dict:
    return _check(requests.get(f"{FLEET_API_URL}/api/v1/devices/{device_id}", headers=_headers(), timeout=10)).json()


def get_device_services(device_id: str) -> list[dict]:
    return _check(requests.get(f"{FLEET_API_URL}/api/v1/services", headers=_headers(), params={"device_id": device_id}, timeout=10)).json()


def get_device_manifest(device_id: str) -> dict:
    return _check(requests.get(f"{FLEET_API_URL}/api/v1/targets/{device_id}/manifest", headers=_headers(), timeout=10)).json()


# ─── Deployments ─────────────────────────────────────────────────────────────

def get_deployments() -> list[dict]:
    return _check(requests.get(f"{FLEET_API_URL}/api/v1/deployments", headers=_headers(), timeout=10)).json()


def get_deployment(deployment_id: str) -> dict:
    return _check(requests.get(f"{FLEET_API_URL}/api/v1/deployments/{deployment_id}", headers=_headers(), timeout=10)).json()


def create_deployment(payload: dict) -> dict:
    return _check(requests.post(f"{FLEET_API_URL}/api/v1/deployments", headers=_headers(), json=payload, timeout=10)).json()


def trigger_deployment(deployment_id: str) -> dict:
    return _check(requests.post(f"{FLEET_API_URL}/api/v1/deployments/{deployment_id}/trigger", headers=_headers(), timeout=30)).json()


def rollback_deployment(deployment_id: str) -> dict:
    return _check(requests.post(f"{FLEET_API_URL}/api/v1/deployments/{deployment_id}/rollback", headers=_headers(), timeout=30)).json()


# ─── Hotfixes ────────────────────────────────────────────────────────────────

def get_hotfixes() -> list[dict]:
    return _check(requests.get(f"{FLEET_API_URL}/api/v1/hotfixes", headers=_headers(), timeout=10)).json()


def get_hotfix(hotfix_id: str) -> dict:
    return _check(requests.get(f"{FLEET_API_URL}/api/v1/hotfixes/{hotfix_id}", headers=_headers(), timeout=10)).json()


def create_hotfix(payload: dict) -> dict:
    return _check(requests.post(f"{FLEET_API_URL}/api/v1/hotfixes", headers=_headers(), json=payload, timeout=10)).json()


def promote_hotfix(hotfix_id: str) -> dict:
    return _check(requests.post(f"{FLEET_API_URL}/api/v1/hotfixes/{hotfix_id}/promote", headers=_headers(), timeout=30)).json()


def revert_hotfix(hotfix_id: str) -> dict:
    return _check(requests.post(f"{FLEET_API_URL}/api/v1/hotfixes/{hotfix_id}/revert", headers=_headers(), timeout=30)).json()


def reconcile_ssh(payload: dict) -> dict:
    hotfix_id = payload.get("hotfix_id", "")
    return _check(requests.post(f"{FLEET_API_URL}/api/v1/hotfixes/{hotfix_id}/reconcile-ssh", headers=_headers(), json=payload, timeout=10)).json()


# ─── Operations ──────────────────────────────────────────────────────────────

def restart_service(device_id: str, service_name: str) -> dict:
    return _check(requests.post(
        f"{FLEET_API_URL}/api/v1/operations/restart-service",
        headers=_headers(),
        json={"device_id": device_id, "service_name": service_name},
        timeout=30,
    )).json()


def run_diagnostics(device_id: str) -> dict:
    return _check(requests.post(
        f"{FLEET_API_URL}/api/v1/operations/run-diagnostics",
        headers=_headers(),
        json={"device_id": device_id},
        timeout=60,
    )).json()


def collect_logs(device_id: str) -> dict:
    return _check(requests.post(
        f"{FLEET_API_URL}/api/v1/operations/collect-logs",
        headers=_headers(),
        json={"device_id": device_id},
        timeout=60,
    )).json()


# ─── Alerts ──────────────────────────────────────────────────────────────────

def get_alerts() -> list[dict]:
    return _check(requests.get(f"{FLEET_API_URL}/api/v1/alerts", headers=_headers(), timeout=10)).json()


# ─── Audit ───────────────────────────────────────────────────────────────────

def get_audit(actor: str | None = None, site_id: str | None = None,
              action: str | None = None, limit: int = 50, offset: int = 0) -> dict:
    params: dict = {"limit": limit, "offset": offset}
    if actor:
        params["actor"] = actor
    if site_id:
        params["siteId"] = site_id
    if action:
        params["action"] = action
    return _check(requests.get(f"{FLEET_API_URL}/api/v1/audit", headers=_headers(), params=params, timeout=10)).json()


# ─── Sites (write) ───────────────────────────────────────────────────────────

def create_site(payload: dict) -> dict:
    return _check(requests.post(f"{FLEET_API_URL}/api/v1/sites", headers=_headers(), json=payload, timeout=10)).json()


def update_site(site_id: str, payload: dict) -> dict:
    return _check(requests.put(f"{FLEET_API_URL}/api/v1/sites/{site_id}", headers=_headers(), json=payload, timeout=10)).json()


def delete_site(site_id: str) -> None:
    _check(requests.delete(f"{FLEET_API_URL}/api/v1/sites/{site_id}", headers=_headers(), timeout=10))


# ─── Zones (write) ───────────────────────────────────────────────────────────

def create_zone(payload: dict) -> dict:
    return _check(requests.post(f"{FLEET_API_URL}/api/v1/zones", headers=_headers(), json=payload, timeout=10)).json()


def update_zone(zone_id: str, payload: dict) -> dict:
    return _check(requests.put(f"{FLEET_API_URL}/api/v1/zones/{zone_id}", headers=_headers(), json=payload, timeout=10)).json()


def delete_zone(zone_id: str) -> None:
    _check(requests.delete(f"{FLEET_API_URL}/api/v1/zones/{zone_id}", headers=_headers(), timeout=10))


# ─── Devices (write) ─────────────────────────────────────────────────────────

def create_device(payload: dict) -> dict:
    return _check(requests.post(f"{FLEET_API_URL}/api/v1/devices", headers=_headers(), json=payload, timeout=10)).json()


def update_device(device_id: str, payload: dict) -> dict:
    return _check(requests.put(f"{FLEET_API_URL}/api/v1/devices/{device_id}", headers=_headers(), json=payload, timeout=10)).json()


def delete_device(device_id: str) -> None:
    _check(requests.delete(f"{FLEET_API_URL}/api/v1/devices/{device_id}", headers=_headers(), timeout=10))


# ─── Profiles ────────────────────────────────────────────────────────────────

def get_profiles() -> list[dict]:
    return _check(requests.get(f"{FLEET_API_URL}/api/v1/profiles", headers=_headers(), timeout=10)).json()


def get_profile(profile_id: str) -> dict:
    return _check(requests.get(f"{FLEET_API_URL}/api/v1/profiles/{profile_id}", headers=_headers(), timeout=10)).json()


def create_profile(payload: dict) -> dict:
    return _check(requests.post(f"{FLEET_API_URL}/api/v1/profiles", headers=_headers(), json=payload, timeout=10)).json()


def update_profile(profile_id: str, payload: dict) -> dict:
    return _check(requests.put(f"{FLEET_API_URL}/api/v1/profiles/{profile_id}", headers=_headers(), json=payload, timeout=10)).json()


def delete_profile(profile_id: str) -> None:
    _check(requests.delete(f"{FLEET_API_URL}/api/v1/profiles/{profile_id}", headers=_headers(), timeout=10))


# ─── Overrides ───────────────────────────────────────────────────────────────

def get_overrides(scope: str | None = None, target_id: str | None = None) -> list[dict]:
    params: dict = {}
    if scope:
        params["scope"] = scope
    if target_id:
        params["target_id"] = target_id
    return _check(requests.get(f"{FLEET_API_URL}/api/v1/overrides", headers=_headers(), params=params, timeout=10)).json()


def create_override(payload: dict) -> dict:
    return _check(requests.post(f"{FLEET_API_URL}/api/v1/overrides", headers=_headers(), json=payload, timeout=10)).json()


def delete_override(override_id: str) -> None:
    _check(requests.delete(f"{FLEET_API_URL}/api/v1/overrides/{override_id}", headers=_headers(), timeout=10))


# ─── Aptly (package repository) ──────────────────────────────────────────────

APTLY_API_URL = os.environ.get("APTLY_API_URL", "http://aptly-api:8080").rstrip("/")


def aptly_list_repos() -> list[dict]:
    resp = requests.get(f"{APTLY_API_URL}/api/repos", timeout=10)
    if resp.status_code == 200:
        return resp.json()
    return []


def aptly_list_packages(repo_name: str) -> list[dict]:
    try:
        resp = requests.get(
            f"{APTLY_API_URL}/api/repos/{repo_name}/packages",
            params={"format": "details"},
            timeout=10,
        )
        if resp.status_code == 200:
            return resp.json()
    except Exception:
        pass
    return []


def aptly_list_publish() -> list[dict]:
    try:
        resp = requests.get(f"{APTLY_API_URL}/api/publish", timeout=10)
        if resp.status_code == 200:
            return resp.json()
    except Exception:
        pass
    return []


# ─── Prometheus (direct — no auth, internal network) ───────────────────────────

PROMETHEUS_URL = os.environ.get("PROMETHEUS_URL", "http://prometheus:9090").rstrip("/")


def prom_query(query: str) -> dict | None:
    """Execute an instant Prometheus query; return the data payload or None on failure."""
    try:
        resp = requests.get(
            f"{PROMETHEUS_URL}/api/v1/query",
            params={"query": query},
            timeout=8,
        )
        if resp.ok:
            return resp.json().get("data")
    except Exception:
        pass
    return None


def prom_targets() -> list[dict]:
    """Return all active Prometheus scrape targets."""
    try:
        resp = requests.get(f"{PROMETHEUS_URL}/api/v1/targets", timeout=8)
        if resp.ok:
            return resp.json().get("data", {}).get("activeTargets", [])
    except Exception:
        pass
    return []


# ─── Observability (via Fleet API) ───────────────────────────────────────────


def get_observability_alerts(status: str = "open") -> list[dict]:
    """Proxy Alertmanager active alerts through the Fleet API."""
    return _check(
        requests.get(
            f"{FLEET_API_URL}/api/v1/alerts",
            headers=_headers(),
            params={"status": status},
            timeout=10,
        )
    ).json()
