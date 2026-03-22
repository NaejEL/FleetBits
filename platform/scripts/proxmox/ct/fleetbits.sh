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
UNPRIVILEGED="0"        # 0 = privileged (required for Docker — runc needs CAP_NET_ADMIN in new netns)
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
info "You need DNS A records (or a wildcard) pointing to your PUBLIC external IP."
info "If you use DynDNS, use the same IP your DynDNS hostname currently resolves to."
info "Examples:"
info "  fleet.yourdomain.com          A  <your-public-ip>"
info "  *.fleet.yourdomain.com        A  <your-public-ip>   (wildcard, recommended)"
echo ""
FLEET_DOMAIN=""
while [[ -z "${FLEET_DOMAIN}" ]]; do
  read -rp "Fleet base domain (e.g. fleet.yourdomain.com): " FLEET_DOMAIN
  if [[ -z "${FLEET_DOMAIN}" ]]; then
    warn "Domain is required and cannot be left blank."
  fi
done

echo ""
warn "Container will be created as PRIVILEGED (required for Docker inside LXC)."
warn "Root inside this CT maps to root on the host — only run trusted workloads inside it."
warn "Alternative: use a full VM if you need stronger isolation."
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

# ── AppArmor: allow runc to write sysctls inside new network namespaces ─────────────
# Proxmox's default LXC AppArmor profile blocks /proc/self/fd/N re-opens that
# runc (≥1.1.8) uses when applying per-netns sysctls (e.g. ip_unprivileged_port_start).
# Even a privileged LXC is affected. Unconfining AppArmor for this CT is the
# standard fix used by TTeck scripts and the Proxmox community.
LXC_CONF="/etc/pve/lxc/${CTID}.conf"
if ! grep -q "lxc.apparmor.profile" "${LXC_CONF}"; then
    echo "lxc.apparmor.profile: unconfined" >> "${LXC_CONF}"
    success "AppArmor set to unconfined for CT${CTID} (required for Docker)."
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

# ── Get container IP ──────────────────────────────────────────────────────────
CT_IP=$(pct exec "${CTID}" -- hostname -I | awk '{print $1}')

# ── Detect public IP (for DNS instructions and certbot) ───────────────────────
info "Detecting your public IP address..."
PUBLIC_IP=$(curl -s --max-time 8 https://api.ipify.org 2>/dev/null \
         || curl -s --max-time 8 https://ifconfig.me 2>/dev/null \
         || true)
if [[ -n "${PUBLIC_IP}" ]]; then
    info "Detected public IP: ${PUBLIC_IP}"
    read -rp "Is this correct? Press Enter to confirm, or type the correct value: " IP_OVERRIDE
    [[ -n "${IP_OVERRIDE}" ]] && PUBLIC_IP="${IP_OVERRIDE}"
else
    warn "Could not auto-detect public IP."
    read -rp "Enter your public/external IP address (the one your domain resolves to): " PUBLIC_IP
    PUBLIC_IP="${PUBLIC_IP:-<your-public-ip>}"
fi

# ── Reverse proxy setup ────────────────────────────────────────────────────────
echo ""
info "Reverse proxy configuration"
info "FleetBits runs on HTTP port 80 inside CT${CTID} (${CT_IP})."
echo ""
echo "  How will you route external traffic to FleetBits?"
echo "    A) Nginx Proxy Manager (NPM) already running in another LXC  [recommended]"
echo "    B) Install nginx + certbot directly on THIS Proxmox host"
echo "    C) Skip — I will configure the reverse proxy myself later"
echo ""
read -rp "  Choice [A/b/c]: " PROXY_CHOICE
PROXY_CHOICE="${PROXY_CHOICE:-a}"

PROXY_MODE=""
NGINX_CONFIGURED=false

