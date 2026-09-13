#!/usr/bin/env bats
# Contract conformance inside FleetBits-agent — acceptance criteria 5 (agent
# side), 16, 18, 19 and 20.

setup() {
  load helpers
  fleet_test_setup
}

# ── Criterion 18 — the example file is exactly the contract ────────────────

@test "device-identity.conf.example holds exactly the contract keys" {
  fleet_contract_keys | sort > "${WORK}/contract.keys"
  fleet_keys_of_file "${REPO_ROOT}/etc/fleet/device-identity.conf.example" \
    | sort > "${WORK}/example.keys"
  run diff "${WORK}/contract.keys" "${WORK}/example.keys"
  [ "$status" -eq 0 ]
}

@test "device-identity.conf.example is accepted by the parser once filled in" {
  sed -e 's/^\(DEVICE_ID\|SITE_ID\|ZONE_ID\|DEVICE_ROLE\|FLEET_AGENT_TOKEN\)=CHANGE_ME$/\1=filled/' \
    "${REPO_ROOT}/etc/fleet/device-identity.conf.example" > "${FLEET_IDENTITY_FILE}"
  run bash -c '
    set -euo pipefail
    . "'"${IDENTITY_LIB}"'"
    fleet_identity_parse "'"${FLEET_IDENTITY_FILE}"'"
  '
  [ "$status" -eq 0 ]
}

# ── Criterion 19 — the README block lists the same keys ────────────────────

@test "the README device-identity.conf block lists the example file's keys" {
  awk '/^## device-identity.conf reference/,/^## Tests/' "${REPO_ROOT}/README.md" \
    | grep -E '^[A-Z][A-Z0-9_]*=' | sed -E 's/=.*//' | sort > "${WORK}/readme.keys"
  fleet_keys_of_file "${REPO_ROOT}/etc/fleet/device-identity.conf.example" \
    | sort > "${WORK}/example.keys"
  run diff "${WORK}/example.keys" "${WORK}/readme.keys"
  [ "$status" -eq 0 ]
}

# ── Criterion 5 (agent side) — container producer matches the whitelist ────

@test "container-entrypoint.sh sets exactly the contract keys, in order" {
  grep -E '^fleet_identity_set[[:space:]]+[A-Z_]+' "${REPO_ROOT}/container-entrypoint.sh" \
    | awk '{print $2}' > "${WORK}/container.keys"
  fleet_contract_keys > "${WORK}/contract.keys"
  run diff "${WORK}/contract.keys" "${WORK}/container.keys"
  [ "$status" -eq 0 ]
}

# ── Criterion 20 — the container entry point produces a valid identity file ─

@test "container-entrypoint.sh renders a parseable identity file" {
  export DEVICE_ID="vps-control-plane"
  export SITE_ID="control-plane"
  export ZONE_ID="vps"
  export DEVICE_ROLE="control-plane-vps"
  export FLEET_API_URL="http://fleet-api:8000"
  export FLEET_AGENT_TOKEN="vps-device-token"
  export FLEET_METRICS_URL="http://prometheus:9090/api/v1/write"
  export FLEET_LOGS_URL="http://loki:3100/loki/api/v1/push"
  export RING="0"
  export ENVIRONMENT="development"
  export SCRAPE_INTERVAL="30s"

  run "${REPO_ROOT}/container-entrypoint.sh" --render-only
  [ "$status" -eq 0 ]

  run bash -c '
    set -euo pipefail
    . "'"${IDENTITY_LIB}"'"
    fleet_identity_parse "'"${FLEET_IDENTITY_FILE}"'"
    printf "%s|%s|%s\n" "${FLEET_ID_DEVICE_ID}" "${FLEET_ID_RING}" "${FLEET_ID_ENVIRONMENT}"
  '
  [ "$status" -eq 0 ]
  [ "$output" = "vps-control-plane|0|development" ]

  run stat -c '%a' "${FLEET_IDENTITY_FILE}"
  [ "$output" = "600" ]
}

@test "container-entrypoint.sh refuses a value that breaks the contract" {
  export DEVICE_ID="vps-control-plane"
  export SITE_ID="control-plane"
  export ZONE_ID="vps"
  export DEVICE_ROLE='bad$(id)'
  export FLEET_API_URL="http://fleet-api:8000"
  export FLEET_AGENT_TOKEN="vps-device-token"
  export FLEET_METRICS_URL="http://prometheus:9090/api/v1/write"
  export FLEET_LOGS_URL="http://loki:3100/loki/api/v1/push"

  run "${REPO_ROOT}/container-entrypoint.sh" --render-only
  [ "$status" -ne 0 ]
  [[ "$output" == *"outside"* ]]
}

# ── Criterion 16 — one file mode across every producer ─────────────────────

@test "firstboot.sh and postinst.sh apply the same identity file mode" {
  run grep -cE 'chmod 600 "\$\{IDENTITY_FILE\}"' "${LIB_DIR}/firstboot.sh"
  [ "$output" = "1" ]
  run grep -cE 'chmod 600 "\$\{IDENTITY_FILE\}"' "${REPO_ROOT}/scripts/postinst.sh"
  [ "$output" = "2" ]
}
