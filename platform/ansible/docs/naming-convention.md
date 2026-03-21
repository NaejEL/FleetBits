# Device naming convention
# ─────────────────────────────────────────────────────────────────────────────
# All fleet devices follow this naming pattern:
#
#   {role}-{site}-{zone}-{seq}
#
#   role   → hardware/function role (see table below)
#   site   → site slug (paris, lyon, nice, lab, …)
#   zone   → zone slug (zone-1, zone-2, shared, …) — "shared" for multi-zone servers
#   seq    → two-digit zero-padded integer: 01, 02, 03, …
#
# Examples:
#   rpi-paris-zone1-01     Raspberry Pi, Paris site, Zone 1, first device
#   rpi-paris-zone1-02     Raspberry Pi, Paris site, Zone 1, second device
#   mini-paris-shared-01   Mini-PC, Paris site, shared server (spans all zones)
#   rpi-lab-zone1-01       Lab/dev RPi
#
# Role prefixes:
# ─────────────────────────────────────────────────────────────────────────────
# | Prefix  | Hardware                     | Typical use                     |
# |---------|------------------------------|---------------------------------|
# | rpi     | Raspberry Pi (any model)     | Puzzle controllers, AV devices  |
# | mini    | Mini-PC / NUC / x86 SBC      | Zone orchestrator, MQTT broker  |
# | vm      | Virtual machine              | Cloud/lab testing               |
# ─────────────────────────────────────────────────────────────────────────────
#
# Zone slugs:
# ─────────────────────────────────────────────────────────────────────────────
# | Slug      | Meaning                                                       |
# |-----------|---------------------------------------------------------------|
# | zone-1    | First zone at a site                                          |
# | zone-2    | Second zone, etc.                                             |
# | shared    | Device shared across multiple zones (e.g. MQTT broker server) |
# ─────────────────────────────────────────────────────────────────────────────
#
# Constraints:
#   - Lowercase letters, digits, and hyphens only (DNS hostname safe)
#   - No underscores, no uppercase, no dots
#   - Maximum 63 characters total (DNS label limit)
#   - Must be unique across the entire fleet
#   - Assigned once — never changed (it becomes the device's identity in Fleet API,
#     Headscale, Prometheus labels, and Loki log streams)
#
# New site checklist:
#   □ Choose site slug (3-6 chars, lowercase): e.g. "nice"
#   □ Update inventories/prod/site_{slug}.yml
#   □ Update group_vars/site_{slug}/vars.yml
#   □ Register site in Fleet API: POST /api/v1/sites
#   □ Add quiet_hours block to alertmanager.yml for site timezone
