#!/bin/bash
# /usr/lib/fleet-agent/generate-config.sh
# ─────────────────────────────────────────────────────────────────────────────
# Reads /etc/fleet/device-identity.conf and generates the runtime config for the
# telemetry collector bundled in this package:
#   - /etc/alloy/config.alloy  when /usr/bin/alloy is installed
#   - /etc/vector/vector.yaml  when /usr/bin/vector is installed
#
# The identity file is PARSED as data by identity-lib.sh — never sourced, never
# evaluated by the shell. Templates are filled by fleet_render_template, a
# single-pass renderer: a substituted value is never rescanned, so it can never
# be taken for the name of another placeholder (see identity-lib.sh).
#
# Called by:
#   - fleet-agent.service (ExecStartPre=) on every service start
#   - Debian postinst script on package install/upgrade
#   - Ansible fleet_agent role when identity.conf changes
# ─────────────────────────────────────────────────────────────────────────────

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source-path=SCRIPTDIR
# shellcheck source=identity-lib.sh
. "${SCRIPT_DIR}/identity-lib.sh"

# The FLEET_* overrides below relocate inputs and outputs so the bats suite can
# run this script unprivileged.
#
# Scope, stated plainly: none of them selects a format, a route or a variant —
# there is one identity format and one provisioning path. What they do select
# is WHERE this root-scoped script reads secrets from and writes them to. On a
# device those paths are fixed by the systemd units, so setting them already
# requires root; the hooks widen no boundary. Said here so the next reader
# weighs them as root-scoped relocations, not as harmless path tweaks.
IDENTITY_FILE="${FLEET_IDENTITY_FILE:-/etc/fleet/device-identity.conf}"
ALLOY_TEMPLATE_FILE="${SCRIPT_DIR}/config.alloy.tmpl"
VECTOR_TEMPLATE_FILE="${SCRIPT_DIR}/config.vector.yaml.tmpl"
ALLOY_BIN="${FLEET_ALLOY_BIN:-/usr/bin/alloy}"
VECTOR_BIN="${FLEET_VECTOR_BIN:-/usr/bin/vector}"
ALLOY_CONFIG_FILE="${FLEET_ALLOY_CONFIG:-/etc/alloy/config.alloy}"
VECTOR_CONFIG_FILE="${FLEET_VECTOR_CONFIG:-/etc/vector/vector.yaml}"
VECTOR_DATA_DIR="${FLEET_VECTOR_DATA_DIR:-/var/lib/fleet-agent/vector}"

fleet_identity_parse "${IDENTITY_FILE}" || exit 1

# Fields without which no collector config can be produced at all.
fleet_identity_require \
  SITE_ID ZONE_ID DEVICE_ID DEVICE_ROLE ENVIRONMENT RING \
  FLEET_METRICS_URL FLEET_LOGS_URL FLEET_AGENT_TOKEN || exit 1

detect_runtime() {
  if [ -x "${ALLOY_BIN}" ]; then
    echo "alloy"
    return 0
  fi

  if [ -x "${VECTOR_BIN}" ]; then
    echo "vector"
    return 0
  fi

  echo "ERROR: no supported telemetry runtime found (${ALLOY_BIN} or ${VECTOR_BIN})" >&2
  exit 1
}

