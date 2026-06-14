#!/usr/bin/env bash
# ServerStick Bootstrap — One-command self-hosting
# Usage: curl -fsSL https://get.serverstick.com | sudo bash
#
# What this does:
# 1. Installs system deps (curl, git, Docker)
# 2. Installs Newt (Pangolin tunnel client)
# 3. Installs NemoClaw with Hermes agent (sandboxed AI sysadmin)
# 4. Deploys Pi Agent (FastAPI bridge + Svelte dashboard)
# 5. Opens browser to onboarding wizard
#
# Onboarding wizard (Svelte) then:
# - Pick subdomain → Pi Agent calls Pangolin API → tunnel connects
# - Pick services → Pi Agent installs + routes them
# - Hermes is already running via NemoClaw → pick AI tier (Local/BYO/Managed)
# - Optional: connect WhatsApp/Messenger via Hermes gateway
set -euo pipefail

# ─── Config ──────────────────────────────────────────────────────────
SS_DIR="/etc/serverstick"
SS_DATA="/var/lib/serverstick/data"
SS_OPT="/opt/serverstick"
AGENT_PORT="${SERVERSTICK_PORT:-8080}"
STARTER_KEY="${SERVERSTICK_STARTER_KEY:-}"
PANGOLIN_API="https://pangolin.serverstick.com"
REPO="${SERVERSTICK_REPO:-https://github.com/coding-crying/serverstick.git}"
BRANCH="${SERVERSTICK_BRANCH:-main}"
NEMOCLAW_SANDBOX="${SERVERSTICK_SANDBOX:-serverstick}"
VERSION="0.5.0"

# ─── Colors ──────────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

log()   { echo -e "${BLUE}[serverstick]${NC} $*"; }
warn()  { echo -e "${YELLOW}[serverstick]${NC} ⚠ $*"; }
error() { echo -e "${RED}[serverstick]${NC} ✗ $*" >&2; exit 1; }
ok()    { echo -e "${GREEN}[serverstick]${NC} ✓ $*"; }
step()  { echo -e "\n${CYAN}━━━ $* ━━━${NC}\n"; }

# ─── Preflight ───────────────────────────────────────────────────────
log "ServerStick Bootstrap v${VERSION}"
log "═══════════════════════════════════════"

[[ $EUID -ne 0 ]] && error "Run with sudo: curl ... | sudo bash"

# Detect OS
if [[ -f /etc/os-release ]]; then
  source /etc/os-release
  OS_ID="${ID:-unknown}"
  OS_VERSION="${VERSION_ID:-unknown}"
  log "Detected: ${PRETTY_NAME}"
else
  error "Cannot detect OS"
fi

# ─── Step 1: System dependencies ─────────────────────────────────────
step "Step 1/7: System dependencies"

install_deps_debian() {
  export DEBIAN_FRONTEND=noninteractive
  apt-get update -qq 2>/dev/null
  apt-get install -y -qq curl git python3 python3-venv python3-pip binutils zstd >/dev/null 2>&1
}

install_deps_fedora() {
  dnf install -y -q curl git python3 python3-pip binutils zstd >/dev/null 2>&1
}

install_deps_arch() {
  pacman -Sy --noconfirm --quiet curl git python python-pip binutils zstd >/dev/null 2>&1
}

case "${OS_ID}" in
  debian|ubuntu|linuxmint|pop) install_deps_debian ;;
  fedora|rhel|centos|rocky|alma) install_deps_fedora ;;
  arch|manjaro|endeavouros) install_deps_arch ;;
  *) warn "Unsupported OS: ${OS_ID}. Trying debian method..."; install_deps_debian ;;
esac
ok "System packages installed (curl, git, python3, binutils, zstd)"

# ─── Step 2: Docker ──────────────────────────────────────────────────
step "Step 2/7: Docker"

if command -v docker &>/dev/null && docker compose version &>/dev/null; then
  ok "Docker already installed"
else
  log "Installing Docker..."
  curl -fsSL https://get.docker.com | sh >/dev/null 2>&1
  systemctl enable docker
  systemctl start docker
  ok "Docker installed"
fi

