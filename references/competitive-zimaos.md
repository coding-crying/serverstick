# ZimaOS Competitive Study

## What ZimaOS Is

**Made by IceWhale Technology** (same team behind CasaOS). ZimaOS is a commercial NAS OS built on top of CasaOS's open-source foundation. Think of it as CasaOS's "Pro" tier — polished, bundled with hardware, and monetized.

| | ZimaOS | CasaOS |
|---|---|---|
| **License** | Proprietary (closed-source on top of CasaOS) | Apache-2.0 (open source, 33.8K stars) |
| **Price** | Free (4 disks, 3 users) / $29 lifetime (ZimaOS+) | Free |
| **Hardware** | Sells own: ZimaBoard ($100-200), ZimaBoard 2, ZimaCube ($500+), ZimaBlade (~$100-200) | Any x86-64 |
| **Audience** | NAS/crossover users wanting simplicity | Homelab enthusiasts |
| **Stack** | Go backend + Vue.js frontend + Docker Compose | Go backend + Vue.js frontend + Docker Compose |

## Numbers

- **3.6M downloads** claimed
- **50K community members** (Discord)
- **162 apps** in CasaOS app store catalog
- **CasaOS: 33.8K GitHub stars**, 1908 forks
- **Languages:** 12 (EN, CN, JP, DE, IT, FR, ES, NL, PL, PT, SV, KO)

## How It Works — Technical Architecture

### CasaOS Core (what ZimaOS builds on)

- **Go backend** — monolithic service with modules: Casa, Connections, Gateway, Health, Notify, Rely, Shares, System, Storage, Peer
- **Vue.js frontend** — SPA dashboard
- **Docker Compose per app** — each app gets its own `docker-compose.yml` in `/Apps/{AppName}/`
- **`x-casaos` extensions** — custom YAML keys in docker-compose for metadata: ports descriptions, volume descriptions, env var descriptions, i18n, categories, architectures
- **`appfile.json`** — rich app metadata: title, icon, screenshots, tagline, overview, category, developer info, container config (web UI port, health checks, privileged mode, network model)
- **Port allocation** — "preferred" ports with "configurable" override (users can change ports)
- **Data paths** — `/DATA/AppData/$AppID/` convention for volumes
- **Peer-to-peer** — built-in P2P connection system for remote access

### ZimaOS Additions (on top of CasaOS)

- **RAID management** — JBOD, RAID 0/1/5/6 with "3 clicks" setup wizard
- **3-2-1 backup** — built-in backup to local, LAN, and cloud destinations
- **ZVM virtualization module** — run VMs alongside Docker (KVM-based?)
- **Zima Client** — desktop + mobile apps for remote access (P2P + relay)
- **Thunderbolt 4 support** on ZimaCube Pro for direct DAS connection
- **AI retrieval** (v1.3) — local model-based search
- **Immutable system partition** — dual-partition, dual-boot for safe rollback
- **GPU device recognition** for container workloads

### App Store Format

```yaml
# docker-compose.yml with x-casaos extensions
name: n8n
services:
  n8n:
    image: n8nio/n8n:1.123.0
    deploy:
      resources:
        reservations:
          memory: 320M
    network_mode: bridge
    ports:
      - target: 5678
        published: "5678"
        protocol: tcp
    restart: unless-stopped
    volumes:
      - type: bind
        source: /DATA/AppData/$AppID
        target: /home/node/.n8n
    x-casaos:
      envs:
        - container: TZ
          description:
            en_us: TimeZone
            zh_cn: 时区
      ports:
        - container: "5678"
          description:
            en_us: web port
      volumes:
        - container: /home/node/.n8n
          description:
            en_us: n8n directory.
    container_name: n8n

x-casaos:
  architectures:
    - amd64
    - arm64
  main: n8n
  author: YoussofKhawaja
  category: Utilities
  description:
    en_US: |
      n8n is a powerful open-source workflow automation...
```

Plus `appfile.json` with title, icon, screenshots, tagline, overview, category, developer info.

**Key pattern:** `$AppID` variable in volume source paths. CasaOS auto-resolves this to a unique app instance ID. This means multiple instances of the same app don't clash.

**Memory reservations** per app — 32M for Portainer, 320M for n8n, 1024M for Immich. Smart.

### Remote Access (No Port Forwarding)

ZimaOS uses **P2P connections** (not a tunnel/reverse proxy). Their docs say:

1. Download Zima Client on your device
2. Scan and connect to ZimaCube on LAN (first setup)
3. After first connection, remote access is auto-configured
4. P2P encrypted, peer-to-peer — data doesn't go through Zima servers
5. Automatic network link switching (LAN when home, P2P when away, Thunderbolt 4 when connected)

**Key difference from ServerStick:** Zima's approach requires their client app. ServerStick uses per-service subdomains over Pangolin (browser-only, no app needed). Trade-offs:
- Zima: P2P = private, but requires client software
- ServerStick: Browser-only, but tunnel goes through Pangolin relay

## What ServerStick Can Learn

### ✅ Things ZimaOS Does Well

1. **RAID in 3 clicks** — Their UX for RAID setup is remarkable. Screenshot shows a clean calculator showing available space based on disk selection. We don't have RAID (not NAS-first), but the *pattern* of making complex infrastructure trivially accessible is the goal.

2. **Memory reservations per app** — CasaOS app store specifies `deploy.resources.reservations.memory` per container. This is smart for resource-constrained devices. ServerStick should consider this in our service catalog YAML.

3. **`$AppID` variable in compose** — Nice pattern for multi-instance isolation. We probably won't need it (one instance per service per device), but the concept of path templating is worth noting.

