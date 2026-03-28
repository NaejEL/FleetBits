"""Packages blueprint — Aptly repository browser with GPG key management."""

from functools import wraps

from flask import Blueprint, flash, redirect, render_template, session, url_for, request

import api_client as api
from api_client import Unauthorized, ApiError

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


# ─── GPG Key Management (4.1) ───────────────────────────────────────────────


@bp.route("/packages/gpg-keys")
@_login_required
def gpg_keys_management():
    """Manage GPG keys for package signing."""
    gpg_keys = api.get_gpg_keys()

    return render_template(
        "gpg_keys.html",
        gpg_keys=gpg_keys,
    )


@bp.route("/packages/gpg-keys/generate", methods=["POST"])
@_login_required
def gpg_keys_generate():
    """Generate a new GPG key."""
    name = request.form.get("name", "").strip()
    email = request.form.get("email", "").strip()
    key_type = request.form.get("key_type", "rsa4096")

    if not name or not email:
        flash("Name and email are required", "error")
        return redirect(url_for("packages.gpg_keys_management"))

    try:
        result = api.generate_gpg_key(name, email, key_type)
        flash(f"GPG key generation started: {result.get('message', 'Check status in a moment')}", "success")
    except ApiError as e:
        flash(f"Error generating GPG key: {e.detail}", "error")

    return redirect(url_for("packages.gpg_keys_management"))


@bp.route("/packages/gpg-keys/import", methods=["POST"])
@_login_required
def gpg_keys_import():
    """Import an existing GPG key."""
    armored_key = request.form.get("armored_key", "").strip()

    if not armored_key:
        flash("PGP key content is required", "error")
        return redirect(url_for("packages.gpg_keys_management"))

    try:
        result = api.import_gpg_key(armored_key)
        flash(f"GPG key imported successfully", "success")
    except ApiError as e:
        flash(f"Error importing GPG key: {e.detail}", "error")

    return redirect(url_for("packages.gpg_keys_management"))


@bp.route("/packages/gpg-keys/<key_id>/delete", methods=["POST"])
@_login_required
def gpg_keys_delete(key_id: str):
    """Delete a GPG key."""
    try:
        api.delete_gpg_key(key_id)
        flash(f"GPG key {key_id} deleted", "success")
    except ApiError as e:
        flash(f"Error deleting GPG key: {e.detail}", "error")

    return redirect(url_for("packages.gpg_keys_management"))


# ─── Multi-Distribution and Multi-Architecture (4.2–4.3) ────────────────────


@bp.route("/packages/by-distribution")
@_login_required
def packages_by_distribution():
    """Browse packages organized by Debian distribution."""
    distributions = api.get_distributions()
    architectures = api.get_architectures()
    repos_data = api.get_repos_by_distribution()
    repos_by_dist = repos_data.get("repos_by_distribution", {})

    return render_template(
        "packages_by_distribution.html",
        distributions=distributions,
        architectures=architectures,
        repos_by_dist=repos_by_dist,
    )


# ─── Raw .deb Upload (4.4) ─────────────────────────────────────────────────


@bp.route("/packages/upload", methods=["GET", "POST"])
@_login_required
def packages_upload():
    """Upload a .deb file, extract metadata, and preview before import."""
    repos = api.get_package_repos()
    repo_names = sorted([r.get("Name", r.get("name", "")) for r in repos if r.get("Name", r.get("name", ""))])
    upload_result = None

    if request.method == "POST":
        repo = request.form.get("repo", "").strip() or None
        distribution = request.form.get("distribution", "").strip() or None
        architecture = request.form.get("architecture", "").strip() or None
        is_overwrite = request.form.get("is_overwrite") == "on"

        uploaded = request.files.get("deb_file")
        if not uploaded or not uploaded.filename:
            flash("Please select a .deb file to upload", "error")
            return render_template("packages_upload.html", repos=repo_names, upload_result=None)

        if not uploaded.filename.lower().endswith(".deb"):
            flash("Only .deb files are supported", "error")
            return render_template("packages_upload.html", repos=repo_names, upload_result=None)

        try:
            upload_result = api.upload_package_file(
                file_name=uploaded.filename,
                file_bytes=uploaded.read(),
                repo=repo,
                distribution=distribution,
                architecture=architecture,
                is_overwrite=is_overwrite,
            )
            flash("Package uploaded and metadata extracted", "success")
        except ApiError as e:
            flash(f"Upload failed: {e.detail}", "error")

    return render_template("packages_upload.html", repos=repo_names, upload_result=upload_result)


@bp.route("/packages/upload/import", methods=["POST"])
@_login_required
def packages_upload_import():
    """Optional import step after metadata preview."""
    package_reference = request.form.get("package_reference", "").strip()
    repo = request.form.get("repo", "").strip()
    force = request.form.get("force") == "on"

    if not package_reference or not repo:
        flash("package_reference and repo are required", "error")
        return redirect(url_for("packages.packages_upload"))

    try:
        result = api.add_uploaded_package_to_repo(package_reference, repo, force=force)
        flash(result.get("message", "Package added to repository"), "success")
    except ApiError as e:
        flash(f"Import failed: {e.detail}", "error")

    return redirect(url_for("packages.packages_upload"))


# ─── Package Promotion Workflow (4.5) ──────────────────────────────────────


@bp.route("/packages/promotion")
@_login_required
def packages_promotion():
    """Show promotion plan (dev→staging, staging→prod)."""
    repos = api.get_package_repos()
    repo_names = sorted([r.get("Name", r.get("name", "")) for r in repos if r.get("Name", r.get("name", ""))])

    source_repo = request.args.get("source_repo", "").strip()
    target_repo = request.args.get("target_repo", "").strip()
    plan = None

    if source_repo and target_repo:
        try:
            plan = api.get_package_promotion_plan(source_repo, target_repo)
        except ApiError as e:
            flash(f"Could not build promotion plan: {e.detail}", "error")

    return render_template(
        "packages_promotion.html",
        repos=repo_names,
        source_repo=source_repo,
        target_repo=target_repo,
        plan=plan,
    )


@bp.route("/packages/promotion/execute", methods=["POST"])
@_login_required
def packages_promotion_execute():
    """Execute package promotion source→target."""
    source_repo = request.form.get("source_repo", "").strip()
    target_repo = request.form.get("target_repo", "").strip()
    force_replace = request.form.get("force_replace") == "on"

    if not source_repo or not target_repo:
        flash("Both source and target repository are required", "error")
        return redirect(url_for("packages.packages_promotion", source_repo=source_repo, target_repo=target_repo))

    try:
        result = api.execute_package_promotion(source_repo, target_repo, force_replace=force_replace)
        status = result.get("status")
        if status == "noop":
            flash(result.get("message", "No promotion needed"), "info")
        else:
            flash(result.get("message", "Promotion completed"), "success")
    except ApiError as e:
        flash(f"Promotion failed: {e.detail}", "error")

    return redirect(url_for("packages.packages_promotion", source_repo=source_repo, target_repo=target_repo))

