#!/usr/bin/env bats
# The three consumers of the identity file — acceptance criteria 3, 4, 6, 10,
# 11 and 12.

setup() {
  load helpers
  fleet_test_setup
}

# ── Criterion 2 / 21 — nothing evaluates the identity file ──────────────────

@test "no agent script sources the identity file" {
  run grep -rnE '^[[:space:]]*(source|\.)[[:space:]]+[^[:space:]]*(IDENTITY|identity\.conf)' \
    "${LIB_DIR}" "${REPO_ROOT}/container-entrypoint.sh" "${REPO_ROOT}/scripts"
  [ "$status" -ne 0 ]
  [ -z "$output" ]
}

# ── Criteria 3 and 4 — each consumer rejects malicious files ────────────────
#
# Two shapes of hostile input:
#   - a key outside the contract whitelist
#   - a value that would execute if the file were evaluated by the interpreter
#     (command substitution, ';' followed by a command, variable expansion)

# prepare_consumer NAME — arrange the sandbox for one consumer and set CMD to
# the script to run. The identity file must already have been written.
prepare_consumer() {
  case "$1" in
    generate-config)
      fleet_install_collector alloy
      CMD="${LIB_DIR}/generate-config.sh"
      ;;
    heartbeat)
      CMD="${LIB_DIR}/heartbeat.sh"
      ;;
    firstboot)
      fleet_install_collector alloy
      fleet_write_provision_json
      # firstboot reads what the server sent, so the hostile file is served by
      # the curl stub and must be rejected before it is installed.
      export FLEET_TEST_PROVISION_RESPONSE="${WORK}/payload.conf"
      cp "${FLEET_IDENTITY_FILE}" "${FLEET_TEST_PROVISION_RESPONSE}"
      rm -f "${FLEET_IDENTITY_FILE}"
      CMD="${LIB_DIR}/firstboot.sh"
      ;;
  esac
}

@test "every consumer rejects a key outside the whitelist" {
  for consumer in generate-config heartbeat firstboot; do
    fleet_test_setup
    fleet_valid_identity
    printf 'EVIL_KEY=whatever\n' >> "${FLEET_IDENTITY_FILE}"
    prepare_consumer "${consumer}"
    run "${CMD}"
    [ "$status" -ne 0 ]
    [[ "$output" == *"not part of the device identity contract"* ]]
  done
}

@test "every consumer rejects a value outside the allowed character set" {
  for consumer in generate-config heartbeat firstboot; do
    for payload in 'x$(id)' 'x;id' 'x${HOME}'; do
      fleet_test_setup
      fleet_valid_identity "DEVICE_ROLE=${payload}"
      prepare_consumer "${consumer}"
      run "${CMD}"
      [ "$status" -ne 0 ]
      [[ "$output" == *"outside"* ]]
    done
  done
}

@test "every consumer refuses an injected command and leaves no trace of it" {
  for consumer in generate-config heartbeat firstboot; do
    for template in '$(touch CANARY)' '`touch CANARY`' 'x;touch CANARY' 'x;$(touch CANARY)'; do
      fleet_test_setup
      payload="${template//CANARY/${CANARY}}"
      fleet_valid_identity "DEVICE_ROLE=${payload}"
      prepare_consumer "${consumer}"
      run "${CMD}"
      [ "$status" -ne 0 ]
      [ ! -e "${CANARY}" ]
    done
  done
}

@test "a variable expansion in a value is never expanded" {
  # SECRET_MARKER is in the environment and the identity file carries its name
  # in a value. Written literally (single quotes below), the file holds the
  # eight characters '${SECRET' ... — never the marker's value. Were the file
  # evaluated by the interpreter instead of parsed, the expansion would put the
  # environment value into SITE_ID and from there into the collector config.
  fleet_install_collector alloy
  fleet_valid_identity 'SITE_ID=paris-${SECRET_MARKER}'
  export SECRET_MARKER="leaked-environment-value"

  run "${LIB_DIR}/generate-config.sh"
  # '$' and '{' are outside the contract character set, so the strict parser
  # rejects the file before any consumer sees the value.
  [ "$status" -ne 0 ]
  [[ "$output" == *"outside"* ]]
  # Nothing was rendered, ...
  [ ! -e "${FLEET_ALLOY_CONFIG}" ]
  # ... and the marker's *value* appears nowhere under the sandbox: only its
  # name, literally, in the identity file the test wrote.
  run grep -rF "leaked-environment-value" "${WORK}"
  [ "$status" -ne 0 ]
  run grep -cF 'SITE_ID=paris-${SECRET_MARKER}' "${FLEET_IDENTITY_FILE}"
  [ "$output" = "1" ]
}

