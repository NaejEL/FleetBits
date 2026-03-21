"""Monitoring blueprint — Platform telemetry from Prometheus and Alertmanager."""

from functools import wraps

from flask import Blueprint, flash, redirect, render_template, session, url_for

import api_client as api
from api_client import ApiError, Unauthorized

bp = Blueprint("monitoring", __name__)


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


def _scalar(data: dict | None) -> float | None:
    """Extract first numeric value from a Prometheus instant query result."""
    if not data:
        return None
    results = data.get("result", [])
    if not results:
        return None
    try:
        return float(results[0]["value"][1])
    except (KeyError, IndexError, ValueError):
        return None


def _fmt_bytes(b: float | None) -> str:
    if b is None:
        return "—"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if b < 1024:
            return f"{b:.1f} {unit}"
        b /= 1024
    return f"{b:.1f} PB"


def _fmt_uptime(seconds: float | None) -> str:
    if seconds is None:
        return "—"
    s = int(seconds)
    d, s = divmod(s, 86400)
    h, s = divmod(s, 3600)
    m, _ = divmod(s, 60)
    if d:
        return f"{d}d {h}h {m}m"
    if h:
        return f"{h}h {m}m"
    return f"{m}m"


@bp.route("/monitoring")
@_login_required
def platform_monitoring():
    # ── VPS host metrics via node_exporter (job="vps_host") ──────────────────
    def q(query: str) -> float | None:
        return _scalar(api.prom_query(query))

    cpu_pct   = q('100 - (avg(rate(node_cpu_seconds_total{job="vps_host",mode="idle"}[2m])) * 100)')
    mem_total = q('node_memory_MemTotal_bytes{job="vps_host"}')
    mem_avail = q('node_memory_MemAvailable_bytes{job="vps_host"}')
    mem_pct   = (100.0 * (1 - mem_avail / mem_total)) if (mem_total and mem_avail) else None
    load1     = q('node_load1{job="vps_host"}')
    load5     = q('node_load5{job="vps_host"}')
    load15    = q('node_load15{job="vps_host"}')
    disk_pct  = q('100 * (1 - (node_filesystem_free_bytes{job="vps_host",mountpoint="/"} / node_filesystem_size_bytes{job="vps_host",mountpoint="/"}))')
    uptime_s  = q('node_time_seconds{job="vps_host"} - node_boot_time_seconds{job="vps_host"}')

    # Network — sum across all non-loopback / non-docker interfaces
    net_rx_bps = _scalar(api.prom_query(
        'sum(rate(node_network_receive_bytes_total{job="vps_host",device!~"lo|docker.*|veth.*|br-.*"}[2m]))'
    ))
    net_tx_bps = _scalar(api.prom_query(
        'sum(rate(node_network_transmit_bytes_total{job="vps_host",device!~"lo|docker.*|veth.*|br-.*"}[2m]))'
    ))

    # Temperature — highest sensor reading (hwmon)
    temp_c = None
    temp_data = api.prom_query('node_hwmon_temp_celsius{job="vps_host"}')
    if temp_data and temp_data.get("result"):
        try:
            temp_c = max(float(r["value"][1]) for r in temp_data["result"])
        except (KeyError, ValueError):
            pass

    host = {
        "cpu_pct":   round(cpu_pct,  1) if cpu_pct  is not None else None,
        "mem_pct":   round(mem_pct,  1) if mem_pct  is not None else None,
        "mem_used":  _fmt_bytes((mem_total - mem_avail) if (mem_total and mem_avail) else None),
        "mem_total": _fmt_bytes(mem_total),
        "disk_pct":  round(disk_pct, 1) if disk_pct is not None else None,
        "load1":     round(load1,    2) if load1    is not None else None,
        "load5":     round(load5,    2) if load5    is not None else None,
        "load15":    round(load15,   2) if load15   is not None else None,
        "uptime":    _fmt_uptime(uptime_s),
        "net_rx":    _fmt_bytes(net_rx_bps),
        "net_tx":    _fmt_bytes(net_tx_bps),
        "temp_c":    round(temp_c,   1) if temp_c   is not None else None,
    }

    # ── Prometheus scrape targets (all platform services) ────────────────────
    targets = api.prom_targets()
    # Sort: down / unknown first, then by job name
    targets.sort(key=lambda t: (0 if t.get("health") != "up" else 1, t.get("labels", {}).get("job", "")))

    # ── Active alerts from Alertmanager (via Fleet API proxy) ────────────────
    alerts = []
    try:
        alerts = api.get_observability_alerts("open")
    except (ApiError, Exception):
        pass

    return render_template(
        "monitoring.html",
        host=host,
        targets=targets,
        alerts=alerts,
    )
