import asyncio
from pathlib import Path

import numpy as np
import pytest

from astrolol.devices.base import (
    Frame,
    FrameBroadcaster,
    IStreamingCamera,
    StreamClosed,
    StreamParams,
    StreamRoi,
)
from astrolol.imaging.streaming import LoopingExposureStream
from tests.conftest import FakeCamera


def make_frame(seq: int, **kw: object) -> Frame:
    return Frame(pixels=np.zeros((4, 6), dtype=np.uint16), seq=seq, timestamp=0.0, exposure=1.0, **kw)  # type: ignore[arg-type]


# --- latest-wins delivery ---

async def test_subscription_keeps_only_the_newest_frame() -> None:
    hub = FrameBroadcaster()
    sub = hub.subscribe()
    for seq in (1, 2, 3):
        hub.publish(make_frame(seq))
    assert (await sub.get()).seq == 3
    assert sub.dropped == 2


async def test_get_waits_for_next_frame() -> None:
    hub = FrameBroadcaster()
    sub = hub.subscribe()
    waiter = asyncio.create_task(sub.get())
    await asyncio.sleep(0)
    assert not waiter.done()
    hub.publish(make_frame(7))
    assert (await asyncio.wait_for(waiter, 1)).seq == 7


async def test_each_subscriber_gets_every_frame_independently() -> None:
    hub = FrameBroadcaster()
    a, b = hub.subscribe(), hub.subscribe()
    hub.publish(make_frame(1))
    assert (await a.get()).seq == 1
    hub.publish(make_frame(2))
    assert (await a.get()).seq == 2
    assert (await b.get()).seq == 2  # b was slow: skipped 1
    assert (a.dropped, b.dropped) == (0, 1)


async def test_close_unsubscribes_and_ends_iteration() -> None:
    hub = FrameBroadcaster()
    sub = hub.subscribe()
    sub.close()
    assert hub.subscriber_count == 0
    assert [f async for f in sub] == []


async def test_pending_frame_is_delivered_before_the_end() -> None:
    hub = FrameBroadcaster()
    sub = hub.subscribe()
    hub.publish(make_frame(1))
    hub.end()
    assert [f.seq async for f in sub] == [1]


async def test_error_surfaces_to_the_consumer() -> None:
    hub = FrameBroadcaster()
    sub = hub.subscribe()
    hub.end(RuntimeError("camera unplugged"))
    with pytest.raises(StreamClosed) as info:
        await sub.get()
    assert isinstance(info.value.__cause__, RuntimeError)


def test_settings_key_identifies_matching_darks() -> None:
    f = make_frame(1, gain=100, binning=2, origin=(10, 20))
    assert f.settings_key == (1.0, 100, 2, (10, 20, 6, 4))
    assert f.settings_key != make_frame(1, gain=100, binning=2).settings_key


# --- LoopingExposureStream ---

class ScriptedCamera(FakeCamera):
    def __init__(self, images_dir: Path, fail_after: int | None = None) -> None:
        super().__init__(images_dir=images_dir)
        self.aborted = False
        self._fail_after = fail_after

    async def expose(self, params):  # type: ignore[no-untyped-def]
        await asyncio.sleep(0)
        if self._fail_after is not None and self._counter >= self._fail_after:
            raise RuntimeError("sensor fault")
        return await super().expose(params)

    async def abort(self) -> None:
        self.aborted = True


async def test_looping_stream_publishes_frames(tmp_path: Path) -> None:
    stream = LoopingExposureStream(ScriptedCamera(tmp_path))
    assert isinstance(stream, IStreamingCamera)
    sub = stream.subscribe_frames()
    await stream.start_stream(StreamParams(exposure=0.5, gain=10))
    first = await asyncio.wait_for(sub.get(), 5)
    second = await asyncio.wait_for(sub.get(), 5)
    await stream.stop_stream()
    assert second.seq > first.seq >= 1
    assert (first.width, first.height) == (64, 64)
    assert first.gain == 10 and first.exposure == 0.5


async def test_roi_crops_and_records_origin(tmp_path: Path) -> None:
    stream = LoopingExposureStream(ScriptedCamera(tmp_path))
    sub = stream.subscribe_frames()
    await stream.start_stream(StreamParams(exposure=1, roi=StreamRoi(x=8, y=16, width=20, height=10)))
    frame = await asyncio.wait_for(sub.get(), 5)
    await stream.stop_stream()
    assert frame.pixels.shape == (10, 20)
    assert frame.origin == (8, 16)


async def test_stop_aborts_the_exposure_and_ends_subscribers(tmp_path: Path) -> None:
    camera = ScriptedCamera(tmp_path)
    stream = LoopingExposureStream(camera)
    sub = stream.subscribe_frames()
    await stream.start_stream(StreamParams(exposure=1))
    await asyncio.wait_for(sub.get(), 5)
    await stream.stop_stream()
    assert camera.aborted and not stream.streaming
    with pytest.raises(StreamClosed):
        await sub.get()


async def test_camera_failure_reaches_subscribers(tmp_path: Path) -> None:
    stream = LoopingExposureStream(ScriptedCamera(tmp_path, fail_after=1))
    sub = stream.subscribe_frames()
    await stream.start_stream(StreamParams(exposure=1))
    with pytest.raises(StreamClosed) as info:
        async for _ in sub:
            pass
    assert "sensor fault" in str(info.value.__cause__)


async def test_cannot_start_twice(tmp_path: Path) -> None:
    stream = LoopingExposureStream(ScriptedCamera(tmp_path))
    await stream.start_stream(StreamParams(exposure=1))
    with pytest.raises(RuntimeError):
        await stream.start_stream(StreamParams(exposure=1))
    await stream.stop_stream()
