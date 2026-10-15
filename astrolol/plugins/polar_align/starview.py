"""Live star view: follow one star on the camera stream while the knobs are turned.

A recheck costs an exposure and a plate solve per reading. This mode solves once, then tracks
a single star in a small window of the camera stream. A star is fixed on the sky, so its shift
in the image since that solve is the telescope's shift: that gives the same "solved" pointing
a recheck would (see shift.py) at the frame rate, and the same update_pole_offset turns it into
the remaining altitude/azimuth error. The view shows where the star has to go for the error to
vanish, so the user turns the knobs until the star sits in the circle.

Frames come through the camera's own stream when it has one, else back-to-back exposures
(imaging.streaming); stars are found and measured by the code the guider uses (imaging.stars).
"""
from __future__ import annotations

import asyncio
import contextlib
import math
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

import numpy as np
import structlog
from pydantic import BaseModel, Field

from astrolol.devices.base.streaming import Frame, StreamClosed, StreamParams, StreamRoi
from astrolol.imaging.frameview import FrameStats, OverlayStar, frame_stats, render_jpeg
from astrolol.imaging.stars import Star, detect_stars, measure, select_guide_stars
from astrolol.imaging.streaming import LoopingExposureStream, streaming_camera
from astrolol.plugins.polar_align.shift import Cd, pointing_after_star_shift, star_moves
from astrolol.plugins.polar_align.solver import Observation
from astrolol.plugins.polar_align.wizard import PolarAlignWizard, WizardRun

logger = structlog.get_logger()

# Remaining error below which the star counts as being on its mark.
ARRIVED_ARCMIN = 0.5
TRACK_HALF = 10  # half-size of the window the star is measured in, stream pixels
MAX_JUMP_PX = 60.0  # a star that moved further than this between frames is a different one
LOST_AFTER_FRAMES = 5
FRAME_TIMEOUT_S = 30.0
MIN_SNR = 3.0
MIN_WINDOW_PX = 96
WINDOW_PADDING = 0.35  # of the star-to-target distance, on top of PAD_MIN_PX
PAD_MIN_PX = 40
RECENTRE_MARGIN = 0.15  # of the window: a star this close to its edge gets a new window
PUBLISH_INTERVAL_S = 1.0


def _now() -> datetime:
    return datetime.now(timezone.utc)


class StarViewRequest(BaseModel):
    exposure_s: float = Field(default=1.0, gt=0, le=10, description="Exposure of each streamed frame")


StarViewState = Literal["idle", "starting", "tracking", "lost", "failed"]


class StarViewInfo(BaseModel):
    state: StarViewState = "idle"
    version: int = 0  # changes with every new frame: fetch the image again when it does
    width: int = 0
    height: int = 0
    origin: tuple[int, int] = (0, 0)  # sensor position (binned pixels) of the image's top-left pixel
    star: OverlayStar | None = None
    az_via: tuple[float, float] | None = Field(
        default=None, description="Where the star would be after the azimuth knob alone (sensor coordinates)"
    )
    target: tuple[float, float] | None = Field(
        default=None, description="Where the star has to go for the error to vanish (sensor coordinates)"
    )
    tolerance_px: float = 0.0  # radius of the circle drawn around the target
    alt_error_arcmin: float | None = None
    az_error_arcmin: float | None = None
    arrived: bool = False
    pixel_scale: float | None = None  # arcsec per pixel of this image
    error: str | None = None
    stats: FrameStats | None = None


class _Geometry:
    """What the solve at the start of the view fixes for the rest of it."""

    def __init__(self, ra_hours: float, dec_deg: float, cd: Cd, binning: int, star_unbinned: tuple[float, float]) -> None:
        self.ra_hours, self.dec_deg = ra_hours, dec_deg
        self.cd = cd  # degrees per unbinned pixel
        self.binning = binning
        self.star0 = star_unbinned


