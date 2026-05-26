"""Comprehensive API tests for ServerStick Pi Agent."""

import json
import tarfile
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock


# ─── Status & Services ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_status(client):
    """GET /api/status returns correct structure."""
    resp = await client.get("/api/status")
    assert resp.status_code == 200
    data = resp.json()
    assert "device_name" in data
    assert "provisioned" in data
    assert "services" in data
    assert "tunnel" in data
    assert isinstance(data["services"], dict)


@pytest.mark.asyncio
async def test_list_services(client):
    """GET /api/services returns catalog entries."""
    resp = await client.get("/api/services")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) >= 3  # At least our mock services
    assert "stirling-pdf" in data
    assert "homepage" in data


@pytest.mark.asyncio
async def test_get_service_detail(client):
    """GET /api/services/{name} returns details + status."""
    resp = await client.get("/api/services/stirling-pdf")
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "stirling-pdf"
    assert "status" in data
    assert "docker" in data


@pytest.mark.asyncio
async def test_get_service_not_found(client):
    """GET /api/services/{name} returns 404 for unknown service."""
    resp = await client.get("/api/services/nonexistent")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_service_action_start(client):
    """POST /api/services/{name}/start starts a service."""
    resp = await client.post("/api/services/stirling-pdf/start")
    assert resp.status_code == 200
    data = resp.json()
    assert data["service"] == "stirling-pdf"
    assert data["action"] == "start"


@pytest.mark.asyncio
async def test_service_action_invalid(client):
    """POST /api/services/{name}/{bad_action} returns 400."""
    resp = await client.post("/api/services/stirling-pdf/explode")
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_service_action_not_found(client):
    """POST /api/services/{unknown}/{action} returns 404."""
    resp = await client.post("/api/services/nonexistent/start")
    assert resp.status_code == 404


# ─── Health Checks ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_health_check_all(client):
    """GET /api/health returns health for all services."""
    resp = await client.get("/api/health")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, dict)
    # Homepage is running in our mock, should have health
    assert "homepage" in data


@pytest.mark.asyncio
async def test_health_check_single(client):
    """GET /api/services/{name}/health returns health for one service."""
    resp = await client.get("/api/services/homepage/health")
    assert resp.status_code == 200
    data = resp.json()
    assert "healthy" in data


@pytest.mark.asyncio
async def test_health_check_not_found(client):
    """GET /api/services/{unknown}/health returns 404."""
    resp = await client.get("/api/services/nonexistent/health")
    assert resp.status_code == 404


# ─── Resource Monitoring ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_resources(client, mock_subprocess):
    """GET /api/resources returns CPU/RAM/disk info."""
    # Mock /proc/stat reads
    stat_content = "cpu  100 0 100 800 0 0 0 0 0 0\n"
    with patch("builtins.open", MagicMock(return_value=iter([stat_content, stat_content]))):
        resp = await client.get("/api/resources")
    assert resp.status_code == 200
    data = resp.json()
    assert "cpu" in data
    assert "ram" in data or "disks" in data


# ─── Service Logs ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_service_logs(client, mock_subprocess):
    """GET /api/services/{name}/logs returns log output."""
    mock_subprocess.return_value = MagicMock(
        returncode=0, stdout="Log line 1\nLog line 2\n", stderr=""
    )
    resp = await client.get("/api/services/stirling-pdf/logs")
    assert resp.status_code == 200
    data = resp.json()
    assert "logs" in data
    assert data["service"] == "stirling-pdf"


@pytest.mark.asyncio
async def test_get_service_logs_not_found(client):
    """GET /api/services/{unknown}/logs returns 404."""
    resp = await client.get("/api/services/nonexistent/logs")
    assert resp.status_code == 404


# ─── Backup / Restore ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_backup(client, tmp_path):
    """POST /api/backup/{name} creates a tar.gz backup."""
    # Create a data directory for the service
    data_dir = tmp_path / "data" / "stirling-pdf"
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "test.txt").write_text("hello")

    resp = await client.post("/api/backup/stirling-pdf")
    assert resp.status_code == 200
    data = resp.json()
    assert data["service"] == "stirling-pdf"
    assert "backup_file" in data
    assert data["backup_file"].endswith(".tar.gz")


