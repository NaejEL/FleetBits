#!/bin/bash
# aptly/entrypoint.sh
# Initialises aptly repos on first start, then launches the aptly API server.
set -euo pipefail

APTLY_CONF="/root/.aptly.conf"

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
        if ! aptly publish show "${repo}" bookworm > /dev/null 2>&1; then
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

init_repos

echo "[aptly] Starting API server on :8080"
exec aptly api serve -listen=":8080" -no-lock
