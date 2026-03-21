# FleetBits API

REST API for the FleetBits fleet management platform.

> **Operator?** You interact with this API through the [Fleet UI](https://github.com/NaejEL/FleetBits-ui) — you don''t need to use it directly. This README is for developers contributing to or integrating with the API.

Built with **FastAPI** + **SQLAlchemy 2 (async)** + **Alembic** + **PostgreSQL 16**.

---

## What it does

- Stores the fleet data model: sites → zones → devices → service units
- Resolves per-device software manifests via a layered override chain
- Manages and tracks ring-based deployments (pending → deploying → success/failed → rolled-back)
- Triggers Ansible jobs in Semaphore for deploy, rollback, restart, and diagnostics
- Proxies Prometheus and Loki queries for the Fleet UI
- Issues per-device bearer tokens for agent authentication
- Records an immutable audit log of every operator action
- (Planned) Acts as OIDC provider for Grafana/Semaphore SSO

---

## Stack

| Component | Choice |
|---|---|
| Framework | FastAPI 0.111 |
| ORM | SQLAlchemy 2.0 (async) |
| Migrations | Alembic |
| Database | PostgreSQL 16 |
| Auth | JWT (python-jose) |
| Validation | Pydantic v2 |
| Settings | pydantic-settings |
| HTTP client | httpx (Semaphore integration) |

---

## Local development

### Quickest setup

Run the platform dev-setup script from the sibling `FleetBits-platform` repo — it writes `FleetBits-api/.env` and starts all dependencies:

```powershell
# Windows
cd .\FleetBits-platform; .\dev-setup.ps1
```
```bash
# Linux / macOS
cd FleetBits-platform && ./dev-setup.sh
```

### Manual setup

```bash
cd FleetBits-api
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env
# Edit .env — at minimum set DATABASE_URL, FLEET_JWT_SECRET, and OPERATOR_PASSWORD

alembic upgrade head             # run DB migrations
uvicorn app.main:app --reload --port 8000
```

Interactive API docs: **http://localhost:8000/docs**

### Run tests

```bash
pytest tests/ -v
```

---

## Configuration

All settings are read from `.env` (or environment variables). Defaults are in `app/config.py`.

| Variable | Default | Description |
|---|---|---|
| `DATABASE_URL` | `postgresql+asyncpg://fleet:devpassword@localhost:5432/fleet` | asyncpg connection string |
| `FLEET_JWT_SECRET` | *(required)* | Secret key for signing JWT tokens |
| `FLEET_JWT_ALGORITHM` | `HS256` | JWT algorithm |
| `FLEET_JWT_EXPIRE_MINUTES` | `480` | Token lifetime (8 hours) |
| `OPERATOR_USERNAME` | `admin` | Default operator login |
| `OPERATOR_PASSWORD` | *(required)* | Default operator password — change immediately |
| `SEMAPHORE_URL` | `http://localhost:3001` | Semaphore base URL |
| `SEMAPHORE_API_KEY` | *(required)* | Semaphore API key |
| `SEMAPHORE_PROJECT_ID` | `1` | Semaphore project ID |
| `PROMETHEUS_URL` | `http://localhost:9090` | Prometheus base URL |
| `LOKI_URL` | `http://localhost:3100` | Loki base URL |
| `ALERTMANAGER_URL` | `http://localhost:9093` | Alertmanager base URL |
| `FLEET_ENV` | `development` | Environment tag injected into audit events |

---

## Authentication

### Operator login (human users)

```http
POST /api/v1/auth/login
Content-Type: application/json

{"username": "admin", "password": "<OPERATOR_PASSWORD>"}
```

Returns `{"access_token": "...", "token_type": "bearer", "expires_in": 28800}`.
Send as `Authorization: Bearer <token>` on subsequent requests.

Credentials are compared with `secrets.compare_digest` to prevent timing attacks.

### Per-device tokens

Devices authenticate using per-device bearer tokens issued by `POST /api/v1/devices/provision`.
Written to `/etc/fleet/device-identity.conf` by the Ansible bootstrap playbook.
Device tokens can only call device-scoped endpoints (heartbeat, provision) — not operator endpoints.

---

## Project structure

```
app/
├── main.py                  FastAPI app factory + router registrations
├── db.py                    SQLAlchemy async engine + session factory
├── auth.py                  JWT validation dependency (operator + device)
├── config.py                pydantic-settings — all env vars with defaults
│
├── models/
│   ├── site.py              Site (top-level fleet grouping)
│   ├── zone.py              Zone (sub-grouping within a site)
│   ├── device.py            Device + ServiceUnit
│   ├── profile.py           Profile + package/config manifests
│   ├── deployment.py        Override, Deployment, Hotfix
│   ├── audit.py             AuditEvent (append-only)
│   └── token.py             ProvisionToken (per-device bearer tokens)
│
├── schemas/                 Pydantic request/response schemas
│
├── routers/
│   ├── auth.py              POST /auth/login
│   ├── sites.py             CRUD — sites
│   ├── zones.py             CRUD — zones
│   ├── devices.py           CRUD — devices + service units + heartbeat
│   ├── profiles.py          Profile + manifest CRUD
│   ├── overrides.py         Per-device manifest overrides
│   ├── deployments.py       Ring deployments — create/gate/trigger/rollback
│   ├── hotfixes.py          Emergency deploys + SSH reconciliation
│   ├── operations.py        Restart / diagnostics -> Semaphore jobs
│   ├── observability.py     Prometheus/Loki/Alertmanager proxy
│   └── audit.py             Audit log (read-only)
│
└── services/
    ├── semaphore.py         Semaphore REST API client
    ├── token.py             Device token lifecycle
    └── manifest_resolver.py Layered override merge chain
```

---

## API endpoint overview

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/v1/auth/login` | Operator login → JWT |
| `GET/POST` | `/api/v1/sites` | List / create sites |
| `GET/PATCH/DELETE` | `/api/v1/sites/{id}` | Read / update / delete site |
| `GET/POST` | `/api/v1/zones` | List / create zones |
| `GET/POST` | `/api/v1/devices` | List / register devices |
| `GET/PATCH` | `/api/v1/devices/{id}` | Read / update device |
| `POST` | `/api/v1/devices/{id}/heartbeat` | Agent heartbeat (device-token auth) |
| `POST` | `/api/v1/devices/provision` | First-boot self-enrollment |
| `POST` | `/api/v1/devices/{id}/token` | Issue/retrieve device bearer token |
| `GET` | `/api/v1/targets/{id}/manifest` | Resolved software manifest |
| `GET/POST` | `/api/v1/profiles` | List / create profiles |
| `GET/POST` | `/api/v1/overrides` | List / create manifest overrides |
| `GET/POST` | `/api/v1/deployments` | List / create ring deployments |
| `POST` | `/api/v1/deployments/{id}/trigger` | Fire deployment job |
| `POST` | `/api/v1/deployments/{id}/promote` | Advance to next ring |
| `POST` | `/api/v1/deployments/{id}/rollback` | Roll back deployment |
| `GET/POST` | `/api/v1/hotfixes` | List / create hotfixes |
| `POST` | `/api/v1/hotfixes/{id}/reconcile-ssh` | Record SSH break-glass intervention |
| `POST` | `/api/v1/operations/restart` | Restart service on device(s) |
| `POST` | `/api/v1/operations/diagnostics` | Run diagnostics on device |
| `GET` | `/api/v1/query/service-health` | Prometheus query proxy |
| `GET` | `/api/v1/query/device-metrics/{id}` | Device metrics proxy |
| `GET` | `/api/v1/query/recent-logs` | Loki query proxy |
| `GET` | `/api/v1/alerts` | Alertmanager open alerts summary |
| `GET` | `/api/v1/audit` | Audit log (filterable, paginated) |

Full interactive spec with schemas and try-it: **http://localhost:8000/docs**

---

## Database migrations

```bash
# Create a new migration after model changes
alembic revision --autogenerate -m "add agent_version to device"

# Apply all pending migrations
alembic upgrade head

# Roll back one step
alembic downgrade -1
```