render_alloy_config() {
  local output_file="${ALLOY_CONFIG_FILE}"
  local -a mapping

  mkdir -p "$(dirname "${output_file}")"

  # Optional blocks are removed FIRST, on the template text alone: their
  # placeholders must disappear with them, because the renderer below fails
  # closed on any placeholder it holds no value for.
  cp "${ALLOY_TEMPLATE_FILE}" "${output_file}.tmp"
  if [ "${FLEET_ID_ENABLE_MQTT_EXPORTER}" != "true" ]; then
    sed -i '/BEGIN MQTT_EXPORTER/,/END MQTT_EXPORTER/d' "${output_file}.tmp"
  fi
  if [ "${FLEET_ID_ENABLE_PROCESS_EXPORTER}" != "true" ]; then
    sed -i '/BEGIN PROCESS_EXPORTER/,/END PROCESS_EXPORTER/d' "${output_file}.tmp"
  fi

  mapping=(
    "SITE_ID_PLACEHOLDER=${FLEET_ID_SITE_ID}"
    "ZONE_ID_PLACEHOLDER=${FLEET_ID_ZONE_ID}"
    "DEVICE_ID_PLACEHOLDER=${FLEET_ID_DEVICE_ID}"
    "DEVICE_ROLE_PLACEHOLDER=${FLEET_ID_DEVICE_ROLE}"
    "PROFILE_PLACEHOLDER=${FLEET_ID_PROFILE}"
    "ENVIRONMENT_PLACEHOLDER=${FLEET_ID_ENVIRONMENT}"
    "RING_PLACEHOLDER=${FLEET_ID_RING}"
    "FLEET_METRICS_URL_PLACEHOLDER=${FLEET_ID_FLEET_METRICS_URL}"
    "FLEET_LOGS_URL_PLACEHOLDER=${FLEET_ID_FLEET_LOGS_URL}"
    "FLEET_AGENT_TOKEN_PLACEHOLDER=${FLEET_ID_FLEET_AGENT_TOKEN}"
    "SCRAPE_INTERVAL_PLACEHOLDER=${FLEET_ID_SCRAPE_INTERVAL}"
  )

  if [ "${FLEET_ID_ENABLE_MQTT_EXPORTER}" = "true" ]; then
    fleet_identity_require MQTT_BROKER_HOST MQTT_BROKER_PORT MQTT_USERNAME MQTT_PASSWORD || {
      rm -f "${output_file}.tmp"
      echo "ERROR: ENABLE_MQTT_EXPORTER=true requires the MQTT credentials of the contract" >&2
      exit 1
    }
    mapping+=(
      "MQTT_BROKER_HOST_PLACEHOLDER=${FLEET_ID_MQTT_BROKER_HOST}"
      "MQTT_BROKER_PORT_PLACEHOLDER=${FLEET_ID_MQTT_BROKER_PORT}"
      "MQTT_USERNAME_PLACEHOLDER=${FLEET_ID_MQTT_USERNAME}"
      "MQTT_PASSWORD_PLACEHOLDER=${FLEET_ID_MQTT_PASSWORD}"
    )
  fi

  if ! (umask 077 && fleet_render_template \
    "${output_file}.tmp" "${output_file}.rendered" "${mapping[@]}"); then
    rm -f "${output_file}.tmp" "${output_file}.rendered"
    echo "ERROR: failed to render ${output_file}" >&2
    exit 1
  fi
  rm -f "${output_file}.tmp"

  mv "${output_file}.rendered" "${output_file}"
  chmod 600 "${output_file}"

  echo "Generated ${output_file} for device ${FLEET_ID_DEVICE_ID} (site=${FLEET_ID_SITE_ID} zone=${FLEET_ID_ZONE_ID})"
}

render_vector_config() {
  local output_file="${VECTOR_CONFIG_FILE}"
  local scrape_interval="${FLEET_ID_SCRAPE_INTERVAL}"
  local scrape_interval_seconds
  local vector_loki_endpoint
  local vector_loki_path

  if [[ "${scrape_interval}" =~ ^([0-9]+)s$ ]]; then
    scrape_interval_seconds="${BASH_REMATCH[1]}"
  else
    echo "ERROR: SCRAPE_INTERVAL must be expressed in whole seconds for Vector runtime (example: 30s)" >&2
    exit 1
  fi

  if [[ "${FLEET_ID_FLEET_LOGS_URL}" =~ ^(https?://[^/]+)(/.*)?$ ]]; then
    vector_loki_endpoint="${BASH_REMATCH[1]}"
    vector_loki_path="${BASH_REMATCH[2]:-/loki/api/v1/push}"
  else
    echo "ERROR: FLEET_LOGS_URL must be an absolute URL (example: https://logs.fleet.example.com/loki/api/v1/push)" >&2
    exit 1
  fi

  mkdir -p "$(dirname "${output_file}")" "${VECTOR_DATA_DIR}"

  if ! (umask 077 && fleet_render_template \
    "${VECTOR_TEMPLATE_FILE}" "${output_file}.tmp" \
    "SITE_ID_PLACEHOLDER=${FLEET_ID_SITE_ID}" \
    "ZONE_ID_PLACEHOLDER=${FLEET_ID_ZONE_ID}" \
    "DEVICE_ID_PLACEHOLDER=${FLEET_ID_DEVICE_ID}" \
    "DEVICE_ROLE_PLACEHOLDER=${FLEET_ID_DEVICE_ROLE}" \
    "PROFILE_PLACEHOLDER=${FLEET_ID_PROFILE}" \
    "ENVIRONMENT_PLACEHOLDER=${FLEET_ID_ENVIRONMENT}" \
    "RING_PLACEHOLDER=${FLEET_ID_RING}" \
    "FLEET_METRICS_URL_PLACEHOLDER=${FLEET_ID_FLEET_METRICS_URL}" \
    "FLEET_LOGS_ENDPOINT_PLACEHOLDER=${vector_loki_endpoint}" \
    "FLEET_LOGS_PATH_PLACEHOLDER=${vector_loki_path}" \
    "FLEET_AGENT_TOKEN_PLACEHOLDER=${FLEET_ID_FLEET_AGENT_TOKEN}" \
    "VECTOR_DATA_DIR_PLACEHOLDER=${VECTOR_DATA_DIR}" \
    "SCRAPE_INTERVAL_SECONDS_PLACEHOLDER=${scrape_interval_seconds}"); then
    rm -f "${output_file}.tmp"
    echo "ERROR: failed to render ${output_file}" >&2
    exit 1
  fi

  mv "${output_file}.tmp" "${output_file}"
  chmod 600 "${output_file}"

  echo "Generated ${output_file} for device ${FLEET_ID_DEVICE_ID} (site=${FLEET_ID_SITE_ID} zone=${FLEET_ID_ZONE_ID})"
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
