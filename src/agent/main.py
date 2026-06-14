#!/usr/bin/env python3
"""ServerStick Pi Agent — FastAPI backend.

Serves the Svelte dashboard, manages Docker services, handles LLM routing,
and provides the provisioning/setup API.

Runs at http://<lan-ip>:8080 (local) or https://dash.<device>.serverstick.com (remote).
"""

import asyncio
import json
import os
import shutil
import subprocess
import tarfile
from datetime import datetime
from pathlib import Path
from contextlib import asynccontextmanager

import httpx
import yaml
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

try:
    from .router import route_model, call_llm
    from .skills import SkillRegistry
except ImportError:
    from router import route_model, call_llm
    from skills import SkillRegistry

# ─── Config ──────────────────────────────────────────────────────────

SS_DIR = Path(os.environ.get("SERVERSTICK_DIR", "/etc/serverstick"))
SS_DATA = Path(os.environ.get("SERVERSTICK_DATA", "/var/lib/serverstick/data"))
CATALOG_DIR = Path(__file__).parent / "skills" / "catalog"
COMPOSE_FILE = SS_DIR / "services" / "docker-compose.yml"
DASHBOARD_DIR = Path(__file__).parent / "dashboard" / "build"
PROVISIONED_FILE = SS_DIR / "provisioned"
NEWT_CONF_DIR = Path(os.environ.get("SERVERSTICK_NEWT_CONF", "/etc/newt"))
BACKUP_DIR = SS_DATA / "backups"

# Ensure directories exist (permission-safe)
for _d in [SS_DIR, SS_DATA, BACKUP_DIR]:
    try:
        _d.mkdir(parents=True, exist_ok=True)
    except PermissionError:
        pass  # Running non-root; dirs will be created by bootstrap on target

PORT = int(os.environ.get("SERVERSTICK_PORT", "8080"))
CLOUD_URL = os.environ.get("SERVERSTICK_CLOUD_URL", "http://localhost:9090/v1/provision")
STARTER_KEY = os.environ.get("SERVERSTICK_STARTER_KEY", "")
DEVICE_TOKEN = os.environ.get("SERVERSTICK_DEVICE_TOKEN", "ss_dev_token_change_me")

# Direct Pangolin fallback (when no middleman is available)
# Hardcoded for hackathon demo — would come from secure config in production
# IMPORTANT: PANGOLIN_API_URL must point at the host where Integration API is reachable.
# Self-hosted Pangolin exposes Integration API on port 3003 internally.
# We use the VPS public IP (not pangolin.serverstick.com) because port 3003 is only
# open on the VPS IP, not via Traefik on 443.
PANGOLIN_API_URL = os.environ.get(
    "SERVERSTICK_PANGOLIN_API_URL",
    "http://89.125.209.77",  # VPS public IP — port 3003 is open directly
)
PANGOLIN_INTEGRATION_PORT = int(os.environ.get("SERVERSTICK_PANGOLIN_INT_PORT", "3003"))
PANGOLIN_API_KEY = os.environ.get("SERVERSTICK_PANGOLIN_API_KEY", "")
PANGOLIN_ORG_ID = os.environ.get("SERVERSTICK_PANGOLIN_ORG_ID", "serverstick")
PANGOLIN_DOMAIN_ID = os.environ.get("SERVERSTICK_PANGOLIN_DOMAIN_ID", "domain1")
# Newt endpoint is the public HTTPS URL (used by the Newt client, not the API)
NEWT_ENDPOINT = os.environ.get("SERVERSTICK_NEWT_ENDPOINT", "https://pangolin.serverstick.com")

# Default service catalog: subdomain -> local port
# Hardcoded for hackathon; v2 reads from recipe catalog dynamically
DEFAULT_SERVICE_PORTS = {
    "homepage": 3002,
    "stirling-pdf": 8440,
    "privatebin": 8084,
    "pairdrop": 3000,
    "uptime-kuma": 3001,
    "rembg": 7000,
    "dozzle": 8888,
    "api": 8080,
}


def _docker_available() -> bool:
    """Check if Docker daemon is accessible."""
    try:
        result = subprocess.run(
            ["docker", "info", "--format", "{{.ServerVersion}}"],
            capture_output=True, text=True, timeout=5
        )
        return result.returncode == 0
    except Exception:
        return False
DEVICE_ID = os.environ.get("SERVERSTICK_DEVICE_ID", "")

# ─── Global state ───────────────────────────────────────────────────

