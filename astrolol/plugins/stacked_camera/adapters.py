"""The two virtual cameras built on one real camera.

``StackedCamera`` takes exposures of any length by adding the short frames of the shared stream;
``FastCamera`` hands those short frames to whoever asks for a stream (the guider). Both stand in
the device manager like any other camera, so the imager, the sequencer and the guider need no
changes. They share one physical stream through ``SourceHub``.
"""

from __future__ import annotations

import asyncio
import contextlib
import dataclasses
import math
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, ClassVar

import structlog

from astrolol.core.errors import ExposureHalted
from astrolol.devices.base.interfaces import IPulseGuider
from astrolol.devices.base.models import CameraStatus, DeviceState, ExposureParams, Image
from astrolol.devices.base.pulse import PulseDirection
from astrolol.devices.base.streaming import (
    Frame,
    FrameBroadcaster,
    FrameSubscription,
    StreamClosed,
    StreamParams,
    StreamRoi,
)
from astrolol.plugins.stacked_camera.accumulator import SumAccumulator
from astrolol.plugins.stacked_camera.events import StackProgress
from astrolol.plugins.stacked_camera.fits import StackInfo, write_stack_fits
from astrolol.plugins.stacked_camera.hub import (
    TOO_FAST_RATIO,
    Lease,
    SourceHub,
    StackSink,
    SubParams,
)
from astrolol.plugins.stacked_camera.hubs import HubRegistry

logger = structlog.get_logger()

STACKED_KEY = "stacked_camera_long"
FAST_KEY = "stacked_camera_fast"

# A frame is stamped when it reaches us, some time after the sensor finished it. A sub counts as
# started after the request if it began no more than this long before it (an allowance for that
# delay, not for light that was there before the request).
LATENCY_ALLOWANCE = 0.3
# How long to wait for the next sub, beyond its own exposure, before giving up on the camera.
FRAME_WAIT_EXTRA = 30.0
# From this sub length on, a frame arriving sooner than half a sub after the previous one cannot
# be a sub of that length (below it, arrival-time jitter is too large to tell).
PACE_CHECK_FROM = 0.5


class _VirtualCamera:
    """What both virtual cameras share: the real camera they stand for."""

    _hubs: ClassVar[HubRegistry]  # set on the subclasses the plugin registers
    DEFAULT_CONNECT_PARAMS: ClassVar[dict[str, Any]] = {"source_id": ""}

    def __init__(self, source_id: str = "", **_: object) -> None:
        self._source_id = source_id

    def _source(self) -> Any:
        return self._hubs.camera(self._source_id)

    async def connect(self) -> None:
        self._source()  # refuses with a clear reason when the real camera is not connected
        await self._learn_source()

    async def _learn_source(self) -> None:
        try:
            await self._hubs.probe(self._source_id)
        except Exception as exc:  # the cards are a nicety, never a reason to refuse a camera
            logger.warning("stacked_camera.probe_error", error=str(exc))

    async def disconnect(self) -> None:
        pass

    async def set_cooler(self, enabled: bool, target_temperature: float | None) -> None:
        await self._source().set_cooler(enabled, target_temperature)

    async def ping(self) -> bool:
        try:
            return bool(await self._source().ping())
        except Exception:
            return False

    async def _source_status(self) -> CameraStatus | None:
        try:
            return await self._source().get_status()  # type: ignore[no-any-return]
        except Exception:
            return None


