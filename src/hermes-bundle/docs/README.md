# ServerStick Hermes Bundle

This directory bundles everything NemoClaw-wrapped Hermes needs to operate as a ServerStick sysadmin.

## Contents

```
hermes-bundle/
├── manifest.json              — skill + script + config registry
├── skills/                    — custom Hermes skills (markdown)
│   ├── pangolin-provision.md
│   ├── pangolin-resource.md
│   ├── llmfit-scan.md
│   ├── install-service.md
│   ├── hermes-webui-connector.md
│   └── hermes-tier-switch.md
├── scripts/                   — bash scripts skills invoke
│   ├── provision.sh
│   ├── apply-tier.sh
│   └── llmfit-scan.sh
├── config/                    — env templates (Svelte GUI fills these in)
│   ├── tier.env.template
│   └── nemoclaw.env.template
├── self-hosted-infra/         — NemoClaw sandbox internal config
│   ├── README.md
│   ├── models/                — bundled GGUF files (optional, git-lfs)
│   ├── configs/
│   │   ├── inference.local.yaml
│   │   └── network-policy.yaml
│   └── bin/                   — bundled llama-server fallback
└── docs/                      — developer + GUI builder docs
```

## How it flows

1. **Bootstrap (`curl | bash`)** installs NemoClaw + Hermes, Pi Agent, Newt, Svelte
2. **Svelte GUI** opens at `http://<lan-ip>:8080`
3. **GUI step 1**: User picks subdomain → GUI calls `provision.sh` via Pi Agent
4. **GUI step 2**: User picks services → GUI calls `install-service` skill (via Hermes or Pi Agent)
5. **GUI step 3**: User picks AI tier (local/byo/managed) → GUI writes `tier.env`, calls `apply-tier.sh`
6. **GUI step 4** (optional): User connects WhatsApp/Matrix → GUI calls `hermes gateway install`
7. **Svelte dashboard** moves from `http://<lan-ip>:8080` to `https://dashboard.<sub>.serverstick.com`

## For the Svelte builder

The Svelte GUI needs to:

1. **Step 1 — Provision**
   - Form: subdomain input
   - POST to Pi Agent `/api/provision` with subdomain
   - Pi Agent calls `scripts/provision.sh` and returns `{tunnel_status, url}`

2. **Step 2 — Pick services**
   - Display catalog from Pi Agent `/api/catalog`
   - User checks boxes
   - POST `/api/install-services` with `{"services": ["homepage", "stirling-pdf", ...]}`
   - Pi Agent (or Hermes via skill) installs and exposes each

3. **Step 3 — Pick AI tier**
   - Display `llmfit-scan` results (call `/api/hardware`)
   - Three cards: Local (recommended model from scan), BYO (key input), Managed (auto)
   - On submit, write `tier.env` and call `/api/apply-tier`
   - Show live terminal output via xterm.js + WebSocket during apply

4. **Step 4 — Connect messaging** (optional)
   - Checkboxes for WhatsApp / Discord / Telegram / Matrix
   - On submit, call `/api/connect-messaging`
   - For WhatsApp: show QR code from `hermes gateway install --channel whatsapp` output

## For the Hermes skill runtime

Hermes reads the skills from `~/.hermes/profiles/serverstick/skills/` (or whatever path is configured in `config.yaml`). The bundle can be installed to that path by:

```bash
cp -r /opt/serverstick/src/hermes-bundle/skills/* /root/.hermes/profiles/serverstick/skills/
```

## Notes for the GUI

- **xterm.js** is for displaying terminal output during long-running steps (especially step 3 if llama.cpp needs to compile/download a model)
- **xterm.js connects to Pi Agent's WebSocket** at `ws://<host>:8080/ws/terminal`
- The WebSocket streams subprocess PTY output — same stream the bootstrap uses

## Testing on a clean machine

Once you have the Svelte UI built, you can test the full flow on a fresh Proxmox VM. The test would be:

1. `curl -fsSL https://get.serverstick.com | sudo bash` on a fresh Debian VM
2. Browser opens to `http://<vm-ip>:8080` (or `https://get.serverstick.com/install.sh` if you have a way to test tunnel-only)
3. Walk through the 4 GUI steps
4. Verify `https://<sub>.serverstick.com` is reachable
5. Verify `https://chat.<sub>.serverstick.com:18789` (Hermes dashboard) is up
