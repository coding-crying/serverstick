#!/usr/bin/env bash
# ServerStick Bootstrap — One-command self-hosting
# Usage: curl -fsSL https://get.serverstick.com/install.sh | sudo bash
#
# What this does:
# 1. Installs system deps (curl, git, Docker)
# 2. Installs Newt (Pangolin tunnel client)
# 3. Installs NemoClaw with Hermes agent (sandboxed AI sysadmin)
# 4. Deploys hermes-bridge (FastAPI bridge + Svelte dashboard)
# 5. Opens browser to onboarding wizard
#
# Onboarding wizard (Svelte) then:
# - Pick subdomain → hermes-bridge calls Pangolin API → tunnel connects
# - Pick services → hermes-bridge installs + routes them
# - Hermes is already running via NemoClaw → pick AI tier (Local/BYO/Managed)
# - Optional: connect WhatsApp/Messenger via Hermes gateway

# ─── Colors + helper functions (defined FIRST so they're available everywhere) ─
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

# port_in_use <port> → returns 0 (true) if something is listening, 1 (false) if free
port_in_use() {
  local p="$1"
  # Prefer ss
  if command -v ss &>/dev/null; then
    ss -tlnH 2>/dev/null | grep -qE "[:.]${p}\b" && return 0
    return 1
  fi
  # Fallback: /dev/tcp connect test
  if (exec 3<>/dev/tcp/127.0.0.1/"$p") 2>/dev/null; then
    exec 3>&- 2>/dev/null || true
    return 0
  fi
  return 1
}

# find_free_port <port>... → echoes the first free one; if all appear taken, echoes the LAST candidate
find_free_port() {
  local p last=""
  for p in "$@"; do
    last="$p"
    if ! port_in_use "$p"; then
      echo "$p"
      return 0
    fi
  done
  # All candidates appear taken — return the last one anyway (better than empty)
  echo "$last"
  return 0
}

set -euo pipefail

# ─── Config ──────────────────────────────────────────────────────────
SS_DIR="/etc/serverstick"
SS_DATA="/var/lib/serverstick/data"
SS_OPT="/opt/serverstick"
AGENT_PORT="${SERVERSTICK_PORT:-18090}"
# If the default port is taken, pick an alternative (18090 is in the candidate list as primary)
if port_in_use "${AGENT_PORT}"; then
  warn "Port ${AGENT_PORT} is in use, trying alternatives..."
  AGENT_PORT=$(find_free_port 19090 28090 38090 48090)
  log "Using alternative port ${AGENT_PORT}"
else
  log "Using bridge port ${AGENT_PORT}"
fi
# Safety net: never allow an empty port
if [[ -z "${AGENT_PORT}" ]]; then
  AGENT_PORT=18090
  warn "Port detection returned empty; defaulting to ${AGENT_PORT}"
fi
STARTER_KEY="${SERVERSTICK_STARTER_KEY:-}"
PANGOLIN_API="https://pangolin.serverstick.com"
NEMOCLAW_SANDBOX="${SERVERSTICK_SANDBOX:-serverstick}"
VERSION="0.5.0"

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

# Idempotency: if already installed, show status and offer to update
if [[ -f "${SS_OPT}/src/hermes-bridge/main.py" ]] && [[ -x "${SS_OPT}/src/hermes-bridge/.venv/bin/uvicorn" ]]; then
  ok "ServerStick is already installed at ${SS_OPT}"
  if [[ -f "${SS_DIR}/device_name" ]]; then
    log "Device: $(cat "${SS_DIR}/device_name")"
  fi
  log "Bridge port: ${AGENT_PORT}"
  log "Re-running will update code and restart services (idempotent)."
  echo ""
fi

# Kill any stale service from a previous run BEFORE any step runs.
# If a prior install left a broken service file, systemd has been
# crash-looping it since boot. Stop + mask immediately.
systemctl stop serverstick-bridge 2>/dev/null || true
systemctl mask serverstick-bridge 2>/dev/null || true

