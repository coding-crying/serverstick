#!/usr/bin/env python3
"""ServerStick Model Discovery Endpoint.

Serves at http://localhost:8080 (or SS_DISCOVERY_PORT).
Reads the starter API key from SOPS-encrypted secrets and queries
the provider's /v1/models endpoint.

FALLBACK CHAIN:
  1. Cloud API at api.serverstick.com/v1/models (proxied, cached)
  2. Direct query to provider /v1/models
  3. Hardcoded fallback (last resort)

This is the first thing that comes up on a ServerStick. Before any
wizard, before Pi, before Docker services — this tells you what
models are reachable with your preseeded key.

Endpoints:
  GET /                — Index (available endpoints)
  GET /models          — List available models from the API provider
  GET /health          — Health check (can we read SOPS secrets?)
  GET /key-status      — Key metadata (credits, status, prefix — never the full key)
  GET /setup           — Setup wizard HTML page
  POST /setup/install  — Apply selected services and spawn serverstick-setup apply
  GET /hardware         — Hardware detection JSON
"""

import http.server
import json
import os
import subprocess
import sys
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError
from urllib.parse import urlencode

SS_DIR = os.environ.get("SERVERSTICK_DIR", "/etc/serverstick")
SS_SECRETS = os.path.join(SS_DIR, "secrets")
SS_SOPS_DIR = os.path.join(SS_DIR, "sops")
PORT = int(os.environ.get("SS_DISCOVERY_PORT", "8080"))

# Cloud fallback URL — the Vercel-deployed API
SS_CLOUD_URL = os.environ.get("SS_CLOUD_URL", "https://api.serverstick.com")

# Hardcoded fallback models — TokenRouter-compatible models that work with the built-in starter key
# These are the models most likely to be available via TokenRouter proxy.
# Format matches OpenAI /v1/models response for zero-surprise integration.
HARDCODED_MODELS = [
    {"id": "glm-5.1",                    "object": "model", "created": 1718000000, "owned_by": "zhipu",       "description": "GLM 5.1 — reasoning powerhouse"},
    {"id": "deepseek-chat",              "object": "model", "created": 1718000000, "owned_by": "deepseek",    "description": "DeepSeek V4 Flash — fast general-purpose"},
    {"id": "deepseek-reasoner",          "object": "model", "created": 1718000000, "owned_by": "deepseek",    "description": "DeepSeek R1 — reasoning model"},
    {"id": "gpt-4o",                     "object": "model", "created": 1718000000, "owned_by": "openai",       "description": "GPT-4o — multimodal flagship"},
    {"id": "gpt-4o-mini",               "object": "model", "created": 1718000000, "owned_by": "openai",       "description": "GPT-4o Mini — fast and cheap"},
    {"id": "claude-sonnet-4-20250514",   "object": "model", "created": 1718000000, "owned_by": "anthropic",    "description": "Claude Sonnet 4 — balanced推理"},
]

# Cache for decrypted secrets (in-memory only, cleared on restart)
_secrets_cache = None


def get_secrets() -> dict:
    """Decrypt SOPS secrets. Cached in-memory for the process lifetime."""
    global _secrets_cache
    if _secrets_cache is not None:
        return _secrets_cache

    try:
        result = subprocess.run(
            ["sops", "--output-type", "json", "-d",
             os.path.join(SS_SECRETS, "keys.enc.yaml")],
            capture_output=True, text=True, timeout=10,
            env={**os.environ, "SOPS_AGE_KEY_FILE": os.path.join(SS_SOPS_DIR, "age.key")}
        )
        if result.returncode != 0:
            return {"error": f"sops decrypt failed: {result.stderr}"}
        _secrets_cache = json.loads(result.stdout)
    except Exception as e:
        return {"error": str(e)}

    return _secrets_cache


def fetch_cloud_models(api_key: str, api_base: str) -> dict:
    """Attempt 1: Query the ServerStick cloud API.

    The cloud API proxies the key to the provider and caches results.
    This is preferred because it works even if the device has limited
    network access (e.g., behind corporate proxies that block some providers).
    """
    try:
        params = urlencode({"api_key": api_key, "api_base": api_base})
        url = f"{SS_CLOUD_URL}/v1/models?{params}"
        req = Request(url, headers={"User-Agent": "ServerStick/0.1"})
        with urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
            # Cloud API returns source field: 'live', 'cache', or 'fallback'
            data["source"] = f"cloud-{data.get('source', 'unknown')}"
            return data
    except HTTPError as e:
        body = e.read().decode() if e.fp else ""
        return {"error": f"Cloud API HTTP {e.code}: {body[:300]}"}
    except URLError as e:
        return {"error": f"Cloud API unreachable: {e.reason}"}
    except Exception as e:
        return {"error": f"Cloud API error: {e}"}


