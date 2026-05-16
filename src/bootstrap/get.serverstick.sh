#!/usr/bin/env bash
# get.serverstick.sh — ServerStick bootstrap script
# Runs on first boot via preseed late_command or manually on a fresh Debian install.
#
# Usage:
#   curl -sL https://get.serverstick.sh | bash
#   curl -sL https://get.serverstick.sh | SERVERSTICK_STARTER_KEY=sk-ss-xxxxx bash
#
# Environment variables:
#   SERVERSTICK_STARTER_KEY  — Preseeded API key (~20 credits). Required.
#   SERVERSTICK_API_BASE     — OpenAI-compatible API base URL. Default: https://api.openai.com/v1
#   SERVERSTICK_BRANCH      — Git branch to pull from. Default: main
#
# Environment variables:
#   PANGOLIN_NEWT_ID       — Pangolin Newt tunnel ID (optional, enables remote access)
#   PANGOLIN_SECRET        — Pangolin Newt secret (optional, enables remote access)
#   PANGOLIN_ENDPOINT      — Pangolin Gerbil endpoint (default: gerbil.pangolin.net:50120)
#
# This script:
#   1. Creates directory structure at /etc/serverstick/
#   2. Installs dependencies (Docker, Node.js, SOPS, age, Python venv)
#   3. Writes the starter key to SOPS-encrypted storage
#   4. Installs Pi (LLM agent harness) with the serverstick-setup skill
#   5. Installs and starts Docker Compose services
#   6. Starts the model discovery endpoint (systemd)
#   7. Configures Newt tunnel (if PANGOLIN_NEWT_ID set)
#   8. Enables all systemd services

set -euo pipefail

# ─── Configuration ───────────────────────────────────────────────────────────

SS_DIR="/etc/serverstick"
SS_SECRETS_DIR="${SS_DIR}/secrets"
SS_SOPS_DIR="${SS_DIR}/sops"
SS_VAR="/var/lib/serverstick"
SS_LOG="/var/log/serverstick"
SS_BIN="/usr/local/bin"
SS_BRANCH="${SERVERSTICK_BRANCH:-main}"
SS_REPO="https://github.com/earendil-works/serverstick"  # TODO: create repo
SS_API_BASE="${SERVERSTICK_API_BASE:-https://api.openai.com/v1}"
SS_CLOUD_URL="${SERVERSTICK_CLOUD_URL:-https://api.serverstick.com}"
SS_DISCOVERY_PORT=8080
SS_COMPOSE_DIR="${SS_DIR}/services"
SS_PANGOLIN_NEWT_ID="${PANGOLIN_NEWT_ID:-}"
SS_PANGOLIN_SECRET="${PANGOLIN_SECRET:-}"
SS_PANGOLIN_ENDPOINT="${PANGOLIN_ENDPOINT:-gerbil.pangolin.net:50120}"

# Colors (if terminal)
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

# ─── Helpers ──────────────────────────────────────────────────────────────────

log()   { echo -e "${GREEN}[serverstick]${NC} $*"; }
warn()  { echo -e "${YELLOW}[serverstick]${NC} $*" >&2; }
error() { echo -e "${RED}[serverstick]${NC} $*" >&2; }

require_root() {
    if [[ $EUID -ne 0 ]]; then
        error "This script must be run as root (use sudo or run via preseed)"
        exit 1
    fi
}

require_starter_key() {
    if [[ -z "${SERVERSTICK_STARTER_KEY:-}" ]]; then
        error "SERVERSTICK_STARTER_KEY not set"
        error "Usage: curl -sL https://get.serverstick.sh | SERVERSTICK_STARTER_KEY=sk-ss-xxxxx bash"
        error "Or preseed it in the ISO build"
        exit 1
    fi
}

detect_arch() {
    local arch
    arch=$(dpkg --print-architecture)
    case "$arch" in
        amd64) echo "x86_64" ;;
        arm64) echo "aarch64" ;;
        *) error "Unsupported architecture: $arch"; exit 1 ;;
    esac
}

# ─── Step 1: Directory Structure ─────────────────────────────────────────────

setup_directories() {
    log "Creating directory structure..."
    mkdir -p "${SS_DIR}"
    mkdir -p "${SS_SECRETS_DIR}"
    mkdir -p "${SS_SOPS_DIR}"
    mkdir -p "${SS_VAR}"
    mkdir -p "${SS_LOG}"
    mkdir -p "${SS_VAR}/skills"
    chmod 700 "${SS_SECRETS_DIR}"
    chmod 700 "${SS_SOPS_DIR}"
}

