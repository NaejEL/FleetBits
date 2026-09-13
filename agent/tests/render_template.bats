#!/usr/bin/env bats
# tests/render_template.bats
# ─────────────────────────────────────────────────────────────────────────────
# The template renderer must never reinterpret a substituted value.
#
# Every contract value is a plain word drawn from FLEET_IDENTITY_VALUE_PATTERN,
# and a placeholder name is a plain word drawn from that same character set. So
# a legitimate, whitelist-passing value CAN spell the name of another
# placeholder. Under the previous `sed -e ... -e ...` cascade — whose
# expressions all apply, in order, to the same line — a device whose
# DEVICE_ROLE was the string FLEET_AGENT_TOKEN_PLACEHOLDER had its role
# expanded a second time into the device bearer token, which then left the
# device as the value of the `device_role` telemetry label, in clear text, to
# Prometheus and Loki.
#
# These tests fail if that collision ever comes back.

load helpers

setup() {
  fleet_test_setup
}

CANARY_TOKEN="sekrit-agent-token-canary"

# ── The collision itself, through each of the three renderers ────────────────

@test "generate-config/alloy never re-substitutes a value that spells a placeholder" {
  fleet_install_collector alloy
  fleet_valid_identity \
    DEVICE_ROLE=FLEET_AGENT_TOKEN_PLACEHOLDER \
    FLEET_AGENT_TOKEN="${CANARY_TOKEN}"

  run "${LIB_DIR}/generate-config.sh"
  [ "$status" -eq 0 ]

  # The role is rendered verbatim, as the literal word it is...
  run grep -F 'replacement  = "FLEET_AGENT_TOKEN_PLACEHOLDER"' "${FLEET_ALLOY_CONFIG}"
  [ "$status" -eq 0 ]
  run grep -F 'device_role = "FLEET_AGENT_TOKEN_PLACEHOLDER"' "${FLEET_ALLOY_CONFIG}"
  [ "$status" -eq 0 ]

  # ... and the bearer token appears ONLY in the two authorization slots the
  # template declares for it, never in a label.
  run grep -c -F "${CANARY_TOKEN}" "${FLEET_ALLOY_CONFIG}"
  [ "$output" = "2" ]
  run grep -n -F "${CANARY_TOKEN}" "${FLEET_ALLOY_CONFIG}"
  [[ "$output" != *"target_label"* ]]
  [[ "$output" != *"device_role"* ]]
}

@test "generate-config/vector never re-substitutes a value that spells a placeholder" {
  fleet_install_collector vector
  fleet_valid_identity \
    DEVICE_ROLE=FLEET_AGENT_TOKEN_PLACEHOLDER \
    FLEET_AGENT_TOKEN="${CANARY_TOKEN}"

  run "${LIB_DIR}/generate-config.sh"
  [ "$status" -eq 0 ]

  run grep -F '.tags.device_role = "FLEET_AGENT_TOKEN_PLACEHOLDER"' "${FLEET_VECTOR_CONFIG}"
  [ "$status" -eq 0 ]
  run grep -c -F "${CANARY_TOKEN}" "${FLEET_VECTOR_CONFIG}"
  [ "$output" = "2" ]
  run grep -n -F "${CANARY_TOKEN}" "${FLEET_VECTOR_CONFIG}"
  [[ "$output" != *"device_role"* ]]
}

