"""One camera stream shared by every consumer of the same physical camera.

A camera can stream for one client at a time, yet the virtual cameras built on it (the fast one
for the guider, the stacked one for the imager) are used independently and restart their streams
whenever they please. The hub owns the single real stream, keeps count of who needs it, and
fans each frame out: to latest-wins subscribers (a guider only wants the newest frame) and to
queues that must see every frame (a stack), counting what a full queue made it lose.
"""

from __future__ import annotations

import asyncio
import contextlib
import statistics
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass

import structlog

from astrolol.devices.base.interfaces import IStreamingCamera
from astrolol.devices.base.streaming import (
    Frame,
    FrameBroadcaster,
    FrameSubscription,
    StreamClosed,
    StreamParams,
)
from astrolol.imaging.streaming import LoopingExposureStream, streaming_camera

logger = structlog.get_logger()

# Frames closer together than this share of their exposure cannot be exposures of that length.
TOO_FAST_RATIO = 0.5
TOO_FAST_WINDOW = 5

DEFAULT_SINK_DEPTH = 8


@dataclass(frozen=True)
class SubParams:
    """How the shared stream runs: every consumer sees frames made with these."""

    exposure: float
    gain: int | None = None
    binning: int = 1

    def stream_params(self) -> StreamParams:
        return StreamParams(exposure=self.exposure, gain=self.gain, binning=self.binning)


@dataclass(frozen=True)
class HubStats:
    frames: int  # frames received from the camera since the stream started
    source_dropped: int  # frames the camera produced that the hub did not get in time
    duty: float | None  # share of wall time the sensor was exposing; None until 2 frames
    # Frames keep arriving much faster than their exposure: the camera ignores the exposure
    # it was asked for (some drivers only read it when the stream starts), so a frame's
    # length is not what its label says and adding them up would give the wrong exposure time.
    too_fast: bool = False


class StackSink:
    """Every frame since it was opened, in order, up to a bounded backlog.

    A sink that is not drained does not slow the camera or the other consumers: past its depth,
    new frames are refused and counted in ``dropped``.
    """

    def __init__(self, depth: int, on_close: Callable[[StackSink], None] | None = None) -> None:
        self._depth = depth
        self._frames: deque[Frame] = deque()
        self._wake = asyncio.Event()
        self._closed = False
        self._error: BaseException | None = None
        self._on_close = on_close
        self.dropped = 0

    def _offer(self, frame: Frame) -> None:
        if self._closed:
            return
        if len(self._frames) >= self._depth:
            self.dropped += 1
            return
        self._frames.append(frame)
        self._wake.set()

    def _end(self, error: BaseException | None) -> None:
        if self._closed:
            return
        self._closed = True
        self._error = error
        self._wake.set()

    @property
    def closed(self) -> bool:
        return self._closed

    async def get(self) -> Frame:
        """The oldest frame not yet taken; ``StreamClosed`` once the sink ended and is empty."""
        while True:
            if self._frames:
                return self._frames.popleft()
            if self._closed:
                raise StreamClosed("stream ended") from self._error
            self._wake.clear()
            await self._wake.wait()

    def close(self) -> None:
        self._end(None)
        self._frames.clear()
        if self._on_close is not None:
            self._on_close(self)


class Lease:
    """A consumer's claim on the stream. Releasing twice is harmless."""

    def __init__(self, hub: SourceHub) -> None:
        self._hub: SourceHub | None = hub

    async def release(self) -> None:
        hub, self._hub = self._hub, None
        if hub is not None:
            await hub._release()


