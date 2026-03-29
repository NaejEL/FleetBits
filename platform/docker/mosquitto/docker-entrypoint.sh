#!/bin/sh
set -eu

if [ -z "${MQTT_BROKER_USERNAME:-}" ] || [ -z "${MQTT_BROKER_PASSWORD:-}" ]; then
  echo "ERROR: MQTT_BROKER_USERNAME and MQTT_BROKER_PASSWORD must be set" >&2
  exit 1
fi

PASSWD_FILE="/mosquitto/config/passwd"
ACL_FILE="/mosquitto/config/acl"
API_URL="${FLEET_API_URL:-http://api:8000}"
SYNC_INTERVAL="${MQTT_ACL_SYNC_INTERVAL:-300}"  # seconds between ACL syncs

# Generate broker password file from runtime secrets.
# Remove existing passwd file first — mosquitto_passwd -c refuses to overwrite on some builds.
rm -f "$PASSWD_FILE"
mosquitto_passwd -b -c "$PASSWD_FILE" "$MQTT_BROKER_USERNAME" "$MQTT_BROKER_PASSWORD"

# Function to generate initial minimal ACL (exporter only)
generate_minimal_acl() {
  cat > "$ACL_FILE" <<EOF
user ${MQTT_BROKER_USERNAME}
topic read \$SYS/#
EOF
}

# Function to sync per-device ACL from API
sync_device_acl() {
  if ! command -v curl >/dev/null 2>&1; then
    echo "[mosquitto-acl] WARNING: curl not available, skipping API sync" >&2
    return 1
  fi
  
  # Try to fetch ACL from API with operator credentials (if available)
  if [ -z "${FLEET_OPERATOR_TOKEN:-}" ]; then
    echo "[mosquitto-acl] INFO: FLEET_OPERATOR_TOKEN not set, skipping device ACL sync" >&2
    return 1
  fi
  
  TEMP_ACL="$(mktemp)"
  trap "rm -f '$TEMP_ACL'" EXIT
  
    if ! curl -sf -H "Authorization: Bearer $FLEET_OPERATOR_TOKEN" \
      "$API_URL/api/v1/devices/mqtt/acl" -o "$TEMP_ACL" 2>/dev/null; then
    echo "[mosquitto-acl] WARNING: Failed to fetch ACL from API" >&2
    return 1
  fi
  
  # Parse JSON response and rebuild ACL file
  # Expected format: {"device_<id>": ["topic1", "topic2"], "fleet_exporter": ["$SYS/#"]}
  {
    echo "user ${MQTT_BROKER_USERNAME}"
    echo "topic read \$SYS/#"
    echo ""
    
    # Simple JSON parsing: extract device entries and generate ACL rules
    python3 -c "
import json, sys
try:
  with open('$TEMP_ACL') as f:
    acl = json.load(f)
  for username, topics in acl.items():
    if username != '${MQTT_BROKER_USERNAME}':
      print(f'user {username}')
      for topic in topics:
        print(f'topic readwrite {topic}')
      print()
except Exception as e:
  print(f'ERROR: {e}', file=sys.stderr)
  sys.exit(1)
" 2>/dev/null && mv "$TEMP_ACL" "$ACL_FILE" && echo "[mosquitto-acl] Synced device ACL from API" && return 0 || true
  }
  
  return 1
}

# Generate initial ACL
generate_minimal_acl
chown mosquitto:mosquitto "$PASSWD_FILE" "$ACL_FILE"
chmod 600 "$PASSWD_FILE"
chmod 640 "$ACL_FILE"

# Start Mosquitto in background
(
  exec /docker-entrypoint.sh "$@"
) &
MOSQUITTO_PID=$!

# Background ACL sync loop (only if API credentials available)
if [ -n "${FLEET_OPERATOR_TOKEN:-}" ]; then
  (
    while true; do
      sleep "$SYNC_INTERVAL"
      if sync_device_acl; then
        # Reload ACL in running Mosquitto
        mosquitto_ctrl reload > /dev/null 2>&1 || true
      fi
    done
  ) &
  ACL_SYNC_PID=$!
  trap "kill $ACL_SYNC_PID 2>/dev/null || true" EXIT
fi

wait $MOSQUITTO_PID