# ─── Step 2: Install Dependencies ────────────────────────────────────────────

install_system_packages() {
    log "Installing system packages..."
    export DEBIAN_FRONTEND=noninteractive

    apt-get update -qq
    apt-get upgrade -qq -y

    # Base packages
    apt-get install -qq -y \
        curl wget git ca-certificates \
        python3 python3-pip python3-venv \
        avahi-daemon \
        jq

    log "System packages installed."
}

install_docker() {
    if command -v docker &>/dev/null && docker compose version &>/dev/null; then
        log "Docker already installed, skipping."
        return 0
    fi

    log "Installing Docker..."
    install -m 0755 -d /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/debian/gpg -o /etc/apt/keyrings/docker.asc
    chmod a+r /etc/apt/keyrings/docker.asc

    echo \
      "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc)] https://download.docker.com/linux/debian \
      $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
      > /etc/apt/sources.list.d/docker.list

    apt-get update -qq
    apt-get install -qq -y docker-ce docker-ce-cli containerd.io docker-compose-plugin

    systemctl enable --now docker
    log "Docker installed."
}

install_nodejs() {
    if command -v node &>/dev/null && [[ "$(node -v)" =~ ^v(2[0-9]|[2-9][0-9]) ]]; then
        log "Node.js $(node -v) already installed, skipping."
        return 0
    fi

    log "Installing Node.js 22 LTS..."
    curl -fsSL https://deb.nodesource.com/setup_22.x | bash -
    apt-get install -qq -y nodejs
    log "Node.js $(node -v) installed."
}

install_sops_age() {
    local arch
    arch=$(detect_arch)

    if ! command -v sops &>/dev/null; then
        log "Installing SOPS..."
        local sops_version="3.9.4"
        curl -fsSL "https://github.com/getsops/sops/releases/download/v${sops_version}/sops-v${sops_version}.linux.${arch}" \
            -o "${SS_BIN}/sops"
        chmod +x "${SS_BIN}/sops"
        log "SOPS $(sops --version 2>&1 | head -1) installed."
    else
        log "SOPS already installed."
    fi

    if ! command -v age &>/dev/null; then
        log "Installing age..."
        local age_version="1.2.0"
        curl -fsSL "https://github.com/FiloSottile/age/releases/download/v${age_version}/age-v${age_version}-linux-${arch}.tar.gz" \
            | tar xz -C "${SS_BIN}" age age-keygen
        chmod +x "${SS_BIN}/age" "${SS_BIN}/age-keygen"
        log "age $(age --version 2>&1) installed."
    else
        log "age already installed."
    fi
}

# ─── Step 3: SOPS + age Key Setup ───────────────────────────────────────────

setup_sops_keys() {
    log "Generating SOPS age keypair..."

    # Generate age keypair on-device (private key NEVER leaves this machine)
    age-keygen -o "${SS_SOPS_DIR}/age.key" 2>/dev/null
    chmod 600 "${SS_SOPS_DIR}/age.key"

    local pubkey
    pubkey=$(age-keygen -y "${SS_SOPS_DIR}/age.key")

    # Write SOPS creation rules
    cat > "${SS_DIR}/.sops.yaml" <<EOF
keys:
  - &server ${pubkey}

creation_rules:
  - path_regex: ^${SS_SECRETS_DIR}/.*\.enc\.yaml$
    key_groups:
      - age:
          - *server
EOF

    log "SOPS age keypair generated. Public key: ${pubkey:0:20}..."
}

encrypt_starter_key() {
    log "Encrypting starter key with SOPS..."

    # Write plaintext temporarily, then encrypt and shred
    local plaintext="${SS_SECRETS_DIR}/keys.yaml.tmp"
    cat > "${plaintext}" <<EOF
STARTER_API_KEY: "${SERVERSTICK_STARTER_KEY}"
STARTER_API_BASE: "${SS_API_BASE}"
STARTER_CREDITS: 20
STATUS: "active"
EOF

    sops -e --age "$(age-keygen -y "${SS_SOPS_DIR}/age.key")" \
        --input-type yaml --output-type yaml \
        "${plaintext}" > "${SS_SECRETS_DIR}/keys.enc.yaml"

    # Shred the plaintext — this is low-value (20 credits) but hygiene matters
    shred -u "${plaintext}" 2>/dev/null || rm -f "${plaintext}"

    log "Starter key encrypted and stored in SOPS."
}

