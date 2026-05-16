# ServerStick — Implementation Plan

Only things we've decided go here. Everything else stays in conversation until validated.

## Decided

### Product

USB stick that installs a preconfigured Debian self-hosting stack onto host storage. Not a persistent live OS — it installs to disk. One-time purchase, XMR mining funds ongoing API costs.

**Core mission:** Help people get off surveillance services onto their own stack. Every service replaces something that harvests your data — searches, documents, photos, messages, file sharing.

### LLM Harness: Pi (NOT forked)

Using [Pi](https://github.com/earendil-works/pi) as the agent harness. Not forking it — using it as a dependency via its skill/extension system.

Confirmed reasons:
- RPC mode (JSONL over stdin/stdout) — works headless, works behind a web bridge
- Skill system — we write custom tools, no core changes needed
- pi-web-ui components — ready-made chat UI pieces if we want them
- MIT licensed, lightweight
- Multi-provider LLM support (cheapest model that works)

Still need to validate: Can Pi skills do everything we need? Do they run in RPC mode? Does the skill packaging work for our use case? **Untested.**

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

### Setup: Custom Web Wizard + Pi RPC

First boot: Pi starts in `--mode rpc`. A thin WebSocket bridge ( Node or Python, TBD) serves a custom web wizard — **not** React, not pi-web-ui. Vanilla HTML/JS frontend, no build step, no node_modules on the target.

**Why custom, not pi-web-ui:**
- pi-web-ui is a coding chat interface. We need a setup wizard (hardware scan → service picker → key entry → install). Wrong abstraction.
- The wizard is a form flow, not a conversation. Pi provides the intelligence behind the scenes, the wizard renders results.
- Vanilla HTML/JS works on any browser including old phones. Ships small.

**Agent Activity panel (polish, not required):**
- Collapsible sidebar/panel showing Pi's raw JSONL stream — tool calls, thinking, responses, errors
- Same data the wizard uses, just rendered as-is for debug/transparency
- Strictly additive — second render target on the same WebSocket, no architecture change

Works on:
- Old laptop with display (Chromium kiosk)
- Headless box (mDNS + phone/laptop browser)

Still need to validate: WebSocket bridge reliability, mDNS on various networks, Chromium kiosk behavior, Pi skill tool execution in RPC mode. **Untested.**

### Tunneling: Pangolin Cloud (verified, operational)

Using Pangolin Cloud (managed, free tier) rather than self-hosted Enterprise. Site `serverstick.com` is configured with DNS verified and tunnel resources provisioned.

**Why Pangolin, not roll-your-own WireGuard + Caddy:**
- Site provisioning, identity, RBAC, web UI — all built
- "Plug and claim" flow uses Pangolin's existing provisioning API
- Reconnection, health checks, subdomain routing — solved problems
- Non-technical users can't debug glue code failures — less custom code = more reliable
- 20k+ stars, actively maintained, FOSS

**Pangolin Cloud resources (serverstick.com):**

| Subdomain | Service | Port |
|-----------|---------|------|
| home | Homepage dashboard | 3002 |
| pdf | Stirling-PDF | 8440 |
| bin | PrivateBin | 8084 |
| drop | PairDrop | 3000 |
| kuma | Uptime Kuma | 3001 |
| rembg | Background removal API | 7000 |
| logs | Dozzle (container logs) | 8888 |
| api | Discovery endpoint | 8080 |
| pi | Pi agent (future) | — |
| tools | IT-Tools (future) | — |

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
- Pi skill package structure (we designed one but haven't tested it)
- systemd target structure (setup.target → default.target)
- Hardware tier classification for AI query limits
- Checkmark UI vs. web-only management
- ISO build pipeline and per-customer key injection
- How updates work post-install
- Memory/RAM requirements per service (can all v1 services run on 4GB?)

---

## Explicitly Rejected

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

Core scaffold implemented, untested on VM:

- ✅ `src/bootstrap/get.serverstick.sh` — Full bootstrap (Docker, Node, SOPS, age, Pi, Docker Compose services, Newt tunnel, systemd)
- ✅ `src/discover/discover.py` — Model discovery HTTP endpoint (:8080, reads SOPS secrets, queries /v1/models)
- ✅ `src/skills/serverstick-setup/SKILL.md` — Pi skill (check-hardware, install-service, configure-sops, check-network)
- ✅ `src/config/preseed.cfg.template` — Debian auto-install (%%STARTER_KEY%% + %%PANGOLIN_NEWT_ID%% + %%PANGOLIN_SECRET%%)
- ✅ `src/services/docker-compose.yml` — 8 services (Homepage, Stirling-PDF, PrivateBin, PairDrop, Uptime Kuma, Dozzle, rembg, Watchtower)
- ✅ `src/services/Dockerfile.discovery` — Discovery API container (unused — switched to host-level systemd)
- ✅ `src/services/serverstick-discovery.service` — Discovery endpoint systemd unit
- ✅ `src/services/serverstick-newt.service` — Newt tunnel systemd unit
- ✅ `src/services/homepage-config/services.yaml` — Homepage dashboard config
- ✅ `src/bootstrap/provision-pangolin.sh` — Standalone Newt installer + systemd service
- ✅ `src/cloud/` — Vercel API project (model discovery proxy, key validation, device registration)
- ✅ `src/build-iso.sh` — ISO builder (Debian netinst + inject preseed + repack)
- ⬜ VM test — Need Debian 12 VM to validate end-to-end
- ⬜ WebSocket bridge — Pi RPC ↔ browser (next milestone)
- ⬜ Web wizard — HTML/JS form flow (next milestone)