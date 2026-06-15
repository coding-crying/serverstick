---
name: pangolin-resource
description: Add/remove a routed resource on this device's Pangolin site (e.g. add `pdf.<device>.serverstick.com` -> localhost:8440). Only acts on this device's site — cannot touch other devices.
version: 1.0.0
triggers:
  - "/add-resource"
  - "/remove-resource"
  - "expose service"
  - "add subdomain"
---

# Pangolin Resource Manager

Add or remove a routed resource on this device's Pangolin site.

## When to use
- User says "I want pdf.myname.serverstick.com"
- Onboarding wizard adds a new service
- Service port changed (e.g. moved Homepage to different port)

## What it does
1. Read site ID from `/etc/serverstick/pangolin.json` (created during provision)
2. Call `PUT /v1/org/{orgId}/resource` (Integration API) with `{name, subdomain, domainId, mode: "http"}`
3. Call `PUT /v1/resource/{id}/target` with `{siteId, ip: "127.0.0.1", port}`
4. Set `sso=0` in `resourcePolicies` (make public) — done via direct DB write OR `PATCH` if API supports it
5. Verify `curl https://<sub>.serverstick.com` returns 2xx/3xx (not 502)

## Important
- This device's site is in the Pangolin org. All resources for THIS device live under one site.
- Pattern: `{service}.{device}.serverstick.com` (sub-sub-domain)
- Resources default to "Protected" (auth wall) — must flip to public

## Gotchas
- `sso=0` toggle requires Pangolin restart OR direct DB write
- Integration API is on port 3003, not 3000 (3000 is Dashboard API with CSRF)
- API key is **org-scoped** — read from `/etc/serverstick/pangolin.json`
