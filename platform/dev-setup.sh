#!/usr/bin/env bash
# ============================================================
# FleetBits — Local Dev Setup (Linux / macOS)
#
# Usage:
#   ./dev-setup.sh                 # first run
#   ./dev-setup.sh --force         # overwrite existing secrets
#   ./dev-setup.sh --no-build      # write config files only, skip compose up
#
# Requires: bash ≥4, docker (with compose plugin), openssl
# ============================================================

set -euo pipefail

# ── Flags ─────────────────────────────────────────────────────────────────────

FORCE=0
NO_BUILD=0

for arg in "$@"; do
    case "$arg" in
        --force)    FORCE=1 ;;
        --no-build) NO_BUILD=1 ;;
        *)
            echo "Unknown argument: $arg"
            echo "Usage: $0 [--force] [--no-build]"
            exit 1
            ;;
    esac
done

# ── Colour helpers ────────────────────────────────────────────────────────────

CYAN='\033[0;36m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
WHITE='\033[1;37m'
RESET='\033[0m'

step()  { echo -e "\n${CYAN}==> $*${RESET}"; }
ok()    { echo -e "    ${GREEN}✓ $*${RESET}"; }
warn()  { echo -e "    ${YELLOW}~ $*${RESET}"; }
err()   { echo -e "${RED}ERROR: $*${RESET}" >&2; exit 1; }

# ── Helpers ───────────────────────────────────────────────────────────────────

rand_base64() { openssl rand -base64 "$1"; }   # $1 = byte count
rand_hex()    { openssl rand -hex   "$1"; }    # $1 = byte count

# Read a KEY=VALUE from an existing env file; returns empty string if not found.
read_env() {
    local file="$1" key="$2"
    grep -m1 "^${key}=" "$file" 2>/dev/null | cut -d'=' -f2- || true
}


# ── Locate repos ──────────────────────────────────────────────────────────────

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DOCKER_DIR="$REPO_ROOT/docker"
API_REPO="$(dirname "$REPO_ROOT")/FleetBits-api"
UI_REPO="$(dirname "$REPO_ROOT")/FleetBits-ui"
SECRETS_ENV="$REPO_ROOT/secrets.env"
OVERRIDE="$DOCKER_DIR/docker-compose.override.yml"
OVERRIDE_EXMP="$DOCKER_DIR/docker-compose.override.yml.example"

echo ""
echo -e "${WHITE}FleetBits — Local Dev Setup${RESET}"
echo "Platform root : $REPO_ROOT"
echo "Docker dir    : $DOCKER_DIR"
echo "API repo      : $API_REPO"

# ── Prerequisites ─────────────────────────────────────────────────────────────

step "Checking prerequisites"

command -v openssl &>/dev/null || err "openssl not found. Install it and retry."
ok "openssl found"

if ! docker info &>/dev/null; then
    err "Docker is not running or not installed."
fi
ok "Docker is running"

[[ -d "$DOCKER_DIR" ]] || err "docker/ directory not found at $DOCKER_DIR"
ok "docker/ directory found"

API_AVAILABLE=0
if [[ -d "$API_REPO" ]]; then
    ok "FleetBits-api repo found"
    API_AVAILABLE=1
else
    echo -e "    ${YELLOW}WARNING: FleetBits-api repo not found at $API_REPO${RESET}"
    echo    "             The fleet-api container will NOT be built from source."
    echo    "             Clone it as a sibling to FleetBits-platform and re-run."
fi

UI_AVAILABLE=0
if [[ -d "$UI_REPO" ]]; then
    ok "FleetBits-ui repo found"
    UI_AVAILABLE=1
else
    echo -e "    ${YELLOW}WARNING: FleetBits-ui repo not found at $UI_REPO${RESET}"
fi

# ── Generate secrets ──────────────────────────────────────────────────────────

step "Generating secrets"

POSTGRES_PASSWORD=$(rand_base64 18)
FLEET_DB_PASSWORD=$(rand_base64 18)
SEMAPHORE_DB_PASSWORD=$(rand_base64 18)
GRAFANA_ADMIN_PASSWORD=$(rand_base64 18)
GRAFANA_PROXY_SECRET=$(rand_base64 32)
SEMAPHORE_API_KEY=$(rand_hex 32)
FLEET_JWT_SECRET=$(rand_base64 48)
MQTT_BROKER_PASSWORD=$(rand_base64 24)
FLEET_UI_SECRET_KEY=$(rand_base64 48)
SEMAPHORE_ACCESS_KEY_ENCRYPTION_KEY=$(rand_base64 48)
SEMAPHORE_ADMIN_PASSWORD=$(rand_base64 18)
OPERATOR_PASSWORD=$(rand_base64 16)
VPS_DEVICE_TOKEN=""
APTLY_GPG_KEY_ID=""
ALERTMANAGER_BASIC_AUTH_USER="admin"

