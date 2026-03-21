"""Deployments blueprint — Deployment Center."""

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

bp = Blueprint("deployments", __name__)


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


@bp.route("/deployments")
@_login_required
def deployment_center():
    deployments = []
    try:
        deployments = api.get_deployments()
    except ApiError as exc:
        flash(f"Could not load deployments: {exc.detail}", "error")

    active = [d for d in deployments if d.get("status") in ("pending", "in_progress")]
    recent = [d for d in deployments if d.get("status") not in ("pending", "in_progress")]

    sites = []
    try:
        sites = api.get_sites()
    except ApiError:
        pass

    return render_template(
        "deployments.html",
        active_deployments=active,
        recent_deployments=recent[:20],
        sites=sites,
    )


@bp.route("/deployments/new", methods=["POST"])
@_login_required
def new_deployment():
    payload = {
        "component": request.form.get("component", ""),
        "artifact_type": request.form.get("artifact_type", "deb"),
        "version": request.form.get("version", ""),
        "target_ring": int(request.form.get("target_ring", 0)),
        "change_id": request.form.get("change_id", ""),
    }
    site_id = request.form.get("site_id")
    if site_id:
        payload["site_id"] = site_id

    try:
        dep = api.create_deployment(payload)
        flash(f"Deployment {dep.get('deployment_id', '')} created.", "success")
    except ApiError as exc:
        flash(f"Could not create deployment: {exc.detail}", "error")

    return redirect(url_for("deployments.deployment_center"))


@bp.route("/deployments/<deployment_id>/trigger", methods=["POST"])
@_login_required
def trigger(deployment_id: str):
    try:
        api.trigger_deployment(deployment_id)
        flash("Rollout triggered.", "success")
    except ApiError as exc:
        flash(f"Trigger failed: {exc.detail}", "error")
    return redirect(url_for("deployments.deployment_center"))


@bp.route("/deployments/<deployment_id>/rollback", methods=["POST"])
@_login_required
def rollback(deployment_id: str):
    try:
        api.rollback_deployment(deployment_id)
        flash("Rollback triggered.", "success")
    except ApiError as exc:
        flash(f"Rollback failed: {exc.detail}", "error")
    return redirect(url_for("deployments.deployment_center"))
