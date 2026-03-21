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

IDENTITY_FILE="/etc/fleet/device-identity.conf"

if [ ! -f "${IDENTITY_FILE}" ]; then
  echo "ERROR: ${IDENTITY_FILE} not found" >&2
  exit 1
fi

# shellcheck source=/dev/null
source "${IDENTITY_FILE}"

if [ -z "${FLEET_API_URL:-}" ] || [ -z "${FLEET_AGENT_TOKEN:-}" ] || [ -z "${DEVICE_ID:-}" ]; then
  echo "ERROR: FLEET_API_URL, FLEET_AGENT_TOKEN, DEVICE_ID must be set in ${IDENTITY_FILE}" >&2
  exit 1
fi

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
  -X POST "${FLEET_API_URL}/api/v1/devices/${DEVICE_ID}/heartbeat" \
  -H "Authorization: Bearer ${FLEET_AGENT_TOKEN}" \
  -H "Content-Type: application/json" \
  -d "${PAYLOAD}" 2>/dev/null) || true

if [ "${HTTP_STATUS}" != "200" ] && [ "${HTTP_STATUS}" != "204" ]; then
  # Log but do not fail — the timer will retry in 30s
  echo "WARNING: Fleet API heartbeat returned HTTP ${HTTP_STATUS:-unreachable}" >&2
fi
