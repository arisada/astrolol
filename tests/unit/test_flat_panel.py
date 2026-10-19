"""Flat panel: manager, REST API, the INDI adapter against a fake client, and driver catalog kind."""
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from astrolol.api.flat_panel import router
from astrolol.core.events import EventBus, FlatPanelChanged
from astrolol.devices.base.models import CoverState, DeviceState
from astrolol.devices.config import DeviceConfig
from astrolol.devices.indi.catalog import _parse_file
from astrolol.devices.indi.flat_panel import IndiFlatPanel
from astrolol.devices.manager import DeviceManager
from astrolol.flat_panel import FlatPanelManager

CONFIG = DeviceConfig(device_id="panel", kind="flat_panel", adapter_key="fake_flat_panel")


# --- manager -----------------------------------------------------------------

@pytest.mark.asyncio
async def test_cover_and_light_through_manager(flat_panel_manager: FlatPanelManager, manager: DeviceManager) -> None:
    await manager.connect(CONFIG)
    status = await flat_panel_manager.open_cover("panel")
    assert status.cover == CoverState.OPEN
    status = await flat_panel_manager.set_light("panel", True, 120)
    assert (status.light_on, status.brightness) == (True, 120)
    status = await flat_panel_manager.close_cover("panel")
    assert status.cover == CoverState.CLOSED


@pytest.mark.asyncio
async def test_changes_are_published(flat_panel_manager: FlatPanelManager, manager: DeviceManager, event_bus: EventBus) -> None:
    await manager.connect(CONFIG)
    q = event_bus.subscribe()
    await flat_panel_manager.set_light("panel", True, 50)
    events = []
    while not q.empty():
        events.append(await q.get())
    changed = [e for e in events if isinstance(e, FlatPanelChanged)]
    assert len(changed) == 1
    assert (changed[0].device_id, changed[0].light_on, changed[0].brightness) == ("panel", True, 50)


# --- API ---------------------------------------------------------------------

@pytest.fixture
def api(manager: DeviceManager, flat_panel_manager: FlatPanelManager) -> AsyncClient:
    app = FastAPI()
    app.include_router(router)
    app.state.flat_panel_manager = flat_panel_manager
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.mark.asyncio
async def test_api_roundtrip(api: AsyncClient, manager: DeviceManager) -> None:
    await manager.connect(CONFIG)
    async with api as c:
        r = await c.get("/flat_panel/panel/status")
        assert r.status_code == 200 and r.json()["cover"] == "closed"
        r = await c.post("/flat_panel/panel/cover/open")
        assert r.json()["cover"] == "open"
        r = await c.post("/flat_panel/panel/light", json={"on": True, "brightness": 200})
        assert r.json()["light_on"] is True and r.json()["brightness"] == 200


@pytest.mark.asyncio
async def test_api_unknown_device_is_404(api: AsyncClient) -> None:
    async with api as c:
        assert (await c.get("/flat_panel/nope/status")).status_code == 404
        assert (await c.post("/flat_panel/nope/cover/open")).status_code == 404


@pytest.mark.asyncio
async def test_api_wrong_kind_is_404(api: AsyncClient, manager: DeviceManager) -> None:
    await manager.connect(DeviceConfig(device_id="fw", kind="filter_wheel", adapter_key="fake_filter_wheel"))
    async with api as c:
        assert (await c.get("/flat_panel/fw/status")).status_code == 404


@pytest.mark.asyncio
async def test_light_only_device_refuses_cover(api: AsyncClient, manager: DeviceManager) -> None:
    await manager.connect(DeviceConfig(
        device_id="lightbox", kind="flat_panel", adapter_key="fake_flat_panel", params={"has_cover": False},
    ))
    async with api as c:
        assert (await c.get("/flat_panel/lightbox/status")).json()["has_cover"] is False
        assert (await c.post("/flat_panel/lightbox/cover/open")).status_code == 422


@pytest.mark.asyncio
async def test_negative_brightness_is_rejected(api: AsyncClient, manager: DeviceManager) -> None:
    await manager.connect(CONFIG)
    async with api as c:
        assert (await c.post("/flat_panel/panel/light", json={"on": True, "brightness": -1})).status_code == 422


# --- INDI adapter ------------------------------------------------------------

class _Member:
    def __init__(self, value, mn=None, mx=None) -> None:
        self.membervalue = value
        self.min, self.max = mn, mx


class _Vector:
    def __init__(self, state: str, **members) -> None:
        self.state = state
        self.data = members

    def getfloatvalue(self, name: str) -> float:
        return float(self.data[name].membervalue)


