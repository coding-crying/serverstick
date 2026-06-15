# ServerStick Hermes Bundle

This directory bundles everything NemoClaw-wrapped Hermes needs to operate as a ServerStick sysadmin.

## Contents

```
hermes-bundle/
├── manifest.json              — skill + script + config registry
├── skills/                    — custom Hermes skills (markdown)
│   ├── pangolin-provision.md
│   ├── pangolin-resource.md
│   ├── llmfit-scan.md
│   ├── install-service.md
│   ├── hermes-webui-connector.md
│   └── hermes-tier-switch.md
├── scripts/                   — bash scripts skills invoke
│   ├── apply-tier.sh
│   └── llmfit-scan.sh
├── config/                    — env templates (Svelte GUI fills these in)
│   ├── tier.env.template
│   └── nemoclaw.env.template
├── self-hosted-infra/         — NemoClaw sandbox internal config
│   ├── README.md
│   ├── models/                — bundled GGUF files (optional, git-lfs)
│   ├── configs/
│   │   ├── inference.local.yaml
│   │   └── network-policy.yaml
│   └── bin/                   — bundled llama-server fallback
└── docs/                      — developer + GUI builder docs
```

## How it flows

1. **Bootstrap (`curl | bash`)** installs NemoClaw + Hermes, Newt, hermes-bridge (FastAPI + Svelte)
2. **Svelte GUI** opens at `http://<lan-ip>:18090`
3. **GUI step 1**: User picks subdomain → GUI POSTs to hermes-bridge `/api/onboard/subdomain`
4. **GUI step 2**: User picks AI tier (local/byo/managed) → GUI POSTs to `/api/onboard/brain`
5. **Svelte dashboard** shows running services, public URLs, hardware stats, chat with Hermes

## For the Svelte builder

The Svelte GUI talks to hermes-bridge (FastAPI, default port 18090). All bridge endpoints:

1. **Step 1 — Pick subdomain**
   - Form: subdomain input
   - POST `/api/onboard/subdomain` with `{"subdomain": "mydevice"}`
   - hermes-bridge calls Pangolin API to create site + 8 sub-subdomains, wires targets, starts Newt + Docker
   - Returns `{site_id, newt_id, subdomains: [...], newt_started, docker_started}`

2. **Dashboard — Service control**
   - GET `/api/services` → list of 8 services with live Docker status
   - POST `/api/services/{id}/start|stop|restart`
   - PATCH `/api/services/{id}/subdomain` → rename a sub-subdomain
   - POST `/api/services/provision` → re-provision a service that failed

3. **Step 2 — Pick AI tier**
   - GET `/api/hardware` → CPU/RAM/disk
   - POST `/api/hardware/scan` → llmfit results
   - POST `/api/onboard/brain` with `{tier, provider, api_key, model}`
   - GET `/api/onboard/brain/{job_id}` → poll status, logs

4. **Chat with Hermes**
   - WS `/ws/chat` — send `{message: "..."}`, receive `{content: "..."}` chunks

## For the Hermes skill runtime

Hermes reads the skills from `~/.hermes/profiles/serverstick/skills/` (or whatever path is configured in `config.yaml`). The bundle is installed to that path by `apply-tier.sh`:

```bash
cp -r /opt/serverstick/src/hermes-bundle/skills/* /root/.hermes/profiles/serverstick/skills/
```

## Notes for the GUI

- The hermes-bridge serves the Svelte build at `/` and exposes the API at `/api/*`
- All endpoints are idempotent — safe to re-run on bad input
- The bridge caches Pangolin resources locally at `/etc/serverstick/resources.json` because Pangolin's Integration API has no list endpoints

## Testing on a clean machine

1. `curl -fsSL https://get.serverstick.com/install.sh | sudo bash` on a fresh Debian VM
2. Browser opens to `http://<vm-ip>:18090`
3. Walk through the wizard: pick subdomain, pick AI tier
4. Verify `https://<sub>.serverstick.com` is reachable
5. Verify services respond at `https://<svc>.<sub>.serverstick.com`
