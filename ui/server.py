"""
Fleet UI — HTTP server (Flask).

Entry point: flask run  (or python server.py for development)
"""

import os

from dotenv import load_dotenv
from flask import Flask, redirect, session, url_for

load_dotenv()

_INSECURE_UI_SECRET_DEFAULT = "dev-secret-change-in-production"


def _env_flag(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _require_secret_key() -> str:
    secret = os.environ.get("SECRET_KEY")
    if not secret:
        raise RuntimeError("Refusing to start Fleet UI: SECRET_KEY is required")
    if secret == _INSECURE_UI_SECRET_DEFAULT:
        raise RuntimeError("Refusing to start Fleet UI: SECRET_KEY is using an insecure default")
    if len(secret) < 32:
        raise RuntimeError("Refusing to start Fleet UI: SECRET_KEY must be at least 32 characters long")
    return secret

app = Flask(__name__)
app.secret_key = _require_secret_key()
_max_upload_bytes = int(os.environ.get("MAX_CONTENT_LENGTH", str(50 * 1024 * 1024)))
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=not _env_flag("FLASK_DEBUG", default=False),
    MAX_CONTENT_LENGTH=_max_upload_bytes,
)

# ─── Blueprints ──────────────────────────────────────────────────────────────

from blueprints.auth import bp as auth_bp  # noqa: E402
from blueprints.inventory import bp as inventory_bp  # noqa: E402
from blueprints.deployments import bp as deployments_bp  # noqa: E402
from blueprints.hotfixes import bp as hotfixes_bp  # noqa: E402
from blueprints.audit import bp as audit_bp  # noqa: E402
from blueprints.admin import bp as admin_bp  # noqa: E402
from blueprints.packages import bp as packages_bp  # noqa: E402
from blueprints.monitoring import bp as monitoring_bp  # noqa: E402

app.register_blueprint(auth_bp)
app.register_blueprint(inventory_bp)
app.register_blueprint(deployments_bp)
app.register_blueprint(hotfixes_bp)
app.register_blueprint(audit_bp)
app.register_blueprint(admin_bp)
app.register_blueprint(packages_bp)
app.register_blueprint(monitoring_bp)

# ─── Root redirect ────────────────────────────────────────────────────────────

@app.route("/")
def index():
    if "jwt" not in session:
        return redirect(url_for("auth.login_page"))
    return redirect(url_for("inventory.overview"))


# ─── Template globals ─────────────────────────────────────────────────────────

@app.context_processor
def inject_globals():
    return {
        "grafana_url": os.environ.get("GRAFANA_URL", "http://localhost:3000"),
        "semaphore_url": os.environ.get("SEMAPHORE_URL", "http://localhost:3001"),
        "current_user": session.get("username"),
        "current_role": session.get("role", "viewer"),
        "current_site_scope": session.get("site_scope"),
    }


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=_env_flag("FLASK_DEBUG", default=False))
