"""Guide pulses on the INDI Guide Simulator (ST4 route) and Telescope Simulator (mount route)."""
from __future__ import annotations

import asyncio
import shutil

import astropy.units as u
import pytest
from astropy.coordinates import SkyCoord

from tests.indi_server import set_scope_info, start_indiserver as _start_indiserver, stop_indiserver as _stop

pytestmark = pytest.mark.skipif(shutil.which("indiserver") is None, reason="indiserver not installed")

_PORT = 17640


@pytest.fixture(scope="module")
def server():
    proc = _start_indiserver(_PORT, "indi_simulator_telescope", "indi_simulator_guide")
    yield proc
    _stop(proc)


@pytest.fixture(scope="module")
async def devices(server, tmp_path_factory):
    from astrolol.devices.indi.camera import IndiCamera
    from astrolol.devices.indi.client import IndiClient
    from astrolol.devices.indi.mount import IndiMount

    client = IndiClient(host="localhost", port=_PORT)
    await client.connect()
    mount = IndiMount(device_name="Telescope Simulator", client=client)
    cam = IndiCamera("Guide Simulator", client, images_dir=tmp_path_factory.mktemp("guide"))
    await mount.connect()
    await cam.connect()
    await set_scope_info(client, "Guide Simulator")
    # The simulator starts at the celestial pole; point it at a rich field so frames have stars.
    await mount.slew(SkyCoord(ra=83.8 * u.deg, dec=-5.4 * u.deg))
    await asyncio.sleep(1)
    await client.wait_prop_not_busy("Telescope Simulator", "EQUATORIAL_EOD_COORD", timeout=90)
    yield cam, mount
    await cam.disconnect()
    await mount.disconnect()
    await client.disconnect()


@pytest.mark.parametrize("direction", ["N", "S", "E", "W"])
async def test_camera_st4_pulse_completes(devices, direction) -> None:
    cam, _ = devices
    await cam.pulse_guide(direction, 200)


@pytest.mark.parametrize("direction", ["N", "S", "E", "W"])
async def test_mount_pulse_completes(devices, direction) -> None:
    _, mount = devices
    await mount.pulse_guide(direction, 200)


async def test_native_stream_delivers_frames_with_roi(devices) -> None:
    from astrolol.devices.base import IStreamingCamera, StreamParams, StreamRoi

    cam, _ = devices
    assert isinstance(cam, IStreamingCamera) and cam.can_stream
    # The window sits on the brightest star of the field the fixture points at (peak at
    # column 1006, row 434 of the 1280x1024 frame): the simulator's empty sky is perfectly flat,
    # so a window placed blindly can legitimately show nothing.
    roi = StreamRoi(x=974, y=410, width=64, height=48)
    sub = cam.subscribe_frames()
    await cam.start_stream(StreamParams(exposure=0.1, roi=roi))
    try:
        frames = [await asyncio.wait_for(sub.get(), 5) for _ in range(5)]
    finally:
        await cam.stop_stream()
    assert frames[-1].seq > frames[0].seq
    last = frames[-1]
    assert last.pixels.shape == (48, 64) and last.origin == (roi.x, roi.y)
    assert last.pixels.std() > 0  # a real image, not zeros
    with pytest.raises(Exception):  # the stream ended
        await asyncio.wait_for(sub.get(), 1)
