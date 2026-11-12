"""Tests for the hub that shares one camera stream between virtual cameras."""
from __future__ import annotations

import asyncio
from pathlib import Path

import numpy as np
import pytest

from astrolol.devices.base.streaming import (
    Frame,
    FrameBroadcaster,
    FrameSubscription,
    StreamClosed,
    StreamParams,
)
from astrolol.plugins.stacked_camera.hub import SourceHub, SubParams
from tests.conftest import FakeCamera

PARAMS = SubParams(exposure=2.0, gain=100, binning=1)


class FakeStreamer:
    """A natively streaming camera that emits only the frames a test hands it."""

    def __init__(self) -> None:
        self._broadcaster = FrameBroadcaster()
        self.started: list[StreamParams] = []
        self.stops = 0
        self.streaming = False
        self.start_error: Exception | None = None
        self._seq = 0

    async def start_stream(self, params: StreamParams) -> None:
        if self.start_error is not None:
            raise self.start_error
        self.started.append(params)
        self.streaming = True

    async def stop_stream(self) -> None:
        self.stops += 1
        self.streaming = False
        self._broadcaster.end()

    def subscribe_frames(self) -> FrameSubscription:
        return self._broadcaster.subscribe()

    def emit(self, value: int = 1, exposure: float = 2.0, timestamp: float | None = None) -> None:
        self._seq += 1
        self._broadcaster.publish(
            Frame(
                pixels=np.full((4, 6), value, dtype=np.uint16),
                seq=self._seq,
                timestamp=float(self._seq) * exposure if timestamp is None else timestamp,
                exposure=exposure,
            )
        )

    def fail(self, error: Exception) -> None:
        self._broadcaster.end(error)


async def settle() -> None:
    for _ in range(5):
        await asyncio.sleep(0)


@pytest.fixture()
def camera() -> FakeStreamer:
    return FakeStreamer()


@pytest.fixture()
def hub(camera: FakeStreamer) -> SourceHub:
    return SourceHub(camera, PARAMS)


# --- Lifecycle ---


async def test_first_lease_starts_the_stream_with_the_hub_params(
    hub: SourceHub, camera: FakeStreamer
) -> None:
    assert not hub.running
    lease = await hub.acquire()
    assert hub.running and camera.streaming
    assert camera.started == [StreamParams(exposure=2.0, gain=100, binning=1, roi=None)]
    await lease.release()


async def test_the_stream_stays_up_until_the_last_lease_is_released(
    hub: SourceHub, camera: FakeStreamer
) -> None:
    first = await hub.acquire()
    second = await hub.acquire()
    assert len(camera.started) == 1 and hub.leases == 2
    await first.release()
    assert hub.running and camera.stops == 0
    await second.release()
    assert not hub.running and camera.stops == 1 and hub.leases == 0


async def test_releasing_a_lease_twice_releases_once(hub: SourceHub, camera: FakeStreamer) -> None:
    kept = await hub.acquire()
    other = await hub.acquire()
    await other.release()
    await other.release()
    assert hub.leases == 1 and hub.running
    await kept.release()


async def test_the_stream_can_be_started_again_after_stopping(
    hub: SourceHub, camera: FakeStreamer
) -> None:
    await (await hub.acquire()).release()
    lease = await hub.acquire()
    assert len(camera.started) == 2 and hub.running
    await lease.release()


async def test_a_camera_that_cannot_start_leaves_no_lease_behind(
    hub: SourceHub, camera: FakeStreamer
) -> None:
    camera.start_error = RuntimeError("busy")
    with pytest.raises(RuntimeError, match="busy"):
        await hub.acquire()
    assert hub.leases == 0 and not hub.running
    camera.start_error = None
    await (await hub.acquire()).release()


async def test_shutdown_stops_even_with_leases_held(hub: SourceHub, camera: FakeStreamer) -> None:
    await hub.acquire()
    sub = hub.subscribe_frames()
    await hub.shutdown()
    assert not hub.running and hub.leases == 0
    assert sub.closed


# --- Fan-out ---


