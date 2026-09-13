#!/bin/bash
# scripts/run-tests.sh
# ─────────────────────────────────────────────────────────────────────────────
# Single entry point for the FleetBits-agent test suite:
#   1. shellcheck over every shell script in the repository
#   2. the bats suite in tests/
#
# Both tools are taken from $PATH when installed and from their official
# container images otherwise, so the command works unchanged on a developer
# machine that only has Docker and on a CI runner that installs the packages.
#
#   ./scripts/run-tests.sh
# ─────────────────────────────────────────────────────────────────────────────

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${REPO_ROOT}"

SHELLCHECK_IMAGE="${SHELLCHECK_IMAGE:-koalaman/shellcheck:stable}"
BATS_IMAGE="${BATS_IMAGE:-bats/bats:latest}"

SCRIPTS=(
  usr/lib/fleet-agent/identity-lib.sh
  usr/lib/fleet-agent/firstboot.sh
  usr/lib/fleet-agent/generate-config.sh
  usr/lib/fleet-agent/heartbeat.sh
  usr/lib/fleet-agent/run-telemetry.sh
  container-entrypoint.sh
  scripts/postinst.sh
  scripts/build-deb.sh
  scripts/run-tests.sh
  tests/helpers.bash
  tests/stubs/curl
  tests/stubs/jq
  tests/stubs/ssh-keygen
  tests/stubs/systemctl
  tests/stubs/tailscale
)

echo "── shellcheck ───────────────────────────────────────────────────────────"
if command -v shellcheck >/dev/null 2>&1; then
  shellcheck -x --shell=bash "${SCRIPTS[@]}"
else
  echo "shellcheck not on PATH — using ${SHELLCHECK_IMAGE}"
  docker run --rm -v "${REPO_ROOT}":/mnt -w /mnt "${SHELLCHECK_IMAGE}" \
    -x --shell=bash "${SCRIPTS[@]}"
fi
echo "shellcheck: OK"

echo "── bats ─────────────────────────────────────────────────────────────────"
if command -v bats >/dev/null 2>&1; then
  bats tests/
else
  echo "bats not on PATH — using ${BATS_IMAGE}"
  docker run --rm -v "${REPO_ROOT}":/code -w /code "${BATS_IMAGE}" tests/
fi
echo "bats: OK"