skill_registry = SkillRegistry(CATALOG_DIR)
device_name: str = ""
provisioned: bool = False
_ws_clients: set[WebSocket] = set()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Load catalog and check provisioning state on startup."""
    skill_registry.load_all()
    _sync_docker_status()

    global provisioned, device_name
    if PROVISIONED_FILE.exists():
        provisioned = True
        device_name = PROVISIONED_FILE.read_text().strip()

    # Start background WebSocket broadcaster
    asyncio.create_task(_ws_broadcaster())
    yield


app = FastAPI(title="ServerStick Agent", version="0.2.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # LAN-only in practice; Pangolin adds auth
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─── Models ───────────────────────────────────────────────────────────

class SetupRequest(BaseModel):
    device_name: str
    services: list[str] = []  # empty = install all recommended services
    starter_key: str | None = None

class ServiceAction(BaseModel):
    action: str  # start, stop, restart, status

class ChatRequest(BaseModel):
    message: str
    context: str = "user_chat"  # user_chat, service_mgmt, diagnostics

class RestoreRequest(BaseModel):
    backup_file: str


# ─── API Routes ───────────────────────────────────────────────────────

@app.get("/api/status")
async def get_status():
    """Overall system status — services, tunnel, device info."""
    services_status = {}
    for name, skill in skill_registry.skills.items():
        services_status[name] = skill.get_status()

    return {
        "device_name": device_name,
        "provisioned": provisioned,
        "docker_available": _docker_available(),
        "services": services_status,
        "tunnel": get_tunnel_status(),
    }


@app.get("/api/services")
async def list_services():
    """List all available services from the catalog."""
    return {
        name: skill.catalog_entry
        for name, skill in skill_registry.skills.items()
    }


@app.get("/api/services/{service_name}")
async def get_service(service_name: str):
    """Get details and status for a specific service."""
    skill = skill_registry.get(service_name)
    if not skill:
        raise HTTPException(404, f"Service '{service_name}' not found in catalog")
    return {
        **skill.catalog_entry,
        "status": skill.get_status(),
    }


@app.post("/api/services/{service_name}/update")
async def update_service(service_name: str):
    """Pull new image and recreate container for a service."""
    skill = skill_registry.get(service_name)
    if not skill:
        raise HTTPException(404, f"Service '{service_name}' not found")

    try:
        # Pull the latest image
        image = skill.catalog_entry.get("docker", {}).get("image", "")
        if image:
            pull = subprocess.run(
                ["docker", "pull", image],
                capture_output=True, text=True, timeout=300
            )
            if pull.returncode != 0:
                return {"service": service_name, "updated": False, "error": pull.stderr[:500]}

        # Recreate the container
        result = skill.stop()
        result = skill.start()
        return {"service": service_name, "updated": True, "output": result.get("output", "")}
    except subprocess.TimeoutExpired:
        raise HTTPException(500, "Image pull timed out (5 min limit)")
    except Exception as e:
        raise HTTPException(500, f"Update failed: {e}")


@app.post("/api/services/{service_name}/{action}")
async def service_action(service_name: str, action: str):
    """Start, stop, restart, install, or uninstall a Docker service."""
    skill = skill_registry.get(service_name)
    if not skill:
        raise HTTPException(404, f"Service '{service_name}' not found")

    if action not in ("start", "stop", "restart", "install", "uninstall"):
        raise HTTPException(400, f"Invalid action: {action}")

    result = getattr(skill, action)()
    return {"service": service_name, "action": action, **result}


@app.delete("/api/services/{service_name}")
async def uninstall_service(service_name: str):
    """RESTful uninstall — removes container and compose config."""
    skill = skill_registry.get(service_name)
    if not skill:
        raise HTTPException(404, f"Service '{service_name}' not found")
    result = skill.uninstall()
    return {"service": service_name, "action": "uninstall", **result}


# ─── Health Check APIs ────────────────────────────────────────────────

@app.get("/api/health")
async def health_check_all():
    """Health check all installed+running services."""
    results = {}
    for name, skill in skill_registry.skills.items():
        status = skill.get_status()
        if status.get("installed") and status.get("running"):
            results[name] = skill.health_check()
        else:
            results[name] = {"healthy": None, "message": "Not running"}
    return results


@app.get("/api/services/{service_name}/health")
async def health_check_service(service_name: str):
    """Health check a specific service."""
    skill = skill_registry.get(service_name)
    if not skill:
        raise HTTPException(404, f"Service '{service_name}' not found")
    return skill.health_check()


# ─── Resource Monitoring ──────────────────────────────────────────────

@app.get("/api/resources")
async def get_resources():
    """Real-time system resource monitoring — CPU, RAM, disk, Docker."""
    resources = {}

    # CPU usage
    try:
        # Read /proc/stat twice with a small gap for delta
        with open("/proc/stat") as f:
            line1 = f.readline()
        await asyncio.sleep(0.1)
        with open("/proc/stat") as f:
            line2 = f.readline()

        def _parse_stat(line):
            parts = line.split()[1:]  # skip "cpu"
            vals = [int(p) for p in parts[:8]]
            idle = vals[3] + vals[4]  # idle + iowait
            total = sum(vals)
            return idle, total

        idle1, total1 = _parse_stat(line1)
        idle2, total2 = _parse_stat(line2)
        diff_idle = idle2 - idle1
        diff_total = total2 - total1
        cpu_pct = round((1 - diff_idle / diff_total) * 100, 1) if diff_total > 0 else 0
        resources["cpu"] = {"usage_percent": cpu_pct}
    except Exception:
        resources["cpu"] = {"usage_percent": None}

    # CPU info
    try:
        cpu_info = subprocess.check_output(["lscpu"], text=True, timeout=5)
        for line in cpu_info.splitlines():
            if "Model name" in line:
                resources["cpu"]["model"] = line.split(":", 1)[1].strip()
            if "CPU(s):" in line and "per" not in line:
                resources["cpu"]["cores"] = int(line.split(":")[1].strip())
    except Exception:
        pass

    # RAM usage
    try:
        mem = subprocess.check_output(["free", "-m"], text=True, timeout=5)
        for line in mem.splitlines():
            if line.startswith("Mem:"):
                parts = line.split()
                resources["ram"] = {
                    "total_mb": int(parts[1]),
                    "used_mb": int(parts[2]),
                    "available_mb": int(parts[6]),
                    "usage_percent": round(int(parts[2]) / int(parts[1]) * 100, 1),
                }
    except Exception:
        resources["ram"] = None

    # Disk usage
    resources["disks"] = {}
    try:
        df = subprocess.check_output(["df", "-h"], text=True, timeout=5)
        for line in df.splitlines():
            parts = line.split()
            if len(parts) >= 6 and parts[5] == "/":
                resources["disks"]["root"] = {
                    "total": parts[1], "used": parts[2], "available": parts[3],
                    "usage_percent": parts[4].rstrip("%"),
                }
            elif len(parts) >= 6 and SS_DATA.as_posix() in parts[5]:
                resources["disks"]["data"] = {
                    "total": parts[1], "used": parts[2], "available": parts[3],
                    "usage_percent": parts[4].rstrip("%"),
                }
    except Exception:
        pass

    # Docker disk usage
    try:
        docker_df = subprocess.check_output(
            ["docker", "system", "df", "--format", "json"],
            text=True, timeout=10
        )
        docker_usage = []
        for line in docker_df.strip().splitlines():
            try:
                docker_usage.append(json.loads(line))
            except json.JSONDecodeError:
                pass
        resources["docker"] = docker_usage if docker_usage else None
    except Exception:
        resources["docker"] = None

    # Container stats
    try:
        stats = subprocess.check_output(
            ["docker", "stats", "--no-stream", "--format", "json"],
            text=True, timeout=15
        )
        container_stats = []
        for line in stats.strip().splitlines():
            try:
                container_stats.append(json.loads(line))
            except json.JSONDecodeError:
                pass
        resources["containers"] = container_stats if container_stats else []
    except Exception:
        resources["containers"] = []

    return resources


# ─── Service Logs ─────────────────────────────────────────────────────

@app.get("/api/services/{service_name}/logs")
async def get_service_logs(service_name: str, lines: int = 100, stream: bool = False):
    """Get Docker container logs for a service."""
    skill = skill_registry.get(service_name)
    if not skill:
        raise HTTPException(404, f"Service '{service_name}' not found")

    if stream:
        return StreamingResponse(
            _stream_logs(service_name),
            media_type="text/plain",
        )

    try:
        result = subprocess.run(
            ["docker", "compose", "-f", str(COMPOSE_FILE), "logs", "--tail", str(lines), service_name],
            capture_output=True, text=True, timeout=15
        )
        return {"service": service_name, "logs": result.stdout + result.stderr}
    except subprocess.TimeoutExpired:
        raise HTTPException(500, "Log retrieval timed out")
    except Exception as e:
        raise HTTPException(500, f"Failed to get logs: {e}")


async def _stream_logs(service_name: str):
    """Async generator that streams docker logs via SSE."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "docker", "compose", "-f", str(COMPOSE_FILE), "logs", "-f", "--tail", "50", service_name,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        while True:
            line = await proc.stdout.readline()
            if not line:
                break
            yield f"data: {line.decode(errors='replace').rstrip()}\n\n"
    except Exception as e:
        yield f"data: ERROR: {e}\n\n"


