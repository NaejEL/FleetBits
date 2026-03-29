# FleetBits Platform

> **New here?** Start with the [root README](../README.md) for an overview of FleetBits, then come back here.

This repository contains everything that runs on your **VPS control plane**: all 13 Docker services, Caddy configuration, Prometheus/Loki/Grafana setup, Ansible playbooks for edge devices, and the installer scripts.

| Repo | Purpose |
|---|---|
| **FleetBits-platform** ← you are here | Docker Compose control plane + Ansible automation |
| `FleetBits-api` | Fleet REST API (FastAPI + PostgreSQL) |
| `FleetBits-ui` | Operator web interface (Flask) |
| `FleetBits-agent` | Edge device agent (.deb package) |

---

## Services included

When you install FleetBits, these 13 services start automatically. You do not need to configure any of them separately.

| Service | Purpose | Access |
|---------|---------|--------|
| **Fleet UI** | Web interface for operators | `https://fleet.yourdomain.com` |
| **Fleet API** | REST API + OpenAPI docs | `https://api.fleet.yourdomain.com` |
| **Grafana** | Metrics dashboards | `https://grafana.fleet.yourdomain.com` |
| **Prometheus** | Metrics storage | internal (behind Caddy auth) |
| **Loki** | Log storage | internal |
| **Alertmanager** | Alert routing | internal (behind Caddy auth) |
| **Caddy** | HTTPS reverse proxy + auto TLS | — |
| **PostgreSQL** | Fleet database | internal |
| **Headscale** | WireGuard VPN coordinator | `https://headscale.fleet.yourdomain.com` |
| **Semaphore** | Ansible job runner | `https://semaphore.fleet.yourdomain.com` |
| **Aptly** | Private `.deb` package repository | `https://repo.fleet.yourdomain.com` |
| **Vaultwarden** | Self-hosted password manager | `https://vault.fleet.yourdomain.com` |
| **cAdvisor** | Container resource metrics | internal |

---

## Installing on a real server

### Option A — Proxmox VE (recommended)

Run this on your Proxmox host shell. It creates an LXC container, installs Docker, and starts the full stack:

```bash
GITHUB_OWNER=<github-owner> bash -c "$(curl -fsSL https://raw.githubusercontent.com/<github-owner>/FleetBits-platform/main/scripts/proxmox/ct/fleetbits.sh)"
```

The script asks for:
- Your domain (e.g. `fleet.yourdomain.com`)
- Container resources (CPU, RAM, disk) — defaults work for most deployments

After ~5 minutes, it prints `https://fleet.yourdomain.com` and an admin password.

> **DNS first**: Before running the installer, create DNS A records pointing `fleet.yourdomain.com` and `*.fleet.yourdomain.com` to your Proxmox host's IP. Caddy uses these to auto-issue TLS certificates via Let's Encrypt.

### Option B — Any Debian 12 server

```bash
curl -fsSL https://raw.githubusercontent.com/<github-owner>/FleetBits-platform/main/scripts/proxmox/install/fleetbits-install.sh \
  | GITHUB_OWNER=<github-owner> FLEET_DOMAIN=fleet.yourdomain.com bash
```

### Nginx on the Proxmox host (Option A only)

If you want nginx on the Proxmox host to handle TLS (recommended for production), use the provided example:

```bash
# On the Proxmox host
cp scripts/proxmox/nginx-example.conf /etc/nginx/sites-available/fleetbits
# Edit the file: replace yourdomain.com with your actual domain
nano /etc/nginx/sites-available/fleetbits
ln -s /etc/nginx/sites-available/fleetbits /etc/nginx/sites-enabled/
certbot --nginx -d fleet.yourdomain.com -d '*.fleet.yourdomain.com'
nginx -t && systemctl reload nginx
```

---

## Updating FleetBits

```bash
# On the VPS (or inside the LXC container)
fleetbits-update
```

This pulls the latest platform config (Prometheus rules, Grafana dashboards, Caddy config), pulls new API and UI images from GHCR, and restarts only the changed containers. Expected downtime: ~5–10 seconds per service.

For a full lifecycle walkthrough (dry-run, health checks, rollback path), see [`docs/operations/update-lifecycle.md`](docs/operations/update-lifecycle.md).

--

## Repository layout