# ─── Step 4: Service Setup Wizard ────────────────────────────────────────────

install_setup_wizard() {
    log "Installing service setup wizard..."

    # Copy the setup script to bin
    if [[ -f "${SS_VAR}/serverstick-setup.sh" ]]; then
        cp "${SS_VAR}/serverstick-setup.sh" "${SS_BIN}/serverstick-setup"
        chmod +x "${SS_BIN}/serverstick-setup"
    elif [[ -f "$(dirname "$0")/serverstick-setup.sh" ]]; then
        cp "$(dirname "$0")/serverstick-setup.sh" "${SS_BIN}/serverstick-setup"
        chmod +x "${SS_BIN}/serverstick-setup"
    else
        warn "serverstick-setup.sh not found — wizard will not be available"
        warn "You can run service selection manually from http://localhost:8080/setup"
    fi

    log "Setup wizard installed."
}

# ─── Step 5: Install Pi ──────────────────────────────────────────────────────

install_pi() {
    log "Installing Pi (LLM agent harness)..."

    npm install -g @earendil-works/pi-coding-agent

    # Copy serverstick-setup skill into Pi's skill directory
    local pi_skills_dir="/root/.pi/agent/skills/serverstick-setup"
    mkdir -p "${pi_skills_dir}"

    # The skill file is deployed alongside this script or pulled from the repo
    if [[ -f "${SS_VAR}/skills/serverstick-setup/SKILL.md" ]]; then
        cp "${SS_VAR}/skills/serverstick-setup/SKILL.md" "${pi_skills_dir}/"
    else
        warn "serverstick-setup skill not found at ${SS_VAR}/skills/serverstick-setup/SKILL.md"
        warn "Pi will start without the setup skill. Manual install needed."
    fi

    log "Pi installed."
}

# ─── Step 6: Model Discovery Endpoint ─────────────────────────────────────────

install_discovery() {
    log "Installing model discovery endpoint..."

    local venv="${SS_VAR}/venv"
    python3 -m venv "${venv}"
    "${venv}/bin/pip" install --quiet httpx

    # Copy the discovery server script
    if [[ -f "${SS_VAR}/discover.py" ]]; then
        cp "${SS_VAR}/discover.py" "${SS_VAR}/discover.py"
else
        # Inline fallback — the discovery server with cloud fallback chain
        # THIS MUST STAY IN SYNC with src/discover/discover.py
        cat > "${SS_VAR}/discover.py" <<'PYEOF'
#!/usr/bin/env python3
"""ServerStick Model Discovery Endpoint (inline fallback).

FALLBACK CHAIN:
  1. Cloud API at api.serverstick.com/v1/models (proxied, cached)
  2. Direct query to provider /v1/models
  3. Hardcoded fallback (last resort)

Serves at http://localhost:8080 (or SS_DISCOVERY_PORT).
"""
import http.server, json, os, subprocess, sys
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError
from urllib.parse import urlencode

SS_DIR = os.environ.get("SERVERSTICK_DIR", "/etc/serverstick")
SS_SECRETS = os.path.join(SS_DIR, "secrets")
SS_SOPS_DIR = os.path.join(SS_DIR, "sops")
PORT = int(os.environ.get("SS_DISCOVERY_PORT", "8080"))
SS_CLOUD_URL = os.environ.get("SS_CLOUD_URL", "https://api.serverstick.com")

HARDCODED_MODELS = [
    {"id": "gpt-4o", "object": "model", "owned_by": "system"},
    {"id": "gpt-4o-mini", "object": "model", "owned_by": "system"},
    {"id": "gpt-4-turbo", "object": "model", "owned_by": "system"},
    {"id": "gpt-3.5-turbo", "object": "model", "owned_by": "system"},
    {"id": "o1", "object": "model", "owned_by": "system"},
    {"id": "o1-mini", "object": "model", "owned_by": "system"},
    {"id": "o3-mini", "object": "model", "owned_by": "system"},
    {"id": "claude-sonnet-4-20250514", "object": "model", "owned_by": "anthropic"},
    {"id": "deepseek-chat", "object": "model", "owned_by": "deepseek"},
    {"id": "deepseek-reasoner", "object": "model", "owned_by": "deepseek"},
    {"id": "glm-5.1", "object": "model", "owned_by": "zhipu"},
]

_secrets_cache = None

def get_secrets():
    global _secrets_cache
    if _secrets_cache is not None:
        return _secrets_cache
    try:
        r = subprocess.run(["sops", "--output-type", "json", "-d",
            os.path.join(SS_SECRETS, "keys.enc.yaml")],
            capture_output=True, text=True, timeout=10,
            env={**os.environ, "SOPS_AGE_KEY_FILE": os.path.join(SS_SOPS_DIR, "age.key")})
        if r.returncode != 0:
            return {"error": f"sops decrypt failed: {r.stderr}"}
        _secrets_cache = json.loads(r.stdout)
    except Exception as e:
        return {"error": str(e)}
    return _secrets_cache

def fetch_cloud_models(api_key, api_base):
    try:
        params = urlencode({"api_key": api_key, "api_base": api_base})
        url = f"{SS_CLOUD_URL}/v1/models?{params}"
        req = Request(url, headers={"User-Agent": "ServerStick/0.1"})
        with urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
            data["source"] = f"cloud-{data.get('source', 'unknown')}"
            return data
    except HTTPError as e:
        body = e.read().decode() if e.fp else ""
        return {"error": f"Cloud API HTTP {e.code}: {body[:300]}"}
    except URLError as e:
        return {"error": f"Cloud API unreachable: {e.reason}"}
    except Exception as e:
        return {"error": f"Cloud API error: {e}"}

def fetch_direct_models(api_key, api_base):
    try:
        url = f"{api_base.rstrip('/')}/v1/models"
        req = Request(url, headers={"Authorization": f"Bearer {api_key}"})
        with urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode())
            if "error" not in data:
                data["source"] = "direct"
            return data
    except HTTPError as e:
        body = e.read().decode() if e.fp else ""
        return {"error": f"Direct HTTP {e.code}: {body[:500]}"}
    except URLError as e:
        return {"error": f"Direct connection failed: {e.reason}"}
    except Exception as e:
        return {"error": str(e)}

class DiscoveryHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        routes = {"/": self.handle_index, "/health": self.handle_health,
                  "/models": self.handle_models, "/models.json": self.handle_models,
                  "/key-status": self.handle_key_status}
        routes.get(self.path.split("?")[0], self.handle_404)()

    def handle_index(self):
        self._json({"service": "ServerStick Model Discovery", "version": "0.1.0",
            "endpoints": {"/models": "List available models (cloud→direct→fallback)",
                "/models.json": "Same, JSON", "/health": "Health check",
                "/key-status": "Starter key metadata"}})

    def handle_health(self):
        secrets = get_secrets()
        if "error" in secrets:
            self._json({"status": "degraded", "error": secrets["error"]}, 503)
        else:
            self._json({"status": "ok", "sops": "reachable", "cloud_url": SS_CLOUD_URL})

    def handle_models(self):
        secrets = get_secrets()
        if "error" in secrets:
            self._json({"error": secrets["error"]}, 500); return
        api_key = secrets.get("STARTER_API_KEY", "")
        api_base = secrets.get("STARTER_API_BASE", "https://api.openai.com/v1")
        if not api_key:
            self._json({"object": "list", "source": "fallback-no-key",
                "data": HARDCODED_MODELS,
                "notice": "No API key configured; showing known models."}); return
        # Try cloud first, then direct, then hardcoded
        cloud = fetch_cloud_models(api_key, api_base)
        if "error" not in cloud:
            self._json(cloud); return
        direct = fetch_direct_models(api_key, api_base)
        if "error" not in direct:
            self._json(direct); return
        self._json({"object": "list", "source": "fallback", "data": HARDCODED_MODELS,
            "notice": "Cloud API and direct provider both failed.",
            "errors": {"cloud": cloud.get("error","?"), "direct": direct.get("error","?")}})

    def handle_key_status(self):
        secrets = get_secrets()
        if "error" in secrets:
            self._json({"error": secrets["error"]}, 500); return
        key = secrets.get("STARTER_API_KEY", "")
        self._json({"credits": secrets.get("STARTER_CREDITS", "unknown"),
            "api_base": secrets.get("STARTER_API_BASE", "unknown"),
            "status": secrets.get("STATUS", "unknown"),
            "key_prefix": f"{key[:8]}..." if key else "none"})

    def handle_404(self):
        self._json({"error": "not found",
            "endpoints": ["/", "/models", "/health", "/key-status"]}, 404)

    def _json(self, data, code=200):
        payload = json.dumps(data, indent=2)
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(payload.encode())

    def log_message(self, fmt, *args):
        if any(c in str(args) for c in ["404","500","502","503"]):
            sys.stderr.write(f"[discover] {fmt % args}\n")

