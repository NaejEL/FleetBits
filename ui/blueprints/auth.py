"""Authentication blueprint — login / logout."""

import os

from flask import (
    Blueprint,
    flash,
    make_response,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

import api_client as api
from api_client import ApiError

bp = Blueprint("auth", __name__)

_FLEET_DOMAIN = os.environ.get("FLEET_DOMAIN", "")
_FLASK_DEBUG = os.environ.get("FLASK_DEBUG", "").strip().lower() in {"1", "true", "yes", "on"}


def _fleet_access_cookie_domain() -> str | None:
    """Return the cookie domain for the fleet_access SSO cookie.

    In production the cookie must be set on the parent domain (e.g.
    '.fleet.example.com') so that it is sent by the browser to all
    subdomains including grafana.fleet.example.com.

    In dev (FLASK_DEBUG=true or FLEET_DOMAIN=localhost) set no domain
    so the cookie applies only to localhost — subdomains don't exist in dev.
    """
    if _FLASK_DEBUG or not _FLEET_DOMAIN or _FLEET_DOMAIN == "localhost":
        return None
    # Prepend dot so the cookie covers all subdomains
    return f".{_FLEET_DOMAIN}"


@bp.route("/login", methods=["GET"])
def login_page():
    if "jwt" in session:
        return redirect(url_for("inventory.overview"))
    return render_template("login.html")


@bp.route("/login", methods=["POST"])
def login_submit():
    username = request.form.get("username", "").strip()
    password = request.form.get("password", "")

    if not username or not password:
        flash("Username and password are required.", "error")
        return render_template("login.html"), 400

    try:
        token_data = api.login(username, password)
        # api.login returns the raw token string
        jwt_token = token_data if isinstance(token_data, str) else token_data.get("access_token", "")
        session["jwt"] = jwt_token
        session["username"] = username
        # Fetch full user profile to store role and site_scope for UI-level gating
        try:
            me = api.get_me()
            session["role"] = me.get("role", "viewer")
            session["site_scope"] = me.get("site_scope")
        except ApiError:
            session["role"] = "viewer"
            session["site_scope"] = None

        resp = make_response(redirect(url_for("inventory.overview")))

        # Set fleet_access cookie: an HttpOnly, Secure cookie carrying the JWT
        # on the parent domain so all subdomains (grafana.*) can participate in
        # Caddy forward_auth without a separate login.
        resp.set_cookie(
            "fleet_access",
            jwt_token,
            httponly=True,
            secure=not _FLASK_DEBUG,
            samesite="Lax",
            domain=_fleet_access_cookie_domain(),
            max_age=8 * 3600,  # mirrors FLEET_JWT_EXPIRE_MINUTES default
        )
        return resp
    except ApiError as exc:
        flash(str(exc.detail), "error")
        return render_template("login.html"), 401


@bp.route("/logout", methods=["POST"])
def logout():
    resp = make_response(redirect(url_for("auth.login_page")))
    # Clear the SSO cookie on logout so Grafana is also de-authed
    resp.delete_cookie(
        "fleet_access",
        domain=_fleet_access_cookie_domain(),
    )
    session.clear()
    return resp
