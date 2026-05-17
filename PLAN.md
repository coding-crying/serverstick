# ServerStick — Implementation Plan

Only things we've decided go here. Everything else stays in conversation until validated.

## Decided

### Product

USB stick that installs a preconfigured Debian self-hosting stack onto host storage. Not a persistent live OS — it installs to disk. One-time purchase, XMR mining funds ongoing API costs.

**Core mission:** Help people get off surveillance services onto their own stack. Every service replaces something that harvests your data — searches, documents, photos, messages, file sharing.

### LLM Harness: Pi (NOT forked)

**DEFERRED** — The original plan was Pi in RPC mode. Now using direct FastAPI + TokenRouter calls with a two-tier model router. Pi's skill system concept lives on as our YAML catalog + Python hooks, but we're not running Pi as a subprocess anymore. Faster, simpler, no RPC bridge complexity.

If we need conversational AI later, we can add it as a skill that calls the LLM router — Pi is an option, not a requirement.

### Secrets: SOPS + age

Confirmed: SOPS for encrypted secret storage, age for key management.
- age keypair generated on-device at first boot
- Private key stays on the installed machine, never on the USB stick
- All secrets in SOPS-encrypted YAML, decrypted at service startup via `sops exec-env`
- LLM agents use `sops --set` / `sops --extract` for individual key operations
- No server process. CLI-only. Fits zero-config.

Still need to validate: Does `sops exec-env` work cleanly with Docker Compose in practice? How does key rotation work for a non-technical user? **Untested.**

### API Keys: Two-Key System

- **Starter key**: ~20 credits, baked in preseed, low value, leakage is acceptable
- **Earnings key**: Generated on-device during setup, from XMR mining, SOPS-encrypted, high value, never touches the stick

No complex provisioning flow needed. The starter key is a sampler that gets consumed during initial setup.

### Installer: Preseeded Debian Netinst

Stock Debian netinst ISO + injected `preseed.cfg` built with `xorriso`. The preseed handles partitioning, user creation, packages. A `late_command` script runs the real setup (Docker, Pi, SOPS, etc.).

Still need to validate: xorriso repack process, preseed reliability on varied hardware, whether late_command network access is reliable. **Untested.**

### Dashboard: Svelte + FastAPI (Pi Agent)

First boot: Pi Agent starts (systemd). FastAPI backend + SvelteKit frontend at `http://<lan-ip>:8080`.

**Why Svelte:**
- Tiny bundle (~15KB gzip), reactive, fast on low-power devices
- SvelteKit SSR for first-contentful-paint on slow connections
- Real product feel, not a toy
- Component model maps to service cards naturally

**Why not vanilla HTML/JS anymore:**
- Need real interactivity (service toggle, status polling, config forms, logs streaming)
- Svelte compiles to vanilla JS anyway — no runtime overhead
- Service catalog cards, subnet routing, live health checks — these need reactive state

**Why FastAPI for backend:**
- Async, WebSocket support for live logs and agent stream
- SOPS/secrets integration, Docker management, all in Python
- Pi was gonna use Python anyway (skills, SOPS CLI calls)
- Single process serves both API and static Svelte build

**Routing architecture — two model tiers:**
- DeepSeek V4 Flash (`deepseek-chat`) — service management, status, simple tasks
- GLM 5.1 (`glm-5.1`) — troubleshooting, security, complex reasoning, user chat
- Simple pattern-matching router; never silently downgrade
- Both via TokenRouter API, key from SOPS-encrypted starter/earnings key

**Skill plugin system:**
- Each service has a YAML catalog entry (docker image, port, volumes, health check, subdomain)
- Python skill classes handle install, configure, health-check, expose
- Skills are loaded dynamically from `catalog/` directory
- New services = new YAML + optional Python hook, no core changes

Works on:
- Old laptop with display (Chromium kiosk)
- Headless box (mDNS + phone/laptop browser)

Still need to validate: WebSocket reliability, mDNS on various networks, Svelte build size on arm64. **Untested.**

### Tunneling: Pangolin Cloud (verified, operational)

Using Pangolin Cloud (managed, free tier) rather than self-hosted Enterprise. Site `serverstick.com` is configured with DNS verified and tunnel resources provisioned.

**Why Pangolin, not roll-your-own WireGuard + Caddy:**
- Site provisioning, identity, RBAC, web UI — all built
- "Plug and claim" flow uses Pangolin's existing provisioning API
- Reconnection, health checks, subdomain routing — solved problems
- Non-technical users can't debug glue code failures — less custom code = more reliable
- 20k+ stars, actively maintained, FOSS

**Pangolin Cloud resources — per-device sub-sub-domains:**

Pattern: `{service}.{device}.serverstick.com` (e.g. `pdf.nick.serverstick.com`)

Each device = 1 Pangolin site with N resources. Blueprint auto-creates resources on first connect.

