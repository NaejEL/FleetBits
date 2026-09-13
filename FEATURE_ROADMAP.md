# FleetBits — Feature Roadmap

> Canonical product direction. Audience: all contributors and LLM agents.
> Last updated: 2026-03-28

---

## Product principles (non-negotiable)

1. **Security first** — all features must not weaken the security posture
2. **UI-first** — non-ops users must complete normal workflows without using CLI or SSH
3. **Low-friction** — new install or dev setup should be one-command with safe defaults

---

## Status legend

| Symbol | Meaning |
|--------|---------|
| ✅ | Complete and in production |
| 🔧 | Partially implemented |
| ⚠️ | Implemented but needs rework |
| ⬜ | Not started |

---

## Current implementation state (2026-03-28)

- **Fleet API**: FastAPI + PostgreSQL via SQLAlchemy + Alembic migrations + JWT auth + RBAC (`fleet_user` / `site_scope` tables)
- **Fleet UI**: Flask Jinja2 app; sidebar navigation; device / package / monitoring pages
- **Fleet Agent**: Grafana Alloy (OTLP metrics + logs); shipped as `.deb` via Aptly; per-device MQTT tokens
- **Platform**: Docker Compose on VPS; Caddy reverse-proxy; Grafana + Prometheus + Alertmanager; Aptly; Ansible + Semaphore

---

## Phase 0 — Runnable baseline (✅ Complete)

| # | Item | Status |
|---|------|--------|
| 0.1 | GHCR images for all four services built and pushed in CI | ✅ |
| 0.2 | Grafana SSO via Fleet API Auth Proxy (no separate Grafana login) | ✅ |
| 0.3 | Aptly GPG key baked into Aptly container image | ✅ |
| 0.4 | `Caddyfile.dev` for HTTP-only local dev (no ACME) | ✅ |
| 0.5 | Per-service README with one-command setup | ✅ |
| 0.6 | Per-device MQTT tokens issued at enrolment | ✅ |
| 0.7 | `dev-setup.ps1` / `dev-setup.sh` one-command local dev setup | ✅ |
| 0.8 | **Proxmox one-click installer** (`scripts/proxmox/ct/fleetbits.sh`) | ✅ |
| 0.9 | **Generic VPS / home server one-click installer** | ⬜ |

---

## Phase 1 — Security & multi-user (✅ Complete)

| # | Item | Status |
|---|------|--------|
| 1.1 | `fleet_user` table; bcrypt password hashing | ✅ |
| 1.2 | RBAC roles: `admin`, `operator`, `viewer` | ✅ |
| 1.3 | `site_scope` table; users scoped per site | ✅ |
| 1.4 | Admin UI: create / edit / delete users in Fleet UI | ✅ |
| 1.5 | `fleet_api_key` table with scoped permissions | ✅ |
| 1.6 | CI bot API key isolated from human users | ✅ |
| 1.7 | Device token isolation (one token per device, revocable) | ✅ |
| 1.8 | Input validation on all API endpoints via Pydantic | ✅ |
| 1.9 | `ip_address` column recorded on each login for audit | ✅ |
| 1.10 | OIDC stub endpoint (`GET /.well-known/openid-configuration`) | ✅ |

---

## Phase 2 — Core UX & navigation (🔧 Mostly complete)

| # | Item | Status |
|---|------|--------|
| 2.1 | SVG icon system; emoji removed from production UI | ✅ |
| 2.2 | Sidebar tree: Sites → Devices hierarchical navigation | ✅ |
| 2.3 | Breadcrumb component on all pages | ✅ |
| 2.4 | Role `<datalist>` fetching distinct roles from API | ✅ |
| 2.5 | Profile-to-device association workflow | ✅ |
| 2.6 | Device filter / search on device list page | ✅ |
| 2.7 | Effective manifest panel (current installed packages) | ✅ |
| 2.8 | Rollout progress banner (Phase 5 dependency) | ⬜ |
| 2.9 | Drift panel (desired vs actual manifest diff) | 🔧 |
| 2.10 | Toast notification system | ✅ |
| 2.11 | Skeleton loading screens | ✅ |
| 2.12 | Tooltips on action buttons | ✅ |

---

## Phase 3 — Observability stack (🔧 Mostly complete)

| # | Item | Status |
|---|------|--------|
| 3.1 | `node_exporter` systemd unit on VPS host OS | ✅ |
| 3.2 | `pid: host` + `/:/host:ro,rslave` on node_exporter container | ✅ |
| 3.3 | `cAdvisor` service in docker-compose | ✅ |
| 3.4 | Platform services Grafana dashboard | ✅ |
| 3.5 | Grafana iframe embedded in Fleet UI monitoring page | ✅ |
| 3.6 | Semaphore routed through Caddy (no WireGuard requirement) | ✅ |
| 3.7 | Prometheus alert rules starter file | ✅ |
| 3.8 | Alertmanager per-site `time_intervals` quiet hours template | ✅ |
| 3.9 | `systemd_exporter` Ansible role for edge devices | ✅ |
| 3.10 | MQTT broker metrics scraped by Prometheus | ✅ |
| 3.11 | Loki log retention policy (7-day default) | ✅ |
| 3.12 | Per-device metrics dashboard | 🔧 |
| 3.13 | Per-site aggregate dashboard | 🔧 |
| 3.14 | Alert routing to per-site webhooks | ⬜ |
| 3.15 | Log-based alerting via Loki rules | ⬜ |
| 3.16 | SLA / uptime report generation | ⬜ |

