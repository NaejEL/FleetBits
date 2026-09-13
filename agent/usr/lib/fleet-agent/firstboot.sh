#!/bin/bash
# /usr/lib/fleet-agent/firstboot.sh
# ─────────────────────────────────────────────────────────────────────────────
# First-boot provisioning script. Runs once on a freshly flashed device.
# Called by fleet-firstboot.service (Type=oneshot, RemainAfterExit=no).
#
# Pre-requisites:
#   /boot/firmware/fleet-provision.json must exist, containing:
#   {
#     "device_id":          "rpi-paris-zone1-02",
#     "provision_token":    "<single-use JWT, 72h TTL>",
#     "api_url":            "https://api.fleet.example.com",
#     "headscale_url":      "https://headscale.fleet.example.com"
#   }
#
# Written by rpi-imager "Advanced Options → Custom files" before flashing.
#
# What this script does:
#   1. Reads fleet-provision.json
#   2. POSTs to Fleet API /api/v1/devices/{device_id}/provision and receives the
#      device identity file (inert KEY=value lines — see identity-lib.sh)
#   3. Validates the file with the strict parser before installing it
#   4. Runs generate-config.sh to produce the collector config
#   5. Enrolls in Headscale mesh
#   6. Enables fleet-agent + fleet-heartbeat.timer
#   7. Disables itself so it never runs again
#   8. Removes the provision token from disk immediately
# ─────────────────────────────────────────────────────────────────────────────

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source-path=SCRIPTDIR
# shellcheck source=identity-lib.sh
. "${SCRIPT_DIR}/identity-lib.sh"

# The FLEET_* overrides below relocate files so the bats suite can run this
# script unprivileged.
#
# Scope, stated plainly: none of them selects a format, a route or a variant —
# there is one identity format and one provisioning path. What they do select
# is WHERE this root-scoped script reads secrets from and writes them to. On a
# device those paths are fixed by the systemd units, so setting them already
# requires root; the hooks widen no boundary. Said here so the next reader
# weighs them as root-scoped relocations, not as harmless path tweaks.
TOKEN_FILE="${FLEET_PROVISION_TOKEN_FILE:-/boot/firmware/fleet-provision.json}"
IDENTITY_FILE="${FLEET_IDENTITY_FILE:-/etc/fleet/device-identity.conf}"
IDENTITY_DIR="$(dirname "${IDENTITY_FILE}")"
APT_AUTH_DIR="${FLEET_APT_AUTH_DIR:-/etc/apt/auth.conf.d}"

log() { echo "[firstboot] $*"; }
fail() { echo "[firstboot] FATAL: $*" >&2; exit 1; }

if [ ! -f "${TOKEN_FILE}" ]; then
  log "No provisioning token at ${TOKEN_FILE} — skipping first-boot enrollment."
  log "Manual enrollment required or device was already provisioned."
  systemctl disable fleet-firstboot.service 2>/dev/null || true
  exit 0
fi

# ── Parse provision token ─────────────────────────────────────────────────────
command -v jq >/dev/null 2>&1 || fail "jq is required but not installed"

DEVICE_ID=$(jq -r '.device_id'       "${TOKEN_FILE}")
TOKEN=$(jq -r     '.provision_token' "${TOKEN_FILE}")
API_URL=$(jq -r   '.api_url'         "${TOKEN_FILE}")
HS_URL=$(jq -r    '.headscale_url'   "${TOKEN_FILE}")

[ -n "${DEVICE_ID}" ] || fail "device_id is empty in ${TOKEN_FILE}"
[ -n "${TOKEN}" ]     || fail "provision_token is empty in ${TOKEN_FILE}"
[ -n "${API_URL}" ]   || fail "api_url is empty in ${TOKEN_FILE}"

log "Provisioning device: ${DEVICE_ID}"

# ── Register with Fleet API → receive device-identity.conf ───────────────────
# The path carries the device id: it must match the route declared by
# FleetBits-api/app/routers/devices.py — POST /devices/{device_id}/provision.
mkdir -p "${IDENTITY_DIR}"
chmod 700 "${IDENTITY_DIR}" 2>/dev/null || true

IDENTITY_TMP="${IDENTITY_FILE}.incoming"
rm -f "${IDENTITY_TMP}"
(umask 077 && : > "${IDENTITY_TMP}")