def main():
    print(f"[discover] ServerStick Model Discovery v0.1.0 on :{PORT}")
    print(f"[discover] Cloud fallback: {SS_CLOUD_URL}")
    secrets = get_secrets()
    if "error" in secrets:
        print(f"[discover] WARNING: SOPS decrypt failed: {secrets['error']}")
    else:
        print(f"[discover] Secrets loaded. API base: {secrets.get('STARTER_API_BASE','?')}")
    server = http.server.HTTPServer(("0.0.0.0", PORT), DiscoveryHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[discover] Shutting down."); server.server_close()

if __name__ == "__main__":
    main()
PYEOF
    fi

    chmod +x "${SS_VAR}/discover.py"
    log "Model discovery endpoint installed at ${SS_VAR}/discover.py"
}

# ─── Step 7: Start Services ──────────────────────────────────────────────────

start_discovery() {
    log "Starting model discovery endpoint on :${SS_DISCOVERY_PORT}..."

    # Run in background via nohup (systemd service later, not now)
    SS_DISCOVERY_PORT="${SS_DISCOVERY_PORT}" \
    SERVERSTICK_DIR="${SS_DIR}" \
    SS_CLOUD_URL="${SS_CLOUD_URL}" \
    nohup "${SS_VAR}/venv/bin/python3" "${SS_VAR}/discover.py" \
        >> "${SS_LOG}/discover.log" 2>&1 &

    local pid=$!
    echo "${pid}" > "${SS_VAR}/discover.pid"

    # Wait briefly for it to come up
    local retries=10
    while [[ $retries -gt 0 ]]; do
        if curl -sf http://localhost:${SS_DISCOVERY_PORT}/health >/dev/null 2>&1; then
            log "Model discovery endpoint is live on :${SS_DISCOVERY_PORT}"
            return 0
        fi
        retries=$((retries - 1))
        sleep 1
    done

    warn "Discovery endpoint not responding after 10s. Check ${SS_LOG}/discover.log"
}

# ─── Step 8: Docker Compose Services ────────────────────────────────────────

setup_compose_services() {
    log "Setting up Docker Compose services..."

    # Create data directories for all services
    mkdir -p "${SS_VAR}/data"/{homepage,stirling-pdf/trainingData,stirling-pdf/extraConfigs,stirling-pdf/customFiles,privatebin,pairdrop,uptime-kuma}

    # Copy docker-compose.yml
    if [[ -f "${SS_COMPOSE_DIR}/docker-compose.yml" ]]; then
        cp "${SS_COMPOSE_DIR}/docker-compose.yml" "${SS_DIR}/docker-compose.yml"
    else
        # Inline fallback — the compose file
        cat > "${SS_DIR}/docker-compose.yml" <<'COMPOSE_EOF'
# ServerStick v1 Services — auto-generated by bootstrap
services:
  homepage:
    image: ghcr.io/benphelps/homepage:latest
    container_name: homepage
    restart: unless-stopped
    ports:
      - "3002:3000"
    volumes:
      - /var/lib/serverstick/data/homepage:/app/config
      - /var/run/docker.sock:/var/run/docker.sock:ro
    environment:
      HOMEPAGE_ALLOWED_HOSTS: "home.serverstick.com"

  stirling-pdf:
    image: frooodle/s-pdf:latest
    container_name: stirling-pdf
    restart: unless-stopped
    ports:
      - "8440:8080"
    volumes:
      - /var/lib/serverstick/data/stirling-pdf/trainingData:/usr/share/tessdata
      - /var/lib/serverstick/data/stirling-pdf/extraConfigs:/configs
    environment:
      DOCKER_ENABLE_SECURITY: "false"
      INSTALL_BOOK_AND_ADVANCED_HTML_OPS: "false"
      SYSTEM_MAXFILESIZE: "50"

  privatebin:
    image: privatebin/nginx-fpm-alpine:latest
    container_name: privatebin
    restart: unless-stopped
    ports:
      - "8084:8080"
    volumes:
      - /var/lib/serverstick/data/privatebin:/srv/data
    read_only: true

  pairdrop:
    image: lscr.io/linuxserver/pairdrop:latest
    container_name: pairdrop
    restart: unless-stopped
    ports:
      - "3000:3000"
    environment:
      PUID: "1000"
      PGID: "1000"
      TZ: "UTC"

  uptime-kuma:
    image: louislam/uptime-kuma:1
    container_name: uptime-kuma
    restart: unless-stopped
    ports:
      - "3001:3001"
    volumes:
      - /var/lib/serverstick/data/uptime-kuma:/app/data

  dozzle:
    image: amir20/dozzle:latest
    container_name: dozzle
    restart: unless-stopped
    ports:
      - "8888:8080"
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock:ro

  rembg:
    image: danielgatis/rembg:latest
    container_name: rembg
    restart: unless-stopped
    ports:
      - "7000:7000"
    command: ["--host", "0.0.0.0", "--port", "7000"]

  watchtower:
    image: containrrr/watchtower:latest
    container_name: watchtower
    restart: unless-stopped
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock:ro
    environment:
      WATCHTOWER_SCHEDULE: "0 0 4 * * *"
      WATCHTOWER_CLEANUP: "true"
      WATCHTOWER_MONITOR_ONLY: "true"
COMPOSE_EOF
    fi

    # Copy homepage config
    if [[ -d "${SS_COMPOSE_DIR}/homepage-config" ]]; then
        cp -r "${SS_COMPOSE_DIR}/homepage-config/"* "${SS_VAR}/data/homepage/"
    fi

    # Pull and start all services
    cd "${SS_DIR}"
    docker compose pull 2>/dev/null || warn "Some images failed to pull (network issue?)"
    docker compose up -d || warn "Some services failed to start"

    log "Docker Compose services deployed."
}

