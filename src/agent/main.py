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
NEWT_CONF_DIR = Path("/etc/newt")
BACKUP_DIR = SS_DATA / "backups"

PORT = int(os.environ.get("SERVERSTICK_PORT", "8080"))
CLOUD_URL = os.environ.get("SERVERSTICK_CLOUD_URL", "https://serverstick.vercel.app/api/v1/provision")
STARTER_KEY = os.environ.get("SERVERSTICK_STARTER_KEY", "")
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
    services: list[str]
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
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    backups = []
    for f in sorted(BACKUP_DIR.glob("*.tar.gz"), reverse=True):
        stat = f.stat()
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

    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
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


# ─── Setup & Provisioning ─────────────────────────────────────────────

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

    # ── Step 1: Cloud provisioning ──
    provisioning_data = {}
    tunnel_error = None
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                CLOUD_URL,
                json={
                    "device_id": DEVICE_ID or name,
                    "device_name": name,
                    "starter_key": starter_key,
                    "services": req.services,
                },
                timeout=30,
            )
            if resp.status_code == 200:
                provisioning_data = resp.json()
            else:
                tunnel_error = f"Cloud API returned {resp.status_code}: {resp.text[:300]}"
    except Exception as e:
        tunnel_error = str(e)

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
    SS_DIR.mkdir(parents=True, exist_ok=True)
    PROVISIONED_FILE.write_text(device_name)

    response = {
        "status": "provisioned",
        "device_name": device_name,
        "domain": f"dash.{device_name}.serverstick.com",
        "services": results,
    }

    if tunnel_error:
        response["tunnel_warning"] = f"Provisioned locally, but tunnel setup failed: {tunnel_error}"
    elif newt_id:
        response["tunnel"] = {"newt_id": newt_id, "endpoint": f"*.{device_name}.serverstick.com"}

    return response


@app.post("/api/chat")
async def chat(req: ChatRequest):
    """LLM chat endpoint — routes to appropriate model."""
    model = route_model(req.message, req.context)
    response = await call_llm(model, req.message)
    return {"model": model, "response": response}


@app.get("/api/catalog")
async def get_catalog():
    """Full service catalog with categories."""
    by_category = {}
    for name, skill in skill_registry.skills.items():
        cat = skill.catalog_entry.get("category", "other")
        by_category.setdefault(cat, []).append({
            "name": name,
            **skill.catalog_entry,
        })
    return by_category


@app.get("/api/hardware")
async def get_hardware():
    """Hardware detection — CPU, RAM, disk, GPU."""
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
    NEWT_CONF_DIR.mkdir(parents=True, exist_ok=True)
    newt_conf = {
        "newtId": newt_id,
        "secret": newt_secret,
        "endpoint": "gerbil.pangolin.net:50120",
    }
    (NEWT_CONF_DIR / "newt.json").write_text(json.dumps(newt_conf, indent=2))
    os.chmod(NEWT_CONF_DIR / "newt.json", 0o600)

    env_file = SS_DIR / "pangolin.env"
    env_file.write_text(
        f"NEWT_ID={newt_id}\n"
        f"NEWT_SECRET=***\n"
        f"NEWT_ENDPOINT=gerbil.pangolin.net:50120\n"
    )
    os.chmod(env_file, 0o600)


def _enable_newt_service():
    """Enable and start the Newt tunnel service."""
    try:
        subprocess.run(["systemctl", "enable", "serverstick-newt"], capture_output=True, timeout=10)
        subprocess.run(["systemctl", "start", "serverstick-newt"], capture_output=True, timeout=10)
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