class _FakeIndi:
    def __init__(self, props: dict) -> None:
        self.props = props
        self.sent: list[tuple] = []

    def _get_vector(self, dev, prop):
        return self.props.get(prop)

    def get_switch_state_nowait(self, dev, prop, el):
        v = self.props.get(prop)
        return None if v is None else v.data[el].membervalue == "On"

    def get_number_nowait(self, dev, prop, el):
        v = self.props.get(prop)
        return None if v is None else v.getfloatvalue(el)

    async def set_switch(self, dev, prop, on):
        self.sent.append(("switch", prop, tuple(on)))

    async def set_number(self, dev, prop, values):
        self.sent.append(("number", prop, values))

    async def wait_prop_busy_then_done(self, *a, **k):
        pass


def _panel(props: dict) -> tuple[IndiFlatPanel, _FakeIndi]:
    client = _FakeIndi(props)
    panel = IndiFlatPanel("Flip Flat", client)  # type: ignore[arg-type]
    panel._state = DeviceState.CONNECTED
    return panel, client


_FULL = {
    "CAP_PARK": _Vector("Ok", PARK=_Member("On"), UNPARK=_Member("Off")),
    "FLAT_LIGHT_CONTROL": _Vector("Ok", FLAT_LIGHT_ON=_Member("Off"), FLAT_LIGHT_OFF=_Member("On")),
    "FLAT_LIGHT_INTENSITY": _Vector("Ok", FLAT_LIGHT_INTENSITY_VALUE=_Member(40, 0, 255)),
}


@pytest.mark.asyncio
async def test_indi_status_of_a_full_device() -> None:
    panel, _ = _panel(dict(_FULL))
    s = await panel.get_status()
    assert (s.has_cover, s.cover, s.has_light, s.light_on) == (True, CoverState.CLOSED, True, False)
    assert (s.brightness, s.max_brightness) == (40, 255)


@pytest.mark.asyncio
async def test_indi_cover_states() -> None:
    props = dict(_FULL)
    props["CAP_PARK"] = _Vector("Ok", PARK=_Member("Off"), UNPARK=_Member("On"))
    assert (await _panel(props)[0].get_status()).cover == CoverState.OPEN
    props["CAP_PARK"] = _Vector("Busy", PARK=_Member("Off"), UNPARK=_Member("On"))
    assert (await _panel(props)[0].get_status()).cover == CoverState.MOVING


@pytest.mark.asyncio
async def test_indi_commands_use_standard_properties() -> None:
    panel, client = _panel(dict(_FULL))
    await panel.open_cover()
    await panel.close_cover()
    await panel.set_light(True, 128)
    assert client.sent == [
        ("switch", "CAP_PARK", ("UNPARK",)),
        ("switch", "CAP_PARK", ("PARK",)),
        ("number", "FLAT_LIGHT_INTENSITY", {"FLAT_LIGHT_INTENSITY_VALUE": 128.0}),  # level first, then on
        ("switch", "FLAT_LIGHT_CONTROL", ("FLAT_LIGHT_ON",)),
    ]


@pytest.mark.asyncio
async def test_indi_brightness_out_of_range_sends_nothing() -> None:
    panel, client = _panel(dict(_FULL))
    with pytest.raises(ValueError):
        await panel.set_light(True, 300)
    assert client.sent == []


@pytest.mark.asyncio
async def test_indi_light_only_and_cover_only_devices() -> None:
    light_only, _ = _panel({k: v for k, v in _FULL.items() if k != "CAP_PARK"})
    assert (await light_only.get_status()).cover is None
    with pytest.raises(ValueError):
        await light_only.open_cover()

    cover_only, _ = _panel({"CAP_PARK": _FULL["CAP_PARK"]})
    s = await cover_only.get_status()
    assert s.has_light is False and s.light_on is None
    with pytest.raises(ValueError):
        await cover_only.set_light(True)


# --- catalog -----------------------------------------------------------------

def test_flat_panel_drivers_are_classified(tmp_path) -> None:
    xml = tmp_path / "d.xml"
    xml.write_text("""<driversList><devGroup group="Auxiliary">
      <device label="Flip Flat" manufacturer="Optec"><driver name="Flip Flat">indi_flipflat</driver></device>
      <device label="Joystick" manufacturer="Others"><driver name="Joystick">indi_joystick</driver></device>
    </devGroup></driversList>""")
    kinds = {e.executable: e.kind for e in _parse_file(xml)}
    assert kinds == {"indi_flipflat": "flat_panel", "indi_joystick": "aux"}
