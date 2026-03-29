#!/bin/bash
# /usr/lib/fleet-agent/generate-config.sh
# ─────────────────────────────────────────────────────────────────────────────
# Reads /etc/fleet/device-identity.conf and generates the runtime config for the
# telemetry collector bundled in this package:
#   - /etc/alloy/config.alloy  when /usr/bin/alloy is installed
#   - /etc/vector/vector.yaml  when /usr/bin/vector is installed
#
# Called by:
#   - fleet-agent.service (ExecStartPre=) on every service start
#   - Debian postinst script on package install/upgrade
#   - Ansible fleet_agent role when identity.conf changes
# ─────────────────────────────────────────────────────────────────────────────

set -euo pipefail

IDENTITY_FILE="/etc/fleet/device-identity.conf"
ALLOY_TEMPLATE_FILE="/usr/lib/fleet-agent/config.alloy.tmpl"
VECTOR_TEMPLATE_FILE="/usr/lib/fleet-agent/config.vector.yaml.tmpl"

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

detect_runtime() {
  if [ -x /usr/bin/alloy ]; then
    echo "alloy"
    return 0
  fi

  if [ -x /usr/bin/vector ]; then
    echo "vector"
    return 0
  fi

  echo "ERROR: no supported telemetry runtime found (/usr/bin/alloy or /usr/bin/vector)" >&2
  exit 1
}

render_alloy_config() {
  local output_file="/etc/alloy/config.alloy"

  mkdir -p /etc/alloy
  cp "${ALLOY_TEMPLATE_FILE}" "${output_file}.tmp"

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
    "${output_file}.tmp"

  if [ "${ENABLE_MQTT_EXPORTER:-false}" = "true" ]; then
    MQTT_USERNAME_ESC=$(printf '%s' "${MQTT_USERNAME:-}" | sed -e 's/[|&\\]/\\&/g')
    MQTT_PASSWORD_ESC=$(printf '%s' "${MQTT_PASSWORD:-}" | sed -e 's/[|&\\]/\\&/g')
    sed -i \
      -e "s|MQTT_BROKER_HOST_PLACEHOLDER|${MQTT_BROKER_HOST:-localhost}|g" \
      -e "s|MQTT_BROKER_PORT_PLACEHOLDER|${MQTT_BROKER_PORT:-1883}|g" \
      -e "s|MQTT_USERNAME_PLACEHOLDER|${MQTT_USERNAME_ESC}|g" \
      -e "s|MQTT_PASSWORD_PLACEHOLDER|${MQTT_PASSWORD_ESC}|g" \
      "${output_file}.tmp"
  else
    sed -i '/BEGIN MQTT_EXPORTER/,/END MQTT_EXPORTER/d' "${output_file}.tmp"
  fi

  if [ "${ENABLE_PROCESS_EXPORTER:-false}" != "true" ]; then
    sed -i '/BEGIN PROCESS_EXPORTER/,/END PROCESS_EXPORTER/d' "${output_file}.tmp"
  fi

  mv "${output_file}.tmp" "${output_file}"
  chmod 600 "${output_file}"

  echo "Generated ${output_file} for device ${DEVICE_ID} (site=${SITE_ID} zone=${ZONE_ID})"
}

render_vector_config() {
  local output_file="/etc/vector/vector.yaml"
  local scrape_interval="${SCRAPE_INTERVAL:-30s}"
  local scrape_interval_seconds
  local vector_loki_endpoint
  local vector_loki_path

  if [[ "${scrape_interval}" =~ ^([0-9]+)s$ ]]; then
    scrape_interval_seconds="${BASH_REMATCH[1]}"
  else
    echo "ERROR: SCRAPE_INTERVAL must be expressed in whole seconds for Vector runtime (example: 30s)" >&2
    exit 1
  fi

  if [[ "${FLEET_LOGS_URL}" =~ ^(https?://[^/]+)(/.*)?$ ]]; then
    vector_loki_endpoint="${BASH_REMATCH[1]}"
    vector_loki_path="${BASH_REMATCH[2]:-/loki/api/v1/push}"
  else
    echo "ERROR: FLEET_LOGS_URL must be an absolute URL (example: https://logs.fleet.example.com/loki/api/v1/push)" >&2
    exit 1
  fi

  mkdir -p /etc/vector /var/lib/fleet-agent/vector
  cp "${VECTOR_TEMPLATE_FILE}" "${output_file}.tmp"

  sed -i \
    -e "s|SITE_ID_PLACEHOLDER|${SITE_ID}|g" \
    -e "s|ZONE_ID_PLACEHOLDER|${ZONE_ID}|g" \
    -e "s|DEVICE_ID_PLACEHOLDER|${DEVICE_ID}|g" \
    -e "s|DEVICE_ROLE_PLACEHOLDER|${DEVICE_ROLE}|g" \
    -e "s|PROFILE_PLACEHOLDER|${PROFILE:-}|g" \
    -e "s|FLEET_METRICS_URL_PLACEHOLDER|${FLEET_METRICS_URL}|g" \
    -e "s|FLEET_LOGS_ENDPOINT_PLACEHOLDER|${vector_loki_endpoint}|g" \
    -e "s|FLEET_LOGS_PATH_PLACEHOLDER|${vector_loki_path}|g" \
    -e "s|FLEET_AGENT_TOKEN_PLACEHOLDER|${FLEET_AGENT_TOKEN}|g" \
    -e "s|SCRAPE_INTERVAL_SECONDS_PLACEHOLDER|${scrape_interval_seconds}|g" \
    "${output_file}.tmp"

  mv "${output_file}.tmp" "${output_file}"
  chmod 600 "${output_file}"

  echo "Generated ${output_file} for device ${DEVICE_ID} (site=${SITE_ID} zone=${ZONE_ID})"
}

RUNTIME="$(detect_runtime)"
case "${RUNTIME}" in
  alloy)
    render_alloy_config
    ;;
  vector)
    render_vector_config
    ;;
  *)
    echo "ERROR: unsupported telemetry runtime ${RUNTIME}" >&2
    exit 1
    ;;
esac
