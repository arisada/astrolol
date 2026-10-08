"""BuiltinGuider — astrolol's own autoguider, implementing the ``Guider`` protocol.

One background task per guiding run: stream frames from the guide camera, pick the guide stars
in the first one, restrict the stream to a window around them, calibrate (unless a calibration
is already known), then for every frame measure the star windows and pulse the mount.
"""

from __future__ import annotations

import asyncio
import contextlib
import math
import random
import time
from dataclasses import dataclass
from typing import Any, Literal, Protocol

import structlog

from astrolol.core.guiding import (
    GuiderBusy,
    GuiderError,
    GuiderNotConnected,
    GuiderStatus,
    GuidingHealth,
    GuidingStats,
    SettleFailed,
    SettleParams,
)
from astrolol.core.guiding.events import GuidingSettled, GuidingStateChanged
from astrolol.core.guiding.health import GuidingHealthTracker
from astrolol.devices.base.interfaces import IPulseGuider, IStreamingCamera
from astrolol.devices.base.streaming import Frame, FrameSubscription, StreamClosed, StreamParams, StreamRoi
from plugins.guider.calibration import Calibration, calibrate
from plugins.guider.controller import AxisSettings, DecMode, GuideController
from plugins.guider.darks import Dark, DarkLibrary, make_dark
from plugins.guider.events import GuiderStep
from plugins.guider.settings import GuiderSettings
from plugins.guider.stars import Star, detect_stars, select_guide_stars
from plugins.guider.tracker import StarTracker, TrackerResult
from plugins.guider.view import GuideView, OverlayStar

logger = structlog.get_logger()

ROI_PADDING = 48  # pixels around the outermost guide star
ROI_MAX_FRACTION = 0.6  # a window covering more of the frame than this is not worth it
MEASURE_TRIES = 6  # frames to wait for a usable star position before giving up on a measurement
REACQUIRE_RADIUS = 60  # pixels searched around a star's last position when it has gone missing
MAX_BLURRED_FRAMES = 10  # a star smeared this many frames in a row counts as lost


def window_half(stars: list[Star]) -> int:
    """Half-size of the measuring window: wide enough for the stars as they are, defocused or not."""
    return int(min(max(math.ceil(1.5 * max(s.fwhm for s in stars)), 8), 30))


class GuideDevices(Protocol):
    """Where the guider gets its hardware. Called at the start of each guiding run."""

    def camera(self) -> IStreamingCamera:
        """Raises GuiderNotConnected when there is no usable guide camera."""
        ...

    def pulse_guider(self) -> IPulseGuider:
        """Raises GuiderNotConnected / PulseGuideNotSupported."""
        ...


@dataclass
class _Settle:
    after: Literal["guide", "dither"]
    params: SettleParams
    future: asyncio.Future[None]
    started: float | None = None  # when the timeout starts (once guiding is running)
    ok_since: float | None = None


