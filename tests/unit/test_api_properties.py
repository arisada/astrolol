"""HTTP tests for GET/POST /devices/{id}/properties."""
from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from astrolol.main import create_app
from tests.conftest import FakeCamera


# ---------------------------------------------------------------------------
# Fake indipyclient vector / member stubs
# ---------------------------------------------------------------------------

class _FakeNumberMember:
    def __init__(self, name: str, value: float, min: float = 0.0, max: float = 100.0, step: float = 1.0):
        self.name = name
        self.label = name
        self.membervalue = str(value)
        self.min = str(min)
        self.max = str(max)
        self.step = str(step)

    def getfloatvalue(self) -> float:
        return float(self.membervalue)


class _FakeSwitchMember:
    def __init__(self, name: str, on: bool = False):
        self.name = name
        self.label = name
        self.membervalue = "On" if on else "Off"


class _FakeTextMember:
    def __init__(self, name: str, value: str = ""):
        self.name = name
        self.label = name
        self.membervalue = value


class _FakeLightMember:
    def __init__(self, name: str, state: str = "Ok"):
        self.name = name
        self.label = name
        self.membervalue = state


class _FakeVector:
    def __init__(
        self,
        name: str,
        vectortype: str,
        members: dict,
        label: str = "",
        group: str = "Main",
        state: str = "Ok",
        perm: str = "rw",
        rule: str | None = None,
    ):
        self.name = name
        self.vectortype = vectortype
        self.label = label or name
        self.group = group
        self.state = state
        self.perm = perm
        self.rule = rule
        self.data = members


class _FakeIndiClient:
    def __init__(self, snapshot: dict):
        self._snapshot = snapshot
        self.set_calls: list = []

    async def get_properties_snapshot(self, device_name: str) -> dict:
        return self._snapshot

    async def set_number(self, device_name: str, prop_name: str, values: dict) -> None:
        self.set_calls.append(("number", device_name, prop_name, values))

    async def set_switch(self, device_name: str, prop_name: str, on_elements: list) -> None:
        self.set_calls.append(("switch", device_name, prop_name, on_elements))

    async def set_text(self, device_name: str, prop_name: str, values: dict) -> None:
        self.set_calls.append(("text", device_name, prop_name, values))


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_DEVICE_ID = "cam1"
_INDI_NAME = "Test Camera"
_CONNECT_PAYLOAD = {
    "device_id": _DEVICE_ID,
    "kind": "camera",
    "adapter_key": "fake_camera",
    "params": {"device_name": _INDI_NAME},
}

_SNAPSHOT = {
    "CCD_EXPOSURE": _FakeVector(
        "CCD_EXPOSURE", "NumberVector",
        members={"CCD_EXPOSURE_VALUE": _FakeNumberMember("CCD_EXPOSURE_VALUE", 1.0, 0.0, 3600.0, 0.001)},
        group="Main Control",
    ),
    "CONNECTION": _FakeVector(
        "CONNECTION", "SwitchVector",
        members={
            "CONNECT": _FakeSwitchMember("CONNECT", on=True),
            "DISCONNECT": _FakeSwitchMember("DISCONNECT", on=False),
        },
        rule="OneOfMany",
    ),
    "CCD_INFO": _FakeVector(
        "CCD_INFO", "TextVector",
        members={"CCD_NAME": _FakeTextMember("CCD_NAME", "Fake CCD")},
        perm="ro",
    ),
    "STATUS_LIGHTS": _FakeVector(
        "STATUS_LIGHTS", "LightVector",
        members={"READY": _FakeLightMember("READY", "Ok")},
        perm="ro",
    ),
    "CCD_BLOB": _FakeVector(
        "CCD_BLOB", "BLOBVector",
        members={},
    ),
}


@pytest.fixture
def app():
    application = create_app()
    application.state.registry.register_camera("fake_camera", FakeCamera)  # type: ignore[arg-type]
    return application


@pytest.fixture
def indi_client():
    return _FakeIndiClient(_SNAPSHOT)


@pytest.fixture
def client(app, indi_client):
    app.state.registry.indi_client = indi_client
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


# ---------------------------------------------------------------------------
# GET /devices/{id}/properties
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_properties_returns_all_non_blob_types(client: AsyncClient) -> None:
    async with client as c:
        await c.post("/devices/connect", json=_CONNECT_PAYLOAD)
        r = await c.get(f"/devices/{_DEVICE_ID}/properties")
    assert r.status_code == 200
    types = {p["type"] for p in r.json()}
    assert types == {"number", "switch", "text", "light"}


@pytest.mark.asyncio
async def test_properties_blob_excluded(client: AsyncClient) -> None:
    async with client as c:
        await c.post("/devices/connect", json=_CONNECT_PAYLOAD)
        r = await c.get(f"/devices/{_DEVICE_ID}/properties")
    names = {p["name"] for p in r.json()}
    assert "CCD_BLOB" not in names


