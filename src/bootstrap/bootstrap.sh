#!/usr/bin/env bash
# ServerStick Bootstrap — Zero-touch Debian provisioning
# Usage: curl -fsSL https://get.serverstick.com | bash
#   or:  bash bootstrap.sh [--starter-key KEY] [--device-name NAME]
#
# This script:
# 1. Installs Docker + dependencies
# 2. Deploys Pi Agent (FastAPI + Svelte dashboard)
# 3. Starts 8 self-hosted services via Docker Compose
# 4. Connects to Pangolin tunnel for remote access
set -euo pipefail

# ─── Config ──────────────────────────────────────────────────────────
SS_DIR="/etc/serverstick"
SS_DATA="/var/lib/serverstick/data"
SS_OPT="/opt/serverstick"
AGENT_PORT="${SERVERSTICK_PORT:-8080}"
STARTER_KEY="${SERVERSTICK_STARTER_KEY:-}"
DEVICE_NAME="${SERVERSTICK_DEVICE_NAME:-}"
REPO="${SERVERSTICK_REPO:-https://github.com/coding-crying/serverstick.git}"
BRANCH="${SERVERSTICK_BRANCH:-main}"
NEW_VERSION="0.3.0"  # Update when releasing

# ─── Colors ──────────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log()   { echo -e "${BLUE}[serverstick]${NC} $*"; }
warn()  { echo -e "${YELLOW}[serverstick]${NC} ⚠ $*"; }
error() { echo -e "${RED}[serverstick]${NC} ✗ $*" >&2; exit 1; }
ok()    { echo -e "${GREEN}[serverstick]${NC} ✓ $*"; }

# ─── Parse args ───────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
  case "$1" in
    --starter-key)  STARTER_KEY="$2"; shift 2 ;;
    --device-name)  DEVICE_NAME="$2"; shift 2 ;;
    --branch)       BRANCH="$2"; shift 2 ;;
    --help)         echo "Usage: bootstrap.sh [--starter-key KEY] [--device-name NAME] [--branch BRANCH]"; exit 0 ;;
    *)              warn "Unknown option: $1"; shift ;;
  esac
done

# ─── Preflight checks ────────────────────────────────────────────────
log "ServerStick Bootstrap v${NEW_VERSION}"
log "═══════════════════════════════════════"

[[ $EUID -ne 0 ]] && error "This script must be run as root (sudo)"

# Detect OS
if [[ -f /etc/os-release ]]; then
  source /etc/os-release
  OS_ID="${ID:-unknown}"
  OS_VERSION="${VERSION_ID:-unknown}"
  log "Detected OS: ${PRETTY_NAME}"
else
  error "Cannot detect OS — /etc/os-release not found"
fi

# ─── Step 1: System dependencies ─────────────────────────────────────
log "Step 1/7: Installing system dependencies..."

apt_get_update() {
  if ! command -v apt-get &>/dev/null; then
    error "Only Debian/Ubuntu is supported. Detected: ${OS_ID}"
  fi
  export DEBIAN_FRONTEND=noninteractive
  apt-get update -qq
  apt-get install -y -qq curl git python3 python3-venv python3-pip >/dev/null 2>&1
}

apt_get_update
ok "System packages installed"

# ─── Step 2: Docker ───────────────────────────────────────────────────
log "Step 2/7: Setting up Docker..."

if command -v docker &>/dev/null && docker compose version &>/dev/null; then
  ok "Docker already installed"
else
  log "Installing Docker..."
  curl -fsSL https://get.docker.com | sh >/dev/null 2>&1
  systemctl enable docker
  systemctl start docker
  ok "Docker installed"
fi

# ─── Step 3: Get ServerStick code ─────────────────────────────────────
log "Step 3/7: Downloading ServerStick..."

if [[ -d "${SS_OPT}/.git" ]]; then
  log "Updating existing installation..."
  cd "${SS_OPT}"
  git fetch origin "${BRANCH}" && git reset --hard "origin/${BRANCH}" 2>/dev/null || true
else
  log "Cloning repository..."
  git clone --branch "${BRANCH}" --depth 1 "${REPO}" "${SS_OPT}" 2>/dev/null || {
    # Fallback: curl tarball if git fails
    warn "Git clone failed, trying tarball..."
    mkdir -p "${SS_OPT}"
    curl -fsSL "${REPO}/archive/refs/heads/${BRANCH}.tar.gz" | tar xz -C "${SS_OPT}" --strip-components=1
  }
fi
ok "ServerStick code ready at ${SS_OPT}"

# ─── Step 4: Pi Agent setup ───────────────────────────────────────────
log "Step 4/7: Setting up Pi Agent..."

cd "${SS_OPT}/src/agent"

# Create Python venv
if [[ ! -d .venv ]]; then
  python3 -m venv .venv
fi
.venv/bin/pip install -q -r requirements.txt 2>/dev/null || {
  warn "pip install encountered issues, trying with system packages..."
  .venv/bin/pip install fastapi "uvicorn[standard]" httpx pydantic pyyaml
}

# Build Svelte dashboard
if [[ -d dashboard ]]; then
  log "Building Svelte dashboard..."
  cd dashboard
  if command -v npm &>/dev/null; then
    npm install --silent 2>/dev/null
    npm run build 2>/dev/null
    ok "Dashboard built"
  else
    warn "npm not found — installing Node.js..."
    curl -fsSL https://deb.nodesource.com/setup_22.x | bash - >/dev/null 2>&1
    apt-get install -y -qq nodejs >/dev/null 2>&1
    npm install --silent 2>/dev/null
    npm run build 2>/dev/null
    ok "Dashboard built"
  fi
  cd ..
