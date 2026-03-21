#!/usr/bin/env bash
# =============================================================================
# FleetBits — Proxmox LXC Installer
# =============================================================================
# Run this script on your Proxmox VE host shell:
#
#   bash -c "$(curl -fsSL https://raw.githubusercontent.com/NaejEL/FleetBits-platform/main/scripts/proxmox/ct/fleetbits.sh)"
#
# What this script does:
#   1. Downloads a Debian 12 LXC template (if not already present)
#   2. Creates an LXC container with nested Docker support
#   3. Configures resources (CPU, RAM, disk) — interactive with defaults
#   4. Starts the container
#   5. Runs scripts/proxmox/install/fleetbits-install.sh inside the container
#
# Requirements:
#   - Proxmox VE 7.x or 8.x
#   - Root on the PVE host
#   - Internet access from the PVE host (to download template + Docker images)
#
# After installation, configure your nginx reverse proxy using:
#   scripts/proxmox/nginx-example.conf
# =============================================================================

set -euo pipefail

# ── Colour helpers ─────────────────────────────────────────────────────────────
RED='\033[0;31m'; GRN='\033[0;32m'; YLW='\033[1;33m'; CYN='\033[0;36m'; NC='\033[0m'
info()    { echo -e "${CYN}[INFO]${NC}  $*"; }
success() { echo -e "${GRN}[OK]${NC}    $*"; }
warn()    { echo -e "${YLW}[WARN]${NC}  $*"; }
error()   { echo -e "${RED}[ERROR]${NC} $*" >&2; exit 1; }

# ── Preflight checks ───────────────────────────────────────────────────────────
[ "$(id -u)" -eq 0 ] || error "Must run as root on the Proxmox host."
command -v pct  &>/dev/null || error "pct not found. Run this on a Proxmox VE host."
command -v pvem &>/dev/null || true  # pvem optional

echo ""
echo -e "${CYN}╔══════════════════════════════════════════════════╗${NC}"
echo -e "${CYN}║          FleetBits Platform — LXC Installer      ║${NC}"
echo -e "${CYN}╚══════════════════════════════════════════════════╝${NC}"
echo ""

# ── Defaults ───────────────────────────────────────────────────────────────────
CTID="${1:-$(pvesh get /cluster/nextid 2>/dev/null || echo 200)}"
HOSTNAME="fleetbits"
DISK_SIZE="32"          # GB
CPU_CORES="4"
RAM_MB="4096"
SWAP_MB="512"
BRIDGE="vmbr0"
STORAGE="local-lvm"     # where to create the container rootfs
UNPRIVILEGED="1"        # 1 = unprivileged (safer), 0 = privileged (needed for raw Docker)
TEMPLATE_STORAGE="local"
DEBIAN_TEMPLATE="debian-12-standard_12.7-1_amd64.tar.zst"

# ── Interactive configuration ──────────────────────────────────────────────────
echo "Press Enter to accept defaults shown in [brackets]."
echo ""

read -rp "Container ID     [${CTID}]: "     INPUT; CTID="${INPUT:-$CTID}"
read -rp "Hostname         [${HOSTNAME}]: " INPUT; HOSTNAME="${INPUT:-$HOSTNAME}"
read -rp "Disk size (GB)   [${DISK_SIZE}]: "INPUT; DISK_SIZE="${INPUT:-$DISK_SIZE}"
read -rp "CPU cores        [${CPU_CORES}]: "INPUT; CPU_CORES="${INPUT:-$CPU_CORES}"
read -rp "RAM (MB)         [${RAM_MB}]: "   INPUT; RAM_MB="${INPUT:-$RAM_MB}"
read -rp "Network bridge   [${BRIDGE}]: "   INPUT; BRIDGE="${INPUT:-$BRIDGE}"
read -rp "Storage pool     [${STORAGE}]: "  INPUT; STORAGE="${INPUT:-$STORAGE}"

