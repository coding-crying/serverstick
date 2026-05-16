# ServerStick

> USB plug-and-play self-hosting. Zero config. Take back your data.

Plug in the stick. Install Debian. Get your own private cloud — PDF tools, pastebin, file sharing, monitoring, background removal, all with a `.serverstick.com` hostname accessible from anywhere.

## What's in the Box

| Service | What it replaces | URL |
|---------|-----------------|-----|
| Homepage | Dashboard | home.serverstick.com |
| Stirling-PDF | ilovepdf / smallpdf | pdf.serverstick.com |
| PrivateBin | Pastebin / GitHub gists | bin.serverstick.com |
| PairDrop | WeTransfer / Drive links | drop.serverstick.com |
| Uptime Kuma | UptimeRobot / Pingdom | kuma.serverstick.com |
| Dozzle | Container log viewer | logs.serverstick.com |
| rembg | remove.bg | rembg.serverstick.com |
| Discovery API | Model routing | api.serverstick.com |

Plus: Pi AI agent, Watchtower (auto-update monitor), SOPS-encrypted secret management.

## Quick Start (VM Testing)

### Prerequisites

- Debian 12 (Bookworm) VM with internet access
- 2GB+ RAM, 20GB+ disk
- Root/sudo access
- An API key with ~20 credits (OpenAI, TokenRouter, etc.)

### 1. Clone and Run

```bash
git clone https://github.com/earendil-works/serverstick.git
cd serverstick

# Test bootstrap on a fresh Debian VM
sudo ./src/test-bootstrap.sh --key sk-ss-...0001

# With Pangolin tunnel (remote access)
sudo ./src/test-bootstrap.sh --key sk-ss-...0001 \
  --tunnel-id mriqk2z8tyl84jb \
  --tunnel-secret your-secret-here

# Skip re-installing dependencies (for re-testing)
sudo ./src/test-bootstrap.sh --key sk-ss-...0001 --skip-install
```

### 2. Verify

```bash
# Health check
curl http://localhost:8080/health

# Model discovery
curl http://localhost:8080/models

# Dashboard
curl http://localhost:3002
```

### 3. Remote Access (Optional)

If you've set up Pangolin tunnel credentials, your services are accessible at `https://*.serverstick.com`. Otherwise, everything works on LAN via `http://serverstick.local` (avahi/mDNS).

## Architecture

```
┌─────────────────────────────────────────────────┐
│                  ServerStick Device              │
│                                                  │
│  ┌──────────────┐  ┌───────────────────────────┐│
│  │  Newt tunnel  │  │  Docker Compose           ││
│  │  (systemd)    │  │  ┌─────┐ ┌─────┐ ┌─────┐ ││
│  │               │  │  │Home-│ │PDF  │ │Bin  │ ││
│  │  gerbil.      │  │  │page │ │     │ │     │ ││
│  │  pangolin.net │  │  └─────┘ └─────┘ └─────┘ ││
│  │       :50120  │  │  ┌─────┐ ┌─────┐ ┌─────┐ ││
│  │       ⇅       │  │  │Drop │ │Kuma │ │Doz- │ ││
│  └──────┬────────┘  │  │     │ │     │ │zle  │ ││
│         │           │  └─────┘ └─────┘ └─────┘ ││
│         │           │  ┌─────┐ ┌─────┐         ││
│  ┌──────┴────────┐  │  │rembg│ │Watch│         ││
│  │ Discovery API  │  │  │     │ │tower│         ││
│  │ :8080 (host)  │  │  └─────┘ └─────┘         ││
│  └───────────────┘  └───────────────────────────┘│
│                                                  │
│  ┌───────────────────────────────────────────┐   │
│  │  Systemd: discovery·newt·sops·age        │   │
│  │  SOPS-encrypted secrets /etc/serverstick  │   │
│  └───────────────────────────────────────────┘   │
└─────────────────────────────────────────────────┘
         │
         │  Wireguard (Newt/Pangolin)
         ▼
┌─────────────────────┐
│  Pangolin Cloud     │
│  *.serverstick.com  │
└─────────────────────┘
```

## File Structure

```
src/
├── bootstrap/
│   ├── get.serverstick.sh      # Main bootstrap script
│   └── provision-pangolin.sh   # Standalone Newt installer
├── cloud/                       # Vercel API (model proxy, key validation)
├── config/
│   └── preseed.cfg.template     # Debian auto-install template
├── discover/
│   ├── discover.py              # Model discovery endpoint
│   └── fallback-models.json     # Hardcoded model list
├── services/
│   ├── docker-compose.yml       # All container services
│   ├── Dockerfile.discovery     # Discovery API (unused, host-level)
│   ├── serverstick-discovery.service
│   ├── serverstick-newt.service
│   └── homepage-config/
│       └── services.yaml        # Dashboard widget config
├── skills/
│   └── serverstick-setup/       # Pi skill for self-hosting
├── build-iso.sh                 # ISO builder
└── test-bootstrap.sh            # VM testing script
```

## Configuration

Template placeholders (replaced during ISO build or test):

| Placeholder | Description | Required |
|------------|-------------|----------|
| `%%STARTER_KEY%%` | API key with ~20 credits | Yes |
| `%%PANGOLIN_NEWT_ID%%` | Pangolin tunnel ID | No (LAN-only if omitted) |
| `%%PANGOLIN_SECRET%%` | Pangolin tunnel secret | No (LAN-only if omitted) |
| `%%PANGOLIN_ENDPOINT%%` | Gerbil relay endpoint | No (default: `gerbil.pangolin.net:50120`) |

## Port Map

| Port | Service | Protocol |
|------|---------|----------|
| 3000 | PairDrop | HTTP |
| 3001 | Uptime Kuma | HTTP |
| 3002 | Homepage dashboard | HTTP |
| 7000 | rembg API | HTTP |
| 8080 | Discovery API | HTTP |
| 8084 | PrivateBin | HTTP |
| 8440 | Stirling-PDF | HTTP |
| 8888 | Dozzle | HTTP |

## License

ServerStick bootstrap and tooling: MIT

Individual services have their own licenses — see each project's repository.