---

## Phase 3a — Unified SSO / Identity (🔧 Grafana done)

> **Vision**: FleetBits login = automatic login everywhere. Users never need to know
> separate credentials for Grafana, Semaphore, or Vaultwarden. Role and site-scope
> are enforced consistently across all services from a single source of truth.

### Architecture

```
Browser login → Fleet UI sets fleet_access JWT cookie (parent domain)
↓
Browser requests grafana.domain/… (iframe or direct)
↓
Caddy forward_auth → fleet-api/auth/grafana-verify (validates cookie JWT)
↓ 200 + X-WEBAUTH-USER/EMAIL/NAME/GROUPS headers
Grafana GF_AUTH_PROXY_ENABLED=true → auto-creates / auto-logs-in user
```

| # | Item | Status |
|---|------|---------|
| 3a.1 | `fleet_access` HttpOnly JWT cookie set on parent domain at login | ✅ |
| 3a.2 | `GET /api/v1/auth/grafana-verify` forward_auth endpoint (Caddy → Fleet API) | ✅ |
| 3a.3 | Caddy `forward_auth` + `copy_headers` on `grafana.{FLEET_DOMAIN}` (prod) | ✅ |
| 3a.4 | Caddy `forward_auth` on `/grafana/*` path (dev, localhost) | ✅ |
| 3a.5 | `GF_AUTH_PROXY_ENABLED / HEADER_NAME / AUTO_SIGN_UP` in Grafana env | ✅ |
| 3a.6 | `GF_AUTH_DISABLE_LOGIN_FORM=true` — no separate Grafana password | ✅ |
| 3a.7 | `grafana_provisioner.py` — creates Grafana user on FleetBits user creation | ✅ |
| 3a.8 | Grafana team per site (`site-{site_id}`); membership synced on role change | ✅ |
| 3a.9 | `grafana_user_id` in `fleet_user` table (migration 0008) | ✅ |
| 3a.10 | `GRAFANA_PROXY_SECRET` shared secret prevents header injection | ✅ |
| 3a.11 | Fleet UI iframe `GRAFANA_URL` routes through Caddy in dev (`/grafana/`) | ✅ |
| 3a.12 | Dashboard `var-site_id` auto-filter per user scope in iframes | ⬜ |
| 3a.13 | **Semaphore SSO**: Fleet API provisions per-user Semaphore accounts at user creation | ⬜ |
| 3a.14 | **Semaphore SSO**: Caddy forward_auth on `/semaphore/*` path | ⬜ |
| 3a.15 | **Vaultwarden SSO**: Fleet API as OIDC provider (`/.well-known/openid-configuration` fully implemented) | ⬜ |
| 3a.16 | **Vaultwarden SSO**: Vaultwarden configured with Fleet API OIDC endpoint | ⬜ |
| 3a.17 | Semaphore OIDC auth (uses Fleet API OIDC provider, same as Vaultwarden) | ⬜ |

### 3a.13 – Semaphore SSO design

- On `POST /auth/users` (any admin/operator user created): Fleet API calls Semaphore REST API
  (`POST /api/users`) to create a matching Semaphore account, stores `semaphore_user_id`
- On role change: update Semaphore role mapping (admin → admin, operator → manager/deployer)
- On deactivation: `DELETE /api/users/{semaphore_user_id}` in Semaphore
- Caddy `forward_auth` on `/semaphore/*` validates `fleet_access` cookie then injects
  Semaphore session header (or use Semaphore API token per user auto-injected in redirects)

### 3a.15 – OIDC provider design

- Fleet API already has `GET /.well-known/openid-configuration` stub (Phase 1.10)
- Full implementation: `GET /auth/authorize`, `POST /auth/token`, `GET /auth/userinfo`
- Scope: `openid profile email roles`; audience: per-service client IDs
- Enables SSO for any OIDC-compliant service (Vaultwarden, Semaphore, Netdata, etc.)
- This is the long-term clean backbone; Auth Proxy is the pragmatic current solution

---

## Phase 4 — Package management (🔧 Mostly complete)

| # | Item | Status |
|---|------|--------|
| 4.1 | GPG key management UI (upload / rotate) | ✅ |
| 4.2 | Multi-distro Aptly repos (bookworm, bullseye) | ✅ |
| 4.3 | Multi-arch build (amd64 + arm64) | ✅ |
| 4.4 | `.deb` upload UI in Fleet UI | ✅ |
| 4.5 | Package promotion workflow (dev → staging → prod) | ⬜ |
| 4.6 | Repo creation via UI (no manual Aptly shell) | ⬜ |
| 4.7 | Repo deletion with safety gate | ⬜ |
| 4.8 | Repo snapshot & rollback | ⬜ |
| 4.9 | Webhook receiver for CI-triggered package publish | ⬜ |

