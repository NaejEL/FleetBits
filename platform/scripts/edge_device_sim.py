#!/usr/bin/env python3
"""Dummy edge-device simulator for local Docker security integration tests.

This process bootstraps a synthetic edge device against fleet-api, then exposes
its current runtime state at http://0.0.0.0:18080/state for tests.
"""

from __future__ import annotations

import json
import os
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


API_URL = os.getenv("EDGE_SIM_API_URL", "http://fleet-api:8000").rstrip("/")
CADDY_URL = os.getenv("EDGE_SIM_CADDY_URL", "http://caddy").rstrip("/")
USERNAME = os.getenv("EDGE_SIM_OPERATOR_USERNAME", os.getenv("OPERATOR_USERNAME", "admin"))
PASSWORD = os.getenv("EDGE_SIM_OPERATOR_PASSWORD", os.getenv("OPERATOR_PASSWORD", "change-me-immediately"))

PROFILE_ID = os.getenv("EDGE_SIM_PROFILE_ID", "edge-sim-profile")
SITE_ID = os.getenv("EDGE_SIM_SITE_ID", "edge-sim-site")
ZONE_ID = os.getenv("EDGE_SIM_ZONE_ID", "edge-sim-zone")
DEVICE_ID = os.getenv("EDGE_SIM_DEVICE_ID", "edge-sim-device-01")
HOSTNAME = os.getenv("EDGE_SIM_HOSTNAME", DEVICE_ID)


STATE: dict[str, object] = {
    "started_at": datetime.now(timezone.utc).isoformat(),
    "api_url": API_URL,
    "caddy_url": CADDY_URL,
    "profile_id": PROFILE_ID,
    "site_id": SITE_ID,
    "zone_id": ZONE_ID,
    "device_id": DEVICE_ID,
    "bootstrapped": False,
    "bootstrap_in_progress": True,
    "bootstrap_attempt": 0,
    "bootstrap_failed": False,
    "admin_login": False,
    "device_token_issued": False,
    "repo_key_registered": False,
    "heartbeat_ok": False,
    "repo_authorize_status": None,
    "repo_pull_status": None,
    "last_error": None,
    "last_update": None,
}

STATE_LOCK = threading.Lock()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _update_state(**values: object) -> None:
    with STATE_LOCK:
        STATE.update(values)
        STATE["last_update"] = _now_iso()


def _get_state(key: str) -> object | None:
    with STATE_LOCK:
        return STATE.get(key)


def _snapshot_state() -> dict[str, object]:
    with STATE_LOCK:
        return dict(STATE)


def _request(
    base: str,
    path: str,
    method: str = "GET",
    data: dict | None = None,
    token: str | None = None,
    extra_headers: dict[str, str] | None = None,
) -> tuple[int, dict | str | None, dict[str, str]]:
    url = f"{base}{path}"
    headers: dict[str, str] = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if extra_headers:
        headers.update(extra_headers)

    body = json.dumps(data).encode() if data is not None else None
    req = urllib.request.Request(url, data=body, headers=headers, method=method)

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            try:
                payload: dict | str | None = json.loads(raw) if raw else None
            except json.JSONDecodeError:
                payload = raw
            return resp.getcode(), payload, dict(resp.headers)
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
        try:
            payload = json.loads(raw) if raw else None
        except json.JSONDecodeError:
            payload = raw
        return exc.code, payload, dict(exc.headers or {})
    except urllib.error.URLError as exc:
        # Return a synthetic status for network failures so callers can decide
        # whether to fail hard (_ensure_ok) or keep bootstrap progressing for
        # non-critical checks.
        return 599, {"detail": str(exc.reason)}, {}


def _ensure_ok(status: int, allowed: tuple[int, ...], action: str) -> None:
    if status not in allowed:
        raise RuntimeError(f"{action} failed with status {status}")


