"""Tests for the system management plugin."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from astrolol.core.plugin_api import PluginContext
from plugins.system.models import (
    NetworkMode,
    NetworkStatus,
    SystemSettings,
    SystemStatus,
    WifiNetwork,
)
from plugins.system.plugin import SystemPlugin, get_plugin


# ── App factory ────────────────────────────────────────────────────────────────

def _make_app() -> FastAPI:
    app = FastAPI()
    profile_store = MagicMock()
    profile_store.get_user_settings.return_value = MagicMock(plugin_settings={})
    app.state.profile_store = profile_store

    ctx = PluginContext(
        event_bus=None,
        device_manager=None,
        device_registry=None,
        profile_store=profile_store,
    )
    plugin = SystemPlugin()
    plugin.setup(app, ctx)
    return app


@pytest.fixture
def client() -> TestClient:
    return TestClient(_make_app())


# ── System status ──────────────────────────────────────────────────────────────

def test_system_status_returns_200(client: TestClient) -> None:
    fake = SystemStatus(
        cpu_percent=12.5,
        memory_percent=45.0,
        memory_used_mb=1800.0,
        memory_total_mb=4000.0,
        disk_percent=30.0,
        disk_used_gb=8.0,
        disk_total_gb=32.0,
        temperature_celsius=42.3,
        uptime_seconds=3600.0,
        hostname="astrolol",
        platform="aarch64",
    )
    with patch("plugins.system.api._si.get_system_status", AsyncMock(return_value=fake)):
        r = client.get("/plugins/system/status")
    assert r.status_code == 200
    data = r.json()
    assert data["cpu_percent"] == 12.5
    assert data["hostname"] == "astrolol"
    assert data["temperature_celsius"] == 42.3


def test_system_status_no_temperature(client: TestClient) -> None:
    fake = SystemStatus(
        cpu_percent=5.0,
        memory_percent=20.0,
        memory_used_mb=800.0,
        memory_total_mb=4000.0,
        disk_percent=15.0,
        disk_used_gb=5.0,
        disk_total_gb=32.0,
        temperature_celsius=None,
        uptime_seconds=100.0,
        hostname="test",
        platform="x86_64",
    )
    with patch("plugins.system.api._si.get_system_status", AsyncMock(return_value=fake)):
        r = client.get("/plugins/system/status")
    assert r.status_code == 200
    assert r.json()["temperature_celsius"] is None


# ── Network status ─────────────────────────────────────────────────────────────

def test_network_status_wifi(client: TestClient) -> None:
    fake = NetworkStatus(
        mode=NetworkMode.wifi,
        interface="wlan0",
        ssid="MyNetwork",
        ip_address="192.168.1.100",
        gateway="192.168.1.1",
        hotspot_ssid=None,
        hotspot_ip=None,
        nmcli_available=True,
    )
    with patch("plugins.system.api._net.get_network_status", AsyncMock(return_value=fake)):
        r = client.get("/plugins/system/network")
    assert r.status_code == 200
    data = r.json()
    assert data["mode"] == "wifi"
    assert data["ssid"] == "MyNetwork"
    assert data["ip_address"] == "192.168.1.100"


def test_network_status_hotspot(client: TestClient) -> None:
    fake = NetworkStatus(
        mode=NetworkMode.hotspot,
        interface="wlan0",
        ssid=None,
        ip_address=None,
        gateway=None,
        hotspot_ssid="AstroLOL",
        hotspot_ip="192.168.50.1",
        nmcli_available=True,
    )
    with patch("plugins.system.api._net.get_network_status", AsyncMock(return_value=fake)):
        r = client.get("/plugins/system/network")
    assert r.status_code == 200
    data = r.json()
    assert data["mode"] == "hotspot"
    assert data["hotspot_ssid"] == "AstroLOL"


def test_network_status_no_nmcli(client: TestClient) -> None:
    fake = NetworkStatus(
        mode=NetworkMode.unknown,
        interface=None,
        ssid=None,
        ip_address=None,
        gateway=None,
        hotspot_ssid=None,
        hotspot_ip=None,
        nmcli_available=False,
    )
    with patch("plugins.system.api._net.get_network_status", AsyncMock(return_value=fake)):
        r = client.get("/plugins/system/network")
    assert r.status_code == 200
    assert r.json()["nmcli_available"] is False


# ── WiFi scan ──────────────────────────────────────────────────────────────────

def test_wifi_scan_returns_list(client: TestClient) -> None:
    fake_networks = [
        WifiNetwork(ssid="HomeNet", bssid="AA:BB:CC:DD:EE:FF", signal=80, security="WPA2", in_use=True),
        WifiNetwork(ssid="Neighbour", bssid="11:22:33:44:55:66", signal=40, security="WPA2", in_use=False),
    ]
    with patch("plugins.system.api._net.scan_wifi", AsyncMock(return_value=fake_networks)):
        r = client.get("/plugins/system/network/scan")
    assert r.status_code == 200
    data = r.json()
    assert len(data) == 2
    assert data[0]["ssid"] == "HomeNet"
    assert data[0]["in_use"] is True


def test_wifi_scan_empty(client: TestClient) -> None:
    with patch("plugins.system.api._net.scan_wifi", AsyncMock(return_value=[])):
        r = client.get("/plugins/system/network/scan")
    assert r.status_code == 200
    assert r.json() == []


# ── WiFi connect ───────────────────────────────────────────────────────────────

def test_wifi_connect_success(client: TestClient) -> None:
    with patch("plugins.system.api._net.connect_wifi", AsyncMock()):
        r = client.post("/plugins/system/network/connect", json={"ssid": "MyNet", "password": "secret123"})
    assert r.status_code == 200
    assert r.json()["status"] == "connected"
    assert r.json()["ssid"] == "MyNet"


def test_wifi_connect_failure(client: TestClient) -> None:
    with patch("plugins.system.api._net.connect_wifi", AsyncMock(side_effect=RuntimeError("Wrong password"))):
        r = client.post("/plugins/system/network/connect", json={"ssid": "MyNet", "password": "wrong"})
    assert r.status_code == 500
    assert "Wrong password" in r.json()["detail"]


# ── Hotspot ────────────────────────────────────────────────────────────────────

def test_hotspot_start_success(client: TestClient) -> None:
    with patch("plugins.system.api._net.start_hotspot", AsyncMock()):
        r = client.post(
            "/plugins/system/network/hotspot/start",
            json={"ssid": "AstroNet", "password": "astronomy123"},
        )
    assert r.status_code == 200
    assert r.json()["status"] == "hotspot_active"
    assert r.json()["ssid"] == "AstroNet"


def test_hotspot_start_short_password(client: TestClient) -> None:
    with patch("plugins.system.api._net.start_hotspot", AsyncMock()):
        r = client.post(
            "/plugins/system/network/hotspot/start",
            json={"ssid": "AstroNet", "password": "short"},
        )
    assert r.status_code == 400


def test_hotspot_stop_success(client: TestClient) -> None:
    with patch("plugins.system.api._net.stop_hotspot", AsyncMock()):
        r = client.post("/plugins/system/network/hotspot/stop")
    assert r.status_code == 200
    assert r.json()["status"] == "hotspot_stopped"


def test_hotspot_stop_failure(client: TestClient) -> None:
    with patch("plugins.system.api._net.stop_hotspot", AsyncMock(side_effect=RuntimeError("Not running"))):
        r = client.post("/plugins/system/network/hotspot/stop")
    assert r.status_code == 500


# ── Settings ───────────────────────────────────────────────────────────────────

def test_get_settings_defaults(client: TestClient) -> None:
    r = client.get("/plugins/system/settings")
    assert r.status_code == 200
    data = r.json()
    assert data["hotspot_ssid"] == "AstroLOL"
    assert data["hotspot_password"] == "astronomy123"
    assert data["hotspot_interface"] == "wlan0"


def test_put_settings(client: TestClient) -> None:
    payload = {"hotspot_ssid": "MyScope", "hotspot_password": "telescope1", "hotspot_interface": "wlan1"}
    r = client.put("/plugins/system/settings", json=payload)
    assert r.status_code == 200
    data = r.json()
    assert data["hotspot_ssid"] == "MyScope"


# ── Sudo setup ─────────────────────────────────────────────────────────────────

def test_sudo_setup_endpoint(client: TestClient) -> None:
    fake_perms = {"nmcli": True, "reboot": False, "shutdown": False}
    with patch("plugins.system.api._net.check_sudo_permissions", AsyncMock(return_value=fake_perms)):
        r = client.get("/plugins/system/sudo")
    assert r.status_code == 200
    data = r.json()
    assert data["nmcli_sudo_ok"] is True
    assert data["reboot_sudo_ok"] is False
    assert len(data["setup_commands"]) > 0


# ── Power controls ─────────────────────────────────────────────────────────────

def test_restart_returns_202(client: TestClient) -> None:
    # We can't actually restart in tests — just verify the endpoint responds
    with patch("plugins.system.api.os.execv"):
        r = client.post("/plugins/system/restart")
    assert r.status_code == 202
    assert r.json()["status"] == "restarting"


def test_reboot_returns_202(client: TestClient) -> None:
    with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=MagicMock(wait=AsyncMock()))):
        r = client.post("/plugins/system/reboot")
    assert r.status_code == 202
    assert r.json()["status"] == "rebooting"


def test_shutdown_returns_202(client: TestClient) -> None:
    with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=MagicMock(wait=AsyncMock()))):
        r = client.post("/plugins/system/shutdown")
    assert r.status_code == 202
    assert r.json()["status"] == "shutting_down"


# ── Storage ────────────────────────────────────────────────────────────────────

def test_storage_returns_list(client: TestClient) -> None:
    from plugins.system.models import StorageDisk
    fake = [
        StorageDisk(device="/dev/sda1", mountpoint="/", filesystem="ext4",
                    total_gb=32.0, used_gb=8.0, free_gb=24.0, percent=25.0, removable=False),
        StorageDisk(device="/dev/sdb1", mountpoint="/media/usb", filesystem="vfat",
                    total_gb=128.0, used_gb=64.0, free_gb=64.0, percent=50.0, removable=True),
    ]
    with patch("plugins.system.api._si.get_storage_disks", AsyncMock(return_value=fake)):
        r = client.get("/plugins/system/storage")
    assert r.status_code == 200
    data = r.json()
    assert len(data) == 2
    assert data[0]["mountpoint"] == "/"
    assert data[1]["removable"] is True


# ── Time / Timezone ─────────────────────────────────────────────────────────────

def test_get_time_info(client: TestClient) -> None:
    from plugins.system.models import TimeInfo
    fake = TimeInfo(
        datetime_local="2026-05-11T22:00:00+02:00",
        datetime_utc="2026-05-11T20:00:00+00:00",
        timezone="Europe/Brussels",
        ntp_synced=True,
        ntp_service_active=True,
        rtc_time=None,
    )
    with patch("plugins.system.api._si.get_time_info", AsyncMock(return_value=fake)):
        r = client.get("/plugins/system/time")
    assert r.status_code == 200
    assert r.json()["timezone"] == "Europe/Brussels"
    assert r.json()["ntp_synced"] is True


def test_list_timezones(client: TestClient) -> None:
    fake_tzs = ["UTC", "Europe/Brussels", "America/New_York"]
    with patch("plugins.system.api._si.get_available_timezones", AsyncMock(return_value=fake_tzs)):
        r = client.get("/plugins/system/time/timezones")
    assert r.status_code == 200
    assert "Europe/Brussels" in r.json()


def test_set_timezone_success(client: TestClient) -> None:
    with patch("plugins.system.api._si.set_timezone", AsyncMock()):
        r = client.put("/plugins/system/time/timezone", json={"timezone": "Europe/Paris"})
    assert r.status_code == 200
    assert r.json()["timezone"] == "Europe/Paris"


def test_set_timezone_empty_rejected(client: TestClient) -> None:
    with patch("plugins.system.api._si.set_timezone", AsyncMock()):
        r = client.put("/plugins/system/time/timezone", json={"timezone": ""})
    assert r.status_code == 400


def test_set_timezone_failure(client: TestClient) -> None:
    with patch("plugins.system.api._si.set_timezone", AsyncMock(side_effect=RuntimeError("Invalid timezone"))):
        r = client.put("/plugins/system/time/timezone", json={"timezone": "Invalid/Zone"})
    assert r.status_code == 500


# ── Hostname ────────────────────────────────────────────────────────────────────

def test_get_hostname(client: TestClient) -> None:
    from plugins.system.models import HostnameInfo
    fake = HostnameInfo(hostname="astrolol-pi", fqdn=None)
    with patch("plugins.system.api._si.get_hostname_info", AsyncMock(return_value=fake)):
        r = client.get("/plugins/system/hostname")
    assert r.status_code == 200
    assert r.json()["hostname"] == "astrolol-pi"


def test_set_hostname_success(client: TestClient) -> None:
    from plugins.system.models import HostnameInfo
    updated = HostnameInfo(hostname="my-astrolol", fqdn=None)
    with patch("plugins.system.api._si.set_hostname", AsyncMock()):
        with patch("plugins.system.api._si.get_hostname_info", AsyncMock(return_value=updated)):
            r = client.put("/plugins/system/hostname", json={"hostname": "my-astrolol"})
    assert r.status_code == 200
    assert r.json()["hostname"] == "my-astrolol"


def test_set_hostname_invalid_chars(client: TestClient) -> None:
    r = client.put("/plugins/system/hostname", json={"hostname": "my hostname!"})
    assert r.status_code == 400


def test_set_hostname_leading_hyphen(client: TestClient) -> None:
    r = client.put("/plugins/system/hostname", json={"hostname": "-badname"})
    assert r.status_code == 400


def test_set_hostname_empty_rejected(client: TestClient) -> None:
    r = client.put("/plugins/system/hostname", json={"hostname": ""})
    assert r.status_code == 422


# ── USB devices ────────────────────────────────────────────────────────────────

def test_usb_devices_returns_list(client: TestClient) -> None:
    from plugins.system.models import UsbDevice
    fake = [
        UsbDevice(bus="001", device="002", vendor_id="03c3", product_id="120c",
                  name="ZWO ASI294MC Pro"),
        UsbDevice(bus="001", device="003", vendor_id="067b", product_id="2303",
                  name="Prolific Technology, Inc. PL2303 Serial Port"),
    ]
    with patch("plugins.system.api._si.get_usb_devices", AsyncMock(return_value=fake)):
        r = client.get("/plugins/system/usb")
    assert r.status_code == 200
    data = r.json()
    assert len(data) == 2
    assert data[0]["name"] == "ZWO ASI294MC Pro"


def test_usb_devices_empty(client: TestClient) -> None:
    with patch("plugins.system.api._si.get_usb_devices", AsyncMock(return_value=[])):
        r = client.get("/plugins/system/usb")
    assert r.status_code == 200
    assert r.json() == []


# ── Saved WiFi connections ─────────────────────────────────────────────────────

def test_list_saved_connections(client: TestClient) -> None:
    from plugins.system.models import SavedWifiConnection
    fake = [
        SavedWifiConnection(name="HomeNet", interface="wlan0", autoconnect=True),
        SavedWifiConnection(name="Observatory", interface=None, autoconnect=False),
    ]
    with patch("plugins.system.api._net.list_saved_wifi_connections", AsyncMock(return_value=fake)):
        r = client.get("/plugins/system/network/saved")
    assert r.status_code == 200
    data = r.json()
    assert len(data) == 2
    assert data[0]["name"] == "HomeNet"
    assert data[0]["autoconnect"] is True


def test_delete_saved_connection_success(client: TestClient) -> None:
    with patch("plugins.system.api._net.delete_saved_connection", AsyncMock()):
        r = client.delete("/plugins/system/network/saved/HomeNet")
    assert r.status_code == 204


def test_delete_saved_connection_failure(client: TestClient) -> None:
    with patch("plugins.system.api._net.delete_saved_connection",
               AsyncMock(side_effect=RuntimeError("Not found"))):
        r = client.delete("/plugins/system/network/saved/NoSuchNetwork")
    assert r.status_code == 500


# ── Plugin manifest ────────────────────────────────────────────────────────────

def test_plugin_manifest() -> None:
    plugin = get_plugin()
    assert plugin.manifest.id == "system"
    assert plugin.manifest.name == "System"
    assert plugin.manifest.nav_order == 90


def test_plugin_protocol() -> None:
    from astrolol.core.plugin_api import Plugin
    plugin = get_plugin()
    assert isinstance(plugin, Plugin)
