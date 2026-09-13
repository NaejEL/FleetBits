#!/bin/bash
# /usr/lib/fleet-agent/heartbeat.sh
# ─────────────────────────────────────────────────────────────────────────────
# POSTs a heartbeat to the Fleet API every time it is called.
# Invoked by fleet-heartbeat.timer (every 30 seconds).
#
# Heartbeat payload:
#   POST /api/v1/devices/{device_id}/heartbeat
#   Authorization: Bearer <FLEET_AGENT_TOKEN>
#   Body: { "status": "online", "uptime_seconds": N, "alloy_running": true/false }
#
# The Fleet API uses these heartbeats to track device online/offline state.
# If no heartbeat is received for >90s the device transitions to "offline"
# and a Prometheus absent() alert fires.
# ─────────────────────────────────────────────────────────────────────────────

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source-path=SCRIPTDIR
# shellcheck source=identity-lib.sh
. "${SCRIPT_DIR}/identity-lib.sh"

# FLEET_IDENTITY_FILE relocates the file so the bats suite can run this script
# on a fixture.
#
# Scope, stated plainly: none of them selects a format, a route or a variant —
# there is one identity format and one provisioning path. What they do select
# is WHERE this root-scoped script reads secrets from and writes them to. On a
# device those paths are fixed by the systemd units, so setting them already
# requires root; the hooks widen no boundary. Said here so the next reader
# weighs them as root-scoped relocations, not as harmless path tweaks.
IDENTITY_FILE="${FLEET_IDENTITY_FILE:-/etc/fleet/device-identity.conf}"

# Parsed, never evaluated: the file is data (see identity-lib.sh).
fleet_identity_parse "${IDENTITY_FILE}" || exit 1
fleet_identity_require FLEET_API_URL FLEET_AGENT_TOKEN DEVICE_ID || exit 1

# Collect system state
UPTIME_SECONDS=$(awk '{print int($1)}' /proc/uptime)
if systemctl is-active --quiet fleet-agent 2>/dev/null; then
  ALLOY_RUNNING="true"
else
  ALLOY_RUNNING="false"
fi

PAYLOAD=$(printf '{"status":"online","uptime_seconds":%d,"alloy_running":%s}' \
  "${UPTIME_SECONDS}" "${ALLOY_RUNNING}")

# POST with a 5s timeout — fail silently if control plane is unreachable.
# The WAL will buffer telemetry; the heartbeat absence will fire the alert.
HTTP_STATUS=$(curl -sf \
  --max-time 5 \
  --retry 2 \
  --retry-delay 1 \
  -o /dev/null \
  -w "%{http_code}" \
  -X POST "${FLEET_ID_FLEET_API_URL}/api/v1/devices/${FLEET_ID_DEVICE_ID}/heartbeat" \
  -H "Authorization: Bearer ${FLEET_ID_FLEET_AGENT_TOKEN}" \
  -H "Content-Type: application/json" \
  -d "${PAYLOAD}" 2>/dev/null) || true

if [ "${HTTP_STATUS}" != "200" ] && [ "${HTTP_STATUS}" != "204" ]; then
  # Log but do not fail — the timer will retry in 30s
  echo "WARNING: Fleet API heartbeat returned HTTP ${HTTP_STATUS:-unreachable}" >&2
fi