async def test_every_subscriber_gets_the_frame(hub: SourceHub, camera: FakeStreamer) -> None:
    lease = await hub.acquire()
    first, second = hub.subscribe_frames(), hub.subscribe_frames()
    camera.emit(7)
    assert (await asyncio.wait_for(first.get(), 1)).pixels[0, 0] == 7
    assert (await asyncio.wait_for(second.get(), 1)).pixels[0, 0] == 7
    await lease.release()


async def test_a_slow_subscriber_skips_frames_but_a_sink_keeps_them_all(
    hub: SourceHub, camera: FakeStreamer
) -> None:
    lease = await hub.acquire()
    latest = hub.subscribe_frames()
    sink = hub.open_sink()
    for value in (1, 2, 3):
        camera.emit(value)
        await settle()
    assert (await asyncio.wait_for(latest.get(), 1)).pixels[0, 0] == 3  # only the newest
    assert [int((await sink.get()).pixels[0, 0]) for _ in range(3)] == [1, 2, 3]
    assert sink.dropped == 0
    await lease.release()


async def test_a_full_sink_drops_and_counts_without_holding_back_others(
    hub: SourceHub, camera: FakeStreamer
) -> None:
    lease = await hub.acquire()
    latest = hub.subscribe_frames()
    sink = hub.open_sink(depth=2)
    for value in (1, 2, 3, 4):
        camera.emit(value)
        await settle()
    assert sink.dropped == 2
    assert [int((await sink.get()).pixels[0, 0]) for _ in range(2)] == [1, 2]  # oldest kept
    assert (await asyncio.wait_for(latest.get(), 1)).pixels[0, 0] == 4
    await lease.release()


async def test_a_sink_only_sees_frames_from_when_it_opened(
    hub: SourceHub, camera: FakeStreamer
) -> None:
    lease = await hub.acquire()
    camera.emit(1)
    await settle()
    sink = hub.open_sink()
    camera.emit(2)
    await settle()
    assert int((await sink.get()).pixels[0, 0]) == 2
    await lease.release()


async def test_a_closed_sink_gets_nothing_more(hub: SourceHub, camera: FakeStreamer) -> None:
    lease = await hub.acquire()
    sink = hub.open_sink()
    sink.close()
    camera.emit(1)
    await settle()
    assert sink.dropped == 0
    with pytest.raises(StreamClosed):
        await sink.get()
    await lease.release()


async def test_frames_already_queued_survive_the_end_of_the_stream(
    hub: SourceHub, camera: FakeStreamer
) -> None:
    lease = await hub.acquire()
    sink = hub.open_sink()
    camera.emit(5)
    await settle()
    await lease.release()  # last lease: the stream stops
    assert int((await sink.get()).pixels[0, 0]) == 5
    with pytest.raises(StreamClosed):
        await sink.get()


# --- Reconfiguring ---


async def test_configure_restarts_a_running_stream_and_keeps_consumers(
    hub: SourceHub, camera: FakeStreamer
) -> None:
    lease = await hub.acquire()
    latest = hub.subscribe_frames()
    sink = hub.open_sink()
    await hub.configure(SubParams(exposure=1.0, gain=100, binning=1))
    assert camera.stops == 1 and len(camera.started) == 2
    assert camera.started[1].exposure == 1.0
    camera.emit(9, exposure=1.0)
    await settle()
    assert (await asyncio.wait_for(latest.get(), 1)).pixels[0, 0] == 9
    assert int((await sink.get()).pixels[0, 0]) == 9
    assert hub.params.exposure == 1.0
    await lease.release()


async def test_configure_with_the_same_params_does_nothing(
    hub: SourceHub, camera: FakeStreamer
) -> None:
    lease = await hub.acquire()
    await hub.configure(PARAMS)
    assert camera.stops == 0 and len(camera.started) == 1
    await lease.release()


async def test_configure_while_stopped_only_takes_effect_on_the_next_start(
    hub: SourceHub, camera: FakeStreamer
) -> None:
    await hub.configure(SubParams(exposure=5.0))
    assert camera.started == []
    lease = await hub.acquire()
    assert camera.started[0].exposure == 5.0
    await lease.release()


# --- Failure ---