class StackedCamera(_VirtualCamera):
    """Exposures of any length, made of the short frames of the shared stream."""

    ADAPTER_KEY: ClassVar[str] = STACKED_KEY
    _bound_images_dir: ClassVar[Path | None] = None  # set on the registered subclass

    def __init__(
        self, source_id: str = "", images_dir: Path | None = None, **params: object
    ) -> None:
        super().__init__(source_id, **params)
        self._images_dir = images_dir or self._bound_images_dir
        self._counter = 0
        self._abort: asyncio.Event | None = None

    @property
    def exposing(self) -> bool:
        return self._abort is not None

    async def disconnect(self) -> None:
        await self.abort()

    async def abort(self) -> None:
        if self._abort is not None:
            self._abort.set()

    async def get_status(self) -> CameraStatus:
        status = await self._source_status()
        if status is None:
            return CameraStatus(state=DeviceState.ERROR)
        busy = self.exposing
        return status.model_copy(
            update={"state": DeviceState.BUSY if busy else DeviceState.CONNECTED}
        )

    async def expose(self, params: ExposureParams) -> Image:
        if self._abort is not None:
            raise RuntimeError("an exposure is already running")
        abort = self._abort = asyncio.Event()
        try:
            return await self._expose(params, abort)
        finally:
            self._abort = None

    @staticmethod
    def plan(duration: float, sub_exposure: float) -> tuple[float, int]:
        """(length of each sub, number of subs). An exposure shorter than a sub is one sub of
        that length; otherwise the exposure is rounded up to a whole number of subs."""
        if duration <= sub_exposure:
            return duration, 1
        return sub_exposure, math.ceil(duration / sub_exposure - 1e-9)

    async def _expose(self, params: ExposureParams, abort: asyncio.Event) -> Image:
        await self._learn_source()  # no-op once known; retries if the stream was busy at connect
        hub = await self._hubs.hub(self._source_id)
        sub_exposure, total = self.plan(params.duration, self._hubs.sub_exposure())
        current = hub.params
        wanted = SubParams(
            exposure=sub_exposure,
            gain=params.gain if params.gain is not None else current.gain,
            binning=params.binning,
        )
        await hub.configure(wanted)
        lease = await hub.acquire()
        sink = hub.open_sink()
        device_id = self._device_id()
        accumulator = SumAccumulator()
        requested = time.monotonic()
        previous: float | None = None  # when the last frame arrived
        first_start: datetime | None = None
        try:
            await self._progress(device_id, True, accumulator, total, sub_exposure)
            while accumulator.count < total:
                frame = await self._next_frame(sink, abort, sub_exposure)
                if hub.stats.too_fast:
                    raise RuntimeError(
                        "The camera sends frames far faster than the exposure asked for, so a "
                        "stack of them would carry the wrong exposure time. Try again; if it keeps "
                        "happening, this camera's stream does not honour its exposure"
                    )
                too_soon = (
                    previous is not None
                    and frame.exposure >= PACE_CHECK_FROM
                    and frame.timestamp - previous < TOO_FAST_RATIO * frame.exposure
                )
                previous = frame.timestamp
                if too_soon or not self._counts(frame, requested, wanted):
                    continue
                if first_start is None:
                    began = frame.timestamp - frame.exposure
                    first_start = datetime.now(UTC) - timedelta(seconds=time.monotonic() - began)
                accumulator.add(frame.pixels, frame.exposure)
                await self._progress(device_id, True, accumulator, total, sub_exposure)
            return await self._finish(hub, wanted, accumulator, first_start, sink.dropped)
        finally:
            sink.close()
            await lease.release()
            await self._progress(device_id, False, accumulator, total, sub_exposure)

    @staticmethod
    def _counts(frame: Frame, requested: float, wanted: SubParams) -> bool:
        """Whether *frame* belongs in the stack: made for this request, with these settings."""
        started = frame.timestamp - frame.exposure
        return (
            started >= requested - LATENCY_ALLOWANCE
            and abs(frame.exposure - wanted.exposure) < 1e-6
            and frame.binning == wanted.binning
            and (wanted.gain is None or frame.gain in (None, wanted.gain))
        )

    @staticmethod
    async def _next_frame(sink: StackSink, abort: asyncio.Event, sub_exposure: float) -> Frame:
        getter = asyncio.ensure_future(sink.get())
        stop = asyncio.ensure_future(abort.wait())
        try:
            done, _ = await asyncio.wait(
                {getter, stop},
                timeout=sub_exposure + FRAME_WAIT_EXTRA,
                return_when=asyncio.FIRST_COMPLETED,
            )
            if stop in done:
                raise ExposureHalted("Exposure halted")
            if getter not in done:
                raise RuntimeError(
                    f"The camera sent no frame for {sub_exposure + FRAME_WAIT_EXTRA:.0f} s"
                )
            try:
                return getter.result()
            except StreamClosed as exc:
                reason = exc.__cause__ or exc
                raise RuntimeError(f"The camera stopped streaming: {reason}") from reason
        finally:
            for task in (getter, stop):
                task.cancel()
            await asyncio.gather(getter, stop, return_exceptions=True)

    async def _finish(
        self,
        hub: SourceHub,
        wanted: SubParams,
        accumulator: SumAccumulator,
        first_start: datetime | None,
        dropped: int,
    ) -> Image:
        status = await self._source_status()
        shape = accumulator.shape
        assert shape is not None and first_start is not None  # at least one sub was added
        if dropped:
            logger.warning("stacked_camera.subs_dropped", count=dropped)
        info = StackInfo(
            subs=accumulator.count,
            exposure=accumulator.exposure,
            start=first_start,
            gain=wanted.gain,
            binning=wanted.binning,
            temperature=None if status is None else status.temperature,
            dropped=dropped,
            full_scale=accumulator.full_scale,
            extra=self._camera_cards(wanted.binning),
        )
        self._counter += 1
        directory = self._images_dir or _default_images_dir()
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"stacked_{self._counter:06d}.fits"
        await asyncio.to_thread(write_stack_fits, path, accumulator.result(), info)
        logger.info(
            "stacked_camera.exposure_done", subs=accumulator.count, exposure=accumulator.exposure
        )
        return Image(
            fits_path=str(path),
            width=shape[1],
            height=shape[0],
            exposure_duration=accumulator.exposure,
            gain=wanted.gain,
        )

    def _camera_cards(self, binning: int) -> dict[str, tuple[object, str]]:
        cards = self._hubs.cards(self._source_id)
        return {} if cards is None else cards.for_binning(binning)

    def _device_id(self) -> str:
        return self._hubs.device_id_of(self) or self._source_id

    async def _progress(
        self,
        device_id: str,
        active: bool,
        accumulator: SumAccumulator,
        total: int,
        sub_exposure: float,
    ) -> None:
        await self._hubs.event_bus.publish(
            StackProgress(
                device_id=device_id,
                active=active,
                subs_done=accumulator.count,
                subs_total=total,
                exposure_done=accumulator.exposure,
                exposure_total=total * sub_exposure,
            )
        )