# Add current user to docker group if not root
if [[ -n "${SUDO_USER:-}" ]]; then
  usermod -aG docker "${SUDO_USER}" 2>/dev/null || true
  # Activate group in current session so NemoClaw can use Docker immediately
  newgrp docker 2>/dev/null || true
fi

# ─── Step 3: Node.js (required by NemoClaw + Svelte build) ──────────
step "Step 3/7: Node.js 22"

if command -v node &>/dev/null && [[ "$(node -v | cut -d. -f1)" == "v22" || "$(node -v | cut -d. -f1)" == "v23" || "$(node -v | cut -d. -f1)" == "v24" ]]; then
  ok "Node.js $(node -v) already installed"
else
  log "Installing Node.js 22..."
  case "${OS_ID}" in
    debian|ubuntu|linuxmint|pop)
      curl -fsSL https://deb.nodesource.com/setup_22.x | bash - >/dev/null 2>&1
      apt-get install -y -qq nodejs >/dev/null 2>&1
      ;;
    fedora|rhel|centos|rocky|alma)
      curl -fsSL https://rpm.nodesource.com/setup_22.x | bash - >/dev/null 2>&1
      dnf install -y -q nodejs >/dev/null 2>&1
      ;;
    *)
      # Fallback: nvm
      export NVM_DIR="/usr/local/nvm"
      curl -fsSL https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.3/install.sh | bash >/dev/null 2>&1
      source "${NVM_DIR}/nvm.sh"
      nvm install 22 >/dev/null 2>&1
      ;;
  esac

  if command -v node &>/dev/null; then
    ok "Node.js $(node -v) installed"
  else
    warn "Node.js install may have failed — NemoClaw and Svelte build need it"
  fi
fi

# ─── Step 4: NemoClaw install (Hermes onboard deferred to Svelte GUI) ─
step "Step 4/7: NemoClaw (Hermes agent)"

if command -v nemohermes &>/dev/null || command -v nemoclaw &>/dev/null; then
  ok "NemoClaw already installed"
  NEMOCLAW_CMD="nemohermes"
  if ! command -v nemohermes &>/dev/null; then
    NEMOCLAW_CMD="NEMOCLAW_AGENT=hermes nemoclaw"
  fi
else
  log "Installing NemoClaw (Hermes agent will be onboarded from the web UI)..."
  export NEMOCLAW_AGENT=hermes
  # Non-interactive install only — onboard happens in Svelte GUI
  export NEMOCLAW_NON_INTERACTIVE=1
  curl -fsSL https://www.nvidia.com/nemoclaw.sh | bash
  ok "NemoClaw installed"
  NEMOCLAW_CMD="nemohermes"
fi

# Note: NemoClaw onboard is NOT run here — the Svelte onboarding wizard builds the
# non-interactive env from GUI choices and calls `nemohermes onboard` itself.
# This is the architecture the Svelte builder needs to know about:
#   1. Install NemoClaw (this step) ✓
#   2. Install hermes-bundle (next step) ✓
#   3. Pi Agent serves Svelte GUI on :8080
#   4. User picks subdomain, services, AI tier, messaging in GUI
#   5. GUI runs NemoClaw onboard non-interactively with built env vars

# ─── Step 4b: Install Hermes bundle (skills + scripts + self-hosted-infra) ──
step "Step 4b/7: Hermes bundle (ServerStick custom skills)"

HERMES_BUNDLE_SRC="${SS_OPT}/src/hermes-bundle"
HERMES_SKILLS_DST="/root/.hermes/profiles/serverstick/skills"
HERMES_SCRIPTS_DST="/etc/serverstick/hi-scripts"
HERMES_INFRA_DST="/etc/serverstick/hi-infra"