async def test_a_camera_failure_reaches_every_consumer(
    hub: SourceHub, camera: FakeStreamer
) -> None:
    lease = await hub.acquire()
    latest = hub.subscribe_frames()
    sink = hub.open_sink()
    boom = RuntimeError("usb unplugged")
    camera.fail(boom)
    await settle()
    assert not hub.running and hub.error is boom
    with pytest.raises(StreamClosed) as latest_info:
        await latest.get()
    assert latest_info.value.__cause__ is boom
    with pytest.raises(StreamClosed) as sink_info:
        await sink.get()
    assert sink_info.value.__cause__ is boom
    await lease.release()  # still safe, and does not stop twice
    assert camera.stops == 1


async def test_a_stream_that_ends_by_itself_is_a_failure(
    hub: SourceHub, camera: FakeStreamer
) -> None:
    lease = await hub.acquire()
    sink = hub.open_sink()
    camera._broadcaster.end()  # the driver stopped streaming on its own
    await settle()
    assert hub.error is not None and not hub.running
    with pytest.raises(StreamClosed):
        await sink.get()
    await lease.release()


async def test_acquire_after_a_failure_starts_again_and_clears_the_error(
    hub: SourceHub, camera: FakeStreamer
) -> None:
    held = await hub.acquire()
    camera.fail(RuntimeError("stall"))
    await settle()
    assert hub.error is not None
    again = await hub.acquire()
    assert hub.running and hub.error is None and len(camera.started) == 2
    sink = hub.open_sink()
    camera.emit(3)
    await settle()
    assert int((await sink.get()).pixels[0, 0]) == 3
    await held.release()
    assert hub.running  # the second lease keeps it going
    await again.release()


# --- Statistics ---


async def test_stats_count_frames_and_measure_the_duty_cycle(
    hub: SourceHub, camera: FakeStreamer
) -> None:
    lease = await hub.acquire()
    assert hub.stats.duty is None
    # 2 s subs arriving every 2.5 s: the sensor exposes 80% of the time
    for i in range(1, 6):
        camera.emit(1, exposure=2.0, timestamp=10.0 + i * 2.5)
        await settle()
    stats = hub.stats
    assert stats.frames == 5 and stats.source_dropped == 0
    assert stats.duty == pytest.approx(0.8)
    await lease.release()


async def test_stats_start_afresh_with_each_stream(hub: SourceHub, camera: FakeStreamer) -> None:
    lease = await hub.acquire()
    camera.emit()
    await settle()
    await lease.release()
    lease = await hub.acquire()
    assert hub.stats.frames == 0
    await lease.release()


# --- Over a camera that cannot stream ---


async def test_works_over_a_camera_without_a_native_stream(tmp_path: Path) -> None:
    hub = SourceHub(FakeCamera(images_dir=tmp_path), SubParams(exposure=0.01))
    lease = await hub.acquire()
    sink = hub.open_sink()
    first = await asyncio.wait_for(sink.get(), 5)
    second = await asyncio.wait_for(sink.get(), 5)
    assert first.pixels.ndim == 2 and second.seq == first.seq + 1
    await lease.release()
    assert not hub.running
    # Frames do not pile up on disk; only the exposure cut short by the stop may leave a file.
    assert len(list(tmp_path.glob("*.fits"))) <= 1


# --- A camera that ignores the exposure it was asked for ---


async def test_frames_much_faster_than_their_exposure_are_flagged(
    hub: SourceHub, camera: FakeStreamer
) -> None:
    lease = await hub.acquire()
    for i in range(8):  # labelled 2 s, arriving every 0.05 s
        camera.emit(exposure=2.0, timestamp=i * 0.05)
        await settle()
    assert hub.stats.too_fast
    await lease.release()


async def test_frames_at_the_pace_of_their_exposure_are_not_flagged(
    hub: SourceHub, camera: FakeStreamer
) -> None:
    lease = await hub.acquire()
    for _ in range(12):
        camera.emit()  # the fake stamps each one an exposure after the last
        await settle()
    assert not hub.stats.too_fast
    await lease.release()


async def test_a_restarted_stream_forgets_the_flag(hub: SourceHub, camera: FakeStreamer) -> None:
    lease = await hub.acquire()
    for i in range(8):
        camera.emit(exposure=2.0, timestamp=i * 0.05)
        await settle()
    await lease.release()
    lease = await hub.acquire()
    assert not hub.stats.too_fast
    await lease.release()
