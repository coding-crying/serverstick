---
name: pangolin-provision
description: Create a Pangolin site (Newt tunnel endpoint) and provision subdomains for this ServerStick device. Uses the hermes-bridge API on localhost — never the raw Pangolin org key.
version: 2.0.0
triggers:
  - "/provision"
  - "provision this device"
  - "set up tunnel"
---

# Pangolin Provision

Create a site + Newt credentials for this device via the hermes-bridge API.

## When to use
- User says "I want my device on serverstick.com"
- Onboarding wizard step 1 (subdomain picked)
- Bootstrap just installed but no `/etc/newt/newt.json` yet

## What it does
1. Call `POST http://localhost:{SERVERSTICK_PORT}/api/onboard/subdomain` with `{"subdomain": "<name>"}`
2. Bridge handles: Pangolin site create, Newt config write, 8 default service resources, Newt start, Docker start
3. Returns `{subdomain, site_id, newt_id, subdomains[], newt_started, docker_started}`
4. Verify: `curl https://<sub>.serverstick.com` or check `systemctl is-active serverstick-newt`

## Bridge details
- Port is in `/etc/serverstick/agent.env` as `SERVERSTICK_PORT` (default 18090)
- Pangolin API key read from `/etc/serverstick/pangolin-api-key` at runtime
- Pangolin API: `http://89.125.209.77:3003/v1/`, orgId=`serverstick`, domainId=`domain1`
- Newt endpoint: `https://pangolin.serverstick.com`
- Config written to `/etc/newt/newt.json` (uses `"id"` key, NOT `"newtId"`)

## CLI equivalent
```bash
curl -X POST http://localhost:18090/api/onboard/subdomain \
  -H 'Content-Type: application/json' \
  -d '{"subdomain": "mydevice"}'
```
