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
#   fleetbits-update --dry-run     # print actions without applying changes
#
# Run on the LXC container (not the Proxmox host).
# =============================================================================

set -euo pipefail

RED='\033[0;31m'; GRN='\033[0;32m'; YLW='\033[1;33m'; CYN='\033[0;36m'; NC='\033[0m'
info()    { echo -e "${CYN}[INFO]${NC}  $*"; }
success() { echo -e "${GRN}[OK]${NC}    $*"; }
warn()    { echo -e "${YLW}[WARN]${NC}  $*"; }
error()   { echo -e "${RED}[ERR]${NC}   $*"; }

require_cmd() {
    command -v "$1" >/dev/null 2>&1 || {
        error "Missing required command: $1"
        exit 1
    }
}

DRY_RUN=false

run_cmd() {
    if [ "${DRY_RUN}" = "true" ]; then
        echo "[DRY-RUN] $*"
        return 0
    fi
    "$@"
}

print_usage() {
    cat <<'EOF'
Usage:
  fleetbits-update [--config-only] [--images-only] [--dry-run]

Options:
  --config-only  Pull latest FleetBits-platform config only
  --images-only  Pull/restart images only (skip git pull)
  --dry-run      Print actions without applying changes
EOF
}

INSTALL_DIR="/opt/fleetbits"
COMPOSE_DIR="${INSTALL_DIR}/FleetBits-platform/docker"
SECRETS_FILE="${INSTALL_DIR}/secrets.env"

CONFIG_ONLY=false
IMAGES_ONLY=false
for arg in "$@"; do
    case "${arg}" in
        --config-only) CONFIG_ONLY=true ;;
        --images-only) IMAGES_ONLY=true ;;
        --dry-run) DRY_RUN=true ;;
        -h|--help)
            print_usage
            exit 0
            ;;
        *)
            error "Unknown argument: ${arg}"
            print_usage
            exit 1
            ;;
    esac
done

if [ "${CONFIG_ONLY}" = "true" ] && [ "${IMAGES_ONLY}" = "true" ]; then
    error "--config-only and --images-only are mutually exclusive"
    exit 1
fi

[ -d "${INSTALL_DIR}" ] || { echo "ERROR: ${INSTALL_DIR} not found. Is FleetBits installed?" >&2; exit 1; }
[ -f "${SECRETS_FILE}" ] || { echo "ERROR: ${SECRETS_FILE} not found." >&2; exit 1; }

require_cmd git
require_cmd docker

COMPOSE=(docker compose --env-file "${SECRETS_FILE}")

if ! "${COMPOSE[@]}" config >/dev/null 2>&1; then
    error "docker compose config validation failed. Fix compose/secrets before updating."
    exit 1
fi

has_jq=false
if command -v jq >/dev/null 2>&1; then
    has_jq=true
fi

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
    run_cmd git pull --ff-only
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

changed_files_between_revs() {
    local from_rev="$1"
    local to_rev="$2"
    git diff --name-only "${from_rev}..${to_rev}" 2>/dev/null || true
}

append_unique_service() {
    local svc="$1"
    if [ -z "${LOCAL_SERVICES_TO_REBUILD:-}" ]; then
        LOCAL_SERVICES_TO_REBUILD="${svc}"
        return
    fi

    case " ${LOCAL_SERVICES_TO_REBUILD} " in
        *" ${svc} "*) ;;
        *) LOCAL_SERVICES_TO_REBUILD="${LOCAL_SERVICES_TO_REBUILD} ${svc}" ;;
    esac
}

