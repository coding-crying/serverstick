# Matrix (Synapse) Service Spec

## Mission Fit

Matrix replaces WhatsApp, Discord, Telegram — the highest-value surveillance services. Messaging is where the most metadata harvesting happens. This is *the* killer service for the "get off surveillance" pitch.

Federation and bridges are core features, not add-ons. A non-federated Matrix server is just a worse Slack. Without bridges, you're asking people to convince contacts to install a new app — that's the #1 reason privacy tools fail. Bridges let users message their existing contacts from Matrix, enabling gradual migration.

## Architecture

### Components

| Component | Image | Port | Purpose | RAM |
|-----------|-------|------|---------|-----|
| Synapse | `matrix-org/synapse:latest` | 8008 | Homeserver | ~500MB (SQLite) |
| Element Web | `vectorim/element-web:latest` | 8080 | Web client | ~50MB (static) |

**Important:** Element Web is a static SPA served by nginx — ~50MB RAM overhead. Synapse is the heavy lifter.

### Ports & Subdomains

| Subdomain | Port | Purpose |
|-----------|------|---------|
| `chat.{device}` | 8080 (Element) | User-facing web client |
| `matrix.{device}` | 8008 (Synapse CS API) | Client-server API + well-known |

### PostgreSQL vs SQLite

**Decision: SQLite for v1.** Synapse supports SQLite out of the box (default). It's fine for single-user/family deployments (~50 concurrent users). PostgreSQL is needed for >100 users or heavy federation traffic.

The Pi Agent skill will have a `migrate_to_postgres()` method for power users who outgrow SQLite. But adding a PSQL container to every install by default is overkill — that's an extra ~200MB RAM and another stateful service to back up.

### Federation

**Enabled by default.** Federation is what makes Matrix valuable — users can talk to anyone on any Matrix server.

**How it works with ServerStick:**
- Synapse `server_name` = `{device}.serverstick.com` (e.g., `nick.serverstick.com`)
- `.well-known/matrix/server` served by Synapse at `https://matrix.{device}.serverstick.com/.well-known/matrix/server`
- Returns `{"m.server": "matrix.{device}.serverstick.com:443"}` 
- Pangolin terminates TLS at the edge — Synapse only sees local traffic
- Federation traffic arrives at port 443 on `matrix.{device}.serverstick.com`, Pangolin routes it to `127.0.0.1:8008`
- No need to expose port 8448 — all federation goes through 443 via the well-known delegation

**User IDs:** `@username:{device}.serverstick.com` (e.g., `@will:nick.serverstick.com`)

**Custom domain (v2):** Allow users to bring their own domain. `@username:theirdomain.com` with federation still through Pangolin.

### Bridges

