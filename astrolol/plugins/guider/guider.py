"""BuiltinGuider — astrolol's own autoguider, implementing the ``Guider`` protocol.

One background task per guiding run: stream frames from the guide camera, pick the guide stars
in the first one, restrict the stream to a window around them, calibrate (unless a calibration
is already known), then for every frame measure the star windows and pulse the mount.

A run is meant to survive what a night throws at it: a frame where a satellite or a hot pixel
moves the star is ignored, a refused pulse or a stuck camera is retried, a star lost to clouds
is looked for (in the whole frame after a while) until it comes back, and guiding that pushes
the star the wrong way (a meridian flip guessed wrong) turns the axis round. It stops on its
own only when the mount slews: what it was locked on is gone.
"""

from __future__ import annotations

import asyncio
import contextlib
import math
import random
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Protocol

import numpy as np
import structlog
from pydantic import BaseModel

from astrolol.core.guiding import (
    GuiderBusy,
    GuiderError,
    GuiderStatus,
    GuidingHealth,
    GuidingStats,
    SettleFailed,
    SettleParams,
)
from astrolol.core.guiding.events import GuidingSettled, GuidingStateChanged
from astrolol.core.guiding.health import GuidingHealthTracker
from astrolol.devices.base.interfaces import IPulseGuider, IStreamingCamera
from astrolol.devices.base.pulse import PulseDirection
from astrolol.devices.base.streaming import Frame, FrameSubscription, StreamClosed, StreamParams, StreamRoi
from astrolol.plugins.guider.calibration import Calibration, CalibrationFailed, CalibrationPoint, calibrate
from astrolol.plugins.guider.controller import AxisSettings, DecMode, GuideController
from astrolol.plugins.guider.darks import Dark, DarkLibrary, make_dark
from astrolol.plugins.guider.devices import MountState
from astrolol.plugins.guider.events import GuiderStep
from astrolol.plugins.guider.settings import GuiderSettings, auto_min_move_px
from astrolol.plugins.guider.stars import Star, detect_stars, select_guide_stars
from astrolol.plugins.guider.tracker import StarTracker, TrackerResult
from astrolol.plugins.guider.view import GuideView, OverlayStar

logger = structlog.get_logger()

ROI_PADDING = 48  # pixels around the outermost guide star (at least the calibration travel)
ROI_MAX_FRACTION = 0.6  # a window covering more of the frame than this is not worth it
ROI_EDGE = 10  # a star or lock this close to the window's edge moves the window
MEASURE_TRIES = 6  # frames to wait for a usable star position before giving up on a measurement
REACQUIRE_RADIUS = 60  # pixels searched around a star's last position when it has gone missing
MAX_BLURRED_FRAMES = 10  # a star smeared this many frames in a row counts as lost
FULL_SEARCH_AFTER_S = 10.0  # lost this long (and at least 5 frames): look in the whole frame
FULL_SEARCH_EVERY_S = 3.0  # a full-frame search costs; not on every frame
JUMP_WARMUP = 5  # frames before the jump check trusts its noise estimate
JUMP_FRAMES = 3  # frames in a row at a new place before a jump is believed
REVERSAL_VOTES = 3  # corrections in a row that moved the star the wrong way
MAX_REVERSALS = 2  # beyond this the calibration is plainly wrong: stop
PULSE_FAILURES_LOST = 3  # refused pulses in a row: the mount is not being guided
STREAM_RETRIES = 4  # camera restarts before giving up
MOUNT_POLL_S = 2.0


def window_half(stars: list[Star]) -> int:
    """Half-size of the measuring window: wide enough for the stars as they are, defocused or not."""
    return int(min(max(math.ceil(1.5 * max(s.fwhm for s in stars)), 8), 30))


class GuideDevices(Protocol):
    """Where the guider gets its hardware. Called at the start of each guiding run.

    May also provide ``async mount_state() -> MountState | None`` (see ``ManagerDevices``).
    """

    def camera(self) -> IStreamingCamera:
        """Raises GuiderNotConnected when there is no usable guide camera."""
        ...

    def pulse_guider(self) -> IPulseGuider:
        """Raises GuiderNotConnected / PulseGuideNotSupported."""
        ...


class CalibrationAttempt(BaseModel):
    """The calibration under way, or the last one that failed: what the UI draws meanwhile."""

    running: bool
    phase: str
    trace: list[CalibrationPoint] = []
    error: str | None = None


class Prediction(BaseModel):
    """The star's own motion as guiding has learnt it (arcsec, or pixels without a pixel scale)."""

    drift_ra: float  # per second
    drift_dec: float
    pe_period_s: float | None = None  # the periodic error being predicted, if any
    pe_amplitude: float | None = None  # peak to peak


class MountMoved(GuiderError):
    pass


@dataclass
class _Settle:
    after: Literal["guide", "dither"]
    params: SettleParams
    future: asyncio.Future[None]
    started: float | None = None  # when the timeout starts (once guiding is running)
    ok_since: float | None = None