@pytest.mark.asyncio
async def test_properties_number_fields(client: AsyncClient) -> None:
    async with client as c:
        await c.post("/devices/connect", json=_CONNECT_PAYLOAD)
        r = await c.get(f"/devices/{_DEVICE_ID}/properties")
    props = {p["name"]: p for p in r.json()}
    exp = props["CCD_EXPOSURE"]
    assert exp["type"] == "number"
    assert exp["state"] == "ok"
    assert exp["permission"] == "rw"
    widget = exp["widgets"][0]
    assert widget["value"] == pytest.approx(1.0)
    assert widget["min"] == pytest.approx(0.0)
    assert widget["max"] == pytest.approx(3600.0)


@pytest.mark.asyncio
async def test_properties_switch_fields(client: AsyncClient) -> None:
    async with client as c:
        await c.post("/devices/connect", json=_CONNECT_PAYLOAD)
        r = await c.get(f"/devices/{_DEVICE_ID}/properties")
    props = {p["name"]: p for p in r.json()}
    sw = props["CONNECTION"]
    assert sw["type"] == "switch"
    assert sw["switch_rule"] == "1ofmany"
    on_widgets = [w for w in sw["widgets"] if w["value"] is True]
    assert len(on_widgets) == 1
    assert on_widgets[0]["name"] == "CONNECT"


@pytest.mark.asyncio
async def test_properties_light_fields(client: AsyncClient) -> None:
    async with client as c:
        await c.post("/devices/connect", json=_CONNECT_PAYLOAD)
        r = await c.get(f"/devices/{_DEVICE_ID}/properties")
    props = {p["name"]: p for p in r.json()}
    lights = props["STATUS_LIGHTS"]
    assert lights["type"] == "light"
    assert lights["permission"] == "ro"
    assert lights["widgets"][0]["state"] == "ok"


@pytest.mark.asyncio
async def test_properties_sorted_by_group_then_name(client: AsyncClient) -> None:
    async with client as c:
        await c.post("/devices/connect", json=_CONNECT_PAYLOAD)
        r = await c.get(f"/devices/{_DEVICE_ID}/properties")
    keys = [(p["group"], p["name"]) for p in r.json()]
    assert keys == sorted(keys)


@pytest.mark.asyncio
async def test_properties_unknown_device_404(client: AsyncClient) -> None:
    async with client as c:
        r = await c.get("/devices/ghost/properties")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_properties_no_indi_client_503(app: object, client: AsyncClient) -> None:
    app.state.registry.indi_client = None  # type: ignore[union-attr]
    async with client as c:
        await c.post("/devices/connect", json=_CONNECT_PAYLOAD)
        r = await c.get(f"/devices/{_DEVICE_ID}/properties")
    assert r.status_code == 503


@pytest.mark.asyncio
async def test_properties_no_device_name_400(client: AsyncClient) -> None:
    """Device connected without device_name param → 400."""
    async with client as c:
        await c.post("/devices/connect", json={
            "device_id": "cam2", "kind": "camera", "adapter_key": "fake_camera",
            "params": {},
        })
        r = await c.get("/devices/cam2/properties")
    assert r.status_code == 400


# ---------------------------------------------------------------------------
# POST /devices/{id}/properties/{prop_name}
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_set_number_property(client: AsyncClient, indi_client: _FakeIndiClient) -> None:
    async with client as c:
        await c.post("/devices/connect", json=_CONNECT_PAYLOAD)
        r = await c.post(
            f"/devices/{_DEVICE_ID}/properties/CCD_EXPOSURE",
            json={"values": {"CCD_EXPOSURE_VALUE": 5.0}},
        )
    assert r.status_code == 204
    assert indi_client.set_calls == [("number", _INDI_NAME, "CCD_EXPOSURE", {"CCD_EXPOSURE_VALUE": 5.0})]


@pytest.mark.asyncio
async def test_set_switch_property(client: AsyncClient, indi_client: _FakeIndiClient) -> None:
    async with client as c:
        await c.post("/devices/connect", json=_CONNECT_PAYLOAD)
        r = await c.post(
            f"/devices/{_DEVICE_ID}/properties/CONNECTION",
            json={"on_elements": ["CONNECT"]},
        )
    assert r.status_code == 204
    assert indi_client.set_calls == [("switch", _INDI_NAME, "CONNECTION", ["CONNECT"])]


@pytest.mark.asyncio
async def test_set_text_property(client: AsyncClient, indi_client: _FakeIndiClient) -> None:
    async with client as c:
        await c.post("/devices/connect", json=_CONNECT_PAYLOAD)
        r = await c.post(
            f"/devices/{_DEVICE_ID}/properties/SITE_INFO",
            json={"values": {"SITE_NAME": "Backyard"}},
        )
    assert r.status_code == 204
    assert indi_client.set_calls == [("text", _INDI_NAME, "SITE_INFO", {"SITE_NAME": "Backyard"})]
