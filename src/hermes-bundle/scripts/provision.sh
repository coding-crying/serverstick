#!/usr/bin/env bash
# ServerStick — Provision this device on Pangolin
# Called by Hermes via /skill pangolin-provision
# Or called by Pi Agent onboarding wizard step 1
#
# Usage: provision.sh <subdomain>
# Reads: SERVERSTICK_PROVISION_API, SERVERSTICK_DEVICE_TOKEN
# Writes: /etc/newt/newt.json, /etc/serverstick/pangolin.json

set -euo pipefail

SUBDOMAIN="${1:-}"
PROVISION_API="${SERVERSTICK_PROVISION_API:-https://api.serverstick.com}"
TOKEN_FILE="/etc/serverstick/device.token"

[[ -z "$SUBDOMAIN" ]] && { echo "Usage: $0 <subdomain>"; exit 1; }
[[ ! -f "$TOKEN_FILE" ]] && { echo "Missing $TOKEN_FILE — get token from Svelte GUI"; exit 1; }

DEVICE_TOKEN=$(cat "$TOKEN_FILE")

log()  { echo -e "\033[0;34m[provision]\033[0m $*"; }
ok()   { echo -e "\033[0;32m[provision]\033[0m ✓ $*"; }
warn() { echo -e "\033[1;33m[provision]\033[0m ⚠ $*"; }
err()  { echo -e "\033[0;31m[provision]\033[0m ✗ $*" >&2; exit 1; }

log "Calling $PROVISION_API/v1/provision ..."
RESPONSE=$(curl -fsS -X POST "$PROVISION_API/v1/provision" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $DEVICE_TOKEN" \
  -d "{\"subdomain\":\"$SUBDOMAIN\"}")

# Parse JSON (requires jq)
NEWT_ID=$(echo "$RESPONSE" | jq -r '.newt_id')
NEWT_SECRET=$(echo "$RESPONSE" | jq -r '.newt_secret')
ORG_ID=$(echo "$RESPONSE" | jq -r '.org_id')
SITE_ID=$(echo "$RESPONSE" | jq -r '.site_id')
API_KEY=$(echo "$RESPONSE" | jq -r '.api_key')

[[ -z "$NEWT_ID" || "$NEWT_ID" == "null" ]] && err "Provision API returned no newt_id: $RESPONSE"

# Write Newt config
mkdir -p /etc/newt
cat > /etc/newt/newt.json << EOF
{
  "id": "$NEWT_ID",
  "secret": "$NEWT_SECRET",
  "endpoint": "https://pangolin.serverstick.com"
}
EOF
chmod 600 /etc/newt/newt.json
ok "Newt config written: /etc/newt/newt.json (id=$NEWT_ID)"

# Write Pangolin API key + org/site for resource management
mkdir -p /etc/serverstick
cat > /etc/serverstick/pangolin.json << EOF
{
  "api_url": "https://pangolin.serverstick.com",
  "api_key": "$API_KEY",
  "org_id": "$ORG_ID",
  "site_id": "$SITE_ID",
  "subdomain": "$SUBDOMAIN"
}
EOF
chmod 600 /etc/serverstick/pangolin.json
ok "Pangolin config written: /etc/serverstick/pangolin.json"

# Enable and start newt
systemctl enable --now serverstick-newt.service
ok "Newt service started"

# Wait for tunnel to connect
log "Waiting for tunnel..."
for i in $(seq 1 30); do
  if systemctl is-active --quiet serverstick-newt; then
    if newt status 2>/dev/null | grep -q "connected"; then
      ok "Tunnel connected"
      break
    fi
  fi
  sleep 1
done

# Verify with a request to the dashboard
log "Verifying $SUBDOMAIN.serverstick.com ..."
sleep 2
if curl -sfI "https://$SUBDOMAIN.serverstick.com" >/dev/null 2>&1; then
  ok "https://$SUBDOMAIN.serverstick.com is live"
else
  warn "Tunnel may still be establishing — check https://$SUBDOMAIN.serverstick.com in a few seconds"
fi

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Device provisioned: https://$SUBDOMAIN.serverstick.com"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