echo ""
info "FleetBits domain configuration"
info "You need a DNS record (or wildcard) pointing to this Proxmox node's IP."
info "Examples:"
info "  fleet.yourdomain.com          → <proxmox-ip>"
info "  *.fleet.yourdomain.com        → <proxmox-ip>  (wildcard, recommended)"
echo ""
FLEET_DOMAIN=""
while [[ -z "${FLEET_DOMAIN}" ]]; do
  read -rp "Fleet base domain (e.g. fleet.yourdomain.com): " FLEET_DOMAIN
  if [[ -z "${FLEET_DOMAIN}" ]]; then
    warn "Domain is required and cannot be left blank."
  fi
done

echo ""
warn "Container will be created with Docker nesting enabled (features: nesting=1,keyctl=1)."
warn "This requires the container to be UNPRIVILEGED — Docker runs inside a user namespace."
echo ""
read -rp "Confirm creation of CT ${CTID} (${HOSTNAME}) on ${STORAGE}? [y/N]: " CONFIRM
[[ "${CONFIRM,,}" == "y" ]] || { info "Aborted."; exit 0; }

# ── Download Debian 12 template if needed ──────────────────────────────────────
TEMPLATE_PATH="/var/lib/vz/template/cache/${DEBIAN_TEMPLATE}"
if [ ! -f "${TEMPLATE_PATH}" ]; then
    info "Downloading Debian 12 standard template..."
    pveam update
    pveam download "${TEMPLATE_STORAGE}" "${DEBIAN_TEMPLATE}" \
        || error "Failed to download template. Check: pveam available --section system"
    success "Template downloaded."
else
    info "Template already present: ${DEBIAN_TEMPLATE}"
fi

# ── Create the container ───────────────────────────────────────────────────────
info "Creating LXC container CT${CTID}..."

pct create "${CTID}" "${TEMPLATE_STORAGE}:vztmpl/${DEBIAN_TEMPLATE}" \
    --hostname    "${HOSTNAME}" \
    --cores       "${CPU_CORES}" \
    --memory      "${RAM_MB}" \
    --swap        "${SWAP_MB}" \
    --rootfs      "${STORAGE}:${DISK_SIZE}" \
    --net0        "name=eth0,bridge=${BRIDGE},ip=dhcp,firewall=1" \
    --ostype      "debian" \
    --unprivileged "${UNPRIVILEGED}" \
    --features    "nesting=1,keyctl=1" \
    --start       0 \
    --onboot      1

success "Container CT${CTID} created."

# ── Apply sysctl settings required by Docker inside unprivileged LXC ──────────
# Docker on recent kernels needs net.ipv4.ip_unprivileged_port_start to be set
# at the LXC level; Docker itself cannot write it from inside the container.
info "Configuring sysctl for Docker compatibility..."
pct set "${CTID}" --features "nesting=1,keyctl=1" 2>/dev/null || true

# Write lxc.sysctl directly into the LXC config file (pct set has no --lxc flag)
LXC_CONF="/etc/pve/lxc/${CTID}.conf"
if ! grep -q "lxc.sysctl.net.ipv4.ip_unprivileged_port_start" "${LXC_CONF}" 2>/dev/null; then
    echo "lxc.sysctl.net.ipv4.ip_unprivileged_port_start = 0" >> "${LXC_CONF}"
    success "sysctl net.ipv4.ip_unprivileged_port_start = 0 added to CT${CTID} config."
fi

# ── Start the container ────────────────────────────────────────────────────────
info "Starting CT${CTID}..."
pct start "${CTID}"
sleep 5

# Wait for networking
info "Waiting for container networking..."
for i in $(seq 1 30); do
    if pct exec "${CTID}" -- ping -c1 8.8.8.8 &>/dev/null; then
        success "Container has network connectivity."
        break
    fi
    [ "${i}" -lt 30 ] || error "Container has no network after 30s. Check bridge ${BRIDGE}."
    sleep 1
done