class SourceHub:
    """The shared stream of one camera. Not tied to the device manager: it takes the camera."""

    def __init__(self, camera: object, params: SubParams) -> None:
        self._wrappers: dict[int, LoopingExposureStream] = {}
        self._stream: IStreamingCamera = streaming_camera(camera, self._wrappers)
        self._params = params
        self._frames = FrameBroadcaster()
        self._sinks: set[StackSink] = set()
        self._leases = 0
        self._lock = asyncio.Lock()
        self._source: FrameSubscription | None = None
        self._pump_task: asyncio.Task[None] | None = None
        self._error: BaseException | None = None
        self._gaps: deque[float] = deque(maxlen=TOO_FAST_WINDOW)  # gap / exposure, recent frames
        self._too_fast = False
        self._reset_stats()

    # --- State ---

    @property
    def params(self) -> SubParams:
        return self._params

    @property
    def running(self) -> bool:
        return self._pump_task is not None and not self._pump_task.done()

    @property
    def error(self) -> BaseException | None:
        """Why the stream ended, if the camera failed; cleared when it is started again."""
        return self._error

    @property
    def leases(self) -> int:
        return self._leases

    @property
    def stats(self) -> HubStats:
        duty = None
        if self._frames_seen >= 2 and self._last_ts > self._first_ts:
            duty = min(1.0, self._exposed_after_first / (self._last_ts - self._first_ts))
        return HubStats(self._frames_seen, self._source_dropped, duty, self._too_fast)

    # --- Consumers ---

    def subscribe_frames(self) -> FrameSubscription:
        """Latest-wins frames at the stream's full size. Take it after ``acquire()``: the
        subscription ends when the stream stops."""
        return self._frames.subscribe()

    def open_sink(self, depth: int = DEFAULT_SINK_DEPTH) -> StackSink:
        """A queue that gets every frame (up to *depth* waiting) from now on."""
        sink = StackSink(depth, on_close=self._sinks.discard)
        self._sinks.add(sink)
        return sink

    async def acquire(self) -> Lease:
        """Claim the stream, starting it if nobody else has (or if it failed since)."""
        async with self._lock:
            self._leases += 1
            if not self.running:
                try:
                    await self._start()
                except BaseException:
                    self._leases -= 1
                    raise
            return Lease(self)

    async def configure(self, params: SubParams) -> None:
        """Change how the stream runs; a running stream restarts, consumers stay attached."""
        async with self._lock:
            if params == self._params:
                return
            self._params = params
            if self.running:
                logger.info("stacked_camera.restart_stream", exposure=params.exposure)
                await self._halt()
                await self._start()

    async def shutdown(self) -> None:
        """Stop for good (the plugin is going away), whoever still holds a lease."""
        async with self._lock:
            self._leases = 0
            await self._halt()
            self._end_consumers(None)

    # --- Internals ---

    async def _release(self) -> None:
        async with self._lock:
            self._leases = max(0, self._leases - 1)
            if self._leases == 0 and self.running:
                await self._halt()
                self._end_consumers(None)

    def _reset_stats(self) -> None:
        self._frames_seen = 0
        self._source_dropped = 0
        self._exposed_after_first = 0.0  # exposure of every frame but the first
        self._first_ts = 0.0
        self._last_ts = 0.0
        self._gaps.clear()
        self._too_fast = False

    async def _start(self) -> None:
        self._error = None
        self._reset_stats()
        # Subscribe before starting: a frame the camera makes at once must not be missed.
        self._source = self._stream.subscribe_frames()
        try:
            await self._stream.start_stream(self._params.stream_params())
        except BaseException:
            self._source.close()
            self._source = None
            raise
        self._pump_task = asyncio.create_task(self._pump(self._source))

    async def _halt(self) -> None:
        """Stop the camera's stream and the pump, keeping the consumers attached."""
        task, self._pump_task = self._pump_task, None
        source, self._source = self._source, None
        with contextlib.suppress(Exception):
            await self._stream.stop_stream()
        if source is not None:
            source.close()
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    def _end_consumers(self, error: BaseException | None) -> None:
        self._frames.end(error)
        for sink in list(self._sinks):
            sink._end(error)

    async def _pump(self, source: FrameSubscription) -> None:
        try:
            async for frame in source:
                self._note(frame, source)
                self._frames.publish(frame)
                for sink in tuple(self._sinks):
                    sink._offer(frame)
        except StreamClosed as exc:  # the camera failed (a clean stop ends the loop quietly)
            await self._failed(exc.__cause__ or exc)
        else:
            if self._source is source:  # ended, but not by us: the camera stopped streaming
                await self._failed(StreamClosed("the camera stopped streaming"))

    async def _failed(self, error: BaseException) -> None:
        logger.error("stacked_camera.stream_failed", error=str(error))
        self._error = error
        self._end_consumers(error)
        with contextlib.suppress(Exception):
            await self._stream.stop_stream()

    def _note(self, frame: Frame, source: FrameSubscription) -> None:
        if self._frames_seen == 0:
            self._first_ts = frame.timestamp
        else:
            self._exposed_after_first += frame.exposure
        gap = frame.timestamp - self._last_ts
        if self._frames_seen > 0:
            self._gaps.append(gap / frame.exposure)
        self._frames_seen += 1
        self._last_ts = frame.timestamp
        if (
            len(self._gaps) == self._gaps.maxlen
            and not self._too_fast
            and max(self._gaps) < TOO_FAST_RATIO
        ):
            interval = round(statistics.median(self._gaps) * frame.exposure, 3)
            logger.warning(
                "stacked_camera.stream_too_fast",
                exposure=frame.exposure,
                interval=interval,
            )
            self._too_fast = True
        self._source_dropped = source.dropped