# ─── Backup / Restore ────────────────────────────────────────────────

@app.get("/api/backups")
async def list_backups():
    """List all backup files."""
    backups = []
    if BACKUP_DIR.exists():
        for f in sorted(BACKUP_DIR.glob("*.tar.gz"), reverse=True):
            try:
                stat = f.stat()
            except OSError:
                continue
            # Parse service name from filename: {service}_{timestamp}.tar.gz
            parts = f.stem.replace(".tar", "").rsplit("_", 1)
            service = parts[0] if len(parts) == 2 else "unknown"
            backups.append({
                "filename": f.name,
                "service": service,
                "size_bytes": stat.st_size,
                "size_mb": round(stat.st_size / (1024 * 1024), 1),
                "created": datetime.fromtimestamp(stat.st_mtime).isoformat(),
            })
    return {"backups": backups}


@app.post("/api/backup/{service_name}")
async def create_backup(service_name: str):
    """Create a tar.gz backup of a service's data volume."""
    skill = skill_registry.get(service_name)
    if not skill:
        raise HTTPException(404, f"Service '{service_name}' not found")

    data_dir = SS_DATA / service_name
    if not data_dir.exists():
        raise HTTPException(404, f"No data directory for '{service_name}' at {data_dir}")

    try:
        BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    except PermissionError:
        raise HTTPException(500, f"Cannot create backup directory: {BACKUP_DIR}")

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_file = BACKUP_DIR / f"{service_name}_{timestamp}.tar.gz"

    try:
        with tarfile.open(backup_file, "w:gz") as tar:
            tar.add(str(data_dir), arcname=service_name)
        stat = backup_file.stat()
        return {
            "service": service_name,
            "backup_file": backup_file.name,
            "size_mb": round(stat.st_size / (1024 * 1024), 1),
            "created": datetime.now().isoformat(),
        }
    except Exception as e:
        # Clean up partial backup
        if backup_file.exists():
            backup_file.unlink()
        raise HTTPException(500, f"Backup failed: {e}")


