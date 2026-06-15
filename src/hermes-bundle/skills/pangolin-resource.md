---
name: pangolin-resource
description: Add/remove a routed resource on this device's Pangolin site (e.g. add `pdf.<device>.serverstick.com` -> localhost:8440). Uses the hermes-bridge API — never the raw Pangolin key.
version: 2.0.0
triggers:
  - "/add-resource"
  - "/remove-resource"
  - "expose service"
  - "add subdomain"
---

# Pangolin Resource Manager

Add a routed resource on this device's Pangolin site via the hermes-bridge API.

## When to use
- User says "I want pdf.myname.serverstick.com"
- Dashboard adds a new service that needs exposing
- Service port changed (e.g. moved Homepage to different port)

## What it does
1. Call `POST http://localhost:{SERVERSTICK_PORT}/api/services/provision` with `{"service_id": "<id>"}`
2. Bridge finds the device's siteId from Pangolin, creates the resource, wires the target
3. Returns `{status, subdomain, resource_id}`
4. Verify: `curl https://<sub>.serverstick.com` returns 2xx/3xx (not 502)

## Service catalog IDs
`filebrowser`, `homepage`, `stirling-pdf`, `privatebin`, `pairdrop`, `uptime-kuma`, `rembg`, `dozzle`

## Pattern
`{service_subdomain}.{device}.serverstick.com` (sub-sub-domain)
e.g. `pdf.jack.serverstick.com` → `127.0.0.1:8440`

## Gotchas
- Resources default to SSO-gated ("Protected"). Making them public requires either a Pangolin dashboard toggle or direct DB write on the VPS.
- Pangolin Integration API is on port 3003 (not 3000 which is the Dashboard API with CSRF)
- API key is read from `/etc/serverstick/pangolin-api-key` at runtime (never hardcode)

## CLI equivalent
```bash
curl -X POST http://localhost:18090/api/services/provision \
  -H 'Content-Type: application/json' \
  -d '{"service_id": "stirling-pdf"}'
```
