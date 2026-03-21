"""Admin blueprint — Deployment Profiles and Version Overrides."""

import json
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

bp = Blueprint("admin", __name__)


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


# ─── Deployment Profiles ─────────────────────────────────────────────────────

@bp.route("/profiles")
@_login_required
def profiles_list():
    profiles = []
    try:
        profiles = api.get_profiles()
    except ApiError as exc:
        flash(f"Could not load profiles: {exc.detail}", "error")
    return render_template("profiles.html", profiles=profiles)


@bp.route("/profiles", methods=["POST"])
@_login_required
def create_profile_post():
    profile_id = request.form.get("profile_id", "").strip()
    name = request.form.get("name", "").strip()
    stack_raw = request.form.get("baseline_stack", "{}").strip()

    if not profile_id or not name:
        flash("Profile ID and name are required.", "error")
        return redirect(url_for("admin.profiles_list"))

    try:
        baseline_stack = json.loads(stack_raw)
    except json.JSONDecodeError:
        flash("Baseline stack must be valid JSON (e.g. {\"service\": \"1.0.0\"}).", "error")
        return redirect(url_for("admin.profiles_list"))

    try:
        api.create_profile({"profile_id": profile_id, "name": name, "baseline_stack": baseline_stack})
        flash(f"Profile '{name}' created.", "success")
    except ApiError as exc:
        flash(f"Could not create profile: {exc.detail}", "error")
    return redirect(url_for("admin.profiles_list"))


@bp.route("/profiles/<profile_id>/delete", methods=["POST"])
@_login_required
def delete_profile_post(profile_id: str):
    try:
        api.delete_profile(profile_id)
        flash(f"Profile '{profile_id}' deleted.", "success")
    except ApiError as exc:
        flash(f"Could not delete profile: {exc.detail}", "error")
    return redirect(url_for("admin.profiles_list"))


# ─── Version Overrides ────────────────────────────────────────────────────────

@bp.route("/overrides")
@_login_required
def overrides_list():
    overrides = []
    sites = []
    try:
        overrides = api.get_overrides()
    except ApiError as exc:
        flash(f"Could not load overrides: {exc.detail}", "error")
    try:
        sites = api.get_sites()
    except ApiError:
        pass
    return render_template("overrides.html", overrides=overrides, sites=sites)


@bp.route("/overrides", methods=["POST"])
@_login_required
def create_override_post():
    expires_at = request.form.get("expires_at", "").strip() or None
    payload = {
        "scope": request.form.get("scope", "").strip(),
        "target_id": request.form.get("target_id", "").strip(),
        "component": request.form.get("component", "").strip(),
        "artifact_type": request.form.get("artifact_type", "deb").strip(),
        "artifact_ref": request.form.get("artifact_ref", "").strip(),
        "reason": request.form.get("reason", "").strip(),
        "created_by": session.get("username", "operator"),
        "expires_at": expires_at,
    }
    if not all([payload["scope"], payload["target_id"], payload["component"], payload["artifact_ref"], payload["reason"]]):
        flash("All fields except expiry are required.", "error")
    else:
        try:
            api.create_override(payload)
            flash(f"Override for '{payload['component']}' on {payload['scope']}:{payload['target_id']} created.", "success")
        except ApiError as exc:
            flash(f"Could not create override: {exc.detail}", "error")
    return redirect(url_for("admin.overrides_list"))


@bp.route("/overrides/<override_id>/delete", methods=["POST"])
@_login_required
def delete_override_post(override_id: str):
    try:
        api.delete_override(override_id)
        flash("Override removed.", "success")
    except ApiError as exc:
        flash(f"Could not delete override: {exc.detail}", "error")
    return redirect(url_for("admin.overrides_list"))