HTTP_STATUS=$(curl -sf \
  --max-time 30 \
  --retry 5 \
  --retry-delay 3 \
  -w "%{http_code}" \
  -X POST "${API_URL}/api/v1/devices/${DEVICE_ID}/provision" \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Accept: text/plain" \
  -o "${IDENTITY_TMP}") \
  || { rm -f "${IDENTITY_TMP}"; fail "Fleet API provisioning request failed"; }

if [ "${HTTP_STATUS}" != "200" ]; then
  rm -f "${IDENTITY_TMP}"
  fail "Fleet API returned HTTP ${HTTP_STATUS} — check provision_token validity"
fi

# Validate BEFORE installing: never put a file on disk that the agent's own
# parser would reject, and never evaluate what the server sent.
if ! fleet_identity_parse "${IDENTITY_TMP}"; then
  rm -f "${IDENTITY_TMP}"
  fail "Fleet API returned an identity file that violates the device identity contract"
fi

mv "${IDENTITY_TMP}" "${IDENTITY_FILE}"
chmod 600 "${IDENTITY_FILE}"
log "device-identity.conf deployed (HTTP ${HTTP_STATUS})"

# Re-read the installed file so every value below comes from the file on disk.
fleet_identity_parse "${IDENTITY_FILE}" || fail "installed ${IDENTITY_FILE} is not parseable"

# ── Generate collector config ─────────────────────────────────────────────────
"${SCRIPT_DIR}/generate-config.sh"
log "Telemetry collector config generated"

# ── Enroll in Headscale mesh ──────────────────────────────────────────────────
# HEADSCALE_PREAUTH_KEY is a declared contract key that is allowed to be empty;
# an empty value simply means "skip mesh enrollment".
if [ -n "${HS_URL}" ] && command -v tailscale >/dev/null 2>&1; then
  if [ -n "${FLEET_ID_HEADSCALE_PREAUTH_KEY}" ]; then
    log "Enrolling in Headscale at ${HS_URL}"
    tailscale up \
      --login-server "${HS_URL}" \
      --authkey "${FLEET_ID_HEADSCALE_PREAUTH_KEY}" \
      --hostname "${FLEET_ID_DEVICE_ID}" \
      --accept-routes
    log "Headscale enrollment complete"
  else
    log "No HEADSCALE_PREAUTH_KEY in identity — skipping Headscale enrollment. Run manually."
  fi
else
  log "tailscale not found or headscale_url empty — skipping Headscale enrollment"
fi

# ── Enable fleet services ─────────────────────────────────────────────────────
systemctl enable --now fleet-agent fleet-heartbeat.timer
log "fleet-agent and heartbeat timer started"

# ── Generate and register repository authorization key ───────────────────────
REPO_KEY_PATH="${IDENTITY_DIR}/repo-access.ed25519"
REPO_PUB_PATH="${REPO_KEY_PATH}.pub"

if ! command -v ssh-keygen >/dev/null 2>&1; then
  fail "ssh-keygen is required to create the repository authorization key"
fi

if [ -f "${REPO_KEY_PATH}" ] && [ ! -f "${REPO_PUB_PATH}" ]; then
  log "Private key exists but public key missing — regenerating public key"
  ssh-keygen -y -f "${REPO_KEY_PATH}" > "${REPO_PUB_PATH}" \
    || fail "Failed to regenerate repository public key"
elif [ ! -f "${REPO_KEY_PATH}" ] && [ -f "${REPO_PUB_PATH}" ]; then
  fail "Repository public key exists without private key; remove both files or reprovision"
elif [ ! -f "${REPO_KEY_PATH}" ] && [ ! -f "${REPO_PUB_PATH}" ]; then
  log "Generating repository authorization keypair"
  ssh-keygen -q -t ed25519 -N "" -C "fleet-repo:${FLEET_ID_DEVICE_ID}" -f "${REPO_KEY_PATH}" \
    || fail "Failed to generate repository authorization keypair"
fi

chmod 600 "${REPO_KEY_PATH}"
chmod 644 "${REPO_PUB_PATH}"

fleet_identity_require FLEET_AGENT_TOKEN \
  || fail "FLEET_AGENT_TOKEN is empty in ${IDENTITY_FILE}; cannot register repository key"

PUBKEY=$(cat "${REPO_PUB_PATH}")
FINGERPRINT=$(ssh-keygen -lf "${REPO_PUB_PATH}" | awk '{print $2}')
KEY_PAYLOAD=$(jq -n --arg public_key "${PUBKEY}" --arg key_fingerprint "${FINGERPRINT}" \
  '{public_key: $public_key, key_fingerprint: $key_fingerprint}')

KEY_STATUS=$(curl -sS \
  --max-time 20 \
  --retry 3 \
  --retry-delay 2 \
  -w "%{http_code}" \
  -X POST "${API_URL}/api/v1/devices/${FLEET_ID_DEVICE_ID}/repo-key/self" \
  -H "Authorization: Bearer ${FLEET_ID_FLEET_AGENT_TOKEN}" \
  -H "Content-Type: application/json" \
  -d "${KEY_PAYLOAD}" \
  -o /dev/null) \
  || fail "Repository key registration request failed"

if [ "${KEY_STATUS}" != "200" ]; then
  fail "Repository key registration failed with HTTP ${KEY_STATUS}"
fi

log "Repository authorization key registered"

# ── Configure APT credentials for authenticated Fleet repo access ───────────
API_HOST=$(printf '%s' "${API_URL}" | sed -E 's#^https?://([^/]+).*$#\1#')
if [[ "${API_HOST}" == api.* ]]; then
  REPO_HOST="repo.${API_HOST#api.}"
  AUTH_FILE="${APT_AUTH_DIR}/fleetbits-repo.conf"

  mkdir -p "${APT_AUTH_DIR}"
  fleet_identity_require REPO_BASIC_TOKEN \
    || fail "REPO_BASIC_TOKEN is empty in ${IDENTITY_FILE}; cannot configure APT repo auth"

  (umask 077 && cat > "${AUTH_FILE}" <<EOF
machine ${REPO_HOST}
login ${FLEET_ID_DEVICE_ID}
password ${FLEET_ID_REPO_BASIC_TOKEN}
EOF
  )
  chmod 600 "${AUTH_FILE}"
  log "APT repo auth configured for ${REPO_HOST}"
else
  log "Could not infer repo host from api_url (${API_URL}) — skipping APT auth config"
fi

# ── Token is single-use: remove from disk immediately ────────────────────────
rm -f "${TOKEN_FILE}"
log "Provision token removed from disk"

# ── Self-disable so this never runs again ────────────────────────────────────
systemctl disable fleet-firstboot.service
log "First-boot complete. Provisioning service disabled."