@app.post("/api/restore/{service_name}")
async def restore_backup(service_name: str, req: RestoreRequest):
    """Restore a service from a backup file."""
    skill = skill_registry.get(service_name)
    if not skill:
        raise HTTPException(404, f"Service '{service_name}' not found")

    backup_file = BACKUP_DIR / req.backup_file
    if not backup_file.exists():
        raise HTTPException(404, f"Backup file not found: {req.backup_file}")

    data_dir = SS_DATA / service_name

    try:
        # Stop the service first
        skill.stop()

        # Remove existing data
        if data_dir.exists():
            shutil.rmtree(data_dir)

        # Extract backup
        with tarfile.open(backup_file, "r:gz") as tar:
            tar.extractall(path=str(SS_DATA))

        # Start the service again
        skill.start()

        return {
            "service": service_name,
            "restored_from": req.backup_file,
            "status": "restored_and_started",
        }
    except Exception as e:
        raise HTTPException(500, f"Restore failed: {e}")


@app.delete("/api/backup/{backup_file}")
async def delete_backup(backup_file: str):
    """Delete a specific backup file."""
    path = BACKUP_DIR / backup_file
    if not path.exists():
        raise HTTPException(404, f"Backup not found: {backup_file}")
    # Safety: ensure it's actually in the backup dir and is a tar.gz
    if not path.name.endswith(".tar.gz"):
        raise HTTPException(400, "Can only delete .tar.gz backup files")
    try:
        path.unlink()
        return {"deleted": backup_file}
    except Exception as e:
        raise HTTPException(500, f"Delete failed: {e}")



@app.post("/api/update-all")
async def update_all_services():
    """Update all running services — pull new images and recreate."""
    results = {}
    for name, skill in skill_registry.skills.items():
        status = skill.get_status()
        if status.get("running"):
            try:
                image = skill.catalog_entry.get("docker", {}).get("image", "")
                if image:
                    pull = subprocess.run(
                        ["docker", "pull", image],
                        capture_output=True, text=True, timeout=300
                    )
                    if pull.returncode != 0:
                        results[name] = {"updated": False, "error": pull.stderr[:200]}
                        continue
                skill.stop()
                skill.start()
                results[name] = {"updated": True}
            except Exception as e:
                results[name] = {"updated": False, "error": str(e)[:200]}
        else:
            results[name] = {"updated": False, "skipped": True, "reason": "not running"}
    return results


# ─── Network Info ─────────────────────────────────────────────────────

@app.get("/api/network")
async def get_network():
    """Network information — IPs, WiFi, hostname, DNS."""
    network = {}

    # Hostname
    try:
        network["hostname"] = subprocess.check_output(
            ["hostname"], text=True, timeout=5
        ).strip()
    except Exception:
        network["hostname"] = None

    # IP addresses
    try:
        ip_out = subprocess.check_output(
            ["hostname", "-I"], text=True, timeout=5
        ).strip()
        network["ips"] = [ip for ip in ip_out.split() if not ip.startswith("172.")]
    except Exception:
        network["ips"] = []

    # WiFi SSID
    try:
        ssid = subprocess.check_output(
            ["iwgetid", "-r"], text=True, timeout=5
        ).strip()
        network["wifi_ssid"] = ssid or None
    except Exception:
        # Try nmcli as fallback
        try:
            nmcli = subprocess.check_output(
                ["nmcli", "-t", "-f", "active,ssid", "dev", "wifi"],
                text=True, timeout=5
            )
            for line in nmcli.splitlines():
                if line.startswith("yes:"):
                    network["wifi_ssid"] = line.split(":", 1)[1]
                    break
            else:
                network["wifi_ssid"] = None
        except Exception:
            network["wifi_ssid"] = None

    # DNS servers
    try:
        resolv = Path("/etc/resolv.conf").read_text()
        dns = []
        for line in resolv.splitlines():
            line = line.strip()
            if line.startswith("nameserver"):
                dns.append(line.split()[1])
        network["dns"] = dns
    except Exception:
        network["dns"] = []

    return network


# ─── Direct Pangolin Provisioning (fallback when no middleman) ──────

