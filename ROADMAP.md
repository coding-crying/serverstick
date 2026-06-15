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

1. **The dedup bug we just hit** — Pangolin's `PUT` is not idempotent. Fixed in code (`75b08a7`), not yet on the live tarball.
2. **The GitHub push problem** — 2 unpushed commits in `serverstick`, 1 in `serverstick-svelte`. Hackathon PAT gone. Nothing on remote since 2026-06-13.
3. **The repo is public** — you wanted it private. Leaking bootstrap + architecture + Pangolin key.
4. **Pangolin key leaked** — baked into the public tarball. Needs rotation.
5. **No end-to-end test in weeks** — test VM (10.0.0.19) unreachable, GB10 offline, bootstrap might have rot.
6. **The Pangolin DB has stale data** — three test sites, two offline. Not technically broken, but messy.
7. **Old PLAN.md is gone** — deleted in the `2eb0939 wipe: clear main for Hermes-first rewrite` commit (2026-06-14). This file replaces it.

---

## The business model (the part that makes it viable)

### The problem with "free with XMR mining"

Pure "free as in beer" is a money pit. VPS bandwidth, Pangolin EE license (if it goes paid), AI inference — they all cost money. The user paying for everything themselves with no revenue = death.

But the user doesn't actually need our VPS for most things. They need a way to make their services reachable from the internet. They can do that themselves with their own tunnel, their own domain, their own port forwarding. Our VPS is one option, not the only one.

### The four tiers

| Tier | Tunnel | AI | Backups | Cost to user | Cost to operator |
|---|---|---|---|---|---|
| **Self-hosted (free forever)** | User's own (WireGuard, Cloudflare, Tailscale, port forward) | Local model, or user pays for own API key | User provides own target | **$0** | **$0** |
| **Hosted with XMR (free to user)** | Our Pangolin on `*.serverstick.com` | Earned via mining XMR in the background | Not included | Mine XMR on the box | VPS bandwidth only |
| **Hosted without XMR (paid)** | Our Pangolin on `*.serverstick.com` | User pays with credits (bought with XMR or fiat) | Not included | $5/mo for 1M AI tokens, or pay-as-you-go | VPS bandwidth + AI inference |
| **Backups (real revenue)** | Either | Either | Encrypted BorgBackup to our Hetzner storage | $6/TB/month | $3.80/TB (Hetzner) |

**The key insight:** the **self-hosted tier is genuinely free and we're fine with it.** It costs us nothing because no traffic flows through our VPS. The user gets full functionality. We get nothing from them directly, but we get:
- Word of mouth / network effect
- Future conversion to hosted tier when they outgrow DIY
- Reputation as "the one that doesn't lock you in"

The hosted tier (Pangolin routing) costs us real money (bandwidth), so it must be paid for — either by XMR or by fiat.

The backup tier is the only one with real margin. $6 - $3.80 = $2.20/TB/month. At 1,000 paying users with 1TB each = $2,200/month net. That's not a business, but it's enough to fund the VPS and a part-time maintainer.

### Why the XMR-as-credit-economy works

