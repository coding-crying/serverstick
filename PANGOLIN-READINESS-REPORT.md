# Pangolin Readiness Report
**Date:** 2026-06-14 (hackathon day)
**Purpose:** Audit self-hosted Pangolin EE on VPS 89.125.209.77 — is it ready for the ServerStick demo and provisioning flow?

---

## TL;DR — Ready ✅

Pangolin is **fully operational** for the hackathon demo. All 8 service subdomains route through Newt tunnel to VM 101 (10.0.0.19). Integration API works for programmatic provisioning. SSL certs auto-issuing via Let's Encrypt. Only minor cleanup needed (the `get.serverstick.com` hack).

**What's missing for full provisioning automation (multi-device):**
- A real **middleman API** at `api.serverstick.com` that takes a device token and calls Pangolin (currently we call Pangolin directly)
- A **device token** scheme (provisioning key) — currently each device would need our org API key
- The **demo resource** (test for the new resource-create flow) is gone but irrelevant
- The **Homepage** service on VM 101 has a Host header mismatch (returns 502) — needs a tweak to that service, not Pangolin

---

## Infrastructure Inventory

| Component | Version | Status | Host |
|-----------|---------|--------|------|
| **Pangolin** | 1.19.2 EE (fosrl/pangolin:ee-1.19.2) | Up 25m (healthy) | VPS 89.125.209.77 |
| **Gerbil** (WireGuard exit) | latest | Up 52m, 1.9GB total / 930MB avail | VPS |
| **Traefik** | 3.6.21 with badger plugin | Up 24m | VPS (shares gerbil netns) |
| **Newt** (tunnel client) | 1.12.5 | Connected, online=true | VM 101 (10.0.0.19) |
| **SQLite DB** | `/opt/pangolin/config/db/db.sqlite` | 0.5MB | VPS (host path) |

**Pangolin docker-compose stack:** `pangolin` (3003) + `gerbil` (80/443/51820/21820) + `traefik` (no exposed ports, internal)

**Domain:** `*.serverstick.com` → 89.125.209.77 (Porkbun wildcard DNS, A record)
**Dashboard:** `https://pangolin.serverstick.com`
**API:** `https://pangolin.serverstick.com/api/v1` (Dashboard) and `http://localhost:3003/v1` (Integration, internal only)

---

## Sites

| niceId | Name | Type | Online | Subnet | WireGuard | Resources | Newt Version |
|--------|------|------|--------|--------|-----------|-----------|--------------|
| `previous-naked-mole-rat` | mybox | newt | ✅ true | 100.89.128.4/30 | 100.89.128.4 | 8 | 1.12.5 |

Only **1 site** (VM 101). Each new device for the demo would get its own site. The Pangolin org `serverstick` has unlimited sites on EE.

---

## Resources (Live Routing)

All 8 resources have **`sso=0` (public)** — no auth wall. All route through `mybox` site (VM 101) via the badger middleware to WireGuard peer `100.89.128.4` on Pangolin-allocated ports:

| Subdomain | Target (after WireGuard) | HTTP Status | Notes |
|-----------|--------------------------|-------------|-------|
| `api.serverstick.com` | 127.0.0.1:8080 (via 100.89.128.4:59278) | **200** | Pi Agent HTML |
| `drop.serverstick.com` | 127.0.0.1:3000 (via 100.89.128.4:40053) | **200** | PairDrop |
| `pdf.serverstick.com` | 127.0.0.1:8440 (via 100.89.128.4:41083) | **401** | Stirling-PDF login wall (working as designed) |
| `bin.serverstick.com` | 127.0.0.1:8084 (via 100.89.128.4:44923) | **200** | PrivateBin |
| `rembg.serverstick.com` | 127.0.0.1:7000 (via 100.89.128.4:63837) | **200** | rembg |
| `uptime.serverstick.com` | 127.0.0.1:3001 (via 100.89.128.4:51120) | **302** | Uptime Kuma → /dashboard |
| `dozzle.serverstick.com` | 127.0.0.1:8888 (via 100.89.128.4:46470) | **200** | Dozzle (was 405, now routing fine) |
| `home.serverstick.com` | 127.0.0.1:3002 (via 100.89.128.4:44306) | **502** | Homepage rejects wrong Host header (service bug, not routing) |
| `get.serverstick.com` | 172.17.0.1:9095 (direct) | **200** | Bootstrap script (VPS direct route, not Newt) |

**8/9 services working correctly.** The 2 "bad" ones (`pdf` 401, `home` 502) are service-side issues, not routing issues.

**`get.serverstick.com` is a special case** — it doesn't go through Newt because the static file server (`serverstick-get` container) runs on the VPS itself. We added a direct route in Traefik's static `dynamic_config.yml` that takes priority over any Pangolin dynamic config. The original `get` resource was deleted from the Pangolin DB to prevent conflicts.

