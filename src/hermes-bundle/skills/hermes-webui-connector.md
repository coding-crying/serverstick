---
name: hermes-webui-connector
description: Connect NemoClaw-wrapped Hermes to the ServerStick Svelte web UI. Binds Hermes' built-in dashboard (port 18789) to the Pi Agent bridge so the Svelte dashboard can talk to Hermes without a separate port.
version: 1.0.0
triggers:
  - "/connect-webui"
  - "link hermes to dashboard"
  - "web ui bridge"
---

# Hermes Web UI Connector

Bind NemoClaw/Hermes into the Pi Agent bridge so the Svelte dashboard can drive it.

## When to use
- After Hermes is onboarded inside NemoClaw
- User opens Svelte dashboard and clicks "Chat with Hermes"
- Hermes dashboard port (18789) needs to be reachable from the dashboard

## What it does
1. Verify NemoClaw sandbox `serverstick` is running: `nemohermes serverstick status`
2. Read Hermes API token from `/sandbox/.hermes/.env` (inside the sandbox) — needs `nemohermes serverstick exec cat /sandbox/.hermes/.env`
3. Pi Agent adds reverse-proxy route: `GET /api/hermes/*` → `http://localhost:18789/*` with bearer auth
4. Write Pi Agent config: `HERMES_API_URL=http://localhost:18789`, `HERMES_TOKEN=<bearer>`
5. Test: `curl -H "Authorization: Bearer $TOKEN" http://localhost:8080/api/hermes/health` returns Hermes health JSON
6. Dashboard can now call `/api/hermes/chat` from the browser

## Gotchas
- Hermes dashboard is on 18789 (TUI bundle) and OpenAI API on 8642 — bind both
- The Hermes token rotates if `nemohermes credentials reset` is run
- Inside NemoClaw, the sandbox can be reached from the host via `localhost` (NemoClaw forwards ports)

## Token extraction script
```bash
NEMOCLAW_CMD="nemohermes"
SANDBOX="serverstick"
TOKEN=$($NEMOCLAW_CMD $SANDBOX exec cat /sandbox/.hermes/.env | grep HERMES_API_TOKEN | cut -d= -f2)
echo "$TOKEN" > /etc/serverstick/hermes.token
chmod 600 /etc/serverstick/hermes.token
```
