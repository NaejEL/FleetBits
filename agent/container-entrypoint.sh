#!/bin/bash
# container-entrypoint.sh
# ─────────────────────────────────────────────────────────────────────────────
# Runs fleet-agent inside Docker (no systemd).
# All configuration is passed via environment variables from docker-compose.
#
# This is the third producer of the device identity file. It writes exactly the
# same contract as the Fleet API provisioning route and the Ansible template —
# see identity-lib.sh, whose key list is the agent-side copy of
# api/app/contracts/device_identity.py.
#
# Required env vars:
#   DEVICE_ID, SITE_ID, ZONE_ID, DEVICE_ROLE
#   FLEET_API_URL, FLEET_AGENT_TOKEN
#   FLEET_METRICS_URL, FLEET_LOGS_URL
#
# Optional (contract defaults applied when unset):
#   PROFILE, ENVIRONMENT, RING, SCRAPE_INTERVAL, REPO_BASIC_TOKEN,
#   HEADSCALE_PREAUTH_KEY, MQTT_BROKER_HOST, MQTT_BROKER_PORT,
#   MQTT_USERNAME, MQTT_PASSWORD, ENABLE_MQTT_EXPORTER, ENABLE_PROCESS_EXPORTER
#
# Usage:
#   container-entrypoint.sh                 run the agent (container default)
#   container-entrypoint.sh --render-only   write the identity file and the
#                                           Alloy config, then exit — used by
#                                           the bats suite to exercise this
#                                           producer outside a container.
# ─────────────────────────────────────────────────────────────────────────────

set -euo pipefail

# In the image the agent scripts live in /usr/lib/fleet-agent while this file is
# installed as /entrypoint.sh. FLEET_AGENT_LIB_DIR relocates the library for the
# out-of-container test run.
#
# Scope of this hook, stated plainly: it selects no format, no route and no
# behaviour — there is exactly one identity format and one provisioning path,
# and nothing here can pick another. What it DOES do is redirect where this
# entry point sources its shell library from, in a process that runs as root.
# Same for FLEET_IDENTITY_FILE below, which redirects where a file of secrets
# gets written. On a device both are fixed by the systemd units and by the
# image layout, so an attacker able to set them already has root; the hook
# widens no boundary that was not already crossed. It is written down here so
# the next reader weighs it as a root-scoped relocation and not as a harmless
# path tweak.
FLEET_AGENT_LIB_DIR="${FLEET_AGENT_LIB_DIR:-/usr/lib/fleet-agent}"
# shellcheck source-path=SCRIPTDIR
# shellcheck source=usr/lib/fleet-agent/identity-lib.sh
. "${FLEET_AGENT_LIB_DIR}/identity-lib.sh"

RENDER_ONLY="false"
if [ "${1:-}" = "--render-only" ]; then
  RENDER_ONLY="true"
  shift
fi

: "${DEVICE_ID:?DEVICE_ID must be set}"
: "${SITE_ID:?SITE_ID must be set}"
: "${ZONE_ID:?ZONE_ID must be set}"
: "${DEVICE_ROLE:?DEVICE_ROLE must be set}"
: "${FLEET_API_URL:?FLEET_API_URL must be set}"
: "${FLEET_AGENT_TOKEN:?FLEET_AGENT_TOKEN must be set}"
: "${FLEET_METRICS_URL:?FLEET_METRICS_URL must be set}"
: "${FLEET_LOGS_URL:?FLEET_LOGS_URL must be set}"

IDENTITY="${FLEET_IDENTITY_FILE:-/etc/fleet/device-identity.conf}"
ALLOY_CFG="${FLEET_ALLOY_CONFIG:-/etc/alloy/config.alloy}"
ALLOY_DATA_DIR="${FLEET_ALLOY_DATA_DIR:-/var/lib/alloy}"
TEMPLATE="${FLEET_AGENT_LIB_DIR}/config.alloy.container.tmpl"

mkdir -p "$(dirname "${IDENTITY}")" "$(dirname "${ALLOY_CFG}")" "${ALLOY_DATA_DIR}"

# ── Build the identity file through the contract writer ──────────────────────
# Every value is validated against the contract before being written, so this
# producer can never emit a file the agent's own parser would reject.
fleet_identity_set DEVICE_ID               "${DEVICE_ID}"
fleet_identity_set SITE_ID                 "${SITE_ID}"
fleet_identity_set ZONE_ID                 "${ZONE_ID}"
fleet_identity_set DEVICE_ROLE             "${DEVICE_ROLE}"
fleet_identity_set PROFILE                 "${PROFILE:-}"
fleet_identity_set ENVIRONMENT             "${ENVIRONMENT:-development}"
fleet_identity_set RING                    "${RING:-0}"
fleet_identity_set FLEET_API_URL           "${FLEET_API_URL}"
fleet_identity_set FLEET_METRICS_URL       "${FLEET_METRICS_URL}"
fleet_identity_set FLEET_LOGS_URL          "${FLEET_LOGS_URL}"
fleet_identity_set FLEET_AGENT_TOKEN       "${FLEET_AGENT_TOKEN}"
fleet_identity_set REPO_BASIC_TOKEN        "${REPO_BASIC_TOKEN:-}"
fleet_identity_set HEADSCALE_PREAUTH_KEY   "${HEADSCALE_PREAUTH_KEY:-}"
fleet_identity_set MQTT_BROKER_HOST        "${MQTT_BROKER_HOST:-localhost}"
fleet_identity_set MQTT_BROKER_PORT        "${MQTT_BROKER_PORT:-1883}"
fleet_identity_set MQTT_USERNAME           "${MQTT_USERNAME:-}"
fleet_identity_set MQTT_PASSWORD           "${MQTT_PASSWORD:-}"
fleet_identity_set ENABLE_MQTT_EXPORTER    "${ENABLE_MQTT_EXPORTER:-false}"
fleet_identity_set ENABLE_PROCESS_EXPORTER "${ENABLE_PROCESS_EXPORTER:-false}"
fleet_identity_set SCRAPE_INTERVAL         "${SCRAPE_INTERVAL:-30s}"