def _window_around(
    star: tuple[float, float], target: tuple[float, float], width: int, height: int
) -> tuple[int, int, int, int]:
    """(x0, y0, x1, y1) in sensor pixels: the star, its target and room around both."""
    pad = max(PAD_MIN_PX, WINDOW_PADDING * math.hypot(target[0] - star[0], target[1] - star[1]))
    x0, x1 = min(star[0], target[0]) - pad, max(star[0], target[0]) + pad
    y0, y1 = min(star[1], target[1]) - pad, max(star[1], target[1]) + pad
    def fit(lo: float, hi: float, size: int) -> tuple[int, int]:
        if hi - lo < MIN_WINDOW_PX:
            mid = (lo + hi) / 2
            lo, hi = mid - MIN_WINDOW_PX / 2, mid + MIN_WINDOW_PX / 2
        lo_i, hi_i = int(math.floor(lo)), int(math.ceil(hi))
        if lo_i < 0:
            hi_i, lo_i = min(size, hi_i - lo_i), 0
        if hi_i > size:
            lo_i, hi_i = max(0, lo_i - (hi_i - size)), size
        return lo_i, hi_i

    fx0, fx1 = fit(x0, x1, width)
    fy0, fy1 = fit(y0, y1, height)
    return fx0, fy0, fx1, fy1