ALERTMANAGER_PASSWORD=$(rand_base64 16)
ALERTMANAGER_BASIC_AUTH_HASH=$(docker run --rm caddy:2 caddy hash-password --plaintext "$ALERTMANAGER_PASSWORD" 2>/dev/null || true)
if [[ -z "$ALERTMANAGER_BASIC_AUTH_HASH" ]]; then
    warn "Could not generate Alertmanager bcrypt hash — using placeholder"
    ALERTMANAGER_BASIC_AUTH_HASH="CHANGE_ME_BCRYPT_HASH"
fi
if [[ "$ALERTMANAGER_BASIC_AUTH_HASH" == *'$'* && "$ALERTMANAGER_BASIC_AUTH_HASH" != *'$$'* ]]; then
    ALERTMANAGER_BASIC_AUTH_HASH="${ALERTMANAGER_BASIC_AUTH_HASH//$/$$}"
fi

# If secrets.env already exists (and no --force), preserve all existing values.
# Any key not yet in the file picks up its freshly-generated default automatically.
if [[ -f "$SECRETS_ENV" && "$FORCE" -eq 0 ]]; then
    warn "secrets.env already exists — preserving existing values (pass --force to regenerate)"
    v=$(read_env "$SECRETS_ENV" POSTGRES_PASSWORD);                   [[ -n "$v" ]] && POSTGRES_PASSWORD="$v"
    v=$(read_env "$SECRETS_ENV" FLEET_DB_PASSWORD);                   [[ -n "$v" ]] && FLEET_DB_PASSWORD="$v"
    v=$(read_env "$SECRETS_ENV" SEMAPHORE_DB_PASSWORD);               [[ -n "$v" ]] && SEMAPHORE_DB_PASSWORD="$v"
    v=$(read_env "$SECRETS_ENV" GRAFANA_ADMIN_PASSWORD);              [[ -n "$v" ]] && GRAFANA_ADMIN_PASSWORD="$v"
    v=$(read_env "$SECRETS_ENV" GRAFANA_PROXY_SECRET);               [[ -n "$v" ]] && GRAFANA_PROXY_SECRET="$v"
    v=$(read_env "$SECRETS_ENV" SEMAPHORE_API_KEY);                   [[ -n "$v" ]] && SEMAPHORE_API_KEY="$v"
    v=$(read_env "$SECRETS_ENV" FLEET_JWT_SECRET);                    [[ -n "$v" ]] && FLEET_JWT_SECRET="$v"
    v=$(read_env "$SECRETS_ENV" MQTT_BROKER_PASSWORD);                [[ -n "$v" ]] && MQTT_BROKER_PASSWORD="$v"
    v=$(read_env "$SECRETS_ENV" FLEET_UI_SECRET_KEY);                 [[ -n "$v" ]] && FLEET_UI_SECRET_KEY="$v"
    v=$(read_env "$SECRETS_ENV" SEMAPHORE_ACCESS_KEY_ENCRYPTION_KEY); [[ -n "$v" ]] && SEMAPHORE_ACCESS_KEY_ENCRYPTION_KEY="$v"
    v=$(read_env "$SECRETS_ENV" SEMAPHORE_ADMIN_PASSWORD);            [[ -n "$v" ]] && SEMAPHORE_ADMIN_PASSWORD="$v"
    v=$(read_env "$SECRETS_ENV" OPERATOR_PASSWORD);                   [[ -n "$v" ]] && OPERATOR_PASSWORD="$v"
    v=$(read_env "$SECRETS_ENV" ALERTMANAGER_BASIC_AUTH_USER);        [[ -n "$v" ]] && ALERTMANAGER_BASIC_AUTH_USER="$v"
    v=$(read_env "$SECRETS_ENV" ALERTMANAGER_BASIC_AUTH_HASH);        [[ -n "$v" ]] && ALERTMANAGER_BASIC_AUTH_HASH="$v"
    v=$(read_env "$SECRETS_ENV" VPS_DEVICE_TOKEN);                    VPS_DEVICE_TOKEN="$v"
    v=$(read_env "$SECRETS_ENV" APTLY_GPG_KEY_ID);                    APTLY_GPG_KEY_ID="$v"
    if [[ "$ALERTMANAGER_BASIC_AUTH_HASH" == *'$'* && "$ALERTMANAGER_BASIC_AUTH_HASH" != *'$$'* ]]; then
        ALERTMANAGER_BASIC_AUTH_HASH="${ALERTMANAGER_BASIC_AUTH_HASH//$/$$}"
    fi
