# FleetBits

**Open-source, self-hosted fleet management platform for Linux edge devices.**

FleetBits lets you manage hundreds of Raspberry Pis, mini-PCs, and x86 devices from a single web interface — **no terminal required for day-to-day operations**. Deploy software updates by ring, monitor health in real time, roll back in one click, and get alerted before problems become outages.

> **Who is this for?** Operations teams, technicians, and system administrators who manage distributed Linux device fleets in the field — digital signage networks, retail kiosks, industrial edge nodes — where people are not necessarily Linux engineers.

> **Security status:** Not yet recommended for public production without reservation. See [SECURITY_ROADMAP.md](SECURITY_ROADMAP.md) for open blockers. Internal lab / controlled pilot use is feasible with caution.

---

## What you can do from the web UI

- **Monitor** every device's CPU, memory, disk, temperature, and service states — live, from anywhere
- **Deploy** software packages to your fleet with a ring-based rollout (test on 1 device → group → full fleet)
- **Roll back** any deployment with one click if something goes wrong
- **SSH** into any device directly from the browser — no VPN client needed
- **Manage users** with role-based access (admin, operator, site manager, viewer)
- **Alert** on failures before your operators notice them

---

## Architecture at a glance

```
┌──────────────────────────────────────────────────────────┐
│  Your VPS  (one Linux server, ~4 GB RAM)                 │
│                                                          │
│   ┌─────────────┐   ┌──────────────┐   ┌─────────────┐  │
│   │  Fleet UI   │──▶│  Fleet API   │──▶│ PostgreSQL  │  │
│   │  (web app)  │   │  (REST API)  │   │ (database)  │  │
│   └─────────────┘   └──────┬───────┘   └─────────────┘  │
│                            │                             │
│   ┌─────────────┐   ┌──────▼───────┐   ┌─────────────┐  │
│   │   Grafana   │◀──│  Prometheus  │   │    Loki     │  │
│   │ (dashboards)│   │  (metrics)   │   │   (logs)    │  │
│   └─────────────┘   └─────────────┘   └─────────────┘  │
│                                                          │
│   ┌─────────────┐   ┌──────────────┐   ┌─────────────┐  │
│   │  Headscale  │   │  Semaphore   │   │    Aptly    │  │
│   │  (VPN hub)  │   │  (Ansible)   │   │ (.deb repo) │  │
│   └─────────────┘   └──────────────┘   └─────────────┘  │
│                                                          │
│   Caddy (HTTPS reverse proxy — handles TLS for you)      │
└──────────────────┬───────────────────────────────────────┘
                   │  WireGuard VPN (Headscale)
     ┌─────────────┼─────────────────────────┐
     ▼             ▼                         ▼
 Raspberry Pi   Mini-PC                  x86 device
 (fleet-agent)  (fleet-agent)            (fleet-agent)
```

Each edge device runs **fleet-agent** — a single `.deb` package that handles metrics, logs, heartbeats, and remote commands. The agent connects back to your VPS through an encrypted WireGuard tunnel managed by Headscale.

---

## Repository layout

| Folder | Purpose |
|------|---------|
| **`/`** ← you are here | Monorepo root — docs, security roadmap, feature roadmap, CI |
| `platform/` | VPS control plane (Docker Compose + Ansible) |
| `api/` | REST API (FastAPI + PostgreSQL) |
| `ui/` | Web interface (Flask) |
| `agent/` | Edge device agent (.deb package) |

---

## Installing FleetBits

You need:
- A Linux VPS with at least **2 CPU cores and 4 GB RAM** (Debian 12 recommended)
- A **domain name** with DNS records pointing to your VPS (e.g. `fleet.yourdomain.com`)
- Nothing else — the installer handles Docker, TLS certificates, and all configuration

### Option A — Proxmox (recommended)

If you run Proxmox VE, FleetBits installs into an LXC container with one command on your Proxmox host:

```bash
GITHUB_OWNER=<github-owner> bash -c "$(curl -fsSL https://raw.githubusercontent.com/<github-owner>/FleetBits/main/platform/scripts/proxmox/ct/fleetbits.sh)"
```

The script asks a few questions (domain, container resources) and does the rest. Takes about 5 minutes.

### Option B — Direct on any Debian 12 VPS

Same installer script, run directly on the server (bare metal, cloud VPS, home server):