async def _pangolin_create_site(client: httpx.AsyncClient, subdomain: str) -> dict:
    """Create a Pangolin site (Newt tunnel endpoint) via Integration API.

    Returns {siteId, niceId, newtId, newtSecret} or raises on failure.
    """
    # 1. Create the site
    resp = await client.put(
        f"{PANGOLIN_API_URL}:{PANGOLIN_INTEGRATION_PORT}/v1/org/{PANGOLIN_ORG_ID}/site",
        json={
            "name": subdomain,
            "type": "newt",
        },
        headers={"Authorization": f"Bearer {PANGOLIN_API_KEY}"},
        timeout=15,
    )
    if resp.status_code not in (200, 201):
        raise RuntimeError(f"Create site failed: {resp.status_code} {resp.text[:200]}")
    site_data = resp.json().get("data", {})

    # Response shape varies — try common fields
    site_id = site_data.get("siteId") or site_data.get("site", {}).get("siteId")
    newt_id = site_data.get("newtId") or site_data.get("site", {}).get("newtId")
    newt_secret = site_data.get("secret") or site_data.get("site", {}).get("secret")

    if not all([site_id, newt_id, newt_secret]):
        # Some Pangolin versions return this in a different shape
        raise RuntimeError(f"Site created but missing creds: {json.dumps(site_data)[:300]}")

    return {
        "siteId": site_id,
        "newtId": newt_id,
        "newtSecret": newt_secret,
    }


async def _pangolin_create_resource(
    client: httpx.AsyncClient, name: str, subdomain: str, site_id: int, port: int
) -> dict:
    """Create a Pangolin resource + target for a single service."""
    # 1. Create resource
    resp = await client.put(
        f"{PANGOLIN_API_URL}:{PANGOLIN_INTEGRATION_PORT}/v1/org/{PANGOLIN_ORG_ID}/resource",
        json={
            "name": name,
            "subdomain": subdomain,
            "domainId": PANGOLIN_DOMAIN_ID,
            "mode": "http",
        },
        headers={"Authorization": f"Bearer {PANGOLIN_API_KEY}"},
        timeout=15,
    )
    if resp.status_code not in (200, 201):
        raise RuntimeError(f"Create resource {name} failed: {resp.status_code} {resp.text[:200]}")
    resource_id = resp.json().get("data", {}).get("resourceId")
    if not resource_id:
        raise RuntimeError(f"No resourceId returned: {resp.text[:200]}")

    # 2. Create target pointing at this site + local port
    target_resp = await client.put(
        f"{PANGOLIN_API_URL}:{PANGOLIN_INTEGRATION_PORT}/v1/resource/{resource_id}/target",
        json={
            "siteId": site_id,
            "ip": "127.0.0.1",
            "port": port,
            "mode": "http",
        },
        headers={"Authorization": f"Bearer {PANGOLIN_API_KEY}"},
        timeout=15,
    )
    if target_resp.status_code not in (200, 201):
        raise RuntimeError(f"Create target {name} failed: {target_resp.status_code} {target_resp.text[:200]}")

    return {"resourceId": resource_id, "subdomain": subdomain}


async def _pangolin_make_public_via_db(orphaned_resources: list[int]) -> None:
    """Direct DB write to set sso=0 on resources. Requires SSH access to Pangolin host.

    Skipped silently if SSH not configured. Resources default to Protected otherwise.
    """
    if not orphaned_resources:
        return
    # We don't have direct DB access from Pi Agent. Log and rely on the user
    # to either configure a provisioning key that returns 'public' resources
    # or run the DB write command from the Pangolin host.
    log_msg = f"Resources {orphaned_resources} created but default to Protected (sso=1). "
    log_msg += "For hackathon demo, they should be made public via direct DB write on Pangolin host: "
    log_msg += f"sqlite3 /opt/pangolin/config/db/db.sqlite \"UPDATE resources SET sso=0 WHERE resourceId IN ({','.join(map(str, orphaned_resources))});\""
    print(f"[setup] {log_msg}")


async def _provision_via_pangolin_direct(subdomain: str, services: list[str]) -> dict:
    """Bypass the middleman, talk to Pangolin Integration API directly.

    This is the demo path — Pangolin org API key is hardcoded in env.
    Production should use a middleman with per-device provisioning keys.
    """
    if not PANGOLIN_API_KEY:
        raise RuntimeError(
            "PANGOLIN_API_KEY not set. Set SERVERSTICK_PANGOLIN_API_KEY env var, "
            "or implement a middleman and point CLOUD_URL at it."
        )

    async with httpx.AsyncClient() as client:
        # 1. Create site (Newt tunnel endpoint for this device)
        site = await _pangolin_create_site(client, subdomain)
        site_id = site["siteId"]

        # 2. Create resources for each selected service
        created = []
        for svc in services:
            port = DEFAULT_SERVICE_PORTS.get(svc)
            if not port:
                print(f"[setup] Unknown service {svc}, skipping")
                continue
            try:
                res = await _pangolin_create_resource(
                    client, name=svc, subdomain=svc, site_id=site_id, port=port
                )
                created.append(res)
            except Exception as e:
                print(f"[setup] Failed to create resource for {svc}: {e}")

        # 3. Hint about public-resource policy (sso=0 toggle)
        await _pangolin_make_public_via_db([r["resourceId"] for r in created])

    return {
        "newt_id": site["newtId"],
        "newt_secret": site["newtSecret"],
        "site_id": site_id,
        "resources": created,
        "tunnel_endpoint": NEWT_ENDPOINT,
        "method": "pangolin_direct",
    }