# ── Run the install script inside the container ────────────────────────────────
info "Transferring install script to CT${CTID}..."
INSTALL_SCRIPT_URL="https://raw.githubusercontent.com/NaejEL/FleetBits-platform/main/scripts/proxmox/install/fleetbits-install.sh"

pct exec "${CTID}" -- bash -c "
    apt-get update -qq && apt-get install -y -qq curl
    curl -fsSL '${INSTALL_SCRIPT_URL}' -o /root/fleetbits-install.sh
    chmod +x /root/fleetbits-install.sh
    FLEET_DOMAIN='${FLEET_DOMAIN}' bash /root/fleetbits-install.sh
"

# ── Get container IP for nginx config ─────────────────────────────────────────
CT_IP=$(pct exec "${CTID}" -- hostname -I | awk '{print $1}')
PROXMOX_IP=$(hostname -I | awk '{print $1}')

# ── Optional: nginx reverse proxy auto-configuration ──────────────────────────
echo ""
info "Nginx reverse proxy setup"
info "FleetBits runs on port 80 inside CT${CTID} (${CT_IP})."
info "An nginx reverse proxy on this Proxmox host routes your domain to it."
echo ""
NGINX_CONFIGURED=false
read -rp "Configure nginx reverse proxy on this Proxmox host automatically? [y/N]: " SETUP_NGINX
if [[ "${SETUP_NGINX,,}" == "y" ]]; then
    info "Detected Proxmox host IP: ${PROXMOX_IP}"

    # Install nginx + certbot if not already present
    if ! command -v nginx &>/dev/null || ! command -v certbot &>/dev/null; then
        info "Installing nginx and certbot..."
        apt-get update -qq
        apt-get install -y -qq nginx certbot python3-certbot-nginx
        success "nginx and certbot installed."
    else
        info "nginx and certbot are already installed."
    fi

    # Download the config template and substitute placeholders
    NGINX_CONF_URL="https://raw.githubusercontent.com/NaejEL/FleetBits-platform/main/scripts/proxmox/nginx-example.conf"
    NGINX_DEST="/etc/nginx/sites-available/fleetbits"
    info "Downloading nginx config template..."
    curl -fsSL "${NGINX_CONF_URL}" -o "${NGINX_DEST}.tmp" \
        || error "Failed to download nginx config from GitHub."

    # Replace CT_IP placeholder and the example domain with the real values
    sed "s/CT_IP/${CT_IP}/g; s/fleet\.yourdomain\.com/${FLEET_DOMAIN}/g" \
        "${NGINX_DEST}.tmp" > "${NGINX_DEST}"
    rm -f "${NGINX_DEST}.tmp"
    success "nginx config written → ${NGINX_DEST}"

    # Enable the site
    if [ ! -L /etc/nginx/sites-enabled/fleetbits ]; then
        ln -s "${NGINX_DEST}" /etc/nginx/sites-enabled/fleetbits
    fi

    # Disable the default placeholder site if present (avoids port 80 conflict)
    [ -L /etc/nginx/sites-enabled/default ] && rm /etc/nginx/sites-enabled/default || true

    # Validate and start nginx (HTTP-only until certbot adds TLS)
    nginx -t || error "nginx config validation failed. Check ${NGINX_DEST}"
    systemctl enable nginx --quiet
    systemctl restart nginx
    success "nginx is running (HTTP only until TLS certificates are obtained)."

    # Offer to run certbot
    echo ""
    warn "Before running certbot, confirm your DNS records point to ${PROXMOX_IP}:"
    warn "  ${FLEET_DOMAIN}           A  ${PROXMOX_IP}"
    warn "  *.${FLEET_DOMAIN}         A  ${PROXMOX_IP}   (wildcard — recommended)"
    warn "  or individual subdomains: grafana / api / repo / headscale / semaphore / metrics / logs"
    echo ""
    read -rp "Obtain Let's Encrypt TLS certificates now with certbot? [y/N]: " RUN_CERTBOT
    if [[ "${RUN_CERTBOT,,}" == "y" ]]; then
        certbot --nginx \
            -d "${FLEET_DOMAIN}" \
            -d "grafana.${FLEET_DOMAIN}" \
            -d "api.${FLEET_DOMAIN}" \
            -d "repo.${FLEET_DOMAIN}" \
            -d "headscale.${FLEET_DOMAIN}" \
            -d "semaphore.${FLEET_DOMAIN}" \
            -d "metrics.${FLEET_DOMAIN}" \
            -d "logs.${FLEET_DOMAIN}" \
            && success "TLS certificates obtained — platform is fully operational!" \
            || warn "certbot did not complete. DNS may not be propagated yet. Re-run later: certbot --nginx -d ${FLEET_DOMAIN} ..."
    else
        info "Skipping certbot. Run it later once DNS is ready:"
        info "  certbot --nginx \\"
        info "    -d ${FLEET_DOMAIN} \\"
        info "    -d grafana.${FLEET_DOMAIN} -d api.${FLEET_DOMAIN} \\"
        info "    -d repo.${FLEET_DOMAIN} -d headscale.${FLEET_DOMAIN} \\"
        info "    -d semaphore.${FLEET_DOMAIN} -d metrics.${FLEET_DOMAIN} \\"
        info "    -d logs.${FLEET_DOMAIN}"
    fi
    NGINX_CONFIGURED=true
