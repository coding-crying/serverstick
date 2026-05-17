# ServerStick — Architecture v2

> USB stick → plug in → self-hosting in 10 minutes. Zero config.

## The Big Picture

```
USB Stick (hardware)
├── Embedded: starter_key, device_id, Pangolin provisioning blueprint
├── Debian netinst ISO with preseed
└── After install → reformatted as restic backup drive

ServerStick Device (the installed machine)
├── Pi Agent (Svelte UI + FastAPI + skill engine)
│   ├── Local dashboard: http://<lan-ip>:8080
│   ├── Remote dashboard: https://dash.<device>.serverstick.com
│   └── Skill plugins: per-service install/config/manage
├── Docker Compose (stateless services)
├── Newt (WireGuard tunnel to Pangolin Cloud)
└── SOPS + age (encrypted secrets)

Pangolin Cloud
├── Site per device (e.g. "nick" → siteId 14913)
├── Resources per service (pdf.nick, home.nick, dash.nick, ...)
├── Auto-provisioned TLS certs per subdomain
└── Access policies, identity, RBAC (future)

Cloud API (Vercel: api.serverstick.com)
├── POST /v1/register — device beacon
├── POST /v1/provision — generate Pangolin site + blueprint + key
├── GET  /v1/models — model discovery proxy
└── GET  /v1/key-status — key validation
```

## Architecture Decisions

### 1. Starter Key on the Stick

The USB stick ships with a `starter_key` embedded in the preseed. This is:
- ~20 credits, low value, leakage-tolerant
- Used during initial setup for LLM calls (Pi agent)
- Consumed by Pi agent during first-boot wizard
- Replaced by earnings key (XMR mining) once device is operational

**Preseed template placeholders:**
```
%%STARTER_KEY%%        — TokenRouter API key (embedded during ISO build)
%%PANGOLIN_NEWT_ID%%   — Pre-provisioned Newt ID (or empty for LAN-only)
%%PANGOLIN_SECRET%%    — Pre-provisioned Newt secret (or empty for LAN-only)
```

The starter key is also available to Pi agent via SOPS-encrypted secrets on the installed system.

### 2. Pi Agent with Skill Plugins

Pi Agent is the on-device brain. It's a FastAPI backend + Svelte frontend that:

1. **Runs on first boot** — hardware scan, service selection, tunnel setup
2. **Serves the dashboard** — local and remote
3. **Manages services** — start, stop, configure, monitor via skill plugins
4. **Routes LLM calls** — cheap model by default, upgrade when needed

#### Skill Plugin System

Each service has a skill plugin that knows how to:
- Install (docker pull, compose up)
- Configure (env vars, volumes, secrets)
- Health check (HTTP endpoint, container status)
- Expose (Pangolin resource creation)

```yaml
# Example: src/agent/skills/rembg.yaml
name: rembg
display: Background Removal
replaces: remove.bg
icon: ✂️
category: media

docker:
  image: danielgatis/rembg
  port: 7000
  volumes:
    - /var/lib/serverstick/data/rembg:/cache

health:
  endpoint: /
  method: GET
  expect_status: 200

pangolin:
  subdomain: rembg
  # Combined with device name → rembg.nick.serverstick.com

llm_cost: low   # cheap model is fine for service management
```

Skills are YAML definitions + optional Python hooks. The agent loads them and knows
which Docker images to pull, which ports to map, and which subdomains to claim.

#### Skill Plugin Categories

| Category | Examples | LLM Tier |
|----------|----------|----------|
| service_mgmt | install, configure, restart, update | flash (cheap) |
| diagnostics | health check, logs, connectivity | flash (cheap) |
| troubleshooting | parse errors, suggest fixes | reasoning (GLM 5.1) |
| setup_wizard | first-boot config, key entry | flash (cheap) |
| security | access policies, TLS status | reasoning (GLM 5.1) |

### 3. Model Routing

Two-tier LLM routing between DeepSeek V4 Flash (cheap) and GLM 5.1 (powerful):

```
┌──────────────────────────┐
│  Pi Agent (FastAPI)      │
│                          │
│  /v1/chat/completions    │
│       │                  │
│  ┌────▼─────┐            │
│  │  Router   │            │
│  └────┬─────┘            │
│       │                  │
│  ┌────┴─────────────┐    │
│  │  classify()      │    │
│  │  complexity: low  │───▶│  DeepSeek V4 Flash
│  │  complexity: high │───▶│  GLM 5.1
│  │  complexity: ?    │───▶│  GLM 5.1 (safe default)
│  └──────────────────┘    │
│                          │
│  TokenRouter API key     │
│  (starter_key → earnings)│
└──────────────────────────┘
```

**Routing logic:**
- Service management, status checks, simple config → `deepseek-chat` (V4 Flash)
- Troubleshooting, security decisions, complex setup → `glm-5.1`
- Unknown/ambiguous → `glm-5.1` (never silently downgrade)
- Explicit user chat (dashboard) → `glm-5.1` (they asked, give them the best)

