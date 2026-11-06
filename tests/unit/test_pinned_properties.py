"""Property values pinned to a device: kept in the inventory, set again at every connection."""
from __future__ import annotations

import types

import pytest
from httpx import ASGITransport, AsyncClient

from astrolol.devices.config import DeviceConfig
from astrolol.devices.indi import pins as pinlib
from astrolol.devices.manager import DeviceManager
from astrolol.equipment.models import CameraItem
from astrolol.equipment.store import EquipmentStore
from astrolol.main import create_app
from tests.conftest import FakeCamera
from tests.unit.test_api_properties import (
    _FakeIndiClient,
    _FakeNumberMember,
    _FakeSwitchMember,
    _FakeTextMember,
    _FakeVector,
)

INDI_NAME = "Test Camera"


# ── the rules ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "name, kind, perm, rule, expected",
    [
        ("CCD_TEMP_RAMP", "number", "rw", None, True),
        ("DEVICE_PORT", "text", "rw", None, True),
        ("UPLOAD_MODE", "switch", "rw", "1ofmany", True),
        ("CCD_CAPTURE_FORMAT", "switch", "rw", "nofmany", True),
        ("TELESCOPE_ABORT_MOTION", "switch", "rw", "atmost1", False),   # a trigger
        ("CCD_INFO", "text", "ro", None, False),
        ("CCD_FRAME_RESET", "switch", "wo", "atmost1", False),
        ("STATUS", "light", "ro", None, False),
        ("CONNECTION", "switch", "rw", "1ofmany", False),
        ("CCD_EXPOSURE", "number", "rw", None, False),                   # would start an exposure
        ("CONFIG_PROCESS", "switch", "rw", "atmost1", False),
        ("CCD_GAIN", "number", "rw", None, False),                       # never an implicit gain
    ],
)
def test_what_can_be_pinned(name, kind, perm, rule, expected) -> None:
    assert pinlib.pinnable(name, kind, perm, rule) is expected


def test_a_gain_is_never_kept_with_the_other_values() -> None:
    """CCD_CONTROLS holds the gain of a ZWO next to its offset: keep the offset, not the gain."""
    spec = pinlib.pin_spec("number", {"Gain": 200.0, "Offset": 10.0})
    assert spec == {"values": {"Offset": 10.0}}
    assert pinlib.pin_spec("number", {"Gain": 200.0}) is None


def test_pin_specs() -> None:
    assert pinlib.pin_spec("number", {"RAMP_SLOPE": 3, "RAMP_THRESHOLD": 0.2}) == {
        "values": {"RAMP_SLOPE": 3.0, "RAMP_THRESHOLD": 0.2}
    }
    assert pinlib.pin_spec("text", {"PORT": "/dev/ttyUSB0"}) == {"values": {"PORT": "/dev/ttyUSB0"}}
    assert pinlib.pin_spec("switch", {"A": False, "B": True}) == {"on_elements": ["B"]}
    assert pinlib.pin_spec("switch", {"A": False}) is None


def test_hand_edited_pins_are_read_carefully() -> None:
    raw = {
        "CCD_TEMP_RAMP": {"values": {"RAMP_SLOPE": 3}},
        "UPLOAD_MODE": {"on_elements": ["UPLOAD_LOCAL"]},
        "CCD_EXPOSURE": {"values": {"CCD_EXPOSURE_VALUE": 600}},   # not allowed
        "BROKEN": "3",
        "EMPTY": {"values": {}},
        "CCD_CONTROLS": {"values": {"Gain": 200, "Offset": 10}},
    }
    assert pinlib.clean_pins(raw) == {
        "CCD_TEMP_RAMP": {"values": {"RAMP_SLOPE": 3}},
        "UPLOAD_MODE": {"on_elements": ["UPLOAD_LOCAL"]},
        "CCD_CONTROLS": {"values": {"Offset": 10}},
    }
    assert pinlib.clean_pins(None) == {} and pinlib.clean_pins([1]) == {}


# ── applying them ──────────────────────────────────────────────────────────

