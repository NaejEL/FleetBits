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

SOURCE_BUILD_DIR="${BUILD_DIR}/alloy-source-v${ALLOY_VERSION}"

# Architecture mapping: Debian arch → Alloy release arch
declare -A ARCH_MAP=(
  [amd64]="linux-amd64"
  [arm64]="linux-arm64"
  [armhf]="linux-armv7"
)

TARGET_ARCH="${TARGET_ARCH:-${1:-}}"
if [ -n "${TARGET_ARCH}" ]; then
  BUILD_ARCHES=("${TARGET_ARCH}")
else
  BUILD_ARCHES=("amd64" "arm64" "armhf")
fi

download_alloy_release_binary() {
  local deb_arch="$1"
  local alloy_bin="$2"
  local alloy_arch="$3"

  local candidate_arches=("${alloy_arch}")
  if [ "${deb_arch}" = "armhf" ]; then
    candidate_arches=("linux-armv7" "linux-armhf" "linux-arm")
  fi

  local candidate_arch
  for candidate_arch in "${candidate_arches[@]}"; do
    local alloy_url="https://github.com/grafana/alloy/releases/download/v${ALLOY_VERSION}/alloy-${candidate_arch}.zip"
    echo "Downloading Alloy ${ALLOY_VERSION} (${candidate_arch})..."

    if ! curl -fsSL "${alloy_url}" -o "${alloy_bin}.zip"; then
      continue
    fi

    local bin_in_zip
    bin_in_zip=$(unzip -Z1 "${alloy_bin}.zip" | grep '^alloy-' | head -n1 || true)
    if [ -z "${bin_in_zip}" ]; then
      rm -f "${alloy_bin}.zip"
      continue
    fi

    unzip -p "${alloy_bin}.zip" "${bin_in_zip}" > "${alloy_bin}"
    rm -f "${alloy_bin}.zip"
    chmod +x "${alloy_bin}"
    return 0
  done

  return 1
}

build_alloy_from_source() {
  local deb_arch="$1"
  local alloy_bin="$2"

  if [ "${deb_arch}" != "armhf" ]; then
    echo "ERROR: source-build fallback is only implemented for armhf" >&2
    exit 1
  fi

  if ! command -v docker >/dev/null 2>&1; then
    echo "ERROR: docker is required to build Alloy from source for ${deb_arch}" >&2
    exit 1
  fi

  if [ ! -d "${SOURCE_BUILD_DIR}/.git" ]; then
    rm -rf "${SOURCE_BUILD_DIR}"
    echo "Cloning Grafana Alloy v${ALLOY_VERSION} source for ${deb_arch} build fallback..."
    git clone --depth 1 --branch "v${ALLOY_VERSION}" \
      https://github.com/grafana/alloy.git \
      "${SOURCE_BUILD_DIR}"
  fi

  local build_image
  build_image=$(grep -m1 -o 'grafana/alloy-build-image:[^ ]*' "${SOURCE_BUILD_DIR}/Dockerfile")
  if [ -z "${build_image}" ]; then
    echo "ERROR: could not determine Grafana Alloy build image for v${ALLOY_VERSION}" >&2
    exit 1
  fi

  echo "Building Grafana Alloy v${ALLOY_VERSION} from source for ${deb_arch} using ${build_image}..."
  docker run --rm \
    -u "$(id -u):$(id -g)" \
    -v "${SOURCE_BUILD_DIR}:/src/alloy" \
    -w /src/alloy \
    "${build_image}" \
    sh -lc 'set -euo pipefail; GOOS=linux GOARCH=arm GOARM=7 RELEASE_BUILD=1 GO_TAGS="netgo embedalloyui promtail_journal_enabled" make alloy'

  install -m 755 "${SOURCE_BUILD_DIR}/build/alloy" "${alloy_bin}"
}

# ── Build one .deb per architecture ──────────────────────────────────────────
for DEB_ARCH in "${BUILD_ARCHES[@]}"; do
  ALLOY_ARCH="${ARCH_MAP[${DEB_ARCH}]:-}"
  [ -n "${ALLOY_ARCH}" ] || { echo "ERROR: unknown architecture ${DEB_ARCH}" >&2; exit 1; }

  echo "──────────────────────────────────────────────────────"
  echo "Building fleet-agent ${VERSION} for ${DEB_ARCH}"

  # Download Alloy binary for this arch
  ALLOY_BIN="${BUILD_DIR}/alloy-${DEB_ARCH}"
  if [ ! -f "${ALLOY_BIN}" ]; then
    if ! download_alloy_release_binary "${DEB_ARCH}" "${ALLOY_BIN}" "${ALLOY_ARCH}"; then
      if [ "${DEB_ARCH}" = "armhf" ]; then
        echo "No official Grafana Alloy armhf asset found for v${ALLOY_VERSION}; falling back to source build."
        build_alloy_from_source "${DEB_ARCH}" "${ALLOY_BIN}"
      else
        echo "ERROR: failed to download Alloy ${ALLOY_VERSION} for ${DEB_ARCH}" >&2
        exit 1
      fi
    fi
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
    --license     "Apache-2.0" \
    --depends     systemd \
    --depends     curl \
    --depends     jq \
    --depends     tailscale \
    --config-files /etc/fleet/device-identity.conf.example \
    --after-install  "${REPO_ROOT}/scripts/postinst.sh" \
    --package     "${DIST_DIR}/fleet-agent_${VERSION}_${DEB_ARCH}.deb" \
    --force \
    --chdir       "${REPO_ROOT}" \
    "build/alloy-${DEB_ARCH}=/usr/bin/alloy" \
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