class _JumpCheck:
    """Tells a real move of the star from a frame where something else moved it.

    Compares each measured position with where the last one and the pulses sent since would
    put it. A frame far off that is ignored; the same place three frames in a row is believed
    (a gust, a bumped tripod).
    """

    def __init__(self) -> None:
        self.prev: np.ndarray | None = None  # last accepted offset from the run's first lock
        self.expected = np.zeros(2)  # move the pulses since then should have caused
        self.var = 0.25  # px², noise of the innovation
        self.frames = 0
        self.suspects: list[np.ndarray] = []

    def reset(self) -> None:
        self.prev, self.suspects = None, []
        self.expected = np.zeros(2)

    def add_pulse(self, move: np.ndarray) -> None:
        self.expected = self.expected + move

    def accept(self, pos: np.ndarray) -> bool:
        if self.prev is None:
            self.prev, self.expected = pos, np.zeros(2)
            return True
        innovation = pos - self.prev - self.expected
        limit = max(1.5, 6.0 * math.sqrt(self.var)) + 0.5 * float(np.hypot(*self.expected))
        size = float(np.hypot(*innovation))
        if self.frames >= JUMP_WARMUP and size > limit:
            if self.suspects and float(np.hypot(*(pos - self.suspects[-1]))) > max(1.5, 3 * math.sqrt(self.var)):
                self.suspects = []  # not the same place as the last odd frame
            self.suspects.append(pos)
            if len(self.suspects) < JUMP_FRAMES:
                return False
            logger.warning("guider.star_moved", px=round(size, 1))
        elif size <= 3 * math.sqrt(self.var) + 0.3:
            # Only ordinary frames teach the noise: a run of large innovations (guiding going
            # the wrong way) must not raise the bar for noticing it.
            self.var += 0.1 * (size**2 - self.var)
        else:
            self.var += 0.02 * (min(size, 3 * math.sqrt(self.var) + 0.5) ** 2 - self.var)
        self.frames += 1
        self.prev, self.expected, self.suspects = pos, np.zeros(2), []
        return True