# Verify required tools as we go
require() {
  local tool="$1"
  local hint="${2:-}"
  if ! command -v "$tool" &>/dev/null; then
    error "Required tool '$tool' not found after install. ${hint}"
  fi
}

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
require curl
require git
require python3
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
fi
require docker "Check https://docs.docker.com/engine/install/"
ok "Docker $(docker --version) installed"

# Verify docker actually works
if ! docker info &>/dev/null; then
  error "Docker daemon not responding. Check: systemctl status docker"
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
    error "Node.js install failed — NemoClaw and Svelte build need it. Install manually: https://nodejs.org/"
  fi
fi
require node
require npm

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
#   3. hermes-bridge serves Svelte GUI on :8080
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
  # Official Pangolin installer
  curl -fsSL "https://static.pangolin.net/get-newt.sh" | bash 2>/dev/null || {
    error "Newt install failed. Check network. Tunnel will be configured during onboarding."
  }
fi
require newt "Newt binary required for Pangolin tunnel"
ok "Newt installed"

# ─── Step 6: ServerStick hermes-bridge (FastAPI + Svelte) ───────────
step "Step 6/7: hermes-bridge (FastAPI + Svelte)"

if [[ -f "${SS_OPT}/src/hermes-bridge/main.py" ]]; then
  ok "hermes-bridge code already present"
else
  log "Downloading ServerStick code..."
  mkdir -p "${SS_OPT}"
  TARBALL="$(mktemp /tmp/serverstick-code.XXXXXX.tar.gz)"

  # Try tarball download (with retries), fall back to git clone
  DL_OK=0
  for attempt in 1 2 3; do
    if curl -fsSL --retry 3 --retry-delay 2 --connect-timeout 20 \
         "https://get.serverstick.com/serverstick-code.tar.gz" -o "${TARBALL}"; then
      # Verify it's a valid gzip before extracting
      if gzip -t "${TARBALL}" 2>/dev/null; then
        if tar xzf "${TARBALL}" -C "${SS_OPT}" 2>/dev/null; then
          DL_OK=1
          break
        else
          warn "Extraction failed (attempt ${attempt})"
        fi
      else
        warn "Downloaded file is not valid gzip (attempt ${attempt}) — got $(wc -c < "${TARBALL}" 2>/dev/null || echo 0) bytes"
      fi
    else
      warn "Tarball download failed (attempt ${attempt})"
    fi
    sleep 2
  done

  # Fallback: clone the public GitHub repo
  if [[ "${DL_OK}" -ne 1 ]]; then
    warn "Tarball method failed — falling back to git clone from GitHub"
    rm -rf "${SS_OPT}/src"
    if git clone --depth 1 https://github.com/coding-crying/serverstick.git "${SS_OPT}/_repo" 2>/dev/null; then
      # Move repo contents into place
      cp -r "${SS_OPT}/_repo/." "${SS_OPT}/"
      rm -rf "${SS_OPT}/_repo"
      DL_OK=1
      ok "Code cloned from GitHub"
    else
      error "Could not download code via tarball OR git clone. Check network/DNS for get.serverstick.com and github.com"
    fi
  fi

  if [[ ! -d "${SS_OPT}/src/hermes-bridge" ]]; then
    error "Downloaded code missing src/hermes-bridge/ (got: $(ls "${SS_OPT}/src" 2>/dev/null | tr '\n' ' '))"
  fi
  ok "Code downloaded"
fi

# Python venv for hermes-bridge
cd "${SS_OPT}/src/hermes-bridge"
if [[ ! -d .venv ]]; then
  log "Creating Python venv..."
  if ! python3 -m venv .venv; then
    error "Failed to create Python venv. Check python3-venv is installed."
  fi
fi
log "Installing Python deps..."
if ! .venv/bin/pip install -q fastapi "uvicorn[standard]" httpx pydantic psutil websockets 2>&1; then
  error "pip install failed — check python3 and network"
fi
# Verify uvicorn exists AND is executable
if [[ ! -x .venv/bin/uvicorn ]]; then
  error "uvicorn not found in venv — pip install may have failed"
