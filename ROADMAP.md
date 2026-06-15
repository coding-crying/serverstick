# ServerStick Roadmap

**Last updated:** 2026-06-15
**Status:** Working prototype, not production. Demoed at NVIDIA hackathon on 2026-06-14. Did not make presentation groups.

---

## What we have right now

### The architecture (as built)

```
Debian/Fedora/Arch box
  → curl | bash (bootstrap.sh)
  → installs Docker, Node 22, NemoClaw (Hermes agent), Newt (tunnel), hermes-bridge
  → hermes-bridge: FastAPI on :18090 + Svelte 5 dashboard
  → hermes-bridge talks to Pangolin EE on NL VPS via REST
  → user picks subdomain → Pangolin site created → 8 sub-subdomains wired
  → user picks AI tier (BYO/local/managed) → nemohermes onboard runs
  → all services public by default, all on *.serverstick.com
```

### Code: ~6,900 LOC across 2 repos

| Repo | Path | State |
|---|---|---|
| `coding-crying/serverstick` | `/home/will/ServerStick` | Active, on `main` @ 5b1eb66, **2 commits unpushed** |
| `coding-crying/serverstick-svelte` | `/home/will/serverstick-svelte` | Initial commit only, has 1 commit ahead (the v2 dashboard with settings gear) **also unpushed** |

### Code that works (verified end-to-end on 2026-06-14)

- ✅ Bootstrap installs everything on Debian 12 + Ubuntu
- ✅ User picks subdomain → Pangolin site created → 8 resources created → targets wired → all sso=0
- ✅ Newt connects, tunnel routes traffic, `*.serverstick.com` serves the local services
- ✅ Stirling PDF, File Browser, PrivateBin, Uptime Kuma, PairDrop, rembg, Dozzle, Homepage — all running
- ✅ Settings gear icon on each tile → edit sub-subdomain live
- ✅ WebSocket chat with Hermes
- ✅ `/api/status` reports bridge, tunnel, services, disk, uptime

### Code that exists but is unverified

- 🟡 `nemohermes onboard` end-to-end on a real box (untested with real API key, untested on GB10)
- 🟡 `apply-tier.sh` skill-copy logic (untested)
- 🟡 Brain job polling (works in code, not tested live)
- 🟡 SSE → WebSocket chat parsing (works in code, not tested live)

### Infrastructure that works

- ✅ Pangolin EE running on 89.125.209.77 (NL VPS, RoyaleHosting)
- ✅ 3 sites: mybox (online), jack (offline), dellhack (offline) — all 3 are test rigs, no real users
- ✅ 18 resources across them, all sso=0
- ✅ `get.serverstick.com` serves the bootstrap script + tarball + key
- ✅ 8 service containers running on the test VM (10.0.0.19)

### What's not on disk / not deployed

