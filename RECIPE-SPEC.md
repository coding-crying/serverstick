# ServerStick Recipe Format Spec

> LLM-consumable service recipes for autonomous self-hosting.
> Combines patterns from Harbor (compose overlays, cross-integration) and
> claude-homelab (SKILL.md narrative, API references), adding hardware
> compatibility, failure recovery, and privacy-first framing.

## Design Principles

1. **LLM-first, not human-first.** Structure, metadata, and decision trees
   over prose. An agent should be able to install, configure, and troubleshoot
   a service without human hand-holding.
2. **Agent-agnostic.** No Claude-specific or GPT-specific patterns. Pure
   structured markdown + YAML that any LLM can parse.
3. **Composable.** Services declare what they need and what they provide.
   Cross-service integration is automatic, not manual.
4. **Hardware-aware.** CPU level, RAM, disk, and GPU requirements are
   first-class metadata. Incompatible services are filtered before install.
5. **Privacy-first.** Every recipe frames what proprietary/spyware service
   it replaces and why self-hosting is better.

## Directory Structure

```
recipes/
├── recipe.schema.yaml          # This spec (validation schema)
├── media/
│   ├── plex/
│   │   ├── RECIPE.md           # Main recipe (required)
│   │   ├── compose.yml         # Docker Compose (required)
│   │   ├── compose.x.plex-sonarr.yml    # Cross-service overlay
│   │   ├── compose.x.plex-radarr.yml    # Cross-service overlay
│   │   ├── compose.x.plex-tailscale.yml # Cross-service overlay
│   │   ├── references/
│   │   │   ├── api.md          # API endpoints & auth
│   │   │   ├── env-vars.md     # Environment variable reference
│   │   │   └── troubleshooting.md  # Known issues & fixes
│   │   └── scripts/
│   │       ├── healthcheck.sh  # Verify service is running correctly
│   │       └── backup.sh       # Export/backup data
│   ├── jellyfin/
│   │   └── ...
│   └── ...
├── ai/
│   ├── ollama/
│   ├── open-webui/
│   └── ...
├── infrastructure/
│   ├── tailscale/
│   ├── nginx-proxy-manager/
│   └── ...
├── productivity/
│   ├── nextcloud/
│   ├── paperless-ngx/
│   └── ...
└── social/
    ├── matrix-synapse/
    └── ...
```

## RECIPE.md Format