@app.post("/api/setup")
async def setup_device(req: SetupRequest):
    """First-boot provisioning wizard.

    1. Validate device name (Pangolin subdomain-safe)
    2. Call cloud API to create Pangolin site + blueprint
    3. Write Newt config with returned credentials
    4. Start selected Docker services
    5. Mark as provisioned

    Idempotent — if already provisioned, returns current state.
    """
    global device_name, provisioned

    # Idempotency guard
    if provisioned and device_name:
        existing_status = await get_status()
        return {
            "status": "already_provisioned",
            "device_name": device_name,
            "domain": f"dash.{device_name}.serverstick.com",
            **existing_status,
        }

    # Validate device name for subdomain use
    name = req.device_name.lower().strip()
    if not name.replace("-", "").replace(".", "").isalnum():
        raise HTTPException(400, "Device name must be alphanumeric (hyphens OK)")
    if len(name) > 20:
        raise HTTPException(400, "Device name too long (max 20 chars)")

    # Use starter key from request, env var, or file
    starter_key = req.starter_key or STARTER_KEY
    if not starter_key:
        key_file = Path("/etc/serverstick/starter-key")
        if key_file.exists():
            starter_key = key_file.read_text().strip()

    # ── Step 1: Cloud provisioning (try middleman first, fall back to direct) ──
    provisioning_data = {}
    tunnel_error = None
    used_method = None

    if CLOUD_URL and CLOUD_URL != "http://localhost:9090/v1/provision":
        # Real middleman configured — try it
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    CLOUD_URL,
                    json={
                        "device_name": name,
                        "starter_key": starter_key,
                        "services": req.services or [],
                    },
                    headers={"Authorization": f"Bearer {DEVICE_TOKEN}"},
                    timeout=30,
                )
                if resp.status_code == 200:
                    provisioning_data = resp.json()
                    used_method = "middleman"
                else:
                    tunnel_error = f"Cloud API returned {resp.status_code}: {resp.text[:300]}"
        except Exception as e:
            tunnel_error = f"Middleman unreachable: {e}"

    # Fallback: direct Pangolin API (hackathon demo path)
    if not provisioning_data and PANGOLIN_API_KEY:
        try:
            provisioning_data = await _provision_via_pangolin_direct(
                name, req.services or list(DEFAULT_SERVICE_PORTS.keys())
            )
            used_method = "pangolin_direct"
            tunnel_error = None  # reset — direct path succeeded
        except Exception as e:
            tunnel_error = f"Direct Pangolin provision failed: {e}"

    if not provisioning_data and not tunnel_error:
        tunnel_error = "No provision path succeeded. Set CLOUD_URL or PANGOLIN_API_KEY."

    # ── Step 2: Write Newt tunnel config if we got credentials ──
    newt_id = provisioning_data.get("newt_id")
    newt_secret = provisioning_data.get("newt_secret")
    if newt_id and newt_secret:
        _write_newt_config(newt_id, newt_secret)
        _enable_newt_service()

    # ── Step 3: Enable selected Docker services ──
    results = {}
    for svc in req.services:
        skill = skill_registry.get(svc)
        if skill:
            results[svc] = skill.install()
    _start_docker_services()

    # ── Step 4: Mark as provisioned ──
    device_name = name
    provisioned = True
    try:
        SS_DIR.mkdir(parents=True, exist_ok=True)
        PROVISIONED_FILE.write_text(device_name)
    except PermissionError:
        pass  # Will be persisted properly on target device (runs as root)

    response = {
        "status": "provisioned",
        "device_name": device_name,
        "domain": f"dash.{device_name}.serverstick.com",
        "services": results,
        "method": used_method,
    }

    if tunnel_error:
        response["tunnel_warning"] = f"Provisioned locally, but tunnel setup failed: {tunnel_error}"
    elif newt_id:
        resources = provisioning_data.get("resources", [])
        response["tunnel"] = {
            "newt_id": newt_id,
            "endpoint": f"*.{device_name}.serverstick.com",
            "tunnel_endpoint": provisioning_data.get("tunnel_endpoint", NEWT_ENDPOINT),
            "subdomains": [r.get("subdomain") for r in resources] if resources else None,
        }

    return response


@app.post("/api/chat")
async def chat(req: ChatRequest):
    """LLM chat endpoint — routes to appropriate model."""
    model = route_model(req.message, req.context)
    response = await call_llm(model, req.message)
    return {"model": model, "response": response}