def fetch_direct_models(api_key: str, api_base: str) -> dict:
    """Attempt 2: Direct query to the provider's /v1/models endpoint.

    Used as fallback when the cloud API is unreachable.
    """
    try:
        url = f"{api_base.rstrip('/')}/v1/models"
        headers = {"Authorization": f"Bearer {api_key}"}
        req = Request(url, headers=headers)
        with urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode())
            if "error" not in data:
                data["source"] = "direct"
            return data
    except HTTPError as e:
        body = e.read().decode() if e.fp else ""
        return {"error": f"Direct HTTP {e.code}: {body[:500]}"}
    except URLError as e:
        return {"error": f"Direct connection failed: {e.reason}"}
    except Exception as e:
        return {"error": str(e)}


class DiscoveryHandler(http.server.BaseHTTPRequestHandler):
    """Minimal HTTP handler for model discovery."""

    def do_GET(self):
        routes = {
            "/": self.handle_index,
            "/health": self.handle_health,
            "/models": self.handle_models,
            "/models.json": self.handle_models,
            "/key-status": self.handle_key_status,
            "/setup": self.handle_setup,
            "/hardware": self.handle_hardware,
        }
        handler = routes.get(self.path.split("?")[0], self.handle_404)
        handler()

    def do_POST(self):
        routes = {
            "/setup/install": self.handle_setup_install,
        }
        handler = routes.get(self.path.split("?")[0], self.handle_404)
        handler()

    def handle_index(self):
        """Landing page — shows what endpoints are available."""
        info = {
            "service": "ServerStick Model Discovery",
            "version": "0.1.0",
            "endpoints": {
                "/models": "List available models (cloud → direct → fallback)",
                "/models.json": "Same, as downloadable JSON",
                "/health": "Health check (SOPS secrets readable?)",
                "/key-status": "Starter key metadata (credits, status, prefix)",
                "/setup": "Setup wizard HTML page",
                "/setup/install": "POST — Apply selected services",
                "/hardware": "Hardware detection JSON",
            }
        }
        self._json(info)

    def handle_health(self):
        """Health check — can we read SOPS secrets?"""
        secrets = get_secrets()
        if "error" in secrets:
            self._json({"status": "degraded", "error": secrets["error"]}, 503)
        else:
            self._json({
                "status": "ok",
                "sops": "reachable",
                "key_file": "present",
                "cloud_url": SS_CLOUD_URL,
            })

    def handle_models(self):
        """Query models using the fallback chain:
        1. Cloud API (proxied, cached)
        2. Direct provider query
        3. Hardcoded fallback
        """
        secrets = get_secrets()
        if "error" in secrets:
            self._json({"error": secrets["error"]}, 500)
            return

        api_key = secrets.get("STARTER_API_KEY", "")
        api_base = secrets.get("STARTER_API_BASE", "https://api.openai.com/v1")

        if not api_key:
            # No key — return hardcoded fallback list
            self._json({
                "object": "list",
                "source": "fallback-no-key",
                "data": HARDCODED_MODELS,
                "notice": "No API key configured; showing known models."
            })
            return

        # Attempt 1: Cloud API
        cloud = fetch_cloud_models(api_key, api_base)
        if "error" not in cloud:
            self._json(cloud)
            return

        # Attempt 2: Direct provider query
        direct = fetch_direct_models(api_key, api_base)
        if "error" not in direct:
            self._json(direct)
            return

        # Attempt 3: Hardcoded fallback
        self._json({
            "object": "list",
            "source": "fallback",
            "data": HARDCODED_MODELS,
            "notice": "Cloud API and direct provider both failed; showing known models.",
            "errors": {
                "cloud": cloud.get("error", "unknown"),
                "direct": direct.get("error", "unknown"),
            }
        })

    def handle_key_status(self):
        """Show starter key metadata — never the actual key value."""
        secrets = get_secrets()
        if "error" in secrets:
            self._json({"error": secrets["error"]}, 500)
            return

        key = secrets.get("STARTER_API_KEY", "")
        self._json({
            "credits": secrets.get("STARTER_CREDITS", "unknown"),
            "api_base": secrets.get("STARTER_API_BASE", "unknown"),
            "status": secrets.get("STATUS", "unknown"),
            "key_prefix": f"{key[:8]}..." if key else "none",
        })

    def handle_setup(self):
        """Serve the setup wizard HTML page."""
        setup_html_path = "/var/lib/serverstick/setup.html"
        try:
            with open(setup_html_path, "r") as f:
                html = f.read()
        except (FileNotFoundError, OSError):
            # Minimal inline fallback if the file doesn't exist yet
            html = """<!DOCTYPE html>
<html><head><title>ServerStick Setup</title></head>
<body><h1>ServerStick Setup</h1><p>Setup page not yet generated.</p></body></html>"""
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(html.encode())

    def handle_setup_install(self):
        """Accept selected services, write them to disk, and spawn serverstick-setup apply."""
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length).decode() if content_length else ""
        try:
            data = json.loads(body) if body else {}
        except json.JSONDecodeError:
            self._json({"ok": False, "error": "Invalid JSON"}, 400)
            return

        services = data.get("services", [])
        if not isinstance(services, list):
            self._json({"ok": False, "error": "'services' must be a list"}, 400)
            return

        # Write selected services to file (one per line)
        selected_path = os.path.join(SS_DIR, "selected-services")
        try:
            os.makedirs(os.path.dirname(selected_path), exist_ok=True)
            with open(selected_path, "w") as f:
                f.write("\n".join(services) + "\n")
        except OSError as e:
            self._json({"ok": False, "error": f"Failed to write selected-services: {e}"}, 500)
            return

        # Spawn serverstick-setup apply in the background
        try:
            subprocess.Popen(
                ["serverstick-setup", "apply"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
        except Exception as e:
            # Non-fatal — the file is written, apply can be run manually
            pass

        self._json({
            "ok": True,
            "message": f"{len(services)} service{'s' if len(services) != 1 else ''} selected, applying...",
            "services": services,
        })

    def handle_hardware(self):
        """Return hardware detection JSON, running detection inline if needed."""
        hw_path = os.path.join(SS_DIR, "hardware.json")
        try:
            with open(hw_path, "r") as f:
                data = json.load(f)
        except (FileNotFoundError, OSError, json.JSONDecodeError):
            # Run hardware detection inline if the file doesn't exist
            data = self._detect_hardware()
        self._json(data)

    def _detect_hardware(self):
        """Minimal inline hardware detection when hardware.json is absent."""
        import platform
        import shutil

        info = {
            "hostname": platform.node(),
            "platform": platform.system(),
            "architecture": platform.machine(),
            "python_version": platform.python_version(),
            "cpus": os.cpu_count() or 0,
        }

        # Try to get memory info
        try:
            result = subprocess.run(
                ["free", "-m"], capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0:
                lines = result.stdout.strip().split("\n")
                if len(lines) >= 2:
                    parts = lines[1].split()
                    if len(parts) >= 2:
                        info["memory_mb"] = int(parts[1])
        except Exception:
            pass

        # Check for GPU
        for cmd in ["nvidia-smi", "rocminfo", "mthreads-gmi"]:
            if shutil.which(cmd):
                try:
                    result = subprocess.run(
                        [cmd], capture_output=True, text=True, timeout=5
                    )
                    if result.returncode == 0:
                        info["gpu_detected"] = True
                        info["gpu_tool"] = cmd
                        break
                except Exception:
                    pass

        info["source"] = "inline-detection"
        return info

    def handle_404(self):
        self._json({"error": "not found", "endpoints": ["/", "/models", "/health", "/key-status", "/setup", "/hardware"]}, 404)

    def _json(self, data, code=200):
        payload = json.dumps(data, indent=2)
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(payload.encode())

    def log_message(self, format, *args):
        # Quieter logging — only log errors
        if any(c in str(args) for c in ["404", "500", "502", "503"]):
            sys.stderr.write(f"[discover] {format % args}\n")


def main():
    print(f"[discover] ServerStick Model Discovery v0.1.0")
    print(f"[discover] Listening on http://0.0.0.0:{PORT}")
    print(f"[discover] SOPS secrets: {SS_SECRETS}")
    print(f"[discover] Age key: {SS_SOPS_DIR}/age.key")
    print(f"[discover] Cloud fallback: {SS_CLOUD_URL}")

    # Pre-warm the secrets cache
    secrets = get_secrets()
    if "error" in secrets:
        print(f"[discover] WARNING: SOPS decrypt failed: {secrets['error']}")
        print(f"[discover]          Model listing will not work until secrets are readable")
    else:
        print(f"[discover] Secrets loaded. API base: {secrets.get('STARTER_API_BASE', 'unknown')}")

    server = http.server.HTTPServer(("0.0.0.0", PORT), DiscoveryHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[discover] Shutting down.")
        server.server_close()


if __name__ == "__main__":
    main()