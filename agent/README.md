# FleetBits Agent

> **Operator?** You don't need to read this repo to enroll devices. Go to the [enrollment guide](../FleetBits-platform/docs/enrolling/) instead. This README is for people who want to understand, build, or modify the agent itself.

`fleet-agent` is the small software package that runs on every edge device in your fleet (Raspberry Pi, mini-PC, x86 server). Install it once — via a golden SD card image or `apt install` — and the device immediately starts reporting to your FleetBits control plane.

---

## What fleet-agent does

Once installed, the agent:

1. **Pushes metrics** — CPU, RAM, disk, temperature, network — to Prometheus on your VPS, every 30 seconds
2. **Pushes logs** — journal output from all systemd services — to Loki on your VPS, continuously
3. **Reports service health** — state of every systemd unit (active / failed / inactive) — visible in Fleet UI
4. **Sends heartbeats** — device identity + agent version + service states — to Fleet API every 30 seconds
5. **Self-enrolls on first boot** — reads `fleet-provision.json` from the SD card, calls the Fleet API, and configures itself. No SSH needed.

All of this happens automatically. Operators never need to SSH into a device to configure or update the agent.

---

## Enrolling a device (operator guide)

The **recommended way** is through the Fleet UI — no terminal needed:

1. Fleet UI → **Devices** → **Add device**
2. Fill in the device name, site, and zone
3. The UI generates a `fleet-provision.json` file — download it
4. Flash the SD card with Raspberry Pi OS Lite using [Raspberry Pi Imager](https://www.raspberrypi.com/software/)
   - Click "Next" → "Edit Settings" → then scroll to **Custom files** → add `fleet-provision.json` to `/boot/firmware/`
5. Insert the SD card and power on — the device appears in Fleet UI within 60 seconds

For replacing a failed device, replacing an SD card, or bulk-enrolling an existing fleet, see the detailed guides in [FleetBits-platform/docs/enrolling/](../FleetBits-platform/docs/enrolling/).

---

## What it installs

```
fleet-agent_<version>_<arch>.deb
  /usr/bin/alloy                               <- Grafana Alloy binary (bundled)
  /etc/fleet/device-identity.conf.example      <- identity template (filled at provision time)
  /usr/lib/fleet-agent/generate-config.sh      <- generates /etc/alloy/config.alloy from identity
  /usr/lib/fleet-agent/heartbeat.sh            <- POSTs heartbeat to Fleet API every 30s
  /usr/lib/fleet-agent/firstboot.sh            <- first-boot self-enrollment
  /lib/systemd/system/fleet-agent.service      <- main service (runs Alloy)
  /lib/systemd/system/fleet-heartbeat.timer    <- systemd timer: heartbeat every 30s
  /lib/systemd/system/fleet-firstboot.service  <- one-shot enrollment unit (self-disabling)
```

The **only file an operator ever touches** is `/etc/fleet/device-identity.conf` — and even that is written automatically during provisioning.

---

## Upgrade behaviour

When `apt-get upgrade fleet-agent` runs on a device:

1. `postinst.sh` re-runs `generate-config.sh` — Alloy config is regenerated from the current identity file
2. `fleet-agent.service` restarts (~5 seconds)
3. **The identity file is never overwritten** — it is declared as a Debian conffile
4. **Telemetry gap is backfilled** — Alloy''s WAL replays any metrics buffered during the restart

No operator action required. Devices update through the ring deployment process triggered from Fleet UI.

---

## Supported architectures

| Architecture | Target hardware |
|---|---|
| `amd64` | Mini-PC, NUC, x86 servers |
| `arm64` | Raspberry Pi 4/5, ARM64 SBCs |
| `armhf` | Raspberry Pi 3/Zero, ARMv7 SBCs |

---

## Repository layout (for contributors)

```
FleetBits-agent/
├── etc/fleet/
│   └── device-identity.conf.example    identity template
├── usr/lib/fleet-agent/
│   ├── generate-config.sh              reads identity -> writes Alloy config
│   ├── heartbeat.sh                    heartbeat sender
│   └── firstboot.sh                    SD card replacement self-enrollment
├── lib/systemd/system/
│   ├── fleet-agent.service
│   ├── fleet-heartbeat.timer
│   └── fleet-firstboot.service
├── scripts/
│   ├── build-deb.sh                    fpm invocation (all three architectures)
│   └── postinst.sh                     Debian postinst hook
├── ALLOY_VERSION                       pinned Grafana Alloy version
└── .github/workflows/
    └── build-fleet-agent.yml           CI: builds on tag push, publishes to Aptly dev
```

---

## Building from source

### Prerequisites

- Ruby + `fpm` (`gem install fpm`)
- `curl` (downloads the Alloy binary at build time)

### Build for all architectures

```bash
AGENT_VERSION=0.1.0 ./scripts/build-deb.sh
# Outputs:
#   dist/fleet-agent_0.1.0_amd64.deb
#   dist/fleet-agent_0.1.0_arm64.deb
#   dist/fleet-agent_0.1.0_armhf.deb
```

### Build for a single architecture

```bash
AGENT_VERSION=0.1.0 ARCH=arm64 ./scripts/build-deb.sh
```

### CI/CD

Push a version tag to trigger the full release pipeline:

```bash
git tag v0.2.0 && git push origin v0.2.0
```

The `build-fleet-agent.yml` workflow:
1. Builds `.deb` packages for all three architectures
2. Uploads to Aptly `dev` repository
3. Builds and pushes a container image to GHCR
4. Triggers a Ring 0 deployment

Use `promote.yml` (manual `workflow_dispatch`) to advance the release through staging → production rings.

---

## device-identity.conf reference

This file lives at `/etc/fleet/device-identity.conf` on every device. It is the only configuration file the agent reads.

```ini
# Written by fleet-firstboot.sh or ansible bootstrap playbook.
# This file is a Debian conffile — apt upgrade will never overwrite it.

DEVICE_ID=player-paris-hall-a-01
SITE_ID=paris
ZONE_ID=hall-a
RING=0

FLEET_API_URL=https://api.fleet.yourdomain.com
FLEET_AGENT_TOKEN=<per-device-bearer-token>
PROMETHEUS_URL=https://metrics.fleet.yourdomain.com
LOKI_URL=https://logs.fleet.yourdomain.com

# Feature flags (set per device by Ansible)
ENABLE_MQTT_EXPORTER=false
ENABLE_PROCESS_EXPORTER=false
SCRAPE_INTERVAL=30s
```