**Implementation:**
```python
# src/agent/router.py
SERVICE_MGMT_PATTERNS = [
    "start", "stop", "restart", "status", "install",
    "health", "logs", "update", "backup"
]

async def route_model(prompt: str, context: str = "") -> str:
    """Return the model ID to use based on task complexity."""
    prompt_lower = prompt.lower()

    # Any pattern match → cheap model
    if any(p in prompt_lower for p in SERVICE_MGMT_PATTERNS):
        return "deepseek-chat"

    # Explicit user chat → best model
    if context == "user_chat":
        return "glm-5.1"

    # Default to reasoning model
    return "glm-5.1"
```

The router is dead simple now. We can upgrade to embedding-based classification later.
The key principle: never silently downgrade. When in doubt, use the reasoning model.

### 4. Dashboard (Svelte)

**Local first, remote second:**

| Phase | URL | Auth |
|-------|-----|------|
| Setup (first boot) | `http://serverstick.local:8080` | None (LAN only) |
| Remote | `https://dash.<device>.serverstick.com` | Pangolin identity |
| Central (future) | `https://app.serverstick.com` | Pangolin SSO |

**Svelte app structure:**
```
src/agent/dashboard/
├── src/
│   ├── lib/
│   │   ├── api.ts          — FastAPI client
│   │   ├── stores.ts       — Svelte stores (services, status, config)
│   │   └── router.ts       — Client-side routing
│   ├── routes/
│   │   ├── +layout.svelte  — App shell (sidebar, nav)
│   │   ├── +page.svelte    — Dashboard home (service grid)
│   │   ├── setup/
│   │   │   └── +page.svelte — First-boot wizard
│   │   ├── services/
│   │   │   └── [id]/
│   │   │       └── +page.svelte — Service detail/config
│   │   ├── tunnel/
│   │   │   └── +page.svelte — Pangolin tunnel status
│   │   └── settings/
│   │       └── +page.svelte — Security, keys, backup
│   ├── App.svelte
│   └── main.ts
├── static/
├── package.json
└── svelte.config.js
```

**Key screens:**
1. **Setup Wizard** — First boot: device name, subdomain picker, service selection, starter key
2. **Dashboard** — Grid of services with status, quick toggle on/off
3. **Service Detail** — Config, logs, health, subdomain info
4. **Tunnel** — Pangolin connection status, bandwidth, resources list
5. **Settings** — Security policies, key management, backup status

### 5. Provisioning Flow (Revised)

```
User buys stick → plugs in → boots

1. Debian installs to disk (preseed)
2. Pi Agent starts (systemd, LAN-only mode)
3. User opens http://serverstick.local:8080

   ┌──────────────────────────────────────────┐
   │  🚀 Welcome to ServerStick               │
   │                                          │
   │  Device name: [nick________]             │
   │                                          │
   │  Your services will be at:               │
   │  • dash.nick.serverstick.com             │
   │  • pdf.nick.serverstick.com             │
   │  • home.nick.serverstick.com             │
   │                                          │
   │  Select services:                        │
   │  ☑ Stirling PDF       ☑ PrivateBin       │
   │  ☑ PairDrop           ☑ Uptime Kuma      │
   │  ☑ Homepage           ☑ rembg            │
   │  ☐ Home Assistant     ☐ SearXNG          │
   │                                          │
   │  [Start Setup]                            │
   └──────────────────────────────────────────┘

4. Pi Agent calls Cloud API:
   POST /v1/provision
   {
     "device_id": "ss-a1b2c3",
     "device_name": "nick",
     "starter_key_prefix": "sk-tr-...",
     "services": ["pdf", "bin", "drop", "kuma", "rembg", "home"]
   }

5. Cloud API:
   a. Creates Pangolin site "nick"
   b. Creates provisioning key for that site
   c. Returns: { site_id, newt_id, newt_secret, resources: [...] }

6. Pi Agent:
   a. Configures Newt with returned credentials
   b. Starts Docker services (selected ones only)
   c. Creates SOPS secrets (Pangolin creds, starter key)
   d. Newt connects → Pangolin auto-provisions TLS certs
   e. Dashboard goes live at dash.nick.serverstick.com

7. USB stick → reformatted as restic backup drive
   (or kept as-is for future reinstall)
```

### 6. Pangolin Resource Auto-Provisioning

Using **Blueprints** — Pangolin's built-in fleet provisioning system:

```yaml
# Provisioning blueprint applied when Newt first connects
resources:
  - name: Dashboard
    subdomain: "dash.{{device_name}}"
    domain: serverstick.com
    targetType: http
    targets:
      - siteId: "{{site_id}}"
        ip: "127.0.0.1"
        port: 8080

  - name: Homepage
    subdomain: "home.{{device_name}}"
    targetType: http
    targets:
      - siteId: "{{site_id}}"
        ip: "127.0.0.1"
        port: 3002

  # ... one per service
```

The `{{device_name}}` template variable is set by the provisioning key.
Pangolin fills it in when the site connects for the first time.

**This eliminates the need for API calls to create resources** — the blueprint
auto-creates everything when the site comes online.

### 7. Data Flow

