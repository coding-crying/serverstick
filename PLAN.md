# ServerStick — Implementation Plan

Only things we've decided go here. Everything else stays in conversation until validated.

## Decided

### Product

**USB stick that installs a preconfigured Debian self-hosting stack onto host storage. Not a persistent live OS — it installs to disk.** One-time purchase, XMR mining funds ongoing API costs.

**Core mission:** Help people get off surveillance services onto their own stack. Every service replaces something that harvests your data — searches, documents, photos, messages, file sharing.

### Competitive Research: Harbor (av/harbor)

**Verdict: Steal the patterns, don't adopt the tool.**

Harbor is the closest analog to ServerStick's service orchestration. Single maintainer (Ivan Cherepanov), 3K stars, 140+ AI/LLM services, daily commits. But:

**What's good (patterns to adopt):**
- `compose.x.A-B.yml` cross-service overlay system — when both services are active, overlay adds env vars, network links, volume mounts. Clean, composable.
- `install.md` per service that you pipe into Claude Code — LLM-consumable install narratives.
- Service metadata with categorization, tags, and hardware awareness.
- "One command brings up a pre-wired stack" philosophy.

**What's bad (why we don't build on it):**
- **235KB bash monolith** as the CLI. Entire orchestration engine is one shell script. Command injection vulnerabilities (CWE-78) found in multiple code paths.
- **One-man show** — 97% of commits from one person. Bus factor = 1.
- **Security posture** — 78 potential security issues found (7 critical, 9 high), no security policy, no responsible disclosure, no security.md. Not suitable for a consumer product.
- **Ghost town engagement** — 3K stars but zero Reddit threads, HN posts flopped (0-4 points), GitHub discussions are 3 comments deep. Stars are passive bookmarks, not users.
- **LLM-stack only** — 140 services are all AI/LLM tools. Not general self-hosting.