```markdown
---
# === IDENTITY ===
name: plex
version: 1.0.0                    # Recipe version (not app version)
category: media
tags: [media-server, streaming, movies, tv, music]
description: >
  Media server that organizes and streams your video, music, and photo
  collections to all your devices.

# === HARDWARE REQUIREMENTS ===
requirements:
  cpu_level: 1                    # 0=x86_v1, 1=x86_v2, 2=x86_v3, 3=x86_v4
  ram_min: "2GB"
  ram_recommended: "4GB"
  disk_min: "1GB"                 # App + config only (not media storage)
  gpu: optional                   # required | optional | none
  gpu_notes: >
    Hardware transcoding requires Intel QuickSync (10th+ gen) or NVIDIA GPU.
    Without GPU, transcoding uses CPU — fine for 1-2 streams.
  arch:
    - amd64
    - arm64                       # Limited GPU support on ARM

# === NETWORKING ===
networking:
  ports:
    - { port: 32400, protocol: tcp, purpose: web-ui }
    - { port: 1900, protocol: udp, purpose: dlna, optional: true }
    - { port: 3005, protocol: tcp, purpose: plex-companion, optional: true }
  dns:
    - { name: plex, type: http, subdomain: plex }
  tunnel_safe: true               # Works over Pangolin tunnel without issues
  bandwidth: moderate             # minimal | moderate | heavy
  bandwidth_notes: >
    Direct LAN streaming is ideal. Remote streaming works over tunnel
    but bandwidth-limited by tunnel throughput. Transcoding reduces
    bandwidth needs at the cost of CPU/GPU.

# === DEPENDENCIES & INTEGRATIONS ===
provides:
  - media-server                  # Capability this service exports
  - dlna-server
integrates_with:                  # Other recipes this service can work with
  - { recipe: sonarr, capability: tv-automation, overlay: compose.x.plex-sonarr.yml }
  - { recipe: radarr, capability: movie-automation, overlay: compose.x.plex-radarr.yml }
  - { recipe: prowlarr, capability: index-management }
  - { recipe: tautulli, capability: monitoring }
  - { recipe: overseerr, capability: request-management }
  - { recipe: tailscale, capability: remote-access, overlay: compose.x.plex-tailscale.yml }
requires: []                      # Hard dependencies (must be installed first)
conflicts_with:                   # Mutually exclusive services
  - { recipe: jellyfin, reason: "Both claim port 8096 and serve same purpose" }

# === PRIVACY FRAMING ===
replaces:
  - { service: "Netflix", reason: "You own your media. No tracking, no subscription creep, no content disappearing." }
  - { service: "Spotify", reason: "Music library you control. No algorithm pushing content." }
  - { service: "Google Photos", reason: "Photo storage without Google scanning your images for ads." }

# === INSTALL PROFILE ===
install:
  difficulty: easy                # easy | medium | hard
  time_minutes: 5
  first_run_url: "http://{host}:32400/web"
  first_run_steps: |
    1. Claim the server with your Plex account (required for remote access)
    2. Add media libraries pointing to /data/movies, /data/tv, etc.
    3. Enable remote access in Settings > Remote Access (optional)
    4. For hardware transcoding: Settings > Transcoder > Use hardware acceleration

# === STATE ===
stateful: true                    # Has persistent data that must survive updates
data_paths:
  - /config                       # Plex configuration/database
  - /data                         # Media files (user-managed)
backup_strategy: |
  Config backup: tar /config (contains database + preferences).
  Media files: user responsibility (often on separate NAS).
  Restore: extract config backup, ensure same Plex claim token.
---

# Plex Media Server

## Overview

Plex organizes video, music, and photos from personal media libraries
and streams them to smart TVs, streaming boxes, mobile devices, and
web browsers. It is the most mature self-hosted media server with the
broadest client support.

**⚠️ Note:** Plex requires a Plex account for initial server claim.
The server itself is self-hosted; only the authentication relay uses
Plex's infrastructure. A Plex Pass subscription enables hardware
transcoding, DVR, and other features but is not required.

## Decision Tree

```
Need media streaming?
├── Want the most client support + easiest setup?
│   └── ✅ Plex (this recipe)
├── Want fully open-source (no account required)?
│   └── → jellyfin recipe
├── Want lightweight, music-only?
│   └── → navidrome recipe
└── Want photo management specifically?
    └── → immich recipe
```

## Hardware Transcoding Decision Tree

```
Have Intel CPU (10th gen+)?
├── Yes → Enable QuickSync in Plex settings. Best value.
└── No
    ├── Have NVIDIA GPU?
    │   ├── Yes → Enable NVENC in Plex settings.
    │   └── No
    │       ├── Only 1-2 concurrent streams?
    │       │   └── CPU transcoding is fine.
    │       └── More streams needed?
    │           └── Consider Jellyfin (more efficient CPU transcode)
    └── ARM (e.g., Raspberry Pi)?
        └── Direct play only. Avoid transcoding.
```

## Failure Recovery

### Server won't start
1. Check logs: `docker logs plex`
2. Common: port 32400 already in use → `ss -tlnp | grep 32400`
3. Common: permissions on /config → ensure UID/GID match
4. Nuclear: rename /config, let Plex recreate, then restore databases

### Can't access web UI
1. Verify container running: `docker ps | grep plex`
2. Check firewall: `ufw status` or `iptables -L -n | grep 32400`
3. Try: `curl http://localhost:32400/web` from host
4. If tunnel: verify Pangolin resource is online and targets correct port

### Transcoding errors
1. Check GPU access: `docker exec plex nvidia-smi` (NVIDIA) or
   `docker exec plex vainfo` (Intel QuickSync)
2. Ensure container has `devices` mapping for /dev/dri (Intel) or
   NVIDIA runtime (NVIDIA)
3. Fallback: disable hardware transcoding, use CPU

### Remote access not working
1. Plex > Settings > Remote Access > Enable
2. If behind CGNAT: use Pangolin tunnel (set tunnel_safe: true)
3. If behind NAT without CGNAT: enable UPnP on router or manual port forward

## API Quick Reference

See `references/api.md` for full endpoint list.

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/status/sessions` | GET | Active playback sessions |
| `/library/sections` | GET | List all libraries |
| `/library/sections/{id}/refresh` | POST | Trigger library scan |
| `/library/sections/{id}/all` | GET | List items in library |

## Environment Variables

See `references/env-vars.md` for full reference.

| Variable | Default | Description |
|----------|---------|-------------|
| `PLEX_CLAIM` | - | Claim token for initial setup |
| `PLEX_UID` | 1000 | User ID for file permissions |
| `PLEX_GID` | 1000 | Group ID for file permissions |
| `TZ` | UTC | Timezone |
```