---

## Phase 5 — Deployment state machine (⬜ Not started)

| # | Item | Status |
|---|------|--------|
| 5.1 | Deployment state machine (`pending → active → complete / failed`) | ⬜ |
| 5.2 | Trigger gate: block new deployment while active one exists | ⬜ |
| 5.3 | `change_id` foreign key on deployment row | ⬜ |
| 5.4 | Ring progress bars in Fleet UI | ⬜ |
| 5.5 | Promote button (advance ring after soak period) | ⬜ |
| 5.6 | Rollback button (pin previous package version fleet-wide) | ⬜ |
| 5.7 | Ring soak policy configuration per site | ⬜ |
| 5.8 | Ring 0 CI auto-promote on green build | ⬜ |
| 5.9 | Platform CI pipeline run after compose deploy | ⬜ |
| 5.10 | Version pinning per-device override | ⬜ |

---

## Phase 6 — Device management (⬜ Not started)

| # | Item | Status |
|---|------|--------|
| 6.1 | Tag / label system for devices | ⬜ |
| 6.2 | Bulk operations (restart, force-check, assign package) | ⬜ |
| 6.3 | SD-card replacement wizard (new token, same identity) | ⬜ |
| 6.4 | Drift visibility: desired vs actual package list | ⬜ |
| 6.5 | Device health score (composite metric) | ⬜ |

---

## Phase 7 — Automation UI (⬜ Not started)

| # | Item | Status |
|---|------|--------|
| 7.1 | Ansible playbook trigger via Fleet UI (no CLI required) | ⬜ |
| 7.2 | Playbook run history & log viewer | ⬜ |
| 7.3 | Scheduled playbook jobs | ⬜ |
| 7.4 | Per-device override variables UI | ⬜ |

---

## Phase 8 — SSH & remote access (⬜ Not started)

| # | Item | Status |
|---|------|--------|
| 8.1 | xterm.js web terminal with session reason modal | ⬜ |
| 8.2 | Session recording (asciicast, stored in Loki) | ⬜ |
| 8.3 | Safe command palette (copy button, no free-form input) | ⬜ |
| 8.4 | Session audit log (user, device, duration, reason) | ⬜ |

---

## Phase 9 — Platform infrastructure (⬜ Not started)

| # | Item | Status |
|---|------|--------|
| 9.1 | Backup / restore UI (Postgres dump + Aptly snapshot) | ⬜ |
| 9.2 | Vaultwarden in docker-compose with Caddy route | ⬜ |
| 9.3 | TLS certificate lifecycle dashboard | ⬜ |
| 9.4 | Device token rotation wizard | ⬜ |
| 9.5 | Platform upgrade runbook (one-command, via Fleet UI) | ⬜ || 9.6 | **Generic VPS installer** — single `curl \| bash` for any Debian 12 server, no Proxmox dependency | ⬜ |
| 9.7 | **Home server installer** — optional Portainer/Dockge integration, no domain required (self-signed TLS or Tailscale) | ⬜ |
| 9.8 | Installer idempotency — re-running preserves secrets and data, only updates images | ⬜ |
| 9.9 | Post-install health check printed at end of each installer | ⬜ |

### 9.6 – Generic VPS installer design

```
curl -fsSL https://raw.githubusercontent.com/<owner>/FleetBits-platform/main/scripts/install/fleetbits-install.sh \
  | FLEET_DOMAIN=fleet.yourdomain.com bash
```

- Runs on any Debian 12 server (VPS, bare metal, home server)
- Installs Docker CE and Docker Compose from official repos
- Generates all secrets (same `openssl rand` + Alertmanager bcrypt approach as Proxmox installer)
- Writes `secrets.env`, enables `fleetbits.service` systemd unit
- Prompts for `FLEET_DOMAIN` interactively if not passed
- Prints credential summary and access URLs at completion
- **Difference from Proxmox installer**: no LXC container creation, no Proxmox API calls, no auto-login on tty1; this is for direct OS access

### 9.7 – Home server installer additions

- Flag: `--tailscale` — configure Caddy with Tailscale certificate authority instead of ACME Let's Encrypt
- Flag: `--no-domain` — use self-signed TLS, skip Caddy ACME, accessible at server LAN IP
- Optional: auto-enroll the host as a fleet device for self-monitoring (same as Proxmox installer prompt)
---

## Phase 10+ — Advanced features (⬜ Not started)

| # | Item | Status |
|---|------|--------|
| 10.1 | Golden image build pipeline (Packer or custom) | ⬜ |
| 10.2 | Full OIDC provider in Fleet API (see Phase 3a.15 for design) | ⬜ |
| 10.3 | TOTP / hardware-key MFA | ⬜ |
| 10.4 | SSO via Dex or Keycloak (alternative to built-in OIDC) | ⬜ |
| 10.5 | Kubernetes deployment target (Helm chart) | ⬜ |
| 10.6 | Multi-region VPS replication | ⬜ |
| 10.7 | Per-device signed manifest verification | ⬜ |