@pytest.mark.asyncio
async def test_list_backups(client, tmp_path):
    """GET /api/backups lists backup files."""
    backup_dir = tmp_path / "data" / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)

    # Create a test backup file
    (backup_dir / "stirling-pdf_20250101_000000.tar.gz").write_bytes(b"\x1f\x8b\x00\x00")

    resp = await client.get("/api/backups")
    assert resp.status_code == 200
    data = resp.json()
    assert "backups" in data
    assert len(data["backups"]) >= 1


@pytest.mark.asyncio
async def test_backup_not_found_service(client):
    """POST /api/backup/{unknown} returns 404."""
    resp = await client.post("/api/backup/nonexistent")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_delete_backup(client, tmp_path):
    """DELETE /api/backup/{file} deletes a backup."""
    backup_dir = tmp_path / "data" / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    test_file = backup_dir / "test_20250101.tar.gz"
    test_file.write_bytes(b"\x1f\x8b\x00\x00")

    resp = await client.delete("/api/backup/test_20250101.tar.gz")
    assert resp.status_code == 200
    assert not test_file.exists()


@pytest.mark.asyncio
async def test_delete_backup_not_found(client):
    """DELETE /api/backup/{missing} returns 404."""
    resp = await client.delete("/api/backup/nonexistent.tar.gz")
    assert resp.status_code == 404


# ─── Update ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_update_service(client, mock_subprocess):
    """POST /api/services/{name}/update pulls new image."""
    mock_subprocess.return_value = MagicMock(returncode=0, stdout="Pulled latest", stderr="")
    resp = await client.post("/api/services/stirling-pdf/update")
    assert resp.status_code == 200
    data = resp.json()
    assert data["service"] == "stirling-pdf"


@pytest.mark.asyncio
async def test_update_service_not_found(client):
    """POST /api/services/{unknown}/update returns 404."""
    resp = await client.post("/api/services/nonexistent/update")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_update_all_services(client, mock_subprocess):
    """POST /api/update-all updates running services."""
    mock_subprocess.return_value = MagicMock(returncode=0, stdout="Pulled", stderr="")
    resp = await client.post("/api/update-all")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, dict)


# ─── Network Info ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_network(client, mock_subprocess, mock_check_output):
    """GET /api/network returns network info."""
    resp = await client.get("/api/network")
    assert resp.status_code == 200
    data = resp.json()
    assert "hostname" in data
    assert "ips" in data
    assert "wifi_ssid" in data


# ─── Catalog ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_catalog(client):
    """GET /api/catalog returns services grouped by category."""
    resp = await client.get("/api/catalog")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, dict)
    # At least one category should exist
    assert len(data) > 0


# ─── Hardware ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_hardware(client, mock_subprocess, mock_check_output):
    """GET /api/hardware returns hardware info."""
    resp = await client.get("/api/hardware")
    assert resp.status_code == 200
    data = resp.json()
    assert "cpu" in data or "cpu_cores" in data


# ─── Tunnel ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_tunnel(client, mock_subprocess):
    """GET /api/tunnel returns tunnel status."""
    resp = await client.get("/api/tunnel")
    assert resp.status_code == 200
    data = resp.json()
    assert "active" in data
    assert "configured" in data


# ─── Setup Validation ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_setup_invalid_name(client):
    """POST /api/setup rejects invalid device names."""
    resp = await client.post("/api/setup", json={
        "device_name": "BAD NAME!",
        "services": ["stirling-pdf"],
    })
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_setup_too_long_name(client):
    """POST /api/setup rejects device names > 20 chars."""
    resp = await client.post("/api/setup", json={
        "device_name": "a" * 21,
        "services": ["stirling-pdf"],
    })
    assert resp.status_code == 400
