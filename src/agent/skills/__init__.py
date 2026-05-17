"""Skill plugin system for ServerStick services.

Each service has a YAML catalog entry (image, port, volumes, health check)
and an optional Python class for advanced operations. Skills are loaded
dynamically from the catalog/ directory.

Services can be managed two ways:
1. Individual per-service compose files (installed via install/uninstall)
2. Shared compose file at /etc/serverstick/services/docker-compose.yml

The system detects which mode is active and uses the appropriate one.
"""

import json
import os
import subprocess
from pathlib import Path
from typing import Any

import yaml

# Use the same env vars as main.py
SS_DIR = Path(os.environ.get("SERVERSTICK_DIR", "/etc/serverstick"))
SS_DATA = Path(os.environ.get("SERVERSTICK_DATA", "/var/lib/serverstick/data"))


class SkillBase:
    """Base class for service skill plugins."""

    # Catalog entry loaded from YAML
    catalog_entry: dict = {}

    # Docker Compose project name
    project: str = "serverstick"

    def __init__(self, catalog_entry: dict):
        self.catalog_entry = catalog_entry
        self.name = catalog_entry.get("name", "unknown")
        self.compose_dir = SS_DIR / "services" / self.name

    def install(self) -> dict:
        """Install the service via Docker Compose.

        If a shared compose file exists at /etc/serverstick/services/docker-compose.yml,
        just start the service from there. Otherwise, generate per-service compose.
        """
        shared_compose = SS_DIR / "services" / "docker-compose.yml"
        if shared_compose.exists():
            # Shared compose mode — just bring up this service
            result = subprocess.run(
                ["docker", "compose", "-f", str(shared_compose), "up", "-d", self.name],
                capture_output=True, text=True, timeout=120
            )
            return {"success": result.returncode == 0, "output": result.stdout + result.stderr, "mode": "shared"}

        # Per-service compose mode
        self.compose_dir.mkdir(parents=True, exist_ok=True)
        compose = self._generate_compose()
        (self.compose_dir / "docker-compose.yml").write_text(compose)

        result = self._compose("up", "-d")
        return {"success": result.returncode == 0, "output": result.stdout + result.stderr, "mode": "individual"}

    def uninstall(self) -> dict:
        """Remove the service."""
        shared_compose = SS_DIR / "services" / "docker-compose.yml"
        if shared_compose.exists():
            # Shared compose — stop and remove this service's container
            result = subprocess.run(
                ["docker", "compose", "-f", str(shared_compose), "stop", self.name],
                capture_output=True, text=True, timeout=60
            )
            subprocess.run(
                ["docker", "compose", "-f", str(shared_compose), "rm", "-f", self.name],
                capture_output=True, text=True, timeout=30
            )
            return {"success": result.returncode == 0, "output": result.stdout + result.stderr, "mode": "shared"}

        result = self._compose("down")
        return {"success": result.returncode == 0, "output": result.stdout + result.stderr, "mode": "individual"}

    def start(self) -> dict:
        """Start the service."""
        result = self._resolve_compose("start", self.name)
        return {"success": result.returncode == 0, "output": result.stdout + result.stderr}

    def stop(self) -> dict:
        """Stop the service."""
        result = self._resolve_compose("stop", self.name)
        return {"success": result.returncode == 0, "output": result.stdout + result.stderr}

    def restart(self) -> dict:
        """Restart the service."""
        result = self._resolve_compose("restart", self.name)
        return {"success": result.returncode == 0, "output": result.stdout + result.stderr}

    def get_status(self) -> dict:
        """Check service status.

        Checks compose file existence first (installed=True if file exists),
        then checks Docker for running state.
        """
        # Check shared compose first
        shared_compose = SS_DIR / "services" / "docker-compose.yml"
        per_service_compose = self.compose_dir / "docker-compose.yml"

        if shared_compose.exists():
            # Shared compose mode — check if this service exists in it
            try:
                compose_data = yaml.safe_load(shared_compose.read_text())
                services = compose_data.get("services", {})
                if self.name not in services:
                    return {"installed": False, "running": False, "status": "not_in_compose"}
            except Exception:
                pass

            # Service is in shared compose — check if container is running
            try:
                result = subprocess.run(
                    ["docker", "compose", "-f", str(shared_compose), "ps", "--format", "json"],
                    capture_output=True, text=True, timeout=10
                )
                if result.returncode == 0 and result.stdout.strip():
                    for line in result.stdout.strip().splitlines():
                        try:
                            c = json.loads(line)
                            # Match by service name or container name
                            svc = c.get("Service", c.get("Name", ""))
                            if svc == self.name or svc.endswith(f"-{self.name}-1") or self.name in svc:
                                return {
                                    "installed": True,
                                    "running": c.get("State") == "running",
                                    "containers": 1,
                                    "status": c.get("State", "unknown"),
                                }
                        except json.JSONDecodeError:
                            pass

                # Also try docker ps directly as fallback
                result2 = subprocess.run(
                    ["docker", "ps", "--filter", f"name={self.name}", "--format", "json"],
                    capture_output=True, text=True, timeout=10
                )
                if result2.returncode == 0 and result2.stdout.strip():
                    return {"installed": True, "running": True, "containers": 1, "status": "running"}

                # Compose file has it but it's not running yet (may be starting or stopped)
                return {"installed": True, "running": False, "status": "stopped"}
            except Exception:
                return {"installed": True, "running": False, "status": "unknown"}

        elif per_service_compose.exists():
            # Per-service compose — check status
            try:
                result = subprocess.run(
                    ["docker", "compose", "-f", str(per_service_compose), "ps", "--format", "json"],
                    capture_output=True, text=True, timeout=10
                )
                if result.returncode == 0 and result.stdout.strip():
                    containers = []
                    for line in result.stdout.strip().splitlines():
                        try:
                            containers.append(json.loads(line))
                        except json.JSONDecodeError:
                            pass
                    running = any(c.get("State") == "running" for c in containers)
                    return {
                        "installed": True,
                        "running": running,
                        "containers": len(containers),
                        "status": "running" if running else "stopped",
                    }
                # compose file exists but no containers
                return {"installed": True, "running": False, "status": "stopped"}
            except Exception:
                return {"installed": True, "running": False, "status": "unknown"}

        # No compose file at all — not installed
        return {"installed": False, "running": False, "status": "not_installed"}

    def health_check(self) -> dict:
        """Run health check against the service endpoint."""
        health = self.catalog_entry.get("health", {})
        if not health:
            return {"healthy": None, "message": "No health check defined"}

        endpoint = health.get("endpoint", "/")
        port = self.catalog_entry.get("docker", {}).get("port", 80)
        url = f"http://127.0.0.1:{port}{endpoint}"

        try:
            import httpx
            response = httpx.get(url, timeout=5, follow_redirects=True)
            expected = health.get("expect_status", 200)
            return {
                "healthy": response.status_code == expected,
                "status_code": response.status_code,
                "url": url,
            }
        except Exception as e:
            return {"healthy": False, "error": str(e)}

    def _compose(self, *args: str) -> subprocess.CompletedProcess:
        """Run a docker compose command for this service's per-service compose."""
        compose_file = self.compose_dir / "docker-compose.yml"
        if not compose_file.exists():
            self.compose_dir.mkdir(parents=True, exist_ok=True)
            compose = self._generate_compose()
            compose_file.write_text(compose)

        return subprocess.run(
            ["docker", "compose", "-f", str(compose_file)] + list(args),
            capture_output=True, text=True, timeout=120,
        )

    def _resolve_compose(self, *args: str) -> subprocess.CompletedProcess:
        """Run a docker compose command, automatically using shared or per-service compose."""
        shared_compose = SS_DIR / "services" / "docker-compose.yml"
        if shared_compose.exists():
            return subprocess.run(
                ["docker", "compose", "-f", str(shared_compose)] + list(args),
                capture_output=True, text=True, timeout=120,
            )
        per_service_compose = self.compose_dir / "docker-compose.yml"
        if per_service_compose.exists():
            return subprocess.run(
                ["docker", "compose", "-f", str(per_service_compose)] + list(args),
                capture_output=True, text=True, timeout=120,
            )
        # Nothing installed — return a fake failure
        return subprocess.CompletedProcess(
            args=[], returncode=1, stdout="", stderr="Service not installed"
        )

    def _generate_compose(self) -> str:
        """Generate docker-compose.yml from catalog entry."""
        d = self.catalog_entry.get("docker", {})
        name = self.name
        image = d.get("image", "")
        port = d.get("port", 80)
        volumes = d.get("volumes", [])
        env = d.get("environment", {})
        restart = d.get("restart", "unless-stopped")

        compose = {
            "services": {
                name: {
                    "image": image,
                    "container_name": name,
                    "restart": restart,
                    "ports": [f"{port}:{port}"],
                }
            }
        }

        # Add environment variables if defined
        if env:
            compose["services"][name]["environment"] = env

        # Add volumes (from catalog + data dir)
        all_volumes = list(volumes) + [f"{SS_DATA}/{name}:/data"]
        compose["services"][name]["volumes"] = all_volumes

        return yaml.dump(compose, default_flow_style=False)