@test "container-entrypoint never re-substitutes a value that spells a placeholder" {
  export DEVICE_ID="rpi-paris-pharaoh-02"
  export SITE_ID="paris"
  export ZONE_ID="pharaoh"
  export DEVICE_ROLE="FLEET_AGENT_TOKEN_PLACEHOLDER"
  export FLEET_API_URL="https://api.fleet.example.com"
  export FLEET_AGENT_TOKEN="${CANARY_TOKEN}"
  export FLEET_METRICS_URL="https://metrics.fleet.example.com/api/v1/write"
  export FLEET_LOGS_URL="https://logs.fleet.example.com/loki/api/v1/push"

  run "${REPO_ROOT}/container-entrypoint.sh" --render-only
  [ "$status" -eq 0 ]

  run grep -F 'replacement  = "FLEET_AGENT_TOKEN_PLACEHOLDER"' "${FLEET_ALLOY_CONFIG}"
  [ "$status" -eq 0 ]
  run grep -c -F "${CANARY_TOKEN}" "${FLEET_ALLOY_CONFIG}"
  [ "$output" = "2" ]
  run grep -n -F "${CANARY_TOKEN}" "${FLEET_ALLOY_CONFIG}"
  [[ "$output" != *"target_label"* ]]
  [[ "$output" != *"device_role"* ]]
}

# ── The mechanism, exercised on its own ──────────────────────────────────────

@test "the renderer substitutes each slot exactly once, left to right" {
  # shellcheck source=../usr/lib/fleet-agent/identity-lib.sh
  . "${IDENTITY_LIB}"
  printf 'a=A_PLACEHOLDER b=B_PLACEHOLDER a-again=A_PLACEHOLDER\n' > "${WORK}/tpl"

  run fleet_render_template "${WORK}/tpl" "${WORK}/out" \
    "A_PLACEHOLDER=B_PLACEHOLDER" "B_PLACEHOLDER=second"
  [ "$status" -eq 0 ]
  run cat "${WORK}/out"
  [ "$output" = 'a=B_PLACEHOLDER b=second a-again=B_PLACEHOLDER' ]
}

@test "the renderer fails closed on a placeholder it was given no value for" {
  # shellcheck source=../usr/lib/fleet-agent/identity-lib.sh
  . "${IDENTITY_LIB}"
  printf 'role=DEVICE_ROLE_PLACEHOLDER token=FLEET_AGENT_TOKEN_PLACEHOLDER\n' > "${WORK}/tpl"

  run fleet_render_template "${WORK}/tpl" "${WORK}/out" "DEVICE_ROLE_PLACEHOLDER=rpi-video"
  [ "$status" -ne 0 ]
  [[ "$output" == *"no value for FLEET_AGENT_TOKEN_PLACEHOLDER"* ]]
}

@test "the renderer refuses a mapping whose value carries a newline" {
  # shellcheck source=../usr/lib/fleet-agent/identity-lib.sh
  . "${IDENTITY_LIB}"
  printf 'role=DEVICE_ROLE_PLACEHOLDER\n' > "${WORK}/tpl"

  run fleet_render_template "${WORK}/tpl" "${WORK}/out" \
    "DEVICE_ROLE_PLACEHOLDER=$(printf 'a\nb')"
  [ "$status" -ne 0 ]
  [[ "$output" == *"newline"* ]]
}

@test "no rendered config keeps an unresolved placeholder" {
  fleet_install_collector alloy
  fleet_valid_identity ENABLE_MQTT_EXPORTER=false ENABLE_PROCESS_EXPORTER=false
  run "${LIB_DIR}/generate-config.sh"
  [ "$status" -eq 0 ]
  run grep -c -E '[A-Z][A-Z0-9_]*_PLACEHOLDER' "${FLEET_ALLOY_CONFIG}"
  [ "$output" = "0" ]
}

@test "the MQTT block renders without leaving a placeholder behind" {
  fleet_install_collector alloy
  fleet_valid_identity ENABLE_MQTT_EXPORTER=true ENABLE_PROCESS_EXPORTER=true
  run "${LIB_DIR}/generate-config.sh"
  [ "$status" -eq 0 ]
  run grep -c -E '[A-Z][A-Z0-9_]*_PLACEHOLDER' "${FLEET_ALLOY_CONFIG}"
  [ "$output" = "0" ]
  run grep -F 'mqtt-password-value' "${FLEET_ALLOY_CONFIG}"
  [ "$status" -eq 0 ]
}