class StarView:
    """One live view at a time, started and stopped through WizardEngine."""

    def __init__(self, app: Any, wizard: PolarAlignWizard) -> None:
        self._app = app
        self._wizard = wizard
        self._task: asyncio.Task[None] | None = None
        self._wrappers: dict[int, LoopingExposureStream] = {}
        self._info = StarViewInfo()
        self._frame: Frame | None = None  # what the image shows: cropped to the window
        self._jpeg: tuple[int, bytes] | None = None

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    def info(self) -> StarViewInfo:
        return self._info

    def jpeg(self) -> bytes | None:
        if self._frame is None:
            return None
        if self._jpeg is None or self._jpeg[0] != self._info.version:
            self._jpeg = (self._info.version, render_jpeg(self._frame.pixels))
        return self._jpeg[1]

    async def start(self, run: WizardRun, req: StarViewRequest) -> None:
        if self.running:
            raise ValueError("The star view is already running")
        if run.status != "converging":
            raise ValueError("Polar alignment is not in the converging phase")
        camera = self._camera(run)  # fail in the caller's request if there is none
        self._info = StarViewInfo(state="starting")
        self._frame, self._jpeg = None, None
        self._task = asyncio.create_task(self._run(run, req, camera), name=f"polar_align_starview_{run.id}")

    async def stop(self) -> None:
        task, self._task = self._task, None
        if task is None:
            return
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
        if self._info.state in ("starting", "tracking", "lost"):
            self._info = self._info.model_copy(update={"state": "idle"})

    # ------------------------------------------------------------------

    def _camera(self, run: WizardRun) -> Any:
        dm = getattr(self._app.state, "device_manager", None)
        if dm is None:
            raise RuntimeError("Polar alignment needs the device manager")
        try:
            raw = dm.get_camera(run.request.camera_id)
        except Exception as exc:
            raise RuntimeError(f"The camera '{run.request.camera_id}' is not connected") from exc
        return streaming_camera(raw, self._wrappers)

    async def _run(self, run: WizardRun, req: StarViewRequest, camera: Any) -> None:
        sub = None
        try:
            reading = await self._wizard.read_pointing(run, keep_frame=True)
            run.live_offset = self._wizard.measure_offset(run, reading.observation)
            await self._wizard.publish_offset(run)
            if reading.solve.cd is None or reading.pixels is None:
                raise RuntimeError("The plate solve did not give the image orientation the star view needs")

            binning = reading.binning
            cd: Cd = tuple(c / binning for c in reading.solve.cd)  # type: ignore[assignment]
            height, width = reading.pixels.shape
            site = self._wizard._site(self._app)
            assert site is not None
            obs = reading.observation
            first_moves = star_moves(
                run.live_offset.alt_error_arcmin, run.live_offset.az_error_arcmin,
                obs.solved_ra_hours, obs.solved_dec_deg, obs.when, site.latitude, site.longitude, cd,
            )
            star = await asyncio.to_thread(self._pick_star, reading.pixels, reading.exposure_s, binning, first_moves.total)
            geometry = _Geometry(
                obs.solved_ra_hours, obs.solved_dec_deg, cd, binning, (star.x * binning, star.y * binning)
            )
            # Stream coordinates: the binned sensor, as the solved frame was.
            sensor_w, sensor_h = width, height
            target = (star.x + first_moves.total[0] / binning, star.y + first_moves.total[1] / binning)
            window = _window_around((star.x, star.y), target, sensor_w, sensor_h)

            params = StreamParams(
                exposure=req.exposure_s, gain=run.request.gain, binning=binning, roi=self._roi(window),
            )
            sub = camera.subscribe_frames()
            await camera.start_stream(params)
            await self._follow(run, req, camera, sub, geometry, star, window, (sensor_w, sensor_h), (site.latitude, site.longitude))
        except asyncio.CancelledError:
            raise
        except StreamClosed as exc:
            self._fail(f"The camera stream ended: {exc.__cause__ or exc}")
        except Exception as exc:
            logger.warning("polar_align.star_view_failed", error=str(exc))
            self._fail(str(exc))
        finally:
            if sub is not None:
                sub.close()
            with contextlib.suppress(Exception):
                await asyncio.shield(camera.stop_stream())

    def _fail(self, message: str) -> None:
        self._info = self._info.model_copy(update={"state": "failed", "error": message, "version": self._info.version + 1})

    @staticmethod
    def _roi(window: tuple[int, int, int, int]) -> StreamRoi:
        x0, y0, x1, y1 = window
        return StreamRoi(x=x0, y=y0, width=x1 - x0, height=y1 - y0)

    def _pick_star(
        self, pixels: np.ndarray, exposure_s: float, binning: int, move_unbinned: tuple[float, float]
    ) -> Star:
        """The best star that stays in the frame while the knobs bring it to its mark."""
        frame = Frame(pixels=pixels, seq=0, timestamp=0.0, exposure=exposure_s, binning=binning)
        stars = detect_stars(frame)
        height, width = pixels.shape
        mx, my = move_unbinned[0] / binning, move_unbinned[1] / binning
        margin = 24
        reachable = [
            s for s in stars
            if margin <= s.x + mx < width - margin and margin <= s.y + my < height - margin
        ]
        ranked = select_guide_stars(reachable, count=1, min_separation=30.0)
        if not ranked:
            raise RuntimeError(
                "No star is both bright enough and able to stay in the frame while the knobs are "
                "turned. Use rechecks until the error is smaller."
                if stars else "No star found in the frame. Try a longer exposure."
            )
        return ranked[0]

    async def _follow(
        self,
        run: WizardRun,
        req: StarViewRequest,
        camera: Any,
        sub: Any,
        geometry: _Geometry,
        star: Star,
        window: tuple[int, int, int, int],
        sensor: tuple[int, int],
        site: tuple[float, float],
    ) -> None:
        mm = getattr(self._app.state, "mount_manager", None)
        if mm is None:
            raise RuntimeError("Polar alignment needs the mount manager")
        binning = geometry.binning
        latitude, longitude = site
        x, y = star.x, star.y
        lost = 0
        last_publish = 0.0
        tracked: Star = star
        while True:
            frame: Frame = await asyncio.wait_for(sub.get(), FRAME_TIMEOUT_S)
            ox, oy = frame.origin
            found = await asyncio.to_thread(measure, frame.pixels, x - ox, y - oy, half=TRACK_HALF)
            if found is not None:
                found = found.shifted(ox, oy)
            if found is None or found.snr < MIN_SNR or math.hypot(found.x - x, found.y - y) > MAX_JUMP_PX:
                found = await asyncio.to_thread(self._relocate, frame, x, y)
            if found is None:
                lost += 1
                if lost >= LOST_AFTER_FRAMES and self._info.state != "lost":
                    self._info = self._info.model_copy(
                        update={"state": "lost", "error": "The star is lost", "version": self._info.version + 1}
                    )
                continue
            lost = 0
            x, y = found.x, found.y
            tracked = found

            dx, dy = x * binning - geometry.star0[0], y * binning - geometry.star0[1]
            ra, dec = pointing_after_star_shift(geometry.ra_hours, geometry.dec_deg, geometry.cd, dx, dy)
            status = await mm.get_status(run.request.mount_id)
            when = _now() - timedelta(seconds=frame.exposure / 2.0)
            error: str | None = None
            offset = None
            try:
                offset = self._wizard.measure_offset(
                    run,
                    Observation(solved_ra_hours=ra, solved_dec_deg=dec, mount_ra_hours=status.ra_jnow, when=when),
                )
            except ValueError as exc:
                error = str(exc)  # a bad geometry for this frame: show it, keep following
            if offset is not None:
                run.live_offset = offset
                run.last_recheck_at = _now()
                run.last_recheck_error = None
                moves = star_moves(
                    offset.alt_error_arcmin, offset.az_error_arcmin, ra, dec, when, latitude, longitude, geometry.cd
                )
                tx, ty = x + moves.total[0] / binning, y + moves.total[1] / binning
                via = (x + moves.az[0] / binning, y + moves.az[1] / binning)
                scale = math.hypot(geometry.cd[0], geometry.cd[2]) * 3600.0 * binning
                tolerance = max(6.0, ARRIVED_ARCMIN * 60.0 / scale) if scale > 0 else 6.0
                total_error = math.hypot(offset.alt_error_arcmin, offset.az_error_arcmin)

                wanted = _window_around((x, y), (tx, ty), sensor[0], sensor[1])
                if wanted != window and self._leaving(window, (x, y), (tx, ty)):
                    window = wanted
                    sub.close()
                    await camera.stop_stream()
                    sub = camera.subscribe_frames()
                    await camera.start_stream(
                        StreamParams(exposure=req.exposure_s, gain=run.request.gain, binning=binning, roi=self._roi(window))
                    )
                    continue

                view, vx, vy = self._crop(frame, window)
                self._frame = view
                self._info = StarViewInfo(
                    state="tracking",
                    version=self._info.version + 1,
                    width=view.width, height=view.height, origin=(vx, vy),
                    star=OverlayStar(
                        x=x, y=y, kind="primary", snr=tracked.snr, fwhm=tracked.fwhm, hfd=tracked.hfd,
                        peak=tracked.peak, flux=tracked.flux, saturated=tracked.saturated,
                    ),
                    az_via=via, target=(tx, ty), tolerance_px=tolerance,
                    alt_error_arcmin=offset.alt_error_arcmin, az_error_arcmin=offset.az_error_arcmin,
                    arrived=total_error < ARRIVED_ARCMIN,
                    pixel_scale=scale or None,
                    stats=frame_stats(frame),
                )
                now = time.monotonic()
                if now - last_publish >= PUBLISH_INTERVAL_S:
                    last_publish = now
                    await self._wizard.publish_offset(run)
            else:
                self._info = self._info.model_copy(update={"error": error, "version": self._info.version + 1})

    @staticmethod
    def _leaving(window: tuple[int, int, int, int], star: tuple[float, float], target: tuple[float, float]) -> bool:
        """The star or its mark is close to (or past) the edge of the window."""
        x0, y0, x1, y1 = window
        mx, my = RECENTRE_MARGIN * (x1 - x0), RECENTRE_MARGIN * (y1 - y0)
        return any(
            not (x0 + mx <= px <= x1 - mx and y0 + my <= py <= y1 - my) for px, py in (star, target)
        )

    @staticmethod
    def _crop(frame: Frame, window: tuple[int, int, int, int]) -> tuple[Frame, int, int]:
        """The part of *frame* inside *window* (a camera that ignores the window sends it whole)."""
        ox, oy = frame.origin
        x0, y0, x1, y1 = window
        cx0, cy0 = max(x0, ox), max(y0, oy)
        cx1, cy1 = min(x1, ox + frame.width), min(y1, oy + frame.height)
        if cx1 - cx0 < 8 or cy1 - cy0 < 8:
            return frame, ox, oy
        pixels = frame.pixels[cy0 - oy:cy1 - oy, cx0 - ox:cx1 - ox]
        return Frame(
            pixels=pixels, seq=frame.seq, timestamp=frame.timestamp, exposure=frame.exposure,
            gain=frame.gain, binning=frame.binning, origin=(cx0, cy0),
        ), cx0, cy0

    @staticmethod
    def _relocate(frame: Frame, x: float, y: float) -> Star | None:
        """The detected star nearest to the last position, if one is close enough."""
        stars = detect_stars(frame, min_fwhm=1.2)
        near = [s for s in stars if math.hypot(s.x - x, s.y - y) <= MAX_JUMP_PX and s.snr >= MIN_SNR]
        return min(near, key=lambda s: math.hypot(s.x - x, s.y - y), default=None)
