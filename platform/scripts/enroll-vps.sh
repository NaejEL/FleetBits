#!/usr/bin/env bash
# =============================================================================
# enroll-vps.sh — Enroll the VPS platform host as a managed fleet-bits device
# =============================================================================
# Idempotent — safe to run multiple times.
# Steps:
#   1. Parse secrets.env for OPERATOR_USERNAME / OPERATOR_PASSWORD
#   2. Obtain an operator JWT from Fleet API
#   3. Create site  'control-plane'        (skip if already exists)
#   4. Create zone  'vps'                  (skip if already exists)
#   5. Create device 'vps-control-plane'   (skip if already exists)
#   6. Issue a new device token
#   7. Write VPS_DEVICE_TOKEN back to secrets.env
#
# Usage:
#   bash enroll-vps.sh [--api-url http://localhost:8000] [--secrets /path/to/secrets.env]
#
# Requirements: curl, jq
# =============================================================================

set -euo pipefail

# ── Colour helpers ─────────────────────────────────────────────────────────────
CYN='\033[0;36m'; GRN='\033[0;32m'; YLW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
info()    { echo -e "${CYN}[INFO]${NC}  $*"; }
success() { echo -e "${GRN}[OK]${NC}    $*"; }
warn()    { echo -e "${YLW}[WARN]${NC}  $*"; }
error()   { echo -e "${RED}[ERROR]${NC} $*" >&2; exit 1; }

# ── Defaults ───────────────────────────────────────────────────────────────────
FLEET_API_URL="http://localhost:8000"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SECRETS_ENV="${SCRIPT_DIR}/../secrets.env"

# ── Argument parsing ───────────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
    case "$1" in
        --api-url)   FLEET_API_URL="$2"; shift 2 ;;
        --secrets)   SECRETS_ENV="$2";   shift 2 ;;
        *) error "Unknown argument: $1. Usage: $0 [--api-url URL] [--secrets PATH]" ;;
    esac
done

# ── Prerequisites check ────────────────────────────────────────────────────────
command -v curl &>/dev/null || error "curl is required but not installed. Run: apt-get install curl"
command -v jq   &>/dev/null || error "jq is required but not installed.   Run: apt-get install jq"

# ── Resolve secrets.env path ──────────────────────────────────────────────────
SECRETS_ENV="$(realpath "${SECRETS_ENV}" 2>/dev/null || echo "${SECRETS_ENV}")"
[ -f "${SECRETS_ENV}" ] || error "secrets.env not found at: ${SECRETS_ENV}
Copy secrets.env.example to secrets.env and fill in the values."

# ── Helpers ────────────────────────────────────────────────────────────────────

read_secret() {
    # Usage: read_secret KEY
    grep -E "^${1}=" "${SECRETS_ENV}" | head -n1 | cut -d= -f2- | tr -d '[:space:]'
}

update_secret() {
    # Usage: update_secret KEY VALUE
    local key="$1" value="$2"
    if grep -qE "^${key}=" "${SECRETS_ENV}"; then
        # Replace existing line (works on Linux and macOS)
        sed -i.bak "s|^${key}=.*|${key}=${value}|" "${SECRETS_ENV}" && rm -f "${SECRETS_ENV}.bak"
    else
        printf '\n%s=%s\n' "${key}" "${value}" >> "${SECRETS_ENV}"
    fi
    info "[secrets.env] ${key} updated."
}

# api_call METHOD ENDPOINT [JSON_BODY]
# Returns response body on success; returns empty string on 409; exits on other errors.
api_call() {
    local method="$1" endpoint="$2" body="${3:-}"
    local url="${FLEET_API_URL}${endpoint}"
    local curl_args=(-s -w "\n%{http_code}" -X "${method}" "${url}"
                     -H "Content-Type: application/json")
    [ -n "${AUTH_HEADER:-}" ] && curl_args+=(-H "Authorization: Bearer ${JWT}")
    [ -n "${body}" ]          && curl_args+=(-d "${body}")

    local raw
    raw=$(curl "${curl_args[@]}")
    local http_code
    http_code=$(echo "${raw}" | tail -n1)
    local response
    response=$(echo "${raw}" | head -n-1)

    if [[ "${http_code}" == "409" ]]; then
        echo ""   # already exists — idempotent
        return 0
    fi

    if [[ "${http_code}" =~ ^2 ]]; then
        echo "${response}"
        return 0
    fi

    error "API call failed [${method} ${url}] HTTP ${http_code}: ${response}"
}

