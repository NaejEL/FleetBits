#!/bin/bash
# aptly/entrypoint.sh
# Initialises aptly repos on first start, then launches the aptly API server.
set -euo pipefail

# Route all output (incl. stderr) to stdout so `docker logs aptly-api` shows everything.
exec 2>&1

APTLY_CONF="/root/.aptly.conf"
KEY_SYNC_DIR="/root/.aptly/security"
AUTHORIZED_KEYS_FILE="${KEY_SYNC_DIR}/device-authorized-keys"
AUTHORIZED_KEYS_JSON="${KEY_SYNC_DIR}/device-authorized-keys.json"

FLEET_API_URL="${FLEET_API_URL:-http://fleet-api:8000}"
OPERATOR_USERNAME="${OPERATOR_USERNAME:-admin}"
OPERATOR_PASSWORD="${OPERATOR_PASSWORD:-}"
REPO_KEY_SYNC_INTERVAL_SECONDS="${REPO_KEY_SYNC_INTERVAL_SECONDS:-300}"

init_repos() {
    echo "[aptly] Checking repositories..."

    for repo in dev staging prod; do
        if ! aptly repo show "${repo}" > /dev/null 2>&1; then
            echo "[aptly] Creating repo: ${repo}"
            aptly repo create \
                -comment="FleetBits ${repo} packages" \
                -component=main \
                -distribution=bookworm \
                "${repo}"
        else
            echo "[aptly] Repo '${repo}' already exists."
        fi
    done

    # Publish each repo to its own prefix (<name>/bookworm) to avoid collisions.
    # Plain string prefix is fully supported by all aptly versions; no named endpoints needed.
    for repo in dev staging prod; do
        if ! aptly publish show bookworm "${repo}" > /dev/null 2>&1; then
            echo "[aptly] Publishing repo: ${repo}"
            # On first run without a GPG key, use --skip-signing for local dev.
            # In production, import the GPG key first (see README).
            aptly publish repo \
                -skip-signing \
                -distribution=bookworm \
                "${repo}" "${repo}"
        fi
    done

    echo "[aptly] Repositories ready."
}

sync_repo_authorized_keys_once() {
    mkdir -p "${KEY_SYNC_DIR}"

    if [ -z "${OPERATOR_PASSWORD}" ]; then
        echo "[aptly] repo-key-sync: OPERATOR_PASSWORD is empty; skipping key sync"
        return 0
    fi

    local login_payload token_response token
    login_payload=$(jq -nc --arg username "${OPERATOR_USERNAME}" --arg password "${OPERATOR_PASSWORD}" \
        '{username: $username, password: $password}')

    token_response=$(curl -fsS \
        --max-time 10 \
        -X POST "${FLEET_API_URL}/api/v1/auth/login" \
        -H "Content-Type: application/json" \
        -d "${login_payload}" 2>/dev/null || true)

    token=$(printf '%s' "${token_response}" | jq -r '.access_token // empty' 2>/dev/null || true)
    if [ -z "${token}" ]; then
        echo "[aptly] repo-key-sync: failed to authenticate to Fleet API"
        return 0
    fi

    local keys_response
    keys_response=$(curl -fsS \
        --max-time 15 \
        -H "Authorization: Bearer ${token}" \
        "${FLEET_API_URL}/api/v1/packages/repo-authorized-keys" 2>/dev/null || true)

    if [ -z "${keys_response}" ]; then
        echo "[aptly] repo-key-sync: no response from /repo-authorized-keys"
        return 0
    fi

    printf '%s\n' "${keys_response}" > "${AUTHORIZED_KEYS_JSON}.tmp"
    jq -r '.authorized_keys // ""' "${AUTHORIZED_KEYS_JSON}.tmp" > "${AUTHORIZED_KEYS_FILE}.tmp"

    mv "${AUTHORIZED_KEYS_JSON}.tmp" "${AUTHORIZED_KEYS_JSON}"
    mv "${AUTHORIZED_KEYS_FILE}.tmp" "${AUTHORIZED_KEYS_FILE}"

    local key_count
    key_count=$(jq -r '.count // 0' "${AUTHORIZED_KEYS_JSON}" 2>/dev/null || echo 0)
    echo "[aptly] repo-key-sync: synchronized ${key_count} authorized device key(s)"
}

sync_repo_authorized_keys_loop() {
    while true; do
        sync_repo_authorized_keys_once || true
        sleep "${REPO_KEY_SYNC_INTERVAL_SECONDS}"
    done
}

init_repos
sync_repo_authorized_keys_loop &

echo "[aptly] Starting API server on :8080"
exec aptly api serve -listen=":8080" -no-lock