@app.get("/api/catalog")
async def get_catalog():
    """Full service catalog with categories and CPU compatibility."""
    # Get current CPU level for compatibility checks
    host_level = "x86_v1"
    level_rank = {"x86_v1": 0, "x86_v2": 1, "x86_v3": 2}
    try:
        flags_raw = subprocess.check_output(
            ["grep", "-m1", "flags", "/proc/cpuinfo"], text=True, timeout=5
        )
        flags = set(flags_raw.split())
        if "avx2" in flags and "fma" in flags:
            host_level = "x86_v3"
        elif "sse4_2" in flags and "popcnt" in flags:
            host_level = "x86_v2"
    except Exception:
        pass

    by_category = {}
    for name, skill in skill_registry.skills.items():
        cat = skill.catalog_entry.get("category", "other")
        entry = {
            "name": name,
            **skill.catalog_entry,
        }
        # CPU compatibility check
        svc_level = skill.catalog_entry.get("docker", {}).get("cpu_level", "x86_v1")
        entry["cpu_compatible"] = level_rank.get(host_level, 0) >= level_rank.get(svc_level, 0)
        entry["cpu_level_required"] = svc_level
        entry["cpu_level_host"] = host_level
        by_category.setdefault(cat, []).append(entry)
    return by_category


@app.get("/api/hardware")
async def get_hardware():
    """Hardware detection — CPU, RAM, disk, GPU, CPU feature level."""
    hardware = {}
    try:
        cpu = subprocess.check_output(
            ["lscpu"], text=True, timeout=5
        )
        for line in cpu.splitlines():
            if "Model name" in line:
                hardware["cpu"] = line.split(":", 1)[1].strip()
            if "CPU(s):" in line and "per" not in line:
                hardware["cpu_cores"] = int(line.split(":")[1].strip())
    except Exception:
        pass

    # CPU feature level detection — determines which service images can run
    # x86_v1: baseline (any 64-bit CPU, 2003+)
    # x86_v2: SSE4.2 + POPCNT (Intel Nehalem 2008+, AMD Bulldozer 2011+)
    # x86_v3: AVX2 + FMA (Intel Haswell 2013+, AMD Zen 2017+)
    try:
        flags_raw = subprocess.check_output(
            ["grep", "-m1", "flags", "/proc/cpuinfo"], text=True, timeout=5
        )
        flags = set(flags_raw.split())
        hardware["cpu_flags"] = {
            "sse4_2": "sse4_2" in flags,
            "avx2": "avx2" in flags,
            "popcnt": "popcnt" in flags,
            "fma": "fma" in flags,
        }
        # Determine x86 microarch level
        if "avx2" in flags and "fma" in flags:
            hardware["cpu_level"] = "x86_v3"
        elif "sse4_2" in flags and "popcnt" in flags:
            hardware["cpu_level"] = "x86_v2"
        else:
            hardware["cpu_level"] = "x86_v1"
    except Exception:
        hardware["cpu_level"] = "unknown"
        hardware["cpu_flags"] = {}

    try:
        mem = subprocess.check_output(["free", "-g"], text=True, timeout=5)
        for line in mem.splitlines():
            if line.startswith("Mem:"):
                parts = line.split()
                hardware["ram_gb"] = int(parts[1])
    except Exception:
        pass

    try:
        disk = subprocess.check_output(
            ["lsblk", "-d", "-o", "NAME,SIZE,ROTA,TYPE"],
            text=True, timeout=5
        )
        hardware["disks"] = disk.strip()
    except Exception:
        pass

    try:
        gpu = subprocess.check_output(
            ["lspci"], text=True, timeout=5
        )
        gpus = [l for l in gpu.splitlines() if "VGA" in l or "3D" in l]
        hardware["gpu"] = gpus[0] if gpus else None
    except Exception:
        hardware["gpu"] = None

    return hardware


@app.get("/api/tunnel")
async def get_tunnel():
    """Pangolin/Newt tunnel status."""
    return get_tunnel_status()


@app.post("/api/tunnel/connect")
async def tunnel_connect():
    """Manually trigger Newt tunnel connection."""
    try:
        result = subprocess.run(
            ["systemctl", "restart", "serverstick-newt"],
            capture_output=True, text=True, timeout=10
        )
        return {"restarted": result.returncode == 0, "output": result.stdout + result.stderr}
    except Exception as e:
        raise HTTPException(500, f"Failed to restart tunnel: {e}")


# ─── WebSocket ────────────────────────────────────────────────────────

@app.websocket("/ws/status")
async def ws_status(websocket: WebSocket):
    """WebSocket endpoint for real-time status updates.

    Client can send "refresh" to trigger an immediate update.
    Server sends status every 5 seconds automatically.
    """
    await websocket.accept()
    _ws_clients.add(websocket)
    try:
        while True:
            data = await websocket.receive_text()
            if data == "refresh":
                status = await _build_ws_status()
                await websocket.send_json(status)
    except WebSocketDisconnect:
        pass
    finally:
        _ws_clients.discard(websocket)


async def _build_ws_status() -> dict:
    """Build the status payload for WebSocket broadcast."""
    services_status = {}
    for name, skill in skill_registry.skills.items():
        services_status[name] = skill.get_status()

    # Lightweight resource snapshot
    ram = {}
    try:
        mem = subprocess.check_output(["free", "-m"], text=True, timeout=5)
        for line in mem.splitlines():
            if line.startswith("Mem:"):
                parts = line.split()
                ram = {"used_mb": int(parts[2]), "total_mb": int(parts[1])}
    except Exception:
        pass

    return {
        "services": services_status,
        "tunnel": get_tunnel_status(),
        "ram": ram,
        "timestamp": datetime.now().isoformat(),
    }