- ❌ NemoClaw not installed on this dev machine (it's an NVIDIA sandbox, not pip-installable)
- ❌ Bridge not running on this dev machine (only test in code)
- ❌ Svelte v2 dashboard (with settings gear) is in `serverstick-svelte` repo but not built into the tarball that ships to the VPS
- ❌ `get.serverstick.com` is serving the **v1** tarball (without the v2 dashboard, without the dedup logic, without the health checks)

---

## What's broken / risky

### 1. The dedup bug we just hit
Pangolin's `PUT` is **not idempotent** — it creates a new site every call. We ended up with 3 dellhack sites and a resource pointed at the wrong one. **Fixed in code** (`75b08a7`), **not yet on the live tarball**. Re-running the bootstrap on a fresh box will not hit this. But the old tarball is still being served.

### 2. The GitHub push problem
We have 2 unpushed commits in `serverstick` and 1 in `serverstick-svelte`. The hackathon PAT is gone. SSH key not configured for GitHub. **Nothing is on the remote since the hackathon push.** If this dev machine dies, we lose all the work since 2026-06-13.

### 3. The 2 Pi Agent stragglers
Cleaned up 4 of 6 references. Still has 1 in `src/services/homepage-config/services.yaml` and 1 in `src/services/docker-compose.yml`. Trivial but not done.

### 4. No end-to-end test in weeks
The test VM (10.0.0.19) is unreachable. The GB10 (dellhack) is offline. We haven't run a fresh `curl | bash` on a real machine since the hackathon. The bootstrap might have rot.

### 5. The Pangolin DB has stale data
Three sites, all for test rigs (mybox, jack, dellhack). Two of three newts are offline. Resources for hackdemo6 are gone but the names linger in the conversation history. Not technically broken, but messy.

### 6. The repo is public
You wanted it private. It's public. That's leaking the bootstrap + the architecture + (if anyone reads the tarball) the Pangolin key.

---

## Roadmap

### Phase 1: Stabilize (this week)
**Goal:** Make sure what's on disk works, what's in the repo is what ships, what ships is reproducible.

- [ ] **P0** Fix the GitHub push problem (add SSH key, push the 2 + 1 unpushed commits)
- [ ] **P0** Make both repos private
- [ ] **P0** Clean the 2 Pi Agent stragglers
- [ ] **P0** Rebuild the tarball with the v2 dashboard + dedup logic + health checks
- [ ] **P0** Deploy new tarball to `get.serverstick.com`
- [ ] **P1** End-to-end test on a fresh Proxmox VM (Debian 12 clean)
- [ ] **P1** Clean Pangolin DB: delete offline sites (jack, dellhack) if the rigs are gone for good
- [ ] **P2** Rotate the leaked Pangolin API key (it's in the public tarball and in the vps)
- [ ] **P2** Move the Pangolin key out of `/etc/serverstick/pangolin-api-key` in the tarball — fetch it from `get.serverstick.com` on bootstrap, but invalidate the old one

### Phase 2: Make it real (weeks 2-4)
**Goal:** Add the things a real user would expect, but skip the things that take months.

- [ ] **P0** Add a working "delete my device" flow (user can nuke their site + resources + containers)
- [ ] **P0** Make the BYO tier actually work end-to-end on a real machine (we never tested it with a real key)
- [ ] **P0** Make hermes-bundle's skill-copy actually work when `nemohermes onboard` runs (we never verified the skills land in the right place)
- [ ] **P1** Add 2-3 more self-hosted services that fit the privacy story (Audiobookshelf, Actual Budget, possibly LibreTranslate)
- [ ] **P1** Custom domain support (user can bring their own domain instead of `*.serverstick.com`)
- [ ] **P1** Auto-update mechanism — signed, opt-in, with rollback
- [ ] **P2** Encrypted service data at rest (SOPS/age or LUKS)
- [ ] **P2** ARM64 build (currently x86_64 only)

### Phase 3: Multi-tenant (month 2+)
**Goal:** Real product. Multiple users on one Pangolin org, billing, quotas.

- [ ] Per-user resource limits
- [ ] Stripe/crypto billing
- [ ] Self-service account creation (instead of provisioning by us)
- [ ] Usage metering
- [ ] Team accounts

### Out of scope for v1 (probably never)
- Mobile app
- Email server (r/deoggle says don't self-host email)
- Kubernetes / multi-node
- Any of the rejected items from the old plan: HashiCorp Vault, forking Pi, OpenCode

---

## Open questions

1. **Distribution model.** We pivoted from "USB stick ISO" to "curl|bash" without revisiting the security implications. The old security audit flagged `curl|bash` as a HIGH risk. The new model is faster to ship but worse on supply chain. Do we ever go back to ISO?

2. **The Pi Agent ghost.** We replaced it but never formally documented why. New devs/contributors will hit references in the old PLAN, in our memory, in conversation history. Worth writing a one-pager on "what we tried, why we moved on"?

3. **The NemoClaw dependency.** It's an NVIDIA product. Not pip-installable. Not reproducible. If NVIDIA pulls it or changes it, we're hosed. Worth abstracting behind a thin shim so we can swap it out?

4. **The Svelte split.** Svelte lives in a separate repo. The build output is committed to the bridge dashboard dir. That's gross. Should the Svelte build happen as a build step, not a committed artifact?

5. **Tests.** We have zero automated tests. Everything is "I ran curl and it worked." The bridge has a lot of edge cases (Pangolin 409s, missing cache, etc.) that would benefit from even a smoke test.

---

## What to do *right now*

If I had to pick one thing to do today: **fix the GitHub push problem and make the repos private.** Everything else is downstream of "we have a canonical source of truth that isn't this machine's hard drive."

The second thing: rebuild and deploy the tarball with the v2 dashboard, dedup, and health checks, so what users install is actually what we have.