# ── Criterion 6 — heartbeat reaches the HTTP request ────────────────────────

@test "heartbeat sends its request using FLEET_API_URL from the identity file" {
  fleet_valid_identity
  run "${LIB_DIR}/heartbeat.sh"
  [ "$status" -eq 0 ]
  run grep -F 'curl https://api.fleet.example.com/api/v1/devices/rpi-paris-pharaoh-02/heartbeat' \
    "${STUB_LOG}"
  [ "$status" -eq 0 ]
}

@test "heartbeat fails when FLEET_API_URL is absent from the file" {
  fleet_valid_identity
  grep -v '^FLEET_API_URL=' "${FLEET_IDENTITY_FILE}" > "${FLEET_IDENTITY_FILE}.t"
  mv "${FLEET_IDENTITY_FILE}.t" "${FLEET_IDENTITY_FILE}"
  run "${LIB_DIR}/heartbeat.sh"
  [ "$status" -ne 0 ]
  [[ "$output" == *"FLEET_API_URL"* ]]
}

# ── Criterion 11 — ENVIRONMENT and RING are rendered as telemetry labels ────

@test "the rendered Alloy config carries the environment and ring labels" {
  fleet_install_collector alloy
  fleet_valid_identity ENVIRONMENT=prod RING=1
  run "${LIB_DIR}/generate-config.sh"
  [ "$status" -eq 0 ]

  run grep -c 'target_label = "environment"' "${FLEET_ALLOY_CONFIG}"
  [ "$output" = "1" ]
  run grep -c 'target_label = "ring"' "${FLEET_ALLOY_CONFIG}"
  [ "$output" = "1" ]
  run grep -F 'replacement  = "prod"' "${FLEET_ALLOY_CONFIG}"
  [ "$status" -eq 0 ]
  run grep -F 'replacement  = "1"' "${FLEET_ALLOY_CONFIG}"
  [ "$status" -eq 0 ]
  run grep -F 'environment = "prod"' "${FLEET_ALLOY_CONFIG}"
  [ "$status" -eq 0 ]
  run grep -F 'ring        = "1"' "${FLEET_ALLOY_CONFIG}"
  [ "$status" -eq 0 ]
  run grep -c 'ENVIRONMENT_PLACEHOLDER\|RING_PLACEHOLDER' "${FLEET_ALLOY_CONFIG}"
  [ "$output" = "0" ]
}

@test "the rendered Vector config carries the environment and ring labels" {
  fleet_install_collector vector
  fleet_valid_identity ENVIRONMENT=prod RING=2
  run "${LIB_DIR}/generate-config.sh"
  [ "$status" -eq 0 ]
  run grep -F '.tags.environment = "prod"' "${FLEET_VECTOR_CONFIG}"
  [ "$status" -eq 0 ]
  run grep -F '.tags.ring = "2"' "${FLEET_VECTOR_CONFIG}"
  [ "$status" -eq 0 ]
  run grep -F '.environment = "prod"' "${FLEET_VECTOR_CONFIG}"
  [ "$status" -eq 0 ]
  run grep -F '.ring = "2"' "${FLEET_VECTOR_CONFIG}"
  [ "$status" -eq 0 ]
}

# ── Criterion 10 — FLEET_LOGS_URL feeds the Vector renderer ─────────────────

@test "the Vector renderer accepts the absolute logs URL of the contract" {
  fleet_install_collector vector
  fleet_valid_identity FLEET_LOGS_URL=https://logs.fleet.example.com/loki/api/v1/push
  run "${LIB_DIR}/generate-config.sh"
  [ "$status" -eq 0 ]
  run grep -F 'endpoint: "https://logs.fleet.example.com"' "${FLEET_VECTOR_CONFIG}"
  [ "$status" -eq 0 ]
  run grep -F 'path: "/loki/api/v1/push"' "${FLEET_VECTOR_CONFIG}"
  [ "$status" -eq 0 ]
}