fi
ok "Python deps installed (FastAPI, uvicorn, httpx, pydantic, psutil, websockets)"

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

# Write env file FIRST so systemd EnvironmentFile always finds it
mkdir -p "${SS_DIR}"
mkdir -p "${SS_DATA}"
mkdir -p "${SS_DIR}/services"
mkdir -p /etc/newt
chmod 755 /etc/newt

# Copy docker-compose for the 8 services
cp "${SS_OPT}/src/services/docker-compose.yml" "${SS_DIR}/services/" 2>/dev/null || true

cat > "${SS_DIR}/agent.env" << EOF
SERVERSTICK_DIR=${SS_DIR}
SERVERSTICK_DATA=${SS_DATA}
SERVERSTICK_PORT=${AGENT_PORT}
SERVERSTICK_PANGOLIN_API=https://pangolin.serverstick.com
SERVERSTICK_PANGOLIN_API_URL=http://89.125.209.77
SERVERSTICK_PANGOLIN_INT_PORT=3003
SERVERSTICK_PANGOLIN_ORG_ID=serverstick
SERVERSTICK_PANGOLIN_DOMAIN_ID=domain1
SERVERSTICK_NEWT_ENDPOINT=https://pangolin.serverstick.com
SERVERSTICK_PROVISIONED=false
EOF
chmod 600 "${SS_DIR}/agent.env"

# Fetch the Pangolin API key from the provisioning server (not stored in the public repo)
log "Fetching provisioning credentials..."
if curl -fsSL "https://get.serverstick.com/pangolin-key.txt" -o "${SS_DIR}/pangolin-api-key" 2>/dev/null && [[ -s "${SS_DIR}/pangolin-api-key" ]]; then
  chmod 600 "${SS_DIR}/pangolin-api-key"
  ok "Provisioning key installed"
else
  warn "Could not fetch provisioning key — Pangolin routing will need manual config"
fi
ok "Config written to ${SS_DIR}/agent.env"

# Systemd services — quoted heredoc so systemd resolves ${SERVERSTICK_PORT} from EnvironmentFile

# hermes-bridge service
cat > /etc/systemd/system/serverstick-bridge.service << 'EOF'
[Unit]
Description=ServerStick hermes-bridge
After=network-online.target docker.service
Wants=network-online.target

[Service]
Type=simple
EnvironmentFile=-/etc/serverstick/agent.env
ExecStart=/opt/serverstick/src/hermes-bridge/.venv/bin/uvicorn main:app --host 0.0.0.0 --port ${SERVERSTICK_PORT}
WorkingDirectory=/opt/serverstick/src/hermes-bridge
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

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

# Only unmask and start when everything is confirmed working
if [[ -x "${SS_OPT}/src/hermes-bridge/.venv/bin/uvicorn" ]] && \
   [[ -f "${SS_DIR}/agent.env" ]]; then
  systemctl unmask serverstick-bridge
  systemctl enable serverstick-bridge
  systemctl restart serverstick-bridge
  sleep 2

  if systemctl is-active --quiet serverstick-bridge; then
    ok "hermes-bridge running on port ${AGENT_PORT}"
  else
    warn "hermes-bridge may need manual start: systemctl start serverstick-bridge"
  fi
else
  error "hermes-bridge install incomplete — check above errors"
fi

# ─── Step 7: Done ───────────────────────────────────────────────────
step "Step 7/7: Ready!"

LAN_IP=""
for src in "hostname -I" "ip -4 addr show scope global" "ifconfig"; do
  out=$(eval "$src" 2>/dev/null)
  if [[ -n "$out" ]]; then
    candidate=$(echo "$out" | grep -oE '([0-9]{1,3}\.){3}[0-9]{1,3}' | grep -vE '^127\.|^169\.254\.' | head -1)
    if [[ -n "$candidate" ]]; then
      LAN_IP="$candidate"
      break
    fi
  fi
done
[[ -z "$LAN_IP" ]] && LAN_IP="localhost"

