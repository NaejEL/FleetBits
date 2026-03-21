"""Admin blueprint — Deployment Profiles, Version Overrides, and User Management."""

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


def _admin_required(f):
    """Like _login_required but also enforces admin role."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if "jwt" not in session:
            return redirect(url_for("auth.login_page"))
        if session.get("role") != "admin":
            flash("Administrator access required.", "error")
            return redirect(url_for("inventory.overview"))
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


# ─── User Management ─────────────────────────────────────────────────────────

@bp.route("/admin/users")
@_admin_required
def users_list():
    users = []
    api_keys = []
    try:
        users = api.get_users()
        api_keys = api.get_api_keys()
    except ApiError as exc:
        flash(f"Could not load data: {exc.detail}", "error")
    return render_template("users.html", users=users, api_keys=api_keys)


@bp.route("/admin/users", methods=["POST"])
@_admin_required
def create_user_post():
    username = request.form.get("username", "").strip()
    password = request.form.get("password", "")
    role = request.form.get("role", "viewer").strip()
    email = request.form.get("email", "").strip() or None
    site_scope = request.form.get("site_scope", "").strip() or None

    if not username or not password:
        flash("Username and password are required.", "error")
        return redirect(url_for("admin.users_list"))

    try:
        api.create_user(username=username, password=password, role=role,
                        email=email, site_scope=site_scope)
        flash(f"User '{username}' created with role '{role}'.", "success")
    except ApiError as exc:
        flash(f"Could not create user: {exc.detail}", "error")
    return redirect(url_for("admin.users_list"))


@bp.route("/admin/users/<user_id>/update", methods=["POST"])
@_admin_required
def update_user_post(user_id: str):
    changes: dict = {}
    role = request.form.get("role", "").strip()
    email = request.form.get("email", "").strip()
    site_scope = request.form.get("site_scope", "").strip()
    is_active = request.form.get("is_active")

    if role:
        changes["role"] = role
    if email:
        changes["email"] = email
    # Explicit empty means "clear site_scope"
    changes["site_scope"] = site_scope or None
    if is_active is not None:
        changes["is_active"] = is_active == "true"

    try:
        api.update_user(user_id, **changes)
        flash("User updated.", "success")
    except ApiError as exc:
        flash(f"Could not update user: {exc.detail}", "error")
    return redirect(url_for("admin.users_list"))


@bp.route("/admin/users/<user_id>/reset-password", methods=["POST"])
@_admin_required
def reset_password_post(user_id: str):
    new_password = request.form.get("new_password", "")
    if not new_password:
        flash("New password is required.", "error")
        return redirect(url_for("admin.users_list"))

    try:
        api.admin_reset_password(user_id, new_password)
        flash("Password reset.", "success")
    except ApiError as exc:
        flash(f"Could not reset password: {exc.detail}", "error")
    return redirect(url_for("admin.users_list"))


# ─── API Key Management ───────────────────────────────────────────────────────

@bp.route("/admin/api-keys", methods=["POST"])
@_admin_required
def create_api_key_post():
    key_name = request.form.get("key_name", "").strip()
    role = request.form.get("role", "ci_bot").strip()
    expires_days_raw = request.form.get("expires_days", "").strip()
    site_scope = request.form.get("site_scope", "").strip() or None

    if not key_name:
        flash("Key name is required.", "error")
        return redirect(url_for("admin.users_list"))

    expires_days = int(expires_days_raw) if expires_days_raw and expires_days_raw.isdigit() else None

    try:
        result = api.create_api_key(key_name=key_name, role=role,
                                    expires_days=expires_days, site_scope=site_scope)
        # Store the raw token in session flash so it can be shown once
        raw_token = result.get("raw_token", "")
        flash(f"API key '{key_name}' created. Token (copy now — shown once): {raw_token}", "api_key")
    except ApiError as exc:
        flash(f"Could not create API key: {exc.detail}", "error")
    return redirect(url_for("admin.users_list"))


@bp.route("/admin/api-keys/<key_id>/revoke", methods=["POST"])
@_admin_required
def revoke_api_key_post(key_id: str):
    try:
        api.revoke_api_key(key_id)
        flash("API key revoked.", "success")
    except ApiError as exc:
        flash(f"Could not revoke key: {exc.detail}", "error")
    return redirect(url_for("admin.users_list"))