```
┌──────────┐      HTTPS       ┌───────────────┐     WireGuard    ┌──────────────┐
│  Browser  │─────────────────▶│   Pangolin     │◀────────────────▶│    Newt      │
│           │  dash.nick.ss.c  │   Cloud        │   tunnel        │  (on device) │
└──────────┘                  └───────────────┘                  └──────┬───────┘
                                                                       │
                                                                ┌───────▼────────┐
                                                                │  Pi Agent       │
                                                                │  (FastAPI :8080)│
                                                                │                 │
                                                                │  ┌───────────┐  │
                                                                │  │ Skill     │  │
                                                                │  │ Engine    │  │
                                                                │  └─────┬─────┘  │
                                                                │        │        │
                                                                │  ┌─────▼─────┐  │
                                                                │  │ LLM Router │  │
                                                                │  │ flash/glm  │  │
                                                                │  └─────┬─────┘  │
                                                                │        │        │
                                                                │  ┌─────▼─────┐  │
                                                                │  │ TokenRouter│  │
                                                                │  │ API (cloud)│  │
                                                                │  └───────────┘  │
                                                                └────────────────┘
```

## Tech Stack

| Component | Technology | Why |
|-----------|-----------|-----|
| Agent Backend | FastAPI (Python) | Async, WebSocket support, Pi was gonna be Python anyway |
| Dashboard | Svelte 5 + SvelteKit | Tiny bundle, reactive, SSR for first load |
| Service Runtime | Docker Compose v2 | Industry standard, well-documented |
| Tunnel | Newt (Pangolin) | Managed WireGuard, auto-provisioning |
| Secrets | SOPS + age | No server process, CLI-only, works offline |
| LLM | TokenRouter (flash + glm) | Two-tier routing, pay-per-use |
| Cloud API | Vercel (serverless) | Zero ops, fast, free tier covers alpha |
| Provisioning | Pangolin Blueprints | Auto-creates resources on site connect |

## Directory Structure (target)

```
src/
├── agent/                    # Pi Agent (everything on-device)
│   ├── main.py               # FastAPI app entry point
│   ├── router.py             # LLM model router (flash/glm)
│   ├── skills/                # Skill plugins
│   │   ├── _base.py           # Skill base class
│   │   ├── service_mgmt.py   # Install/start/stop/restart services
│   │   ├── diag.py           # Diagnostics, health checks
│   │   ├── tunnel.py         # Newt/Pangolin tunnel management
│   │   ├── secrets.py        # SOPS key operations
│   │   └── catalog/           # Per-service YAML definitions
│   │       ├── rembg.yaml
│   │       ├── stirling-pdf.yaml
│   │       ├── privatebin.yaml
│   │       ├── pairdrop.yaml
│   │       ├── uptime-kuma.yaml
│   │       ├── homepage.yaml
│   │       ├── dozzle.yaml
│   │       └── homeassistant.yaml
│   ├── dashboard/             # SvelteKit app
│   │   ├── src/
│   │   ├── static/
│   │   ├── package.json
│   │   └── svelte.config.js
│   └── Dockerfile             # Agent container (or host systemd)
│
├── bootstrap/                # First-boot scripts
│   ├── get.serverstick.sh    # curl | bash entry point
│   ├── provision-pangolin.sh # Newt tunnel setup
│   └── serverstick-setup.sh  # Main setup orchestrator
│
├── cloud/                    # Vercel serverless API
│   ├── api/
│   │   └── v1/
│   │       ├── register.js   # Device beacon
│   │       ├── provision.js  # Generate Pangolin site + blueprint + key
│   │       ├── models.js     # Model discovery proxy
│   │       └── key-status.js # Key validation
│   └── public/
│       └── index.html
│
├── services/                  # Docker Compose stack
│   ├── docker-compose.yml
│   └── homepage-config/
│
├── config/                    # Templates
│   └── preseed.cfg.template
│
├── build-iso.sh              # ISO builder
└── PLAN.md                   # Decisions log
```

## Phase Order

### Phase 1: Pi Agent Core (NOW — VM test)
- [ ] FastAPI backend with `/api/` endpoints
- [ ] Skill plugin loader (YAML catalog + Python hooks)
- [ ] Docker Compose manager (start/stop/restart)
- [ ] Svelte dashboard skeleton (service grid, status indicators)
- [ ] LLM router (flash/glm two-tier)
- [ ] Local-only mode: `http://<lan-ip>:8080`

### Phase 2: Cloud Provisioning
- [ ] `POST /v1/provision` endpoint (creates Pangolin site + blueprint)
- [ ] Device registration flow (starter key → cloud API → provisioning key)
- [ ] Blueprint auto-creation of per-service resources

### Phase 3: Remote Access
- [ ] Newt auto-configuration from provisioning key
- [ ] Dashboard accessible at `dash.<device>.serverstick.com`
- [ ] Pangolin access policies per resource

### Phase 4: Polish & Package
- [ ] ISO build pipeline with embedded keys
- [ ] Backup automation (restic → USB stick)
- [ ] Service health monitoring dashboard
- [ ] Security settings UI
- [ ] Multi-device management (future: app.serverstick.com)