If 10,000 users opt in to mining on their boxes:
- ~5 kH/s per box (50W CPU, 24/7)
- 50 MH/s total = ~1% of network hashrate
- 4.3 XMR/day at $150 = **$648/day = $237K/year**
- All to one wallet (the operator's)

The user never touches XMR. They get "credits" in their dashboard. Conversion is internal:
- Mining rate: 5 kH/s for 24h = $0.10 of credits
- AI cost: 100 DeepSeek V4 Flash messages = $0.014 of inference
- So 24h of mining = ~700 messages
- Volatility is absorbed by the operator, not the user

### Why this doesn't bleed

- **Self-hosted users** = $0 to us
- **Hosted + XMR users** = their mining covers our VPS cost
- **Hosted + fiat users** = their payments cover our VPS + inference
- **Backup users** = positive margin

The only path to bleeding is: a hosted user who opted out of XMR and doesn't pay. **That's not a tier we offer.** You either mine, pay, or self-host.

### The "I don't want to be locked in" stance

The user's words: *"I don't care if users want to use my product for free. I just don't want to bleed."*

This is the right product stance. The default tier is "free, bring your own tunnel." The hosted tier is opt-in, paid for in some form. We never lock anyone out, we never charge for things that don't cost us money.

### Risks to the model

- **XMR regulatory pressure** — delisting from exchanges would hurt the opt-in mining tier. Mitigation: also accept BTC Lightning and fiat.
- **Mining unprofitability** — if XMR difficulty spikes or price crashes, free users stop mining. Mitigation: have a hard cap on hosted free tier (1 GB egress/month), then they must self-host or pay.
- **User gaming** — mine briefly, claim credits, kill miner, use forever. Mitigation: credits earned per (hashrate × hours) per day, not per minute.
- **The 1% problem** — one heavy user on the hosted tier can cost more in bandwidth than 100 light users. Mitigation: bandwidth caps per hosted user, soft cap at 5 GB/month, hard cap at 50 GB/month, then throttled.

---

## Distribution / install options

Today: `curl|bash` only. The roadmap expands to three options.

### Option A: `curl|bash` (today, for hackers)

`curl -fsSL https://get.serverstick.com/install.sh | sudo bash`

- ✅ Fast to ship, zero friction for the user
- ❌ No drive selection — installs alongside whatever's there
- ❌ No "this is destructive" warning
- ❌ Supply chain risk (compromise of get.serverstick.com = pwn every install)
- ❌ Doesn't fit "normal humans" — they're scared of `curl|bash`

### Option B: Debian live image (the right way, build this)

A bootable ISO that:
1. Boots into live Debian
2. Detects all drives, asks **which one to wipe** (explicit, no surprises)
3. Runs `preseed.cfg` to install Debian + ServerStick to that drive
4. Sets a per-ISO random password, printed on the USB sticker
5. First boot → setup wizard
6. Done

Implementation: stock Debian netinst + custom `preseed.cfg` + our bootstrap script in the ISO + xorriso to build.

Effort: 1-2 weeks. The deleted `src/config/preseed.cfg.template` was a start — needs recreating.

### Option C: Physical USB stick (the customer-acquisition product)

A 32GB USB3 stick we ship for ~$30-50 that includes:
- The Debian live image (Option B)
- A **provisioning token** baked into the image (UUID burned at manufacture time)
- A sticker with: device name slot, QR code linking to setup docs, recovery info

When the user plugs it in and installs, the bridge calls our API:
```
POST /v1/provision {provisioning_token: "uuid-xxxx"}
→ returns: {pangolin_api_key, starter_credits: 5000, ...}
```

No API key entry. No XMR setup required (mining is still opt-in for extra credits). Just works.

This is the **acquisition product**. The stick pays for itself through future backup subscriptions.

---

## The install flow (the future)

The end-to-end install should feel like:

1. **Get a stick** (or download ISO) → 1-2 days shipping or instant
2. **Plug in, boot, pick drive** → 5 minutes, mostly waiting
3. **First-boot wizard**:
   - **Step 1: Identity** — pick a name (e.g. "kitchenpi") OR plug in provisioning token
   - **Step 2: Hardware scan** — bridge runs `llmfit`, shows: "8GB RAM, 4 cores, no GPU. We recommend: Qwen3 1.7B for chat, Whisper base for STT. DeepSeek V4 Flash via cloud for harder questions."
   - **Step 3: Choose routing** — "Use our hosted `*.serverstick.com` (XMR or paid)" OR "Bring your own tunnel" (with guided setup for Cloudflare / Tailscale / port forward)
   - **Step 4: Choose services** — pre-checked the 8 defaults, user can uncheck, add more from catalog
   - **Step 5: Choose AI tier** — Local / BYO key / Hosted credits / Mining-funded
   - **Step 6: (optional) Backups** — show pricing, default off, easy to enable later
4. **Done** → dashboard with all the URLs

The hardware scan should be a **live report**, not a placeholder. Run `llmfit-scan` for real, show actual numbers: CPU model, RAM, disk free, whether GPU is detected, recommended local model size.

---

## Roadmap

### Phase 1: Stabilize (this week)
**Goal:** Make sure what's on disk works, what's in the repo is what ships, what ships is reproducible.

- [ ] **P0** Fix the GitHub push problem (add SSH key, push the 2 + 1 unpushed commits)
- [ ] **P0** Make both repos private
- [ ] **P0** Rebuild the tarball with the v2 dashboard + dedup logic + health checks
- [ ] **P0** Deploy new tarball to `get.serverstick.com`
- [ ] **P0** End-to-end test on a fresh Proxmox VM (Debian 12 clean)
- [ ] **P1** Clean Pangolin DB: delete offline sites (jack, dellhack) if the rigs are gone for good
- [ ] **P2** Rotate the leaked Pangolin API key (regenerate on VPS, update get.serverstick.com)

### Phase 2: Real install + real revenue (weeks 2-4)
**Goal:** Live image installer + backups as the first paid product.

- [ ] **P0** Live Debian ISO installer (drive picker, preseed, first-boot wizard)
- [ ] **P0** BorgBackup integration — free tier with 1 GB cap on Hetzner Storage Box
- [ ] **P0** Paid backup tier: $6/TB/month, Stripe + XMR payment options
- [ ] **P1** Local IP passthrough + mDNS + QR code for media (Jellyfin etc.)
- [ ] **P1** Self-host mode: user provides their own tunnel/domain, no Pangolin
- [ ] **P1** Hardware scan made real in the wizard (actual llmfit output, not placeholders)
- [ ] **P2** Live hardware detection in the ISO (show CPU/RAM/disk before install)

### Phase 3: XMR economy + scale (month 2)
**Goal:** The XMR-funded hosted tier works at scale. Real users.

- [ ] **P0** XMR mining opt-in toggle in the dashboard
- [ ] **P0** Credit balance + burn-down rate display
- [ ] **P0** Model tier gating (free credits = DeepSeek Flash only, better models need payment)
- [ ] **P1** Time-decay on credits (90 days, prevents the "mine once, use forever" attack)
- [ ] **P1** Bandwidth caps on hosted free tier (5 GB soft, 50 GB hard, then throttle)
- [ ] **P2** Multi-region VPS (cheaper for non-EU users, lower latency)

### Phase 4: Physical product (month 3)
**Goal:** The USB stick is a real product people can buy.

- [ ] **P0** Provisioning token system (UUID → API key + starter credits)
- [ ] **P0** Fulfillment pipeline (Stripe order → print sticker → ship)
- [ ] **P1** Sticker design + printer integration
- [ ] **P2** Bulk pricing (white-label for sysadmins who want to deploy at work)

### Out of scope for v1 (probably never)
- Mobile app
- Email server (r/degoogle says don't self-host email)
- Kubernetes / multi-node
- Any of the rejected items from the old plan: HashiCorp Vault, forking Pi, OpenCode

---

## Open questions

1. **Pricing for the hosted-without-XMR tier.** Right now I wrote "$5/mo for 1M AI tokens." That's an estimate. Needs real numbers from TokenRouter. Also: do we do pure pay-as-you-go, or only subscriptions?

2. **The Pi Agent ghost.** We replaced it but never formally documented why. New devs/contributors will hit references in the old PLAN, in our memory, in conversation history. Worth writing a one-pager on "what we tried, why we moved on"?

3. **The NemoClaw dependency.** It's an NVIDIA product. Not pip-installable. Not reproducible. If NVIDIA pulls it or changes it, we're hosed. Worth abstracting behind a thin shim so we can swap it out?

4. **The Svelte split.** Svelte lives in a separate repo. The build output is committed to the bridge dashboard dir. That's gross. Should the Svelte build happen as a build step, not a committed artifact?

5. **Tests.** We have zero automated tests. Everything is "I ran curl and it worked." The bridge has a lot of edge cases (Pangolin 409s, missing cache, etc.) that would benefit from even a smoke test.

6. **Monero custody.** If we hold XMR for 10K users, we hold a lot of XMR. Are we a regulated money service? Do we need a money transmitter license? Or is the "credits" abstraction enough to keep us out of that?

7. **The provisioning token for sticks.** UUID-based tokens are easy to forge if someone reads them off a sticker. Need either (a) signed tokens with a private key, or (b) a one-time redemption URL on the back of the sticker that requires physical access to redeem.

---

## What to do *right now*

If I had to pick one thing to do today: **fix the GitHub push problem and make the repos private.** Everything else is downstream of "we have a canonical source of truth that isn't this machine's hard drive."

The second thing: rebuild and deploy the tarball with the v2 dashboard, dedup, and health checks, so what users install is actually what we have.

The third thing: start the live ISO work. We deleted the preseed template, we need to recreate it. It's a 1-2 week project but it's the difference between "hackathon demo" and "thing you can hand to a non-technical friend."