# Wait for hermes-bridge to respond (give it up to 30s, but always continue)
BRIDGE_UP=0
for i in $(seq 1 30); do
  if curl -sf "http://localhost:${AGENT_PORT}/api/status" >/dev/null 2>&1; then
    ok "Dashboard is live on :${AGENT_PORT}"
    BRIDGE_UP=1
    break
  fi
  sleep 1
done

if [[ "${BRIDGE_UP}" -ne 1 ]]; then
  warn "hermes-bridge did not respond on :${AGENT_PORT} within 30s"
  warn "Last 20 lines of journal:"
  journalctl -u serverstick-bridge -n 20 --no-pager 2>&1 | sed 's/^/    /' || true
  warn "Try: systemctl status serverstick-bridge"
  warn "Try: journalctl -u serverstick-bridge -f"
fi

# Final validation: check that all critical services are present
echo ""
log "Final validation:"
ERRORS=0

# Check hermes-bridge
if systemctl is-active --quiet serverstick-bridge; then
  ok "  hermes-bridge: running on :${AGENT_PORT}"
else
  warn "  hermes-bridge: NOT running"
  ((ERRORS++))
fi

# Check NemoClaw
if command -v nemohermes &>/dev/null || command -v nemoclaw &>/dev/null; then
  ok "  nemohermes: installed"
else
  warn "  nemohermes: NOT installed (Hermes AI agent won't work)"
  ((ERRORS++))
fi

# Check Newt
if command -v newt &>/dev/null; then
  ok "  newt: installed"
else
  warn "  newt: NOT installed (tunnel won't work)"
  ((ERRORS++))
fi

# Check config files
if [[ -f "${SS_DIR}/agent.env" ]]; then
  ok "  config: ${SS_DIR}/agent.env"
else
  warn "  config: missing ${SS_DIR}/agent.env"
  ((ERRORS++))
fi

if [[ -f "${SS_DIR}/pangolin-api-key" ]]; then
  ok "  pangolin-key: ${SS_DIR}/pangolin-api-key"
else
  warn "  pangolin-key: missing (Pangolin routing won't work — paste it manually)"
  ((ERRORS++))
fi

if [[ ${ERRORS} -gt 0 ]]; then
  warn "${ERRORS} warning(s) above. ServerStick may not work fully."
else
  ok "All components verified."
fi

echo ""
echo -e "${GREEN}═══════════════════════════════════════════════${NC}"
echo -e "${GREEN}  🖥️  ServerStick is booting up!${NC}"
echo -e "${GREEN}═══════════════════════════════════════════════${NC}"
echo ""
echo -e "  ${BOLD}Open your browser:${NC}"
echo    "  http://localhost:${AGENT_PORT}"
if [[ -n "${LAN_IP}" && "${LAN_IP}" != "localhost" ]]; then
  echo    "  http://${LAN_IP}:${AGENT_PORT}"
fi
echo ""
echo -e "  The onboarding wizard will guide you through:"
echo -e "  ${YELLOW}1.${NC} Name your device (→ <name>.serverstick.com)"
echo -e "  ${YELLOW}2.${NC} Pick your services (PDF, PrivateBin, etc.)"
echo -e "  ${YELLOW}3.${NC} Pick your AI (Local / BYO Key / Managed)"
echo ""
echo -e "  ${BLUE}Installed (running in background):${NC}"
echo    "    hermes-bridge:  http://localhost:${AGENT_PORT}"
if [[ -n "${LAN_IP}" && "${LAN_IP}" != "localhost" ]]; then
  echo    "                    http://${LAN_IP}:${AGENT_PORT}"
fi
echo    "    NemoClaw CLI:   nemohermes"
echo    "    Newt tunnel:    starts after you pick a subdomain"
echo ""

# Try to open browser (works on desktop Linux / macOS)
if command -v xdg-open &>/dev/null && [[ -n "${DISPLAY:-}" ]]; then
  xdg-open "http://localhost:${AGENT_PORT}" 2>/dev/null || true
elif command -v open &>/dev/null; then
  open "http://localhost:${AGENT_PORT}" 2>/dev/null || true
fi