case "${PROXY_CHOICE,,}" in

  a)
    PROXY_MODE="npm"
    echo ""
    info "Nginx Proxy Manager selected."
    echo ""
    info "Add the following Proxy Hosts in your NPM dashboard:"
    info "  Dashboard → Proxy Hosts → Add Proxy Host"
    echo ""
    printf "  %-44s  %-16s  %s\n" "Domain Name" "Forward Host" "Port"
    printf "  %-44s  %-16s  %s\n" "────────────────────────────────────────────" "────────────────" "────"
    printf "  %-44s  %-16s  %s\n"  "${FLEET_DOMAIN}"              "${CT_IP}" "80"
    printf "  %-44s  %-16s  %s\n"  "api.${FLEET_DOMAIN}"          "${CT_IP}" "80"
    printf "  %-44s  %-16s  %s\n"  "repo.${FLEET_DOMAIN}"         "${CT_IP}" "80"
    printf "  %-44s  %-16s  %s\n"  "headscale.${FLEET_DOMAIN}"    "${CT_IP}" "80"
    printf "  %-44s  %-16s  %s  ← Enable Websockets\n" "grafana.${FLEET_DOMAIN}"   "${CT_IP}" "80"
    printf "  %-44s  %-16s  %s  ← Enable Websockets\n" "semaphore.${FLEET_DOMAIN}" "${CT_IP}" "80"
    printf "  %-44s  %-16s  %s\n"  "metrics.${FLEET_DOMAIN}"      "${CT_IP}" "80"
    printf "  %-44s  %-16s  %s\n"  "logs.${FLEET_DOMAIN}"         "${CT_IP}" "80"
    echo ""
    info "For SSL: open each Proxy Host → SSL tab → Request a new SSL certificate"
    info "         (Let's Encrypt) and enable Force SSL."
    echo ""
    # Optional: auto-configure via NPM API
    read -rp "Auto-add all proxy hosts via NPM API now? [y/N]: " NPM_API_YN
    if [[ "${NPM_API_YN,,}" == "y" ]]; then
        read -rp "NPM URL (e.g. http://192.168.1.50:81): " NPM_BASE_URL
        NPM_BASE_URL="${NPM_BASE_URL%/}"
        read -rp "NPM admin email: " NPM_EMAIL
        read -rsp "NPM admin password: " NPM_PASS; echo ""
        NPM_TOKEN=$(curl -sf -X POST "${NPM_BASE_URL}/api/tokens" \
            -H 'Content-Type: application/json' \
            -d "{\"identity\":\"${NPM_EMAIL}\",\"secret\":\"${NPM_PASS}\"}" \
            | grep -oP '"token"\s*:\s*"\K[^"]+' || true)
        if [[ -z "${NPM_TOKEN}" ]]; then
            warn "Could not authenticate to NPM (check URL and credentials)."
            warn "Proxy hosts were NOT created — add them manually in the NPM UI."
        else
            success "Authenticated to NPM."
            npm_add_proxy_host() {
                local domain="$1" ws="${2:-false}"
                local payload result
                payload="{\"domain_names\":[\"${domain}\"],\"forward_scheme\":\"http\",\"forward_host\":\"${CT_IP}\",\"forward_port\":80,\"block_exploits\":true,\"allow_websocket_upgrade\":${ws},\"ssl_forced\":false,\"certificate_id\":0}"
                result=$(curl -sf -X POST "${NPM_BASE_URL}/api/nginx/proxy-hosts" \
                    -H "Authorization: Bearer ${NPM_TOKEN}" \
                    -H 'Content-Type: application/json' \
                    -d "${payload}" 2>&1)
                if echo "${result}" | grep -q '"id"'; then
                    success "  Created: ${domain}"
                else
                    warn "  Failed: ${domain}  (may already exist — check NPM UI)"
                fi
            }
            npm_add_proxy_host "${FLEET_DOMAIN}"
            npm_add_proxy_host "api.${FLEET_DOMAIN}"
            npm_add_proxy_host "repo.${FLEET_DOMAIN}"
            npm_add_proxy_host "headscale.${FLEET_DOMAIN}"
            npm_add_proxy_host "grafana.${FLEET_DOMAIN}"   "true"
            npm_add_proxy_host "semaphore.${FLEET_DOMAIN}" "true"
            npm_add_proxy_host "metrics.${FLEET_DOMAIN}"
            npm_add_proxy_host "logs.${FLEET_DOMAIN}"
            echo ""
            info "Proxy hosts created in NPM (HTTP only — SSL not yet configured)."
            info "In NPM: open each host → SSL tab → Request certificate (Let's Encrypt)."
            NGINX_CONFIGURED=true
        fi
    fi
    ;;

  b)
    PROXY_MODE="nginx"
    echo ""
    if ! command -v nginx &>/dev/null || ! command -v certbot &>/dev/null; then
        info "Installing nginx and certbot on this Proxmox host..."
        apt-get update -qq
        apt-get install -y -qq nginx certbot python3-certbot-nginx
        success "nginx and certbot installed."
    else
        info "nginx and certbot are already installed."
    fi
    NGINX_CONF_URL="https://raw.githubusercontent.com/NaejEL/FleetBits-platform/main/scripts/proxmox/nginx-example.conf"
    NGINX_DEST="/etc/nginx/sites-available/fleetbits"
    info "Downloading nginx config template..."
    curl -fsSL "${NGINX_CONF_URL}" -o "${NGINX_DEST}.tmp" \
        || error "Failed to download nginx config from GitHub."
    sed "s/CT_IP/${CT_IP}/g; s/fleet\.yourdomain\.com/${FLEET_DOMAIN}/g" \
        "${NGINX_DEST}.tmp" > "${NGINX_DEST}"
    rm -f "${NGINX_DEST}.tmp"
    success "nginx config written → ${NGINX_DEST}"
    [ ! -L /etc/nginx/sites-enabled/fleetbits ] \
        && ln -s "${NGINX_DEST}" /etc/nginx/sites-enabled/fleetbits || true
    [ -L /etc/nginx/sites-enabled/default ] \
        && rm /etc/nginx/sites-enabled/default || true
    nginx -t || error "nginx config validation failed. Check ${NGINX_DEST}"
    systemctl enable nginx --quiet
    systemctl restart nginx
    success "nginx is running (HTTP only — TLS not yet configured)."
    echo ""
    warn "Before running certbot, confirm these DNS records are live and point to ${PUBLIC_IP}:"
    warn "  ${FLEET_DOMAIN}           A  ${PUBLIC_IP}"
    warn "  *.${FLEET_DOMAIN}         A  ${PUBLIC_IP}   (wildcard — recommended)"
    echo ""
    read -rp "Obtain Let's Encrypt TLS certificates now? [y/N]: " RUN_CERTBOT
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
            || warn "certbot did not complete — DNS may not have propagated yet. Re-run: certbot --nginx -d ${FLEET_DOMAIN} ..."
    else
        info "Run certbot later once DNS has propagated:"
        info "  certbot --nginx \\"
        info "    -d ${FLEET_DOMAIN} \\"
        info "    -d grafana.${FLEET_DOMAIN} -d api.${FLEET_DOMAIN} \\"
        info "    -d repo.${FLEET_DOMAIN} -d headscale.${FLEET_DOMAIN} \\"
        info "    -d semaphore.${FLEET_DOMAIN} -d metrics.${FLEET_DOMAIN} \\"
        info "    -d logs.${FLEET_DOMAIN}"
    fi
    NGINX_CONFIGURED=true
    ;;

  *)
    PROXY_MODE="manual"
    info "Skipping reverse proxy setup — configure it manually after install."
    ;;
