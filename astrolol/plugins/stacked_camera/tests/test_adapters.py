"""Tests for the stacked and fast virtual cameras, run through the real device manager."""
from __future__ import annotations

import asyncio
from pathlib import Path

import astropy.io.fits as astropy_fits
import pytest

from astrolol.core.errors import DeviceConnectionError, ExposureHalted
from astrolol.devices.base.interfaces import ICamera, IPulseGuider, IStreamingCamera
from astrolol.devices.base.models import DeviceState, ExposureParams
from astrolol.devices.base.streaming import (
    StreamClosed,
    StreamParams,
    StreamRoi,
)
from astrolol.plugins.stacked_camera.adapters import FAST_KEY, STACKED_KEY
from astrolol.plugins.stacked_camera.events import StackProgress
from astrolol.plugins.stacked_camera.tests.rig import (
    SUB,
    PulsingSource,
    Rig,
    SourceCamera,
    feed,
    started,
)


def _ids(rig: Rig) -> set[str]:
    return {d["device_id"] for d in rig.manager.list_connected()}


# --- Registration and connecting ---


async def test_the_plugin_registers_both_adapters_as_its_own(rig: Rig) -> None:
    assert STACKED_KEY in rig.registry.cameras and FAST_KEY in rig.registry.cameras
    assert rig.registry.sources[STACKED_KEY] == rig.registry.sources[FAST_KEY] == "stacked_camera"


async def test_adapters_are_cameras(rig: Rig) -> None:
    await rig.source()
    stacked, fast = await rig.stacked(), await rig.fast()
    assert isinstance(stacked, ICamera) and isinstance(fast, ICamera)
    assert isinstance(fast, IStreamingCamera) and not isinstance(stacked, IStreamingCamera)


async def test_connecting_without_the_real_camera_is_refused(rig: Rig) -> None:
    with pytest.raises(DeviceConnectionError, match="not connected"):
        await rig.stacked()
    assert _ids(rig) == set()


async def test_connecting_without_choosing_a_camera_is_refused(rig: Rig) -> None:
    with pytest.raises(DeviceConnectionError, match="Choose the camera"):
        await rig.connect(STACKED_KEY, "cam_stack", source_id="")


async def test_a_stacked_camera_cannot_be_built_on_another(rig: Rig) -> None:
    await rig.source()
    await rig.stacked()
    with pytest.raises(DeviceConnectionError, match="itself a stacked camera"):
        await rig.connect(FAST_KEY, "again", source_id="cam_stack")


# --- Stacked camera ---


async def test_exposure_is_the_sum_of_the_subs(rig: Rig) -> None:
    source = await rig.source()
    stacked = await rig.stacked()
    feeder = asyncio.create_task(_after_start(source, 5, value=100))
    image = await asyncio.wait_for(stacked.expose(ExposureParams(duration=0.25)), 5)
    await feeder
    assert image.exposure_duration == pytest.approx(0.25)
    assert (image.width, image.height) == (8, 6)
    header = astropy_fits.getheader(image.fits_path)
    assert header["NSUBS"] == 5 and header["EXPTIME"] == pytest.approx(0.25)
    assert header["BITPIX"] == 32
    assert header["SATURATE"] == 5 * 65535
    assert (astropy_fits.getdata(image.fits_path) == 500).all()  # nothing subtracted


async def _after_start(source: SourceCamera, count: int, **frame: object) -> None:
    await started(source)
    await feed(source, count, **frame)


async def test_the_stream_runs_at_the_plugin_sub_length_with_the_requested_settings(
    rig: Rig,
) -> None:
    source = await rig.source()
    stacked = await rig.stacked()
    feeder = asyncio.create_task(_after_start(source, 2, gain=120, binning=2))
    await asyncio.wait_for(stacked.expose(ExposureParams(duration=0.1, gain=120, binning=2)), 5)
    await feeder
    assert source.started == [StreamParams(exposure=SUB, gain=120, binning=2, roi=None)]


async def test_an_exposure_is_rounded_up_to_whole_subs(rig: Rig) -> None:
    source = await rig.source()
    stacked = await rig.stacked()
    feeder = asyncio.create_task(_after_start(source, 3))
    image = await asyncio.wait_for(stacked.expose(ExposureParams(duration=0.12)), 5)
    await feeder
    assert image.exposure_duration == pytest.approx(0.15)
    assert astropy_fits.getheader(image.fits_path)["NSUBS"] == 3


