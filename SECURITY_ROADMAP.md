# FleetBits Security Roadmap

> Canonical security strategy and execution tracker for the monorepo.
> Last updated: 2026-03-29 (security hardening pass — P0 code fixes applied)

---

## Security posture (owner decision)

### Public production use

**Not yet safe enough to recommend without reservation.**

### Internal lab / controlled pilot use

**Possible with caution**, only if all are true:

- trusted operators only
- no hostile multi-tenant environment
- limited internet exposure
- fast patch cadence
- residual pilot risk is explicitly accepted

---

## P0 blockers (must close before public production)

- `SEC-P0-01` — **MQTT broker hardening completeness**
  - State: ✅ **CLOSED** (2026-03-29 — regression fix applied)
  - Done: per-device MQTT credentials (unique username+bcrypt password per device), fail-closed broker (`allow_anonymous=false`), topic-level ACL isolation (`device/<device_id>/#` only — heartbeat wildcard `device/+/heartbeat` removed to restore per-device isolation), ACL sync loop in Mosquitto every 300s
  - Regression fixed: `get_mqtt_acl()` previously included `"device/+/heartbeat"` allowing cross-device topic access — removed in this cycle
  - Evidence: `FleetBits-api/app/routers/devices.py` (`get_mqtt_acl`), `FleetBits-platform/docker/mosquitto/docker-entrypoint.sh`

- `SEC-P0-02` — **Device token/credential storage safety**
  - State: ✅ **CLOSED** (2026-03-29 — two regressions fixed)
  - Done: MQTT passwords bcrypt-hashed in DB (`mqtt_password_hash` column), plaintext returned **once** at enrollment only, device bearer tokens SHA-256 hashed at rest, migration `0007_device_mqtt_credentials.py` reversible
  - Regression 1 fixed: `provision_device` now enforces single-use via ProvisionToken DB lookup (hash → used_at check + mark consumed) — preventing replay attacks within 72h TTL
  - Regression 2 fixed: `provision_device` now stores `device_token_hash` so the temporary bearer token is valid for subsequent calls (was returned but never persisted)
  - Evidence: `FleetBits-api/app/routers/devices.py` (`provision_device`), `FleetBits-api/app/services/token.py`

- `SEC-P0-03` — **Branch protection across all 4 repos**
  - State: 🔧 **Infrastructure ready — run script to activate** (5 min total)
  - Done: `CODEOWNERS`, `PULL_REQUEST_TEMPLATE.md`, `dependabot.yml`, `security-baseline.yml` present in all 4 repos; `FleetBits-platform/scripts/apply-branch-protection.sh` written and ready
  - Next action (owner): `GITHUB_OWNER=<username> bash FleetBits-platform/scripts/apply-branch-protection.sh`
    (requires `gh` CLI authenticated with `admin:repo` scope)

- `SEC-P0-04` — **Required security baseline checks before merge**
  - State: 🔧 **Workflows deployed — activation requires branch protection** (see SEC-P0-03)
  - Done: `security-baseline.yml` with `dependency-review`, `secret-scan`, `python-sast-and-deps` (bandit + pip-audit), `filesystem-vuln-scan` (Trivy) deployed in all 4 repos
  - Next action (owner): Run `apply-branch-protection.sh` — it sets all checks as required

- `SEC-P0-05` — **Security regression suite required in CI**
  - State: 🔧 **Suite passing — activation requires branch protection** (see SEC-P0-03)
  - Done: `security-regression-stack` workflow exists and passes in `FleetBits-api`
  - Next action (owner): Run `apply-branch-protection.sh` — it sets `security-regression-stack` as required for `FleetBits-api`

- `SEC-P0-06` — **Pre-commit security enforcement**
  - State: 🔧 **Security hooks deployed — team adoption pending** (~1 week)
  - Done (2026-03-29): All 4 `.pre-commit-config.yaml` files updated with `gitleaks` (v8.18.4), `bandit` (1.7.8, `-r app -ll`), and `ruff --select S` hooks (Python repos); `detect-private-key` was the only security hook before this cycle
  - Next action (owner+team): Each developer runs `pre-commit install` in every repo they contribute to; add to new-hire onboarding

- `SEC-P0-07` — **Governance gates + JWT revocation completeness**
  - State: 🔧 **Code complete — activation requires branch protection** (see SEC-P0-03)
  - Done (2026-03-29): `POST /auth/logout` endpoint added — revokes active JWT via `jti` immediately; provision tokens now include `jti` UUID claim enabling individual revocation; `CODEOWNERS` and `pr-security-checklist.yml` workflows exist in all 4 repos
  - JWT revocation coverage: `change-password` → revokes by jti; `logout` → revokes by jti; admin `reset-password` → `token_valid_after` bulk invalidation; `update_user` (role/scope change) → `token_valid_after` bulk invalidation
  - Next action (owner): Run `apply-branch-protection.sh` to enforce CODEOWNERS and checklist as required checks

---