def _bootstrap_once() -> None:
    # Admin login
    st, body, _ = _request(
        API_URL,
        "/api/v1/auth/login",
        method="POST",
        data={"username": USERNAME, "password": PASSWORD},
    )
    _ensure_ok(st, (200,), "admin login")
    assert isinstance(body, dict) and "access_token" in body
    admin_token = body["access_token"]
    _update_state(admin_login=True)

    # Ensure profile/site/zone/device exist (409 = already exists)
    st, _, _ = _request(
        API_URL,
        "/api/v1/profiles",
        method="POST",
        token=admin_token,
        data={
            "profile_id": PROFILE_ID,
            "name": "Edge Simulator Profile",
            "baseline_stack": {"components": [{"name": "sim", "artifactType": "deb", "artifactRef": "sim=1.0.0"}]},
        },
    )
    _ensure_ok(st, (201, 409), "ensure profile")

    st, _, _ = _request(
        API_URL,
        "/api/v1/sites",
        method="POST",
        token=admin_token,
        data={"site_id": SITE_ID, "name": "Edge Simulator Site", "timezone": "UTC"},
    )
    _ensure_ok(st, (201, 409), "ensure site")

    st, _, _ = _request(
        API_URL,
        "/api/v1/zones",
        method="POST",
        token=admin_token,
        data={
            "zone_id": ZONE_ID,
            "site_id": SITE_ID,
            "name": "Edge Simulator Zone",
            "criticality": "standard",
            "profile_id": PROFILE_ID,
        },
    )
    _ensure_ok(st, (201, 409), "ensure zone")

    st, _, _ = _request(
        API_URL,
        "/api/v1/devices",
        method="POST",
        token=admin_token,
        data={
            "device_id": DEVICE_ID,
            "zone_id": ZONE_ID,
            "site_id": SITE_ID,
            "profile_id": PROFILE_ID,
            "role": "kiosk",
            "hostname": HOSTNAME,
            "ring": 0,
        },
    )
    _ensure_ok(st, (201, 409), "ensure device")

    # Issue/re-issue device token
    st, body, _ = _request(
        API_URL,
        f"/api/v1/devices/{DEVICE_ID}/token",
        method="POST",
        token=admin_token,
    )
    _ensure_ok(st, (200,), "issue device token")
    assert isinstance(body, dict) and "device_token" in body
    device_token = body["device_token"]
    _update_state(device_token_issued=True, device_token=device_token)

    # Register repository key (first-boot parity)
    pubkey = "ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABAQCdummy edge-sim@test"
    st, _, _ = _request(
        API_URL,
        f"/api/v1/devices/{DEVICE_ID}/repo-key/self",
        method="POST",
        token=device_token,
        data={"public_key": pubkey, "key_fingerprint": "SHA256:edge-sim"},
    )
    _ensure_ok(st, (200, 201), "register repo key")
    _update_state(repo_key_registered=True, repo_public_key=pubkey)

    # Send heartbeat
    st, _, _ = _request(
        API_URL,
        f"/api/v1/devices/{DEVICE_ID}/heartbeat",
        method="POST",
        token=device_token,
        data={
            "agent_version": "edge-sim-1.0",
            "service_states": {"fleet-agent": "active"},
            "os_info": {"simulator": True},
        },
    )
    _ensure_ok(st, (204,), "heartbeat")
    _update_state(heartbeat_ok=True)

    # Repo authorize health-check
    st, body, _ = _request(
        API_URL,
        "/api/v1/packages/repo/authorize",
        method="GET",
        token=device_token,
    )
    _update_state(repo_authorize_status=st, repo_authorize_body=body)

    # Caddy package-path access check (status may differ by repo contents / redirects)
    st, _, _ = _request(
        CADDY_URL,
        "/dists/focal/Release",
        method="GET",
        token=device_token,
    )
    _update_state(repo_pull_status=st)


def _heartbeat_loop() -> None:
    while True:
        try:
            token = _get_state("device_token")
            if token:
                st, _, _ = _request(
                    API_URL,
                    f"/api/v1/devices/{DEVICE_ID}/heartbeat",
                    method="POST",
                    token=str(token),
                    data={"agent_version": "edge-sim-1.0", "service_states": {"fleet-agent": "active"}},
                )
                _update_state(heartbeat_status=st, heartbeat_ok=(st == 204))
        except Exception as exc:  # pragma: no cover
            _update_state(last_error=f"heartbeat_loop: {exc}")
        time.sleep(30)


def _bootstrap_loop() -> None:
    for attempt in range(1, 61):
        try:
            _update_state(bootstrap_attempt=attempt, bootstrap_in_progress=True, bootstrap_failed=False)
            _bootstrap_once()
            _update_state(bootstrapped=True, bootstrap_in_progress=False, bootstrap_failed=False, last_error=None)
            return
        except Exception as exc:  # pragma: no cover
            _update_state(
                bootstrap_attempt=attempt,
                bootstrap_in_progress=True,
                bootstrap_failed=False,
                last_error=f"bootstrap attempt {attempt}: {exc}",
            )
            time.sleep(2)

    _update_state(bootstrap_in_progress=False, bootstrap_failed=True)


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, _format, *_args):
        return

    def do_GET(self):  # noqa: N802
        if self.path in ("/health", "/state"):
            payload = json.dumps(_snapshot_state()).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return
        self.send_response(404)
        self.end_headers()


def main() -> None:
    bootstrap_thread = threading.Thread(target=_bootstrap_loop, daemon=True)
    bootstrap_thread.start()

    heartbeat_thread = threading.Thread(target=_heartbeat_loop, daemon=True)
    heartbeat_thread.start()

    server = ThreadingHTTPServer(("0.0.0.0", 18080), _Handler)
    server.serve_forever()


if __name__ == "__main__":
    main()