## compose.yml Format

Standard Docker Compose with ServerStick conventions:

```yaml
# ServerStick Recipe: plex
# Category: media
# CPU Level: 1 (x86_v2 / SSE4.2+)

services:
  plex:
    image: lscr.io/linuxserver/plex:latest
    container_name: plex
    restart: unless-stopped
    environment:
      - PUID=${PLEX_UID:-1000}
      - PGID=${PLEX_GID:-1000}
      - TZ=${TZ:-UTC}
      # - PLEX_CLAIM=claim-xxxxxxx  # Set during first install only
    volumes:
      - ${APPDATA}/plex/config:/config
      - ${MEDIA}:/data
    ports:
      - "32400:32400/tcp"
      # - "1900:1900/udp"   # DLNA (optional)
      # - "3005:3005/tcp"   # Plex Companion (optional)
    # Hardware transcoding - uncomment based on GPU:
    # devices:
    #   - /dev/dri:/dev/dri     # Intel QuickSync
    # deploy:
    #   resources:
    #     reservations:
    #       devices:
    #         - driver: nvidia
    #           count: 1
    #           capabilities: [gpu]  # NVIDIA
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:32400/identity"]
      interval: 30s
      timeout: 10s
      retries: 3
    labels:
      serverstick.recipe: plex
      serverstick.category: media
      serverstick.cpu_level: "1"
      serverstick.version: "1.0.0"
```

## Cross-Service Overlay Format

Named `compose.x.<serviceA>-<serviceB>.yml`. Applied when both
services are active. These add environment variables, network links,
or volume mounts that wire services together.

Example `compose.x.plex-sonarr.yml`:

```yaml
# Overlay: plex ↔ sonarr
# When both are running, Sonarr notifies Plex to refresh on import.

services:
  sonarr:
    environment:
      - PLEX_HOST=plex
      - PLEX_PORT=32400
      - PLEX_TOKEN=${PLEX_TOKEN}  # Auto-populated by Pi Agent
    depends_on:
      - plex
    networks:
      - media

  plex:
    networks:
      - media

networks:
  media:
    name: serverstick-media
    external: false
```

## CPU Level Definitions

Used in `requirements.cpu_level` to ensure binary compatibility
with target hardware:

| Level | Name | CPU Flags | Era | Examples |
|-------|------|-----------|-----|----------|
| 0 | x86_v1 | SSE2 | ~2003+ | Old C2D/C2Q, Atom |
| 1 | x86_v2 | SSE4.2, POPCNT | ~2008+ | Core i3/i5/i7 1st-4th gen |
| 2 | x86_v3 | AVX, AVX2 | ~2013+ | Core i3/i5/i7 4th+ gen, Xeon E3/E5 v3 |
| 3 | x86_v4 | AVX-512 | ~2017+ | Xeon Scalable, Core i9 12th+ gen |

Most self-hosted services work at level 0 or 1.
AI/ML services (Ollama, Whisper, rembg) typically require level 2+.

## Pi Agent Integration

The Pi Agent reads recipes at runtime:

```
GET /api/v1/capabilities
→ Returns CPU level, RAM, disk, GPU for this machine

GET /api/v1/services/available
→ Returns all recipes whose requirements are met

GET /api/v1/services/installed
→ Returns running services + their status

POST /api/v1/services/{name}/install
→ Agent reads RECIPE.md + compose.yml, runs install

POST /api/v1/services/{name}/troubleshoot
→ Agent reads failure recovery section, runs diagnostics
```

## Open-Core Distribution Model

### Open (Community)
- Full recipe catalog (RECIPE.md + compose.yml + overlays)
- Community PRs for new services and updates
- Basic Pi Agent with install/health-check/troubleshoot

### Commercial (ServerStick Pro)
- Curated + tested recipe guarantees (CI pipeline validates each recipe)
- One-click install from mobile dashboard
- Automatic cross-service wiring (Pangolin tunnel + split-horizon DNS)
- Priority failure recovery with remote diagnostics
- "Replace your spyware" migration wizards (import data from Netflix,
  Google Photos, Spotify export APIs)

## License

Recipes: CC-BY-SA 4.0 (open, share-alike, attribution)
Pi Agent core: MIT
ServerStick Pro: Proprietary

## Attribution

This format builds on patterns from:
- **Harbor** (github.com/av/harbor) — compose overlay system, AI-agent integration
- **claude-homelab** (github.com/jacobmagar/claude-homelab) — SKILL.md format, API references
