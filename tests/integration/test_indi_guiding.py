"""The built-in guider against INDI's Guide Simulator, through both pulse routes."""
from __future__ import annotations

import asyncio
import shutil

import astropy.units as u
import pytest
from astropy.coordinates import SkyCoord

from astrolol.core.events import EventBus
from astrolol.core.guiding import SettleParams
from astrolol.plugins.guider.guider import BuiltinGuider
from astrolol.plugins.guider.settings import GuiderSettings, pick_pulse_guider
from tests.integration.test_indi_simulators import _start_indiserver, _stop

# Real-time: each test guides for minutes of wall-clock time (~7 min in all), so these are
# deselected by default (see pyproject.toml). Run them before a release and after any
# guiding change:  python3 -m pytest tests/integration/test_indi_guiding.py -m slow
pytestmark = [
    pytest.mark.slow,
    pytest.mark.skipif(shutil.which("indiserver") is None, reason="indiserver not installed"),
]

_PORT = 17650


@pytest.fixture(scope="module")
def server():
    proc = _start_indiserver(_PORT, "indi_simulator_telescope", "indi_simulator_guide")
    yield proc
    _stop(proc)


@pytest.fixture(scope="module")
async def rig(server, tmp_path_factory):
    from astrolol.devices.indi.camera import IndiCamera
    from astrolol.devices.indi.client import IndiClient
    from astrolol.devices.indi.mount import IndiMount

    client = IndiClient(host="localhost", port=_PORT)
    await client.connect()
    mount = IndiMount(device_name="Telescope Simulator", client=client)
    cam = IndiCamera("Guide Simulator", client, images_dir=tmp_path_factory.mktemp("g"))
    await mount.connect()
    await cam.connect()
    await cam.set_active_telescope("Telescope Simulator")
    # The simulator starts at the celestial pole, where its star field is not stable: point it
    # at a normal target and track, so the only motion is what the guider causes.
    await mount.set_tracking(True)
    await mount.slew(SkyCoord(ra=83.8 * u.deg, dec=-5.4 * u.deg))
    await asyncio.sleep(1)
    await client.wait_prop_not_busy("Telescope Simulator", "EQUATORIAL_EOD_COORD", timeout=90)
    yield cam, mount
    await cam.disconnect()
    await mount.disconnect()
    await client.disconnect()


class Devices:
    def __init__(self, cam, mount, output) -> None:  # noqa: ANN001
        self.cam, self.mount, self.output = cam, mount, output

    def camera(self):  # noqa: ANN201
        return self.cam

    def pulse_guider(self):  # noqa: ANN201
        return pick_pulse_guider(self.output, self.cam, self.mount)


@pytest.mark.parametrize("output", ["camera", "mount"])
async def test_guides_the_simulator(rig, output) -> None:
    cam, mount = rig
    guider = BuiltinGuider(
        EventBus(),
        GuiderSettings(guide_output=output, exposure=0.5, calibration_steps=5),
        Devices(cam, mount, output),
    )
    await guider.guide(SettleParams(pixels=2.0, time=0, timeout=90))
    start = guider.mark()
    await asyncio.sleep(24)  # the simulator delivers a frame every ~2 s
    stats = guider.stats(start)
    health = guider.health()
    await guider.stop()
    print(output, guider.calibration, stats)

    # Calibration found two clearly different axes and a plausible guide speed.
    cal = guider.calibration
    assert cal is not None
    cos = abs(cal.ra_x * cal.dec_x + cal.ra_y * cal.dec_y) / (cal.ra_rate * cal.dec_rate)
    assert cos < 0.35, cal  # within ~20 degrees of perpendicular
    assert 0.005 < cal.ra_rate < 0.05 and 0.005 < cal.dec_rate < 0.05, cal
    # And it kept the star: no loss, errors of a few pixels at most (the simulator has no drift
    # of its own, so this proves the loop is stable, not that it improves anything).
    assert stats.steps >= 3
    assert stats.losses == 0 and health.guiding
    assert stats.rms_total is not None and stats.rms_total < 3.0, stats


async def test_plugin_api_guides_the_simulator(rig) -> None:
    """The same flow as the page: choose the camera, start guiding, watch the status."""
    import httpx
    from fastapi import FastAPI

    from astrolol.core.plugin_api import PluginContext
    from astrolol.plugins.guider.plugin import get_plugin

    cam, mount = rig

    class Manager:
        def get_camera(self, device_id):  # noqa: ANN001, ANN202
            assert device_id == "guide_cam"
            return cam

        def get_mount(self, device_id):  # noqa: ANN001, ANN202
            assert device_id == "mount"
            return mount

    app, plugin = FastAPI(), get_plugin()
    plugin.setup(app, PluginContext(event_bus=EventBus(), device_manager=Manager(), device_registry=object()))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as http:
        settings = (await http.get("/plugins/guider/settings")).json()
        settings.update(camera_id="guide_cam", exposure=0.5, calibration_steps=5)
        assert (await http.put("/plugins/guider/settings", json=settings)).status_code == 200
        assert (await http.post("/plugins/guider/guide", json={"settle": {"pixels": 2.0, "time": 0, "timeout": 90}})).status_code == 204
        try:
            for _ in range(150):
                status = (await http.get("/plugins/guider/status")).json()
                if status["health"]["guiding"]:
                    break
                await asyncio.sleep(1)
            assert status["health"]["guiding"], status
            assert status["calibration"] is not None
        finally:
            assert (await http.post("/plugins/guider/stop")).status_code == 204
        assert not (await http.get("/plugins/guider/status")).json()["status"]["active"]
    await plugin.shutdown()
