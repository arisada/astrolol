"""Tests for the bluetooth_serial plugin API, against a fake BluetoothBackend
(no real BlueZ/hardware required — same pattern as FakeCamera/FakeMount)."""
from __future__ import annotations

import socket

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from astrolol.devices.bluetooth.backend import BlueZUnavailableError
from astrolol.devices.bluetooth.manager import BluetoothManager
from astrolol.devices.bluetooth.store import BluetoothDeviceStore
from plugins.bluetooth_serial.api import router


class FakeBackend:
    def __init__(self) -> None:
        self.scan_results: list[tuple[str, str, int | None]] = [("AA:BB:CC:DD:EE:FF", "HC-06", -60)]
        self.paired_macs: set[str] = set()
        self.channel = 1
        self.fail_pairing = False
        self.unavailable = False

    async def scan(self, timeout: float) -> list[tuple[str, str, int | None]]:
        if self.unavailable:
            raise BlueZUnavailableError("no bluetoothd")
        return self.scan_results

    async def pair(self, mac: str, pin: str | None) -> tuple[str, int]:
        if self.fail_pairing:
            raise RuntimeError("pairing rejected by device")
        self.paired_macs.add(mac.upper())
        return "HC-06", self.channel

    async def is_paired(self, mac: str) -> bool:
        return mac.upper() in self.paired_macs

    async def forget(self, mac: str) -> None:
        self.paired_macs.discard(mac.upper())

    async def open_socket(self, mac: str, channel: int) -> socket.socket:
        raise NotImplementedError  # not exercised via this plugin's API


@pytest.fixture()
def backend(tmp_path) -> FakeBackend:
    return FakeBackend()


@pytest.fixture()
def client(tmp_path, backend: FakeBackend) -> TestClient:
    app = FastAPI()
    app.state.bluetooth_manager = BluetoothManager(
        backend=backend, store=BluetoothDeviceStore(tmp_path / "bluetooth_devices.json")
    )
    app.include_router(router)
    return TestClient(app)


def test_scan_returns_discovered_devices(client: TestClient) -> None:
    r = client.get("/plugins/bluetooth_serial/scan")
    assert r.status_code == 200
    devices = r.json()
    assert devices == [{"mac": "AA:BB:CC:DD:EE:FF", "name": "HC-06", "rssi": -60, "paired": False}]


def test_scan_marks_already_paired_devices(client: TestClient) -> None:
    client.post("/plugins/bluetooth_serial/pair", json={"mac": "AA:BB:CC:DD:EE:FF", "pin": "1234"})
    r = client.get("/plugins/bluetooth_serial/scan")
    assert r.json()[0]["paired"] is True


def test_scan_unavailable_backend_returns_503(client: TestClient, backend: FakeBackend) -> None:
    backend.unavailable = True
    r = client.get("/plugins/bluetooth_serial/scan")
    assert r.status_code == 503


def test_pair_persists_device_with_resolved_channel(client: TestClient) -> None:
    r = client.post("/plugins/bluetooth_serial/pair", json={"mac": "aa:bb:cc:dd:ee:ff", "pin": "1234"})
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == "AA:BB:CC:DD:EE:FF"
    assert body["name"] == "HC-06"
    assert body["channel"] == 1


def test_pair_with_custom_name(client: TestClient) -> None:
    r = client.post(
        "/plugins/bluetooth_serial/pair",
        json={"mac": "AA:BB:CC:DD:EE:FF", "pin": "1234", "name": "Mount link"},
    )
    assert r.json()["name"] == "Mount link"


def test_pair_failure_returns_400(client: TestClient, backend: FakeBackend) -> None:
    backend.fail_pairing = True
    r = client.post("/plugins/bluetooth_serial/pair", json={"mac": "AA:BB:CC:DD:EE:FF"})
    assert r.status_code == 400


def test_rename_paired_device(client: TestClient) -> None:
    client.post("/plugins/bluetooth_serial/pair", json={"mac": "AA:BB:CC:DD:EE:FF", "pin": "1234"})
    r = client.patch("/plugins/bluetooth_serial/paired/AA:BB:CC:DD:EE:FF", json={"name": "EQMOD link"})
    assert r.status_code == 200
    assert r.json()["name"] == "EQMOD link"


def test_rename_unknown_device_returns_404(client: TestClient) -> None:
    r = client.patch("/plugins/bluetooth_serial/paired/NOPE", json={"name": "x"})
    assert r.status_code == 404


def test_forget_removes_device(client: TestClient, backend: FakeBackend) -> None:
    client.post("/plugins/bluetooth_serial/pair", json={"mac": "AA:BB:CC:DD:EE:FF", "pin": "1234"})
    r = client.delete("/plugins/bluetooth_serial/paired/AA:BB:CC:DD:EE:FF")
    assert r.status_code == 204
    assert "AA:BB:CC:DD:EE:FF" not in backend.paired_macs


def test_forget_unknown_device_returns_404(client: TestClient) -> None:
    r = client.delete("/plugins/bluetooth_serial/paired/NOPE")
    assert r.status_code == 404


def test_plugin_manifest_fields() -> None:
    from plugins.bluetooth_serial.plugin import get_plugin

    plugin = get_plugin()
    assert plugin.manifest.id == "bluetooth_serial"
    assert plugin.manifest.hot_reloadable is True
