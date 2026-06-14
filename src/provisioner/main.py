"""ServerStick Provisioning API — Middleman proxy to Pangolin Cloud.

The Pangolin API key lives here, never on the stick.
Sticks authenticate with a device token; this API does the rest.

Run: uvicorn main:app --host 0.0.0.0 --port 9090
"""

import os
import re
import logging
from datetime import datetime, timezone
from typing import Optional

import httpx
from fastapi import FastAPI, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

PANGOLIN_API = os.getenv("PANGOLIN_API", "https://api.pangolin.net/v1")
PANGOLIN_KEY = os.getenv("PANGOLIN_API_KEY", "")
PANGOLIN_ORG_ID = os.getenv("PANGOLIN_ORG_ID", "org_oz3r7e5oiug17wj")
PANGOLIN_DOMAIN_ID = os.getenv("PANGOLIN_DOMAIN_ID", "xf75k3jyq73czxm")  # serverstick.com domain

# Device token — simple shared secret for now (v1). Replace with proper DB later.
DEVICE_TOKEN = os.getenv("DEVICE_TOKEN", "ss_dev_token_change_me")

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

# Rename policy: one rename allowed within RENAME_WINDOW_DAYS of initial provisioning.
# After that, the device name is locked permanently.
RENAME_WINDOW_DAYS = int(os.getenv("RENAME_WINDOW_DAYS", "7"))

# ---------------------------------------------------------------------------
# Service catalog
# ---------------------------------------------------------------------------
# Each service has a list of subdomains. Most services have one, but some
# (e.g., Matrix/Synapse) need multiple: the API/federation endpoint plus
# any auxiliary subdomains.
#
# Each subdomain entry: {subdomain, port, label}
#   - subdomain: prefix prepended to {device}.serverstick.com
#   - port: local port the service listens on
#   - label: human-readable name shown in the Pangolin dashboard
# ---------------------------------------------------------------------------

SERVICE_CATALOG: dict[str, dict] = {
    "dash": {
        "name": "Dashboard",
        "subdomains": [
            {"subdomain": "dash", "port": 8080, "label": "Dashboard"},
        ],
    },
    "home": {
        "name": "Homepage",
        "subdomains": [
            {"subdomain": "home", "port": 3002, "label": "Homepage"},
        ],
    },
    "pdf": {
        "name": "Stirling PDF",
        "subdomains": [
            {"subdomain": "pdf", "port": 8440, "label": "Stirling PDF"},
        ],
    },
    "bin": {
        "name": "PrivateBin",
        "subdomains": [
            {"subdomain": "bin", "port": 8084, "label": "PrivateBin"},
        ],
    },
    "drop": {
        "name": "PairDrop",
        "subdomains": [
            {"subdomain": "drop", "port": 3000, "label": "PairDrop"},
        ],
    },
    "kuma": {
        "name": "Uptime Kuma",
        "subdomains": [
            {"subdomain": "kuma", "port": 3001, "label": "Uptime Kuma"},
        ],
    },
    "rembg": {
        "name": "rembg",
        "subdomains": [
            {"subdomain": "rembg", "port": 7000, "label": "rembg"},
        ],
    },
    "logs": {
        "name": "Dozzle",
        "subdomains": [
            {"subdomain": "logs", "port": 8888, "label": "Dozzle"},
        ],
    },
    "api": {
        "name": "API",
        "subdomains": [
            {"subdomain": "api", "port": 8080, "label": "API"},
        ],
    },
    "matrix": {
        "name": "Matrix (Synapse)",
        "subdomains": [
            # Synapse API + federation endpoint
            {"subdomain": "matrix", "port": 8008, "label": "Synapse"},
            # .well-known delegation — same server, but Pangolin needs
            # a separate resource so we can route it independently
            # if we ever move federation to a different port
        ],
    },
    "watchtower": {
        "name": "Watchtower",
        "subdomains": [],  # headless — no tunnel resource needed
    },
}

