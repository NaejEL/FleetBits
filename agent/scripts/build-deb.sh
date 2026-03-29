#!/bin/bash
# scripts/build-deb.sh
# ─────────────────────────────────────────────────────────────────────────────
# Build the fleet-agent .deb package for one or more architectures using fpm.
#
# Dependencies: fpm (https://fpm.readthedocs.io), curl, file, tar, unzip
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
  VERSION=$(git -C "${REPO_ROOT}" describe --tags --exact-match 2>/dev/null || true)
  VERSION="${VERSION#v}"
fi
if [ -z "${VERSION}" ]; then
  VERSION=$(cat "${REPO_ROOT}/ALLOY_VERSION")
fi
[ -n "${VERSION}" ] || { echo "ERROR: could not determine version" >&2; exit 1; }

# ── Runtime versions ──────────────────────────────────────────────────────────
ALLOY_VERSION=$(cat "${REPO_ROOT}/ALLOY_VERSION")
VECTOR_VERSION=$(cat "${REPO_ROOT}/VECTOR_VERSION")
BUILD_DIR="${REPO_ROOT}/build"
DIST_DIR="${REPO_ROOT}/dist"
mkdir -p "${BUILD_DIR}" "${DIST_DIR}"

# Architecture mapping: Debian arch → runtime strategy
# amd64/arm64 stay on Alloy. armhf uses Vector because Alloy no longer ships
# official armhf artifacts.
declare -A RUNTIME_MAP=(
  [amd64]="alloy"
  [arm64]="alloy"
  [armhf]="vector"
)

declare -A ALLOY_ARCH_MAP=(
  [amd64]="linux-amd64"
  [arm64]="linux-arm64"
)

TARGET_ARCH="${TARGET_ARCH:-${1:-}}"
if [ -n "${TARGET_ARCH}" ]; then
  BUILD_ARCHES=("${TARGET_ARCH}")
else
  BUILD_ARCHES=("amd64" "arm64" "armhf")
fi

download_alloy_release_binary() {
  local alloy_bin="$1"
  local alloy_arch="$2"
  local alloy_url="https://github.com/grafana/alloy/releases/download/v${ALLOY_VERSION}/alloy-${alloy_arch}.zip"

  echo "Downloading Alloy ${ALLOY_VERSION} (${alloy_arch})..."
  curl -fsSL "${alloy_url}" -o "${alloy_bin}.zip"

  local bin_in_zip
  bin_in_zip=$(unzip -Z1 "${alloy_bin}.zip" | grep '^alloy-' | head -n1 || true)
  if [ -z "${bin_in_zip}" ]; then
    rm -f "${alloy_bin}.zip"
    echo "ERROR: could not find Alloy binary in ${alloy_url}" >&2
    exit 1
  fi

  unzip -p "${alloy_bin}.zip" "${bin_in_zip}" > "${alloy_bin}"
  rm -f "${alloy_bin}.zip"
  chmod +x "${alloy_bin}"
}

download_vector_release_binary() {
  local vector_bin="$1"
  local vector_url="https://github.com/vectordotdev/vector/releases/download/v${VECTOR_VERSION}/vector-${VECTOR_VERSION}-armv7-unknown-linux-gnueabihf.tar.gz"
  local extract_dir="${BUILD_DIR}/vector-armhf-extract"
  local extracted_root="${extract_dir}/vector-${VECTOR_VERSION}-armv7-unknown-linux-gnueabihf"

  echo "Downloading Vector ${VECTOR_VERSION} (armv7-unknown-linux-gnueabihf)..."
  curl -fsSL "${vector_url}" -o "${vector_bin}.tar.gz"

  rm -rf "${extract_dir}"
  mkdir -p "${extract_dir}"
  tar -xzf "${vector_bin}.tar.gz" -C "${extract_dir}"
  rm -f "${vector_bin}.tar.gz"

  if [ ! -f "${extracted_root}/bin/vector" ]; then
    echo "ERROR: could not find Vector binary in ${vector_url}" >&2
    exit 1
  fi

  cp "${extracted_root}/bin/vector" "${vector_bin}"
  chmod +x "${vector_bin}"
}

# ── Build one .deb per architecture ──────────────────────────────────────────
for DEB_ARCH in "${BUILD_ARCHES[@]}"; do
  RUNTIME="${RUNTIME_MAP[${DEB_ARCH}]:-}"
  [ -n "${RUNTIME}" ] || { echo "ERROR: unknown architecture ${DEB_ARCH}" >&2; exit 1; }

  echo "──────────────────────────────────────────────────────"
  echo "Building fleet-agent ${VERSION} for ${DEB_ARCH} (${RUNTIME})"

  PACKAGE_BINARY_SOURCE=""
  case "${RUNTIME}" in
    alloy)
      ALLOY_ARCH="${ALLOY_ARCH_MAP[${DEB_ARCH}]:-}"
      [ -n "${ALLOY_ARCH}" ] || { echo "ERROR: unknown Alloy architecture mapping for ${DEB_ARCH}" >&2; exit 1; }

      ALLOY_BIN="${BUILD_DIR}/alloy-${DEB_ARCH}"
      if [ ! -f "${ALLOY_BIN}" ]; then
        download_alloy_release_binary "${ALLOY_BIN}" "${ALLOY_ARCH}"
      fi
      PACKAGE_BINARY_SOURCE="build/alloy-${DEB_ARCH}=/usr/bin/alloy"
      ;;

    vector)
      VECTOR_BIN="${BUILD_DIR}/vector-${DEB_ARCH}"
      if [ ! -f "${VECTOR_BIN}" ]; then
        download_vector_release_binary "${VECTOR_BIN}"
      fi
      PACKAGE_BINARY_SOURCE="build/vector-${DEB_ARCH}=/usr/bin/vector"
      ;;

    *)
      echo "ERROR: unsupported runtime ${RUNTIME}" >&2
      exit 1
      ;;
  esac

  # Make scripts executable
  chmod +x \
    "${REPO_ROOT}/usr/lib/fleet-agent/generate-config.sh" \
    "${REPO_ROOT}/usr/lib/fleet-agent/heartbeat.sh" \
    "${REPO_ROOT}/usr/lib/fleet-agent/firstboot.sh" \
    "${REPO_ROOT}/usr/lib/fleet-agent/run-telemetry.sh"

  # Build the .deb
  fpm \
    --input-type  dir \
    --output-type deb \
    --name        fleet-agent \
    --version     "${VERSION}" \
    --architecture "${DEB_ARCH}" \
    --maintainer  "FleetBits <fleet@example.com>" \
    --description "Fleet edge agent — architecture-aware telemetry collector + identity scripts + systemd units" \
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
    "${PACKAGE_BINARY_SOURCE}" \
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
