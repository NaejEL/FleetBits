"""Audit blueprint — Audit Log."""

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

bp = Blueprint("audit", __name__)

_PAGE_SIZE = 25


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


@bp.route("/audit")
@_login_required
def audit_log():
    actor = request.args.get("actor", "").strip() or None
    site_id = request.args.get("site_id", "").strip() or None
    action = request.args.get("action", "").strip() or None
    page = max(1, int(request.args.get("page", 1)))
    offset = (page - 1) * _PAGE_SIZE

    events = []
    total = 0
    try:
        result = api.get_audit(actor=actor, site_id=site_id, action=action,
                               limit=_PAGE_SIZE, offset=offset)
        if isinstance(result, dict):
            events = result.get("items", [])
            total = result.get("total", len(events))
        else:
            events = result
            total = len(events)
    except ApiError as exc:
        flash(f"Could not load audit log: {exc.detail}", "error")

    sites = []
    try:
        sites = api.get_sites()
    except ApiError:
        pass

    has_next = (offset + _PAGE_SIZE) < total
    has_prev = page > 1

    return render_template(
        "audit.html",
        events=events,
        total=total,
        page=page,
        has_next=has_next,
        has_prev=has_prev,
        filters={"actor": actor or "", "site_id": site_id or "", "action": action or ""},
        sites=sites,
    )
