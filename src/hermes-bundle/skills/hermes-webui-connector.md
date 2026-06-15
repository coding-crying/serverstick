---
name: hermes-webui-connector
description: Connect NemoClaw-wrapped Hermes to the ServerStick Svelte web UI. The hermes-bridge already proxies Hermes chat — this skill verifies and fixes the connection.
version: 2.0.0
triggers:
  - "/connect-webui"
  - "link hermes to dashboard"
  - "web ui bridge"
---

# Hermes Web UI Connector

Verify that Hermes is reachable from the Svelte dashboard via the hermes-bridge.

## When to use
- After Hermes is onboarded inside NemoClaw
- User opens dashboard and Hermes shows "offline"
- Troubleshooting chat connectivity

## What it does
1. Check bridge is up: `curl -sf http://localhost:{SERVERSTICK_PORT}/api/status`
2. Check NemoClaw/Hermes is running: `curl -sf http://localhost:8642/health`
3. If Hermes is down: `nemohermes serverstick start` (or `nemoclaw serverstick start`)
4. Verify bridge can proxy: `curl -sf http://localhost:{SERVERSTICK_PORT}/api/hermes/logs`
5. Dashboard chats via WebSocket at `ws://localhost:{SERVERSTICK_PORT}/ws/chat` → bridge proxies to NemoClaw `:8642`

## Architecture
```
Browser → Svelte Dashboard
  → WS ws://localhost:18090/ws/chat
    → hermes-bridge (FastAPI)
      → NemoClaw API http://localhost:8642/v1/chat/completions
        → Hermes agent (inside sandbox)
```

## Port mapping
- Bridge (Svelte dashboard): `SERVERSTICK_PORT` (default 18090)
- NemoClaw API (OpenAI-compatible): `8642`
- NemoClaw dashboard: `18789`

## Gotchas
- The bridge port is in `/etc/serverstick/agent.env` as `SERVERSTICK_PORT`
- Inside NemoClaw, the sandbox forwards ports to the host
- Hermes token is managed by NemoClaw, not the bridge
- If `nemohermes` is not found, try `nemoclaw` — command name varies by install

## Quick fix commands
```bash
# Check everything
curl -sf http://localhost:18090/api/status

# Start Hermes if down
nemohermes serverstick start

# Restart bridge
systemctl restart serverstick-bridge
```