|| Service | Subdomain pattern | Port |
|---------|-------------------|------|
| Dashboard | dash.{device} | 8080 |
| Homepage | home.{device} | 3002 |
| Stirling-PDF | pdf.{device} | 8440 |
| PrivateBin | bin.{device} | 8084 |
| PairDrop | drop.{device} | 3000 |
| Uptime Kuma | kuma.{device} | 3001 |
| rembg | rembg.{device} | 7000 |
| Dozzle | logs.{device} | 8888 |
| Discovery API | api.{device} | 8080 |
| Watchtower | (headless, no subdomain) | — |

Current test site: "nick" (siteId 14913). Blueprint YAML below.

**Tunnel client:** Newt runs as a systemd service on the ServerStick device. Connects to `gerbil.pangolin.net:50120`. All resources route to `127.0.0.1:PORT` via Newt.

**Provisioning flow:** ISO preseeds `PANGOLIN_NEWT_ID` + `PANGOLIN_SECRET`. Bootstrap installs Newt binary, writes `/etc/serverstick/pangolin.env`, enables `serverstick-newt.service`. If credentials omitted, device operates LAN-only — run `provision-pangolin.sh` later to enable remote access.

**API details:** org-scoped key. Use `PUT /resource/{id}/target` with `{siteId, ip, port}` to wire resources. Site ID: 14913.

### Backup: Same-Stick restic (included) + Cloud (paid tier)

The USB stick installs Debian onto the host's internal storage. After install completes, Pi **wipes the USB stick and formats it as a restic backup repository**. One device — install medium becomes backup drive.

- **Free tier:** restic to the repurposed USB stick. Encrypted, deduplicated, incremental. Pi manages the schedule, verification, and notifications. Protects against OS failure, bad updates, Docker mistakes, config corruption. The user just sees "backup: active, last run 2h ago."
- **Paid tier (future):** restic to encrypted Hetzner Storage Box (€3.29/mo for 1TB) behind the same Pangolin VPS. True 3-2-1 offsite backup. Pi manages this too — zero config for the user.

The stick is never ejected after install. It sits in the port as a dedicated backup drive. Physical failure of the stick loses both the server and the backup (recovery requires re-download of same ServerStick ISO or cloud backup). Software failures leave the backup partition intact.

restic verification: Pi runs `restic check` after every backup, alerts on failure. `restic mount` lets users browse backups like a filesystem if needed.

This unlocks services with real state — messages, configs, databases are all automatically backed up to the stick.

### Service Catalog: v1 (alpha)

**Every service replaces a surveillance service.** Not "homelab tools" — "get off spyware."

**Docker Compose services (stateless or near-stateless):**

| Service | Replaces | Port | Image |
|---------|----------|------|-------|
| Homepage | Dashboard spyware | 3002 | `ghcr.io/benphelps/homepage` |
| Stirling-PDF | ilovepdf/smallpdf | 8440 | `frooodle/s-pdf` |
| PrivateBin | Pastebin/gists | 8084 | `privatebin/nginx-fpm-alpine` |
| PairDrop | WeTransfer/Drive links | 3000 | `lscr.io/linuxserver/pairdrop` |
| Uptime Kuma | UptimeRobot/Pingdom | 3001 | `louislam/uptime-kuma` |
| Dozzle | Container logs viewer | 8888 | `amir20/dozzle` |
| rembg | remove.bg | 7000 | `danielgatis/rembg` |
| Watchtower | Auto-update monitor | — | `containrrr/watchtower` (headless, cron) |

**Host services (systemd):**

| Service | Port | Description |
|---------|------|-------------|
| Discovery API | 8080 | Model discovery fallback chain |
| Newt | — | Pangolin tunnel client (systemd, no port) |

**Deferred to v2:** Tuwunel (Matrix), SearXNG, Home Assistant, IT-Tools, Pi web UI

---

### Development Model Preferences

- **GLM 5.1** — For tougher/important implementations, complex debugging, architecture decisions, and issues that need deeper reasoning. Higher quality, higher cost.
- **DeepSeek V4 Flash** — For general usage, routine tasks, drafting, and everyday development. Much lower API cost, sufficient for most work.

Both accessed via TokenRouter. Use DeepSeek by default; escalate to GLM when it matters.

---

### Cloud API: api.serverstick.com (Vercel)

The cloud side serves three functions: the `curl | bash` install target, a model discovery API with fallback, and device registration.

**Endpoints:**
- `GET serverstick.com/get.sh` — The bootstrap script (static, curlable)
- `GET serverstick.com/` — Landing page
- `GET api.serverstick.com/v1/models` — Proxy model discovery. Accepts `api_key` + `api_base`, forwards to provider, returns live models. Falls back to cached list if provider is unreachable. Falls back to hardcoded list if cache is empty.
- `GET api.serverstick.com/v1/key-status` — Validate a key without exposing it. Returns validity, model count, key prefix (first 8 chars only).
- `POST api.serverstick.com/v1/register` — Device registration beacon. v1 is simple acknowledge; v2 will return Pangolin provisioning tokens.
- `GET api.serverstick.com/health` — Service health