```
FleetBits-platform/
├── secrets.env.example           Template — copy to secrets.env and fill in
├── dev-setup.ps1 / dev-setup.sh  One-command local development setup
├── scripts/
│   ├── proxmox/ct/fleetbits.sh   Proxmox LXC installer (run on PVE host)
│   ├── proxmox/install/          Install script (runs inside LXC)
│   ├── proxmox/nginx-example.conf  Nginx TLS termination example
│   └── update.sh                 Installed as `fleetbits-update`
│
├── docker/
│   ├── docker-compose.yml                    All 13 services
│   ├── docker-compose.override.behind-proxy.yml  For nginx/TLS-terminating proxy
│   ├── caddy/                    Caddyfile (auto-TLS + routing)
│   ├── prometheus/               Scrape config + alert rules
│   ├── loki/                     Log store config
│   ├── grafana/                  Dashboard JSON + provisioning
│   ├── alertmanager/             Alert routing + quiet-hours template
│   ├── headscale/                WireGuard mesh coordinator config
│   ├── postgresql/               Database init SQL
│   └── aptly/                    Private .deb repository image
│
├── ansible/
│   ├── inventories/              Device inventory per environment
│   ├── group_vars/               Variables + encrypted vault
│   ├── roles/                    Reusable roles
│   └── playbooks/                Day-to-day operation playbooks
│
└── docs/
    ├── quickstart.md
    ├── ui-guide.md
    ├── enrolling/
    └── operations/
```

---

## Quick start — local development

### Prerequisites

- Docker Engine + Compose v2
- All four repos cloned into the same parent directory:

```
FleetBits/
├── FleetBits-platform/   ← run dev-setup from here
├── FleetBits-api/
├── FleetBits-ui/
└── FleetBits-agent/
```

### One command (recommended)

**Windows (PowerShell):**
```powershell
cd FleetBits-platform
.\dev-setup.ps1
```

**Linux / macOS:**
```bash
cd FleetBits-platform
./dev-setup.sh
```

The script generates all secrets, writes every config file, and starts the full stack. It prints service URLs and credentials when done.

### Local service URLs

| URL | Service | Notes |
|-----|---------|-------|
| http://localhost | Fleet UI | Login: `admin` / your `OPERATOR_PASSWORD` |
| http://localhost:8000/docs | Fleet API + Swagger | |
| http://localhost/grafana | Grafana | Routed through Caddy with Fleet UI SSO (no direct :3000 login in dev) |
| http://localhost/semaphore | Semaphore | Routed through Caddy (dev/prod parity) |
| http://localhost/alertmanager | Alertmanager | Basic auth via `ALERTMANAGER_BASIC_AUTH_*` in `secrets.env` |
| http://localhost:9090 | Prometheus | |

### Telemetry ingest security (March 2026)

Fleet metrics and logs ingress is now enforced through `fleet-api` authentication:

- `https://metrics.<domain>/api/v1/write` is routed to `fleet-api` telemetry ingress (device bearer required)
- `https://logs.<domain>/loki/api/v1/push` is routed to `fleet-api` telemetry ingress (device bearer required)
- Direct unauthenticated writes to Prometheus/Loki public routes are blocked at Caddy

Compatibility rollback (temporary only): set `TELEMETRY_AUTH_REQUIRED=false` in `secrets.env` and restart `fleet-api`.
Use this only as an emergency bridge during migration; keep it `true` in production.

### Manual setup

```bash
cp secrets.env.example secrets.env
# Edit secrets.env — replace all CHANGE_ME values
cp docker/docker-compose.override.yml.example docker/docker-compose.override.yml
cd docker
docker compose --env-file ../secrets.env up -d
```

### Security contributor guardrails

Enable pre-commit hooks locally and run them before submitting a PR:

```bash
pip install pre-commit
pre-commit install
pre-commit run --all-files
```

Security/governance files are CODEOWNERS-protected and expected to receive owner review.

---

## Ansible vault

Ansible secrets (SSH keys, API tokens, site-specific credentials) are stored in an encrypted vault file. Operators never see the raw values.

```bash
# One-time: create a vault password (store it in Vaultwarden, not in the repo)
echo "$(openssl rand -base64 32)" > ~/.fleet-vault-pass
chmod 600 ~/.fleet-vault-pass

cd ansible
cp group_vars/all/vault.yml.example group_vars/all/vault.yml
# Edit vault.yml — fill all CHANGE_ME values
ansible-vault encrypt group_vars/all/vault.yml --vault-password-file ~/.fleet-vault-pass
```

---

## Secrets reference

| File | Contents | Committed? |
|------|----------|-----------|
| `secrets.env` | All Docker Compose service credentials | **No** — in `.gitignore` |
| `docker/docker-compose.override.yml` | Local build contexts + port overrides | **No** |
| `FleetBits-api/.env` | API env for local dev | **No** |
| `FleetBits-ui/.env` | UI env for local dev | **No** |
| `ansible/group_vars/all/vault.yml` | Ansible secrets (encrypted ciphertext) | **Yes** — encrypted |

The vault password lives only in your team's password manager (Vaultwarden). Never commit it.

---

## Adding a new site

```bash
# 1. Create the site in Fleet UI → Sites → Add site
# 2. Create ansible/inventories/prod/site_<slug>.yml
# 3. Add ansible/group_vars/site_<slug>/vars.yml (from template)
# 4. Add Alertmanager quiet_hours for the site timezone
# 5. Enroll devices: Fleet UI → Devices → Add device → follow the wizard
```

See `docs/operations/new-site.md` for the complete checklist.