```bash
curl -fsSL https://raw.githubusercontent.com/<github-owner>/FleetBits/main/platform/scripts/proxmox/install/fleetbits-install.sh \
  | GITHUB_OWNER=<github-owner> FLEET_DOMAIN=fleet.yourdomain.com bash
```

> **Planned:** A dedicated `scripts/install/fleetbits-install.sh` for non-Proxmox targets is on the Phase 9 roadmap. It will add home-server modes (Tailscale TLS, no-domain self-signed) and full idempotency.

### After installation

The installer prints a credential summary. Open `https://fleet.yourdomain.com` in your browser to log in.

> Grafana, once opened via Fleet UI, logs in automatically through FleetBits SSO — no separate Grafana password needed.

---

## Connecting your first device

1. In the Fleet UI → **Devices** → **Add device** — fill in name and location
2. The UI generates a provision token and a `fleet-provision.json` file
3. Flash a Raspberry Pi OS Lite SD card using [Raspberry Pi Imager](https://www.raspberrypi.com/software/)
   - Under "Advanced options" → "Custom files" → add the `fleet-provision.json` to `/boot/firmware/`
4. Boot the Pi — it self-enrolls within 60 seconds and appears in the Fleet UI

No SSH needed. No manual package installation.

---

## Documentation

| Guide | Audience |
|-------|---------|
| [Quick-start guide](platform/docs/quickstart.md) | Everyone |
| [Web UI walkthrough](platform/docs/ui-guide.md) | Operators |
| [Enrolling a device](platform/docs/enrolling/) | Technicians |
| [Platform README](platform/README.md) | Admins / DevOps |
| [API README](api/README.md) | Developers |
| [Security roadmap](SECURITY_ROADMAP.md) | Everyone |
| [Feature roadmap](FEATURE_ROADMAP.md) | Everyone |
| [LLM agent guidelines](LLM_AGENT_GUIDELINES.md) | AI contributors |
| [Roadmap pointer](ROADMAP.md) | Everyone |

---

## Key features

| Feature | Detail |
|---------|--------|
| **Ring-based deployments** | Deploy to Ring 0 (1 device) → Ring 1 (test group) → Ring 2 (full fleet). Automatic soak periods. |
| **One-click rollback** | Every deployment stores the previous state. Rollback completes in seconds. |
| **Grafana built-in** | Metrics and dashboards are included out of the box. No separate Grafana subscription. |
| **Self-hosted** | All data stays on your VPS. No cloud dependency, no per-device fees. |
| **Ansible automation** | Run playbooks on any device or group directly from the web UI. |
| **Private `.deb` repository** | Host your own packages with Aptly. Push new versions from CI, deploy to fleet. |
| **WireGuard mesh** | Headscale keeps all devices connected through a zero-config mesh VPN. |

---

## Status

FleetBits is in active development. Canonical planning docs:

- [SECURITY_ROADMAP.md](SECURITY_ROADMAP.md)
- [FEATURE_ROADMAP.md](FEATURE_ROADMAP.md)
- [SECURITY_IMPLEMENTATION_PLAN.md](SECURITY_IMPLEMENTATION_PLAN.md)

---

## Security

**Q: Is FleetBits safe to use?**

For **public production use**: **No, not yet safe enough to recommend without reservation**.

For **internal lab / controlled pilot use**: **possible with caution**, if operators are trusted, exposure is limited, and patch cadence is fast.

See [IS_FLEETBITS_SAFE.md](IS_FLEETBITS_SAFE.md) for the concise safety decision and [SECURITY_ROADMAP.md](SECURITY_ROADMAP.md) for open blockers and required closure criteria.

| Use Case | Safe? |
|----------|-------|
| Development/staging | ✅ Yes |
| Internal/controlled pilot | ⚠️ Maybe, with caution |
| Public internet (production) | ❌ Not yet |
| Healthcare/regulated | ❌ Requires substantial additional compliance/security work |

**Current Security Execution Board**: [SECURITY_IMPLEMENTATION_PLAN.md](SECURITY_IMPLEMENTATION_PLAN.md)

---

## Contributing

Contributions welcome. Start by reading the README of the component you are touching (`api/`, `ui/`, `agent/`, `platform/`). Issues and discussions open on GitHub.

---

## License

MIT