**Fallback chain (on-device discover.py):**
1. Cloud API (`api.serverstick.com/v1/models`) — proxied through our server, cached responses
2. Direct provider query — device talks to OpenAI/Anthropic/DeepSeek directly
3. Hardcoded model list — baked into discover.py, known-good models

This means a ServerStick works even if our cloud is down, even if the provider is down — just with a stale model list.

**Deployment:** Vercel (serverless functions for API routes, static for get.sh + landing). Porkbun for DNS. No server to manage.

**Source:** `src/cloud/` — Vercel project with `api/` routes and `public/` static files.

---

## Not Yet Decided (do not add to this file until confirmed)

- XMR mining integration details (hosted vs independent, payout flow)
- systemd target structure (setup.target → default.target)
- Hardware tier classification for AI query limits
- ISO build pipeline and per-customer key injection
- How updates work post-install
- Memory/RAM requirements per service (can all v1 services run on 4GB?)
- Svelte vs SvelteKit — do we need SSR on-device or is SPA fine?
- Pi Agent: Docker container vs host systemd service?
- Multi-device management UX (central dashboard vs per-device)

---

## Explicitly Rejected

- **Pi as active agent harness** — Running Pi in RPC mode as the brain is overkill for service management. Direct FastAPI + model router is simpler, faster, no subprocess complexity. Pi's skill concept lives on as YAML catalog + Python hooks.
- **Forking Pi** — Using it as a dependency with skills. Maintaining a fork is a trap we don't want.
- **HashiCorp Vault** — BSL-licensed, overkill, requires a running server process. SOPS + age is the right fit.
- **OpenBao** — Also overkill for our use case. No server process needed.
- **Infisical as default** — Requires running a server. Could be an optional add-on later but not the base case.
- **PI Imager fork** — Web wizard handles all user interaction. No native app to maintain.
- **Single API key** — Two-key system (starter + earnings) is the right model. The starter key being reusable isn't a real concern at 20 credits.
- **Roll-your-own WireGuard + Caddy** — Would mean reimplementing what Pangolin already does (provisioning, identity, claiming API, health checks, reconnection, subdomain routing) but worse and with nobody maintaining it. Pangolin IS WireGuard with a management layer.
- **AdGuard Home / Pi-hole in v1** — DNS blocking requires router config we can't automate, and the failure mode is the whole house losing internet. Single point of failure for all DNS. Not zero-config.
- **Vaultwarden** — Password manager where backup failure = catastrophic data loss. Consequences of failure out of proportion to convenience. Skip.
- **Jellyfin + *arr stack** — Productizing piracy is legal liability. Even LLM-guided setup doesn't create distance, it makes it worse.
- **Matrix bridges in v1** — Each bridge is a reverse-engineered integration that breaks when upstream APIs change. Managing auth, reconnection, and rate-limiting for non-technical users is high support burden. Bridges can be added later once the core Matrix experience is solid.
- **IT-Tools** — Dropped from v1. Utility knife with no clear surveillance service it replaces. Doesn't fit the "get off spyware" framing.

---

## Build Status (v0.1 Alpha)

Core scaffold implemented, VM test pending:

- ✅ `src/bootstrap/get.serverstick.sh` — Full bootstrap (Docker, Node, SOPS, age, Docker Compose services, Newt tunnel, systemd)
- ✅ `src/discover/discover.py` — Model discovery HTTP endpoint (:8080, reads SOPS secrets, queries /v1/models) — **TO BE REPLACED by Pi Agent**
- ✅ `src/skills/serverstick-setup/SKILL.md` — Pi skill definition (will become agent skills)
- ✅ `src/config/preseed.cfg.template` — Debian auto-install (%%STARTER_KEY%% + %%PANGOLIN_NEWT_ID%% + %%PANGOLIN_SECRET%%)
- ✅ `src/services/docker-compose.yml` — 8 services (needs per-device subdomain update)
- ✅ `src/services/Dockerfile.discovery` — Discovery API container (unused — host systemd)
- ✅ `src/services/serverstick-discovery.service` — systemd unit (will be replaced by Pi Agent)
- ✅ `src/services/serverstick-newt.service` — Newt tunnel systemd unit
- ✅ `src/services/homepage-config/services.yaml` — Homepage dashboard config
- ✅ `src/bootstrap/provision-pangolin.sh` — Standalone Newt installer (needs blueprint rewrite)
- ✅ `src/cloud/` — Vercel API project (needs /v1/provision endpoint)
- ✅ `src/build-iso.sh` — ISO builder (Debian netinst + inject preseed + repack)
- ✅ `ARCHITECTURE.md` — Full architecture document (new)
- ⬜ Pi Agent — FastAPI backend + Svelte dashboard + skill engine + LLM router
- ⬜ Service catalog — YAML definitions for each service
- ⬜ Cloud `/v1/provision` — Pangolin site + blueprint generation
- ⬜ Svelte dashboard — service grid, status, config, tunnel status
- ⬜ VM test — Debian 12 end-to-end validation