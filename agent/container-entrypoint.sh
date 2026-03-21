#!/bin/bash
# container-entrypoint.sh
# ─────────────────────────────────────────────────────────────────────────────
# Runs fleet-agent inside Docker (no systemd).
# All configuration is passed via environment variables from docker-compose.
#
# Required env vars:
#   DEVICE_ID, SITE_ID, ZONE_ID, DEVICE_ROLE
#   FLEET_API_URL, FLEET_AGENT_TOKEN
#   FLEET_METRICS_URL, FLEET_LOGS_URL
#
# Optional:
#   PROFILE, ENVIRONMENT, RING, SCRAPE_INTERVAL (default: 30s)
# ─────────────────────────────────────────────────────────────────────────────

set -euo pipefail

: "${DEVICE_ID:?DEVICE_ID must be set}"
: "${SITE_ID:?SITE_ID must be set}"
: "${ZONE_ID:?ZONE_ID must be set}"
: "${DEVICE_ROLE:?DEVICE_ROLE must be set}"
: "${FLEET_API_URL:?FLEET_API_URL must be set}"
: "${FLEET_AGENT_TOKEN:?FLEET_AGENT_TOKEN must be set}"
: "${FLEET_METRICS_URL:?FLEET_METRICS_URL must be set}"
: "${FLEET_LOGS_URL:?FLEET_LOGS_URL must be set}"

IDENTITY="/etc/fleet/device-identity.conf"
ALLOY_CFG="/etc/alloy/config.alloy"
TEMPLATE="/usr/lib/fleet-agent/config.alloy.container.tmpl"

mkdir -p /etc/fleet /etc/alloy /var/lib/alloy

# ── Write identity file ───────────────────────────────────────────────────────
cat > "${IDENTITY}" <<EOF
SITE_ID=${SITE_ID}
ZONE_ID=${ZONE_ID}
DEVICE_ID=${DEVICE_ID}
DEVICE_ROLE=${DEVICE_ROLE}
PROFILE=${PROFILE:-}
ENVIRONMENT=${ENVIRONMENT:-development}
RING=${RING:-0}
FLEET_METRICS_URL=${FLEET_METRICS_URL}
FLEET_LOGS_URL=${FLEET_LOGS_URL}
FLEET_API_URL=${FLEET_API_URL}
FLEET_AGENT_TOKEN=${FLEET_AGENT_TOKEN}
SCRAPE_INTERVAL=${SCRAPE_INTERVAL:-30s}
ENABLE_MQTT_EXPORTER=false
ENABLE_PROCESS_EXPORTER=false
EOF

# ── Generate Alloy config from container template ─────────────────────────────
INTERVAL="${SCRAPE_INTERVAL:-30s}"
sed \
  -e "s|SITE_ID_PLACEHOLDER|${SITE_ID}|g" \
  -e "s|ZONE_ID_PLACEHOLDER|${ZONE_ID}|g" \
  -e "s|DEVICE_ID_PLACEHOLDER|${DEVICE_ID}|g" \
  -e "s|DEVICE_ROLE_PLACEHOLDER|${DEVICE_ROLE}|g" \
  -e "s|PROFILE_PLACEHOLDER|${PROFILE:-}|g" \
  -e "s|FLEET_METRICS_URL_PLACEHOLDER|${FLEET_METRICS_URL}|g" \
  -e "s|FLEET_LOGS_URL_PLACEHOLDER|${FLEET_LOGS_URL}|g" \
  -e "s|FLEET_AGENT_TOKEN_PLACEHOLDER|${FLEET_AGENT_TOKEN}|g" \
  -e "s|SCRAPE_INTERVAL_PLACEHOLDER|${INTERVAL}|g" \
  "${TEMPLATE}" > "${ALLOY_CFG}"

echo "[fleet-agent] Generated ${ALLOY_CFG} for device ${DEVICE_ID}"

# ── Start Alloy in background ─────────────────────────────────────────────────
alloy run "${ALLOY_CFG}" \
  --disable-reporting \
  --storage.path=/var/lib/alloy \
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
    alloy run "${ALLOY_CFG}" --disable-reporting --storage.path=/var/lib/alloy &
    ALLOY_PID=$!
  fi

  PAYLOAD=$(printf '{"status":"online","uptime_seconds":%d,"alloy_running":%s}' \
    "${UPTIME_SECONDS}" "${ALLOY_RUNNING}")

  HTTP_STATUS=$(curl -sf \
    --max-time 5 --retry 2 --retry-delay 1 \
    -o /dev/null -w "%{http_code}" \
    -X POST "${FLEET_API_URL}/api/v1/devices/${DEVICE_ID}/heartbeat" \
    -H "Authorization: Bearer ${FLEET_AGENT_TOKEN}" \
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
