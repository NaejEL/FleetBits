#!/usr/bin/env bash
# tests/helpers.bash — shared setup for the fleet-agent bats suite.
#
# Every test runs the real scripts, unprivileged, against a throw-away
# directory. External commands the scripts rely on (curl, jq, ssh-keygen,
# systemctl, tailscale) are replaced by the recording stubs in tests/stubs so
# no test ever touches the developer machine.

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export REPO_ROOT
export LIB_DIR="${REPO_ROOT}/usr/lib/fleet-agent"
export IDENTITY_LIB="${LIB_DIR}/identity-lib.sh"

# fleet_test_setup — per-test sandbox with stubs first on PATH.
fleet_test_setup() {
  WORK="${BATS_TEST_TMPDIR}/work"
  mkdir -p "${WORK}/etc/fleet" "${WORK}/bin"
  export WORK
  export FLEET_IDENTITY_FILE="${WORK}/etc/fleet/device-identity.conf"
  export FLEET_PROVISION_TOKEN_FILE="${WORK}/boot/fleet-provision.json"
  export FLEET_APT_AUTH_DIR="${WORK}/etc/apt/auth.conf.d"
  export FLEET_ALLOY_CONFIG="${WORK}/etc/alloy/config.alloy"
  export FLEET_VECTOR_CONFIG="${WORK}/etc/vector/vector.yaml"
  export FLEET_VECTOR_DATA_DIR="${WORK}/var/lib/fleet-agent/vector"
  export FLEET_ALLOY_DATA_DIR="${WORK}/var/lib/alloy"
  export FLEET_AGENT_LIB_DIR="${LIB_DIR}"
  # Neither collector binary exists by default; tests opt in explicitly.
  export FLEET_ALLOY_BIN="${WORK}/bin/alloy"
  export FLEET_VECTOR_BIN="${WORK}/bin/vector"
  # Recording files used by the stubs.
  export STUB_LOG="${WORK}/stub.log"
  export CANARY="${WORK}/INJECTED_COMMAND_RAN"
  : > "${STUB_LOG}"
  export PATH="${REPO_ROOT}/tests/stubs:${PATH}"
}

# fleet_install_collector alloy|vector — make the chosen runtime "installed".
fleet_install_collector() {
  local which_one="$1"
  local target="${WORK}/bin/${which_one}"
  printf '#!/bin/sh\nexit 0\n' > "${target}"
  chmod +x "${target}"
}

# fleet_valid_identity [KEY=value ...] — write a contract-complete identity file,
# overriding the given keys.
fleet_valid_identity() {
  local -A values=(
    [DEVICE_ID]=rpi-paris-pharaoh-02
    [SITE_ID]=paris
    [ZONE_ID]=pharaoh
    [DEVICE_ROLE]=rpi-video
    [PROFILE]=profile_v1
    [ENVIRONMENT]=lab
    [RING]=0
    [FLEET_API_URL]=https://api.fleet.example.com
    [FLEET_METRICS_URL]=https://metrics.fleet.example.com/api/v1/write
    [FLEET_LOGS_URL]=https://logs.fleet.example.com/loki/api/v1/push
    [FLEET_AGENT_TOKEN]=agent-token-value
    [REPO_BASIC_TOKEN]=repo-token-value
    [HEADSCALE_PREAUTH_KEY]=""
    [MQTT_BROKER_HOST]=localhost
    [MQTT_BROKER_PORT]=1883
    [MQTT_USERNAME]=device_rpi-paris-pharaoh-02
    [MQTT_PASSWORD]=mqtt-password-value
    [ENABLE_MQTT_EXPORTER]=false
    [ENABLE_PROCESS_EXPORTER]=false
    [SCRAPE_INTERVAL]=30s
  )
  local order=(
    DEVICE_ID SITE_ID ZONE_ID DEVICE_ROLE PROFILE ENVIRONMENT RING
    FLEET_API_URL FLEET_METRICS_URL FLEET_LOGS_URL
    FLEET_AGENT_TOKEN REPO_BASIC_TOKEN HEADSCALE_PREAUTH_KEY
    MQTT_BROKER_HOST MQTT_BROKER_PORT MQTT_USERNAME MQTT_PASSWORD
    ENABLE_MQTT_EXPORTER ENABLE_PROCESS_EXPORTER SCRAPE_INTERVAL
  )

  local arg key
  for arg in "$@"; do
    key="${arg%%=*}"
    values["${key}"]="${arg#*=}"
  done

  local out="${FLEET_IDENTITY_FILE}"
  mkdir -p "$(dirname "${out}")"
  : > "${out}"
  for key in "${order[@]}"; do
    printf '%s=%s\n' "${key}" "${values[${key}]}" >> "${out}"
  done
}

# fleet_contract_keys — the canonical key list, read from the parser library.
fleet_contract_keys() {
  # shellcheck source-path=SCRIPTDIR
  # shellcheck source=../usr/lib/fleet-agent/identity-lib.sh
  . "${IDENTITY_LIB}"
  printf '%s\n' "${FLEET_IDENTITY_KEYS[@]}"
}

# fleet_keys_of_file FILE — the KEY= names appearing in an identity-shaped file.
fleet_keys_of_file() {
  grep -E '^[A-Z][A-Z0-9_]*=' "$1" | sed -E 's/=.*//'
}

# fleet_write_provision_json — the /boot payload firstboot.sh consumes.
fleet_write_provision_json() {
  mkdir -p "$(dirname "${FLEET_PROVISION_TOKEN_FILE}")"
  cat > "${FLEET_PROVISION_TOKEN_FILE}" <<'JSON'
{
  "device_id": "rpi-paris-pharaoh-02",
  "provision_token": "provision-jwt-placeholder",
  "api_url": "https://api.fleet.example.com",
  "headscale_url": "https://headscale.fleet.example.com"
}
JSON
}
