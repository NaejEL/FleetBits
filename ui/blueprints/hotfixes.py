"""Hotfixes blueprint — Hotfix Console."""

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

bp = Blueprint("hotfixes", __name__)


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


@bp.route("/hotfixes")
@_login_required
def hotfix_console():
    hotfixes = []
    try:
        hotfixes = api.get_hotfixes()
    except ApiError as exc:
        flash(f"Could not load hotfixes: {exc.detail}", "error")

    active = [h for h in hotfixes if h.get("status") not in ("reverted", "promoted")]
    past = [h for h in hotfixes if h.get("status") in ("reverted", "promoted")]

    sites = []
    try:
        sites = api.get_sites()
    except ApiError:
        pass

    return render_template(
        "hotfixes.html",
        active_hotfixes=active,
        past_hotfixes=past,
        sites=sites,
    )


@bp.route("/hotfixes/new", methods=["POST"])
@_login_required
def new_hotfix():
    payload = {
        "device_id": request.form.get("device_id", ""),
        "service_name": request.form.get("service_name", ""),
        "artifact_type": request.form.get("artifact_type", "git"),
        "artifact_ref": request.form.get("artifact_ref", ""),
        "change_id": request.form.get("change_id", ""),
        "reason": request.form.get("reason", ""),
        "expires_at": request.form.get("expires_at", ""),
        "after_fix": request.form.get("after_fix", "decide_later"),
    }
    try:
        hf = api.create_hotfix(payload)
        flash(f"Hotfix {hf.get('hotfix_id', '')} created.", "success")
    except ApiError as exc:
        flash(f"Could not create hotfix: {exc.detail}", "error")
    return redirect(url_for("hotfixes.hotfix_console"))


@bp.route("/hotfixes/<hotfix_id>/promote", methods=["POST"])
@_login_required
def promote(hotfix_id: str):
    try:
        api.promote_hotfix(hotfix_id)
        flash("Hotfix promoted to baseline.", "success")
    except ApiError as exc:
        flash(f"Promote failed: {exc.detail}", "error")
    return redirect(url_for("hotfixes.hotfix_console"))


@bp.route("/hotfixes/<hotfix_id>/revert", methods=["POST"])
@_login_required
def revert(hotfix_id: str):
    try:
        api.revert_hotfix(hotfix_id)
        flash("Hotfix reverted.", "success")
    except ApiError as exc:
        flash(f"Revert failed: {exc.detail}", "error")
    return redirect(url_for("hotfixes.hotfix_console"))


@bp.route("/hotfixes/reconcile-ssh", methods=["POST"])
@_login_required
def reconcile_ssh():
    payload = {
        "device_id": request.form.get("device_id", ""),
        "hotfix_id": request.form.get("hotfix_id", ""),
        "commands": request.form.get("commands", ""),
        "evidence": request.form.get("evidence", ""),
    }
    try:
        api.reconcile_ssh(payload)
        flash("SSH action reconciled.", "success")
    except ApiError as exc:
        flash(f"Reconcile failed: {exc.detail}", "error")
    return redirect(url_for("hotfixes.hotfix_console"))
