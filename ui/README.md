# FleetBits UI

Operator web interface for the FleetBits fleet management platform.

> **Non-devops user?** This is the app you use every day to manage your fleet. Read the [UI walkthrough](../FleetBits-platform/docs/ui-guide.md) for a screenshot-driven guide. This README is for developers contributing to or deploying the UI.

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
- Fleet API running (start the full stack with `FleetBits-platform/dev-setup.ps1`)

### Quickest setup

```powershell
# Windows — starts everything including the UI
cd .\FleetBits-platform; .\dev-setup.ps1
```
```bash
# Linux / macOS
cd FleetBits-platform && ./dev-setup.sh
```

Then open **http://localhost** (via Caddy) or **http://localhost:5000** (direct Flask).

### Manual setup

```bash
cd FleetBits-ui
python -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env
# Edit .env — set FLEET_API_URL and FLASK_SECRET_KEY

flask run --port 5000
```

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