# ── Banner ─────────────────────────────────────────────────────────────────────
echo ""
echo -e "${CYN}╔══════════════════════════════════════════════════╗${NC}"
echo -e "${CYN}║         FleetBits — Enroll VPS Device            ║${NC}"
echo -e "${CYN}╚══════════════════════════════════════════════════╝${NC}"
echo ""

# ── 1. Read credentials ───────────────────────────────────────────────────────
info "[1/6] Reading credentials from secrets.env..."

OPERATOR_USERNAME=$(read_secret "OPERATOR_USERNAME")
OPERATOR_PASSWORD=$(read_secret "OPERATOR_PASSWORD")

if [[ -z "${OPERATOR_USERNAME}" || -z "${OPERATOR_PASSWORD}" ]]; then
    warn "OPERATOR_USERNAME / OPERATOR_PASSWORD not found in secrets.env."
    read -rp "Fleet operator username: " OPERATOR_USERNAME
    read -rsp "Fleet operator password: " OPERATOR_PASSWORD
    echo ""
fi

# ── 2. Obtain JWT ─────────────────────────────────────────────────────────────
info "[2/6] Authenticating as operator '${OPERATOR_USERNAME}'..."

AUTH_RESPONSE=$(api_call POST "/api/v1/auth/login" \
    "{\"username\":\"${OPERATOR_USERNAME}\",\"password\":\"${OPERATOR_PASSWORD}\"}")

JWT=$(echo "${AUTH_RESPONSE}" | jq -r '.access_token // empty')
[ -n "${JWT}" ] || error "Login failed — no access_token in response: ${AUTH_RESPONSE}"
AUTH_HEADER="set"   # flag for api_call to include Authorization header
success "JWT obtained."

# ── 3. Create site ────────────────────────────────────────────────────────────
info "[3/6] Creating site 'control-plane'..."
SITE=$(api_call POST "/api/v1/sites" '{"site_id":"control-plane","name":"Control Plane"}')
[ -n "${SITE}" ] && success "Site created." || info "Site already exists (skipped)."

# ── 4. Create zone ────────────────────────────────────────────────────────────
info "[4/6] Creating zone 'vps' under 'control-plane'..."
ZONE=$(api_call POST "/api/v1/zones" '{"zone_id":"vps","name":"VPS","site_id":"control-plane"}')
[ -n "${ZONE}" ] && success "Zone created." || info "Zone already exists (skipped)."

# ── 5. Create device ──────────────────────────────────────────────────────────
info "[5/6] Creating device 'vps-control-plane'..."
DEVICE=$(api_call POST "/api/v1/devices" \
    '{"device_id":"vps-control-plane","role":"control-plane-vps","hostname":"vps-control-plane","site_id":"control-plane","zone_id":"vps","ring":0}')
[ -n "${DEVICE}" ] && success "Device created." || info "Device already exists (skipped)."

# ── 6. Issue device token ─────────────────────────────────────────────────────
info "[6/6] Issuing a new device token for 'vps-control-plane'..."
TOKEN_RESPONSE=$(api_call POST "/api/v1/devices/vps-control-plane/token")
DEVICE_TOKEN=$(echo "${TOKEN_RESPONSE}" | jq -r '.device_token // empty')
[ -n "${DEVICE_TOKEN}" ] || error "Token issuance failed — no device_token in response: ${TOKEN_RESPONSE}"
success "Token issued (shown once, saved to secrets.env)."

# ── 7. Write token to secrets.env ─────────────────────────────────────────────
update_secret "VPS_DEVICE_TOKEN" "${DEVICE_TOKEN}"

echo ""
echo -e "${GRN}Done!  VPS device enrolled successfully.${NC}"
echo "  Device ID : vps-control-plane"
echo "  Site      : control-plane"
echo "  Zone      : vps"
echo "  Token     : written to secrets.env as VPS_DEVICE_TOKEN"
echo ""
echo "Next steps:"
echo "  cd FleetBits-platform/docker"
echo "  docker compose --env-file ../secrets.env up -d --build vps-device"
echo "  docker compose --env-file ../secrets.env logs vps-device -f --tail 30"
echo ""
