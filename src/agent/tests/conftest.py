"""Test fixtures for ServerStick Pi Agent API tests."""

import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from collections import OrderedDict

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport

# Add the agent directory to path so we can import main
AGENT_DIR = Path(__file__).parent.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))


class MockSkill:
    """Mock skill for testing without real Docker."""
    def __init__(self, name: str, catalog_entry: dict | None = None):
        self.name = name
        self.catalog_entry = catalog_entry or {
            "name": name,
            "display": name.replace("-", " ").title(),
            "replaces": "cloud-service",
            "icon": "📦",
            "category": "system",
            "description": f"Test service {name}",
            "docker": {"image": f"test/{name}:latest", "port": 8080},
        }
        self._installed = False
        self._running = False

    def get_status(self) -> dict:
        return {
            "installed": self._installed,
            "running": self._running,
            "status": "running" if self._running else ("stopped" if self._installed else "not_installed"),
        }

    def health_check(self) -> dict:
        if self._running:
            return {"healthy": True, "message": "OK"}
        return {"healthy": None, "message": "Not running"}

    def install(self) -> dict:
        self._installed = True
        self._running = True
        return {"success": True, "output": f"Installed {self.name}"}

    def uninstall(self) -> dict:
        self._installed = False
        self._running = False
        return {"success": True, "output": f"Uninstalled {self.name}"}

    def start(self) -> dict:
        if self._installed:
            self._running = True
            return {"success": True, "output": f"Started {self.name}"}
        return {"success": False, "output": "Not installed"}

    def stop(self) -> dict:
        self._running = False
        return {"success": True, "output": f"Stopped {self.name}"}

    def restart(self) -> dict:
        if self._installed:
            self._running = True
            return {"success": True, "output": f"Restarted {self.name}"}
        return {"success": False, "output": "Not installed"}


def make_mock_registry():
    """Create a mock SkillRegistry with a few test services."""
    skills = OrderedDict()
    for name in ["stirling-pdf", "homepage", "uptime-kuma", "privatebin"]:
        skills[name] = MockSkill(name)
    # Mark one as installed+running for testing
    skills["homepage"]._installed = True
    skills["homepage"]._running = True

    registry = MagicMock()
    registry.skills = skills
    registry.get = lambda n: skills.get(n)
    registry.load_all = MagicMock()
    return registry


@pytest.fixture
def mock_registry():
    return make_mock_registry()


@pytest.fixture
def mock_subprocess():
    """Patch subprocess.run to avoid real system calls."""
    with patch("main.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="",
            stderr="",
        )
        yield mock_run


@pytest.fixture
def mock_check_output():
    """Patch subprocess.check_output for hardware/network endpoints."""
    outputs = {
        "lscpu": "Architecture: x86_64\nModel name: Test CPU\nCPU(s): 4\n",
        "free": "              total        used        free      shared  buff/cache   available\nMem:           7982        4096        2048         256        1838        3630\nSwap:          2048           0        2048\n",
        "hostname": "teststick\n",
        "hostname -I": "192.168.1.100 172.17.0.1 \n",
    }

    def _check_output(cmd, **kwargs):
        cmd_str = str(cmd)
        if "lscpu" in cmd_str:
            return outputs["lscpu"]
        elif "-I" in cmd_str:
            return outputs["hostname -I"]
        elif "hostname" in cmd_str:
            return outputs["hostname"]
        elif "free" in cmd_str:
            return outputs["free"]
        return ""

    with patch("main.subprocess.check_output", side_effect=_check_output) as mock:
        yield mock


@pytest_asyncio.fixture
async def client(mock_registry, tmp_path):
    """Create an async test client with mocked dependencies."""
    with patch("main.skill_registry", mock_registry), \
         patch("main.SS_DIR", tmp_path / "etc"), \
         patch("main.SS_DATA", tmp_path / "data"), \
         patch("main.COMPOSE_FILE", tmp_path / "etc" / "services" / "docker-compose.yml"), \
         patch("main.BACKUP_DIR", tmp_path / "data" / "backups"), \
         patch("main.PROVISIONED_FILE", tmp_path / "etc" / "provisioned"), \
         patch("main.provisioned", False), \
         patch("main.device_name", ""), \
         patch("main.DASHBOARD_DIR", tmp_path / "nonexistent"):

        # Create needed dirs
        (tmp_path / "data" / "backups").mkdir(parents=True, exist_ok=True)
        (tmp_path / "etc" / "services").mkdir(parents=True, exist_ok=True)

        from main import app
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac
