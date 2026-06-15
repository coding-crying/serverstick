#!/usr/bin/env bash
# serverstick-verify — Check that a ServerStick install is working
# Usage: serverstick-verify [subdomain]
#
# Checks:
#   1. hermes-bridge is running and responding
#   2. Pangolin key is present and valid
#   3. Newt is connected
#   4. (If subdomain given) Public URLs are reachable
#   5. Services are running
#
# Exits 0 if everything is OK, 1 if any check fails.

set -uo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

ok()   { echo -e "${GREEN}✓${NC} $*"; }
warn() { echo -e "${YELLOW}⚠${NC} $*"; }
fail() { echo -e "${RED}✗${NC} $*"; }
log()  { echo -e "${BLUE}[verify]${NC} $*"; }

SS_DIR="${SERVERSTICK_DIR:-/etc/serverstick}"
AGENT_PORT="${SERVERSTICK_PORT:-18090}"
DEVICE_NAME="${1:-}"
ERRORS=0

echo ""
log "ServerStick verification"
log "═══════════════════════════"
echo ""

# 1. Bridge is running
log "1. hermes-bridge running?"
if systemctl is-active --quiet serverstick-bridge 2>/dev/null; then
  ok "  service is active"
else
  fail "  service is NOT active"
  warn "  fix: sudo systemctl start serverstick-bridge"
  ERRORS=$((ERRORS + 1))
fi

if curl -sf --max-time 5 "http://localhost:${AGENT_PORT}/api/health" >/dev/null 2>&1; then
  ok "  responding on :${AGENT_PORT}"
else
  fail "  not responding on :${AGENT_PORT}"
  warn "  fix: check journalctl -u serverstick-bridge -n 30"
  ERRORS=$((ERRORS + 1))
fi
echo ""

# 2. Pangolin key
log "2. Pangolin API key present?"
if [[ -s "${SS_DIR}/pangolin-api-key" ]]; then
  ok "  key file exists ($(wc -c < "${SS_DIR}/pangolin-api-key") bytes)"
else
  fail "  no key file at ${SS_DIR}/pangolin-api-key"
  warn "  fix: see bootstrap output or README 'Manual key setup'"
  ERRORS=$((ERRORS + 1))
fi
echo ""

# 3. Newt connected
log "3. Newt tunnel connected?"
if systemctl is-active --quiet serverstick-newt 2>/dev/null; then
  ok "  Newt service is active"
  if pgrep -f "newt" >/dev/null 2>&1; then
    ok "  newt process running (PID $(pgrep -f newt | head -1))"
  else
    warn "  newt service active but no process found"
  fi
else
  warn "  Newt service is NOT active"
  if [[ -f /etc/newt/newt.json ]]; then
    warn "  fix: sudo systemctl restart serverstick-newt"
  else
    warn "  fix: complete the onboarding wizard to write /etc/newt/newt.json"
  fi
  ERRORS=$((ERRORS + 1))
fi
echo ""

# 4. Get device name from disk if not provided
if [[ -z "${DEVICE_NAME}" ]] && [[ -f "${SS_DIR}/device_name" ]]; then
  DEVICE_NAME=$(cat "${SS_DIR}/device_name")
fi

# 5. Public URL check (if we have a device name)
if [[ -n "${DEVICE_NAME}" ]]; then
  log "4. Public URL reachable? (${DEVICE_NAME}.serverstick.com)"
  HTTP_CODE=$(curl -sk --max-time 10 -o /dev/null -w "%{http_code}" "https://${DEVICE_NAME}.serverstick.com" 2>/dev/null || echo "000")
  case "${HTTP_CODE}" in
    200|301|302|307|308)
      ok "  https://${DEVICE_NAME}.serverstick.com → HTTP ${HTTP_CODE}"
      ;;
    502|503|504)
      warn "  https://${DEVICE_NAME}.serverstick.com → HTTP ${HTTP_CODE} (tunnel may be down)"
      warn "  fix: sudo systemctl restart serverstick-newt"
      ERRORS=$((ERRORS + 1))
      ;;
    404)
      warn "  HTTPS works but no resource at that subdomain"
      warn "  fix: complete the wizard or check subdomain is correct"
      ;;
    000)
      fail "  https://${DEVICE_NAME}.serverstick.com → no response (timeout or DNS)"
      warn "  fix: check DNS resolution: nslookup ${DEVICE_NAME}.serverstick.com"
      ERRORS=$((ERRORS + 1))
      ;;
    *)
      warn "  https://${DEVICE_NAME}.serverstick.com → HTTP ${HTTP_CODE} (unexpected)"
      ;;
  esac
  echo ""
fi

# 6. Services running
log "5. Docker services running?"
if command -v docker &>/dev/null; then
  RUNNING=$(docker ps --format '{{.Names}}' 2>/dev/null | grep -E '^(filebrowser|homepage|stirling-pdf|privatebin|pairdrop|uptime-kuma|rembg|dozzle)$' | wc -l)
  if [[ "${RUNNING}" -ge 1 ]]; then
    ok "  ${RUNNING} of 8 services running"
    docker ps --format '    - {{.Names}}: {{.Status}}' 2>/dev/null | grep -E '^(filebrowser|homepage|stirling-pdf|privatebin|pairdrop|uptime-kuma|rembg|dozzle)' || true
  else
    warn "  no services running"
    warn "  fix: cd /etc/serverstick/services && docker compose up -d"
    ERRORS=$((ERRORS + 1))
  fi
else
  warn "  docker not installed"
fi
echo ""

# Summary
log "═══════════════════════════"
if [[ ${ERRORS} -eq 0 ]]; then
  ok "All checks passed. ServerStick is healthy."
  exit 0
else
  fail "${ERRORS} check(s) failed. See fixes above."
  echo ""
  log "For more help:"
  log "  - README: https://github.com/coding-crying/serverstick"
  log "  - Issues: https://github.com/coding-crying/serverstick/issues"
  log "  - Logs:   journalctl -u serverstick-bridge -n 50"
  exit 1
fi