class BuiltinGuider:
    name = "builtin"

    def __init__(
        self,
        bus: Any,
        settings: GuiderSettings,
        devices: GuideDevices,
        darks: DarkLibrary | None = None,
        *,
        ra: AxisSettings | None = None,
        dec: AxisSettings | None = None,
        dec_mode: DecMode = "auto",
    ) -> None:
        self._bus = bus
        self.settings = settings
        self._devices = devices
        self.darks = darks or DarkLibrary()
        self._ra, self._dec, self._dec_mode = ra, dec, dec_mode
        self.calibration: Calibration | None = None
        self._health = GuidingHealthTracker()
        self._task: asyncio.Task[None] | None = None
        self._state = "Stopped"
        self._paused = False
        self._settle: _Settle | None = None
        self._tracker: StarTracker | None = None
        self._controller: GuideController | None = None
        self._pulse_end = 0.0
        # Seconds between frames as observed (drivers do not always honour the exposure we ask
        # for); a frame only shows a pulse if it arrives a full period after the pulse ended.
        self._capturing_dark = False
        self.view = GuideView()
        self._preview: asyncio.Task[None] | None = None
        self._period = 0.0
        self._last_frame_at: float | None = None
        self._last_frame_seq = 0

    # ── Guider protocol ──────────────────────────────────────────────────

    def status(self) -> GuiderStatus:
        return GuiderStatus(
            guider=self.name,
            connected=True,
            state="Previewing" if self._previewing else "Paused" if self._paused and self._running else self._state,
            guiding=self._health.guiding,
            active=self._running or self._capturing_dark,
            settling=self._settle is not None,
            pixel_scale=self.settings.pixel_scale,
        )

    def health(self) -> GuidingHealth:
        return self._health.health()

    def mark(self) -> float:
        return self._health.mark()

    def stats(self, since: float, until: float | None = None) -> GuidingStats:
        return self._health.stats(since, until)

    @property
    def _previewing(self) -> bool:
        return self._preview is not None and not self._preview.done()

    @property
    def _running(self) -> bool:
        return self._task is not None and not self._task.done()

    async def guide(
        self, settle: SettleParams, *, recalibrate: bool = False, wait_settle: bool = True
    ) -> None:
        if self._capturing_dark:
            raise GuiderBusy("Taking darks")
        await self.stop_preview()
        if self._running and recalibrate:
            await self.stop()
        if self._running:
            if self._settle is not None:
                raise GuiderBusy("Already settling")
            request = self._begin_settle("guide", settle, started=time.monotonic())
        else:
            request = self._begin_settle("guide", settle)
            if recalibrate:
                self.calibration = None
            self._task = asyncio.create_task(self._run(), name="builtin_guider")
        if wait_settle:
            await request.future
        else:
            request.future.add_done_callback(lambda f: f.cancelled() or f.exception())

    async def stop(self) -> None:
        task, self._task = self._task, None
        if task is None:
            return
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    async def dither(self, pixels: float, ra_only: bool, settle: SettleParams) -> None:
        if not self._running or self._paused or self._tracker is None or self.calibration is None:
            raise GuiderError("Cannot dither: not guiding")
        if self._settle is not None:
            raise GuiderBusy("Already settling")
        angle = random.choice((0.0, math.pi)) if ra_only else random.uniform(0, 2 * math.pi)
        shift = self.calibration.sensor_shift(pixels * math.cos(angle), pixels * math.sin(angle))
        self._tracker.shift_lock(*shift)
        if self._controller is not None:
            self._controller.reset()
        logger.info("guider.dither", pixels=pixels, ra_only=ra_only, shift=shift)
        request = self._begin_settle("dither", settle, started=time.monotonic())
        await request.future

    async def pause(self) -> None:
        if self._running and not self._paused:
            self._paused = True
            await self._lost("paused")

    async def resume(self) -> None:
        self._paused = False
        if self._controller is not None:
            self._controller.reset()

    async def start_preview(self) -> None:
        """Show what the guide camera sees, with the stars the guider would pick."""
        if self._running or self._capturing_dark:
            raise GuiderBusy("Already guiding")
        if self._previewing:
            return
        camera = self._devices.camera()  # fail here, in the caller's request, if there is none
        self._preview = asyncio.create_task(self._preview_loop(camera), name="guider_preview")

    async def stop_preview(self) -> None:
        task, self._preview = self._preview, None
        if task is None:
            return
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    async def _preview_loop(self, camera: IStreamingCamera) -> None:
        cfg = self.settings
        sub = camera.subscribe_frames()
        self._restarted_stream()
        try:
            await camera.start_stream(StreamParams(exposure=cfg.exposure, gain=cfg.gain))
            analysed = 0.0
            while True:
                frame = await self._next_frame(sub, 0.0)
                now = time.monotonic()
                if now - analysed < 1.0:  # finding stars costs far more than showing a frame
                    self.view.update(frame, self.view.info().stars, "preview")
                    continue
                analysed = now
                chosen, found = await asyncio.to_thread(self._pick_stars, frame)
                self.view.update(frame, self._candidates(chosen, found), "preview")
        except (StreamClosed, asyncio.TimeoutError) as exc:
            logger.warning("guider.preview_ended", error=str(exc))
        finally:
            sub.close()
            with contextlib.suppress(Exception):
                await asyncio.shield(camera.stop_stream())
            self.view.go_idle()

    async def capture_dark(self, count: int = 10) -> Dark:
        """Stack *count* frames taken with the current exposure and gain into a dark.

        The scope must be covered. Frames use the guide settings, because a dark only applies
        to frames taken with exactly those.
        """
        if self._running or self._capturing_dark:
            raise GuiderBusy("Stop guiding before taking darks")
        await self.stop_preview()
        camera = self._devices.camera()
        cfg = self.settings
        self._capturing_dark = True
        self._state = "Capturing dark"
        sub = camera.subscribe_frames()
        try:
            self._restarted_stream()
            since = time.monotonic()
            await camera.start_stream(StreamParams(exposure=cfg.exposure, gain=cfg.gain))
            await self._next_frame(sub, since)  # the first frame may predate the stream
            frames = [await self._next_frame(sub, since) for _ in range(count)]
        except StreamClosed as exc:
            raise GuiderError(f"The guide camera stream ended: {exc.__cause__ or exc}") from exc
        finally:
            sub.close()
            with contextlib.suppress(Exception):
                await asyncio.shield(camera.stop_stream())
            self._capturing_dark = False
            self._state = "Stopped"
        dark = await asyncio.to_thread(make_dark, frames)
        self.darks.add(dark)
        logger.info("guider.dark_captured", frames=count, hot_pixels=int(dark.hot.sum()))
        return dark

    # ── The guiding run ──────────────────────────────────────────────────

    async def _run(self) -> None:
        camera: IStreamingCamera | None = None
        sub: FrameSubscription | None = None
        error: BaseException | None = None
        try:
            camera = self._devices.camera()
            pulser = self._devices.pulse_guider()
            cfg = self.settings
            params = StreamParams(exposure=cfg.exposure, gain=cfg.gain)
            self._pulse_end = 0.0
            self._restarted_stream()

            self._state = "Selecting star"
            sub = camera.subscribe_frames()
            await camera.start_stream(params)
            first = await self._next_frame(sub, 0.0)
            stars, detected = await asyncio.to_thread(self._pick_stars, first)
            self.view.update(first, self._candidates(stars, detected), "guiding")
            if not stars:
                raise GuiderError("No suitable guide star in the frame")
            logger.info("guider.stars_selected", count=len(stars), primary=(round(stars[0].x, 1), round(stars[0].y, 1)))
            # Window wide enough for the stars as they are (defocused ones are broad).
            half = window_half(stars)
            tracker = self._tracker = StarTracker(stars, self.darks, half=half)
            tracker.refresh(first)

            roi = self._roi_for(stars, first, half)
            if roi is not None:  # the driver now sends only the window we track
                sub.close()
                await camera.stop_stream()
                sub = camera.subscribe_frames()
                since = time.monotonic()
                await camera.start_stream(params.model_copy(update={"roi": roi}))
                if not await self._rereference(sub, tracker, since):
                    # The driver did not give us the region we asked for: track in full frames.
                    logger.warning("guider.roi_ignored", roi=roi.model_dump())
                    sub.close()
                    await camera.stop_stream()
                    sub = camera.subscribe_frames()
                    since = time.monotonic()
                    await camera.start_stream(params)
                    await self._rereference(sub, tracker, since)

            async def measure() -> tuple[float, float]:
                """The guide star's position in a frame taken after the last pulse.

                A star smeared by the pulse (it moved during the exposure) or briefly missing
                is waited out; one that moved out of its window is searched for.
                """
                for attempt in range(MEASURE_TRIES):
                    frame = await self._next_frame(sub, self._usable_after_pulse())
                    result = tracker.update(frame)
                    if result.readings[0].state == "lost" and attempt >= 1:
                        if tracker.reacquire(frame, REACQUIRE_RADIUS, indices=[0]):
                            result = tracker.update(frame)
                    self._show(frame, result, tracker)
                    reading = result.readings[0]
                    if reading.state == "ok" and reading.star is not None:
                        return reading.star.x, reading.star.y
                    logger.debug("guider.measure_retry", attempt=attempt, state=reading.state)
                raise GuiderError(f"Lost the guide star during calibration ({MEASURE_TRIES} frames without it)")

            async def pulse(direction, ms) -> None:  # noqa: ANN001
                await pulser.pulse_guide(direction, ms)
                self._pulse_end = time.monotonic()

            fresh_calibration = self.calibration is None
            if self.calibration is None:
                self._state = "Calibrating"
                self.calibration = await calibrate(
                    measure, pulse, steps=cfg.calibration_steps
                )
                logger.info("guider.calibrated", **self.calibration.model_dump(exclude={"trace"}), points=len(self.calibration.trace))
            tracker.reset_lock()
            self._controller = GuideController(
                self.calibration, self._ra, self._dec, self._dec_mode,
                compensate_backlash=cfg.dec_backlash_compensation,
                last_dec_dir=-1 if fresh_calibration else 0,  # calibration ends with South pulses
            )

            self._state = "Guiding"
            await self._guide_loop(sub, tracker, pulser)
        except asyncio.CancelledError:
            raise
        except StreamClosed as exc:
            error = GuiderError(f"The guide camera stream ended: {exc.__cause__ or exc}")
        except Exception as exc:
            error = exc
            logger.error("guider.run_failed", error=str(exc), exc_info=not isinstance(exc, GuiderError))
        finally:
            await self._finish(camera, sub, error)

    async def _guide_loop(self, sub: FrameSubscription, tracker: StarTracker, pulser: IPulseGuider) -> None:
        cfg = self.settings
        assert self.calibration is not None and self._controller is not None
        scale = cfg.pixel_scale or 1.0
        lost_since: float | None = None
        blurred_frames = 0
        while True:
            frame = await self._next_frame(sub, self._usable_after_pulse())
            now = time.monotonic()
            result = tracker.update(frame)
            self._show(frame, result, tracker)
            await self._check_settle_timeout(now)
            if result.dx is None or result.dy is None:
                if result.blurred and blurred_frames < MAX_BLURRED_FRAMES:
                    blurred_frames += 1  # smeared by a pulse or by wind: its position is not to be trusted
                    continue
                lost_since = lost_since or now
                if now - lost_since > self._frame_wait * 2:
                    await self._lost("star_lost")
                    tracker.reacquire(frame, REACQUIRE_RADIUS)
                if now - lost_since > cfg.lost_timeout_s:
                    raise GuiderError("Guide star lost")
                continue
            lost_since = None
            blurred_frames = 0
            ra_px, dec_px = self.calibration.axis_error(result.dx, result.dy)
            if self._health.on_step(ra_px * scale, dec_px * scale):
                await self._bus.publish(GuidingStateChanged(guider=self.name, guiding=True))
            await self._update_settle(now, math.hypot(result.dx, result.dy))
            if self._paused:
                continue
            pulses = self._controller.correct(result.dx, result.dy)
            await self._bus.publish(
                GuiderStep(
                    frame=frame.seq,
                    ra_dist=ra_px * scale,
                    dec_dist=dec_px * scale,
                    ra_corr=sum(ms if d == "W" else -ms for d, ms in pulses if d in "WE"),
                    dec_corr=sum(ms if d == "N" else -ms for d, ms in pulses if d in "NS"),
                    star_snr=result.readings[0].star.snr if result.readings[0].star else None,
                    stars_found=result.found,
                )
            )
            if pulses:
                await asyncio.gather(*(pulser.pulse_guide(d, ms) for d, ms in pulses))
                self._pulse_end = time.monotonic()

    async def _finish(
        self, camera: IStreamingCamera | None, sub: FrameSubscription | None, error: BaseException | None
    ) -> None:
        if sub is not None:
            sub.close()
        if camera is not None:
            with contextlib.suppress(Exception):
                await asyncio.shield(camera.stop_stream())
        self._state = "Stopped"
        self._paused = False
        self.view.go_idle()
        self._tracker = None
        self._controller = None
        await self._lost("stopped" if error is None else "error")
        if self._settle is not None:
            exc = error if isinstance(error, GuiderError) else GuiderError(str(error)) if error else None
            await self._end_settle(exc or SettleFailed("guiding stopped while settling"))

    # ── Helpers ──────────────────────────────────────────────────────────

    def _pick_stars(self, frame: Frame) -> tuple[list[Star], list[Star]]:
        """(the stars to guide on, every star detected)."""
        found = detect_stars(frame, self.darks)
        return select_guide_stars(found, self.settings.star_count), found

    @staticmethod
    def _candidates(chosen: list[Star], found: list[Star]) -> list[OverlayStar]:
        picked = {id(s): i for i, s in enumerate(chosen)}
        return [
            OverlayStar(
                x=s.x, y=s.y, snr=s.snr, fwhm=s.fwhm, half=window_half([s]),
                kind="candidate" if id(s) not in picked else "primary" if picked[id(s)] == 0 else "companion",
            )
            for s in found
        ]

    def _show(self, frame: Frame, result: TrackerResult, tracker: StarTracker) -> None:
        stars = []
        for i, (reading, last) in enumerate(zip(result.readings, tracker.last_positions)):
            star = reading.star
            stars.append(
                OverlayStar(
                    x=star.x if star else last[0], y=star.y if star else last[1],
                    kind="lost" if star is None else "primary" if i == 0 else "companion",
                    snr=star.snr if star else None, fwhm=star.fwhm if star else None, half=tracker.half,
                )
            )
        self.view.update(frame, stars, "guiding", tracker.lock_positions)

    def _roi_for(self, stars: list[Star], frame: Frame, half: int) -> StreamRoi | None:
        pad = ROI_PADDING + half
        x0 = max(int(min(s.x for s in stars)) - pad, 0)
        y0 = max(int(min(s.y for s in stars)) - pad, 0)
        x1 = min(int(max(s.x for s in stars)) + pad + 1, frame.origin[0] + frame.width)
        y1 = min(int(max(s.y for s in stars)) + pad + 1, frame.origin[1] + frame.height)
        if (x1 - x0) * (y1 - y0) >= ROI_MAX_FRACTION * frame.width * frame.height:
            return None
        return StreamRoi(x=x0, y=y0, width=x1 - x0, height=y1 - y0)

    async def _rereference(self, sub: FrameSubscription, tracker: StarTracker, since: float) -> int:
        """Re-measure the reference flux after a stream restart; returns the stars found.

        A restart can change the image: the first frame may still belong to the old stream, and
        a window or a mode may be rendered at a different brightness. The first frame is
        discarded and the second becomes the reference.
        """
        self._restarted_stream()
        await self._next_frame(sub, since)
        return tracker.refresh(await self._next_frame(sub, since))

    @property
    def _frame_wait(self) -> float:
        return max(self.settings.exposure, self._period)

    def _usable_after_pulse(self) -> float:
        return self._pulse_end + self._frame_wait

    async def _next_frame(self, sub: FrameSubscription, newer_than: float, *, timeout: float | None = None) -> Frame:
        """The next frame that arrived at or after *newer_than* (monotonic time).

        Frames older than the last pulse show the star before it moved: using them makes the
        loop correct twice for one error. Also learns the frame period from the arrivals.
        """
        async with asyncio.timeout(timeout if timeout is not None else self._frame_wait * 5 + 15):
            while True:
                frame = await sub.get()
                if self._last_frame_at is not None and frame.seq > self._last_frame_seq:
                    # Per frame: the ones skipped while we waited on a pulse still took time.
                    gap = (frame.timestamp - self._last_frame_at) / (frame.seq - self._last_frame_seq)
                    self._period = gap if self._period == 0.0 else 0.7 * self._period + 0.3 * gap
                self._last_frame_at, self._last_frame_seq = frame.timestamp, frame.seq
                if frame.timestamp >= newer_than:
                    return frame

    def _restarted_stream(self) -> None:
        self._last_frame_at = None
        self._last_frame_seq = 0
        self._period = 0.0

    async def _lost(self, reason: str) -> None:
        if self._health.on_lost(reason):
            await self._bus.publish(
                GuidingStateChanged(
                    guider=self.name, guiding=False, reason=reason,
                    notify="warning", notify_title="Guiding stopped",
                    notify_body=f"{self.name} guiding stopped: {reason}",
                )
            )

    # ── Settling ─────────────────────────────────────────────────────────

    def _begin_settle(
        self, after: Literal["guide", "dither"], params: SettleParams, started: float | None = None
    ) -> _Settle:
        request = _Settle(after, params, asyncio.get_running_loop().create_future(), started)
        self._settle = request
        return request

    async def _check_settle_timeout(self, now: float) -> None:
        s = self._settle
        if s is not None and s.started is not None and now - s.started > s.params.timeout:
            await self._end_settle(SettleFailed("timed-out waiting for guider to settle"))

    async def _update_settle(self, now: float, error_px: float) -> None:
        s = self._settle
        if s is None:
            return
        if s.started is None:
            s.started = now
        if error_px > s.params.pixels:
            s.ok_since = None
        elif s.ok_since is None:
            s.ok_since = now
        if s.ok_since is not None and now - s.ok_since >= s.params.time:
            await self._end_settle(None)

    async def _end_settle(self, error: Exception | None) -> None:
        s, self._settle = self._settle, None
        if s is None or s.future.done():
            return
        if error is None:
            s.future.set_result(None)
        else:
            s.future.set_exception(error)
        await self._bus.publish(
            GuidingSettled(guider=self.name, after=s.after, error=None if error is None else str(error))
        )
        logger.info("guider.settled", after=s.after, error=None if error is None else str(error))