class FastCamera(_VirtualCamera):
    """The short frames of the shared stream, for the guider and anything else that streams."""

    ADAPTER_KEY: ClassVar[str] = FAST_KEY

    def __init__(self, source_id: str = "", **params: object) -> None:
        super().__init__(source_id, **params)
        self._broadcaster = FrameBroadcaster()
        self._lease: Lease | None = None
        self._sub: FrameSubscription | None = None
        self._pump: asyncio.Task[None] | None = None
        self._roi: StreamRoi | None = None

    @property
    def can_stream(self) -> bool:
        return True

    @property
    def streaming(self) -> bool:
        return self._lease is not None

    async def connect(self) -> None:
        source = self._source()
        await self._learn_source()
        if isinstance(source, IPulseGuider):
            # An ST4 output on the real camera guides through this one too. Set per instance
            # so a camera without one does not claim to pulse guide.
            self.pulse_guide = self._pulse_guide

    async def _pulse_guide(self, direction: PulseDirection, duration_ms: int) -> None:
        await self._source().pulse_guide(direction, duration_ms)

    async def disconnect(self) -> None:
        await self.stop_stream()

    async def abort(self) -> None:
        pass

    async def expose(self, params: ExposureParams) -> Image:
        raise RuntimeError(
            "This camera only streams short frames: use the stacked camera for exposures"
        )

    async def get_status(self) -> CameraStatus:
        status = await self._source_status()
        if status is None:
            return CameraStatus(state=DeviceState.ERROR)
        state = DeviceState.BUSY if self.streaming else DeviceState.CONNECTED
        return status.model_copy(update={"state": state})

    def subscribe_frames(self) -> FrameSubscription:
        return self._broadcaster.subscribe()

    async def start_stream(self, params: StreamParams) -> None:
        if self._lease is not None:
            raise RuntimeError("already streaming")
        hub = await self._hubs.hub(self._source_id)
        await self._adopt(hub, params)
        lease = await hub.acquire()
        self._lease = lease
        self._sub = hub.subscribe_frames()
        self._roi = params.roi
        self._pump = asyncio.create_task(self._run(self._sub))

    async def stop_stream(self) -> None:
        task, self._pump = self._pump, None
        sub, self._sub = self._sub, None
        lease, self._lease = self._lease, None
        if sub is not None:
            sub.close()
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        if lease is not None:
            await lease.release()
        self._broadcaster.end()

    async def _adopt(self, hub: SourceHub, params: StreamParams) -> None:
        """Fit the shared stream to this request as far as a stack running on it allows.

        The sub-exposure is the plugin's, not the stream request's. Gain and binning are the
        request's, unless a stack is already running on the stream: it keeps its own.
        """
        current = hub.params
        gain = params.gain if params.gain is not None else current.gain
        if hub.leases == 0:
            await hub.configure(
                SubParams(self._hubs.sub_exposure(), gain=gain, binning=params.binning)
            )
            current = hub.params
        elif (gain, params.binning) != (current.gain, current.binning):
            logger.warning(
                "stacked_camera.stream_settings_kept",
                asked_gain=params.gain,
                asked_binning=params.binning,
                gain=current.gain,
                binning=current.binning,
            )
        if abs(params.exposure - current.exposure) > 1e-6:
            logger.warning(
                "stacked_camera.stream_exposure_kept", asked=params.exposure, used=current.exposure
            )

    async def _run(self, sub: FrameSubscription) -> None:
        try:
            async for frame in sub:
                self._broadcaster.publish(self._cropped(frame))
        except StreamClosed as exc:  # the real camera failed
            self._broadcaster.end(exc.__cause__ or exc)
        else:
            self._broadcaster.end()

    def _cropped(self, frame: Frame) -> Frame:
        roi = self._roi
        if roi is None:
            return frame
        # The region is in sensor pixels; the frame says where its own corner sits on the sensor.
        x0 = max(0, roi.x - frame.origin[0])
        y0 = max(0, roi.y - frame.origin[1])
        x1 = min(frame.width, roi.x + roi.width - frame.origin[0])
        y1 = min(frame.height, roi.y + roi.height - frame.origin[1])
        if x1 <= x0 or y1 <= y0:
            return frame  # outside the frame: better a whole frame than none
        return dataclasses.replace(
            frame,
            pixels=frame.pixels[y0:y1, x0:x1],
            origin=(frame.origin[0] + x0, frame.origin[1] + y0),
        )


def _default_images_dir() -> Path:
    from astrolol.config.settings import settings

    return settings.images_dir


def bind_adapters(
    hubs: HubRegistry, images_dir: Path | None = None
) -> tuple[type[StackedCamera], type[FastCamera]]:
    """The two adapter classes wired to *hubs*: the device manager builds adapters from params
    alone, so what they share comes with the class. Nothing lives at module level."""
    stacked = type(
        "StackedCameraAdapter",
        (StackedCamera,),
        {"_hubs": hubs, "_bound_images_dir": images_dir},
    )
    fast = type("FastCameraAdapter", (FastCamera,), {"_hubs": hubs})
    return stacked, fast
