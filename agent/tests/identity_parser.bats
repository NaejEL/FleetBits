#!/usr/bin/env bats
# Strict parser — acceptance criterion 3 (whitelist + character set) and the
# inertness guarantee the whole contract rests on (VIB-05).

setup() {
  load helpers
  fleet_test_setup
}

parse() {
  bash -c '
    set -euo pipefail
    . "'"${IDENTITY_LIB}"'"
    fleet_identity_parse "'"$1"'"
    printf "%s\n" "${FLEET_ID_DEVICE_ID}"
  '
}

# parse_in_locale LOCALE FILE — same parse, under an explicitly chosen locale.
# `env` is used rather than a prefix assignment so the setting reaches the bash
# the parser actually runs in, and nothing leaks into the test process.
parse_in_locale() {
  env LC_ALL="$1" LANG="$1" bash -c '
    set -euo pipefail
    . "'"${IDENTITY_LIB}"'"
    fleet_identity_parse "'"$2"'"
    printf "%s\n" "${FLEET_ID_DEVICE_ID}"
  '
}

@test "a contract-complete file parses and exposes every key" {
  fleet_valid_identity
  run bash -c '
    set -euo pipefail
    . "'"${IDENTITY_LIB}"'"
    fleet_identity_parse "'"${FLEET_IDENTITY_FILE}"'"
    for key in "${FLEET_IDENTITY_KEYS[@]}"; do
      varname="FLEET_ID_${key}"
      printf "%s=%s\n" "${key}" "${!varname}"
    done
  '
  [ "$status" -eq 0 ]
  [[ "$output" == *"DEVICE_ID=rpi-paris-pharaoh-02"* ]]
  [[ "$output" == *"HEADSCALE_PREAUTH_KEY="* ]]
}

@test "blank lines and whole-line comments are ignored" {
  fleet_valid_identity
  printf '\n# a trailing comment\n\n' >> "${FLEET_IDENTITY_FILE}"
  run parse "${FLEET_IDENTITY_FILE}"
  [ "$status" -eq 0 ]
}

@test "a key outside the whitelist is rejected" {
  fleet_valid_identity
  printf 'EVIL_KEY=whatever\n' >> "${FLEET_IDENTITY_FILE}"
  run parse "${FLEET_IDENTITY_FILE}"
  [ "$status" -ne 0 ]
  [[ "$output" == *"not part of the device identity contract"* ]]
}

@test "a duplicate key is rejected" {
  fleet_valid_identity
  printf 'DEVICE_ID=other\n' >> "${FLEET_IDENTITY_FILE}"
  run parse "${FLEET_IDENTITY_FILE}"
  [ "$status" -ne 0 ]
  [[ "$output" == *"duplicate key"* ]]
}

@test "a missing key is rejected" {
  fleet_valid_identity
  grep -v '^FLEET_API_URL=' "${FLEET_IDENTITY_FILE}" > "${FLEET_IDENTITY_FILE}.trimmed"
  mv "${FLEET_IDENTITY_FILE}.trimmed" "${FLEET_IDENTITY_FILE}"
  run parse "${FLEET_IDENTITY_FILE}"
  [ "$status" -ne 0 ]
  [[ "$output" == *"required key 'FLEET_API_URL' is missing"* ]]
}

@test "an empty value is rejected for a mandatory key" {
  fleet_valid_identity FLEET_AGENT_TOKEN=
  run parse "${FLEET_IDENTITY_FILE}"
  [ "$status" -ne 0 ]
  [[ "$output" == *"must not be empty"* ]]
}

@test "an empty value is accepted for a declared-optional key" {
  fleet_valid_identity PROFILE= MQTT_USERNAME= MQTT_PASSWORD= REPO_BASIC_TOKEN=
  run parse "${FLEET_IDENTITY_FILE}"
  [ "$status" -eq 0 ]
}

@test "a malformed line without '=' is rejected" {
  fleet_valid_identity
  printf 'this is not a pair\n' >> "${FLEET_IDENTITY_FILE}"
  run parse "${FLEET_IDENTITY_FILE}"
  [ "$status" -ne 0 ]
  [[ "$output" == *"malformed line"* ]]
}

# Every character the contract forbids, one test each. '|', '&' and '\' also
# protect the sed substitutions in generate-config.sh.
@test "values carrying a forbidden character are rejected" {
  local payloads=(
    'x$(id)'
    'x`id`'
    'x;id'
    'x|id'
    'x&id'
    'x\id'
    'x id'
    'x"id'
    "x'id"
    'x$HOME'
    'x>out'
  )
  for payload in "${payloads[@]}"; do
    fleet_valid_identity "DEVICE_ROLE=${payload}"
    run parse "${FLEET_IDENTITY_FILE}"
    [ "$status" -ne 0 ]
    [[ "$output" == *"outside"* ]]
    # The value itself must never be echoed: it may be a credential.
    [[ "$output" != *"${payload}"* ]]
  done
}

@test "a NUL byte in the file is rejected, never silently absorbed" {
  # `IFS= read -r line` DROPS NUL bytes instead of reporting them. Before this
  # guard, `DEVICE_ROLE=a<NUL>b` reached the value check as `ab`, passed it and
  # was stored: the parser returned 0 on a file whose content it had silently
  # rewritten, while app/contracts/device_identity.py rejects the same bytes.
  fleet_valid_identity
  local mutated="${WORK}/with-nul.conf"
  {
    grep -v '^DEVICE_ROLE=' "${FLEET_IDENTITY_FILE}"
    printf 'DEVICE_ROLE=a\000b\n'
  } > "${mutated}"
  mv "${mutated}" "${FLEET_IDENTITY_FILE}"

  run parse "${FLEET_IDENTITY_FILE}"
  [ "$status" -ne 0 ]
  [[ "$output" == *"NUL byte"* ]]
}

@test "a NUL byte anywhere in the file is rejected, not just inside a value" {
  fleet_valid_identity
  printf '\000\n' >> "${FLEET_IDENTITY_FILE}"
  run parse "${FLEET_IDENTITY_FILE}"
  [ "$status" -ne 0 ]
  [[ "$output" == *"NUL byte"* ]]
}

@test "the character-set verdict does not depend on the active locale" {
  # 'A-Z' and 'a-z' are collation RANGES: under a glibc UTF-8 locale they sweep
  # in accented letters, and 'rôle' was accepted here while the Python contract
  # rejected it. fleet_identity_set pins LC_ALL=C for the comparison. The
  # authoritative multi-locale cross-check is
  # FleetBits-api tests/test_device_identity_contract.py
  # ::test_python_and_bash_validators_agree_on_every_probe; this is the guard on
  # the agent side. On a C-only runtime the loop simply re-runs the C verdict —
  # it can never fail for the wrong reason.
  local loc
  for loc in C C.UTF-8 en_US.UTF-8 fr_FR.UTF-8; do
    fleet_valid_identity 'DEVICE_ROLE=rôle'
    run parse_in_locale "${loc}" "${FLEET_IDENTITY_FILE}"
    [ "$status" -ne 0 ]
    [[ "$output" == *"outside"* ]]
  done
}

@test "the parser never evaluates the file: no injected command runs" {
  fleet_valid_identity "DEVICE_ROLE=\$(touch ${CANARY})"
  run parse "${FLEET_IDENTITY_FILE}"
  [ "$status" -ne 0 ]
  [ ! -e "${CANARY}" ]
}
