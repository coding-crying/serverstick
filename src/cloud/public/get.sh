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
# This script:
#   1. Creates directory structure at /etc/serverstick/
#   2. Installs dependencies (Docker, Node.js, SOPS, age, Python venv)
#   3. Writes the starter key to SOPS-encrypted storage
#   4. Installs Pi (LLM agent harness) with the serverstick-setup skill
#   5. Starts the model discovery endpoint
#   6. Starts Pi in RPC mode

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
SS_DISCOVERY_PORT=8080

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

# ─── Step 4: Install Pi ──────────────────────────────────────────────────────

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

# ─── Step 5: Model Discovery Endpoint ─────────────────────────────────────────

install_discovery() {
    log "Installing model discovery endpoint..."

    local venv="${SS_VAR}/venv"
    python3 -m venv "${venv}"
    "${venv}/bin/pip" install --quiet httpx

    # Copy the discovery server script
    if [[ -f "${SS_VAR}/discover.py" ]]; then
        cp "${SS_VAR}/discover.py" "${SS_VAR}/discover.py"
    else
        # Inline fallback — the discovery server
        cat > "${SS_VAR}/discover.py" <<'PYEOF'
#!/usr/bin/env python3
"""ServerStick Model Discovery Endpoint.

Serves at http://localhost:8080 (or SS_DISCOVERY_PORT).
Reads the starter API key from SOPS-encrypted secrets and queries
the provider's /v1/models endpoint.

Endpoints:
  GET /models      — List available models from the API provider
  GET /models.json — Same, as downloadable JSON
  GET /health      — Health check
  GET /key-status  — Show key usage status (credits remaining, etc.)
"""
import http.server
import json
import os
import subprocess
import sys
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError

SS_DIR = os.environ.get("SERVERSTICK_DIR", "/etc/serverstick")
SS_SECRETS = os.path.join(SS_DIR, "secrets")
SS_SOPS_DIR = os.path.join(SS_DIR, "sops")
PORT = int(os.environ.get("SS_DISCOVERY_PORT", "8080"))

# Cache for decrypted secrets (in-memory only)
_secrets_cache = None


def get_secrets() -> dict:
    """Decrypt SOPS secrets. Cached in-memory for the process lifetime."""
    global _secrets_cache
    if _secrets_cache is not None:
        return _secrets_cache

    try:
        result = subprocess.run(
            ["sops", "--output-type", "json", "-d",
             os.path.join(SS_SECRETS, "keys.enc.yaml")],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode != 0:
            return {"error": f"sops decrypt failed: {result.stderr}"}
        _secrets_cache = json.loads(result.stdout)
    except Exception as e:
        return {"error": str(e)}

    return _secrets_cache


def fetch_models(api_key: str, api_base: str) -> dict:
    """Query the provider's /v1/models endpoint."""
    url = f"{api_base.rstrip('/')}/v1/models"
    headers = {"Authorization": f"Bearer {api_key}"}

    try:
        req = Request(url, headers=headers)
        with urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode())
            return data
    except HTTPError as e:
        body = e.read().decode() if e.fp else ""
        return {"error": f"HTTP {e.code}: {body[:500]}"}
    except URLError as e:
        return {"error": f"Connection failed: {e.reason}"}
    except Exception as e:
        return {"error": str(e)}


class DiscoveryHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        routes = {
            "/": self.handle_index,
            "/health": self.handle_health,
            "/models": self.handle_models,
            "/models.json": self.handle_models,
            "/key-status": self.handle_key_status,
        }
        handler = routes.get(self.path.split("?")[0], self.handle_404)
        handler()

    def handle_index(self):
        """Landing page — shows what endpoints are available."""
        info = {
            "service": "ServerStick Model Discovery",
            "endpoints": {
                "/models": "List available models from API provider",
                "/models.json": "Same, as JSON",
                "/health": "Health check",
                "/key-status": "Starter key status",
            }
        }
        self._json(info)

    def handle_health(self):
        """Health check — can we read SOPS secrets?"""
        secrets = get_secrets()
        if "error" in secrets:
            self._json({"status": "degraded", "error": secrets["error"]}, 503)
        else:
            self._json({"status": "ok"})

    def handle_models(self):
        """Query the provider's model list using the preseeded API key."""
        secrets = get_secrets()
        if "error" in secrets:
            self._json({"error": secrets["error"]}, 500)
            return

        api_key = secrets.get("STARTER_API_KEY", "")
        api_base = secrets.get("STARTER_API_BASE", "https://api.openai.com/v1")

        if not api_key:
            self._json({"error": "No API key in secrets"}, 500)
            return

        models = fetch_models(api_key, api_base)
        if "error" in models:
            self._json(models, 502)
        else:
            self._json(models)

    def handle_key_status(self):
        """Show starter key metadata (not the key itself)."""
        secrets = get_secrets()
        if "error" in secrets:
            self._json({"error": secrets["error"]}, 500)
            return

        # Never expose the actual key — just metadata
        self._json({
            "credits": secrets.get("STARTER_CREDITS", "unknown"),
            "api_base": secrets.get("STARTER_API_BASE", "unknown"),
            "status": secrets.get("STATUS", "unknown"),
            "key_prefix": secrets.get("STARTER_API_KEY", "")[:8] + "..." if secrets.get("STARTER_API_KEY") else "none",
        })

    def handle_404(self):
        self._json({"error": "not found"}, 404)

    def _json(self, data, code=200):
        payload = json.dumps(data, indent=2)
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.write(payload.encode())

    def write(self, data: bytes):
        self.wfile.write(data)

    def log_message(self, format, *args):
        # Quieter logging — only errors
        if "404" in str(args) or "500" in str(args):
            sys.stderr.write(f"[discover] {format}\n" % args)


def main():
    print(f"[discover] ServerStick Model Discovery starting on :{PORT}")
    print(f"[discover] SOPS secrets dir: {SS_SECRETS}")
    server = http.server.HTTPServer(("0.0.0.0", PORT), DiscoveryHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[discover] Shutting down.")
        server.server_close()


if __name__ == "__main__":
    main()
PYEOF
    fi

    chmod +x "${SS_VAR}/discover.py"
    log "Model discovery endpoint installed at ${SS_VAR}/discover.py"
}

# ─── Step 6: Start Services ──────────────────────────────────────────────────

start_discovery() {
    log "Starting model discovery endpoint on :${SS_DISCOVERY_PORT}..."

    # Run in background via nohup (systemd service later, not now)
    SS_DISCOVERY_PORT="${SS_DISCOVERY_PORT}" \
    SERVERSTICK_DIR="${SS_DIR}" \
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

# ─── Step 7: Write Environment ────────────────────────────────────────────────

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

    # 4. Install Pi agent
    install_pi

    # 5. Install and start model discovery
    install_discovery
    start_discovery

    # 6. Write environment
    write_env_file

    echo ""
    log "╔══════════════════════════════════════╗"
    log "║     Bootstrap complete!              ║"
    log "╚══════════════════════════════════════╝"
    echo ""
    log "Model discovery: http://localhost:${SS_DISCOVERY_PORT}/models"
    log "Key status:      http://localhost:${SS_DISCOVERY_PORT}/key-status"
    log "Health check:    http://localhost:${SS_DISCOVERY_PORT}/health"
    echo ""
    log "Next steps:"
    log "  1. Test model discovery: curl http://localhost:${SS_DISCOVERY_PORT}/models"
    log "  2. Start Pi in RPC mode: pi --mode rpc --no-session"
    log "  3. Run setup wizard (coming soon)"
    echo ""

    # Shred installer logs that contain the preseeded key
    if [[ -f /var/log/syslog ]]; then
        log "Shredding installer logs (contain preseeded key)..."
        shred -u /var/log/syslog 2>/dev/null || true
    fi
}

main "$@"