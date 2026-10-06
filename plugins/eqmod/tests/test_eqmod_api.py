"""Tests for the EQMOD plugin's registration and settings API."""
from __future__ import annotations

import asyncio

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from astrolol.core.events import EventBus
from astrolol.core.plugin_api import Plugin, PluginContext
from astrolol.devices.config import DeviceConfig
from astrolol.devices.manager import DeviceManager
from astrolol.devices.registry import DeviceRegistry
from astrolol.profiles.store import ProfileStore
from plugins.eqmod.plugin import EqmodPlugin, get_plugin
from plugins.eqmod.simulator import EqmodSimMount


@pytest.fixture(autouse=True)
def _isolated_state_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("ASTROLOL_DATA_DIR", str(tmp_path))


def _make_app(tmp_path) -> tuple[FastAPI, DeviceManager]:
    app = FastAPI()
    registry = DeviceRegistry()
    event_bus = EventBus()
    device_manager = DeviceManager(registry=registry, event_bus=event_bus)
    profile_store = ProfileStore(tmp_path / "profiles.json")

    app.state.device_manager = device_manager
    app.state.profile_store = profile_store

    ctx = PluginContext(
        event_bus=event_bus,
        device_manager=device_manager,
        device_registry=registry,
        profile_store=profile_store,
    )
    EqmodPlugin().setup(app, ctx)
    return app, device_manager


@pytest.fixture()
def client(tmp_path) -> TestClient:
    app, _ = _make_app(tmp_path)
    return TestClient(app)


# --- Manifest / registration ---

def test_plugin_manifest_fields() -> None:
    plugin = get_plugin()
    assert plugin.manifest.id == "eqmod"
    assert plugin.manifest.name == "EQMOD Mount"


def test_get_plugin_returns_plugin_protocol() -> None:
    assert isinstance(get_plugin(), Plugin)


def test_setup_registers_eqmod_sim_adapter(tmp_path) -> None:
    registry = DeviceRegistry()
    event_bus = EventBus()
    ctx = PluginContext(
        event_bus=event_bus,
        device_manager=DeviceManager(registry=registry, event_bus=event_bus),
        device_registry=registry,
    )
    EqmodPlugin().setup(FastAPI(), ctx)
    assert registry.mounts["eqmod_sim"] is EqmodSimMount


# --- Settings API ---

def test_settings_default(client: TestClient) -> None:
    r = client.get("/plugins/eqmod/settings")
    assert r.status_code == 200
    assert r.json() == {"led_brightness": 50, "indi_proxy_enabled": False,
                        "indi_proxy_api_url": "http://127.0.0.1:8000"}


def test_settings_roundtrip(client: TestClient) -> None:
    r = client.put("/plugins/eqmod/settings", json={"led_brightness": 10})
    assert r.status_code == 200
    assert r.json()["led_brightness"] == 10
    assert client.get("/plugins/eqmod/settings").json()["led_brightness"] == 10


def test_settings_rejects_out_of_range(client: TestClient) -> None:
    r = client.put("/plugins/eqmod/settings", json={"led_brightness": 999})
    assert r.status_code == 422


def test_settings_apply_live_to_connected_mount(tmp_path) -> None:
    app, device_manager = _make_app(tmp_path)
    client = TestClient(app)

    asyncio.run(device_manager.connect(
        DeviceConfig(device_id="m1", kind="mount", adapter_key="eqmod_sim")
    ))

    r = client.put("/plugins/eqmod/settings", json={"led_brightness": 77})
    assert r.status_code == 200

    mount = device_manager.get_mount("m1")
    assert mount.get_led_brightness() == 77


def test_setup_registers_real_eqmod_adapter() -> None:
    from plugins.eqmod.mount import EqmodMount

    registry = DeviceRegistry()
    event_bus = EventBus()
    ctx = PluginContext(
        event_bus=event_bus,
        device_manager=DeviceManager(registry=registry, event_bus=event_bus),
        device_registry=registry,
    )
    EqmodPlugin().setup(FastAPI(), ctx)
    # Registered as a factory (not the class directly) so a BluetoothManager can be
    # injected without eqmod importing the bluetooth_serial plugin — see plugin.py.
    assert isinstance(registry.mounts["eqmod"](port="/dev/fake"), EqmodMount)
    assert registry.default_connect_params("mount", "eqmod") == {"port": "/dev/ttyUSB0"}
    assert registry.default_connect_params("mount", "eqmod_sim") == {"state_key": "default"}


def test_diagnostics_reports_connected_real_mounts_only(tmp_path) -> None:
    from plugins.eqmod.mount import EqmodMount
    from plugins.eqmod.tests.test_mount import CPR, _FakeController

    app, device_manager = _make_app(tmp_path)
    controller = _FakeController()
    device_manager.registry.register_mount(
        "eqmod_fake",
        lambda **params: EqmodMount(transport_factory=lambda port, baud: controller, **params),
    )
    client = TestClient(app)

    # The simulator has no controller to read, so it is not listed.
    asyncio.run(device_manager.connect(
        DeviceConfig(device_id="sim1", kind="mount", adapter_key="eqmod_sim")
    ))
    assert client.get("/plugins/eqmod/diagnostics").json() == []

    # Mounts are a singleton kind: connecting the real one evicts the simulator.
    asyncio.run(device_manager.connect(DeviceConfig(
        device_id="real1", kind="mount", adapter_key="eqmod_fake",
        params={"port": "/dev/fake", "baudrate": 9600},
    )))
    r = client.get("/plugins/eqmod/diagnostics")
    assert r.status_code == 200
    body = r.json()
    assert [d["device_id"] for d in body] == ["real1"]
    assert body[0]["axes"]["RA"]["cpr"] == CPR
    assert body[0]["error"] is None


def test_settings_toggle_the_indi_proxy(tmp_path) -> None:
    from plugins.eqmod.indi_proxy_setup import IndiProxyRegistration
    from plugins.eqmod.tests.test_indi_proxy_setup import _FakeIndiManager

    app, _ = _make_app(tmp_path)
    manager = _FakeIndiManager()
    app.state.eqmod_indi_proxy = IndiProxyRegistration(manager, tmp_path / "run")
    client = TestClient(app)

    r = client.put("/plugins/eqmod/settings", json={"led_brightness": 50, "indi_proxy_enabled": True})
    assert r.status_code == 200
    assert manager.calls == [("add", str(tmp_path / "run" / "astrolol-indi-mount-proxy"))]

    # Saving an unrelated setting must not restart the proxy (PHD2 would drop it).
    client.put("/plugins/eqmod/settings", json={"led_brightness": 20, "indi_proxy_enabled": True})
    assert len(manager.calls) == 1

    status = client.get("/plugins/eqmod/indi_proxy").json()
    assert status["enabled"] is True and status["device_name"] == "astrolol Mount Proxy"


def test_settings_reject_a_bad_proxy_url(client: TestClient) -> None:
    r = client.put("/plugins/eqmod/settings", json={"indi_proxy_api_url": "localhost:8000"})
    assert r.status_code == 422