**What we take from Harbor:**
1. The compose overlay pattern (already in RECIPE-SPEC.md as `compose.x.A-B.yml`)
2. Service metadata format (already in our YAML catalog)
3. The "pre-wired stack" philosophy (Pi Agent's core value prop)

### Competitive Research: EverOS (EverMind/印奇智能)

**Verdict: Skip. Marketing spend, not organic demand.**

EverOS is an AI memory/agent framework (6K stars). The hackathon strategy is user acquisition — $5K prize pools buy 50+ integration projects. Open-source the framework, close the cloud (evermind.ai). Standard "open core, closed cloud" model.

**Why we don't use it:**
- Memory architecture (MemCell, Workspace, Dialectic) is overengineered for service management.
- Hackathon-driven stars are vanity metrics, not community signal.
- Chinese AI company entering global markets — aggressive growth posture, burn rate concern.
- Landing page is v0.dev-quality. 6K stars but no substance past the fold.
- We need service orchestration, not a memory layer.

**Memory stack decision for ServerStick:**
- **v1:** Hermes built-in memory (proven, works, no extra infra).
- **v2:** Evaluate Honcho for dialectic/agentic memory if complexity warrants it.
- **Skip:** EverOS, LangChain, LlamaIndex — all solve problems we don't have.

### LLM Recipe Book: Open Service Catalog for AI-Driven Installation

**The recipe book is the core IP, not the USB stick.** The stick is the delivery mechanism — the recipes are what make it work without a human sysadmin.

**What it is:** Structured, LLM-consumable recipes for self-hosted services. Each recipe contains:
- **What it does** (1-2 sentences, no marketing fluff)
- **Hardware requirements** (CPU level x86_v1/v2/v3, min RAM, disk, GPU)
- **Network requirements** (ports, DNS, reverse proxy config)
- **Step-by-step install** with decision points and conditionals
- **Common failure modes** + recovery steps
- **Post-install verification** (curl commands, health checks)
- **Surveillance service replaced** (the "why" for each service)

**Why it's novel:**
- **Harbor** (★3k) — closest analog, but LLM-stack only (Ollama, vLLM, Open WebUI). Has `install.md` you pipe into Claude Code, but only for AI services. One-man show, bash monolith, poor security posture.
- **claude-homelab** (★50) — SKILL.md files per homelab service, but Claude Code-specific, not a standalone catalog.
- **CasaOS/Coolify app stores** — Docker Compose manifests in JSON/YAML. Machine-readable but not LLM-optimized: no natural language docs, no decision trees, no error recovery.
- **MCP registries** (Smithery, ToolHive, mcp.run) — Narrowly scoped to MCP servers, not general self-hosting.

**Nobody's doing general-purpose, LLM-consumable recipes for self-hosted services.** This is the gap.

**Format:** YAML frontmatter (machine-parseable metadata) + Markdown body (natural language install narrative). LLMs read both; dashboards parse the frontmatter.

```yaml
# recipes/rembg.yaml
name: rembg
replaces: remove.bg
cpu_level: x86_v2        # SSE4.2, 2008+
min_ram: 2GB
ports: [7000]
image: danielgatis/rembg
tags: [privacy, image-processing, gpu-optional]
---

## What It Does
Removes image backgrounds. Replaces remove.bg and similar services that
upload your photos to unknown servers.

## Install
1. Add to docker-compose.yml under `services:`
   ...
```

**Open-core model:**
- **Open:** Recipe catalog on GitHub. Community PRs welcome ("add your service").
- **Closed/branded:** USB stick experience, Pangolin tunnel, Pi Agent orchestration, dashboard UX.
- The catalog becomes the standard reference for "how to install self-hosted services with AI assistance" — drives brand awareness, positions ServerStick as the authority.

**Publishing strategy:** Open the recipe catalog as a standalone repo (`serverstick/recipes`) before the stick ships. Let it grow. Each recipe is a self-contained file that any agent (Claude, Codex, Hermes, raw LLM) can consume. The Pi Agent just reads them locally.

### LLM Harness: Direct FastAPI + TokenRouter (NOT Pi)

**Pi as harness REJECTED** — Running Pi in RPC mode is overkill for service management. Direct FastAPI + model router is simpler, faster, no subprocess complexity. Pi's skill concept lives on as YAML catalog + Python hooks.

Two-tier router in `src/agent/router.py`:
- **DeepSeek V4 Flash** — default, service management, status, simple tasks
- **GLM 5.1** — promoted for troubleshooting, security, complex reasoning, user chat
- Never silently downgrade; always show which model responded

### Secrets: SOPS + age

Confirmed: SOPS for encrypted secret storage, age for key management.
- age keypair generated on-device at first boot
- Private key stays on the installed machine, never on the USB stick
- All secrets in SOPS-encrypted YAML, decrypted at service startup via `sops exec-env`
- LLM agents use `sops --set` / `sops --extract` for individual key operations
- No server process. CLI-only. Fits zero-config.

Still need to validate: Does `sops exec-env` work cleanly with Docker Compose in practice? **Untested.**

### API Keys: Two-Key System

- **Starter key**: ~20 credits, baked in preseed, low value, leakage is acceptable
- **Earnings key**: Generated on-device during setup, from XMR mining, SOPS-encrypted, high value, never touches the stick

### Installer: Preseeded Debian Netinst

Stock Debian netinst ISO + injected `preseed.cfg` built with `xorriso`. The preseed handles partitioning, user creation, packages. A `late_command` script runs the real setup (Docker, Pi, SOPS, etc.).

Still need to validate: xorriso repack process, preseed reliability on varied hardware. **Untested.**

### Setup Mode: GUI Kiosk → Headless

First boot starts a minimal GUI stack so the user can run setup directly on the machine. After `/api/setup` completes, the system switches to headless `multi-user.target` permanently.

- `serverstick-setup.target` — X11 + `matchbox-window-manager` + Chromium kiosk (`--no-sandbox --kiosk http://localhost:8080`)
- After setup: `systemctl set-default multi-user.target` → reboot → no GUI, no Xorg, no Chromium
- Emergency re-entry: `systemctl isolate serverstick-setup.target` brings kiosk back
- **Laptop lid close:** `HandleLidSwitch=ignore` in `logind.conf` (preseed/late_command) so the machine stays on when closed
- **Battery-less laptops:** Some throttle to 800MHz without a battery installed. Warn during setup if detected. *TBD: where in the UX to surface this warning.*

**Physical UX (stickers in box):**
- Device name sticker: `nick.serverstick.com`
- Service quick-reference or QR code → homepage
- Peel-off recovery card: Hetzner Storage Box username + blank line for password hint

### Dashboard: Svelte + FastAPI (Pi Agent)

First boot: Pi Agent starts (systemd). FastAPI backend + SvelteKit frontend at `http://<lan-ip>:8080`.

**Stack:**
- **Backend:** FastAPI (`src/agent/main.py`) — 11 API routes, serves Svelte static build
- **Frontend:** SvelteKit with `adapter-static` — builds to static files, served by FastAPI
- **Skill engine:** `src/agent/skills/` — YAML catalog + Python SkillBase classes
- **LLM router:** `src/agent/router.py` — two-tier DeepSeek/GLM routing
- **Provisioning:** `/api/setup` — idempotent first-boot wizard, creates Pangolin site + starts services

**Why Svelte:** Tiny bundle (~15KB gzip), reactive, compiles to vanilla JS, no runtime overhead.

Works on:
- Old laptop with display (Chromium kiosk)
- Headless box (mDNS + phone/laptop browser)
- Remote via Pangolin tunnel at `dash.{device}.serverstick.com`

### Local-First DNS: Per-Device Split-Horizon (Pi Agent)

**Problem:** All traffic through the Pangolin VPS tunnel wastes bandwidth and adds latency — especially for media streaming on the LAN. But making the stick the network DNS server (Pi-hole/AdGuard) creates a SPOF: stick dies = whole house loses DNS.

**Solution: Per-device agent, not network-level DNS.** Same model as Tailscale's MagicDNS.

The Pi Agent installs on each user device (phone, laptop, tablet) and only intercepts `*.serverstick.com` queries — everything else uses the device's normal DNS, completely untouched.

**How it works:**
- Pi Agent detects if it's on the same LAN as the stick (can it reach the stick's LAN IP?)
- **On LAN:** Writes a domain-specific DNS override for `*.serverstick.com` → stick's LAN IP
  - macOS: `/etc/resolver/serverstick.com`
  - Windows: NRPT rule
  - Linux: `/etc/hosts` entry or dnsmasq snippet
