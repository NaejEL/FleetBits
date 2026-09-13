# LLM Agent Guidelines (Canonical)

> Audience: LLM coding agents working on FleetBits.
> This file is intentionally optimized for machine execution, not narrative human documentation.
> Last updated: 2026-03-28

---

## 1) Prime directive

Always prefer decisions that maximize:

1. **Security first** (fail closed, least privilege, no plaintext secrets)
2. **UI-first operations** (non-ops user can complete core tasks without CLI)
3. **Low-friction onboarding** (new dev starts with `dev-setup.ps1` / `dev-setup.sh`)

If a proposed change improves feature speed but weakens one of the above, reject it.

---

## 2) Planning hierarchy

When updating plans/docs:

1. `SECURITY_ROADMAP.md` is the canonical security direction
2. `FEATURE_ROADMAP.md` is the canonical product direction
3. Repo-specific roadmaps (e.g., `FleetBits-api/FEATURE_ROADMAP.md`) are scoped to that repo only

Never introduce a second conflicting source of truth.

---

## 3) Security requirements for all code changes

Agents MUST enforce:

- no plaintext token/secret storage at rest
- no logging of secrets, tokens, or credential equivalents
- fail-closed defaults for auth and transport boundaries
- explicit authorization checks on read and mutation paths
- regression tests for any security-sensitive behavior change

If a security control cannot be validated, mark status as **open** — never claim complete.

---

## 4) Secret lifecycle automation policy

Treat secret management as a product feature, not an ops footnote.

Required direction:

- automatic safe secret generation during setup
- guided rotation flow (UI and/or scripted)
- revocation support for compromised credentials
- predictable, low-friction developer workflow

Avoid manual copy/paste secret workflows when automation is feasible.

---

## 5) Non-ops UX policy

Default assumption: primary users are not infrastructure specialists.

Therefore:

- normal operations should be available in UI
- CLI/SSH is break-glass, not first-class UX
- docs and flows should reduce cognitive load
- status and error messages should be actionable, not jargon-heavy

---

## 6) Documentation cleanup rules

When docs conflict or bloat:

1. create clean canonical doc
2. downgrade old doc to compatibility pointer or delete if safe
3. update README doc map
4. remove stale claims (especially security claims)

Never leave contradictory security statements in active docs.

---

## 7) Pull request and governance expectations

Agent changes should align with enforced governance:

- branch protection required
- mandatory security checks
- mandatory security regression checks where configured
- pre-commit policy documented and adopted

If enforcement is not active, explicitly call it out as unresolved risk.

---

## 8) Implementation style constraints

- prefer small, verifiable increments
- preserve existing public API unless change is intentional and documented
- update tests with behavior changes
- never mark work complete without validation evidence

---

## 9) Architecture Decision Records (why we chose each technology)

These decisions are final for MVP. Do not revisit without a documented ADR.

| Domain | Choice | Key reason to NOT change |
|--------|--------|--------------------------|
| Metrics store | **Prometheus** | Industry standard, largest exporter ecosystem, native Grafana integration, PromQL is transferable skill. Migration to VictoriaMetrics is backend-swap only if scale demands. |
| Edge collector | **Grafana Alloy** | Single binary replacing node_exporter + promtail + systemd_exporter. WAL for store-and-forward during outages. One `.deb` per device. |
| Log store | **Loki** | Lightweight, label-indexed (same label model as Prometheus), native Grafana datasource. Not Elastic — too heavy. |
| Dashboards | **Grafana OSS** | Uncontested for this stack. No Grafana Enterprise needed at MVP. |
| Alerting | **Alertmanager** | `time_intervals` for per-site nightly quiet hours. Mature grouping/inhibition. |
| Deployment orchestration | **Semaphore UI** | <300 MB, REST API for Fleet API triggers, direct git integration, job history. Replace with Rundeck post-MVP for approval governance. Never AWX (requires Kubernetes). |
| Package distribution | **aptly** | `aptly repo copy` for dev→staging→prod promotion without re-signing. Snapshot model maps directly to rollout rings. REST API callable from Ansible. |
| VPN / remote access | **Headscale** (self-hosted WireGuard) | Self-hosted, one container, `ansible_host: 100.64.x.y` (direct SSH, no ProxyCommand). Tailscale SaaS creates a cloud dependency. Teleport needs separate auth cluster. |
| Fleet inventory | **Custom FastAPI + PostgreSQL** | No off-the-shelf CMDB (Netbox, Ralph, Snipe-IT) has Zone, Profile, ServiceOverride, Hotfix entities. Forcing a category mismatch costs more than building light custom. |
| Control plane host | **Single VPS, Docker Compose** | Full stack fits in 6 GB RAM (Hetzner CAX21 ~6 EUR/month). Upgrade VPS tier to scale — no Kubernetes needed until hundreds of zones. |

