# FleetBits UI

Operator web interface for the FleetBits fleet management platform.

> **Non-devops user?** This is the app you use every day to manage your fleet. Read the [UI walkthrough](../platform/docs/ui-guide.md) for a screenshot-driven guide. This README is for developers contributing to or deploying the UI.

Built with **Flask 3.1** + **Jinja2** — no npm, no build step, no frontend framework.

---

## What it does

Everything you need to run your fleet, from a single browser tab:

- **Fleet Overview** — site health cards, open alerts, active ring rollout progress
- **Site / Zone View** — zone health matrix, per-service status, Grafana panels embedded inline
- **Device View** — live metrics, service list with one-click restart, device manifest
- **Deployment Center** — create ring deployments, watch per-ring progress bars, promote or roll back from the UI
- **Hotfix Console** — emergency deploys, SSH break-glass reconciliation
- **Audit Log** — immutable, filterable, paginated history of every action
- **User Management** — create users, assign roles (admin/operator/site_manager/viewer), manage API keys

---

## Pages

| URL | Page | Who uses it |
|---|---|---|
| `/login` | Login | Everyone |
| `/overview` | Fleet Overview | Everyone — morning health check |
| `/sites/<id>` | Site View | Operators monitoring a location |
| `/zones/<id>` | Zone View | Operators targeting a zone |
| `/devices/<id>` | Device View | Operators troubleshooting a device |
| `/deployments` | Deployment Center | Operators releasing new software |
| `/hotfixes` | Hotfix Console | Operators handling emergencies |
| `/audit` | Audit Log | Admins reviewing history |
| `/admin/users` | User Management | Admins |

---

## Stack

| Component | Choice |
|---|---|
| HTTP server | Flask 3.1 |
| Templates | Jinja2 |
| Auth | Session-based (JWT issued by Fleet API, stored in Flask session) |
| Frontend | Vanilla JS + Fetch API — no framework, no build tools |
| CSS | Plain CSS — dark ops theme |
| Grafana embeds | `<iframe>` d-solo panel URLs (`?kiosk`) |

---

## Local development

### Prerequisites

- Python 3.11+
- Fleet API running (start the full stack with `platform/dev-setup.ps1`)

### Quickest setup

```powershell
# Windows — starts everything including the UI
cd ..\platform; .\dev-setup.ps1
```
```bash
# Linux / macOS
cd ../platform && ./dev-setup.sh
```

Then open **http://localhost** (via Caddy) or **http://localhost:5000** (direct Flask).

### Manual setup

```bash
cd ui
python -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env
# Edit .env — set FLEET_API_URL and FLASK_SECRET_KEY

flask run --port 5000
```

### Tests

```bash
cd ui
python -m venv .venv
./.venv/bin/pip install -r requirements.txt -r requirements-dev.txt
./.venv/bin/python -m pytest
```

Two requirements files, deliberately: `requirements.txt` holds what the
application needs at runtime and is the only one `ui/Dockerfile` installs, so
the published `fleet-ui` image carries no test runner. `requirements-dev.txt`
holds the test dependencies. Both are watched by the same dependabot `pip`
entry on `/ui`.

To be exact about what "the image carries no test runner" means: the `pytest`
*package* is absent from the image — `python -c "import pytest"` fails in it.
The `requirements-dev.txt` *file* is present, along with `tests/`, `pytest.ini`
and `ruff.toml`, because the Dockerfile ends with `COPY . .` and `ui/` has no
`.dockerignore`. They are inert bytes, not an installed dependency surface.

CI runs the same command on every pull request touching `ui/**`
(`.github/workflows/ui-tests.yml`).

**What this suite covers.** One thing: that `server.py` imports and that the
Flask application object is built — the application factory runs, every
blueprint is registered, the URL map is populated and the session cookie
hardening survives the build. That is the failure a dependency bump produces
when Flask, Jinja2 or `requests` changes an API on the import path. It exists
because before it, a `ui/` dependency update was validated only by "`pip
install` resolved" and "no known CVE", and neither of those ever imports the
application.

**What this suite does NOT cover.** Everything a request would exercise. No
route is called, no template is rendered, no response is asserted, and no
interaction with the Fleet API is checked. A route returning the wrong data, a
template raising at render time, a missing permission check — none of that is
caught here, and a green run says nothing about any of it. This is the minimum
that makes "the dependency bump did not break the component" mean something;
it is not test coverage of `ui/`, and treating it as coverage would recreate
exactly the false assurance it was added to remove.

---

### Security contributor guardrails

Enable and run pre-commit hooks before every PR:

```bash
pip install pre-commit
pre-commit install
pre-commit run --all-files
```

Security and workflow files are covered by CODEOWNERS review policy.

---

## Configuration

| Variable | Default | Description |
|---|---|---|
| `FLEET_API_URL` | `http://localhost:8000` | Fleet API base URL |
| `FLASK_SECRET_KEY` | *(required)* | Session signing key |
| `FLASK_ENV` | `development` | `development` or `production` |
| `GRAFANA_URL` | `http://localhost:3000` | Grafana base URL for iframe embeds |

---

## Project structure

```
app/
├── __init__.py          Flask app factory
├── auth.py              Login/logout routes + JWT session handling
├── config.py            Environment-based configuration
│
├── routes/
│   ├── overview.py      Fleet Overview
│   ├── sites.py         Site View
│   ├── zones.py         Zone View
│   ├── devices.py       Device View
│   ├── deployments.py   Deployment Center
│   ├── hotfixes.py      Hotfix Console
│   ├── audit.py         Audit Log
│   └── admin.py         User Management
│
├── templates/
│   ├── base.html        Layout, nav sidebar, breadcrumbs, flash messages
│   └── ...              One template per page
│
└── static/
    ├── css/             Dark ops theme
    └── js/              Fetch helpers, live-update polling, toast notifications
```

---

## Design principles

- **Zero terminal after setup** — every fleet operation (deploy, rollback, restart, SSH, user creation) is reachable from the UI. Terminal-only features are tracked as bugs.
- **No frontend build step** — contributors can edit a `.html` file and refresh. No Webpack, no npm install.
- **Grafana panels embedded** — metric charts are Grafana iframes, not custom Python code. We don''t reimplement what Grafana already does well.
- **Progressive enhancement** — the UI works without JavaScript for read-only views. JS adds live updates and toast notifications.