class _Client:
    """The few IndiClient members apply_pins uses."""

    def __init__(self, vectors: dict, alert: tuple[str, ...] = ()) -> None:
        self.vectors, self.alert, self.calls = vectors, alert, []

    async def wait_for_property(self, device: str, prop: str, timeout: float = 10.0):  # noqa: ANN201
        if prop not in self.vectors:
            raise TimeoutError(f"{prop} not announced")
        return self.vectors[prop]

    def _vector_state(self, device: str, prop: str) -> str:
        return "Alert" if prop in self.alert else "Ok"

    async def set_number(self, device: str, prop: str, values: dict) -> None:
        self.calls.append(("number", prop, values))

    async def set_text(self, device: str, prop: str, values: dict) -> None:
        self.calls.append(("text", prop, values))

    async def set_switch(self, device: str, prop: str, on: list) -> None:
        self.calls.append(("switch", prop, on))


@pytest.fixture(autouse=True)
def _no_wait(monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.setattr(pinlib, "SETTLE_S", 0.0)
    monkeypatch.setattr(pinlib, "PROPERTY_WAIT_S", 0.0)


async def test_pins_are_written_to_the_device() -> None:
    client = _Client({
        "CCD_TEMP_RAMP": types.SimpleNamespace(vectortype="NumberVector"),
        "DEVICE_PORT": types.SimpleNamespace(vectortype="TextVector"),
        "UPLOAD_MODE": types.SimpleNamespace(vectortype="SwitchVector"),
    })
    failed = await pinlib.apply_pins(client, "Cam", {
        "CCD_TEMP_RAMP": {"values": {"RAMP_SLOPE": 3}},
        "DEVICE_PORT": {"values": {"PORT": "/dev/ttyUSB0"}},
        "UPLOAD_MODE": {"on_elements": ["UPLOAD_LOCAL"]},
    })
    assert failed == []
    assert client.calls == [
        ("number", "CCD_TEMP_RAMP", {"RAMP_SLOPE": 3.0}),
        ("text", "DEVICE_PORT", {"PORT": "/dev/ttyUSB0"}),
        ("switch", "UPLOAD_MODE", ["UPLOAD_LOCAL"]),
    ]


async def test_a_property_the_driver_lacks_or_refuses_is_reported_and_the_rest_still_set() -> None:
    client = _Client({
        "CCD_TEMP_RAMP": types.SimpleNamespace(vectortype="NumberVector"),
        "OTHER": types.SimpleNamespace(vectortype="NumberVector"),
    }, alert=("OTHER",))
    failed = await pinlib.apply_pins(client, "Cam", {
        "MISSING": {"values": {"X": 1}},
        "OTHER": {"values": {"Y": 1}},
        "CCD_TEMP_RAMP": {"values": {"RAMP_SLOPE": 3}},
    })
    assert sorted(failed) == ["MISSING", "OTHER"]
    assert ("number", "CCD_TEMP_RAMP", {"RAMP_SLOPE": 3.0}) in client.calls


# ── the device manager ─────────────────────────────────────────────────────

async def test_connecting_sets_the_pins_and_keeps_them_out_of_the_adapter(manager: DeviceManager) -> None:
    seen: dict = {}

    class Strict(FakeCamera):
        def __init__(self, device_name: str) -> None:   # no other parameter: pinned_props must not arrive
            super().__init__()
            seen["device_name"] = device_name

    manager.registry.register_camera("strict_camera", Strict)  # type: ignore[arg-type]
    manager.registry.indi_client = _Client({"CCD_TEMP_RAMP": types.SimpleNamespace(vectortype="NumberVector")})
    config = DeviceConfig(
        device_id="cam1", kind="camera", adapter_key="strict_camera",
        params={"device_name": "Cam", pinlib.PINNED_KEY: {"CCD_TEMP_RAMP": {"values": {"RAMP_SLOPE": 3}}}},
    )

    await manager.connect(config)

    assert seen == {"device_name": "Cam"}
    assert manager.registry.indi_client.calls == [("number", "CCD_TEMP_RAMP", {"RAMP_SLOPE": 3.0})]


async def test_a_reconnection_sets_them_again(manager: DeviceManager) -> None:
    manager.registry.register_camera("fake_camera", FakeCamera)  # type: ignore[arg-type]
    client = manager.registry.indi_client = _Client({"CCD_TEMP_RAMP": types.SimpleNamespace(vectortype="NumberVector")})
    await manager.connect(DeviceConfig(
        device_id="cam1", kind="camera", adapter_key="fake_camera",
        params={"device_name": "Cam", pinlib.PINNED_KEY: {"CCD_TEMP_RAMP": {"values": {"RAMP_SLOPE": 3}}}},
    ))
    await manager.soft_disconnect("cam1")
    client.calls.clear()
    await manager.reconnect("cam1")
    assert client.calls == [("number", "CCD_TEMP_RAMP", {"RAMP_SLOPE": 3.0})]


async def test_a_device_with_nothing_pinned_is_left_alone(manager: DeviceManager) -> None:
    manager.registry.register_camera("fake_camera", FakeCamera)  # type: ignore[arg-type]
    client = manager.registry.indi_client = _Client({})
    await manager.connect(DeviceConfig(device_id="cam1", kind="camera", adapter_key="fake_camera", params={"device_name": "Cam"}))
    assert client.calls == []


# ── the API ────────────────────────────────────────────────────────────────

_SNAPSHOT = {
    "CCD_TEMP_RAMP": _FakeVector(
        "CCD_TEMP_RAMP", "NumberVector",
        members={"RAMP_SLOPE": _FakeNumberMember("RAMP_SLOPE", 0.0, 0.0, 10.0)},
    ),
    "CCD_CONTROLS": _FakeVector(
        "CCD_CONTROLS", "NumberVector",
        members={"Gain": _FakeNumberMember("Gain", 200.0, 0.0, 500.0), "Offset": _FakeNumberMember("Offset", 10.0, 0.0, 100.0)},
    ),
    "UPLOAD_MODE": _FakeVector(
        "UPLOAD_MODE", "SwitchVector",
        members={"UPLOAD_CLIENT": _FakeSwitchMember("UPLOAD_CLIENT", True), "UPLOAD_LOCAL": _FakeSwitchMember("UPLOAD_LOCAL")},
        rule="OneOfMany",
    ),
    "CCD_ABORT_EXPOSURE": _FakeVector(
        "CCD_ABORT_EXPOSURE", "SwitchVector", members={"ABORT": _FakeSwitchMember("ABORT")}, rule="AtMostOne",
    ),
    "DEVICE_PORT": _FakeVector(
        "DEVICE_PORT", "TextVector", members={"PORT": _FakeTextMember("PORT", "/dev/ttyUSB0")},
    ),
}


@pytest.fixture
def rig(tmp_path):  # noqa: ANN001, ANN201
    app = create_app()
    app.state.registry.register_camera("fake_camera", FakeCamera)  # type: ignore[arg-type]
    app.state.registry.indi_client = _FakeIndiClient(_SNAPSHOT)
    store = app.state.equipment_store = EquipmentStore(tmp_path / "inventory.json")
    item = store.create(CameraItem(name="Test", indi_driver="indi_test", indi_device_name=INDI_NAME))
    client = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
    return app, client, store, item


async def _connect(c: AsyncClient) -> None:
    r = await c.post("/devices/connect", json={
        "device_id": "cam1", "kind": "camera", "adapter_key": "fake_camera", "params": {"device_name": INDI_NAME},
    })
    assert r.status_code == 201, r.text


async def test_the_property_list_says_what_can_be_pinned(rig) -> None:  # noqa: ANN001
    app, client, store, item = rig
    async with client as c:
        await _connect(c)
        props = {p["name"]: p for p in (await c.get("/devices/cam1/properties")).json()}
    assert props["CCD_TEMP_RAMP"]["pinnable"] and not props["CCD_TEMP_RAMP"]["pinned"]
    assert props["UPLOAD_MODE"]["pinnable"] and props["DEVICE_PORT"]["pinnable"]
    assert not props["CCD_ABORT_EXPOSURE"]["pinnable"]      # a trigger


async def test_pinning_keeps_the_current_value_in_the_inventory_item(rig) -> None:  # noqa: ANN001
    app, client, store, item = rig
    async with client as c:
        await _connect(c)
        await c.post("/devices/cam1/properties/CCD_TEMP_RAMP", json={"values": {"RAMP_SLOPE": 3}})
        _SNAPSHOT["CCD_TEMP_RAMP"].data["RAMP_SLOPE"].membervalue = "3.0"   # what the driver now reports
        r = await c.put("/devices/cam1/pins/CCD_TEMP_RAMP")
        assert r.status_code == 200 and r.json() == {"values": {"RAMP_SLOPE": 3.0}}
        props = {p["name"]: p for p in (await c.get("/devices/cam1/properties")).json()}
        assert props["CCD_TEMP_RAMP"]["pinned"]
    saved = store.get(item.id).connect_params
    assert saved == {"pinned_props": {"CCD_TEMP_RAMP": {"values": {"RAMP_SLOPE": 3.0}}}}
    # and a reconnection of the same inventory item sets it
    from astrolol.equipment.optical_path import item_device_config

    assert item_device_config(store.get(item.id)).params["pinned_props"] == saved["pinned_props"]
    _SNAPSHOT["CCD_TEMP_RAMP"].data["RAMP_SLOPE"].membervalue = "0.0"


async def test_setting_a_pinned_property_keeps_the_new_value(rig) -> None:  # noqa: ANN001
    app, client, store, item = rig
    async with client as c:
        await _connect(c)
        assert (await c.put("/devices/cam1/pins/CCD_TEMP_RAMP")).status_code == 200
        assert (await c.post("/devices/cam1/properties/CCD_TEMP_RAMP", json={"values": {"RAMP_SLOPE": 2}})).status_code == 204
        # a property that is not pinned stays out of the item
        assert (await c.post("/devices/cam1/properties/DEVICE_PORT", json={"values": {"PORT": "/dev/x"}})).status_code == 204
    assert store.get(item.id).connect_params["pinned_props"] == {"CCD_TEMP_RAMP": {"values": {"RAMP_SLOPE": 2.0}}}


async def test_unpinning(rig) -> None:  # noqa: ANN001
    app, client, store, item = rig
    async with client as c:
        await _connect(c)
        await c.put("/devices/cam1/pins/CCD_TEMP_RAMP")
        await c.put("/devices/cam1/pins/UPLOAD_MODE")
        assert (await c.delete("/devices/cam1/pins/CCD_TEMP_RAMP")).status_code == 204
        assert list(store.get(item.id).connect_params["pinned_props"]) == ["UPLOAD_MODE"]
        assert (await c.delete("/devices/cam1/pins/UPLOAD_MODE")).status_code == 204
    assert store.get(item.id).connect_params == {}


async def test_what_cannot_be_pinned_is_refused(rig) -> None:  # noqa: ANN001
    app, client, store, item = rig
    async with client as c:
        await _connect(c)
        assert (await c.put("/devices/cam1/pins/CCD_ABORT_EXPOSURE")).status_code == 409
        assert (await c.put("/devices/cam1/pins/NO_SUCH")).status_code == 404
        r = await c.put("/devices/cam1/pins/CCD_CONTROLS")     # the gain does not go with it
        assert r.json() == {"values": {"Offset": 10.0}}
    assert store.get(item.id).connect_params["pinned_props"]["CCD_CONTROLS"] == {"values": {"Offset": 10.0}}


async def test_a_device_outside_the_inventory_cannot_be_pinned(rig) -> None:  # noqa: ANN001
    app, client, store, item = rig
    store.delete(item.id)
    async with client as c:
        await _connect(c)
        props = {p["name"]: p for p in (await c.get("/devices/cam1/properties")).json()}
        assert not any(p["pinnable"] for p in props.values())
        r = await c.put("/devices/cam1/pins/CCD_TEMP_RAMP")
    assert r.status_code == 409 and "inventory" in r.json()["detail"]