fi

echo ""
echo -e "${GRN}╔══════════════════════════════════════════════════╗${NC}"
echo -e "${GRN}║           FleetBits installed successfully!       ║${NC}"
echo -e "${GRN}╚══════════════════════════════════════════════════╝${NC}"
echo ""
echo -e "  Container:    CT${CTID} (${HOSTNAME})"
echo -e "  Container IP: ${CT_IP}"
echo -e "  Domain:       ${FLEET_DOMAIN}"
echo ""
echo -e "${YLW}Next steps:${NC}"
echo ""
echo -e "  1. Add DNS records pointing to this Proxmox host (${PROXMOX_IP}):"
echo -e "     ${FLEET_DOMAIN}           A  ${PROXMOX_IP}"
echo -e "     *.${FLEET_DOMAIN}         A  ${PROXMOX_IP}   (wildcard, recommended)"
echo ""
if [ "${NGINX_CONFIGURED}" = false ]; then
    echo -e "  2. Configure nginx reverse proxy on this Proxmox host:"
    echo -e "     apt install nginx certbot python3-certbot-nginx"
    echo -e "     # Download and deploy the config template:"
    echo -e "     curl -fsSL https://raw.githubusercontent.com/NaejEL/FleetBits-platform/main/scripts/proxmox/nginx-example.conf \\"
    echo -e "       | sed \"s/CT_IP/${CT_IP}/g; s/fleet\\.yourdomain\\.com/${FLEET_DOMAIN}/g\" \\"
    echo -e "       > /etc/nginx/sites-available/fleetbits"
    echo -e "     ln -s /etc/nginx/sites-available/fleetbits /etc/nginx/sites-enabled/"
    echo -e "     nginx -t && systemctl restart nginx"
    echo -e "     certbot --nginx -d ${FLEET_DOMAIN} -d grafana.${FLEET_DOMAIN} ..."
    echo ""
    echo -e "  3. Access the platform after nginx + TLS are configured:"
else
    echo -e "  2. nginx is configured and running. ✓"
    echo -e "     Config: /etc/nginx/sites-available/fleetbits"
    echo ""
    echo -e "  3. Access the platform:"
fi
echo -e "     https://${FLEET_DOMAIN}              — Fleet UI"
echo -e "     https://grafana.${FLEET_DOMAIN}      — Grafana"
echo -e "     https://api.${FLEET_DOMAIN}          — Fleet API"
echo ""
echo -e "  4. Log into Fleet UI with the admin credentials from the install output."
echo -e "     (or check /opt/fleetbits/credentials.txt on CT${CTID})"
echo ""