- **Remote:** Leaves public DNS in place → traffic routes through Pangolin tunnel as normal
- **Stick goes down?** → Self-hosted services unreachable (obviously), but Netflix/Google/everything else works fine. No SPOF.
- **No router changes. Zero.**

**Why this matters:**
- Bandwidth-heavy services (future: Jellyfin, Immich, Nextcloud) stay on LAN — never touch our VPS. User confirms: most streaming won't leave the home anyway.
- Same domain names work everywhere — users don't need to remember LAN IPs vs tunnel URLs
- Zero config — Pi Agent generates DNS overrides from the service registry
- Pangolin tunnel only carries lightweight remote access traffic (dashboard, API, text services)

**Bring-your-own-domain is free.** DNS is cheap. We offer `*.serverstick.com` subdomains for free too. The paid product is **Pangolin tunnel routing** — that's our VPS bandwidth. Only stick buyers get remote access through our infrastructure.

**Fallback:** If the agent can't detect the stick on LAN, it leaves public DNS records in place. Everything routes through Pangolin — suboptimal but works.

**Pricing implication:**
- **Free:** Self-host, bring domain, local-only (no Pangolin tunnel)
- **Stick purchase:** Pangolin tunnel included, remote access out of the box
- **Bandwidth add-on:** Only if someone hammers the tunnel

**Install UX for Pi Agent:** One command (`curl | bash` or platform packages). Detects OS, writes the right DNS override, daemon runs in background to detect LAN/remote and swap targets. **Untested** — need to validate per-platform DNS override mechanisms.

### Tunneling: Pangolin Cloud (verified, operational)

Using Pangolin Cloud (managed, free tier) for tunneling. Each device = 1 Pangolin site with N resources.

**Pattern:** `{service}.{device}.serverstick.com` (e.g. `pdf.nick.serverstick.com`)