fi

ok "Secrets ready"

# ── secrets.env ───────────────────────────────────────────────────────────────

step "Writing secrets.env"
cat > "$SECRETS_ENV" <<EOF
# ============================================================
# FleetBits Platform — LOCAL DEV secrets
# Generated by dev-setup.sh — DO NOT COMMIT
# ============================================================

FLEET_DOMAIN=localhost

POSTGRES_PASSWORD=${POSTGRES_PASSWORD}
FLEET_DB_PASSWORD=${FLEET_DB_PASSWORD}
SEMAPHORE_DB_PASSWORD=${SEMAPHORE_DB_PASSWORD}

GRAFANA_ADMIN_PASSWORD=${GRAFANA_ADMIN_PASSWORD}
GRAFANA_PROXY_SECRET=${GRAFANA_PROXY_SECRET}

SEMAPHORE_API_KEY=${SEMAPHORE_API_KEY}

FLEET_JWT_SECRET=${FLEET_JWT_SECRET}
MQTT_BROKER_USERNAME=fleet_exporter
MQTT_BROKER_PASSWORD=${MQTT_BROKER_PASSWORD}
FLEET_UI_SECRET_KEY=${FLEET_UI_SECRET_KEY}
SEMAPHORE_ACCESS_KEY_ENCRYPTION_KEY=${SEMAPHORE_ACCESS_KEY_ENCRYPTION_KEY}
SEMAPHORE_ADMIN_PASSWORD=${SEMAPHORE_ADMIN_PASSWORD}

FLEETBITS_API_IMAGE=fleetbits-api:dev
FLEETBITS_UI_IMAGE=fleetbits-ui:dev

FLEET_API_INTERNAL_URL=http://fleet-api:8000
GRAFANA_INTERNAL_URL=http://grafana:3000
GRAFANA_PROXY_SECRET=${GRAFANA_PROXY_SECRET}

APTLY_GPG_KEY_ID=${APTLY_GPG_KEY_ID}

FLEET_ENV=development
ALLOW_ALL_ORIGINS=true
FLASK_DEBUG=true

OPERATOR_USERNAME=admin
OPERATOR_PASSWORD=${OPERATOR_PASSWORD}

ALERTMANAGER_BASIC_AUTH_USER=${ALERTMANAGER_BASIC_AUTH_USER}
ALERTMANAGER_BASIC_AUTH_HASH=${ALERTMANAGER_BASIC_AUTH_HASH}

VPS_DEVICE_TOKEN=${VPS_DEVICE_TOKEN}
EOF
ok "secrets.env written  (login: admin / ${OPERATOR_PASSWORD})"

# ── docker-compose.override.yml ───────────────────────────────────────────────

step "Preparing docker/docker-compose.override.yml"

if [[ ! -f "$OVERRIDE" || "$FORCE" -eq 1 ]]; then
    [[ -f "$OVERRIDE_EXMP" ]] || { echo -e "${RED}ERROR: $OVERRIDE_EXMP not found.${RESET}" >&2; exit 1; }
    cp "$OVERRIDE_EXMP" "$OVERRIDE"
    ok "Copied from .example"
else
    warn "docker-compose.override.yml already exists — not changed (pass --force to reset)"
fi

# ── Write FleetBits-api/.env ──────────────────────────────────────────────────

if [[ "$API_AVAILABLE" -eq 1 ]]; then
    step "Writing FleetBits-api/.env"
    API_ENV="$API_REPO/.env"
    if [[ -f "$API_ENV" && "$FORCE" -eq 0 ]]; then
        warn "FleetBits-api/.env already exists — not changed (pass --force to overwrite)"
    else
        cat > "$API_ENV" <<EOF
# FleetBits API — local dev
# Generated by dev-setup.sh — DO NOT COMMIT

DATABASE_URL=postgresql+asyncpg://fleet:${FLEET_DB_PASSWORD}@localhost:5432/fleet

SEMAPHORE_URL=http://localhost:3001
SEMAPHORE_API_KEY=${SEMAPHORE_API_KEY}
SEMAPHORE_PROJECT_ID=1
SEMAPHORE_DEPLOY_TEMPLATE_ID=1
SEMAPHORE_ROLLBACK_TEMPLATE_ID=2
SEMAPHORE_RESTART_TEMPLATE_ID=3
SEMAPHORE_DIAGNOSTICS_TEMPLATE_ID=4
SEMAPHORE_LOGS_TEMPLATE_ID=5

FLEET_JWT_SECRET=${FLEET_JWT_SECRET}
FLEET_JWT_ALGORITHM=HS256
FLEET_JWT_EXPIRE_MINUTES=480

