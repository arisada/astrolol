"""Each device item in the inventory says what drives it: INDI, INDIGO or a plugin."""
from __future__ import annotations

import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from astrolol.app import discover_plugins, setup_plugins
from astrolol.core.plugin_api import PluginContext
from astrolol.devices.registry import DeviceRegistry
from astrolol.equipment.models import CameraItem, MountItem, OTAItem, SiteItem
from astrolol.equipment.source import device_source
from astrolol.equipment.store import EquipmentStore
from astrolol.main import create_app


def _registry() -> DeviceRegistry:
    registry = DeviceRegistry()
    registry.register_camera("indi_camera", object)       # core: no plugin
    with registry.registering_for("alpaca"):
        registry.register_camera("alpaca_camera", object)
    return registry


def test_registry_records_the_plugin_behind_each_adapter() -> None:
    registry = _registry()
    assert registry.sources == {"alpaca_camera": "alpaca"}
    registry.register_mount("after", object)               # outside the block: core again
    assert "after" not in registry.sources


def test_setup_records_the_adapters_each_plugin_registers() -> None:
    registry = DeviceRegistry()
    ctx = PluginContext(event_bus=None, device_manager=None, device_registry=registry)
    setup_plugins(FastAPI(), ctx, discover_plugins(), ["alpaca", "eqmod"])
    assert registry.sources["alpaca_mount"] == "alpaca"
    assert registry.sources["eqmod"] == registry.sources["eqmod_sim"] == "eqmod"


@pytest.mark.parametrize("item, expected", [
    (CameraItem(name="c", indi_driver="indi_simulator_ccd"), "indi"),
    (CameraItem(name="c", indi_driver="indigo_ccd_simulator"), "indigo"),
    (CameraItem(name="c", indi_driver="/opt/indigo/bin/indigo_ccd_asi"), "indigo"),
    (CameraItem(name="c", adapter_key="alpaca_camera"), "alpaca"),
    (CameraItem(name="c", adapter_key="indi_camera"), "indi"),
    (MountItem(name="m", adapter_key="eqmod"), None),        # plugin not loaded here
    (CameraItem(name="c"), None),
    (OTAItem(name="o", focal_length=400, aperture=80), None),
    (SiteItem(name="s", latitude=0, longitude=0), None),
])
def test_device_source(item, expected) -> None:  # noqa: ANN001
    assert device_source(item, _registry()) == expected


@pytest.fixture
def client(tmp_path):  # noqa: ANN001, ANN201
    app = create_app()
    app.state.equipment_store = EquipmentStore(tmp_path / "inventory.json")
    with app.state.registry.registering_for("alpaca"):
        app.state.registry.register_camera("alpaca_camera", object)
    return TestClient(app)


def test_the_inventory_says_what_drives_each_device(client: TestClient, tmp_path) -> None:  # noqa: ANN001
    alpaca = client.post("/inventory", json={"type": "camera", "name": "Sim", "adapter_key": "alpaca_camera"}).json()
    indigo = client.post("/inventory", json={"type": "camera", "name": "Sim2", "indi_driver": "indigo_ccd_simulator"}).json()
    assert (alpaca["source"], indigo["source"]) == ("alpaca", "indigo")
    by_name = {i["name"]: i.get("source") for i in client.get("/inventory").json()}
    assert by_name == {"Sim": "alpaca", "Sim2": "indigo"}
    assert client.get(f"/inventory/{alpaca['id']}").json()["source"] == "alpaca"


def test_a_source_sent_by_a_client_is_not_kept(client: TestClient, tmp_path) -> None:  # noqa: ANN001
    item = client.post("/inventory", json={"type": "camera", "name": "Cam", "indi_driver": "indi_simulator_ccd",
                                           "source": "alpaca"}).json()
    assert item["source"] == "indi"
    r = client.put(f"/inventory/{item['id']}", json={**item, "source": "something"})
    assert r.json()["source"] == "indi"
    saved = json.loads((tmp_path / "inventory.json").read_text())["items"]
    assert len(saved) == 1 and saved[0].get("source") is None