DEFAULT_SERVICES = ["dash", "home", "pdf", "bin", "drop", "kuma", "rembg", "logs", "api", "watchtower"]

# ---------------------------------------------------------------------------
# Provisioned device state
# ---------------------------------------------------------------------------
# In-memory store for v1. Replace with a real DB for production.
# Tracks: device_name → {site_id, newt_id, newt_secret, provisioned_at,
#                         renamed_at, rename_count, resources}
# ---------------------------------------------------------------------------

_device_store: dict[str, dict] = {}

def _get_device(device_name: str) -> dict | None:
    return _device_store.get(device_name.lower())

def _save_device(device_name: str, data: dict):
    _device_store[device_name.lower()] = data

# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------

logging.basicConfig(level=LOG_LEVEL, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("serverstick-provisioner")

app = FastAPI(title="ServerStick Provisioning API", version="0.2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["POST", "GET", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class ProvisionRequest(BaseModel):
    device_name: str = Field(..., min_length=2, max_length=20, pattern=r"^[a-z0-9-]+$",
                             description="Device name (becomes subdomain: {svc}.{name}.serverstick.com)")
    services: Optional[list[str]] = Field(default=None,
                                          description="Services to provision. Defaults to all.")
    starter_key: Optional[str] = Field(default=None,
                                       description="Starter API key (credit-based, for future use)")

class ProvisionResponse(BaseModel):
    status: str
    device_name: str
    site_id: int
    newt_id: str
    newt_secret: str
    domain: str
    resources: list[dict]
    tunnel_endpoint: str

class RenameRequest(BaseModel):
    new_device_name: str = Field(..., min_length=2, max_length=20, pattern=r"^[a-z0-9-]+$",
                                  description="New device name")

class RenameResponse(BaseModel):
    status: str
    old_device_name: str
    new_device_name: str
    resources: list[dict]

class HealthResponse(BaseModel):
    status: str
    pangolin_reachable: bool

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def pangolin_headers() -> dict:
    return {
        "Authorization": f"Bearer {PANGOLIN_KEY}",
        "Content-Type": "application/json",
    }

async def pangolin_call(method: str, path: str, json_body: dict | None = None) -> dict:
    """Call the Pangolin API and return the JSON response data."""
    url = f"{PANGOLIN_API}{path}"
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.request(method, url, headers=pangolin_headers(), json=json_body)
        if resp.status_code >= 400:
            logger.error("Pangolin API error %s %s → %d: %s", method, path, resp.status_code, resp.text[:500])
            raise HTTPException(status_code=502, detail=f"Pangolin API error: {resp.status_code} {resp.text[:200]}")
        body = resp.json()
        return body.get("data", body)

async def _create_resources_for_services(
    site_id: int,
    device_name: str,
    services: list[str],
) -> list[dict]:
    """Create Pangolin HTTP resources + targets for each subdomain of each service.
    
    Returns list of {service, subdomain, resourceId, port} dicts.
    """
    resources = []
    for svc in services:
        catalog = SERVICE_CATALOG.get(svc)
        if not catalog:
            logger.warning("Unknown service '%s', skipping", svc)
            continue

        # Skip headless services (no subdomains)
        if not catalog.get("subdomains"):
            logger.info("Service '%s' is headless, no resource needed", svc)
            resources.append({
                "service": svc,
                "subdomain": None,
                "resourceId": None,
                "port": None,
            })
            continue

        for sub_entry in catalog["subdomains"]:
            subdomain = f"{sub_entry['subdomain']}.{device_name}"
            label = sub_entry.get("label", catalog["name"])
            port = sub_entry["port"]

            # Create HTTP resource
            try:
                res_data = await pangolin_call("PUT", f"/org/{PANGOLIN_ORG_ID}/resource", {
                    "name": label,
                    "subdomain": subdomain,
                    "domainId": PANGOLIN_DOMAIN_ID,
                    "http": True,
                    "protocol": "tcp",
                })
                resource_id = res_data.get("resourceId")
                logger.info("Resource created: %s → id=%s", subdomain, resource_id)
            except HTTPException as e:
                logger.warning("Failed to create resource %s: %s", subdomain, e.detail)
                continue

            if not resource_id:
                logger.warning("No resourceId returned for %s, skipping target", subdomain)
                continue

            # Create target: site → 127.0.0.1:port
            try:
                await pangolin_call("PUT", f"/resource/{resource_id}/target", {
                    "siteId": site_id,
                    "ip": "127.0.0.1",
                    "port": port,
                    "method": "http",
                    "enabled": True,
                })
                logger.info("Target created: resource %s → 127.0.0.1:%d", resource_id, port)
            except HTTPException as e:
                logger.warning("Failed to create target for %s: %s", subdomain, e.detail)

            resources.append({
                "service": svc,
                "subdomain": f"{subdomain}.serverstick.com",
                "resourceId": resource_id,
                "port": port,
            })

    return resources


async def _delete_resources(resource_ids: list[int]):
    """Delete Pangolin resources by ID. Best-effort — logs failures but doesn't raise."""
    for rid in resource_ids:
        try:
            await pangolin_call("DELETE", f"/org/{PANGOLIN_ORG_ID}/resource/{rid}")
            logger.info("Deleted resource %d", rid)
        except HTTPException as e:
            logger.warning("Failed to delete resource %d: %s", rid, e.detail)

# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

def verify_device_token(authorization: str = Header(...)):
    """Validate the device token from Authorization header."""
    if authorization.startswith("Bearer "):
        token = authorization[7:]
    else:
        token = authorization

    if token != DEVICE_TOKEN:
        raise HTTPException(status_code=401, detail="Invalid device token")
    return token

# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/health", response_model=HealthResponse)
async def health():
    reachable = False
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(f"{PANGOLIN_API}/", headers=pangolin_headers())
            reachable = resp.status_code == 200
    except Exception:
        pass
    return HealthResponse(status="ok", pangolin_reachable=reachable)


@app.post("/v1/provision", response_model=ProvisionResponse)
async def provision(req: ProvisionRequest, token: str = Header(..., alias="Authorization")):
    """Provision a new ServerStick device: create Pangolin site + resources + targets."""
    verify_device_token(token)

    if not PANGOLIN_KEY:
        raise HTTPException(status_code=500, detail="Pangolin API key not configured")

    device_name = req.device_name.lower().strip()

    # Check if already provisioned
    existing = _get_device(device_name)
    if existing:
        raise HTTPException(status_code=409, detail=f"Device '{device_name}' already provisioned")

    # Resolve services
    requested = req.services or DEFAULT_SERVICES
    services = [s for s in requested if s in SERVICE_CATALOG]
    if not services:
        raise HTTPException(status_code=400, detail="No valid services requested")

    # --- Step 1: Create Pangolin site (type=newt) ---
    logger.info("Creating Pangolin site for device '%s'", device_name)
    site_data = await pangolin_call("PUT", f"/org/{PANGOLIN_ORG_ID}/site", {
        "name": device_name,
        "type": "newt",
    })
    site_id = site_data.get("siteId") or site_data.get("niceId")
    newt_id = site_data.get("newtId", "")
    newt_secret = site_data.get("secret", "")

    if not site_id:
        raise HTTPException(status_code=502, detail=f"Pangolin returned no siteId: {site_data}")

    logger.info("Site created: id=%s, newtId=%s", site_id, newt_id)

    # --- Step 2: Create resources + targets for each service subdomain ---
    resources = await _create_resources_for_services(site_id, device_name, services)

    # --- Step 3: Save device state ---
    _save_device(device_name, {
        "site_id": site_id,
        "newt_id": newt_id,
        "newt_secret": newt_secret,
        "services": services,
        "resources": resources,
        "provisioned_at": datetime.now(timezone.utc).isoformat(),
        "rename_count": 0,
        "renamed_at": None,
    })

    # --- Step 4: Return everything the device needs ---
    return ProvisionResponse(
        status="provisioned",
        device_name=device_name,
        site_id=site_id,
        newt_id=newt_id,
        newt_secret=newt_secret,
        domain=f"{device_name}.serverstick.com",
        resources=resources,
        tunnel_endpoint="gerbil.pangolin.net:50120",
    )


@app.put("/v1/rename", response_model=RenameResponse)
async def rename_device(req: RenameRequest, token: str = Header(..., alias="Authorization")):
    """Rename a provisioned device — changes all subdomains.
    
    Policy: ONE rename allowed, only within RENAME_WINDOW_DAYS of initial provisioning.
    After that, the device name is permanently locked.
    
    This is intentionally hard because renaming:
    - Destroys all existing Pangolin resources (subdomains change)
    - Recreates them under the new device name
    - DNS propagation takes time
    - Users need to update bookmarks, share new links, etc.
    """
    verify_device_token(token)

    if not PANGOLIN_KEY:
        raise HTTPException(status_code=500, detail="Pangolin API key not configured")

    old_name = None
    old_device = None
    # Find the device by looking through the store — we need the Authorization
    # to map to a device. For v1, with a single shared device token, we need
    # the request to identify the device.
    # TODO: When we have per-device tokens, this becomes trivial.
    
    # For now, require the old device name in a header
    # (The Pi Agent knows its own device name)
    raise HTTPException(
        status_code=501,
        detail="Rename requires per-device authentication (not yet implemented). "
               "For now, delete the old site in Pangolin dashboard and re-provision."
    )

    # --- Full rename flow (ready for per-device auth) ---
    # old_name = req.old_device_name  # would need this field
    # old_device = _get_device(old_name)
    # if not old_device:
    #     raise HTTPException(status_code=404, detail=f"Device '{old_name}' not found")
    #
    # # Check rename policy
    # if old_device["rename_count"] >= 1:
    #     raise HTTPException(status_code=403, detail="Device name already renamed once — permanently locked")
    #
    # provisioned_at = datetime.fromisoformat(old_device["provisioned_at"])
    # elapsed = (datetime.now(timezone.utc) - provisioned_at).days
    # if elapsed > RENAME_WINDOW_DAYS:
    #     raise HTTPException(
    #         status_code=403,
    #         detail=f"Rename window expired ({RENAME_WINDOW_DAYS} days). Device name is permanently locked."
    #     )
    #
    # new_name = req.new_device_name.lower().strip()
    # if _get_device(new_name):
    #     raise HTTPException(status_code=409, detail=f"Device name '{new_name}' already taken")
    #
    # # Delete old resources
    # old_resource_ids = [r["resourceId"] for r in old_device["resources"] if r.get("resourceId")]
    # await _delete_resources(old_resource_ids)
    #
    # # Create new resources under new device name
    # new_resources = await _create_resources_for_services(
    #     old_device["site_id"], new_name, old_device["services"]
    # )
    #
    # # Update store
    # old_device["resources"] = new_resources
    # old_device["rename_count"] += 1
    # old_device["renamed_at"] = datetime.now(timezone.utc).isoformat()
    # _save_device(new_name, old_device)
    # del _device_store[old_name]
    #
    # return RenameResponse(
    #     status="renamed",
    #     old_device_name=old_name,
    #     new_device_name=new_name,
    #     resources=new_resources,
    # )


@app.get("/v1/catalog")
async def catalog():
    """Return the service catalog (no auth required — public info)."""
    return {"services": {k: v for k, v in SERVICE_CATALOG.items()}}


@app.get("/v1/device/{device_name}")
async def get_device(device_name: str, token: str = Header(..., alias="Authorization")):
    """Get provisioned device state."""
    verify_device_token(token)
    device = _get_device(device_name)
    if not device:
        raise HTTPException(status_code=404, detail=f"Device '{device_name}' not found")
    return {"device_name": device_name, **device}