async def test_an_exposure_shorter_than_a_sub_is_one_sub_of_that_length(rig: Rig) -> None:
    source = await rig.source()
    stacked = await rig.stacked()
    feeder = asyncio.create_task(_after_start(source, 1, exposure=0.02))
    image = await asyncio.wait_for(stacked.expose(ExposureParams(duration=0.02)), 5)
    await feeder
    assert image.exposure_duration == pytest.approx(0.02)
    assert source.started[-1].exposure == pytest.approx(0.02)


async def test_subs_begun_before_the_request_or_with_other_settings_are_left_out(
    rig: Rig,
) -> None:
    source = await rig.source()
    stacked = await rig.stacked()

    async def feeder() -> None:
        await started(source)
        source.emit(value=9999, age=5.0)  # began long before the request
        source.emit(value=9999, exposure=0.5)  # another sub-exposure
        source.emit(value=9999, binning=2)  # another binning
        await feed(source, 2, value=10)

    task = asyncio.create_task(feeder())
    image = await asyncio.wait_for(stacked.expose(ExposureParams(duration=0.1)), 5)
    await task
    assert (astropy_fits.getdata(image.fits_path) == 20).all()
    assert astropy_fits.getheader(image.fits_path)["NSUBS"] == 2


async def test_progress_is_published_and_ends_inactive(rig: Rig) -> None:
    queue = rig.bus.subscribe()
    source = await rig.source()
    stacked = await rig.stacked()
    feeder = asyncio.create_task(_after_start(source, 3))
    await asyncio.wait_for(stacked.expose(ExposureParams(duration=0.15)), 5)
    await feeder
    progress = []
    while not queue.empty():
        event = queue.get_nowait()
        if isinstance(event, StackProgress):
            progress.append(event)
    assert [e.subs_done for e in progress if e.active] == [0, 1, 2, 3]
    assert progress[-1].active is False
    assert {e.device_id for e in progress} == {"cam_stack"}
    assert progress[-1].subs_total == 3 and progress[-1].exposure_total == pytest.approx(0.15)


async def test_abort_halts_the_exposure_and_releases_the_stream(rig: Rig) -> None:
    source = await rig.source()
    stacked = await rig.stacked()
    task = asyncio.create_task(stacked.expose(ExposureParams(duration=10)))
    await started(source)
    assert stacked.exposing
    await stacked.abort()
    with pytest.raises(ExposureHalted):
        await asyncio.wait_for(task, 2)
    assert not stacked.exposing and not source.streaming
    assert list(rig.tmp_path.glob("*.fits")) == []


async def test_a_second_exposure_is_refused_while_one_runs(rig: Rig) -> None:
    source = await rig.source()
    stacked = await rig.stacked()
    task = asyncio.create_task(stacked.expose(ExposureParams(duration=10)))
    await started(source)
    with pytest.raises(RuntimeError, match="already running"):
        await stacked.expose(ExposureParams(duration=1))
    await stacked.abort()
    with pytest.raises(ExposureHalted):
        await task


async def test_a_camera_that_fails_mid_exposure_ends_it_with_the_reason(rig: Rig) -> None:
    source = await rig.source()
    stacked = await rig.stacked()

    async def break_it() -> None:
        await started(source)
        await feed(source, 1)
        source.fail(RuntimeError("usb unplugged"))

    task = asyncio.create_task(break_it())
    with pytest.raises(RuntimeError, match="usb unplugged"):
        await asyncio.wait_for(stacked.expose(ExposureParams(duration=10)), 5)
    await task
    assert not stacked.exposing


async def test_a_camera_that_sends_nothing_ends_the_exposure(rig: Rig) -> None:
    source = await rig.source()
    stacked = await rig.stacked()
    with pytest.raises(RuntimeError, match="no frame"):
        await asyncio.wait_for(stacked.expose(ExposureParams(duration=10)), 5)
    assert not source.streaming


