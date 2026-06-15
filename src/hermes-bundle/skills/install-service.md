---
name: install-service
description: Install, start, and expose a self-hosted service from the ServerStick catalog. Handles Docker start + Pangolin resource creation + verification.
version: 2.0.0
triggers:
  - "/install"
  - "install <service>"
  - "add <service>"
---

# Service Installer

Install a service from the built-in catalog and expose it via Pangolin.

## When to use
- User says "add Stirling-PDF" or "install privatebin"
- Dashboard "Add Service" button clicked
- Hermes decides a service should be installed

## What it does
1. Check service exists in catalog: `GET http://localhost:{SERVERSTICK_PORT}/api/services`
2. Start the container: `docker compose -f /etc/serverstick/services/docker-compose.yml up -d <service>`
3. Wait for health check: `curl -sf http://localhost:<port>` returns 2xx
4. Expose via Pangolin: `POST http://localhost:{SERVERSTICK_PORT}/api/services/provision` with `{"service_id": "<id>"}`
5. Verify: `curl https://<sub>.<device>.serverstick.com`

## Built-in catalog (9 services)
| ID | Name | Port | Subdomain |
|---|---|---|---|
| filebrowser | Files | 8080 | files |
| homepage | Homepage | 3002 | home |
| stirling-pdf | Stirling PDF | 8440 | pdf |
| privatebin | PrivateBin | 8084 | bin |
| pairdrop | PairDrop | 3000 | drop |
| uptime-kuma | Uptime Kuma | 3001 | kuma |
| rembg | rembg | 7000 | rembg |
| dozzle | Dozzle | 8888 | logs |
| hermes | Hermes AI | 18789 | hermes |

## Privacy framing
Every service in the catalog replaces a surveillance service. Mention this to the user during install.

## CLI equivalent
```bash
# Start the container
docker compose -f /etc/serverstick/services/docker-compose.yml up -d stirling-pdf

# Expose via Pangolin
curl -X POST http://localhost:18090/api/services/provision \
  -H 'Content-Type: application/json' \
  -d '{"service_id": "stirling-pdf"}'
```
