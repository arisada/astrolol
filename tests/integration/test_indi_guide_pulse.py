"""Guide pulses on the INDI Guide Simulator (ST4 route) and Telescope Simulator (mount route)."""
from __future__ import annotations

import shutil

import pytest

from tests.integration.test_indi_simulators import _start_indiserver, _stop

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
    import asyncio

    from astrolol.devices.base import IStreamingCamera, StreamParams, StreamRoi

    cam, _ = devices
    assert isinstance(cam, IStreamingCamera) and cam.can_stream
    sub = cam.subscribe_frames()
    await cam.start_stream(StreamParams(exposure=0.1, roi=StreamRoi(x=100, y=200, width=64, height=48)))
    try:
        frames = [await asyncio.wait_for(sub.get(), 5) for _ in range(5)]
    finally:
        await cam.stop_stream()
    assert frames[-1].seq > frames[0].seq
    last = frames[-1]
    assert last.pixels.shape == (48, 64) and last.origin == (100, 200)
    assert last.pixels.std() > 0  # a real image, not zeros
    with pytest.raises(Exception):  # the stream ended
        await asyncio.wait_for(sub.get(), 1)
