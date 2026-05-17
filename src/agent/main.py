#!/usr/bin/env python3
"""ServerStick Pi Agent — FastAPI backend.

Serves the Svelte dashboard, manages Docker services, handles LLM routing,
and provides the provisioning/setup API.

Runs at http://<lan-ip>:8080 (local) or https://dash.<device>.serverstick.com (remote).
Replaces the old discover.py — single process, single port.
"""

import json
import os
import subprocess
from pathlib import Path
from contextlib import asynccontextmanager

import httpx
import yaml
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
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

PORT = int(os.environ.get("SERVERSTICK_PORT", "8080"))
CLOUD_URL = os.environ.get("SERVERSTICK_CLOUD_URL", "https://serverstick.vercel.app/api/v1/provision")
STARTER_KEY = os.environ.get("SERVERSTICK_STARTER_KEY", "")
DEVICE_ID = os.environ.get("SERVERSTICK_DEVICE_ID", "")

# ─── Global state ───────────────────────────────────────────────────

skill_registry = SkillRegistry(CATALOG_DIR)
device_name: str = ""
provisioned: bool = False


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Load catalog and check provisioning state on startup."""
    skill_registry.load_all()

    # Auto-detect running Docker services on startup
    _sync_docker_status()

    # Check if already provisioned
    global provisioned, device_name
    if PROVISIONED_FILE.exists():
        provisioned = True
        device_name = PROVISIONED_FILE.read_text().strip()
    yield


app = FastAPI(title="ServerStick Agent", version="0.1.0", lifespan=lifespan)

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
        # Try reading from USB mount
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
    # First, update the compose file to only include selected services
    results = {}
    for svc in req.services:
        skill = skill_registry.get(svc)
        if skill:
            results[svc] = skill.install()

    # Also pull up services that are in the shared compose but not individually managed
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

    # Also check if Newt config exists
    newt_conf = NEWT_CONF_DIR / "newt.json"
    configured = newt_conf.exists()

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

    # Also write the env file for systemd
    env_file = SS_DIR / "pangolin.env"
    env_file.write_text(
        f"NEWT_ID={newt_id}\n"
        f"NEWT_SECRET={newt_secret}\n"
        f"NEWT_ENDPOINT=gerbil.pangolin.net:50120\n"
    )


def _enable_newt_service():
    """Enable and start the Newt tunnel service."""
    try:
        subprocess.run(["systemctl", "enable", "serverstick-newt"], capture_output=True, timeout=10)
        subprocess.run(["systemctl", "start", "serverstick-newt"], capture_output=True, timeout=10)
    except Exception:
        pass  # Not fatal — can be started manually


def _sync_docker_status():
    """On startup, check which Docker services are actually running and update registry."""
    try:
        result = subprocess.run(
            ["docker", "compose", "-f", str(COMPOSE_FILE), "ps", "--format", "json"],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0 and result.stdout.strip():
            # Parse running containers
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
        result = subprocess.run(
            ["docker", "compose", "-f", str(COMPOSE_FILE), "up", "-d"],
            capture_output=True, text=True, timeout=120
        )
    except Exception:
        pass


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=PORT)