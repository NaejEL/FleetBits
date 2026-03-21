#!/bin/bash
# scripts/build-deb.sh
# ─────────────────────────────────────────────────────────────────────────────
# Build the fleet-agent .deb package for one or more architectures using fpm.
#
# Dependencies: fpm (https://fpm.readthedocs.io), curl, file
#   gem install fpm
#
# Usage:
#   # Build for all supported architectures (default):
#   ./scripts/build-deb.sh
#
#   # Build for a single architecture:
#   TARGET_ARCH=arm64 ./scripts/build-deb.sh
#
#   # Override version (default: read from git tag or ALLOY_VERSION file):
#   VERSION=1.2.3 ./scripts/build-deb.sh
#
# Output: dist/fleet-agent_<version>_<arch>.deb
# ─────────────────────────────────────────────────────────────────────────────

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

# ── Version ───────────────────────────────────────────────────────────────────
VERSION="${VERSION:-}"
if [ -z "${VERSION}" ]; then
  # Use git tag if available, otherwise fall back to ALLOY_VERSION
  VERSION=$(git -C "${REPO_ROOT}" describe --tags --exact-match 2>/dev/null || true)
  VERSION="${VERSION#v}"   # strip leading 'v'
fi
if [ -z "${VERSION}" ]; then
  VERSION=$(cat "${REPO_ROOT}/ALLOY_VERSION")
fi
[ -n "${VERSION}" ] || { echo "ERROR: could not determine version" >&2; exit 1; }

# ── Alloy version + download ──────────────────────────────────────────────────
ALLOY_VERSION=$(cat "${REPO_ROOT}/ALLOY_VERSION")
BUILD_DIR="${REPO_ROOT}/build"
DIST_DIR="${REPO_ROOT}/dist"
mkdir -p "${BUILD_DIR}" "${DIST_DIR}"

# Architecture mapping: Debian arch → Alloy release arch
declare -A ARCH_MAP=(
  [amd64]="linux-amd64"
  [arm64]="linux-arm64"
  [armhf]="linux-armv7"
)

TARGET_ARCH="${TARGET_ARCH:-}"
if [ -n "${TARGET_ARCH}" ]; then
  BUILD_ARCHES=("${TARGET_ARCH}")
else
  BUILD_ARCHES=("amd64" "arm64" "armhf")
fi

# ── Build one .deb per architecture ──────────────────────────────────────────
for DEB_ARCH in "${BUILD_ARCHES[@]}"; do
  ALLOY_ARCH="${ARCH_MAP[${DEB_ARCH}]:-}"
  [ -n "${ALLOY_ARCH}" ] || { echo "ERROR: unknown architecture ${DEB_ARCH}" >&2; exit 1; }

  echo "──────────────────────────────────────────────────────"
  echo "Building fleet-agent ${VERSION} for ${DEB_ARCH}"

  # Download Alloy binary for this arch
  ALLOY_BIN="${BUILD_DIR}/alloy-${DEB_ARCH}"
  if [ ! -f "${ALLOY_BIN}" ]; then
    ALLOY_URL="https://github.com/grafana/alloy/releases/download/v${ALLOY_VERSION}/alloy-${ALLOY_ARCH}.zip"
    echo "Downloading Alloy ${ALLOY_VERSION} (${ALLOY_ARCH})..."
    curl -fsSL "${ALLOY_URL}" -o "${ALLOY_BIN}.zip"
    unzip -p "${ALLOY_BIN}.zip" "alloy-${ALLOY_ARCH}" > "${ALLOY_BIN}"
    rm "${ALLOY_BIN}.zip"
    chmod +x "${ALLOY_BIN}"
  fi

  # Make scripts executable
  chmod +x \
    "${REPO_ROOT}/usr/lib/fleet-agent/generate-config.sh" \
    "${REPO_ROOT}/usr/lib/fleet-agent/heartbeat.sh" \
    "${REPO_ROOT}/usr/lib/fleet-agent/firstboot.sh"

  # Build the .deb
  fpm \
    --input-type  dir \
    --output-type deb \
    --name        fleet-agent \
    --version     "${VERSION}" \
    --architecture "${DEB_ARCH}" \
    --maintainer  "FleetBits <fleet@example.com>" \
    --description "Fleet edge agent — Grafana Alloy + identity scripts + systemd units" \
    --url         "https://github.com/NaejEL/FleetBits-agent" \
    --license     "Apache-2.0" \
    --depends     systemd \
    --depends     curl \
    --depends     jq \
    --depends     tailscale \
    --config-files /etc/fleet/device-identity.conf \
    --after-install  "${REPO_ROOT}/scripts/postinst.sh" \
    --package     "${DIST_DIR}/fleet-agent_${VERSION}_${DEB_ARCH}.deb" \
    --force \
    --chdir       "${REPO_ROOT}" \
    "${ALLOY_BIN}=/usr/bin/alloy" \
    "etc/fleet/=/etc/fleet/" \
    "usr/lib/fleet-agent/=/usr/lib/fleet-agent/" \
    "lib/systemd/system/fleet-agent.service=/lib/systemd/system/fleet-agent.service" \
    "lib/systemd/system/fleet-heartbeat.service=/lib/systemd/system/fleet-heartbeat.service" \
    "lib/systemd/system/fleet-heartbeat.timer=/lib/systemd/system/fleet-heartbeat.timer" \
    "lib/systemd/system/fleet-firstboot.service=/lib/systemd/system/fleet-firstboot.service"

  echo "Built: ${DIST_DIR}/fleet-agent_${VERSION}_${DEB_ARCH}.deb"
done

echo "──────────────────────────────────────────────────────"
echo "All builds complete. Packages in ${DIST_DIR}/"
