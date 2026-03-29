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

    active = [d for d in deployments if d.get("status") in ("pending", "scheduled", "deploying")]
    recent = [d for d in deployments if d.get("status") not in ("pending", "scheduled", "deploying")]

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
    artifact_type = request.form.get("artifact_type", "deb")
    artifact_ref = (request.form.get("artifact_ref") or "").strip()
    rollout_mode = request.form.get("rollout_mode", "ring-0")
    change_id = (request.form.get("change_id") or "").strip() or None
    site_id = (request.form.get("site_id") or "").strip()

    if not artifact_ref:
        flash("Artifact reference is required.", "error")
        return redirect(url_for("deployments.deployment_center"))

    target_scope: dict = {}
    if site_id:
        target_scope["siteId"] = site_id

    payload = {
        "artifact_type": artifact_type,
        "artifact_ref": artifact_ref,
        "rollout_mode": rollout_mode,
        "target_scope": target_scope,
        "requested_by": session.get("username", "unknown"),
        "change_id": change_id,
    }

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


@bp.route("/deployments/<deployment_id>/promote", methods=["POST"])
@_login_required
def promote(deployment_id: str):
    try:
        dep = api.promote_deployment(deployment_id)
        next_mode = dep.get("rollout_mode", "next ring")
        flash(f"Promoted — new {next_mode} deployment {dep.get('deployment_id', '')} created.", "success")
    except ApiError as exc:
        flash(f"Promotion failed: {exc.detail}", "error")
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