class _ReversalCheck:
    """Notices an axis whose corrections move the star the wrong way (and away from the lock)."""

    def __init__(self) -> None:
        self.votes = [0, 0]

    def check(self, axis: int, sent_px: float, observed_px: float, noise: float) -> bool:
        """*sent_px*: the move the pulse should have made along the axis; True when the axis
        has gone the wrong way often enough to be turned round."""
        if abs(sent_px) < max(0.5, 3 * noise):
            return False
        ratio = observed_px / sent_px
        # Wrong way: about as far back as it should have gone forward. A drift outpacing a
        # small correction gives a ratio nearer zero, and only for a frame or two.
        if ratio < -0.5:
            self.votes[axis] += 1
        elif ratio > 0.3:
            self.votes[axis] = 0
        if self.votes[axis] >= REVERSAL_VOTES:
            self.votes[axis] = 0
            return True
        return False


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
        dec_mode: DecMode | None = None,
        scale_resolver: Callable[[str | None], Awaitable[float | None]] | None = None,
        calibration_file: Path | None = None,
    ) -> None:
        self._bus = bus
        self.settings = settings
        self._devices = devices
        self.darks = darks or DarkLibrary()
        self._ra, self._dec, self._dec_mode = ra, dec, dec_mode
        self._calibration_file = calibration_file
        self._calibration: Calibration | None = self._load_calibration()
        self.calibration_attempt: CalibrationAttempt | None = None
        self.active_calibration: Calibration | None = None  # as adjusted to the current pointing
        self.last_error: str | None = None
        self.mount: MountState | None = None  # as last read
        self._mount_checked = 0.0
        self._health = GuidingHealthTracker()
        self._task: asyncio.Task[None] | None = None
        self._start_lock = asyncio.Lock()
        self._state = "Stopped"
        self._paused = False
        self._settle: _Settle | None = None
        self._tracker: StarTracker | None = None
        self._controller: GuideController | None = None
        self._pulse_end = 0.0
        self._capturing_dark = False
        self.view = GuideView()
        self._preview: asyncio.Task[None] | None = None
        # Seconds between frames as observed (drivers do not always honour the exposure we ask
        # for); a frame only shows a pulse if it arrives a full period after the pulse ended.
        self._period = 0.0
        self._last_frame_at: float | None = None
        self._last_frame_seq = 0
        # Pixel scale: the setting when given, else worked out from the optics. It only changes
        # between runs, so that a run reports its errors in one unit throughout.
        self._scale_resolver = scale_resolver
        self._scale: float | None = settings.pixel_scale
        self.pixel_scale_source: Literal["settings", "optics"] | None = "settings" if settings.pixel_scale else None
        self._scale_checked = 0.0
        # The live stream, for changing its exposure or window while guiding.
        self._camera: IStreamingCamera | None = None
        self._sub: FrameSubscription | None = None
        self._params: StreamParams | None = None
        self._roi: StreamRoi | None = None
        self._restream = False
        self._preview_picks: list[Star] = []  # the stars shown last, so the choice stays put
        self._preview_found: list[Star] = []
        self.preferred_star: tuple[float, float] | None = None  # picked by the user
        self._lock_shift = np.zeros(2)  # dithers so far this run
        self._jump = _JumpCheck()
        self._sensor: tuple[int, int] | None = None  # full frame size, from the run's first frame

    # ── Calibration, kept across restarts ────────────────────────────────

    @property
    def calibration(self) -> Calibration | None:
        return self._calibration

    @calibration.setter
    def calibration(self, cal: Calibration | None) -> None:
        self._calibration = cal
        self._save_calibration()

    def _load_calibration(self) -> Calibration | None:
        path = self._calibration_file
        if path is None or not path.is_file():
            return None
        try:
            return Calibration.model_validate_json(path.read_text())
        except Exception as exc:  # a damaged file only means calibrating again
            logger.warning("guider.calibration_unreadable", path=str(path), error=str(exc))
            return None

    def _save_calibration(self) -> None:
        path = self._calibration_file
        if path is None:
            return
        try:
            if self._calibration is None:
                path.unlink(missing_ok=True)
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(self._calibration.model_dump_json())
        except OSError as exc:
            logger.warning("guider.calibration_not_saved", path=str(path), error=str(exc))

    def _calibration_applies(self, cal: Calibration) -> bool:
        """A calibration made with other hardware no longer says what pulses do."""
        cfg = self.settings
        return all(
            made is None or made == now
            for made, now in (
                (cal.camera_id, cfg.camera_id),
                (cal.guide_output, cfg.guide_output),
                (cal.mount_id if cfg.guide_output == "mount" else None, cfg.mount_id if cfg.guide_output == "mount" else None),
            )
        )

    def _flip_dec_guess(self) -> bool:
        choice = self.settings.flip_dec_after_meridian_flip
        return choice == "yes" or (choice == "auto" and self.settings.guide_output == "mount")

    # ── Guider protocol ──────────────────────────────────────────────────

    def status(self) -> GuiderStatus:
        return GuiderStatus(
            guider=self.name,
            connected=True,
            state="Previewing" if self._previewing else "Paused" if self._paused and self._running else self._state,
            guiding=self._health.guiding,
            active=self._running or self._capturing_dark,
            settling=self._settle is not None,
            pixel_scale=self._scale,
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
        async with self._start_lock:  # two requests at once must not start two runs
            if self._capturing_dark:
                raise GuiderBusy("Taking darks")
            await self.stop_preview()
            await self.refresh_pixel_scale()
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
                self.last_error = None
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
        cal = self.active_calibration
        if not self._running or self._paused or self._tracker is None or cal is None:
            raise GuiderError("Cannot dither: not guiding")
        if self._settle is not None:
            raise GuiderBusy("Already settling")
        angle = random.choice((0.0, math.pi)) if ra_only else random.uniform(0, 2 * math.pi)
        shift = cal.sensor_shift(pixels * math.cos(angle), pixels * math.sin(angle))
        self._tracker.shift_lock(*shift)
        self._lock_shift += shift
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

    def clear_calibration(self) -> None:
        self.calibration = None
        self.calibration_attempt = None

    def select_star(self, x: float, y: float) -> Star | None:
        """Make the star nearest to (x, y) in the preview the guide star. None: no star there."""
        found = self._preview_found
        star = min(found, key=lambda s: math.hypot(s.x - x, s.y - y), default=None)
        if star is None or math.hypot(star.x - x, star.y - y) > 15:
            return None
        self.preferred_star = (star.x, star.y)
        self._preview_picks = select_guide_stars(
            found, self.settings.star_count, prefer=self.preferred_star, **self._selection_bounds(self.view.frame)
        )
        if self.view.frame is not None:
            self.view.update(self.view.frame, self._candidates(self._preview_picks, found), "preview", period=self._period)
        return star

    async def refresh_pixel_scale(self, *, max_age: float = 0.0) -> float | None:
        """Settle on the pixel scale to use: the setting, else the one the optics give.

        Left alone during a run, so that its errors keep one unit.
        """
        if self._running:
            return self._scale
        now = time.monotonic()
        if max_age and now - self._scale_checked < max_age:
            return self._scale
        self._scale_checked = now
        if self.settings.pixel_scale:
            self._scale, self.pixel_scale_source = self.settings.pixel_scale, "settings"
        else:
            derived = await self._scale_resolver(self.settings.camera_id) if self._scale_resolver else None
            self._scale, self.pixel_scale_source = derived, "optics" if derived else None
        self.view.pixel_scale = self._scale
        return self._scale

    async def update_settings(self, new: GuiderSettings) -> None:
        """Take new settings. A change of exposure or gain reaches the camera at once: the
        preview restarts, and a guiding run swaps its stream between two frames. Other
        hardware means another calibration."""
        old, stream_changed = self.settings, (new.exposure, new.gain) != (self.settings.exposure, self.settings.gain)
        if stream_changed and self._capturing_dark:
            raise GuiderBusy("Taking darks")
        self.settings = new
        self._scale_checked = 0.0
        if self._calibration is not None and not self._calibration_applies(self._calibration):
            logger.info("guider.calibration_dropped", reason="hardware changed")
            self.clear_calibration()
        if stream_changed:
            if self._previewing:
                await self.stop_preview()
                try:
                    await self.start_preview()
                except GuiderError:
                    pass
            elif self._running:
                self._restream = True
        if (new.pixel_scale, new.camera_id) != (old.pixel_scale, old.camera_id):
            await self.refresh_pixel_scale()

    async def start_preview(self) -> None:
        """Show what the guide camera sees, with the stars the guider would pick."""
        if self._running or self._capturing_dark:
            raise GuiderBusy("Already guiding")
        if self._previewing:
            return
        camera = self._devices.camera()  # fail here, in the caller's request, if there is none
        await self.refresh_pixel_scale()
        self._preview_picks = []
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
                    self.view.update(frame, self.view.stars, "preview", period=self._period)
                    continue
                analysed = now
                chosen, found = await asyncio.to_thread(self._pick_stars, frame, self._preview_picks)
                self._preview_picks, self._preview_found = chosen, found
                self.view.update(frame, self._candidates(chosen, found), "preview", period=self._period)
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

    async def refresh_mount(self, *, max_age: float = 5.0) -> MountState | None:
        """Read the mount when not guiding (a run keeps it up to date itself), for the page."""
        now = time.monotonic()
        if not self._running and now - self._mount_checked >= max_age:
            self._mount_checked = now
            self.mount = await self._read_mount()
        return self.mount

    def prediction(self) -> Prediction | None:
        """What guiding has learnt of the star's own motion, while guiding."""
        c = self._controller
        if c is None:
            return None
        ra = c.predictors[0]
        scale = self._scale or 1.0
        return Prediction(
            drift_ra=ra.drift * scale, drift_dec=c.predictors[1].drift * scale,
            pe_period_s=ra.active_period, pe_amplitude=ra.amplitude_px * scale if ra.active_period else None,
        )

    def dark_matches(self) -> bool:
        """Is there a dark for the current exposure and gain?"""
        cfg = self.settings
        return any(d.exposure == cfg.exposure and d.gain == cfg.gain for d in self.darks.describe())

    # ── The guiding run ──────────────────────────────────────────────────

    async def _run(self) -> None:
        camera: IStreamingCamera | None = None
        error: BaseException | None = None
        watcher: asyncio.Task[None] | None = None
        try:
            camera = self._camera = self._devices.camera()
            pulser = self._devices.pulse_guider()
            cfg = self.settings
            self.mount = await self._read_mount()
            self._check_mount_still(self.mount)
            self._params = StreamParams(exposure=cfg.exposure, gain=cfg.gain)
            self._restream, self._roi = False, None
            self._pulse_end = 0.0
            self._lock_shift = np.zeros(2)
            self._jump = _JumpCheck()
            self._restarted_stream()

            self._state = "Selecting star"
            self._sub = camera.subscribe_frames()
            await camera.start_stream(self._params)
            first = await self._next_frame(self._sub, 0.0)
            stars, detected = await asyncio.to_thread(self._pick_stars, first, None)
            self.view.update(first, self._candidates(stars, detected), "guiding")
            if not stars:
                raise GuiderError("No suitable guide star in the frame")
            logger.info("guider.stars_selected", count=len(stars), primary=(round(stars[0].x, 1), round(stars[0].y, 1)))
            # Window wide enough for the stars as they are (defocused ones are broad).
            half = window_half(stars)
            tracker = self._tracker = StarTracker(stars, self.darks, half=half)
            tracker.refresh(first)
            self._sensor = (first.origin[0] + first.width, first.origin[1] + first.height)
            await self._fit_roi(tracker)

            async def measure() -> tuple[float, float]:
                """Where the guide stars are in a frame taken after the last pulse, as the primary's
                lock plus the stars' mean displacement (several stars average the seeing out).

                A star smeared by the pulse (it moved during the exposure) or briefly missing
                is waited out; one that moved out of its window is searched for.
                """
                lock = tracker.lock_positions[0]
                for attempt in range(MEASURE_TRIES):
                    frame = await self._frame(tracker, self._usable_after_pulse())
                    result = tracker.update(frame)
                    if result.dx is None and attempt >= 1 and tracker.reacquire(frame, REACQUIRE_RADIUS):
                        result = tracker.update(frame)
                    self._show(frame, result, tracker, "calibrating")
                    if result.dx is not None and result.dy is not None:
                        return lock[0] + result.dx, lock[1] + result.dy
                    logger.debug("guider.measure_retry", attempt=attempt, state=result.readings[0].state)
                raise GuiderError(f"Lost the guide star during calibration ({MEASURE_TRIES} frames without it)")

            async def pulse(direction: PulseDirection, ms: int) -> None:
                await pulser.pulse_guide(direction, ms)
                self._pulse_end = time.monotonic()

            base = self._calibration
            if base is not None and not self._calibration_applies(base):
                logger.info("guider.calibration_dropped", reason="made with other hardware")
                base = None
            fresh_calibration = base is None
            if base is None:
                self._state = "Calibrating"
                base = await self._calibrate(measure, pulse)
                self.calibration = base
            tracker.reset_lock()
            active = self.active_calibration = base.for_pointing(
                self.mount.dec if self.mount else None, self.mount.pier_side if self.mount else None,
                flip_dec=self._flip_dec_guess(),
            )
            if active is not base:
                logger.info("guider.calibration_adjusted", dec=active.dec, pier_side=active.pier_side,
                            made_at_dec=base.dec, made_on=base.pier_side)
            self._controller = GuideController(
                active, *self._axis_settings(),
                compensate_backlash=cfg.dec_backlash_compensation,
                last_dec_dir=-1 if fresh_calibration else 0,  # calibration ends with South pulses
                predict_drift=cfg.predict_drift,
                predict_periodic=cfg.predict_periodic_error,
                pe_period_s=cfg.worm_period_s,
            )

            self._state = "Guiding"
            watcher = asyncio.create_task(self._watch_mount(), name="guider_mount_watch")
            await self._guide_loop(tracker, pulser)
        except asyncio.CancelledError:
            raise
        except StreamClosed as exc:
            error = GuiderError(f"The guide camera stream ended: {exc.__cause__ or exc}")
        except Exception as exc:
            error = exc
            logger.error("guider.run_failed", error=str(exc), exc_info=not isinstance(exc, GuiderError))
        finally:
            if watcher is not None:
                watcher.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await watcher
            await self._finish(camera, error)

    async def _calibrate(self, measure: Callable[[], Awaitable[tuple[float, float]]], pulse: Callable[[PulseDirection, int], Awaitable[None]]) -> Calibration:
        cfg = self.settings
        self.calibration_attempt = CalibrationAttempt(running=True, phase="drift")

        def progress(trace: list[CalibrationPoint], phase: str) -> None:
            self.calibration_attempt = CalibrationAttempt(running=True, phase=phase, trace=list(trace))

        try:
            cal = await calibrate(
                measure, pulse, steps=cfg.calibration_steps, travel_px=cfg.calibration_travel_px,
                dec=self.mount.dec if self.mount else None, progress=progress,
            )
        except CalibrationFailed as exc:
            self.calibration_attempt = CalibrationAttempt(running=False, phase="failed", trace=exc.trace, error=str(exc))
            raise
        except BaseException:
            attempt = self.calibration_attempt
            self.calibration_attempt = attempt.model_copy(update={"running": False}) if attempt else None
            raise
        cal = cal.model_copy(update={
            "pier_side": self.mount.pier_side if self.mount else None,
            "camera_id": cfg.camera_id, "guide_output": cfg.guide_output,
            "mount_id": cfg.mount_id, "created": time.time(),
        })
        self.calibration_attempt = None
        logger.info(
            "guider.calibrated", **cal.model_dump(exclude={"trace", "quality"}), points=len(cal.trace),
            issues=cal.quality.issues if cal.quality else [],
        )
        return cal

    def _axis_settings(self) -> tuple[AxisSettings, AxisSettings, DecMode]:
        cfg = self.settings
        min_move = cfg.min_move_px if cfg.min_move_px is not None else auto_min_move_px(self._scale)
        common = dict(min_move_px=min_move, max_pulse_ms=cfg.max_pulse_ms, min_pulse_ms=cfg.min_pulse_ms)
        ra = self._ra or AxisSettings(aggressiveness=cfg.ra_aggressiveness, hysteresis=cfg.ra_hysteresis, **common)
        dec = (self._dec or AxisSettings(aggressiveness=cfg.dec_aggressiveness, hysteresis=0.0, **common)).model_copy(
            update={"resist_switch": cfg.dec_resist_reversals}
        )
        return ra, dec, self._dec_mode or cfg.dec_mode

    async def _guide_loop(self, tracker: StarTracker, pulser: IPulseGuider) -> None:
        cfg = self.settings
        assert self._controller is not None
        scale = self._scale or 1.0
        lost_since: float | None = None
        last_search = 0.0
        blurred_frames = 0
        pulse_failures = 0
        reversals = 0
        reversal = _ReversalCheck()
        last_axis: tuple[float, float] | None = None  # (RA, Dec) error of the last accepted frame
        sent_axis = np.zeros(2)  # move the pulses since then should have made, per axis (px)
        while True:
            frame = await self._frame(tracker, self._usable_after_pulse())
            now = time.monotonic()
            self._react_to_mount()
            result = tracker.update(frame)
            self._show(frame, result, tracker, "guiding")
            await self._check_settle_timeout(now)
            if result.dx is None or result.dy is None:
                if result.blurred and blurred_frames < MAX_BLURRED_FRAMES:
                    blurred_frames += 1  # smeared by a pulse or by wind: its position is not to be trusted
                    continue
                lost_since = lost_since or now
                lost_for = now - lost_since
                if lost_for > self._frame_wait * 2:
                    await self._lost("star_lost")
                    if tracker.reacquire(frame, REACQUIRE_RADIUS) == 0 and lost_for > max(
                        FULL_SEARCH_AFTER_S, 5 * self._frame_wait
                    ) and now - last_search > FULL_SEARCH_EVERY_S:
                        last_search = now
                        await self._search_everywhere(tracker, frame)
                if cfg.lost_timeout_s and lost_for > cfg.lost_timeout_s:
                    raise GuiderError("Guide star lost")
                continue
            if lost_since is not None:
                lost_since = None
                self._jump.reset()  # where it was before the loss says nothing now
                last_axis = None
                self._controller.reset()
            await self._fit_roi(tracker)  # a dither or a star found elsewhere may need the window moved
            blurred_frames = 0
            pos = np.array([result.dx, result.dy]) + self._lock_shift
            if not self._jump.accept(pos):
                logger.debug("guider.frame_ignored", dx=round(result.dx, 2), dy=round(result.dy, 2))
                continue
            controller = self._controller
            cal = controller.calibration
            ra_px, dec_px = cal.axis_error(result.dx, result.dy)
            if last_axis is not None and not self._paused:
                noise = min(math.sqrt(self._jump.var), 1.0)
                for axis, (sent, now_err, before) in enumerate(zip(sent_axis, (ra_px, dec_px), last_axis)):
                    if reversal.check(axis, float(sent), now_err - before, noise):
                        reversals += 1
                        if reversals > MAX_REVERSALS:
                            raise GuiderError("Guiding keeps pushing the star away: calibrate again")
                        self._reverse_axis(axis)
                        controller = self._controller
                        cal = controller.calibration
                        ra_px, dec_px = cal.axis_error(result.dx, result.dy)
            last_axis, sent_axis = (ra_px, dec_px), np.zeros(2)
            if self._paused:
                continue
            if pulse_failures < PULSE_FAILURES_LOST and self._health.on_step(ra_px * scale, dec_px * scale):
                await self._bus.publish(GuidingStateChanged(guider=self.name, guiding=True))
            await self._update_settle(now, math.hypot(result.dx, result.dy))
            pulses = controller.correct(result.dx, result.dy, frame.timestamp)
            west = sum(ms if d == "W" else -ms for d, ms in pulses if d in "WE")
            north = sum(ms if d == "N" else -ms for d, ms in pulses if d in "NS")
            await self._bus.publish(
                GuiderStep(
                    frame=frame.seq,
                    ra_dist=ra_px * scale,
                    dec_dist=dec_px * scale,
                    ra_corr=west,
                    dec_corr=north,
                    star_snr=result.readings[0].star.snr if result.readings[0].star else None,
                    stars_found=result.found,
                )
            )
            if not pulses:
                continue
            outcomes = await asyncio.gather(*(pulser.pulse_guide(d, ms) for d, ms in pulses), return_exceptions=True)
            self._pulse_end = time.monotonic()
            failed = [o for o in outcomes if isinstance(o, BaseException)]
            if failed:
                controller.pulses_failed()
                pulse_failures += 1
                logger.warning("guider.pulse_failed", error=str(failed[0]), in_a_row=pulse_failures)
                if pulse_failures == PULSE_FAILURES_LOST:
                    await self._lost("pulse_failed")
                continue
            pulse_failures = 0
            self._jump.add_pulse(cal.matrix @ np.array([west, north], dtype=float))
            sent_axis = np.array([west * cal.ra_rate, north * cal.dec_rate])

    def _reverse_axis(self, axis: int) -> None:
        """Corrections on *axis* push the star away: turn the axis round and say so."""
        assert self._controller is not None and self.active_calibration is not None
        cal = self.active_calibration
        flipped = cal.with_ra_reversed() if axis == 0 else cal.with_dec_reversed()
        self.active_calibration = flipped
        self._controller.calibration = flipped
        self._controller.forget_drift()
        self._jump.reset()
        name = "RA" if axis == 0 else "Dec"
        logger.warning("guider.axis_reversed", axis=name)
        base = self._calibration
        if axis == 1 and base is not None and self.mount and self.mount.pier_side and base.pier_side and (
            self.mount.pier_side != base.pier_side
        ):
            # The flip was guessed wrong for this mount: remember how it really behaves.
            guessed = base.flip_dec if base.flip_dec is not None else self._flip_dec_guess()
            self.calibration = base.model_copy(update={"flip_dec": not guessed})
        asyncio.get_running_loop().create_task(
            self._bus.publish(
                GuidingStateChanged(
                    guider=self.name, guiding=self._health.guiding, reason="axis_reversed",
                    notify="warning", notify_title="Guiding corrected",
                    notify_body=f"{name} corrections were moving the star away; the axis has been reversed.",
                )
            )
        )

    # ── The mount ────────────────────────────────────────────────────────

    async def _read_mount(self) -> MountState | None:
        read = getattr(self._devices, "mount_state", None)
        if read is None:
            return None
        try:
            async with asyncio.timeout(5):
                return await read()  # type: ignore[no-any-return]
        except Exception as exc:
            logger.debug("guider.mount_unreadable", error=str(exc))
            return None

    @staticmethod
    def _check_mount_still(state: MountState | None) -> None:
        if state is None:
            return
        if state.parked:
            raise GuiderError("The mount is parked")
        if state.slewing:
            raise MountMoved("The mount is slewing")

    async def _watch_mount(self) -> None:
        while True:
            await asyncio.sleep(MOUNT_POLL_S)
            state = await self._read_mount()
            if state is not None:
                self.mount = state

    def _react_to_mount(self) -> None:
        """Stop when the mount slews or parks: the stars locked on are gone. Follow a pier side
        that changed under us (a flip while guiding) by adjusting the calibration."""
        state = self.mount
        if state is None:
            return
        if state.slewing:
            raise MountMoved("The mount slewed: guiding stopped")
        if state.parked:
            raise MountMoved("The mount parked: guiding stopped")
        active = self.active_calibration
        if active is None or self._calibration is None or self._controller is None:
            return
        if state.pier_side and active.pier_side and state.pier_side != active.pier_side:
            adjusted = self._calibration.for_pointing(state.dec, state.pier_side, flip_dec=self._flip_dec_guess())
            logger.warning("guider.pier_side_changed", pier_side=state.pier_side)
            self.active_calibration = adjusted
            self._controller.calibration = adjusted
            self._controller.forget_drift()

    # ── Frames and the stream ────────────────────────────────────────────

    async def _frame(self, tracker: StarTracker, newer_than: float) -> Frame:
        """The next usable frame. A stream that stops or ends is restarted a few times before
        the run gives up: a USB hiccup must not end a night's guiding."""
        failures = 0
        while True:
            await self._apply_stream_change(tracker)
            try:
                return await self._next_frame(self._sub, newer_than)  # type: ignore[arg-type]
            except (StreamClosed, TimeoutError) as exc:
                cause: BaseException = exc.__cause__ or exc
            while True:
                failures += 1
                logger.warning("guider.stream_failed", error=str(cause) or type(cause).__name__, attempt=failures)
                if failures > STREAM_RETRIES:
                    raise GuiderError(f"The guide camera stopped sending frames: {cause}")
                await self._lost("camera")
                await asyncio.sleep(min(2.0**failures, 15.0) * min(self._frame_wait, 1.0))
                try:
                    await self._restart_stream(self._roi)
                    break
                except Exception as exc:  # the camera refused to start: count it and wait longer
                    cause = exc
            newer_than = 0.0

    async def _restart_stream(self, roi: StreamRoi | None) -> None:
        """Stop the stream and start it again with the current exposure and gain and *roi*."""
        assert self._camera is not None
        cfg = self.settings
        if self._sub is not None:
            self._sub.close()
        with contextlib.suppress(Exception):
            await self._camera.stop_stream()
        self._sub = self._camera.subscribe_frames()
        self._params = StreamParams(exposure=cfg.exposure, gain=cfg.gain, roi=roi)
        self._roi = roi
        self._restarted_stream()
        self._pulse_end = time.monotonic()  # the first frame may predate the new setting
        await self._camera.start_stream(self._params)

    async def _apply_stream_change(self, tracker: StarTracker) -> None:
        """Restart the stream with the exposure and gain now in the settings, if they changed.

        The calibration and the lock positions stay; only the stars' reference brightness is
        measured again, since it depends on the exposure.
        """
        if not self._restream or self._camera is None:
            return
        self._restream = False
        await self._restart_stream(self._roi)
        since = time.monotonic()
        await self._next_frame(self._sub, since)  # type: ignore[arg-type]
        tracker.refresh(await self._next_frame(self._sub, since), relock=False)  # type: ignore[arg-type]
        cfg = self.settings
        logger.info("guider.exposure_changed", exposure=cfg.exposure, gain=cfg.gain)

    async def _fit_roi(self, tracker: StarTracker) -> None:
        """Have the camera send only a window around the stars and where they should be.

        Moves the window when a star or its lock gets near its edge (a dither, a drift, a star
        found again elsewhere); falls back to full frames when the driver ignores windows.
        """
        if self._camera is None or self._sensor is None:
            return
        if self._roi is not None and self._inside_roi(tracker, self._roi):
            return
        roi = self._roi_for(tracker, self._sensor, tracker.half)
        if roi == self._roi:
            return
        await self._restart_stream(roi)
        if roi is None:
            await self._rereference(tracker)
            return
        if not await self._rereference(tracker):
            # The driver did not give us the region we asked for: track in full frames.
            logger.warning("guider.roi_ignored", roi=roi.model_dump())
            await self._restart_stream(None)
            await self._rereference(tracker)

    def _inside_roi(self, tracker: StarTracker, roi: StreamRoi) -> bool:
        reach = tracker.half + ROI_EDGE
        return all(
            roi.x + reach <= x <= roi.x + roi.width - reach and roi.y + reach <= y <= roi.y + roi.height - reach
            for x, y in tracker.last_positions + tracker.lock_positions
        )

    def _roi_for(self, tracker: StarTracker, sensor: tuple[int, int], half: int) -> StreamRoi | None:
        pad = max(ROI_PADDING, int(self.settings.calibration_travel_px) + 20) + half
        points = tracker.last_positions + tracker.lock_positions
        width, height = sensor
        x0 = max(int(min(x for x, _ in points)) - pad, 0)
        y0 = max(int(min(y for _, y in points)) - pad, 0)
        x1 = min(int(max(x for x, _ in points)) + pad + 1, width)
        y1 = min(int(max(y for _, y in points)) + pad + 1, height)
        if x1 <= x0 or y1 <= y0 or (x1 - x0) * (y1 - y0) >= ROI_MAX_FRACTION * width * height:
            return None
        return StreamRoi(x=x0, y=y0, width=x1 - x0, height=y1 - y0)

    async def _rereference(self, tracker: StarTracker) -> int:
        """Re-measure the stars after a stream restart; returns the stars found.

        A restart can change the image: the first frame may still belong to the old stream, and
        a window or a mode may be rendered at a different brightness. The first frame is
        discarded and the second renews the reference brightness (the locks stay).
        """
        since = time.monotonic()
        await self._next_frame(self._sub, since)  # type: ignore[arg-type]
        return tracker.refresh(await self._next_frame(self._sub, since), relock=False)  # type: ignore[arg-type]

    async def _search_everywhere(self, tracker: StarTracker, frame: Frame) -> None:
        """The star has been gone a while: look for the star pattern in the whole frame."""
        if self._roi is not None:
            logger.info("guider.searching_full_frame")
            await self._restart_stream(None)
            since = time.monotonic()
            await self._next_frame(self._sub, since)  # type: ignore[arg-type]
            frame = await self._next_frame(self._sub, since)  # type: ignore[arg-type]
        detected = await asyncio.to_thread(detect_stars, frame, self.darks)
        shift = tracker.relocate(detected)
        if shift is not None:
            logger.info("guider.star_found_again", shift=(round(shift[0], 1), round(shift[1], 1)))

    def _restarted_stream(self) -> None:
        self._last_frame_at = None
        self._last_frame_seq = 0
        self._period = 0.0

    async def _finish(self, camera: IStreamingCamera | None, error: BaseException | None) -> None:
        if self._sub is not None:
            self._sub.close()
        self._sub = self._camera = None
        self._restream = False
        self._sensor = None
        if camera is not None:
            with contextlib.suppress(Exception):
                await asyncio.shield(camera.stop_stream())
        self._state = "Stopped"
        self._paused = False
        self.view.go_idle()
        self._tracker = None
        self._controller = None
        self.active_calibration = None
        self.preferred_star = None
        if error is not None:
            self.last_error = str(error)
        reason = "stopped" if error is None else "mount_moved" if isinstance(error, MountMoved) else "error"
        await self._lost(reason)
        if self._settle is not None:
            exc = error if isinstance(error, GuiderError) else GuiderError(str(error)) if error else None
            await self._end_settle(exc or SettleFailed("guiding stopped while settling"))

    # ── Helpers ──────────────────────────────────────────────────────────

    def _selection_bounds(self, frame: Frame | None) -> dict[str, Any]:
        if frame is None:
            return {}
        ox, oy = frame.origin
        margin = min(self.settings.calibration_travel_px + 10, 0.15 * min(frame.width, frame.height))
        return {"bounds": (ox, oy, ox + frame.width, oy + frame.height), "margin": margin}

    def _pick_stars(self, frame: Frame, keep: list[Star] | None = None) -> tuple[list[Star], list[Star]]:
        """(the stars to guide on, every star detected); *keep* holds the previous choice."""
        found = detect_stars(frame, self.darks)
        chosen = select_guide_stars(
            found, self.settings.star_count, keep=keep, prefer=self.preferred_star, **self._selection_bounds(frame)
        )
        return chosen, found

    @staticmethod
    def _candidates(chosen: list[Star], found: list[Star]) -> list[OverlayStar]:
        picked = {id(s): i for i, s in enumerate(chosen)}
        return [
            OverlayStar(
                x=s.x, y=s.y, snr=s.snr, fwhm=s.fwhm, hfd=s.hfd, peak=s.peak, flux=s.flux, half=window_half([s]),
                saturated=s.saturated,
                kind="candidate" if id(s) not in picked else "primary" if picked[id(s)] == 0 else "companion",
            )
            for s in found
        ]

    def _show(self, frame: Frame, result: TrackerResult, tracker: StarTracker, mode: Literal["guiding", "calibrating"]) -> None:
        stars = []
        for i, (reading, last) in enumerate(zip(result.readings, tracker.last_positions)):
            star = reading.star
            stars.append(
                OverlayStar(
                    x=star.x if star else last[0], y=star.y if star else last[1],
                    kind="lost" if star is None else "primary" if i == 0 else "companion",
                    snr=star.snr if star else None, fwhm=star.fwhm if star else None,
                    hfd=star.hfd if star else None, peak=star.peak if star else None,
                    flux=star.flux if star else None, half=tracker.half,
                    saturated=bool(star and star.saturated), state=reading.state,
                )
            )
        self.view.update(frame, stars, mode, tracker.lock_positions, period=self._period)

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


