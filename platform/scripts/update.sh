#!/usr/bin/env bash
# =============================================================================
# FleetBits Platform — Rolling Update Script
# =============================================================================
# Pulls the latest platform config, pulls new Docker images, and restarts
# only the containers whose images have changed. Zero-downtime is not
# guaranteed on a single-host compose setup, but restarts are sequential
# and typically take < 10 seconds per service.
#
# Usage:
#   fleetbits-update               # update everything
#   fleetbits-update --config-only # git pull config, no image pull/restart
#   fleetbits-update --images-only # pull + restart images, no git pull
#
# Run on the LXC container (not the Proxmox host).
# =============================================================================

set -euo pipefail

RED='\033[0;31m'; GRN='\033[0;32m'; YLW='\033[1;33m'; CYN='\033[0;36m'; NC='\033[0m'
info()    { echo -e "${CYN}[INFO]${NC}  $*"; }
success() { echo -e "${GRN}[OK]${NC}    $*"; }
warn()    { echo -e "${YLW}[WARN]${NC}  $*"; }

INSTALL_DIR="/opt/fleetbits"
COMPOSE_DIR="${INSTALL_DIR}/FleetBits-platform/docker"
SECRETS_FILE="${INSTALL_DIR}/secrets.env"

CONFIG_ONLY=false
IMAGES_ONLY=false
for arg in "$@"; do
    case "${arg}" in
        --config-only) CONFIG_ONLY=true ;;
        --images-only) IMAGES_ONLY=true ;;
    esac
done

[ -d "${INSTALL_DIR}" ] || { echo "ERROR: ${INSTALL_DIR} not found. Is FleetBits installed?" >&2; exit 1; }
[ -f "${SECRETS_FILE}" ] || { echo "ERROR: ${SECRETS_FILE} not found." >&2; exit 1; }

echo ""
echo -e "${CYN}╔══════════════════════════════════════════════╗${NC}"
echo -e "${CYN}║       FleetBits Platform Update              ║${NC}"
echo -e "${CYN}╚══════════════════════════════════════════════╝${NC}"
echo ""

# ── Step 1: Pull latest platform config ───────────────────────────────────────
if [ "${IMAGES_ONLY}" != "true" ]; then
    info "Pulling latest FleetBits-platform config from GitHub..."
    cd "${INSTALL_DIR}/FleetBits-platform"
    BEFORE=$(git rev-parse HEAD)
    git pull --ff-only
    AFTER=$(git rev-parse HEAD)

    if [ "${BEFORE}" != "${AFTER}" ]; then
        success "Config updated: ${BEFORE:0:8} → ${AFTER:0:8}"
        git log --oneline "${BEFORE}..${AFTER}" | while read -r line; do
            echo "    ${line}"
        done
    else
        info "Config already up to date."
    fi
fi

# ── Step 2: Pull new Docker images ────────────────────────────────────────────
if [ "${CONFIG_ONLY}" != "true" ]; then
    info "Pulling latest Docker images (fleet-api, fleet-ui)..."
    cd "${COMPOSE_DIR}"

    # Record image digests before pull to detect changes
    OLD_API_DIGEST=$(docker inspect --format='{{index .RepoDigests 0}}' \
        "$(docker compose --env-file "${SECRETS_FILE}" images -q fleet-api 2>/dev/null)" 2>/dev/null || echo "none")
    OLD_UI_DIGEST=$(docker inspect --format='{{index .RepoDigests 0}}' \
        "$(docker compose --env-file "${SECRETS_FILE}" images -q fleet-ui 2>/dev/null)" 2>/dev/null || echo "none")

    docker compose --env-file "${SECRETS_FILE}" pull fleet-api fleet-ui

    NEW_API_DIGEST=$(docker inspect --format='{{index .RepoDigests 0}}' \
        "$(docker compose --env-file "${SECRETS_FILE}" images -q fleet-api 2>/dev/null)" 2>/dev/null || echo "none")
    NEW_UI_DIGEST=$(docker inspect --format='{{index .RepoDigests 0}}' \
        "$(docker compose --env-file "${SECRETS_FILE}" images -q fleet-ui 2>/dev/null)" 2>/dev/null || echo "none")

    API_CHANGED=false
    UI_CHANGED=false
    [ "${OLD_API_DIGEST}" != "${NEW_API_DIGEST}" ] && API_CHANGED=true
    [ "${OLD_UI_DIGEST}"  != "${NEW_UI_DIGEST}"  ] && UI_CHANGED=true

    if [ "${API_CHANGED}" = "true" ]; then
        info "fleet-api image updated. Restarting..."
        docker compose --env-file "${SECRETS_FILE}" up -d --no-deps fleet-api
        success "fleet-api restarted."
    else
        info "fleet-api image unchanged."
    fi

    if [ "${UI_CHANGED}" = "true" ]; then
        info "fleet-ui image updated. Restarting..."
        docker compose --env-file "${SECRETS_FILE}" up -d --no-deps fleet-ui
        success "fleet-ui restarted."
    else
        info "fleet-ui image unchanged."
    fi

    # ── Rebuild locally-built services if config changed ──────────────────────
    # Services built from the repo (not pulled from GHCR): prometheus, loki, alertmanager,
    # alertmanager, headscale, postgresql, aptly, caddy, node-exporter are pinned images.
    # Rebuild if their Dockerfiles or config changed.
    if [ "${CONFIG_ONLY}" != "true" ] && [ "${BEFORE:-}" != "${AFTER:-}" ]; then
        info "Platform config changed — rebuilding local services..."
        docker compose --env-file "${SECRETS_FILE}" up -d --build \
            prometheus loki alertmanager headscale caddy
        success "Local services rebuilt."
    fi
fi

# ── Step 3: Verify health ──────────────────────────────────────────────────────
info "Checking service health..."
cd "${COMPOSE_DIR}"
UNHEALTHY=$(docker compose --env-file "${SECRETS_FILE}" ps --format json 2>/dev/null \
    | jq -r 'select(.Health == "unhealthy") | .Name' 2>/dev/null || true)

if [ -n "${UNHEALTHY}" ]; then
    warn "Unhealthy containers detected:"
    echo "${UNHEALTHY}" | while read -r name; do warn "  ${name}"; done
    warn "Check logs: docker logs <name>"
else
    success "All services healthy."
fi

# ── Step 4: Clean up old images ────────────────────────────────────────────────
info "Removing dangling images..."
docker image prune -f --filter "dangling=true" > /dev/null
success "Cleanup complete."

echo ""
success "FleetBits update complete."
echo ""