(umask 077 && fleet_identity_render > "${IDENTITY}")
chmod 600 "${IDENTITY}"

# Read it back through the strict parser — the file on disk is the contract,
# and everything below uses the parsed values, never the raw environment.
fleet_identity_parse "${IDENTITY}"

# ── Generate Alloy config from container template ─────────────────────────────
# Single-pass rendering, same reason as generate-config.sh: a chain of sed
# expressions lets a value that happens to spell a later placeholder name be
# substituted a second time — which turned a crafted DEVICE_ROLE into the
# device bearer token, shipped as a telemetry label.
(umask 077 && fleet_render_template "${TEMPLATE}" "${ALLOY_CFG}" \
  "SITE_ID_PLACEHOLDER=${FLEET_ID_SITE_ID}" \
  "ZONE_ID_PLACEHOLDER=${FLEET_ID_ZONE_ID}" \
  "DEVICE_ID_PLACEHOLDER=${FLEET_ID_DEVICE_ID}" \
  "DEVICE_ROLE_PLACEHOLDER=${FLEET_ID_DEVICE_ROLE}" \
  "PROFILE_PLACEHOLDER=${FLEET_ID_PROFILE}" \
  "ENVIRONMENT_PLACEHOLDER=${FLEET_ID_ENVIRONMENT}" \
  "RING_PLACEHOLDER=${FLEET_ID_RING}" \
  "FLEET_METRICS_URL_PLACEHOLDER=${FLEET_ID_FLEET_METRICS_URL}" \
  "FLEET_LOGS_URL_PLACEHOLDER=${FLEET_ID_FLEET_LOGS_URL}" \
  "FLEET_AGENT_TOKEN_PLACEHOLDER=${FLEET_ID_FLEET_AGENT_TOKEN}" \
  "SCRAPE_INTERVAL_PLACEHOLDER=${FLEET_ID_SCRAPE_INTERVAL}")
chmod 600 "${ALLOY_CFG}"

echo "[fleet-agent] Generated ${ALLOY_CFG} for device ${FLEET_ID_DEVICE_ID}"

if [ "${RENDER_ONLY}" = "true" ]; then
  exit 0
fi

# ── Start Alloy in background ─────────────────────────────────────────────────
alloy run "${ALLOY_CFG}" \
  --disable-reporting \
  --storage.path="${ALLOY_DATA_DIR}" \
  &
ALLOY_PID=$!
echo "[fleet-agent] Alloy started (pid=${ALLOY_PID})"

# ── Heartbeat loop ─────────────────────────────────────────────────────────────
# Replaces the systemd timer. Runs every 30 seconds.
# Checks if alloy process is still alive instead of using systemctl.
send_heartbeat() {
  UPTIME_SECONDS=$(awk '{print int($1)}' /proc/uptime 2>/dev/null || echo 0)
  if kill -0 "${ALLOY_PID}" 2>/dev/null; then
    ALLOY_RUNNING="true"
  else
    ALLOY_RUNNING="false"
    echo "[fleet-agent] WARNING: Alloy process died — restarting"
    alloy run "${ALLOY_CFG}" --disable-reporting --storage.path="${ALLOY_DATA_DIR}" &
    ALLOY_PID=$!
  fi

  PAYLOAD=$(printf '{"status":"online","uptime_seconds":%d,"alloy_running":%s}' \
    "${UPTIME_SECONDS}" "${ALLOY_RUNNING}")

  HTTP_STATUS=$(curl -sf \
    --max-time 5 --retry 2 --retry-delay 1 \
    -o /dev/null -w "%{http_code}" \
    -X POST "${FLEET_ID_FLEET_API_URL}/api/v1/devices/${FLEET_ID_DEVICE_ID}/heartbeat" \
    -H "Authorization: Bearer ${FLEET_ID_FLEET_AGENT_TOKEN}" \
    -H "Content-Type: application/json" \
    -d "${PAYLOAD}" 2>/dev/null) || HTTP_STATUS="unreachable"

  if [ "${HTTP_STATUS}" != "204" ] && [ "${HTTP_STATUS}" != "200" ]; then
    echo "[fleet-agent] Heartbeat → HTTP ${HTTP_STATUS}"
  fi
}

# Initial heartbeat after 10 s (Alloy needs time to start)
sleep 10
send_heartbeat

while true; do
  sleep 30
  send_heartbeat
done