Current test site: "nick" (siteId 14913). Blueprint auto-creates resources on first connect.

|| Service | Subdomain | Port ||
||---------|-----------|------||
|| Dashboard | dash.{device} | 8080 ||
|| Homepage | home.{device} | 3002 ||
|| Stirling-PDF | pdf.{device} | 8440 ||
|| PrivateBin | bin.{device} | 8084 ||
|| PairDrop | drop.{device} | 3000 ||
|| Uptime Kuma | kuma.{device} | 3001 ||
|| rembg | rembg.{device} | 7000 ||
|| Dozzle | logs.{device} | 8888 ||
|| API | api.{device} | 8080 ||
|| Watchtower | (headless) | — ||

**Tunnel client:** Newt runs as `serverstick-newt.service`. Connects to `gerbil.pangolin.net:50120`. All resources route to `127.0.0.1:PORT` via Newt.

**Provisioning flow:** Bootstrap writes `SERVERSTICK_STARTER_KEY` env var. Pi Agent `/api/setup` calls cloud API → cloud creates Pangolin site + blueprint → returns Newt credentials → device connects. If credentials omitted, device operates LAN-only.

### Matrix (Synapse) — Communication Hub

**Federation and bridges are core features, not add-ons.** A non-federated Matrix server is just a worse Slack. Without bridges, you're asking people to convince contacts to install a new app — the #1 reason privacy tools fail.

| Component | Image | Port | Subdomain | RAM |
|-----------|-------|------|-----------|-----|
| Synapse | `matrix-org/synapse:latest` | 8008 | `matrix.{device}` | ~500MB (SQLite) |
| Element Web | `vectorim/element-web:latest` | 8080 | `chat.{device}` | ~50MB (static) |

**SQLite for v1** — fine for <50 users. PostgreSQL upgrade path via Pi Agent for power users.

**Federation enabled by default:** `server_name = {device}.serverstick.com`. Federation traffic through Pangolin on 443 (no port 8448 needed). `.well-known/matrix/server` handled by Synapse.

**Bridges (opt-in, per-service):**

| Bridge | Replaces | Auth | Re-auth | RAM |
|--------|----------|------|---------|-----|
| WhatsApp | WhatsApp | QR code scan | Every ~14 days | ~250MB |
| Discord | Discord | OAuth2 bot invite | Never | ~200MB |
| Telegram | Telegram | Bot token + phone | Never | ~200MB |
| Signal | Signal | Phone number linking | ~90 days | ~200MB |

**Pi Agent guardrails** — the AI sysadmin value prop, made real:
1. **Bridge health monitoring** — auto-detect down/degraded bridges, restart within 2 min (3 restarts in 10 min → alert user, stop restart-loop)
2. **QR re-auth** — detect WhatsApp re-login needed, surface QR code in dashboard with notification
3. **Federation health** — verify `.well-known` reachability, audit federation config, surface issues
4. **Bridge setup/removal** — guided one-click flows via Pi Agent dashboard, dynamic app service registration
5. **Rate limit protection** — detect 429s from remote servers, back off bridge message sending
6. **Media cleanup** — periodic `synapse-compress-media` + size monitoring

**Docker networking:** Matrix services use a dedicated `serverstick-matrix` bridge network (bridges reach Synapse via `http://synapse:8008`). Other services stay on host networking.

**Minimum spec:** 4GB RAM for Synapse + Element + 1 bridge. 8GB for all 4 bridges. Pi Agent surfaces resource recommendations.

**User IDs:** `@username:{device}.serverstick.com` — federation-ready from day one.

**Custom domain (v2):** Allow users to bring their own domain for `@username:theirdomain.com`.

Full spec: `references/matrix-spec.md`

### Backup: Same-Stick restic (included) + Cloud (paid tier)

The USB stick installs Debian onto host storage, then **wipes and formats as a restic backup repository**.

- **Free tier:** restic to the repurposed USB stick. Encrypted, deduplicated, incremental.
- **Paid tier (future):** restic to encrypted Hetzner Storage Box behind Pangolin VPS. True 3-2-1 offsite backup.