## S0 Security Gate — Full Item Status (as of 2026-03-28)

| Code | Category | Status |
|------|----------|--------|
| S0.1–S0.3 | Authorization scope checks | ✅ All router scopes enforced + tested |
| S0.4 | Input validation (PromQL/LogQL sanitized) | ✅ Complete |
| S0.5 | Provision token scope enforcement | ✅ Complete |
| S0.6–S0.7 | Secrets & fail-closed defaults | ✅ Complete |
| S0.8 | Package repo device-key auth + ACL | ✅ Complete |
| S0.9–S0.10 | Prometheus/Grafana access control | ✅ Public paths blocked |
| S0.11 | Semaphore admin auth enforced | ✅ Complete |
| S0.16–S0.17 | Telemetry trust + label canonicalization | ✅ Complete |
| S0.18 | Brute-force protection | ✅ Login rate-limit + audit |
| S0.19 | Public /metrics blocked | ✅ Complete |
| S0.20 | Dev toggles decoupled from ENV | ✅ Complete |
| S0.21 | JWT revocation (`jti`-based + staleness + logout) | ✅ Complete — `POST /auth/logout`, provision token `jti`, `change-password` |
| S0.NEW | Per-device MQTT credentials (bcrypt) | ✅ Complete — migration `0007` |
| **S0.12** | Toolchain required checks (GitHub branch protection) | 🔧 Script ready — `bash scripts/apply-branch-protection.sh` |
| **S0.13** | Developer pre-commit security hooks | 🔧 gitleaks + bandit + ruff-S deployed — team runs `pre-commit install` |
| **S0.14** | Pipeline security suite as required check | 🔧 69/69 tests pass — **5 min to activate** |
| **S0.15** | PR governance (CODEOWNERS + branch protection) | 🔧 Files present — **5 min to activate** |

**Total effort to close S0: ~30 min (GitHub UI) + 2 weeks (team adoption)**

---

## Security-first implementation waves

### Wave 1 — Close technical exploit paths ✅ COMPLETE

1. ✅ Closed MQTT broker hardening gaps (`SEC-P0-01`)
2. ✅ Eliminated plaintext credential exposure (`SEC-P0-02`)
3. ✅ Security regression tests for MQTT/token abuse: 69/69 passing

### Wave 2 — Enforce governance and merge safety 🔧 IN PROGRESS

1. Apply branch protections on all four repos (`SEC-P0-03`) — **pending owner action**
2. Require baseline security checks (`SEC-P0-04`) — **pending owner action**
3. Require security regression workflow (`SEC-P0-05`) — **pending owner action**
4. Enforce pre-commit + checklist policy (`SEC-P0-06`, `SEC-P0-07`) — **pending owner action**

### Wave 3 — Operability for non-ops teams ⬜ NOT STARTED

1. Automate secret creation for local/dev/prod onboarding
2. Automate secret rotation and revocation workflows
3. Provide UI-first secret lifecycle operations (create/rotate/revoke)

---

## Required security controls for merge policy

Apply to each repo:

- `FleetBits-api`
- `FleetBits-ui`
- `FleetBits-agent`
- `FleetBits-platform`

Minimum required checks:

1. `security-baseline`
2. `pr-security-checklist`
3. `security-regression-stack` (where applicable)
4. build/test workflow(s) for that repo

Minimum branch rules:

- pull request required before merge
- required status checks must pass
- stale approvals dismissed on new commits
- force pushes blocked
- direct pushes to protected branch blocked
- code owner review required for security-sensitive paths

---

## Security regression suite policy

The security suite must include at least:

- authZ scope boundary tests
- device token lifecycle misuse tests
- MQTT unauthorized topic access tests
- telemetry spoofing/injection tests
- secret leakage checks in logs/config dumps

Promotion rule:

- no merge to `main` with failing required security suite
- no “soft fail” for security regressions

---

## Production readiness gate (security)

FleetBits can be marked “safe for public production” only when:

1. all `SEC-P0-*` blockers are closed
2. required security checks are enforced in all 4 repos
3. security regression suite is stable and required
4. secret lifecycle automation exists (create/rotate/revoke) with low-ops UX
5. independent re-review confirms no critical open findings

Until then: treat production internet exposure as **high risk**.

---

## Trust boundary model

```
INTERNET
  │
  ▼
Caddy (TLS termination)
  ├── fleet-ui:5000          ← authenticated (JWT)
  ├── api.fleet:8000         ← authenticated (JWT)
  ├── grafana:3000           ← authenticated (Grafana built-in)
  ├── metrics.fleet:9090     ← /api/v1/write and /federate only; bearer token (risk: no per-device scope on write)
  ├── logs.fleet:3100        ← /loki/api/v1/push only; bearer token (risk: same as above)
  ├── repo.fleet:8080        ← unauthenticated read (packages are signed; no auth = exposure risk)
  └── headscale:8080         ← Headscale coordination server
  
HEADSCALE VPN (100.64.0.0/10) — all internal-only services
  ├── semaphore:3000         ← Ansible automation UI — Headscale-only (Caddy enforces)
  ├── prometheus:9090        ← no auth on internal port (trust VPN isolation only)
  ├── loki:3100              ← no auth on internal port (trust VPN isolation only)
  └── postgres:5432          ← no public exposure; fleet_net docker network only

fleet_net (Docker internal network)
  ├── fleet-api → postgres   ← ORM layer; parameterised queries only
  ├── fleet-api → mosquitto  ← ACL sync (admin credentials in secrets.env)
  └── fleet-api → headscale  ← API key in secrets.env
```

