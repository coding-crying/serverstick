---
name: install-service
description: Install, start, and expose a self-hosted service from the ServerStick recipe catalog. Handles the full stack: write config, start Docker, add Pangolin resource, verify.
version: 1.0.0
triggers:
  - "/install"
  - "install <service>"
  - "add <service>"
---

# Service Installer

Install any service from the ServerStick recipe catalog and expose it via Pangolin.

## When to use
- Onboarding wizard step 2 — user picks services to enable
- User says "add Stirling-PDF" or "install privatebin"
- Dashboard says "Install" next to a catalog item

## What it does
1. Read recipe from `/etc/serverstick/recipes/<name>.yaml`
2. Verify hardware meets `min_ram`, `cpu_level` (x86_v1/v2/v3)
3. Add service to `/etc/serverstick/services/docker-compose.yml` overlay
4. `docker compose up -d` (with appropriate volumes from recipe)
5. Wait for health check (recipe's `healthcheck.url` or `healthcheck.command`)
6. Call `pangolin-resource` skill to expose at `{service}.{device}.serverstick.com`
7. Register in `/etc/serverstick/registry.json` for dashboard display

## Recipe format (summary)
```yaml
name: stirling-pdf
replaces: ilovepdf
cpu_level: x86_v2
min_ram: 1GB
ports: [8440]
image: frooodle/s-pdf
volumes:
  - /var/lib/serverstick/data/stirling-pdf:/configs
healthcheck:
  url: http://localhost:8440
  expect: 200
tags: [privacy, documents, pdf]
```

## Privacy framing
Every service in the catalog replaces a surveillance service. Mention this to the user during install.