### Service Catalog: v1 (alpha)

**Every service replaces a surveillance service.** Not "homelab tools" — "get off spyware."

**Bandwidth classification:** Most streaming stays on LAN. Services marked `tunnel_safe` work well over Pangolin; heavy services are LAN-primary with split-horizon DNS.

|| Service | Replaces | Port | Image | Tunnel Safe ||
||---------|----------|------|-------|-------------||
|| Homepage | Dashboard spyware | 3002 | `ghcr.io/benphelps/homepage` | ✅ ||
|| Stirling-PDF | ilovepdf/smallpdf | 8440 | `frooodle/s-pdf` | ✅ ||
|| PrivateBin | Pastebin/gists | 8084 | `privatebin/nginx-fpm-alpine` | ✅ ||
|| PairDrop | WeTransfer/Drive | 3000 | `lscr.io/linuxserver/pairdrop` | ✅ (LAN) ||
|| Uptime Kuma | UptimeRobot/Pingdom | 3001 | `louislam/uptime-kuma` | ✅ ||
|| Dozzle | Container logs | 8888 | `amir20/dozzle` | ✅ ||
|| rembg | remove.bg | 7000 | `danielgatis/rembg` | ⚠️ (image upload) ||
|| Watchtower | Auto-update | — | `containrrr/watchtower` | (headless) ||
|| Synapse | WhatsApp/Discord/Telegram | 8008 | `matrix-org/synapse` | ✅ ||
|| Element Web | Matrix web client | 8080 | `vectorim/element-web` | ✅ ||

**Deferred to v2:** SearXNG, Home Assistant, IT-Tools, Pi web UI

### Development Model Preferences

- **GLM 5.1** — Tough/important implementations, complex debugging, architecture decisions
- **DeepSeek V4 Flash** — General usage, routine tasks, drafting, everyday development

Both via TokenRouter. Use DeepSeek by default; escalate to GLM when it matters.

---

## Build Status (v0.1 Alpha)

### ✅ Completed

