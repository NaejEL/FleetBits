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


@bp.route("/monitoring")
@_login_required
def platform_monitoring():
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
        targets=targets,
        alerts=alerts,
    )