# ─── Step 9: Newt Tunnel ────────────────────────────────────────────────────

setup_newt() {
    if [[ -z "${SS_PANGOLIN_NEWT_ID}" ]] || [[ -z "${SS_PANGOLIN_SECRET}" ]]; then
        warn "PANGOLIN_NEWT_ID / PANGOLIN_SECRET not set. Skipping tunnel setup."
        warn "Run provision-pangolin.sh later to enable remote access."
        return 0
    fi

    log "Setting up Pangolin tunnel..."

    # Install Newt
    local arch newt_arch
    arch=$(dpkg --print-architecture)
    case "$arch" in
        amd64) newt_arch="x86_64" ;;
        arm64) newt_arch="aarch64" ;;
        *) warn "Unsupported arch for Newt: $arch"; return 1 ;;
    esac

    if ! command -v newt &>/dev/null; then
        curl -fsSL "https://github.com/missive/Newt/releases/latest/download/newt-linux-${newt_arch}" \
            -o "${SS_BIN}/newt"
        chmod +x "${SS_BIN}/newt"
        log "Newt installed."
    fi

    # Write Pangolin config
    cat > "${SS_DIR}/pangolin.env" <<EOF
# Pangolin tunnel configuration (generated by ServerStick bootstrap)
NEWT_ID=${SS_PANGOLIN_NEWT_ID}
NEWT_SECRET=${SS_PANGOLIN_SECRET}
NEWT_ENDPOINT=${SS_PANGOLIN_ENDPOINT}
EOF
    chmod 600 "${SS_DIR}/pangolin.env"

    # Install systemd service
    cat > /etc/systemd/system/serverstick-newt.service <<'NEWT_SVC'
[Unit]
Description=ServerStick Pangolin Tunnel (Newt)
After=network-online.target docker.service
Wants=network-online.target

[Service]
Type=simple
EnvironmentFile=/etc/serverstick/pangolin.env
ExecStart=/usr/local/bin/newt --id ${NEWT_ID} --secret ${NEWT_SECRET} --endpoint ${NEWT_ENDPOINT}
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal

NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
NEWT_SVC

    systemctl daemon-reload
    systemctl enable --now serverstick-newt.service
    log "Newt tunnel service installed and enabled."
}

# ─── Step 10: Systemd Services ────────────────────────────────────────────────