esac

echo ""
echo -e "${GRN}╔══════════════════════════════════════════════════╗${NC}"
echo -e "${GRN}║           FleetBits installed successfully!       ║${NC}"
echo -e "${GRN}╚══════════════════════════════════════════════════╝${NC}"
echo ""
echo -e "  Container:    CT${CTID} (${HOSTNAME})"
echo -e "  Container IP: ${CT_IP}"
echo -e "  Domain:       ${FLEET_DOMAIN}"
echo -e "  Public IP:    ${PUBLIC_IP}"
echo ""
echo -e "${YLW}Next steps:${NC}"
echo ""
echo -e "  1. Ensure DNS A records point to your public IP (${PUBLIC_IP}):"
echo -e "     ${FLEET_DOMAIN}           A  ${PUBLIC_IP}"
echo -e "     *.${FLEET_DOMAIN}         A  ${PUBLIC_IP}   (wildcard, recommended)"
echo -e "     If you use DynDNS, point these to the same IP as your DynDNS hostname."
echo ""
if [ "${PROXY_MODE}" = "npm" ] && [ "${NGINX_CONFIGURED}" = false ]; then
    echo -e "  2. In NPM: add the proxy hosts listed above, then enable SSL per host."
    echo -e "     Dashboard → Proxy Hosts → Add Proxy Host → SSL tab → Request certificate"
elif [ "${PROXY_MODE}" = "npm" ] && [ "${NGINX_CONFIGURED}" = true ]; then
    echo -e "  2. NPM proxy hosts created. ✓"
    echo -e "     → In NPM: open each host → SSL tab → Request new certificate (Let's Encrypt)."
elif [ "${NGINX_CONFIGURED}" = true ]; then
    echo -e "  2. nginx is configured and running. ✓"
    echo -e "     Config: /etc/nginx/sites-available/fleetbits"
else
    echo -e "  2. Configure your reverse proxy to forward all 8 domains to ${CT_IP}:80:"
    echo -e "     ${FLEET_DOMAIN}, api.${FLEET_DOMAIN}, repo.${FLEET_DOMAIN},"
    echo -e "     headscale.${FLEET_DOMAIN}, grafana.${FLEET_DOMAIN} (WS),"
    echo -e "     semaphore.${FLEET_DOMAIN} (WS), metrics.${FLEET_DOMAIN}, logs.${FLEET_DOMAIN}"
fi
echo ""
echo -e "  3. Access the platform after proxy + TLS are configured:"
echo -e "     https://${FLEET_DOMAIN}              — Fleet UI"
echo -e "     https://grafana.${FLEET_DOMAIN}      — Grafana"
echo -e "     https://api.${FLEET_DOMAIN}          — Fleet API"
echo ""
echo -e "  4. Log into Fleet UI with the admin credentials from the install output."
echo -e "     (or check /opt/fleetbits/credentials.txt on CT${CTID})"
echo ""
