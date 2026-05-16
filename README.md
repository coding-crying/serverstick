# ServerStick

> USB plug-and-play self-hosting. Zero config. Take back your data.

Plug in the stick. Boot any machine. Your private cloud is live at `*.serverstick.com` — PDF tools, file sharing, monitoring, background removal, AI model routing, all on hardware you control.

## 🔄 Hackathon Sponsors We Use

ServerStick integrates **6 of the hackathon sponsors** into a cohesive self-hosting appliance:

| Sponsor | Integration | How |
|---------|-------------|-----|
| **TokenRouter** | Model gateway | Discovery API routes to the best AI model via TokenRouter's unified API |
| **Z.ai (GLM-5.1)** | Reasoning engine | Ships as the default reasoning model — Opus-level depth for on-device agents |
| **Qwen Cloud** | Fast inference | Available through TokenRouter for agentic coding and multimodal tasks |
| **Zeabur** | Cloud deployment | Demo environment deployed on Zeabur for zero-setup evaluation |
| **Nosana** | GPU marketplace | Future: decentralized GPU backends for local model inference |
| **Butterbase** | Backend-as-a-service | Future: user auth and data persistence for the setup wizard |

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
| Discovery API | AI model routing | api.serverstick.com |

Plus: Pi AI agent, Watchtower (auto-update), SOPS-encrypted secret management, hardware-aware service selection.

## Quick Start

### One-liner install (bare metal / VM)

```bash
curl -fsSL https://serverstick.com/get.sh | \
  SERVERSTICK_STARTER_KEY=sk-ss-xxxxx bash
```

### VM test (with Pangolin tunnel for remote access)

```bash
git clone https://github.com/coding-crying/serverstick.git
cd serverstick

# Test with starter key only (LAN access)
sudo ./src/test-bootstrap.sh --key sk-ss-xxxxx

# Test with remote access via Pangolin tunnel
sudo ./src/test-bootstrap.sh --key sk-ss-xxxxx \
  --tunnel-id mriqk2z8tyl84jb \
  --tunnel-secret your-secret-here
```

### Verify

```bash
curl http://localhost:8080/health     # Health check
curl http://localhost:8080/models      # List available AI models
curl http://localhost:3002             # Dashboard
```

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
│  │  ┌──────────┐ │  └───────────────────────────┘│
│  │  │TokenRouter│ │                              │
│  │  │  GLM-5.1  │ │  ┌─────────────────────────┐│
│  │  │  Qwen     │ │  │  Systemd: newt·sops·age ││
│  │  │  DeepSeek │ │  │  SOPS secrets /etc/ss   ││
│  │  └──────────┘ │  └─────────────────────────┘│
│  └───────────────┘                              │
└─────────────────────────────────────────────────┘
         │
         │  Wireguard (Newt/Pangolin)
         ▼
┌─────────────────────┐
│  Pangolin Cloud     │
│  *.serverstick.com  │
└─────────────────────┘
```

## AI Model Discovery

Every ServerStick ships with a starter key for **TokenRouter** — an OpenAI-compatible proxy that routes to the best model for the task:

```bash
# On-device discovery endpoint
curl http://localhost:8080/models

# 3-tier fallback:
# 1. Cloud API (api.serverstick.com) — cached, fast
# 2. Direct provider (TokenRouter) — live models
# 3. Hardcoded list — works offline

# Default models (GLM-5.1 for reasoning, DeepSeek V4 Flash for speed)
glm-5.1          # Z.ai — Opus-level reasoning
deepseek-chat    # DeepSeek V4 Flash — fast general-purpose
deepseek-reasoner # DeepSeek R1 — chain-of-thought
gpt-4o           # OpenAI — multimodal
gpt-4o-mini      # OpenAI — fast & cheap
claude-sonnet-4  # Anthropic — balanced
```

## Hardware-Aware Setup

The setup wizard scans your hardware and recommends services:

| Hardware | Recommendation |
|----------|---------------|
| < 2GB RAM | Lightweight only (PrivateBin, PairDrop) |
| Has NVIDIA GPU | + rembg background removal |
| Has disk space | + Homepage dashboard, Uptime Kuma |
| Raspberry Pi | ARM-optimized stack |

Choose services via **TUI** (SSH) or **web wizard** (`http://localhost:8080/setup`).

## File Structure

```
src/
├── bootstrap/
│   ├── get.serverstick.sh      # Main bootstrap (11-step automated setup)
│   ├── serverstick-setup.sh    # Hardware scan + service selector
│   └── provision-pangolin.sh   # Standalone Newt tunnel installer
├── cloud/                       # Vercel API (model proxy + caching)
│   ├── api/v1/models.js        # Cloud model discovery fallback
│   ├── api/v1/key-status.js    # Key validation
│   ├── api/v1/register.js      # Device registration
│   └── public/
│       ├── index.html           # Landing page
│       └── get.sh               # curl | bash installer
├── config/
│   └── preseed.cfg.template     # Debian auto-install template
├── discover/
│   └── discover.py              # On-device model discovery API
├── services/
│   ├── docker-compose.yml       # 8 container services
│   ├── serverstick-discovery.service
│   ├── serverstick-newt.service
│   └── homepage-config/services.yaml
└── test-bootstrap.sh            # VM test harness
```

## Configuration

| Environment Variable | Description | Required |
|---------------------|-------------|----------|
| `SERVERSTICK_STARTER_KEY` | API key (TokenRouter/OpenAI-compatible) | Yes |
| `SERVERSTICK_API_BASE` | API base URL | No (default: TokenRouter) |
| `PANGOLIN_NEWT_ID` | Tunnel ID for remote access | No (LAN-only if omitted) |
| `PANGOLIN_SECRET` | Tunnel secret | No |
| `PANGOLIN_ENDPOINT` | Gerbil relay endpoint | No (default: `gerbil.pangolin.net:50120`) |

## Port Map

| Port | Service | Protocol |
|------|---------|----------|
| 3000 | PairDrop | HTTP |
| 3001 | Uptime Kuma | HTTP |
| 3002 | Homepage dashboard | HTTP |
| 6099 | rembg API | HTTP |
| 8080 | Discovery API | HTTP |
| 8084 | PrivateBin | HTTP |
| 8400 | Stirling-PDF | HTTP |
| 9999 | Dozzle | HTTP |

## Credits

Built with:
- **[TokenRouter](https://tokenrouter.ai)** — unified AI model gateway (sponsor 🔄)
- **[Z.ai / GLM-5.1](https://z.ai)** — frontier reasoning model (sponsor 🔄)
- **[Qwen Cloud](https://qwen.ai)** — state-of-the-art agentic coding models (sponsor 🔄)
- **[Zeabur](https://zeabur.com)** — cloud deployment platform (sponsor 🔄)
- **[Pangolin CE](https://github.com/FosyleOrg/pangolin)** — WireGuard tunnel + reverse proxy
- **[Nosana](https://nosana.com)** — decentralized GPU compute (sponsor 🔄)
- Docker, Debian, SOPS, age, Newt, Homepage

## License

ServerStick bootstrap and tooling: **MIT**

Individual services have their own licenses — see each project's repository.