@test "the Vector renderer refuses a non-absolute logs URL" {
  fleet_install_collector vector
  fleet_valid_identity FLEET_LOGS_URL=logs.fleet.example.com/loki/api/v1/push
  run "${LIB_DIR}/generate-config.sh"
  [ "$status" -ne 0 ]
  [[ "$output" == *"absolute URL"* ]]
}

# ── Criterion 12 — an empty HEADSCALE_PREAUTH_KEY is a valid state ──────────

@test "an empty HEADSCALE_PREAUTH_KEY is accepted by generate-config and heartbeat" {
  for consumer in generate-config heartbeat; do
    fleet_test_setup
    fleet_install_collector alloy
    fleet_valid_identity HEADSCALE_PREAUTH_KEY=
    case "${consumer}" in
      generate-config) run "${LIB_DIR}/generate-config.sh" ;;
      heartbeat)       run "${LIB_DIR}/heartbeat.sh" ;;
    esac
    [ "$status" -eq 0 ]
  done
}

@test "firstboot skips Headscale enrollment when the preauth key is empty" {
  fleet_install_collector alloy
  fleet_valid_identity HEADSCALE_PREAUTH_KEY=
  fleet_write_provision_json
  export FLEET_TEST_PROVISION_RESPONSE="${WORK}/payload.conf"
  cp "${FLEET_IDENTITY_FILE}" "${FLEET_TEST_PROVISION_RESPONSE}"
  rm -f "${FLEET_IDENTITY_FILE}"

  run "${LIB_DIR}/firstboot.sh"
  [ "$status" -eq 0 ]
  # Every assertion about firstboot's own output must read this copy: `run`
  # below overwrites $output with the output of grep.
  firstboot_output="$output"
  [[ "${firstboot_output}" == *"skipping Headscale enrollment"* ]]
  # ... and enrollment still ran to completion, without a fatal error.
  [[ "${firstboot_output}" == *"First-boot complete"* ]]
  [[ "${firstboot_output}" != *"FATAL"* ]]
  # The branch was not taken: tailscale was never invoked.
  run grep -c '^tailscale ' "${STUB_LOG}"
  [ "$output" = "0" ]
  run grep -F 'systemctl disable fleet-firstboot.service' "${STUB_LOG}"
  [ "$status" -eq 0 ]
}

@test "firstboot enrolls in Headscale when a preauth key is present" {
  fleet_install_collector alloy
  fleet_valid_identity HEADSCALE_PREAUTH_KEY=preauth-key-value
  fleet_write_provision_json
  export FLEET_TEST_PROVISION_RESPONSE="${WORK}/payload.conf"
  cp "${FLEET_IDENTITY_FILE}" "${FLEET_TEST_PROVISION_RESPONSE}"
  rm -f "${FLEET_IDENTITY_FILE}"

  run "${LIB_DIR}/firstboot.sh"
  [ "$status" -eq 0 ]
  run grep -F 'tailscale up --login-server https://headscale.fleet.example.com --authkey preauth-key-value' \
    "${STUB_LOG}"
  [ "$status" -eq 0 ]
}

# ── Criterion 1 — firstboot calls the declared route, device id included ────

@test "firstboot posts to the provisioning route carrying the device id" {
  fleet_install_collector alloy
  fleet_valid_identity
  fleet_write_provision_json
  export FLEET_TEST_PROVISION_RESPONSE="${WORK}/payload.conf"
  cp "${FLEET_IDENTITY_FILE}" "${FLEET_TEST_PROVISION_RESPONSE}"
  rm -f "${FLEET_IDENTITY_FILE}"

  run "${LIB_DIR}/firstboot.sh"
  [ "$status" -eq 0 ]
  run grep -F 'curl https://api.fleet.example.com/api/v1/devices/rpi-paris-pharaoh-02/provision' \
    "${STUB_LOG}"
  [ "$status" -eq 0 ]
}

@test "firstboot installs the identity file with mode 600" {
  fleet_install_collector alloy
  fleet_valid_identity
  fleet_write_provision_json
  export FLEET_TEST_PROVISION_RESPONSE="${WORK}/payload.conf"
  cp "${FLEET_IDENTITY_FILE}" "${FLEET_TEST_PROVISION_RESPONSE}"
  rm -f "${FLEET_IDENTITY_FILE}"

  run "${LIB_DIR}/firstboot.sh"
  [ "$status" -eq 0 ]
  run stat -c '%a' "${FLEET_IDENTITY_FILE}"
  [ "$output" = "600" ]
}
