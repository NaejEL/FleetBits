# host_vars/
# ─────────────────────────────────────────────────────────────────────────────
# Per-device variable overrides.  Most devices have NO file here — they
# inherit everything from group_vars (all → rpi/mini_pc → site_<slug>).
#
# Create a file here only when a device genuinely differs from its group defaults:
#   - Different log level for debugging
#   - ENABLE_MQTT_EXPORTER=true for the one RPi running Mosquitto
#   - Non-standard shared_zones list for the site's mini-PC
#
# Filename must match the inventory hostname exactly, e.g.:
#   host_vars/rpi-paris-zone1-02.yml
#
# Example content:
# ─────────────────────────────────────────────────────────────────────────────
# # host_vars/rpi-paris-zone1-02.yml
# log_level: debug              # temporary for troubleshooting
# enable_mqtt_exporter: true    # this device also runs Mosquitto
# ─────────────────────────────────────────────────────────────────────────────
#
# The ansible_host line is written here automatically by bootstrap_device.yml
# (headscale_enroll role) when a device is first enrolled.  It records the
# stable Headscale mesh IP.  It should then be copied to inventories/prod/
# and this file's ansible_host entry removed (to keep a single source of truth).
