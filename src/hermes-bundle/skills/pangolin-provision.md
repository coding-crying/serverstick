---
name: pangolin-provision
description: Create a Pangolin site (Newt tunnel endpoint) and provision subdomains for this ServerStick device. Uses the ServerStick provisioning API (middleman) — never the raw Pangolin org key.
version: 1.0.0
triggers:
  - "/provision"
  - "provision this device"
  - "set up tunnel"
---

# Pangolin Provision

Create a site + Newt credentials for this device via the ServerStick middleman API.

## When to use
- User says "I want my device on serverstick.com"
- Onboarding wizard step 1 completes (subdomain picked)
- Bootstrap just installed Newt but no `/etc/newt/newt.json` yet

## What it does
1. Read device token from `/etc/serverstick/device.token` (or env)
2. POST to `https://api.serverstick.com/v1/provision` with `{subdomain, services[]}`
3. Receive `{newt_id, newt_secret, subdomains: [...]}`
4. Write `/etc/newt/newt.json` with id (not newtId!), endpoint, secret
5. `systemctl enable --now serverstick-newt`
6. Wait for tunnel to come up, verify with `curl https://<sub>.serverstick.com`

## Env vars used
- `SERVERSTICK_PROVISION_API` (default `https://api.serverstick.com`)
- `SERVERSTICK_DEVICE_TOKEN` (provisioning token from GUI)

## CLI equivalent
```bash
bash /etc/serverstick/scripts/provision.sh <subdomain>
```