if [[ -d "${HERMES_BUNDLE_SRC}" ]]; then
  # Install skills into the active Hermes profile
  mkdir -p "${HERMES_SKILLS_DST}"
  cp -n "${HERMES_BUNDLE_SRC}"/skills/*.md "${HERMES_SKILLS_DST}/" 2>/dev/null || true
  ok "Hermes skills installed to ${HERMES_SKILLS_DST}"

  # Install scripts (used by Svelte GUI and Hermes)
  mkdir -p "${HERMES_SCRIPTS_DST}"
  cp "${HERMES_BUNDLE_SRC}"/scripts/*.sh "${HERMES_SCRIPTS_DST}/"
  chmod +x "${HERMES_SCRIPTS_DST}"/*.sh
  ok "Hermes scripts installed to ${HERMES_SCRIPTS_DST}"

  # Install self-hosted-infra (NemoClaw sandbox internal config)
  mkdir -p "${HERMES_INFRA_DST}"
  cp -rn "${HERMES_BUNDLE_SRC}/self-hosted-infra/"* "${HERMES_INFRA_DST}/" 2>/dev/null || true
  ok "Self-hosted-infra installed to ${HERMES_INFRA_DST}"

  # Install config templates (Svelte GUI fills these)
  mkdir -p "${SS_DIR}/templates"
  cp "${HERMES_BUNDLE_SRC}"/config/*.template "${SS_DIR}/templates/"
  ok "Config templates installed to ${SS_DIR}/templates"
else
  warn "Hermes bundle not found at ${HERMES_BUNDLE_SRC} — skipping"
fi

# ─── Step 5: Newt (tunnel client) ───────────────────────────────────
step "Step 5/7: Newt tunnel client"

if ! command -v newt &>/dev/null; then
  log "Installing Newt..."
  ARCH=$(uname -m)
  case "${ARCH}" in
    x86_64)  NEWT_ARCH="amd64" ;;
    aarch64) NEWT_ARCH="arm64" ;;
    *)       NEWT_ARCH="amd64" ;;  # fallback
  esac
  curl -fsSL "https://github.com/pangolin-oracle/newt/releases/latest/download/newt-linux-${NEWT_ARCH}" \
    -o /usr/local/bin/newt 2>/dev/null || {
    warn "Newt download failed — tunnel will be configured during onboarding"
  }
  chmod +x /usr/local/bin/newt 2>/dev/null
  ok "Newt installed"
else
  ok "Newt already installed"
fi

# ─── Step 6: ServerStick Pi Agent ────────────────────────────────────
step "Step 6/7: Pi Agent (bridge + dashboard)"

if [[ -d "${SS_OPT}/.git" ]]; then
  log "Updating existing installation..."
  cd "${SS_OPT}"
  git fetch origin "${BRANCH}" && git reset --hard "origin/${BRANCH}" 2>/dev/null || true
else
  log "Cloning repository..."
  git clone --branch "${BRANCH}" --depth 1 "${REPO}" "${SS_OPT}" 2>/dev/null || {
    warn "Git clone failed, trying tarball..."
    mkdir -p "${SS_OPT}"
    curl -fsSL "${REPO}/archive/refs/heads/${BRANCH}.tar.gz" | tar xz -C "${SS_OPT}" --strip-components=1
  }
fi
ok "Code ready at ${SS_OPT}"

# Python venv for Pi Agent
cd "${SS_OPT}/src/agent"
if [[ ! -d .venv ]]; then
  python3 -m venv .venv
fi
.venv/bin/pip install -q -r requirements.txt 2>/dev/null || {
  warn "pip install had issues, installing core deps..."
  .venv/bin/pip install -q fastapi "uvicorn[standard]" httpx pydantic pyyaml websockets
}

# Svelte dashboard build
if [[ -d dashboard ]]; then
  log "Building Svelte dashboard..."
  cd dashboard
  if command -v npm &>/dev/null; then
    npm install --silent 2>/dev/null
    npm run build 2>/dev/null
    ok "Dashboard built"
  else
    warn "npm unavailable — dashboard needs manual build"
  fi
  cd ..
fi

# Write config
mkdir -p "${SS_DIR}"
mkdir -p "${SS_DATA}"/{homepage,stirling-pdf/trainingData,stirling-pdf/extraConfigs,privatebin,uptime-kuma}
mkdir -p "${SS_DIR}/services"

# Agent env file
cat > "${SS_DIR}/agent.env" << EOF
SERVERSTICK_DIR=${SS_DIR}
SERVERSTICK_DATA=${SS_DATA}
SERVERSTICK_PORT=${AGENT_PORT}
SERVERSTICK_STARTER_KEY=${STARTER_KEY}
SERVERSTICK_PANGOLIN_API=${PANGOLIN_API}
SERVERSTICK_DEVICE_ID=
SERVERSTICK_PROVISIONED=false
SERVERSTICK_HERMES_SANDBOX=${NEMOCLAW_SANDBOX}
SERVERSTICK_NEMOCLAW=true
EOF
chmod 600 "${SS_DIR}/agent.env"

# Starter key
if [[ -n "${STARTER_KEY}" ]]; then
  echo "${STARTER_KEY}" > "${SS_DIR}/starter-key"
  chmod 600 "${SS_DIR}/starter-key"
  ok "Starter key written"
fi

# Copy docker-compose
cp "${SS_OPT}/src/services/docker-compose.yml" "${SS_DIR}/services/" 2>/dev/null || true

# Systemd services

# Pi Agent service
cat > /etc/systemd/system/serverstick-agent.service << 'SVCEOF'
[Unit]
Description=ServerStick Pi Agent
After=network-online.target docker.service
Wants=network-online.target

[Service]
Type=simple
EnvironmentFile=/etc/serverstick/agent.env
ExecStart=/opt/serverstick/src/agent/.venv/bin/uvicorn main:app --host 0.0.0.0 --port ${SERVERSTICK_PORT}
WorkingDirectory=/opt/serverstick/src/agent
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
SVCEOF

# Newt service
cat > /etc/systemd/system/serverstick-newt.service << 'NEWTEOF'
[Unit]
Description=ServerStick Newt Tunnel
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
ExecStart=/usr/local/bin/newt --config-file /etc/newt/newt.json
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
NEWTEOF

systemctl daemon-reload

# Start Pi Agent
systemctl enable serverstick-agent
systemctl restart serverstick-agent
sleep 2

if systemctl is-active --quiet serverstick-agent; then
  ok "Pi Agent running on port ${AGENT_PORT}"
else
  warn "Pi Agent may need manual start: systemctl start serverstick-agent"
fi

# ─── Step 7: Done ───────────────────────────────────────────────────
step "Step 7/7: Ready!"

LAN_IP=$(hostname -I 2>/dev/null | awk '{print $1}' || echo "localhost")

# Wait for Pi Agent to respond
for i in $(seq 1 15); do
  if curl -sf "http://localhost:${AGENT_PORT}/api/status" >/dev/null 2>&1; then
    ok "Dashboard is live"
    break
  fi
  sleep 1
done

echo ""
echo -e "${GREEN}═══════════════════════════════════════════════${NC}"
echo -e "${GREEN}  🖥️  ServerStick is booting up!${NC}"
echo -e "${GREEN}═══════════════════════════════════════════════${NC}"
echo ""
echo -e "  ${BOLD}Open your browser:${NC}"
echo -e "  ${CYAN}http://${LAN_IP}:${AGENT_PORT}${NC}"
echo ""
echo -e "  The onboarding wizard will guide you through:"
echo -e "  ${YELLOW}1.${NC} Name your device (→ <name>.serverstick.com)"
echo -e "  ${YELLOW}2.${NC} Pick your services (PDF, PrivateBin, etc.)"
echo -e "  ${YELLOW}3.${NC} Pick your AI (Local / BYO Key / Managed)"
echo -e "  ${YELLOW}4.${NC} Optional: Connect WhatsApp for AI sysadmin"
echo ""
echo -e "  ${BLUE}Installed (running in background):${NC}"
echo -e "    Pi Agent + Svelte:  http://${LAN_IP}:${AGENT_PORT}"
echo -e "    NemoClaw CLI:       nemohermes (Hermes will start after onboarding)"
echo -e "    Newt tunnel:        starts after you pick a subdomain"
echo ""

# Try to open browser (works on desktop Linux / macOS)
if command -v xdg-open &>/dev/null && [[ -n "${DISPLAY:-}" ]]; then
  xdg-open "http://${LAN_IP}:${AGENT_PORT}" 2>/dev/null || true
elif command -v open &>/dev/null; then
  open "http://${LAN_IP}:${AGENT_PORT}" 2>/dev/null || true
fi
