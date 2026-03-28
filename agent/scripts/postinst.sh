#!/bin/bash
# scripts/postinst.sh
# ─────────────────────────────────────────────────────────────────────────────
# Debian postinst script — runs after package installation or upgrade.
# Called by dpkg with one argument: "configure" (install) or "upgrade" <old-version>.
#
# On install:
#   - Creates /etc/alloy/ directory
#   - Regenerates Alloy config if device-identity.conf already exists
#   - Does NOT enable or start services (Ansible does that via 'systemctl enable --now')
#
# On upgrade:
#   - Regenerates /etc/alloy/config.alloy from the (preserved) device-identity.conf
#   - Restarts fleet-agent to apply the new Alloy binary + config
# ─────────────────────────────────────────────────────────────────────────────

set -e

ACTION="${1:-configure}"
IDENTITY_FILE="/etc/fleet/device-identity.conf"

# Ensure the Alloy config directory exists in all cases
mkdir -p /etc/alloy
chmod 755 /etc/alloy

# Make scripts executable (in case fpm didn't preserve permissions)
chmod +x /usr/lib/fleet-agent/generate-config.sh
chmod +x /usr/lib/fleet-agent/heartbeat.sh
chmod +x /usr/lib/fleet-agent/firstboot.sh

case "${ACTION}" in
  configure)
    if [ -f "${IDENTITY_FILE}" ]; then
      chmod 600 "${IDENTITY_FILE}" || true
      echo "fleet-agent: regenerating /etc/alloy/config.alloy from existing identity..."
      /usr/lib/fleet-agent/generate-config.sh || {
        echo "WARNING: generate-config.sh failed — run it manually after deploying ${IDENTITY_FILE}" >&2
      }
    else
      echo "fleet-agent: ${IDENTITY_FILE} not found."
      echo "  Deploy it via Ansible (fleet_agent role) before starting fleet-agent."
      echo "  Template: /etc/fleet/device-identity.conf.example"
    fi

    # Reload systemd to pick up new unit files
    if command -v systemctl >/dev/null 2>&1 && systemctl is-system-running --quiet 2>/dev/null; then
      systemctl daemon-reload || true
    fi
    ;;

  upgrade)
    echo "fleet-agent: upgrading from ${2:-unknown} to new version"

    if [ -f "${IDENTITY_FILE}" ]; then
      chmod 600 "${IDENTITY_FILE}" || true
      echo "fleet-agent: regenerating /etc/alloy/config.alloy..."
      /usr/lib/fleet-agent/generate-config.sh || {
        echo "WARNING: generate-config.sh failed during upgrade" >&2
      }
    fi

    if command -v systemctl >/dev/null 2>&1 && systemctl is-system-running --quiet 2>/dev/null; then
      systemctl daemon-reload || true
      # Restart only if the service is currently active
      if systemctl is-active --quiet fleet-agent 2>/dev/null; then
        echo "fleet-agent: restarting service after upgrade..."
        systemctl restart fleet-agent || true
      fi
    fi
    ;;
esac

exit 0
