"""Authentication blueprint — login / logout."""

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
from api_client import ApiError

bp = Blueprint("auth", __name__)


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
        token = api.login(username, password)
        session["jwt"] = token
        session["username"] = username
        return redirect(url_for("inventory.overview"))
    except ApiError as exc:
        flash(str(exc.detail), "error")
        return render_template("login.html"), 401


@bp.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return redirect(url_for("auth.login_page"))