fi

# Install systemd service
cp "${SS_OPT}/src/config/serverstick-agent.service" /etc/systemd/system/
systemctl daemon-reload
systemctl enable serverstick-agent

# Write starter key if provided
mkdir -p "${SS_DIR}"
if [[ -n "${STARTER_KEY}" ]]; then
  echo "${STARTER_KEY}" > "${SS_DIR}/starter-key"
  chmod 600 "${SS_DIR}/starter-key"
  ok "Starter key written"
fi

# Write agent env file
cat > "${SS_DIR}/agent.env" << EOF
SERVERSTICK_DIR=${SS_DIR}
SERVERSTICK_DATA=${SS_DATA}
SERVERSTICK_PORT=${AGENT_PORT}
SERVERSTICK_STARTER_KEY=${STARTER_KEY}
SERVERSTICK_DEVICE_ID=
EOF
chmod 600 "${SS_DIR}/agent.env"

# Start the agent
systemctl restart serverstick-agent
sleep 2
if systemctl is-active --quiet serverstick-agent; then
  ok "Pi Agent running on port ${AGENT_PORT}"
else
  warn "Pi Agent may need manual start: systemctl start serverstick-agent"
fi

# ─── Step 5: Docker services ───────────────────────────────────────────
log "Step 5/7: Starting Docker services..."

mkdir -p "${SS_DATA}"/{homepage,stirling-pdf/trainingData,stirling-pdf/extraConfigs,privatebin,uptime-kuma}

# Copy docker-compose.yml to the expected location
mkdir -p "${SS_DIR}/services"
cp "${SS_OPT}/src/services/docker-compose.yml" "${SS_DIR}/services/"

# Template the device name in compose
if [[ -n "${DEVICE_NAME}" ]]; then
  sed -i "s/{{DEVICE_NAME}}/${DEVICE_NAME}/g" "${SS_DIR}/services/docker-compose.yml"
fi

cd "${SS_DIR}/services"
docker compose up -d 2>&1 | tail -5
ok "Docker services starting"

# ─── Step 6: Newt tunnel ──────────────────────────────────────────────
log "Step 6/7: Setting up Pangolin tunnel..."

if [[ -f "${SS_DIR}/pangolin.env" ]]; then
  source "${SS_DIR}/pangolin.env"
fi

if [[ -n "${NEWT_ID:-}" ]] && [[ -n "${NEWT_SECRET:-}" ]]; then
  # Install Newt binary
  if ! command -v newt &>/dev/null; then
    log "Installing Newt..."
    curl -fsSL https://github.com/pangolin-oracle/newt/releases/latest/download/newt-linux-amd64 \
      -o /usr/local/bin/newt 2>/dev/null
    chmod +x /usr/local/bin/newt
    ok "Newt installed"
  fi

# Write pangolin env for systemd service
  mkdir -p "${SS_DIR}"
cat > "${SS_DIR}/pangolin.env" << ENVPANG
# Pangolin tunnel configuration (generated by ServerStick bootstrap)
NEWT_ID=${NEWT_ID}
NEWT_SECRET=${NEWT_SECRET}
NEWT_ENDPOINT=${NEWT_ENDPOINT:-gerbil.pangolin.net:50120}
ENVPANG
  chmod 600 "${SS_DIR}/pangolin.env"

  # Install and start systemd service
  cp "${SS_OPT}/src/config/serverstick-newt.service" /etc/systemd/system/
  systemctl daemon-reload
  systemctl enable serverstick-newt
  systemctl restart serverstick-newt
  sleep 2
  if systemctl is-active --quiet serverstick-newt; then
    ok "Pangolin tunnel connected"
  else
    warn "Pangolin tunnel starting — check: journalctl -u serverstick-newt"
  fi
else
  warn "No Newt credentials found — tunnel not configured"
  warn "Use the web UI at http://$(hostname -I | awk '{print $1}'):${AGENT_PORT} to set up tunneling"
fi

# ─── Step 7: Done ─────────────────────────────────────────────────────
log "Step 7/7: Finalizing..."

LAN_IP=$(hostname -I 2>/dev/null | awk '{print $1}' || echo "unknown")

echo ""
echo -e "${GREEN}═══════════════════════════════════════════════${NC}"
echo -e "${GREEN}  🖥️  ServerStick is ready!${NC}"
echo -e "${GREEN}═══════════════════════════════════════════════${NC}"
echo ""
echo -e "  Dashboard:  ${BLUE}http://${LAN_IP}:${AGENT_PORT}${NC}"
echo ""
if [[ -n "${DEVICE_NAME}" ]]; then
  echo -e "  Domain:      ${BLUE}dash.${DEVICE_NAME}.serverstick.com${NC}"
fi
echo ""
echo -e "  Next steps:"
if [[ -z "${DEVICE_NAME}" ]]; then
  echo -e "  ${YELLOW}1. Open the dashboard and complete setup${NC}"
fi
echo -e "  ${YELLOW}2. Configure remote access via Pangolin tunnel${NC}"
echo -e "  ${YELLOW}3. Add services from the dashboard${NC}"
echo ""