Bridges are opt-in per-service, installed through the Pi Agent dashboard. Each bridge is a separate Docker container running [mautrix](https://maupoint.org/bridges/) or [beeper](https://github.com/beeper) bridge software.

#### Bridge Priority

| Bridge | Replaces | Image | Auth Method | Support Level |
|--------|----------|-------|-------------|---------------|
| **WhatsApp** | WhatsApp | `mautrix/whatsapp:latest` | QR code scan (phone) | Tier 1 — most requested |
| **Discord** | Discord | `mautrix/discord:latest` | OAuth2 bot invite | Tier 1 — second most requested |
| **Telegram** | Telegram | `mautrix/telegram:latest` | Bot token + phone | Tier 2 |
| **Signal** | Signal | `mautrix/signal:latest` | Phone number linking | Tier 2 |
| **Slack** | Slack | `beeper/slack-bridge` | OAuth2 | Tier 3 — business use |

#### Bridge Ports

| Bridge | Port | Subdomain |
|--------|------|-----------|
| WhatsApp bridge | 8440 | (internal — no public subdomain needed) |
| Discord bridge | 8441 | (internal) |
| Telegram bridge | 8442 | (internal) |
| Signal bridge | 8443 | (internal) |

Bridges don't need their own Pangolin subdomains — they communicate through Synapse's Client-Server API locally.

### Pi Agent Guardrails (Skill System)

This is the key innovation that makes bridges survivable for non-technical users. The Pi Agent skill for Matrix includes intelligent monitoring, auto-recovery, and user-facing guidance.

#### Skill: `matrix.yaml` + `MatrixSkill` class

The Matrix skill extends `SkillBase` with bridge management, health monitoring, and automatic remediation. This is where the "AI sysadmin" value prop becomes real.

**Guardrails by category:**

##### 1. Bridge Health Monitoring
```python
class MatrixSkill(SkillBase):
    def bridge_status(self, bridge_name: str) -> dict:
        """Check bridge container health + last event timestamp."""
        # Checks: container running? Last event within 5 min? Errors in logs?
        # Returns: healthy | degraded | down | auth_required
        
    def auto_restart_bridges(self) -> dict:
        """Restart any bridge that's been down > 2 minutes."""
        # Called by Pi Agent on health check cycle
        
    def bridge_reauth_needed(self, bridge_name: str) -> bool:
        """Detect if a bridge needs re-authentication."""
        # WhatsApp: QR code expired (every ~2 weeks)
        # Discord: token revoked
        # Telegram: bot token invalid
        # Returns True if user action needed
```

##### 2. Automatic Bridge Recovery
- **Container crash:** Auto-restart within 2 minutes. If 3 restarts in 10 min, alert user via dashboard + don't restart-loop.
- **Auth expiry:** WhatsApp QR codes expire every ~2 weeks. Pi Agent detects the "need to re-login" state and shows a notification in the dashboard with a QR code to scan. User scans from phone, bridge reconnects.
- **Network issues:** Bridges lose connection frequently. Pi Agent restarts the bridge container, checks Synapse reachability first, and only restarts if Synapse is healthy.
- **Rate limits:** Detect Matrix rate-limiting (429s from other homeservers). Back off bridge message sending automatically.

##### 3. User-Facing Bridge Management
```python
    def setup_bridge(self, bridge_name: str) -> dict:
        """Guided bridge setup via Pi Agent dashboard."""
        # 1. Pull bridge image
        # 2. Generate bridge config from template
        # 3. Register bridge as Synapse application service
        # 4. Start bridge container
        # 5. Return auth instructions (QR code for WhatsApp, Bot token for Telegram, etc.)
        
    def get_bridge_qr(self, bridge_name: str) -> dict:
        """Get current auth QR code for bridges that need one."""
        # Extracts QR from bridge logs/data
        # Returns base64 PNG for dashboard display
        
    def remove_bridge(self, bridge_name: str) -> dict:
        """Clean bridge removal — stop container, unregister from Synapse, clean data."""
```

##### 4. Federation Guardrails
```python
    def federation_status(self) -> dict:
        """Check federation health — can other servers reach us?"""
        # Verifies .well-known is accessible
        # Checks federation reachability from external test
        # Returns: federating | partial | broken | disabled
        
    def federation_audit(self) -> dict:
        """Audit federation config for common issues."""
        # Checks: server_name matches domain, TLS valid, well-known correct
        # Validates SRV records if custom domain
        # Returns list of issues + fixes
```

##### 5. User Registration Guardrails
- **Default: closed registration.** Users are created by the admin via dashboard.
- Admin creates accounts in setup wizard (1 admin + N family members).
- Registration shared secret stored in SOPS — Pi Agent can create accounts programmatically.
- Optional: open registration with reCAPTCHA (requires domain+reCAPTCHA keys, not for v1).

### Synapse Config Template

Key settings for the ServerStick deployment:

```yaml
# homeserver.yaml (generated by Pi Agent)
server_name: "{{ device }}.serverstick.com"

# SQLite for v1 (migrate to PSQL for >50 users)
database:
  name: sqlite3
  args:
    database: /data/homeserver.db

# Federation enabled
enable_federation: true
federation_domain_whitelist: null  # federate with everyone

# Registration closed by default
enable_registration: false
registrations_require_3pid: []
registration_shared_secret: "{{ SOPS:registration_shared_secret }}"

# Logging — rotate aggressively on small devices
log_config: /data/log.config

# Rate limiting — protect against abuse
rc_federation:
  window_size: 1000
  sleep_limit: 500
  sleep_moderate: 1.0
  sleep_limit: 0.1
  
rc_message:
  per_second: 0.2
  burst_count: 10

# Media storage limits
media_store_path: /data/media
max_upload_size: 50M
max_image_pixels: 32M

# Application services (bridges will be registered here)
app_service_config_files: []
# Added dynamically when bridges are installed:
# - /data/bridges/whatsapp/registration.yaml
# - /data/bridges/discord/registration.yaml
```

### Docker Compose Entry (Matrix + Element)

```yaml
synapse:
  image: matrix-org/synapse:latest
  container_name: synapse
  restart: unless-stopped
  ports:
    - "127.0.0.1:8008:8008"  # Client API + federation
  volumes:
    - /var/lib/serverstick/data/synapse:/data
  environment:
    SYNAPSE_CONFIG_PATH: /data/homeserver.yaml

element:
  image: vectorim/element-web:latest
  container_name: element
  restart: unless-stopped
  ports:
    - "127.0.0.1:8080:80"  # Web client
  volumes:
    - /var/lib/serverstick/data/element/config.json:/app/config.json
```

### Bridge Compose Entries (per-bridge, added dynamically)

```yaml
# Added by Pi Agent when user enables WhatsApp bridge
whatsapp-bridge:
  image: mautrix/whatsapp:latest
  container_name: whatsapp-bridge
  restart: unless-stopped
  ports:
    - "127.0.0.1:8440:8080"  # Internal only
  volumes:
    - /var/lib/serverstick/data/bridges/whatsapp:/data
  depends_on:
    - synapse
```

### Catalog Entry: matrix.yaml

```yaml
name: synapse
display: Matrix (Synapse)
replaces: "WhatsApp / Discord / Telegram"
icon: "💬"
category: communication
description: "Private messaging server — chat with anyone on Matrix, bridge to WhatsApp, Discord, and Telegram."
docker:
  image: matrix-org/synapse:latest
  port: 8008
  restart: unless-stopped
  volumes:
    - /var/lib/serverstick/data/synapse:/data
  environment: {}
health:
  endpoint: /_matrix/client/versions
  method: GET
  expect_status: 200
pangolin:
  subdomain: matrix
llm_cost: low
bridges:
  whatsapp:
    image: mautrix/whatsapp:latest
    port: 8440
    auth: qr_code
    reauth_frequency: 14d
  discord:
    image: mautrix/discord:latest
    port: 8441
    auth: oauth2
    reauth_frequency: never
  telegram:
    image: mautrix/telegram:latest
    port: 8442
    auth: bot_token
    reauth_frequency: never
  signal:
    image: mautrix/signal:latest
    port: 8443
    auth: phone_link
    reauth_frequency: 90d
companion:
  name: element
  image: vectorim/element-web:latest
  port: 8080
  pangolin_subdomain: chat
```

### Element Web Config

```json
{
  "default_server_config": {
    "m.homeserver": {
      "base_url": "https://matrix.{{ device }}.serverstick.com"
    }
  },
  "disable_custom_urls": true,
  "disable_3pid_login": true,
  "brand": "ServerStick Chat",
  "show_labs_settings": false
}
```

## Resource Requirements

| Scenario | RAM | Storage |
|----------|-----|---------|
| Synapse (SQLite) + Element | ~550MB | ~1GB (grows with media) |
| + WhatsApp bridge | ~800MB total | +500MB |
| + All 4 bridges | ~1.5GB total | +2GB |

**Minimum device spec with Matrix:** 4GB RAM (same as v1 baseline, but tight with all 4 bridges). 8GB recommended for full bridge suite.

**The Pi Agent should surface this recommendation:** "Installing Matrix + WhatsApp bridge requires ~800MB RAM. Your device has 4GB — this will work but leaves limited headroom. Consider upgrading to 8GB for all bridges."

## Setup Wizard Flow

1. User selects "Matrix" from service catalog
2. Pi Agent asks for device name (already set during provisioning) → derives `server_name`
3. Pi Agent generates Synapse config + signing key
4. Pi Agent registers 1 admin account + optional family accounts
5. Element Web deployed with correct `base_url`
6. Pangolin resources created: `matrix.{device}` + `chat.{device}`
7. Federation tested (Pi Agent verifies `.well-known` is reachable externally)
8. Bridges offered as opt-in: "Connect to WhatsApp? Discord? Telegram?" Each has a one-click setup flow with auth instructions.
9. Dashboard shows bridge health status at all times.

## Pitfalls

- **WhatsApp QR code re-auth every ~2 weeks** — This is the biggest support burden. The Pi Agent MUST detect this state and surface the QR code in the dashboard. Users will get a notification: "Your WhatsApp bridge needs re-scanning. Click to show QR code."
- **Synapse signing key is irreplaceable** — If lost, the server can't federate and all user IDs become invalid. Must be in SOPS + restic backup. NOT on the USB stick.
- **Federation requires stable domain** — Once federated, `{device}.serverstick.com` is embedded in user IDs on remote servers. Domain change = new identity. The device name must be chosen carefully.
- **Bridge containers share Docker network with Synapse** — They communicate via Synapse's Client-Server API on `http://synapse:8008`. Use Docker network aliases, not host networking.
- **Bridge application service registrations** — Each bridge needs a `registration.yaml` loaded by Synapse at startup. Adding/removing bridges requires Synapse restart. Pi Agent handles this.
- **Media storage grows unbounded** — Synapse doesn't prune media by default. Need a cleanup job (synapse-media-cleanup cron) or set `max_upload_size: 50M` and periodic `synapse-compress-media` runs.
- **Docker networking** — All current services use `network_mode: host`. Synapse + bridges should use a dedicated Docker network (`serverstick-matrix`) so bridge containers can reach `http://synapse:8008` by hostname. Element and Pangolin Newt still reach Synapse via host network on `127.0.0.1:8008`.
- **Element config must hardcode homeserver URL** — The `base_url` in Element's `config.json` must point to `https://matrix.{device}.serverstick.com`, not `localhost`. This is generated by Pi Agent during setup.
- **Federation key delegation** — Synapse's `/.well-known/matrix/server` endpoint must return the correct server name and port. With Pangolin terminating TLS at 443, the well-known response should delegate to port 443 (default), not 8448.