async def test_the_next_exposure_after_a_failure_works(rig: Rig) -> None:
    source = await rig.source()
    stacked = await rig.stacked()

    async def break_it() -> None:
        await started(source)
        source.fail(RuntimeError("stall"))

    task = asyncio.create_task(break_it())
    with pytest.raises(RuntimeError):
        await asyncio.wait_for(stacked.expose(ExposureParams(duration=10)), 5)
    await task
    feeder = asyncio.create_task(_after_start(source, 1))
    image = await asyncio.wait_for(stacked.expose(ExposureParams(duration=0.05)), 5)
    await feeder
    assert image.exposure_duration == pytest.approx(0.05)


async def test_status_cooler_and_ping_follow_the_real_camera(rig: Rig) -> None:
    source = await rig.source()
    stacked = await rig.stacked()
    status = await stacked.get_status()
    assert status.state == DeviceState.CONNECTED and status.temperature == -10.0
    await stacked.set_cooler(True, -15.0)
    assert source.cooler == (True, -15.0)
    assert await stacked.ping() is True
    source.alive = False
    assert await stacked.ping() is False


async def test_status_is_busy_while_exposing(rig: Rig) -> None:
    source = await rig.source()
    stacked = await rig.stacked()
    task = asyncio.create_task(stacked.expose(ExposureParams(duration=10)))
    await started(source)
    assert (await stacked.get_status()).state == DeviceState.BUSY
    await stacked.abort()
    with pytest.raises(ExposureHalted):
        await task
    assert (await stacked.get_status()).state == DeviceState.CONNECTED


async def test_disconnecting_aborts_a_running_exposure(rig: Rig) -> None:
    source = await rig.source()
    await rig.stacked()
    stacked = rig.manager.get_camera("cam_stack")
    task = asyncio.create_task(stacked.expose(ExposureParams(duration=10)))
    await started(source)
    await rig.manager.disconnect("cam_stack")
    with pytest.raises(ExposureHalted):
        await asyncio.wait_for(task, 2)


async def test_images_are_written_to_the_bound_folder(rig: Rig) -> None:
    source = await rig.source()
    stacked = await rig.stacked()
    stacked._images_dir = rig.tmp_path
    feeder = asyncio.create_task(_after_start(source, 1))
    image = await asyncio.wait_for(stacked.expose(ExposureParams(duration=0.05)), 5)
    await feeder
    assert Path(image.fits_path).parent == rig.tmp_path


# --- Fast camera ---


async def test_the_fast_camera_streams_the_short_frames(rig: Rig) -> None:
    source = await rig.source()
    fast = await rig.fast()
    await fast.start_stream(StreamParams(exposure=SUB))
    sub = fast.subscribe_frames()
    source.emit(value=7)
    frame = await asyncio.wait_for(sub.get(), 1)
    assert frame.pixels[0, 0] == 7 and frame.origin == (0, 0)
    await fast.stop_stream()
    assert not source.streaming


async def test_the_fast_stream_is_cropped_to_the_region(rig: Rig) -> None:
    source = await rig.source()
    fast = await rig.fast()
    await fast.start_stream(StreamParams(exposure=SUB, roi=StreamRoi(x=2, y=1, width=3, height=2)))
    sub = fast.subscribe_frames()
    source.emit(value=7, shape=(6, 8))
    frame = await asyncio.wait_for(sub.get(), 1)
    assert frame.pixels.shape == (2, 3) and frame.origin == (2, 1)
    assert frame.settings_key[3] == (2, 1, 3, 2)
    await fast.stop_stream()


async def test_a_region_beyond_the_frame_gives_the_whole_frame(rig: Rig) -> None:
    source = await rig.source()
    fast = await rig.fast()
    roi = StreamRoi(x=50, y=50, width=3, height=3)
    await fast.start_stream(StreamParams(exposure=SUB, roi=roi))
    sub = fast.subscribe_frames()
    source.emit(shape=(6, 8))
    assert (await asyncio.wait_for(sub.get(), 1)).pixels.shape == (6, 8)
    await fast.stop_stream()


async def test_starting_twice_is_an_error_and_stopping_twice_is_fine(rig: Rig) -> None:
    await rig.source()
    fast = await rig.fast()
    await fast.start_stream(StreamParams(exposure=SUB))
    with pytest.raises(RuntimeError, match="already streaming"):
        await fast.start_stream(StreamParams(exposure=SUB))
    await fast.stop_stream()
    await fast.stop_stream()