async def _ws_broadcaster():
    """Background task: push status to all connected WebSocket clients every 5s."""
    while True:
        await asyncio.sleep(5)
        if not _ws_clients:
            continue
        try:
            status = await _build_ws_status()
            dead = set()
            for ws in _ws_clients:
                try:
                    await ws.send_json(status)
                except Exception:
                    dead.add(ws)
            _ws_clients.difference_update(dead)
        except Exception:
            pass


# ─── Static Dashboard ─────────────────────────────────────────────────

if DASHBOARD_DIR.exists() and (DASHBOARD_DIR / "_app").exists():
    app.mount("/_app", StaticFiles(directory=DASHBOARD_DIR / "_app"), name="static")

    @app.get("/{full_path:path}")
    async def serve_dashboard(full_path: str):
        """Serve Svelte SPA — all routes fall back to index.html."""
        file = DASHBOARD_DIR / full_path
        if full_path and file.exists() and file.is_file():
            return FileResponse(file)
        return FileResponse(DASHBOARD_DIR / "index.html")
else:
    @app.get("/")
    async def dashboard_placeholder():
        return {"message": "Dashboard not built yet. Run: cd src/agent/dashboard && npm run build"}


# ─── Helpers ──────────────────────────────────────────────────────────

def get_tunnel_status() -> dict:
    """Check Newt tunnel status via systemctl."""
    try:
        result = subprocess.run(
            ["systemctl", "is-active", "serverstick-newt"],
            capture_output=True, text=True, timeout=5
        )
        active = result.stdout.strip() == "active"
    except Exception:
        active = False

    configured = (SS_DIR / "pangolin.env").exists()

    return {
        "active": active,
        "configured": configured,
        "device_name": device_name,
        "domain": f"{device_name}.serverstick.com" if device_name else None,
    }


def _write_newt_config(newt_id: str, newt_secret: str):
    """Write Newt tunnel configuration."""
    try:
        NEWT_CONF_DIR.mkdir(parents=True, exist_ok=True)
    except PermissionError:
        return  # Will be configured on target device (runs as root)

    newt_conf = {
        "id": newt_id,
        "secret": newt_secret,
        "endpoint": NEWT_ENDPOINT,
    }
    (NEWT_CONF_DIR / "newt.json").write_text(json.dumps(newt_conf, indent=2))
    try:
        os.chmod(NEWT_CONF_DIR / "newt.json", 0o600)
    except OSError:
        pass

    env_file = SS_DIR / "pangolin.env"
    try:
        env_file.write_text(
            f"NEWT_ID={newt_id}\n"
            f"NEWT_SECRET={newt_secret}\n"
            f"NEWT_ENDPOINT={NEWT_ENDPOINT}\n"
        )
        os.chmod(env_file, 0o600)
    except (PermissionError, OSError):
        pass


def _enable_newt_service():
    """Write systemd unit file (if missing), then enable and start the Newt tunnel service."""
    unit_path = Path("/etc/systemd/system/serverstick-newt.service")
    if not unit_path.exists():
        unit_content = (
            "[Unit]\n"
            "Description=ServerStick Pangolin Tunnel (Newt)\n"
            "After=network-online.target\n"
            "Wants=network-online.target\n\n"
            "[Service]\n"
            "ExecStart=/usr/local/bin/newt --config-file /etc/newt/newt.json\n"
            "Restart=always\n"
            "RestartSec=5\n\n"
            "[Install]\n"
            "WantedBy=multi-user.target\n"
        )
        try:
            unit_path.write_text(unit_content)
            subprocess.run(["systemctl", "daemon-reload"], capture_output=True, timeout=10)
        except (PermissionError, OSError):
            pass  # Not running as root
    try:
        subprocess.run(["systemctl", "enable", "serverstick-newt"], capture_output=True, timeout=10)
        subprocess.run(["systemctl", "restart", "serverstick-newt"], capture_output=True, timeout=10)
    except Exception:
        pass


def _sync_docker_status():
    """On startup, check which Docker services are actually running and update registry."""
    try:
        result = subprocess.run(
            ["docker", "compose", "-f", str(COMPOSE_FILE), "ps", "--format", "json"],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0 and result.stdout.strip():
            for line in result.stdout.strip().splitlines():
                try:
                    container = json.loads(line)
                    name = container.get("Name", container.get("Service", ""))
                    if name in skill_registry.skills:
                        skill_registry.skills[name].catalog_entry["_running"] = container.get("State") == "running"
                except json.JSONDecodeError:
                    pass
    except Exception:
        pass


def _start_docker_services():
    """Start all services via docker compose up."""
    try:
        subprocess.run(
            ["docker", "compose", "-f", str(COMPOSE_FILE), "up", "-d"],
            capture_output=True, text=True, timeout=120
        )
    except Exception:
        pass


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=PORT)
