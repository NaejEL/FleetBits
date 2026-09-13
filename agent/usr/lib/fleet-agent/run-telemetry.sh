#!/bin/bash
# /usr/lib/fleet-agent/run-telemetry.sh
# ─────────────────────────────────────────────────────────────────────────────
# Launch the telemetry collector that is bundled for this package architecture.
# - amd64/arm64: Grafana Alloy
# - armhf:       Vector
# ─────────────────────────────────────────────────────────────────────────────

set -euo pipefail

if [ -x /usr/bin/alloy ]; then
  exec /usr/bin/alloy run /etc/alloy/config.alloy --disable-reporting
fi

if [ -x /usr/bin/vector ]; then
  exec /usr/bin/vector --config /etc/vector/vector.yaml
fi

echo "ERROR: no supported telemetry runtime found (/usr/bin/alloy or /usr/bin/vector)" >&2
exit 1