**Telemetry two-plane architecture (critical):**
- Telemetry push (metrics, logs, heartbeat): outbound HTTPS via Caddy — does NOT require VPN
- SSH management (deploy, restart, diagnose): Ansible over WireGuard mesh — DOES require Headscale
- This deliberate separation means Alloy's WAL keeps buffering during any VPN outage

---

## 10) Device naming convention

```
{role}-{site}-{zone}-{seq}
```

Examples: `mini-paris-pharaoh-01`, `rpi-paris-pharaoh-02`, `rpi-lyon-alice-01`

- All lowercase, hyphens only
- `role` is free-text descriptive (not an enum): `mini`, `rpi`, `server`, `kiosk`
- `zone` is the zone slug, not a number
- `seq` is zero-padded two digits

**DEVICE_ROLE** (distinct from the naming role prefix) is a short free-text string set at provisioning in `device-identity.conf`. Examples: `mini-orchestrator`, `mini-shared`, `rpi-puzzle`, `rpi-video`, `rpi-audio`, `rpi-av`, `rpi-all-in-one`, `rpi-mqtt-bridge`. Use lowercase + hyphens. No central registry — just be consistent within a device group.

---

## 11) Telemetry label convention (critical — define once, enforce everywhere)

All Prometheus metrics and Loki log streams must carry exactly these labels. They are injected by Grafana Alloy's relabel rules from `device-identity.conf` at config generation time.

| Label | Example | Source |
|-------|---------|--------|
| `site` | `paris` | Static in Alloy config (from SITE_ID) |
| `zone` | `pharaoh` | Static in Alloy config (from ZONE_ID) |
| `device_id` | `rpi-paris-pharaoh-02` | Static in Alloy config (from DEVICE_ID) |
| `device_role` | `rpi-video` | Static in Alloy config (from DEVICE_ROLE) |
| `profile` | `profile_v1` | Static in Alloy config (from PROFILE) |
| `environment` | `lab`, `prod` | Static in Alloy config (from ENVIRONMENT) |
| `ring` | `0`, `1`, `2` | Updated by install-fleet-agent playbook at each deployment |
| `service` | `zone-controller` | From systemd_exporter (unit name) |

**Never query Prometheus or Loki without filtering on at least `site` or `device_id`.** Fleet-wide unfiltered queries against 350 devices will be slow and expensive.

The `ring` label is a deployment-time annotation, not a fixed device property. Ansible updates it via `generate-config.sh` on every `fleet-agent` upgrade. Use it to correlate metric changes with ring-ring promotions.

---

## 12) Fleet data model (entity summary)

```
Site → Zone → Device → ServiceUnit
            ↓
         Profile (reusable baseline stack)
            ↓
         Override (site|zone|device scope, expires)
            ↓
         Deployment (ring-0|ring-1|prod|hotfix)
            ↓
         AuditEvent (immutable, all mutations)
```

**Key constraint — override resolution order (most specific wins):**
```
effective_manifest =
    common_bricks (global defaults)
    MERGE profile.baseline_stack
    MERGE site_overrides
    MERGE zone_overrides
    MERGE device_overrides
```

Each merge is a dict update — later layers win. The resolver is a simple Python function in Fleet API.

**Deployment state machine:**
```
pending → scheduled → deploying → success
                           ↓
                         failed → (operator initiates rollback manually)
                           ↓
                       rolled-back
```

Deployments require explicit `POST /deployments/{id}/trigger` — nothing fires automatically after creation.

---

## 13) Zone topology patterns (hardware reference)

The fleet uses three recurring hardware patterns. Dashboards and alert rules must work with all three:

- **Pattern A** — Dedicated mini-PC per zone: mini-PC runs orchestrator + MQTT broker; N RPis handle puzzles/video/audio
- **Pattern B** — Shared server: one mini-PC (role: `mini-shared`) serves multiple zones; zone RPis have their own MQTT broker
- **Pattern C** — RPi-heavy: mini-PC is orchestrator only; RPis handle video, audio, MQTT bridge, puzzles

All patterns are equal citizens. Monitoring is service-driven (systemd unit health), not topology-driven. `device_role` labels exist for dashboard filtering only.

---

## 14) Rollout rings reference

| Ring | Scope | Gate |
|------|-------|------|
| 0 — Lab | Dedicated lab devices (real hardware in office) | Automated smoke tests + manual validation (min 2h soak), zero P1/P2 alerts |
| 1 — Canary | 1–2 pilot sites, low criticality | Operator explicitly triggers + no P1/P2 for 24h |
| 2 — Production | All remaining sites | Operator explicitly triggers per site + no P1/P2 for 48h |
| Hotfix | Single device/zone, bypasses rings | Mandatory `changeId` + `reason` + expiry; must be promoted or reverted before expiry |

**Ring 0 requires real hardware** (RPi amd64/arm64/armhf). ARM CPU catches install failures that never appear on amd64 CI runners. Minimum lab: 2 × RPi 4, 1 × mini-PC.

Zones cannot be updated while in active session. The platform never auto-promotes rings — every ring promotion is an explicit operator action.