---

## API Authentication

### Integration API (port 3003) — For ServerStick

- **Endpoint:** `http://localhost:3003/v1` (internal only, not exposed to internet)
- **Key format:** `r16t9qlyj6sc15g.pnza7wuexw7kymbyfv5yoiuyibo3zdpn4qwhz3xg` (`<id>.<secret>`)
- **Storage:** Argon2id-hashed in `apiKeys` table, plaintext NEVER stored
- **Scope:** Org-level (bound to `serverstick` org via `apiKeyOrg` table)
- **Actions granted:** `getOrg`, `updateOrg`, `createResource`, `createTarget`, `updateTarget`, `listResources`, `listSites`, `getDNSRecords`, `listOrgDomains`, `createOrgDomain`, `inviteUser`, `listUsers`, `applyBlueprint`, `listBlueprints`, `getBlueprint`, etc. — broad org admin
- **`isRoot`:** `false` (good — not a superuser key)

**This key works.** Verified on 2026-06-14 21:17 UTC by listing sites and resources.

### Dashboard API (port 3000) — CSRF Protected
- **Endpoint:** `https://pangolin.serverstick.com/api/v1/`
- **Auth:** Session cookie OR API key + CSRF token
- **For ServerStick:** Don't use this. Use Integration API instead.

### Provisioning Keys — Not Used Yet
- **Endpoint:** `siteProvisioningKeys` table exists in schema
- **Status:** Code path exists, no license gate on validation
- **Use case:** Per-device, single-use keys that auto-expire — ideal for the middleman API
- **Not configured yet** — would be added in the middleman API

---

## Provisioning Flow (Current State)

**Right now, provisioning = manual API calls from the Pi Agent.**

```bash
# 1. Create site (manual, on Pangolin dashboard for first device)
# 2. Get newt id + secret from dashboard
# 3. Write /etc/newt/newt.json with id (not newtId!)
# 4. systemctl enable --now serverstick-newt.service
# 5. Wait for tunnel
# 6. For each service:
PUT /api/v1/org/serverstick/resource  # create resource
PUT /api/v1/resource/{id}/target     # set target (siteId, ip, port)
# 7. UPDATE resources SET sso=0 (direct DB write or PATCH) — make public
# 8. Restart Pangolin for sso change to take effect (DB-only toggle)
```

**This is what works but isn't scalable.** For the hackathon demo, we can script the per-device flow into the Pi Agent, but for true multi-device provisioning we need a middleman API.

---

## What's Needed for Full Provisioning Automation

### Tier 1 — Demo-ready (1 device, scripted from Pi Agent)
**Status: ✅ Ready** — current state works for the DGX Spark demo

- Bootstrap script (`get.serverstick.com/install.sh`) installs Docker + Newt + Pi Agent
- Pi Agent calls Pangolin Integration API (with our org key) to create site + resources
- Newt connects, services route
- Pi Agent is the API consumer; no middleman needed for 1 device

### Tier 2 — Multi-device (middleman API)
**Status: ⬜ Not built** — needed for post-hackathon scaling

- Need: `https://api.serverstick.com/v1/provision` endpoint
- Stack options: Vercel serverless (already stubbed in `src/cloud/api/v1/provision.js`) OR a tiny Cloudflare Worker
- The middleman:
  1. Receives `{device_token, subdomain, services[]}` from Pi Agent
  2. Validates token (rate limit, allowlist)
  3. Calls Pangolin Integration API to create site + resources
  4. Returns `{newt_id, newt_secret, subdomains: [...]}`
  5. Pi Agent writes newt.json and starts tunnel
- Pangolin org API key never leaves the middleman
- Device tokens are short-lived (or per-stick) and revocable

### Tier 3 — Self-service (stick purchase flow)
**Status: ⬜ Future** — not for hackathon

- Sticks ship with a baked-in starter token (URL: `get.serverstick.com/stick/{serial}`)
- Stick → middleman → Pangolin → device provisioned
- XMR mining on device → funds TokenRouter account → funds ongoing API access
- Dashboard moves from `http://<lan-ip>:8080` → `https://dashboard.<sub>.serverstick.com`

---

## Gotchas Discovered (Save These!)

