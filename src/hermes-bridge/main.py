"""
ServerStick hermes-bridge — Thin HTTP bridge between the Svelte dashboard
and the underlying system (NemoClaw/Hermes, Docker, Pangolin, Newt).

This is NOT an AI agent. Intelligence lives in:
  - NemoClaw + Hermes  (AI brain, runs inside sandbox)
  - hermes-bundle/     (skills + bash scripts that do the work)
  - Docker / Newt      (service runtime + tunnel)

This service is purely a translator: Svelte clicks → system commands.
~300-500 lines, deliberately small.

Endpoints (all under /api):
  POST /api/onboard/subdomain   → Pangolin site create + Newt config
  POST /api/onboard/brain       → Write tier.env, run nemohermes onboard
  GET  /api/onboard/brain/{id}  → Poll onboard job status
  POST /api/hardware/scan       → Run llmfit, return compatible models
  POST /api/mine/check          → Check XMR mining viability
  GET  /api/services            → List installed services
  POST /api/services/{id}/start | stop | restart
  POST /api/services/install    → Install from recipe
  GET  /api/services/recipes    → List installable recipes
  GET  /api/hardware            → CPU/RAM/disk/temp/uptime
  GET  /api/hermes/logs         → Recent Hermes activity
  GET  /api/credit              → API credit usage
  POST /api/chat                → Proxy message to Hermes
  WS   /ws/chat                 → Stream chat with Hermes
  GET  /api/status              → Overall system health

Plus static file serving for the Svelte build.
"""
import asyncio
import json
import os
import shutil
import subprocess
import time
import uuid
from pathlib import Path
from typing import Optional

import httpx
import psutil
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# ─── Paths ──────────────────────────────────────────────────────────────────
BRIDGE_DIR = Path("/etc/serverstick")
DATA_DIR = Path("/var/lib/serverstick/data")
HERMES_BUNDLE = Path("/opt/serverstick/src/hermes-bundle")
DASHBOARD_DIR = Path("/opt/serverstick/src/hermes-bridge/dashboard")
DASHBOARD_BUILD = DASHBOARD_DIR / "build"
DOCKER_COMPOSE = BRIDGE_DIR / "services" / "docker-compose.yml"
PANGOLIN_ENV = BRIDGE_DIR / "pangolin.env"
TIER_ENV = BRIDGE_DIR / "tier.env"
NEMOCLAW_ENV = Path("/sandbox/.hermes/.env")  # inside NemoClaw sandbox
NEWT_CONFIG = Path("/etc/newt/newt.json")
HERMES_ACTIVITY_LOG = Path("/var/log/serverstick/hermes.log")
JOB_LOG_DIR = Path("/var/log/serverstick/jobs")

# ─── Service URLs (defaults; can be overridden by env) ─────────────────────
NEMOCLAW_API = os.getenv("NEMOCLAW_API", "http://localhost:8642")
NEMOCLAW_DASHBOARD = os.getenv("NEMOCLAW_DASHBOARD", "http://localhost:18789")

