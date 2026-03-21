"""
Fleet UI — HTTP server (Flask).

Entry point: flask run  (or python server.py for development)
"""

import os

from dotenv import load_dotenv
from flask import Flask, redirect, session, url_for

load_dotenv()

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-change-in-production")

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
    }


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=os.environ.get("FLEET_ENV") == "development")