install_systemd_services() {
    log "Installing systemd services..."

    # Discovery endpoint systemd service
    cat > /etc/systemd/system/serverstick-discovery.service <<'DISC_SVC'
[Unit]
Description=ServerStick Model Discovery Endpoint
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
EnvironmentFile=/etc/serverstick/env
ExecStart=/var/lib/serverstick/venv/bin/python3 /var/lib/serverstick/discover.py
Restart=always
RestartSec=3
StandardOutput=journal
StandardError=journal

NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
PrivateTmp=true
ReadWritePaths=/var/log/serverstick

[Install]
WantedBy=multi-user.target
DISC_SVC

    systemctl daemon-reload
    systemctl enable serverstick-discovery.service
    systemctl start serverstick-discovery.service || warn "Discovery service failed to start"

    log "Systemd services installed."
}

# ─── Step 11: Write Environment ────────────────────────────────────────────

write_env_file() {
    cat > "${SS_DIR}/env" <<EOF
# ServerStick Environment
# Generated by get.serverstick.sh on $(date -u +"%Y-%m-%dT%H:%M:%SZ")
SERVERSTICK_DIR=${SS_DIR}
SERVERSTICK_VAR=${SS_VAR}
SERVERSTICK_API_BASE=${SS_API_BASE}
SERVERSTICK_DISCOVERY_PORT=${SS_DISCOVERY_PORT}
SERVERSTICK_SOPS_KEY=${SS_SOPS_DIR}/age.key
EOF
    chmod 600 "${SS_DIR}/env"
    log "Environment file written to ${SS_DIR}/env"
}

# ─── Main ─────────────────────────────────────────────────────────────────────

main() {
    log "╔══════════════════════════════════════╗"
    log "║     ServerStick Bootstrap v0.1       ║"
    log "║     Plug in. Take back your data.    ║"
    log "╚══════════════════════════════════════╝"
    echo ""

    require_root
    require_starter_key

    local arch
    arch=$(detect_arch)
    log "Architecture: ${arch}"
    log "API base: ${SS_API_BASE}"

    # 1. Directory structure
    setup_directories

    # 2. Install dependencies
    install_system_packages
    install_docker
    install_nodejs
    install_sops_age

    # 3. SOPS key setup + encrypt starter key
    setup_sops_keys
    encrypt_starter_key

    # 4. Install service setup wizard
    install_setup_wizard

    # 5. Install Pi agent
    install_pi

    # 6. Install and start model discovery
    install_discovery

    # 7. Docker Compose services
    setup_compose_services

    # 8. Newt tunnel (optional — only if credentials provided)
    setup_newt

    # 9. Systemd services
    install_systemd_services

    # 10. Write environment file
    write_env_file

    echo ""
    log "╔══════════════════════════════════════╗"
    log "║     Bootstrap complete!              ║"
    log "╚══════════════════════════════════════╝"
    echo ""
    log "Local services:"
    log "  Dashboard:  http://localhost:3002"
    log "  PDF tools:  http://localhost:8440"
    log "  Pastebin:   http://localhost:8084"
    log "  File share: http://localhost:3000"
    log "  Monitor:    http://localhost:3001"
    log "  Rembg:      http://localhost:7000"
    log "  Discovery:  http://localhost:8080/models"
    echo ""
    if [[ -n "${SS_PANGOLIN_NEWT_ID}" ]]; then
        log "Remote access (Pangolin tunnel):"
        log "  https://home.serverstick.com"
        log "  https://pdf.serverstick.com"
        log "  https://bin.serverstick.com"
        log "  https://drop.serverstick.com"
        log "  https://kuma.serverstick.com"
        log "  https://rembg.serverstick.com"
        log "  https://api.serverstick.com"
        log "  https://pi.serverstick.com"
        echo ""
    else
        log "Remote access: Not configured (run provision-pangolin.sh to enable)"
        echo ""
    fi
    log "Next steps:"
    log "  1. Run service selection wizard:"
    log "     serverstick-setup       (terminal menu)"
    log "     http://localhost:8080/setup  (web wizard)"
    log "  2. Test model discovery: curl http://localhost:8080/models"
    log "  3. Start Pi in RPC mode: pi --mode rpc --no-session"
    echo ""

    # Auto-open setup wizard if a display is available
    if [[ -n "${DISPLAY:-}" ]] && command -v xdg-open &>/dev/null; then
        log "Opening setup wizard in browser..."
        xdg-open "http://localhost:8080/setup" 2>/dev/null || true
    fi

    # Shred installer logs that contain the preseeded key
    if [[ -f /var/log/syslog ]]; then
        log "Shredding installer logs (contain preseeded key)..."
        shred -u /var/log/syslog 2>/dev/null || true
    fi
}

main "$@"