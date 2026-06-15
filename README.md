# ServerStick

USB plug-and-play self-hosting. Zero config. Take back your data.

```bash
curl -fsSL https://get.serverstick.com/install.sh | sudo bash
# open http://localhost:18090
# pick a subdomain (e.g. "mybox")
# pick services, pick AI tier
# done — your stuff is live at <service>.<subdomain>.serverstick.com
```

## What it is

ServerStick turns any Linux box into a self-hosted server with HTTPS, public
URLs, and an AI sysadmin — in one command. No port forwarding, no DNS, no
nginx configs, no certificates to renew.

You plug a USB stick into a fresh Debian box, run the bootstrap, and walk
away. A few minutes later you have a homepage, file browser, PDF tools,
encrypted pastebin, uptime monitor, and an AI agent you can chat with —
all on `*.serverstick.com` subdomains, all HTTPS, all public (or private,
your call).

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│ User's machine (any Linux: Debian, Fedora, Arch)            │
│                                                             │
│  hermes-bridge (FastAPI :18090) ◄── Svelte dashboard        │
│       │                                                     │
│       │ HTTP                                                 │
│       ▼                                                     │
│  NemoClaw + Hermes (AI sysadmin, :18789 / :8642)            │
│       │                                                     │
│       │ docker compose                                      │
│       ▼                                                     │
│  8 service containers (Stirling, PrivateBin, ...)           │
│       │                                                     │
│       │ wireguard tunnel                                    │
│       ▼                                                     │
│  Newt tunnel client ────────────► Pangolin on VPS           │
│                                  (reverse proxy + TLS)      │
└─────────────────────────────────────────────────────────────┘
                                        │
                                        ▼
                              *.serverstick.com
```

### Components

| Component | What | Where |
|---|---|---|
| `bootstrap.sh` | One-command installer | runs on user machine |
| `hermes-bridge` | FastAPI: HTTP→system translator (300 lines) | runs on user machine |
| `hermes-bundle` | Skills + scripts for the AI agent | bundled, deployed to NemoClaw |
| NemoClaw + Hermes | AI sysadmin (NVIDIA) | runs on user machine |
| Newt | WireGuard tunnel client | runs on user machine |
| Pangolin | Reverse proxy + TLS + DNS | hosted on our VPS |
| 8 services | Self-hosted apps | Docker on user machine |

## The 8 services (shipped by default)

| Service | Subdomain | What it does |
|---|---|---|
| 📁 File Browser | `files` | Web file manager |
| 🏠 Homepage | `home` | Server dashboard |
| 📑 Stirling PDF | `pdf` | PDF tools (merge, split, OCR) |
| 📋 PrivateBin | `bin` | Encrypted pastebin |
| 📁 PairDrop | `drop` | AirDrop-style file sharing |
| 📈 Uptime Kuma | `kuma` | Uptime monitor |
| 🖼️ rembg | `rembg` | Background removal |
| 📜 Dozzle | `logs` | Real-time container logs |

## Repository layout

```
src/
├── bootstrap/
│   ├── bootstrap.sh              ← the curl|bash installer
│   └── provision-pangolin.sh     ← one-off VPS Pangolin bootstrap
├── hermes-bridge/
│   ├── main.py                   ← FastAPI bridge (HTTP ↔ system)
│   └── dashboard/                ← Svelte 5 web UI
├── hermes-bundle/
│   ├── SOUL.md                   ← Hermes agent system prompt
│   ├── manifest.json             ← bundle metadata
│   ├── skills/                   ← 6 custom skills for Hermes
│   ├── scripts/                  ← bash scripts (apply-tier, etc.)
│   └── config/                   ← env templates
├── services/
│   └── docker-compose.yml        ← the 8 services
└── config/
    └── preseed.cfg.template      ← Debian preseed for USB imaging
```

## How provisioning works

1. User runs `curl | bash` → bootstrap installs system deps, Docker, Node, NemoClaw, Newt, hermes-bridge
2. Svelte dashboard opens at `:18090`
3. User picks a subdomain (e.g. `mybox`)
4. Bridge calls Pangolin API:
   - `PUT /v1/org/serverstick/site` → creates `mybox.serverstick.com` site (idempotent via local cache)
   - `PUT /v1/org/serverstick/resource` × 8 → creates `pdf.mybox`, `files.mybox`, etc.
   - `PUT /v1/resource/{id}/target` → wires each subdomain to `127.0.0.1:{port}`
   - `POST /v1/resource/{id}` → makes each public (sso=false)
5. Newt config written to `/etc/newt/newt.json`, Newt tunnel connects
6. `docker compose up -d` starts all 8 services
7. User picks AI tier (BYO key / local / managed), `apply-tier.sh` runs `nemohermes onboard`

Total time: ~5 minutes on a fresh box.

## Idempotency

Re-running `curl | bash` is safe — won't duplicate sites, resources, or services.
Re-running the subdomain step on the dashboard reuses the existing site.

The bridge maintains `/etc/serverstick/resources.json` as a local cache of
created Pangolin resources. This is the only reliable way to do lookups,
because Pangolin's Integration API has no list endpoints.

## Building from source

```bash
git clone https://github.com/coding-crying/serverstick.git
cd serverstick

# Build the Svelte dashboard
cd src/hermes-bridge/dashboard
npm install
npm run build
cd ../../..

# Build the code tarball (excludes node_modules and .venv)
tar czf /tmp/serverstick-code.tar.gz --exclude='node_modules' --exclude='.venv' src/

# Deploy to VPS hosting get.serverstick.com
scp /tmp/serverstick-code.tar.gz nlvps:/opt/serverstick/get/
```

## Status

Working as of 2026-06-15:
- [x] Single-command install on Debian/Fedora/Arch
- [x] HTTPS on subdomains via Pangolin + Newt tunnel
- [x] 8 services running on first install
- [x] AI agent (Hermes) integrated via NemoClaw
- [x] Idempotent provisioning (no duplicate sites/resources)
- [x] Public resources by default (no SSO wall)

Not yet:
- [ ] Multi-tenant (one Pangolin org, many users)
- [ ] Billing / quota tracking
- [ ] Custom domains (currently only `*.serverstick.com`)
- [ ] Encrypted-at-rest service data
- [ ] ARM build (works on x86_64 only)

## License

Private for now. Will move to MIT when the API key situation is resolved.