**Known risks to mitigate (Wave 3):**
1. `repo.fleet` (aptly) has no authentication — anyone who discovers the subdomain can list packages. Packages are GPG-signed, so downloads cannot be tampered with, but existence is disclosed.
2. Prometheus and Loki remote-write endpoints accept any valid device bearer token — no per-device write scope. A compromised device token can write metrics/logs with forged labels. Remediation: use the Fleet API telemetry proxy endpoints (`/api/v1/telemetry/metrics/write`, `/api/v1/telemetry/logs/push`) which enforce label rewriting server-side.
3. Prometheus scrape at `metrics.fleet/federate` is also exposed — requires auth header enforcement in Caddy or upstream. Currently trusted at network level only.

---

## MQTT architecture and threat model

### Implemented ACL design (SEC-P0-01 ✅ CLOSED)

Per-device topic namespace isolates devices from each other:

| Topic pattern | Access | Who |
|---|---|---|
| `devices/{device_id}/telemetry/#` | publish | device itself only |
| `devices/{device_id}/commands/#` | subscribe | device itself only |
| `devices/{device_id}/#` | publish + subscribe | fleet-api (admin) |
| `$SYS/#` | subscribe | fleet-api (admin) |

**Credentials:**
- Each device enrolled via `POST /api/v1/devices/provision` receives a unique MQTT username (`device_id`) and a randomly generated password (returned once, plaintext, in provisioning response)
- Password stored as bcrypt hash in `device.mqtt_password_hash` column — never retrievable after enrollment
- `allow_anonymous=false` on broker
- ACL file regenerated from DB every 300 seconds by the ACL sync loop in fleet-api

**Broker configuration (in docker-compose):**
- Internal listener: `fleet_net` only, port 1883 — no TLS needed (Docker encrypted overlay network)
- WebSocket listener: disabled (was 9001 — unnecessary and removed)
- External listener: none — fleet-api is the only MQTT gateway; devices never reach the broker directly

### Remaining MQTT improvements (Wave 3)

| Item | Priority | Description |
|---|---|---|
| Mutual TLS on MQTT listener | P2 | Replace username/password auth with client certificates; certificates derived from Headscale CA |
| Credential rotation | P1 | Add `POST /api/v1/devices/{id}/mqtt-credentials/rotate` endpoint; trigger via Semaphore when a device is re-imaged |
| Broker metrics exposure | P2 | Enable `$SYS` metrics scraping only from fleet-api Prometheus exporter; deny from device tokens |

---

## STRIDE analysis summary

### Fleet API (`fleet-api`)

| Threat | Category | Severity | Status |
|---|---|---|---|
| JWT forgery (weak secret) | Spoofing | High | Mitigated — strong random `JWT_SECRET` required in secrets.env |
| JWT missing `site_scope` claim enforcement | Elevation of Privilege | High | Mitigated — every DB query filters by site_scope claim |
| SQL injection via ORM | Tampering | High | Mitigated — SQLAlchemy parameterised queries only |
| PromQL/LogQL injection via observability proxy | Tampering | Medium | Partial — label values validated at API layer; full sanitisation pending |
| Audit log tampering | Repudiation | Medium | Partial — audit_event is append-only in code; no DB-level write lock yet |
| Deployment trigger race (no idempotency) | Tampering | Medium | Mitigated — `Idempotency-Key` header required on deployment creation |
| Out-of-scope resource enumeration | Information Disclosure | Medium | Mitigated — 404 returned for out-of-scope resources (not 403) |

### MQTT broker (`mosquitto`)

| Threat | Category | Severity | Status |
|---|---|---|---|
| Anonymous access | Spoofing | Critical | ✅ Closed — `allow_anonymous=false` |
| Cross-device topic spoofing | Tampering | Critical | ✅ Closed — per-device ACL `devices/{device_id}/#` |
| Credential brute-force | Spoofing | Medium | Partial — bcrypt cost=12; rate limiting not yet enforced at broker |
| Stale ACL (revoked device still has access) | Elevation | High | Partial — ACL reloads every 300s; immediate revocation not guaranteed within window |
| Broker admin credentials in env | Information Disclosure | Medium | Accepted risk — admin credentials in `secrets.env` on VPS; mitigated by VPS access controls |

---

## Related docs

- `FEATURE_ROADMAP.md` — non-security product roadmap
- `GUIDELINES.md` — developer and agent conventions
