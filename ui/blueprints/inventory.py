"""Inventory blueprint — Fleet Overview, Site View, Zone View, Device View."""

from functools import wraps

from flask import (
    Blueprint,
    flash,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

import api_client as api
from api_client import ApiError, Unauthorized

bp = Blueprint("inventory", __name__)


def _login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "jwt" not in session:
            return redirect(url_for("auth.login_page"))
        try:
            return f(*args, **kwargs)
        except Unauthorized:
            session.clear()
            flash("Your session has expired. Please log in again.", "warning")
            return redirect(url_for("auth.login_page"))
    return decorated


@bp.route("/overview")
@_login_required
def overview():
    sites = []
    alerts = []
    deployments = []
    zones = []
    devices = []
    profiles = []
    overrides = []

    try:
        sites = api.get_sites()
    except ApiError as exc:
        flash(f"Could not load sites: {exc.detail}", "error")

    try:
        alerts = api.get_alerts()
    except ApiError:
        alerts = []

    try:
        all_deps = api.get_deployments()
        # Show only active/in-progress deployments
        deployments = [d for d in all_deps if d.get("status") in ("pending", "in_progress")]
    except ApiError:
        deployments = []

    try:
        zones = api.get_zones()
    except ApiError:
        zones = []

    try:
        devices = api.get_devices()
    except ApiError:
        devices = []

    try:
        profiles = api.get_profiles()
    except ApiError:
        profiles = []

    try:
        overrides = api.get_overrides()
    except ApiError:
        overrides = []

    n_critical = sum(1 for a in alerts if a.get("labels", {}).get("severity") == "critical")
    n_warning  = sum(1 for a in alerts if a.get("labels", {}).get("severity") == "warning")
    n_online   = sum(1 for d in devices if d.get("status") == "online")

    stats = {
        "sites":              len(sites),
        "zones":              len(zones),
        "devices":            len(devices),
        "devices_online":     n_online,
        "alerts_critical":    n_critical,
        "alerts_warning":     n_warning,
        "active_deployments": len(deployments),
        "profiles":           len(profiles),
        "active_overrides":   len(overrides),
    }

    return render_template(
        "overview.html",
        sites=sites,
        alerts=alerts,
        active_deployments=deployments,
        stats=stats,
    )


@bp.route("/sites/<site_id>")
@_login_required
def site_view(site_id: str):
    try:
        site = api.get_site(site_id)
    except ApiError as exc:
        flash(f"Could not load site: {exc.detail}", "error")
        return redirect(url_for("inventory.overview"))

    zones = []
    try:
        zones = api.get_zones(site_id=site_id)
    except ApiError as exc:
        flash(f"Could not load zones: {exc.detail}", "error")

    # Fetch devices per zone to build health matrix
    zone_devices: dict[str, list] = {}
    for z in zones:
        try:
            zone_devices[z["zone_id"]] = api.get_devices(zone_id=z["zone_id"])
        except ApiError:
            zone_devices[z["zone_id"]] = []

    try:
        recent_audit = api.get_audit(site_id=site_id, limit=10)
        events = recent_audit.get("items", recent_audit) if isinstance(recent_audit, dict) else recent_audit
    except ApiError:
        events = []

    return render_template(
        "site.html",
        site=site,
        zones=zones,
        zone_devices=zone_devices,
        events=events,
    )


@bp.route("/zones/<zone_id>")
@_login_required
def zone_view(zone_id: str):
    try:
        zone = api.get_zone(zone_id)
    except ApiError as exc:
        flash(f"Could not load zone: {exc.detail}", "error")
        return redirect(url_for("inventory.overview"))

    devices = []
    device_services: dict[str, list] = {}
    try:
        devices = api.get_devices(zone_id=zone_id)
        for d in devices:
            try:
                device_services[d["device_id"]] = api.get_device_services(d["device_id"])
            except ApiError:
                device_services[d["device_id"]] = []
    except ApiError as exc:
        flash(f"Could not load devices: {exc.detail}", "error")

    alerts = []
    try:
        all_alerts = api.get_alerts()
        device_ids = {d["device_id"] for d in devices}
        alerts = [a for a in all_alerts if a.get("labels", {}).get("device_id") in device_ids]
    except ApiError:
        alerts = []

    try:
        recent_audit = api.get_audit(limit=10)
        events = recent_audit.get("items", recent_audit) if isinstance(recent_audit, dict) else recent_audit
    except ApiError:
        events = []

    site_id = zone.get("site_id")
    site = None
    if site_id:
        try:
            site = api.get_site(site_id)
        except ApiError:
            pass

    return render_template(
        "zone.html",
        zone=zone,
        site=site,
        devices=devices,
        device_services=device_services,
        alerts=alerts,
        events=events,
        device_roles=sorted({d["role"] for d in devices if d.get("role")}),
    )


@bp.route("/devices/<device_id>")
@_login_required
def device_view(device_id: str):
    try:
        device = api.get_device(device_id)
    except ApiError as exc:
        flash(f"Could not load device: {exc.detail}", "error")
        return redirect(url_for("inventory.overview"))

    services = []
    try:
        services = api.get_device_services(device_id)
    except ApiError:
        pass

    manifest = {}
    try:
        manifest = api.get_device_manifest(device_id)
    except ApiError:
        pass

    zone = None
    site = None
    zone_id = device.get("zone_id")
    if zone_id:
        try:
            zone = api.get_zone(zone_id)
            site_id = zone.get("site_id")
            if site_id:
                site = api.get_site(site_id)
        except ApiError:
            pass

    return render_template(
        "device.html",
        device=device,
        zone=zone,
        site=site,
        services=services,
        manifest=manifest,
    )


@bp.route("/devices/<device_id>/restart-service", methods=["POST"])
@_login_required
def restart_service(device_id: str):
    service_name = request.form.get("service_name", "")
    if not service_name:
        flash("Service name is required.", "error")
    else:
        try:
            api.restart_service(device_id, service_name)
            flash(f"Restart triggered for {service_name}.", "success")
        except ApiError as exc:
            flash(f"Restart failed: {exc.detail}", "error")
    return redirect(url_for("inventory.device_view", device_id=device_id))


@bp.route("/devices/<device_id>/diagnostics", methods=["POST"])
@_login_required
def run_diagnostics(device_id: str):
    try:
        api.run_diagnostics(device_id)
        flash("Diagnostics job triggered.", "success")
    except ApiError as exc:
        flash(f"Diagnostics failed: {exc.detail}", "error")
    return redirect(url_for("inventory.device_view", device_id=device_id))


# ─── Sites CRUD ──────────────────────────────────────────────────────────────

@bp.route("/sites", methods=["POST"])
@_login_required
def create_site_post():
    payload = {
        "site_id": request.form.get("site_id", "").strip(),
        "name": request.form.get("name", "").strip(),
        "timezone": request.form.get("timezone", "UTC").strip() or "UTC",
    }
    if not payload["site_id"] or not payload["name"]:
        flash("Site ID and name are required.", "error")
    else:
        try:
            api.create_site(payload)
            flash(f"Site '{payload['name']}' created.", "success")
        except ApiError as exc:
            flash(f"Could not create site: {exc.detail}", "error")
    return redirect(url_for("inventory.overview"))


@bp.route("/sites/<site_id>/delete", methods=["POST"])
@_login_required
def delete_site_post(site_id: str):
    try:
        api.delete_site(site_id)
        flash(f"Site '{site_id}' deleted.", "success")
    except ApiError as exc:
        flash(f"Could not delete site: {exc.detail}", "error")
    return redirect(url_for("inventory.overview"))


# ─── Zones CRUD ──────────────────────────────────────────────────────────────

@bp.route("/zones", methods=["POST"])
@_login_required
def create_zone_post():
    site_id = request.form.get("site_id", "").strip()
    payload = {
        "zone_id": request.form.get("zone_id", "").strip(),
        "name": request.form.get("name", "").strip(),
        "site_id": site_id,
        "criticality": request.form.get("criticality", "standard"),
        "profile_id": request.form.get("profile_id", "").strip() or None,
    }
    if not payload["zone_id"] or not payload["name"] or not site_id:
        flash("Zone ID, name, and site are required.", "error")
    else:
        try:
            api.create_zone(payload)
            flash(f"Zone '{payload['name']}' created.", "success")
        except ApiError as exc:
            flash(f"Could not create zone: {exc.detail}", "error")
    return redirect(url_for("inventory.site_view", site_id=site_id) if site_id else url_for("inventory.overview"))


@bp.route("/zones/<zone_id>/delete", methods=["POST"])
@_login_required
def delete_zone_post(zone_id: str):
    site_id = request.form.get("site_id", "").strip()
    try:
        api.delete_zone(zone_id)
        flash(f"Zone '{zone_id}' deleted.", "success")
    except ApiError as exc:
        flash(f"Could not delete zone: {exc.detail}", "error")
    return redirect(url_for("inventory.site_view", site_id=site_id) if site_id else url_for("inventory.overview"))


# ─── Devices CRUD ────────────────────────────────────────────────────────────

@bp.route("/devices", methods=["POST"])
@_login_required
def create_device_post():
    zone_id = request.form.get("zone_id", "").strip()
    site_id = request.form.get("site_id", "").strip()
    ring_raw = request.form.get("ring", "").strip()
    payload = {
        "device_id": request.form.get("device_id", "").strip(),
        "hostname": request.form.get("hostname", "").strip(),
        "role": request.form.get("role", "").strip(),
        "zone_id": zone_id or None,
        "site_id": site_id or None,
        "ring": int(ring_raw) if ring_raw.isdigit() else None,
    }
    if not payload["device_id"] or not payload["hostname"] or not payload["role"]:
        flash("Device ID, hostname, and role are required.", "error")
    else:
        try:
            result = api.create_device(payload)
            flash(f"Device '{result['device_id']}' registered — ready for first-boot provisioning.", "success")
        except ApiError as exc:
            flash(f"Could not register device: {exc.detail}", "error")
    if zone_id:
        return redirect(url_for("inventory.zone_view", zone_id=zone_id))
    return redirect(url_for("inventory.overview"))


@bp.route("/devices/<device_id>/delete", methods=["POST"])
@_login_required
def delete_device_post(device_id: str):
    zone_id = request.form.get("zone_id", "").strip()
    try:
        api.delete_device(device_id)
        flash(f"Device '{device_id}' removed from inventory.", "success")
    except ApiError as exc:
        flash(f"Could not delete device: {exc.detail}", "error")
    if zone_id:
        return redirect(url_for("inventory.zone_view", zone_id=zone_id))
    return redirect(url_for("inventory.overview"))