async def test_restarting_the_fast_stream_restarts_the_real_one_only_when_alone(rig: Rig) -> None:
    source = await rig.source()
    fast = await rig.fast()
    for _ in range(3):
        await fast.start_stream(StreamParams(exposure=SUB))
        await fast.stop_stream()
    assert len(source.started) == 3 and source.stops == 3


async def test_the_fast_stream_keeps_the_plugin_sub_exposure(rig: Rig) -> None:
    source = await rig.source()
    fast = await rig.fast()
    await fast.start_stream(StreamParams(exposure=1.0, gain=80, binning=2))
    assert source.started[-1] == StreamParams(exposure=SUB, gain=80, binning=2, roi=None)
    await fast.stop_stream()


async def test_the_fast_camera_and_a_stack_share_one_stream(rig: Rig) -> None:
    source = await rig.source()
    fast = await rig.fast()
    stacked = await rig.stacked()
    await fast.start_stream(StreamParams(exposure=SUB))
    sub = fast.subscribe_frames()
    task = asyncio.create_task(stacked.expose(ExposureParams(duration=0.15)))
    await asyncio.sleep(0.02)  # the stack has claimed the stream too
    # The guider restarts its stream, as it does on every region change.
    await fast.stop_stream()
    assert source.streaming and source.stops == 0
    await fast.start_stream(StreamParams(exposure=SUB))
    sub = fast.subscribe_frames()
    await feed(source, 3, value=5)
    image = await asyncio.wait_for(task, 5)
    assert (astropy_fits.getdata(image.fits_path) == 15).all()
    assert (await asyncio.wait_for(sub.get(), 1)).pixels[0, 0] == 5  # the guider saw frames too
    assert len(source.started) == 1  # one physical stream throughout
    await fast.stop_stream()
    assert not source.streaming


async def test_the_fast_camera_does_not_expose(rig: Rig) -> None:
    await rig.source()
    fast = await rig.fast()
    with pytest.raises(RuntimeError, match="stacked camera"):
        await fast.expose(ExposureParams(duration=1))


async def test_a_camera_failure_reaches_the_guider(rig: Rig) -> None:
    source = await rig.source()
    fast = await rig.fast()
    await fast.start_stream(StreamParams(exposure=SUB))
    sub = fast.subscribe_frames()
    boom = RuntimeError("usb unplugged")
    source.fail(boom)
    with pytest.raises(StreamClosed) as info:
        await asyncio.wait_for(sub.get(), 1)
    assert info.value.__cause__ is boom
    await fast.stop_stream()  # still clean, and the stream can start again
    await fast.start_stream(StreamParams(exposure=SUB))
    await fast.stop_stream()


async def test_the_fast_camera_pulse_guides_only_when_the_real_one_can(rig: Rig) -> None:
    await rig.source()
    assert not isinstance(await rig.fast(), IPulseGuider)
    await rig.manager.disconnect("cam_fast")
    await rig.manager.disconnect("cam")
    source = await rig.source("pulsing_source")
    assert isinstance(source, PulsingSource)
    fast = await rig.fast()
    assert isinstance(fast, IPulseGuider)
    await fast.pulse_guide("N", 120)
    assert source.pulses == [("N", 120)]


async def test_disconnecting_the_fast_camera_stops_its_stream(rig: Rig) -> None:
    source = await rig.source()
    fast = await rig.fast()
    await fast.start_stream(StreamParams(exposure=SUB))
    await rig.manager.disconnect("cam_fast")
    assert not source.streaming


# --- The real camera comes and goes ---


async def test_the_hub_follows_the_real_camera_when_it_is_connected_again(rig: Rig) -> None:
    first = await rig.source()
    fast = await rig.fast()
    await fast.start_stream(StreamParams(exposure=SUB))
    await fast.stop_stream()
    await rig.manager.disconnect("cam_fast")
    await rig.manager.disconnect("cam")
    second = await rig.source()
    assert second is not first
    fast = await rig.fast()
    await fast.start_stream(StreamParams(exposure=SUB))
    assert second.streaming and not first.streaming
    await fast.stop_stream()