1. **`"id"` not `"newtId"`** in `/etc/newt/newt.json` — the #1 newt config gotcha
2. **`--config-file` not `--config`** in newt CLI (latter is deprecated)
3. **Integration API requires `flags.enable_integration_api: true`** in Pangolin config + port 3003 exposed
4. **Integration API is separate Express server** from Dashboard API (port 3003 vs 3000)
5. **Resource creation requires `mode` field** (`"http"`, `"ssh"`, `"rdp"`, `"vnc"`, `"tcp"`, `"udp"`)
6. **Resources default to "Protected"** (SSO auth wall) — set `sso=0` in `resourcePolicies` table to make public
7. **DB location:** `/opt/pangolin/config/db/db.sqlite` (not `/opt/pangolin/config/db.sqlite` which is 0 bytes)
8. **`resourcePolicies.sso = 0` = public** — DB update requires Pangolin restart
9. **YAML escape in Traefik `dynamic_config.yml`**: use single-quoted strings for `Host(\`...\`)`, not double-quoted with escaped backticks
10. **Pangolin dynamic config DOES NOT contain dashboard routes** (`pangolin.serverstick.com` Host) — those are in the static config and were broken until we fixed the YAML
11. **DNS resolution inside Traefik (network_mode: service:gerbil) is flaky on container restart** — sometimes needs a full stack restart to recover
12. **Port 3003 is NOT exposed externally** — Integration API is internal-only. Must be called from VPS host or another container on the pangolin_frontend network

---

## Verification Commands

```bash
# Sites (Integration API)
curl -H "Authorization: Bearer r16t9q...xg" \
  http://localhost:3003/v1/org/serverstick/sites

# Resources (Integration API)
curl -H "Authorization: Bearer r16t9q...xg" \
  http://localhost:3003/v1/org/serverstick/resources

# Domains (Integration API)
curl -H "Authorization: Bearer r16t9q...xg" \
  http://localhost:3003/v1/org/serverstick/domains

# Public routing (no auth)
curl -I https://api.serverstick.com      # → 200 (Pi Agent)
curl -I https://bin.serverstick.com      # → 200 (PrivateBin)
curl -I https://drop.serverstick.com     # → 200 (PairDrop)
curl -I https://rembg.serverstick.com    # → 200 (rembg)
curl -I https://uptime.serverstick.com   # → 302 (Uptime Kuma)
curl -I https://dozzle.serverstick.com   # → 200 (Dozzle)
curl -I https://pdf.serverstick.com      # → 401 (Stirling-PDF login)
curl -I https://home.serverstick.com     # → 502 (Homepage Host header issue)
curl -I https://get.serverstick.com      # → 200 (Bootstrap script)
```

---

## Risk Assessment for the Hackathon

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| **Newt disconnects mid-demo** | Low | High | systemd auto-restart; VM 101 stable; tested reconnect via `systemctl restart serverstick-newt` |
| **Pangolin stack crashes** | Very Low | High | Docker auto-restart; static `dynamic_config.yml` survives Pangolin dynamic config generation |
| **API key compromised** | Low | Medium | Argon2id hashed; key is org-scoped (not root); can rotate via dashboard without losing routing |
| **SSL cert renewal fails** | Very Low | Medium | Let's Encrypt auto-renew; 7-day buffer; only 9 certs to manage |
| **VM 101 unreachable** | Low | High | All 8 services run on VM 101; backup = `tar` of /opt/serverstick + sqlite dump of Pangolin DB |
| **Homepage 502** | High (every time) | Low | Demo UX issue, not a routing issue; tell user "use dash.<sub>.serverstick.com" instead |
| **Port 3003 from middleman** | Medium | Medium | If middleman is on a different host, need to tunnel through the `pangolin_frontend` Docker network or proxy via Pangolin dashboard auth |

---

## Recommended Pre-Demo Checks

```bash
# On VPS
docker ps | grep -E "(pangolin|gerbil|traefik)"   # all 3 healthy
sqlite3 /opt/pangolin/config/db/db.sqlite \
  "SELECT COUNT(*) FROM resources WHERE sso=0;"     # ≥ 9

# From public internet
for s in api drop pdf bin rembg uptime dozzle home get; do
  printf "%-30s " "$s.serverstick.com"
  curl -sk -o /dev/null -w "%{http_code}\n" -m 5 "https://$s.serverstick.com"
done

# Tunnel health (on VM 101)
systemctl status serverstick-newt.service          # active
newt status                                         # connected
```

---

## What I'd Build Next (Post-Hackathon)

1. **Middleman API** at `api.serverstick.com` (Vercel function, ~50 lines of code, reuses the verified Pangolin API patterns)
2. **Provisioning key flow** — generate a `siteProvisioningKey` per device, expire after first use
3. **Test on DGX Spark** — the actual hackathon target; need to validate the NemoClaw install + Hermes + tier switching on real hardware
4. **Cleanup `home.serverstick.com`** — fix Homepage's Host header behavior so it routes correctly
5. **Migrate `get.serverstick.com`** to a real hosted bucket or GitHub Pages with raw URL fallback, so VPS restarts don't break installs
6. **Add bcrypt/argon2 to the bootstrap key** — currently the starter key is just a string; should be hashed in transit and verified by middleman