- `src/agent/main.py` — FastAPI backend with 15+ API routes (status, services, catalog, setup, chat, hardware, tunnel, resources, backups, network, health, logs, update-all, WebSocket)
- `src/agent/router.py` — Two-tier LLM router (DeepSeek V4 Flash default → GLM 5.1 upgrade)
- `src/agent/skills/` — Skill plugin system with SkillRegistry + YAML catalog entries
- CPU feature detection — `/api/hardware` detects x86_v1/v2/v3 level, `/api/catalog` filters incompatible services
- `src/agent/dashboard/` — SvelteKit dashboard with setup wizard + service toggle UI
- `src/agent/Dockerfile` — Multi-stage build (Python backend + Node dashboard build)
- `src/agent/requirements.txt` — Python dependencies
- `src/agent/dev-start.sh` — Dev launcher script
- `src/services/docker-compose.yml` — 8 services with host networking + Watchtower label-based updates
- `src/config/serverstick-agent.service` — Pi Agent systemd unit
- `src/config/serverstick-newt.service` — Newt tunnel systemd unit (auto-reconnect)
- `src/bootstrap/bootstrap.sh` — Zero-touch curl|bash seeder for bare Debian
- `src/bootstrap/provision-pangolin.sh` — Per-device Newt + Pangolin setup
- `src/cloud/api/v1/provision.js` — Vercel serverless provisioning endpoint (stub)
- `src/config/preseed.cfg.template` — Debian auto-install template
- `ARCHITECTURE.md` — Full architecture spec
- `RECIPE-SPEC.md` — Recipe format spec (YAML frontmatter + Markdown body, compose overlays, CPU levels, failure recovery, privacy framing)
- **VM 101 test environment** — Proxmox VMID 101 @ 10.0.0.19, Debian 12, 8GB RAM, Docker 29.5.2, Pi Agent running on :8080
- **Competitive research** — Harbor (steal patterns, don't adopt), EverOS (skip), claude-homelab (SKILL.md format reference)

### ⬜ In Progress / Next

- VM end-to-end test — verify bootstrap → Pi Agent → tunnel → services flow
- Cloud `/v1/provision` — real Pangolin Blueprint + Provisioning Key API calls
- SOPS/age key generation flow testing
- ISO packaging — xorriso repack + preseed injection
- Additional skill YAML catalog entries (only rembg exists; need homepage, stirling-pdf, privatebin, pairdrop, uptime-kuma, dozzle, synapse, element)
- Split-horizon DNS agent (Pi Agent on user devices) — per-platform DNS override validation
- Matrix spec implementation (references/matrix-spec.md exists, no code yet)

### 🗑️ Removed (superseded)

- `src/discover/discover.py` — Replaced by Pi Agent
- `src/services/Dockerfile.discovery` — No longer needed (host systemd)
- `src/services/serverstick-discovery.service` — Replaced by `serverstick-agent.service`
- `src/services/serverstick-newt.service` — Moved to `src/config/`
- `src/skills/serverstick-setup/SKILL.md` — Replaced by agent skills system
- `src/bootstrap/get.serverstick.sh` — Replaced by `bootstrap.sh`
- `src/bootstrap/serverstick-setup.sh` — Replaced by `bootstrap.sh`
- `src/test-bootstrap.sh` — Replaced by VM testing

---

## Not Yet Decided

- XMR mining integration details (hosted vs independent, payout flow)
- Hardware tier classification for AI query limits
- ISO build pipeline and per-customer key injection
- How updates work post-install
- Multi-device management UX (central dashboard vs per-device)
- Which services are "LAN-only" vs "tunnel-safe" — user notes most streaming won't leave the home, so heavy bandwidth services (Jellyfin/Immich in v2) should default to LAN-only with split-horizon DNS

---

### Explicitly Rejected

- **Pi as active agent harness** — Running Pi in RPC mode as the brain is overkill. Direct FastAPI + model router is simpler. Pi's skill concept lives in YAML catalog + Python hooks.
- **Forking Pi** — Maintaining a fork is a trap.
- **HashiCorp Vault** — BSL-licensed, overkill, requires a server process. SOPS + age is the right fit.
- **OpenBao** — Also overkill for our use case.
- **Infisical as default** — Requires running a server. Could be optional add-on later.
- **PI Imager fork** — Web wizard handles all user interaction. No native app.
- **Single API key** — Two-key system (starter + earnings) is the right model.
- **Roll-your-own WireGuard + Caddy** — Pangolin IS WireGuard with a management layer. Don't reimplement.
- **AdGuard Home / Pi-hole in v1** — DNS blocking requires router config. Single point of failure for all DNS.
- **Vaultwarden** — Backup failure = catastrophic data loss. Consequences out of proportion.
- **Jellyfin + *arr stack** — Productizing piracy is legal liability.
- **Matrix bridges as unsupported add-ons** — Bridges are core features with Pi Agent guardrails (health monitoring, auto-restart, re-auth flows, guided setup), not optional footguns.
- **IT-Tools** — No clear surveillance service it replaces. Doesn't fit the framing.
- **Building on Harbor** — Bash monolith, CWE-78 command injection, one-man show (97% of commits), zero community engagement. Steal the overlay pattern and metadata format, don't depend on the project.
- **EverOS / EverMind for memory** — Overengineered for service management. Hackathon-driven stars, not real adoption. Memory needs for v1 are simple; Hermes built-in suffices.
- **LangChain / LlamaIndex as orchestration** — Both solve RAG/chain problems we don't have. Pi Agent's skill engine is simpler and purpose-built.

### Security Invariants

- **No baked secrets in ISO.** The preseed/ISO contains only public data. Starter keys come from the cloud API at first boot via one-time provisioning tokens.
- **Embed bootstrap in ISO.** No `curl | bash` in the installer path. The ISO is self-contained. Network fetches are for Docker images and the Newt binary only.
- **No remote text in LLM context.** LLM skill docs must never be fetched from URLs. Catalog updates are signed YAML data only. Help text lives in the Svelte dashboard.
- **Secrets never enter LLM context.** The agent reports "configured/missing" boolean state, never decrypted values. `sops exec-env` is for systemd service startup only.