4. **`x-casaos` extensions in docker-compose** — We already do something similar with our YAML catalog per service. Their approach is slightly more formal (i18n, port descriptions, architecture lists). Worth considering enriching our catalog with:
   - Memory reservations
   - Architecture support (amd64/arm64)
   - Health check commands
   - Web UI port hints (auto-link in dashboard)

5. **Immutable system partition + dual-boot rollback** — This is genuinely good. ServerStick installs Debian to disk; there's no rollback mechanism. We should consider A/B partition schemes for updates.

6. **P2P remote without client** — Not exactly, they need Zima Client. But the *idea* of auto-configure-on-first-LAN-connection is good. Our Pangolin setup already does something similar (bootstrap → get tunnel credentials → connect).

7. **3-2-1 backup messaging** — They make backup simple and visible. "All backup status at a glance" is a strong UX claim. ServerStick's restic integration should aim for this.

8. **162 apps in catalog** — We have 8. That's fine for v1, but the catalog system needs to scale. Their YAML + docker-compose pattern is proven.

9. **Local account system** — "Self-generated device identity, fully offline. No emails, phone numbers, or platform logins." This is exactly ServerStick's philosophy. Good validation.

10. **Timeline/roadmap transparency** — Their timeline page (Q1, Q2, Q3 2025 milestones) builds trust. ServerStick should consider public roadmap.

### ❌ Things ZimaOS Does Poorly (Our Opportunities)

1. **No AI sysadmin** — ZimaOS has "local AI retrieval" (v1.3) which is basically search, not management. When a Docker container crashes at 3am, you're still reading logs. **This is ServerStick's #1 differentiator.**

2. **Privacy framing is shallow** — ZimaOS says "stand against tracking and analyzing any user data" but their product page doesn't name *which surveillance services* they replace. They say "private cloud" but don't make the surveillance-to-self-hosting connection explicit. **ServerStick's "replace surveillance services" framing is sharper.**

3. **Requires their hardware** — ZimaBoard, ZimaCube, ZimaBlade. You can install on any x86 box, but the marketing pushes their hardware. **ServerStick is hardware-agnostic — USB stick works on anything.**

4. **Client app for remote access** — Needs Zima Client installed on every device. **ServerStick is browser-only.** Sub-domains just work in any browser, no installation.

5. **NAS-first, not privacy-first** — ZimaOS is fundamentally a NAS with apps. The app store is secondary to the storage story. **ServerStick flips this — services are primary, storage/backup is supporting infrastructure.**

6. **No zero-config installer** — ZimaOS requires flashing an ISO, booting, going through setup. It's "easy" but not "plug in a USB stick and it configures itself." **ServerStick's preseed + curl|bash is genuinely more turnkey.**

7. **No per-service subdomains** — ZimaOS apps are accessed via IP:port or through Zima Client. There's no clean remote URL per service. **ServerStick gives every service its own subdomain = instant sharing.**

8. **No provisioning key fleet system** — ZimaOS assumes one device. **ServerStick has Pangolin blueprints for per-device auto-provisioning.**

9. **$29 for "unlimited" vs. free for basic** — ZimaOS+ costs $29 to unlock unlimited disks/users. **ServerStick doesn't gate hardware behind paywalls.**

10. **XMR mining / sustainability model** — ZimaOS charges $29 once (they sell hardware for margin). **ServerStick uses XMR mining to fund ongoing API costs.** Different business model, but ours is more sustainable for the "service replaces surveillance" angle.

## Service Overlap

| ServerStick v1 Service | CasaOS Equivalent | Notes |
|---|---|---|
| Homepage | ❌ (CasaOS IS the dashboard) | We need Homepage; CasaOS doesn't |
| Stirling-PDF | ❌ | Not in CasaOS catalog |
| PrivateBin | ❌ | Not in CasaOS catalog |
| PairDrop | ❌ | Not in CasaOS catalog |
| Uptime Kuma | ✅ UptimeKuma | Available |
| rembg | ❌ | Not in CasaOS catalog |
| Dozzle | ❌ | Not in CasaOS catalog |
| Watchtower | ❌ | Not in CasaOS catalog (they auto-update via app store) |

**Interesting:** 5 of our 8 v1 services aren't in CasaOS's 162-app catalog. Our v1 picks are specifically chosen to *replace surveillance services* — PDF tools, pastebins, file sharing, background removal, log viewers. CasaOS's catalog is more "homelab enthusiast" (Jellyfin, Plex, *arr stack, HomeAssistant). Different philosophy entirely.

## Key Takeaways for ServerStick

1. **Add memory reservations to our service catalog YAML** — Follow CasaOS's pattern of `deploy.resources.reservations.memory`. Critical for constrained devices.

2. **Consider A/B partition scheme for updates** — ZimaOS's immutable + dual-boot pattern allows safe rollback. Our Debian install doesn't have this yet.

3. **Enrich service catalog with web UI hints** — `web_ui` port/path metadata would let our dashboard auto-link to services.

4. **Study their onboarding flow** — They have a 3-step RAID wizard. We should make our setup wizard equally smooth (currently: device name → service selection → API keys → network config → install).

5. **Their app store YAML format is worth studying** — We already have a similar pattern but could add: architecture support, health check commands, i18n descriptions, screenshots.

6. **Don't build a client app** — Their Zima Client is a friction point. Browser + subdomains is simpler.

7. **Local account = right call** — Validates our no-SSO decision.

8. **162 apps vs 8** — We're v1, scope is fine. But our catalog system needs to scale cleanly.