class SkillRegistry:
    """Load and manage skill plugins from YAML catalog."""

    def __init__(self, catalog_dir: Path):
        self.catalog_dir = catalog_dir
        self.skills: dict[str, SkillBase] = {}

    def load_all(self):
        """Load all YAML catalog entries."""
        if not self.catalog_dir.exists():
            print(f"[skills] Catalog dir not found: {self.catalog_dir}")
            return

        yaml_files = list(self.catalog_dir.glob("*.yaml")) + list(self.catalog_dir.glob("*.yml"))
        if not yaml_files:
            print(f"[skills] No YAML files found in {self.catalog_dir}")
            return

        for yaml_file in yaml_files:
            self._load_skill(yaml_file)

        print(f"[skills] Loaded {len(self.skills)} services: {', '.join(self.skills.keys())}")

    def _load_skill(self, path: Path):
        """Load a single skill from YAML."""
        try:
            entry = yaml.safe_load(path.read_text())
            if not entry or "name" not in entry:
                return

            name = entry["name"]
            skill = SkillBase(entry)
            self.skills[name] = skill
        except Exception as e:
            print(f"[skills] Error loading {path}: {e}")

    def get(self, name: str) -> SkillBase | None:
        """Get a skill by name."""
        return self.skills.get(name)

    def list_services(self) -> list[str]:
        """List all loaded service names."""
        return list(self.skills.keys())