derive_local_rebuild_targets() {
    local from_rev="$1"
    local to_rev="$2"
    local f

    LOCAL_SERVICES_TO_REBUILD=""
    while IFS= read -r f; do
        [ -z "${f}" ] && continue
        case "${f}" in
            docker/prometheus/*) append_unique_service prometheus ;;
            docker/loki/*) append_unique_service loki ;;
            docker/alertmanager/*) append_unique_service alertmanager ;;
            docker/headscale/*) append_unique_service headscale ;;
            docker/caddy/*) append_unique_service caddy ;;
            docker/postgresql/*) append_unique_service postgresql ;;
            docker/aptly/*) append_unique_service aptly-api ;;
            docker/grafana/*) append_unique_service grafana ;;
            docker/mosquitto/*) append_unique_service mosquitto ;;
            docker/mqtt-exporter/*) append_unique_service mqtt-exporter ;;
            docker/docker-compose.yml|docker/docker-compose.override.behind-proxy.yml)
                append_unique_service prometheus
                append_unique_service loki
                append_unique_service alertmanager
                append_unique_service headscale
                append_unique_service caddy
                append_unique_service postgresql
                append_unique_service aptly-api
                append_unique_service grafana
                append_unique_service mosquitto
                append_unique_service mqtt-exporter
                ;;
        esac
    done < <(changed_files_between_revs "${from_rev}" "${to_rev}")
}

get_service_digest() {
    local service="$1"
    local image_id
    image_id=$("${COMPOSE[@]}" images -q "${service}" 2>/dev/null || true)
    if [ -z "${image_id}" ]; then
        echo "none"
        return
    fi

    docker inspect --format='{{index .RepoDigests 0}}' "${image_id}" 2>/dev/null || echo "none"
}

# ── Secrets migration: add new required keys if missing ───────────────────────
# Run regardless of --config-only / --images-only so existing installs always
# get required secrets even if only images are being updated.
if [ "${DRY_RUN}" != "true" ]; then
    if ! grep -q "^GRAFANA_PROXY_SECRET=" "${SECRETS_FILE}" 2>/dev/null; then
        warn "GRAFANA_PROXY_SECRET missing from secrets.env — generating for Grafana SSO..."
        NEW_SECRET=$(openssl rand -base64 32)
        {
            echo ""
            echo "# Grafana Auth Proxy shared secret (added automatically by fleetbits-update)"
            echo "GRAFANA_PROXY_SECRET=${NEW_SECRET}"
        } >> "${SECRETS_FILE}"
        success "GRAFANA_PROXY_SECRET added to secrets.env."
    fi
else
    if ! grep -q "^GRAFANA_PROXY_SECRET=" "${SECRETS_FILE}" 2>/dev/null; then
        echo "[DRY-RUN] Would generate and append GRAFANA_PROXY_SECRET to secrets.env"
    fi
fi

# ── Step 2: Pull new Docker images ────────────────────────────────────────────
if [ "${CONFIG_ONLY}" != "true" ]; then
    info "Pulling latest Docker images (fleet-api, fleet-ui)..."
    cd "${COMPOSE_DIR}"

    # Record image digests before pull to detect changes
    OLD_API_DIGEST=$(get_service_digest fleet-api)
    OLD_UI_DIGEST=$(get_service_digest fleet-ui)

    run_cmd "${COMPOSE[@]}" pull fleet-api fleet-ui

    NEW_API_DIGEST=$(get_service_digest fleet-api)
    NEW_UI_DIGEST=$(get_service_digest fleet-ui)

    API_CHANGED=false
    UI_CHANGED=false
    [ "${OLD_API_DIGEST}" != "${NEW_API_DIGEST}" ] && API_CHANGED=true
    [ "${OLD_UI_DIGEST}"  != "${NEW_UI_DIGEST}"  ] && UI_CHANGED=true

    if [ "${API_CHANGED}" = "true" ]; then
        info "fleet-api image updated. Restarting..."
        run_cmd "${COMPOSE[@]}" up -d --no-deps fleet-api
        success "fleet-api restarted."
    else
        info "fleet-api image unchanged."
    fi

    if [ "${UI_CHANGED}" = "true" ]; then
        info "fleet-ui image updated. Restarting..."
        run_cmd "${COMPOSE[@]}" up -d --no-deps fleet-ui
        success "fleet-ui restarted."
    else
        info "fleet-ui image unchanged."
    fi

    # ── Rebuild locally-built services if config changed ──────────────────────
    # Services built from the repo (not pulled from GHCR): prometheus, loki, alertmanager,
    # alertmanager, headscale, postgresql, aptly, caddy, node-exporter are pinned images.
    # Rebuild if their Dockerfiles or config changed.
    if [ "${CONFIG_ONLY}" != "true" ] && [ "${BEFORE:-}" != "${AFTER:-}" ]; then
        derive_local_rebuild_targets "${BEFORE}" "${AFTER}"
        if [ -n "${LOCAL_SERVICES_TO_REBUILD:-}" ]; then
            info "Platform config changed — rebuilding impacted local services: ${LOCAL_SERVICES_TO_REBUILD}"
            run_cmd "${COMPOSE[@]}" up -d --build ${LOCAL_SERVICES_TO_REBUILD}
            success "Impacted local services rebuilt."
        else
            info "Platform config changed, but no local Docker service configs were modified."
        fi
    fi
fi

# ── Step 3: Verify health ──────────────────────────────────────────────────────
info "Checking service health..."
cd "${COMPOSE_DIR}"
if [ "${DRY_RUN}" = "true" ]; then
    info "Skipping health check in dry-run mode."
else
    if [ "${has_jq}" = "true" ]; then
        UNHEALTHY=$("${COMPOSE[@]}" ps --format json 2>/dev/null \
            | jq -r 'select(.Health == "unhealthy") | .Name' 2>/dev/null || true)

        if [ -n "${UNHEALTHY}" ]; then
            warn "Unhealthy containers detected:"
            echo "${UNHEALTHY}" | while read -r name; do warn "  ${name}"; done
            warn "Check logs: docker logs <name>"
        else
            success "No unhealthy containers detected."
        fi
    else
        warn "jq not installed — using plain compose status output as fallback."
        "${COMPOSE[@]}" ps
    fi
fi

# ── Step 4: Clean up old images ────────────────────────────────────────────────
info "Removing dangling image layers..."
if [ "${DRY_RUN}" = "true" ]; then
    echo "[DRY-RUN] docker image prune -f --filter dangling=true"
else
    docker image prune -f --filter "dangling=true" > /dev/null
fi
success "Cleanup complete."

echo ""
success "FleetBits update complete."
echo ""
