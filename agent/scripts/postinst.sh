#!/bin/bash
# scripts/postinst.sh
# ─────────────────────────────────────────────────────────────────────────────
# Debian postinst script — runs after package installation or upgrade.
# Called by dpkg with one argument: "configure" (install) or "upgrade" <old-version>.
#
# On install:
#   - Creates runtime config directories for Alloy and Vector
#   - Regenerates the active runtime config if device-identity.conf already exists
#   - Does NOT enable or start services (Ansible does that via 'systemctl enable --now')
#
# On upgrade:
#   - Regenerates the active runtime config from the preserved identity file
#   - Restarts fleet-agent to apply the new runtime binary + config
# ─────────────────────────────────────────────────────────────────────────────

set -e

ACTION="${1:-configure}"
IDENTITY_FILE="/etc/fleet/device-identity.conf"

mkdir -p /etc/alloy /etc/vector /var/lib/fleet-agent/vector
chmod 755 /etc/alloy /etc/vector /var/lib/fleet-agent /var/lib/fleet-agent/vector || true

# Make scripts executable (in case fpm didn't preserve permissions)
chmod +x /usr/lib/fleet-agent/generate-config.sh
chmod +x /usr/lib/fleet-agent/heartbeat.sh
chmod +x /usr/lib/fleet-agent/firstboot.sh
chmod +x /usr/lib/fleet-agent/run-telemetry.sh

case "${ACTION}" in
  configure)
    if [ -f "${IDENTITY_FILE}" ]; then
      chmod 600 "${IDENTITY_FILE}" || true
      echo "fleet-agent: regenerating runtime config from existing identity..."
      /usr/lib/fleet-agent/generate-config.sh || {
        echo "WARNING: generate-config.sh failed — run it manually after deploying ${IDENTITY_FILE}" >&2
      }
    else
      echo "fleet-agent: ${IDENTITY_FILE} not found."
      echo "  Deploy it via Ansible (fleet_agent role) before starting fleet-agent."
      echo "  Template: /etc/fleet/device-identity.conf.example"
    fi

    if command -v systemctl >/dev/null 2>&1 && systemctl is-system-running --quiet 2>/dev/null; then
      systemctl daemon-reload || true
    fi
    ;;

  upgrade)
    echo "fleet-agent: upgrading from ${2:-unknown} to new version"

    if [ -f "${IDENTITY_FILE}" ]; then
      chmod 600 "${IDENTITY_FILE}" || true
      echo "fleet-agent: regenerating runtime config..."
      /usr/lib/fleet-agent/generate-config.sh || {
        echo "WARNING: generate-config.sh failed during upgrade" >&2
      }
    fi

    if command -v systemctl >/dev/null 2>&1 && systemctl is-system-running --quiet 2>/dev/null; then
      systemctl daemon-reload || true
      if systemctl is-active --quiet fleet-agent 2>/dev/null; then
        echo "fleet-agent: restarting service after upgrade..."
        systemctl restart fleet-agent || true
      fi
    fi
    ;;
esac

exit 0
