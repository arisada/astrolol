"""Unit tests for BluetoothManager, against a fake backend (no real BlueZ/hardware)."""
from __future__ import annotations

import socket

import pytest

from astrolol.devices.bluetooth.manager import BluetoothManager
from astrolol.devices.bluetooth.store import BluetoothDeviceStore


class FakeBackend:
    def __init__(self) -> None:
        self.paired_macs: set[str] = set()
        self.opened: list[tuple[str, int]] = []
        self.fake_socket = object()
        self.fail_first_n_opens = 0

    async def scan(self, timeout: float):
        return [("AA:BB:CC:DD:EE:FF", "HC-06", -55)]

    async def pair(self, mac: str, pin: str | None):
        self.paired_macs.add(mac.upper())
        return "HC-06", 3

    async def is_paired(self, mac: str) -> bool:
        return mac.upper() in self.paired_macs

    async def forget(self, mac: str) -> None:
        self.paired_macs.discard(mac.upper())

    async def open_socket(self, mac: str, channel: int):
        self.opened.append((mac, channel))
        if len(self.opened) <= self.fail_first_n_opens:
            raise OSError("Host is down")
        return self.fake_socket


@pytest.fixture()
def backend() -> FakeBackend:
    return FakeBackend()


@pytest.fixture()
def manager(tmp_path, backend: FakeBackend) -> BluetoothManager:
    return BluetoothManager(backend=backend, store=BluetoothDeviceStore(tmp_path / "bt.json"))


async def test_pair_resolves_channel_and_persists(manager: BluetoothManager) -> None:
    device = await manager.pair("aa:bb:cc:dd:ee:ff", pin="1234")
    assert device.id == "AA:BB:CC:DD:EE:FF"
    assert device.channel == 3
    assert manager.get_paired("AA:BB:CC:DD:EE:FF") == device


async def test_scan_marks_paired_devices(manager: BluetoothManager) -> None:
    await manager.pair("AA:BB:CC:DD:EE:FF", pin="1234")
    found = await manager.scan()
    assert found[0].paired is True


def test_rename_unknown_device_raises(manager: BluetoothManager) -> None:
    with pytest.raises(KeyError):
        manager.rename("nope", "x")


async def test_forget_unknown_device_raises(manager: BluetoothManager) -> None:
    with pytest.raises(KeyError):
        await manager.forget("nope")


async def test_open_unknown_device_raises(manager: BluetoothManager) -> None:
    with pytest.raises(KeyError):
        await manager.open("nope")


async def test_open_fails_if_no_longer_paired_at_os_level(manager: BluetoothManager, backend: FakeBackend) -> None:
    await manager.pair("AA:BB:CC:DD:EE:FF", pin="1234")
    backend.paired_macs.clear()  # simulate link key lost (factory reset, wiped bluetoothd state, ...)
    with pytest.raises(ConnectionError):
        await manager.open("AA:BB:CC:DD:EE:FF")


async def test_open_does_not_attempt_pairing(manager: BluetoothManager, backend: FakeBackend) -> None:
    """A missing pairing must surface as an error, not trigger an unattended pair (no PIN source)."""
    with pytest.raises(KeyError):
        await manager.open("AA:BB:CC:DD:EE:FF")
    assert backend.opened == []


async def test_open_returns_backend_socket(manager: BluetoothManager, backend: FakeBackend) -> None:
    device = await manager.pair("AA:BB:CC:DD:EE:FF", pin="1234")
    sock = await manager.open(device.id)
    assert sock is backend.fake_socket
    assert backend.opened == [("AA:BB:CC:DD:EE:FF", 3)]


async def test_open_retries_transient_failure_then_succeeds(
    manager: BluetoothManager, backend: FakeBackend, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The ACL link can take a moment to settle right after pairing; a single
    ENETDOWN/EHOSTDOWN-style failure must not surface to the caller."""
    from astrolol.devices.bluetooth import manager as manager_module

    monkeypatch.setattr(manager_module, "OPEN_RETRY_DELAYS", (0.0, 0.0))
    device = await manager.pair("AA:BB:CC:DD:EE:FF", pin="1234")
    backend.fail_first_n_opens = 2
    sock = await manager.open(device.id)
    assert sock is backend.fake_socket
    assert len(backend.opened) == 3


async def test_open_raises_after_exhausting_retries(
    manager: BluetoothManager, backend: FakeBackend, monkeypatch: pytest.MonkeyPatch
) -> None:
    from astrolol.devices.bluetooth import manager as manager_module

    monkeypatch.setattr(manager_module, "OPEN_RETRY_DELAYS", (0.0, 0.0))
    device = await manager.pair("AA:BB:CC:DD:EE:FF", pin="1234")
    backend.fail_first_n_opens = 999
    with pytest.raises(ConnectionError):
        await manager.open(device.id)
    assert len(backend.opened) == 3


async def test_persistence_survives_new_manager_instance(tmp_path, backend: FakeBackend) -> None:
    path = tmp_path / "bt.json"
    manager1 = BluetoothManager(backend=backend, store=BluetoothDeviceStore(path))
    await manager1.pair("AA:BB:CC:DD:EE:FF", pin="1234", name="Mount link")

    manager2 = BluetoothManager(backend=backend, store=BluetoothDeviceStore(path))
    devices = manager2.list_paired()
    assert len(devices) == 1
    assert devices[0].name == "Mount link"
