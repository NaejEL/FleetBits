"""Packages blueprint — Aptly repository browser."""

from functools import wraps

from flask import Blueprint, flash, redirect, render_template, session, url_for

import api_client as api
from api_client import Unauthorized

bp = Blueprint("packages", __name__)


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


@bp.route("/packages")
@_login_required
def packages_browser():
    repos = api.aptly_list_repos()
    publish_endpoints = api.aptly_list_publish()

    repo_names = [r.get("Name", r.get("name", "")) for r in repos]

    packages_by_repo: dict[str, list] = {}
    for name in repo_names:
        pkgs = api.aptly_list_packages(name)
        # Normalise key casing from aptly's response
        packages_by_repo[name] = [
            {
                "package": p.get("Package", p.get("package", "—")),
                "version": p.get("Version", p.get("version", "—")),
                "arch": p.get("Architecture", p.get("architecture", "—")),
                "maintainer": p.get("Maintainer", p.get("maintainer", "")),
                "description": (p.get("Description", p.get("description", "")) or "").splitlines()[0],
            }
            for p in pkgs
        ]

    env_order = ["dev", "staging", "prod"]
    ordered = [n for n in env_order if n in repo_names] + [n for n in repo_names if n not in env_order]

    return render_template(
        "packages.html",
        repos=ordered,
        packages_by_repo=packages_by_repo,
        publish_endpoints=publish_endpoints,
    )