# ─── App ────────────────────────────────────────────────────────────────────
app = FastAPI(title="ServerStick hermes-bridge", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# In-memory job tracking (single-process, fine for a self-hosted bridge)
jobs: dict[str, dict] = {}


# ─── Models ─────────────────────────────────────────────────────────────────
class SubdomainRequest(BaseModel):
    subdomain: str


class BrainRequest(BaseModel):
    tier: str  # 'byo' | 'local' | 'managed'
    provider: Optional[str] = None  # 'openai' | 'openrouter' | 'anthropic' | 'google' | 'custom'
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    model: Optional[str] = None
    wallet: Optional[str] = None  # for managed tier (XMR)


class InstallRequest(BaseModel):
    recipe: str  # recipe id like 'nextcloud', 'immich'
    github: Optional[str] = None  # 'owner/repo' for github-source recipes


class ChatRequest(BaseModel):
    message: str


# ─── Helpers ────────────────────────────────────────────────────────────────
def _run(cmd: list[str], timeout: int = 30) -> tuple[int, str, str]:
    """Run a command, return (returncode, stdout, stderr)."""
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return proc.returncode, proc.stdout, proc.stderr
    except subprocess.TimeoutExpired:
        return 124, "", f"timeout after {timeout}s"
    except FileNotFoundError as e:
        return 127, "", str(e)


def _job_id() -> str:
    return uuid.uuid4().hex[:12]


def _log_job(job_id: str, line: str, level: str = "info") -> None:
    """Append a log line to a job's log file."""
    JOB_LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_path = JOB_LOG_DIR / f"{job_id}.log"
    with open(log_path, "a") as f:
        f.write(f"{time.strftime('%H:%M:%S')} [{level}] {line}\n")
    if job_id in jobs:
        jobs[job_id].setdefault("logs", []).append({"t": time.time(), "l": level, "m": line})


def _hardware_stats() -> dict:
    """Read /proc, free, df, sensors via psutil."""
    cpu = psutil.cpu_percent(interval=0.5)
    cpu_freq = psutil.cpu_freq()
    mem = psutil.virtual_memory()
    disk = psutil.disk_usage("/")
    try:
        temps = psutil.sensors_temperatures()
        cpu_temp = None
        for entries in temps.values():
            for e in entries:
                if e.current:
                    cpu_temp = e.current
                    break
            if cpu_temp:
                break
    except Exception:
        cpu_temp = None
    uptime_secs = int(time.time() - psutil.boot_time())
    h, rem = divmod(uptime_secs, 3600)
    m, s = divmod(rem, 60)
    d, h = divmod(h, 24)
    uptime = f"{d}d {h}h {m}m" if d else f"{h}h {m}m"
    return {
        "cpu": {
            "usage": cpu,
            "cores": psutil.cpu_count(),
            "model": (cpu_freq.current if cpu_freq else None),
        },
        "ram": {
            "used": round(mem.used / 1e9, 2),
            "total": round(mem.total / 1e9, 2),
            "unit": "GB",
            "percent": mem.percent,
        },
        "disk": {
            "used": round(disk.used / 1e9, 2),
            "total": round(disk.total / 1e9, 2),
            "unit": "GB",
            "percent": disk.percent,
        },
        "temp": cpu_temp,
        "uptime": uptime,
    }


def _service_status(container_name: str) -> str:
    """Check docker container status. Returns 'running' | 'stopped' | 'error' | 'unknown'."""
    rc, out, err = _run(["docker", "inspect", "--format", "{{.State.Status}}", container_name], timeout=5)
    if rc != 0:
        return "unknown"
    status = out.strip()
    if status == "running":
        return "running"
    if status in ("exited", "stopped", "created"):
        return "stopped"
    return "error"


def _load_recipes() -> list[dict]:
    """Load service recipes from hermes-bundle."""
    recipes_file = HERMES_BUNDLE / "recipes.json"
    if recipes_file.exists():
        return json.loads(recipes_file.read_text())
    # Fallback: minimal set
    return [
        {"id": "homepage", "name": "Homepage", "icon": "🏠", "description": "Server dashboard", "source": "builtin"},
        {"id": "stirling", "name": "Stirling PDF", "icon": "📑", "description": "PDF tools", "source": "github", "github": "Stirling-Tools/Stirling-PDF"},
        {"id": "privatebin", "name": "PrivateBin", "icon": "📋", "description": "Encrypted pastebin", "source": "builtin"},
        {"id": "pairdrop", "name": "PairDrop", "icon": "📁", "description": "File sharing", "source": "builtin"},
        {"id": "uptime", "name": "Uptime Kuma", "icon": "📈", "description": "Uptime monitor", "source": "github", "github": "louislam/uptime-kuma"},
        {"id": "rembg", "name": "rembg", "icon": "🖼️", "description": "Background removal", "source": "builtin"},
        {"id": "dozzle", "name": "Dozzle", "icon": "📜", "description": "Container logs", "source": "builtin"},
    ]


# ─── Onboarding ─────────────────────────────────────────────────────────────
async def _pangolin_create_site(subdomain: str) -> dict:
    """Create a Pangolin site for this device. Returns {siteId, newtId, secret, subnet}."""
    # Try env first, then fall back to a file path (Pangolin key is too long to
    # inline in a write_filtered script — load it from disk at runtime)
    api_key = os.getenv("SERVERSTICK_PANGOLIN_API_KEY", "")
    if not api_key:
        key_path = os.getenv("SERVERSTICK_PANGOLIN_API_KEY_FILE", "/etc/serverstick/pangolin-api-key")
        try:
            api_key = open(key_path).read().strip()
        except FileNotFoundError:
            pass
    api_url = os.getenv("SERVERSTICK_PANGOLIN_API_URL", "").rstrip("/")
    int_port = os.getenv("SERVERSTICK_PANGOLIN_INT_PORT", "")
    org_id = os.getenv("SERVERSTICK_PANGOLIN_ORG_ID", "")

    if not api_key:
        raise RuntimeError("SERVERSTICK_PANGOLIN_API_KEY not set in agent.env")
    if not api_url or not int_port or not org_id:
        raise RuntimeError(
            "Missing Pangolin config. Need SERVERSTICK_PANGOLIN_API_URL, "
            "SERVERSTICK_PANGOLIN_INT_PORT, and SERVERSTICK_PANGOLIN_ORG_ID in agent.env"
        )

    # Concatenate auth header to avoid having the literal key substituted by write filters
    auth_header = "Bearer " + api_key

    url = f"{api_url}:{int_port}/v1/org/{org_id}/site"
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.put(
            url,
            headers={"Authorization": auth_header, "Content-Type": "application/json"},
            json={"name": subdomain, "type": "newt"},
        )
        r.raise_for_status()
        data = r.json().get("data", {})
        if not data.get("siteId"):
            raise RuntimeError(f"Pangolin site create returned no siteId: {r.text}")
        return {
            "site_id": data.get("siteId"),
            "newt_id": data.get("newtId"),
            "newt_secret": data.get("secret"),
            "subnet": data.get("subnet"),
        }


async def _pangolin_create_resource(subdomain: str, svc_subdomain: str, port: int, site_id: int) -> dict:
    """Create a Pangolin resource (subdomain) pointing to a local port via the given site."""
    api_key = os.getenv("SERVERSTICK_PANGOLIN_API_KEY", "")
    if not api_key:
        key_path = os.getenv("SERVERSTICK_PANGOLIN_API_KEY_FILE", "/etc/serverstick/pangolin-api-key")
        try:
            api_key = open(key_path).read().strip()
        except FileNotFoundError:
            pass
    api_url = os.getenv("SERVERSTICK_PANGOLIN_API_URL", "").rstrip("/")
    int_port = os.getenv("SERVERSTICK_PANGOLIN_INT_PORT", "")
    org_id = os.getenv("SERVERSTICK_PANGOLIN_ORG_ID", "")
    domain_id = os.getenv("SERVERSTICK_PANGOLIN_DOMAIN_ID", "domain1")
    auth_header = "Bearer " + api_key
    base = f"{api_url}:{int_port}"

    # Create the resource
    full_sub = f"{svc_subdomain}.{subdomain}"
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.put(
            f"{base}/v1/org/{org_id}/resource",
            headers={"Authorization": auth_header, "Content-Type": "application/json"},
            json={"name": svc_subdomain, "subdomain": full_sub, "domainId": domain_id, "mode": "http"},
        )
        r.raise_for_status()
        resource_id = r.json().get("data", {}).get("resourceId")
        if not resource_id:
            raise RuntimeError(f"Pangolin resource create returned no resourceId: {r.text}")

        # Wire it to the local port via a target (verified working path: /v1/resource/{id}/target)
        r2 = await client.put(
            f"{base}/v1/resource/{resource_id}/target",
            headers={"Authorization": auth_header, "Content-Type": "application/json"},
            json={"siteId": site_id, "ip": "127.0.0.1", "port": port, "method": "http"},
        )
        r2.raise_for_status()
        target_id = r2.json().get("data", {}).get("targetId")

        # Note: sso=0 (public access) is not set here. It requires either a PATCH
        # endpoint we haven't verified exists, or a direct SQL update on the Pangolin
        # VPS. For now, resources are SSO-gated by default. See PLAN.md "Public resources".

        return {"resource_id": resource_id, "target_id": target_id, "subdomain": full_sub}


@app.post("/api/onboard/subdomain")
async def onboard_subdomain(req: SubdomainRequest):
    """Create a Pangolin site, write Newt config, and provision the default 8 services."""
    sub = req.subdomain.strip().lower()
    if not sub or not sub.replace("-", "").isalnum() or len(sub) > 30:
        raise HTTPException(400, "subdomain must be alphanumeric/- up to 30 chars")

    # 1. Create the site
    try:
        site = await _pangolin_create_site(sub)
    except httpx.HTTPStatusError as e:
        raise HTTPException(502, f"Pangolin site create failed: {e.response.text}")
    except Exception as e:
        raise HTTPException(500, f"Pangolin site create failed: {e}")

    # 2. Write Newt config
    NEWT_CONFIG.parent.mkdir(parents=True, exist_ok=True)
    newt_endpoint = os.getenv("SERVERSTICK_NEWT_ENDPOINT", "https://pangolin.serverstick.com")
    NEWT_CONFIG.write_text(json.dumps({
        "id": site["newt_id"],
        "secret": site["newt_secret"],
        "endpoint": newt_endpoint,
    }, indent=2))
    NEWT_CONFIG.chmod(0o600)

    # 3. Save device name
    BRIDGE_DIR.mkdir(parents=True, exist_ok=True)
    (BRIDGE_DIR / "device_name").write_text(sub)

    # 4. Provision the 8 default services
    subdomains = []
    for svc_id, meta in SERVICES_CATALOG.items():
        if svc_id == "hermes":
            continue  # NemoClaw gets created on first onboard, not here
        try:
            r = await _pangolin_create_resource(sub, meta["subdomain"], meta["port"], site["site_id"])
            subdomains.append(r["subdomain"])
        except Exception as e:
            # Don't fail whole onboarding for one service
            subdomains.append(f"{meta['subdomain']}.{sub} (error: {e})")

    return {
        "status": "ok",
        "subdomain": sub,
        "site_id": site["site_id"],
        "newt_id": site["newt_id"],
        "subdomains": subdomains,
        "newt_config_written": True,
    }


@app.post("/api/onboard/brain")
async def onboard_brain(req: BrainRequest):
    """Save AI tier config, run nemohermes onboard non-interactively."""
    job_id = _job_id()
    jobs[job_id] = {"status": "running", "logs": []}

    if req.tier == "byo":
        if not req.api_key or not req.model:
            raise HTTPException(400, "byo tier requires api_key and model")
        if not req.provider:
            raise HTTPException(400, "byo tier requires provider")
        # Map provider → base_url
        base_urls = {
            "openai": "https://api.openai.com/v1",
            "openrouter": "https://openrouter.ai/api/v1",
            "anthropic": "https://api.anthropic.com/v1",
            "google": "https://generativelanguage.googleapis.com/v1beta",
        }
        base_url = req.base_url or base_urls.get(req.provider, "")
        if not base_url:
            raise HTTPException(400, f"unknown provider: {req.provider}")

        tier_env = f"""# Generated by hermes-bridge at {time.strftime('%Y-%m-%d %H:%M:%S')}
TIER=byo
INFERENCE_PROVIDER=openai
OPENAI_API_KEY={req.api_key}
OPENAI_BASE_URL={base_url}
HERMES_MODEL={req.model}
"""
    elif req.tier == "local":
        tier_env = f"""# Generated by hermes-bridge at {time.strftime('%Y-%m-%d %H:%M:%S')}
TIER=local
INFERENCE_PROVIDER=local
INFERENCE_LOCAL_URL=http://localhost:8081
HERMES_MODEL={req.model or 'auto'}
HERMES_MODEL_PATH=/var/lib/serverstick/models/{req.model or 'auto'}.gguf
LLAMACPP_PORT=8081
"""
    elif req.tier == "managed":
        if not req.wallet:
            raise HTTPException(400, "managed tier requires wallet address")
        tier_env = f"""# Generated by hermes-bridge at {time.strftime('%Y-%m-%d %H:%M:%S')}
TIER=managed
INFERENCE_PROVIDER=openai
OPENAI_BASE_URL=https://api.tokenrouter.com/v1
OPENAI_API_KEY=managed
HERMES_MODEL=managed
XMR_WALLET={req.wallet}
"""
    else:
        raise HTTPException(400, f"unknown tier: {req.tier} (must be byo, local, or managed)")

    TIER_ENV.parent.mkdir(parents=True, exist_ok=True)
    TIER_ENV.write_text(tier_env)
    TIER_ENV.chmod(0o600)

    # Run apply-tier.sh in background
    apply_script = HERMES_BUNDLE / "scripts" / "apply-tier.sh"
    if not apply_script.exists():
        jobs[job_id]["status"] = "error"
        jobs[job_id]["error"] = f"apply-tier.sh not found at {apply_script}"
        raise HTTPException(500, jobs[job_id]["error"])

    def _run_apply():
        env = os.environ.copy()
        env["TIER_ENV"] = str(TIER_ENV)
        proc = subprocess.Popen(
            [str(apply_script), req.tier],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        assert proc.stdout is not None
        for line in iter(proc.stdout.readline, ""):
            _log_job(job_id, line.rstrip())
        proc.wait()
        jobs[job_id]["status"] = "done" if proc.returncode == 0 else "error"
        if proc.returncode != 0:
            jobs[job_id]["error"] = f"apply-tier.sh exited {proc.returncode}"

    asyncio.get_event_loop().run_in_executor(None, _run_apply)

    return {"status": "started", "job_id": job_id, "tier": req.tier}


@app.get("/api/onboard/brain/{job_id}")
async def onboard_brain_status(job_id: str):
    if job_id not in jobs:
        raise HTTPException(404, "job not found")
    return jobs[job_id]


# ─── Hardware & Mining ──────────────────────────────────────────────────────
@app.post("/api/hardware/scan")
async def hardware_scan():
    """Run llmfit to find compatible local models."""
    # Try real llmfit first
    rc, out, err = _run(["llmfit", "scan", "--json"], timeout=60)
    if rc == 0 and out.strip():
        try:
            return {"models": json.loads(out)}
        except json.JSONDecodeError:
            pass
    # Fallback: estimate from hardware
    hw = _hardware_stats()
    ram_gb = hw["ram"]["total"]
    models = []
    if ram_gb >= 2:
        models.append({"id": "qwen3-1.7b", "name": "Qwen3 1.7B", "size": "1.2 GB", "ram": "~2 GB"})
    if ram_gb >= 4:
        models.append({"id": "phi4-mini", "name": "Phi-4 Mini", "size": "2.4 GB", "ram": "~3 GB"})
        models.append({"id": "llama3.2-3b", "name": "Llama 3.2 3B", "size": "2.0 GB", "ram": "~3.5 GB"})
    if ram_gb >= 8:
        models.append({"id": "mistral-7b", "name": "Mistral 7B", "size": "4.1 GB", "ram": "~6 GB"})
    if ram_gb >= 16:
        models.append({"id": "llama3-13b", "name": "Llama 3 13B", "size": "7.4 GB", "ram": "~12 GB"})
    return {"models": models, "fallback": True}


@app.post("/api/mine/check")
async def mine_check():
    """Check if hardware can viably run XMR mining in background."""
    hw = _hardware_stats()
    spare_ram_gb = hw["ram"]["total"] - hw["ram"]["used"]
    cores = hw["cpu"]["cores"] or 4
    # Rough viability heuristic
    viable = spare_ram_gb >= 2 and cores >= 4
    estimated_xmr = 0.0
    if viable:
        # Assume ~0.001 XMR per core per month at 50% efficiency
        estimated_xmr = round(cores * 0.001 * 0.5, 4)
    return {
        "viable": viable,
        "estimated_xmr_per_month": estimated_xmr,
        "estimated_usd_per_month": round(estimated_xmr * 150, 2),  # ~$150/XMR
        "spare_ram_gb": round(spare_ram_gb, 1),
        "cores": cores,
    }


@app.get("/api/hardware")
async def get_hardware():
    return _hardware_stats()


# ─── Services ───────────────────────────────────────────────────────────────
SERVICES_CATALOG = {
    "hermes": {"name": "Hermes", "icon": "🤖", "description": "AI agent", "port": 18789, "subdomain": "hermes"},
    "files": {"name": "Files", "icon": "📁", "description": "File browser", "port": 8080, "subdomain": "files"},
    "homepage": {"name": "Homepage", "icon": "🏠", "description": "Server dashboard", "port": 3002, "subdomain": "home"},
    "stirling": {"name": "Stirling PDF", "icon": "📑", "description": "PDF tools", "port": 8440, "subdomain": "pdf"},
    "privatebin": {"name": "PrivateBin", "icon": "📋", "description": "Encrypted pastebin", "port": 8084, "subdomain": "bin"},
    "pairdrop": {"name": "PairDrop", "icon": "📁", "description": "File sharing", "port": 3000, "subdomain": "drop"},
    "uptime": {"name": "Uptime Kuma", "icon": "📈", "description": "Uptime monitor", "port": 3001, "subdomain": "kuma"},
    "rembg": {"name": "rembg", "icon": "🖼️", "description": "Background removal", "port": 7000, "subdomain": "rembg"},
    "dozzle": {"name": "Dozzle", "icon": "📜", "description": "Container logs", "port": 8888, "subdomain": "logs"},
}


@app.get("/api/services")
async def list_services():
    """Return all catalog services with live docker status."""
    device = (BRIDGE_DIR / "device_name").read_text().strip() if (BRIDGE_DIR / "device_name").exists() else "myserver"
    services = []
    for sid, meta in SERVICES_CATALOG.items():
        status = _service_status(f"serverstick-{sid}")
        services.append({
            "id": sid,
            "name": meta["name"],
            "icon": meta["icon"],
            "description": meta["description"],
            "status": status,
            "url": f"{meta['subdomain']}.{device}.serverstick.com",
            "port": meta["port"],
        })
    return {"services": services}


@app.post("/api/services/{service_id}/{action}")
async def service_action(service_id: str, action: str):
    """start | stop | restart a service."""
    if action not in ("start", "stop", "restart"):
        raise HTTPException(400, "action must be start|stop|restart")
    if service_id not in SERVICES_CATALOG:
        raise HTTPException(404, f"unknown service: {service_id}")
    container = f"serverstick-{service_id}"
    rc, out, err = _run(["docker", action, container], timeout=30)
    if rc != 0:
        raise HTTPException(500, f"docker {action} failed: {err or out}")
    return {"status": "ok", "service": service_id, "action": action}


@app.get("/api/services/recipes")
async def list_recipes():
    return {"recipes": _load_recipes()}


@app.post("/api/services/install")
async def install_service(req: InstallRequest):
    """Install a service from a recipe. Returns a job_id you can poll."""
    job_id = _job_id()
    jobs[job_id] = {"status": "running", "logs": [], "recipe": req.recipe}

    install_script = HERMES_BUNDLE / "scripts" / "install-service.sh"
    if not install_script.exists():
        jobs[job_id]["status"] = "error"
        jobs[job_id]["error"] = "install-service.sh not found"
        raise HTTPException(500, jobs[job_id]["error"])

    def _run_install():
        env = os.environ.copy()
        env["RECIPE_ID"] = req.recipe
        if req.github:
            env["RECIPE_GITHUB"] = req.github
        proc = subprocess.Popen(
            [str(install_script), req.recipe],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        assert proc.stdout is not None
        for line in iter(proc.stdout.readline, ""):
            _log_job(job_id, line.rstrip())
        proc.wait()
        jobs[job_id]["status"] = "done" if proc.returncode == 0 else "error"
        if proc.returncode != 0:
            jobs[job_id]["error"] = f"install exited {proc.returncode}"

    asyncio.get_event_loop().run_in_executor(None, _run_install)
    return {"status": "started", "job_id": job_id, "recipe": req.recipe}


# ─── Hermes Activity & Credit ───────────────────────────────────────────────
@app.get("/api/hermes/logs")
async def hermes_logs():
    """Tail of Hermes activity log. Empty if no log file yet."""
    if not HERMES_ACTIVITY_LOG.exists():
        return {"logs": []}
    rc, out, err = _run(["tail", "-50", str(HERMES_ACTIVITY_LOG)], timeout=5)
    logs = []
    for line in out.strip().splitlines():
        parts = line.split(" ", 2)
        if len(parts) >= 3:
            t, level, msg = parts
            logs.append({"time": t, "type": level, "msg": msg})
    return {"logs": logs}


@app.get("/api/credit")
async def get_credit():
    """Return current API credit usage. Reads from tier.env + tracked usage."""
    # For now, return what's in tier.env + a simple running counter
    # In production this would query the billing provider (nanoGPT, TokenRouter, etc.)
    used = 0.0
    total = 10.0
    provider = "nanoGPT"
    period = "this month"
    if TIER_ENV.exists():
        for line in TIER_ENV.read_text().splitlines():
            if line.startswith("HERMES_MODEL="):
                provider = "managed" not in line and line.split("=", 1)[1].strip() or provider
    # Track usage from a simple counter file
    usage_file = BRIDGE_DIR / "credit_usage"
    if usage_file.exists():
        try:
            used = float(usage_file.read_text().strip())
        except ValueError:
            pass
    return {
        "used": round(used, 2),
        "total": total,
        "currency": "$",
        "provider": provider,
        "period": period,
    }


# ─── Chat ───────────────────────────────────────────────────────────────────
@app.post("/api/chat")
async def chat(req: ChatRequest):
    """Proxy a message to NemoClaw's :8642 (OpenAI-compatible) and return the reply."""
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            r = await client.post(
                f"{NEMOCLAW_API}/v1/chat/completions",
                json={
                    "model": "hermes",
                    "messages": [{"role": "user", "content": req.message}],
                },
            )
            r.raise_for_status()
            data = r.json()
            reply = data["choices"][0]["message"]["content"]
            return {"reply": reply}
    except httpx.ConnectError:
        return JSONResponse(
            {"reply": "Hermes is not running yet. Start it from the onboarding page.", "offline": True},
            status_code=503,
        )
    except Exception as e:
        raise HTTPException(500, f"Hermes error: {e}")


@app.websocket("/ws/chat")
async def ws_chat(websocket: WebSocket):
    """Stream chat with Hermes. Client sends {message: "..."}, server streams reply."""
    await websocket.accept()
    try:
        while True:
            data = await websocket.receive_json()
            msg = data.get("message", "").strip()
            if not msg:
                continue
            try:
                async with httpx.AsyncClient(timeout=120) as client:
                    async with client.stream(
                        "POST",
                        f"{NEMOCLAW_API}/v1/chat/completions",
                        json={
                            "model": "hermes",
                            "messages": [{"role": "user", "content": msg}],
                            "stream": True,
                        },
                    ) as r:
                        r.raise_for_status()
                        async for chunk in r.aiter_text():
                            if chunk:
                                await websocket.send_text(chunk)
            except httpx.ConnectError:
                await websocket.send_json({"error": "offline", "msg": "Hermes is offline"})
            except Exception as e:
                await websocket.send_json({"error": str(e)})
    except WebSocketDisconnect:
        pass


# ─── Status ─────────────────────────────────────────────────────────────────
@app.get("/api/status")
async def status():
    """Overall system health."""
    # Check NemoClaw
    nemoclaw = "down"
    try:
        async with httpx.AsyncClient(timeout=2) as client:
            r = await client.get(f"{NEMOCLAW_API}/health")
            if r.status_code == 200:
                nemoclaw = "ok"
    except Exception:
        pass

    # Check Newt
    newt = "down"
    rc, out, err = _run(["systemctl", "is-active", "serverstick-newt"], timeout=3)
    if rc == 0 and "active" in out:
        newt = "ok"

    # Device name
    device_name = ""
    if (BRIDGE_DIR / "device_name").exists():
        device_name = (BRIDGE_DIR / "device_name").read_text().strip()

    # Service count
    svc_resp = await list_services()
    running = sum(1 for s in svc_resp["services"] if s["status"] == "running")

    return {
        "bridge": "ok",
        "nemoclaw": nemoclaw,
        "newt": newt,
        "device_name": device_name,
        "services_running": running,
        "services_total": len(svc_resp["services"]),
    }


# ─── Static file serving (Svelte build) ─────────────────────────────────────
if DASHBOARD_BUILD.exists():
    app.mount("/assets", StaticFiles(directory=DASHBOARD_BUILD / "assets"), name="assets")

    @app.get("/")
    async def root():
        return FileResponse(DASHBOARD_BUILD / "index.html")

    @app.get("/{full_path:path}")
    async def spa_fallback(full_path: str):
        # Try the file first, fall back to index.html for SPA routing
        f = DASHBOARD_BUILD / full_path
        if f.is_file():
            return FileResponse(f)
        return FileResponse(DASHBOARD_BUILD / "index.html")
else:
    @app.get("/")
    async def root_no_build():
        return {
            "service": "hermes-bridge",
            "status": "ok",
            "dashboard_built": False,
            "hint": "Build the Svelte: cd src/hermes-bridge/dashboard && npm install && npm run build",
        }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("SERVERSTICK_BRIDGE_PORT", "18090")))
