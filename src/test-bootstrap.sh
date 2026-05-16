#!/usr/bin/env bash
# test-bootstrap.sh — Test ServerStick bootstrap on a bare Debian VM
#
# This runs get.serverstick.sh on an existing Debian install, simulating
# what happens after the ISO installs Debian and runs the late_command.
# Use this for development testing WITHOUT building an ISO first.
#
# Usage:
#   sudo ./test-bootstrap.sh --key sk-ss-...0001
#   sudo ./test-bootstrap.sh --key sk-ss-...0001 --api-base https://tokenrouter.ai/v1
#   sudo ./test-bootstrap.sh --key sk-ss-...0001 --tunnel-id mriqk2z8tyl84jb --tunnel-secret xxx
#
# Prerequisites: Fresh Debian 12 (Bookworm) install with internet access.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BOOTSTRAP="${SCRIPT_DIR}/bootstrap/get.serverstick.sh"
DISCOVER="${SCRIPT_DIR}/discover/discover.py"
COMPOSE="${SCRIPT_DIR}/services/docker-compose.yml"

STARTER_KEY=""
API_BASE="https://api.openai.com/v1"
SKIP_INSTALL=""
PANGOLIN_NEWT_ID=""
PANGOLIN_SECRET=""
PANGOLIN_ENDPOINT="gerbil.pangolin.net:50120"
NO_TUNNEL=""

usage() {
    echo "Usage: $0 --key STARTER_KEY [options]"
    echo ""
    echo "  --key KEY              Starter API key (required)"
    echo "  --api-base URL         API base URL (default: https://api.openai.com/v1)"
    echo "  --tunnel-id ID         Pangolin Newt tunnel ID"
    echo "  --tunnel-secret SECRET Pangolin Newt secret"
    echo "  --tunnel-endpoint URL  Pangolin Gerbil endpoint (default: gerbil.pangolin.net:50120)"
    echo "  --no-tunnel            Skip tunnel setup even if credentials available"
    echo "  --skip-install         Skip Docker/Node/SOPS install (for re-testing)"
    echo "  --help                 Show this help"
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --key)             STARTER_KEY="$2"; shift 2 ;;
        --api-base)        API_BASE="$2"; shift 2 ;;
        --tunnel-id)       PANGOLIN_NEWT_ID="$2"; shift 2 ;;
        --tunnel-secret)   PANGOLIN_SECRET="$2"; shift 2 ;;
        --tunnel-endpoint) PANGOLIN_ENDPOINT="$2"; shift 2 ;;
        --no-tunnel)       NO_TUNNEL="1"; shift ;;
        --skip-install)    SKIP_INSTALL="1"; shift ;;
        --help|-h)         usage; exit 0 ;;
        *)                 echo "Unknown: $1"; usage; exit 1 ;;
    esac
done

if [[ -z "${STARTER_KEY}" ]]; then
    echo "ERROR: --key is required"
    exit 1
fi

if [[ $EUID -ne 0 ]]; then
    echo "ERROR: Run as root (sudo)"
    exit 1
fi

# Clear tunnel if --no-tunnel
if [[ -n "${NO_TUNNEL}" ]]; then
    PANGOLIN_NEWT_ID=""
    PANGOLIN_SECRET=""
fi

echo "╔══════════════════════════════════════╗"
echo "║   ServerStick Test Bootstrap          ║"
echo "║   Testing on this machine directly     ║"
echo "╚══════════════════════════════════════╝"
echo ""

# ─── Option A: Full bootstrap ──────────────────────────────────────────────────

if [[ -z "${SKIP_INSTALL}" ]]; then
    echo "[test] Running full bootstrap..."
    echo "[test] This installs Docker, Node.js, SOPS, age, Pi, Docker Compose services,"
    echo "[test] Newt tunnel, systemd services, and the discovery endpoint."
    echo ""

    export SERVERSTICK_STARTER_KEY="${STARTER_KEY}"
    export SERVERSTICK_API_BASE="${API_BASE}"
    export SERVERSTICK_CLOUD_URL="${CLOUD_URL:-https://api.serverstick.com}"

    # Pass Pangolin credentials if available
    if [[ -n "${PANGOLIN_NEWT_ID}" ]] && [[ -n "${PANGOLIN_SECRET}" ]]; then
        export PANGOLIN_NEWT_ID
        export PANGOLIN_SECRET
        export PANGOLIN_ENDPOINT
        echo "[test] Tunnel credentials provided — Newt will be configured."
    else
        echo "[test] No tunnel credentials — skipping remote access setup."
    fi

    bash "${BOOTSTRAP}"
else
    echo "[test] Skipping install (--skip-install). Reusing existing setup."
    echo "[test] Just restarting services."
fi

# ─── Deploy services from source ────────────────────────────────────────────────

echo ""
echo "[test] Deploying services from source..."

SS_VAR="/var/lib/serverstick"
SS_DIR="/etc/serverstick"

mkdir -p "${SS_VAR}"

# Copy discovery endpoint from source
cp "${DISCOVER}" "${SS_VAR}/discover.py"
chmod +x "${SS_VAR}/discover.py"

# Set up Python venv if needed
if [[ ! -d "${SS_VAR}/venv" ]]; then
    python3 -m venv "${SS_VAR}/venv"
fi
"${SS_VAR}/venv/bin/pip" install --quiet httpx 2>/dev/null || true

# Copy Docker Compose from source
if [[ -f "${COMPOSE}" ]]; then
    cp "${COMPOSE}" "${SS_DIR}/docker-compose.yml"
    echo "[test] Docker Compose file deployed."
fi

# Copy Homepage dashboard config
HOMEPAGE_SRC="${SCRIPT_DIR}/services/homepage-config"
if [[ -d "${HOMEPAGE_SRC}" ]]; then
    mkdir -p "${SS_VAR}/data/homepage"
    cp -r "${HOMEPAGE_SRC}/"* "${SS_VAR}/data/homepage/" 2>/dev/null || true
    echo "[test] Homepage config deployed."
fi

# ─── Start services ─────────────────────────────────────────────────────────────

echo ""
echo "[test] Starting discovery endpoint..."
if [[ -f "${SS_VAR}/discover.pid" ]]; then
    kill "$(cat "${SS_VAR}/discover.pid")" 2>/dev/null || true
    rm -f "${SS_VAR}/discover.pid"
fi

SS_DISCOVERY_PORT=8080 \
SERVERSTICK_DIR="${SS_DIR}" \
SS_CLOUD_URL="${CLOUD_URL:-https://api.serverstick.com}" \
nohup "${SS_VAR}/venv/bin/python3" "${SS_VAR}/discover.py" \
    >> /var/log/serverstick/discover.log 2>&1 &
echo "$!" > "${SS_VAR}/discover.pid"

# Start Docker Compose services
if command -v docker &>/dev/null && [[ -f "${SS_DIR}/docker-compose.yml" ]]; then
    echo "[test] Starting Docker Compose services..."
    cd "${SS_DIR}"
    docker compose up -d 2>/dev/null || echo "[test] WARNING: Some Docker services failed to start"
else
    echo "[test] Docker not available or compose file missing — skipping container services."
fi

# Start Newt tunnel (systemd)
if [[ -n "${PANGOLIN_NEWT_ID}" ]] && [[ -n "${PANGOLIN_SECRET}" ]]; then
    if systemctl is-enabled serverstick-newt.service &>/dev/null; then
        echo "[test] Restarting Newt tunnel..."
        systemctl restart serverstick-newt.service || echo "[test] WARNING: Newt service failed to start"
    else
        echo "[test] Newt service not installed. Run bootstrap with tunnel credentials."
    fi
fi

echo "[test] Waiting for services to come up..."
sleep 3

# ─── Verify ─────────────────────────────────────────────────────────────────────

echo ""
echo "[test] Verifying..."
echo ""

PASS=0
FAIL=0

check_service() {
    local name="$1"
    local url="$2"
    if curl -sf --max-time 5 "${url}" >/dev/null 2>&1; then
        echo "  ✅ ${name}"
        PASS=$((PASS + 1))
    else
        echo "  ❌ ${name}"
        FAIL=$((FAIL + 1))
    fi
}

echo "=== Local Services ==="
check_service "Discovery API" "http://localhost:8080/health"
check_service "Homepage" "http://localhost:3002"
check_service "Stirling-PDF" "http://localhost:8440"
check_service "PrivateBin" "http://localhost:8084"
check_service "PairDrop" "http://localhost:3000"
check_service "Uptime Kuma" "http://localhost:3001"
check_service "Dozzle" "http://localhost:8888"

echo ""
echo "=== Docker Containers ==="
if command -v docker &>/dev/null; then
    docker compose -f "${SS_DIR}/docker-compose.yml" ps --format "table {{.Name}}\t{{.Status}}" 2>/dev/null || echo "  Docker Compose not available"
fi

echo ""
echo "=== Systemd Services ==="
for svc in serverstick-discovery serverstick-newt; do
    if systemctl is-active --quiet "${svc}.service" 2>/dev/null; then
        echo "  ✅ ${svc}.service — active"
    else
        echo "  ⬜ ${svc}.service — not active"
    fi
done

if [[ -n "${PANGOLIN_NEWT_ID}" ]]; then
    echo ""
    echo "=== Pangolin Tunnel ==="
    if systemctl is-active --quiet serverstick-newt.service 2>/dev/null; then
        echo "  ✅ Newt tunnel connected"
    else
        echo "  ❌ Newt tunnel not connected"
        journalctl -u serverstick-newt --no-pager -n 10 2>/dev/null || true
    fi
fi

echo ""
echo "╔══════════════════════════════════════╗"
echo "║   Test Results: ${PASS} passed, ${FAIL} failed        ║"
echo "╚══════════════════════════════════════╝"
echo ""
echo "  Local endpoints:"
echo "    http://localhost:8080/        — Discovery API"
echo "    http://localhost:3002/        — Dashboard"
echo "    http://localhost:8440/        — Stirling PDF"
echo "    http://localhost:8084/        — PrivateBin"
echo "    http://localhost:3000/        — PairDrop"
echo "    http://localhost:3001/        — Uptime Kuma"
echo "    http://localhost:8888/        — Dozzle (logs)"
echo "    http://localhost:7000/        — rembg API"
echo ""

if [[ -n "${PANGOLIN_NEWT_ID}" ]]; then
    echo "  Remote endpoints (via Pangolin tunnel):"
    echo "    https://home.serverstick.com   — Dashboard"
    echo "    https://pdf.serverstick.com    — Stirling PDF"
    echo "    https://bin.serverstick.com    — PrivateBin"
    echo "    https://drop.serverstick.com   — PairDrop"
    echo "    https://kuma.serverstick.com   — Uptime Kuma"
    echo "    https://rembg.serverstick.com  — Background Removal"
    echo "    https://logs.serverstick.com   — Container Logs"
    echo "    https://api.serverstick.com    — Discovery API"
    echo ""
fi

echo "  SSH tunnel (if testing on remote VM):"
echo "    ssh -L 8080:localhost:8080 -L 3002:localhost:3002 user@vm-ip"
echo ""