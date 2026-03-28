#!/bin/bash
# /usr/lib/fleet-agent/generate-config.sh
# ─────────────────────────────────────────────────────────────────────────────
# Reads /etc/fleet/device-identity.conf and generates /etc/alloy/config.alloy.
# Called by:
#   - fleet-agent.service (ExecStartPre=) on every service start
#   - Debian postinst script on package install/upgrade
#   - Ansible fleet_agent role when identity.conf changes
#
# The generated config.alloy is the ONLY file Alloy reads at runtime.
# All PLACEHOLDER values are resolved here via sed substitution.
# ─────────────────────────────────────────────────────────────────────────────

set -euo pipefail

IDENTITY_FILE="/etc/fleet/device-identity.conf"
TEMPLATE_FILE="/usr/lib/fleet-agent/config.alloy.tmpl"
OUTPUT_FILE="/etc/alloy/config.alloy"

if [ ! -f "${IDENTITY_FILE}" ]; then
  echo "ERROR: ${IDENTITY_FILE} not found. Deploy it via Ansible before starting fleet-agent." >&2
  exit 1
fi

# shellcheck source=/dev/null
source "${IDENTITY_FILE}"

# Validate required fields
for var in SITE_ID ZONE_ID DEVICE_ID DEVICE_ROLE FLEET_METRICS_URL FLEET_LOGS_URL FLEET_AGENT_TOKEN; do
  if [ -z "${!var:-}" ]; then
    echo "ERROR: Required variable ${var} is not set in ${IDENTITY_FILE}" >&2
    exit 1
  fi
done

# Ensure output directory exists
mkdir -p "$(dirname "${OUTPUT_FILE}")"

# Start from the template
cp "${TEMPLATE_FILE}" "${OUTPUT_FILE}.tmp"

# ── Substitute PLACEHOLDER values ────────────────────────────────────────────
sed -i \
  -e "s|SITE_ID_PLACEHOLDER|${SITE_ID}|g" \
  -e "s|ZONE_ID_PLACEHOLDER|${ZONE_ID}|g" \
  -e "s|DEVICE_ID_PLACEHOLDER|${DEVICE_ID}|g" \
  -e "s|DEVICE_ROLE_PLACEHOLDER|${DEVICE_ROLE}|g" \
  -e "s|PROFILE_PLACEHOLDER|${PROFILE:-}|g" \
  -e "s|FLEET_METRICS_URL_PLACEHOLDER|${FLEET_METRICS_URL}|g" \
  -e "s|FLEET_LOGS_URL_PLACEHOLDER|${FLEET_LOGS_URL}|g" \
  -e "s|FLEET_AGENT_TOKEN_PLACEHOLDER|${FLEET_AGENT_TOKEN}|g" \
  -e "s|SCRAPE_INTERVAL_PLACEHOLDER|${SCRAPE_INTERVAL:-30s}|g" \
  "${OUTPUT_FILE}.tmp"

# ── Optional components: MQTT exporter ───────────────────────────────────────
if [ "${ENABLE_MQTT_EXPORTER:-false}" = "true" ]; then
  sed -i \
    -e "s|MQTT_BROKER_HOST_PLACEHOLDER|${MQTT_BROKER_HOST:-localhost}|g" \
    -e "s|MQTT_BROKER_PORT_PLACEHOLDER|${MQTT_BROKER_PORT:-1883}|g" \
    -e "s|MQTT_USERNAME_PLACEHOLDER|${MQTT_USERNAME:-}|g" \
    -e "s|MQTT_PASSWORD_PLACEHOLDER|${MQTT_PASSWORD:-}|g" \
    "${OUTPUT_FILE}.tmp"
else
  # Strip the mqtt_exporter block from the config
  sed -i '/BEGIN MQTT_EXPORTER/,/END MQTT_EXPORTER/d' "${OUTPUT_FILE}.tmp"
fi

# ── Optional components: process exporter ────────────────────────────────────
if [ "${ENABLE_PROCESS_EXPORTER:-false}" != "true" ]; then
  sed -i '/BEGIN PROCESS_EXPORTER/,/END PROCESS_EXPORTER/d' "${OUTPUT_FILE}.tmp"
fi

# Atomically replace the output file
mv "${OUTPUT_FILE}.tmp" "${OUTPUT_FILE}"
chmod 600 "${OUTPUT_FILE}"

echo "Generated ${OUTPUT_FILE} for device ${DEVICE_ID} (site=${SITE_ID} zone=${ZONE_ID})"