PROMETHEUS_URL=http://localhost:9090
LOKI_URL=http://localhost:3100
ALERTMANAGER_URL=http://localhost:9093

FLEET_ENV=development
ALLOW_ALL_ORIGINS=true
FLEET_API_URL=http://localhost:8000

OPERATOR_USERNAME=admin
OPERATOR_PASSWORD=${OPERATOR_PASSWORD}

GRAFANA_INTERNAL_URL=http://localhost:3000
GRAFANA_ADMIN_PASSWORD=${GRAFANA_ADMIN_PASSWORD}
GRAFANA_PROXY_SECRET=${GRAFANA_PROXY_SECRET}
EOF
        ok "FleetBits-api/.env written"
    fi
fi

# ── Write FleetBits-ui/.env ───────────────────────────────────────────────────

if [[ "$UI_AVAILABLE" -eq 1 ]]; then
    step "Writing FleetBits-ui/.env"
    UI_ENV="$UI_REPO/.env"
    if [[ -f "$UI_ENV" && "$FORCE" -eq 0 ]]; then
        warn "FleetBits-ui/.env already exists — not changed (pass --force to overwrite)"
    else
        cat > "$UI_ENV" <<EOF
# FleetBits UI — local dev
# Generated by dev-setup.sh — DO NOT COMMIT

SECRET_KEY=${FLEET_UI_SECRET_KEY}
FLEET_API_URL=http://localhost:8000
# Dev: Grafana iframes go through Caddy /grafana/ so forward_auth is enforced.
GRAFANA_URL=http://localhost/grafana
SEMAPHORE_URL=http://localhost/semaphore
FLEET_DOMAIN=localhost
FLEET_ENV=development
FLASK_DEBUG=true
EOF
        ok "FleetBits-ui/.env written"
    fi
fi

# ── docker compose up ─────────────────────────────────────────────────────────

if [[ "$NO_BUILD" -eq 1 ]]; then
    echo -e "\n${YELLOW}Skipping docker compose (--no-build passed).${RESET}"
else
    step "Starting stack  (docker compose up --build -d)"
    echo "    This may take a few minutes on first run while images are pulled/built."
    (cd "$DOCKER_DIR" && docker compose --env-file ../secrets.env up --build -d)
    ok "Stack is up"

    # ── Seed demo data ─────────────────────────────────────────────────────────
    step "Seeding demo data"
    token=""
    echo "    Waiting for API to be ready ..."
    for i in $(seq 1 30); do
        login_resp=$(curl -sS -X POST "http://localhost:8000/api/v1/auth/login" \
            -H "Content-Type: application/json" \
            -d "{\"username\":\"admin\",\"password\":\"${OPERATOR_PASSWORD}\"}" 2>/dev/null || true)
        token=$(printf '%s' "$login_resp" | sed -n 's/.*"access_token"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p')
        [[ -n "$token" ]] && break
        sleep 2
    done
    if [[ -n "$token" ]]; then
        api_seed() {
            local endpoint="$1" payload="$2" label="$3" code
            code=$(curl -sS -o /dev/null -w "%{http_code}" -X POST "http://localhost:8000${endpoint}" \
                -H "Content-Type: application/json" \
                -H "Authorization: Bearer ${token}" \
                -d "$payload" 2>/dev/null || echo "000")
            if [[ "$code" == "200" || "$code" == "201" || "$code" == "409" ]]; then
                echo "    + ${label}"
            else
                warn "seed ${label} — HTTP ${code}"
            fi
        }
        api_seed "/api/v1/profiles" '{"profile_id":"default-kiosk","name":"Default Kiosk Profile","baseline_stack":{}}' "profile/default-kiosk"
        ok "Demo data seeded"
    else
        warn "API did not become ready in time — seed skipped (run manually)"
    fi
fi

# ── Summary ───────────────────────────────────────────────────────────────────

echo ""
echo -e "${WHITE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}"
echo -e "${GREEN} FleetBits dev stack ready${RESET}"
echo -e "${WHITE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}"
echo ""
echo "  Fleet UI        http://localhost             (admin / ${OPERATOR_PASSWORD})"
echo "  Fleet API docs  http://localhost:8000/docs"
echo "  Grafana         http://localhost/grafana      (login not needed — FleetBits SSO)"
echo "  Semaphore       http://localhost/semaphore"
echo "  Prometheus      http://localhost:9090"
echo ""
echo -e "${YELLOW}  Credentials are saved in secrets.env — keep it private.${RESET}"
echo ""
echo "  To stop:   cd docker && docker compose --env-file ../secrets.env down"
echo "  To reset:  ./dev-setup.sh --force"
echo ""
