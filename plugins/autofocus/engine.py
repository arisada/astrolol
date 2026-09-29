"""Autofocus engine: orchestrates the V-curve measurement sequence.

Algorithm
---------
1. Record current focuser position as the centre.
2. Generate ``2 * num_steps + 1`` sample positions evenly spaced by ``step_size``
   (clamped to ≥ 0).
3. For each position: move focuser → expose → detect stars → measure median FWHM.
4. Refit the parabola after every data point so the UI can show a live curve.
5. Move to the parabola minimum (or to the measured minimum if the fit fails).
"""
from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

import structlog

from astrolol.config.settings import settings
from astrolol.core.events import EventBus
from astrolol.core.mem_guard import mem_guard
from astrolol.devices.base.models import ExposureParams
from astrolol.devices.manager import DeviceManager
from plugins.autofocus.algorithms import fit_hyperbola, fit_parabola
from plugins.autofocus.models import (
    AutofocusAbortedEvent,
    AutofocusCompletedEvent,
    AutofocusConfig,
    AutofocusDataPointEvent,
    AutofocusFailedEvent,
    AutofocusRun,
    AutofocusSettings,
    AutofocusStartedEvent,
    CurveFit,
    FocusDataPoint,
    StarInfo,
)
from plugins.autofocus.star_detector import detect_stars

logger = structlog.get_logger()

_MOVE_TIMEOUT = 120.0   # seconds to wait for a single focuser move
_EXPOSE_TIMEOUT = 300.0  # seconds to wait for a single exposure


def _annotate_preview(
    jpeg_path: str,
    stars: list[dict],
    fits_w: int,
    fits_h: int,
) -> None:
    """Draw green circles on the JPEG for each detected star.

    Star coordinates are in FITS pixel space; the JPEG may have been
    downscaled by fits_to_jpeg, so we apply the same scale factor.
    """
    from PIL import Image, ImageDraw
    # fits_to_jpeg/fits_to_jpeg_linear save grayscale ("L" mode) JPEGs. Drawing a
    # colour outline directly on an "L" image silently converts it to a grayscale
    # luminance value (PIL has no color to draw with), which is why the circles
    # rendered as near-black regardless of the outline colour requested below.
    img = Image.open(jpeg_path).convert("RGB")
    jpeg_w, jpeg_h = img.size
    sx = jpeg_w / fits_w if fits_w else 1.0
    sy = jpeg_h / fits_h if fits_h else 1.0
    draw = ImageDraw.Draw(img)
    for star in stars:
        cx = star["x"] * sx
        cy = star["y"] * sy
        r  = star["fwhm"] * max(sx, sy) * 2.5
        # Bright magenta reads clearly against both dark sky and stretched star
        # cores (green/cyan tend to blend into star halos); width=1 keeps the
        # circle from eating into small/faint stars.
        draw.ellipse([cx - r, cy - r, cx + r, cy + r], outline="#ff2ec8", width=1)
    img.save(jpeg_path, format="JPEG", quality=90)


def _read_fits_shape(fits_path: str) -> tuple[int, int]:
    """Return (width, height) by reading the FITS header directly."""
    try:
        from astropy.io import fits
        with fits.open(fits_path) as hdul:
            data = hdul[0].data
            if data is None:
                return 0, 0
            # Shape is (..., H, W) in numpy convention
            shape = data.shape
            while len(shape) > 2:
                shape = shape[1:]
            return int(shape[1]), int(shape[0])  # (width, height)
    except Exception:
        return 0, 0


class AutofocusEngine:
    """Manages one autofocus run at a time."""

    def __init__(
        self,
        event_bus: EventBus,
        device_manager: DeviceManager,
        settings_provider: Callable[[], AutofocusSettings] | None = None,
    ) -> None:
        self._bus = event_bus
        self._device_manager = device_manager
        self._settings_provider = settings_provider or AutofocusSettings
        self._current_run: AutofocusRun | None = None
        self._task: asyncio.Task | None = None
        # Maps step number (1-indexed) → {"auto": path, "linear": path}
        self._preview_paths: dict[int, dict[str, str]] = {}

    @property
    def current_run(self) -> AutofocusRun | None:
        return self._current_run

    def preview_path(self, step: int, stretch: str = "auto") -> str | None:
        return self._preview_paths.get(step, {}).get(stretch)

    async def start(self, config: AutofocusConfig) -> AutofocusRun:
        if self._task is not None and not self._task.done():
            raise ValueError("Autofocus is already running. Call abort() first.")

        total_steps = config.num_steps * 2 + 1
        run = AutofocusRun(config=config, status="running", total_steps=total_steps)
        self._current_run = run
        self._preview_paths.clear()

        self._task = asyncio.create_task(self._run(run), name=f"autofocus_{run.id}")
        return run

    async def focus(self, camera_id: str, focuser_id: str) -> AutofocusRun:
        """Run autofocus with the saved autofocus settings and wait for the result.

        For automation (the sequencer): the filter is left as it is. Cancelling the caller
        aborts the run (the focuser returns to where it started). Raises ValueError when a
        run is already in progress; a failed run is returned with status "failed".
        """
        s = self._settings_provider()
        config = AutofocusConfig(
            camera_id=camera_id,
            focuser_id=focuser_id,
            step_size=s.step_size,
            num_steps=s.num_steps,
            exposure_time=s.exposure_time,
            binning=s.binning,
            gain=s.gain,
            fit_algo=s.fit_algo,
            metric=s.metric,
            lock_stars=s.lock_stars,
        )
        run = await self.start(config)
        task = self._task
        assert task is not None
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            await self.abort()
            raise
        return run

    async def abort(self) -> None:
        if self._task is not None and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    # ── Internal ──────────────────────────────────────────────────────────────

    async def _run(self, run: AutofocusRun) -> None:
        config = run.config
        preview_dir = Path(settings.images_dir) / "autofocus" / run.id
        preview_dir.mkdir(parents=True, exist_ok=True)

        restore_to: int | None = None
        try:
            camera = self._device_manager.get_camera(config.camera_id)
            focuser = self._device_manager.get_focuser(config.focuser_id)

            # Optional: change filter before starting
            if config.filter_slot is not None:
                await self._select_filter(config.filter_slot, config.filter_wheel_id)

            # Determine starting position. restore_to is always the position the
            # focuser was at *before this run touched it* — even when a manual
            # start_position is given — so a failed/aborted run always lands back
            # where the user actually was, not at the requested sweep centre.
            focuser_status = await focuser.get_status()
            restore_to = focuser_status.position or 0
            start_pos = restore_to

            if config.start_position is not None:
                logger.info("autofocus.moving_to_start_position", position=config.start_position)
                await asyncio.wait_for(focuser.move_to(config.start_position), timeout=_MOVE_TIMEOUT)
                start_pos = config.start_position

            positions = [
                start_pos + (i - config.num_steps) * config.step_size
                for i in range(run.total_steps)
            ]
            positions = [max(0, p) for p in positions]

            await self._bus.publish(AutofocusStartedEvent(
                run_id=run.id,
                camera_id=config.camera_id,
                focuser_id=config.focuser_id,
                total_steps=run.total_steps,
            ))

            params = ExposureParams(
                duration=config.exposure_time,
                gain=config.gain,
                binning=config.binning,
                frame_type="light",
            )

            # When lock_stars is set, frozen after the first step that detects any
            # stars, and reused as the preferred population for every later step —
            # see star_detector.detect_stars() for how a step falls back to a fresh
            # detection if none of these stars can be matched.
            reference_stars: list[dict] | None = None

            for step_idx, position in enumerate(positions):
                run.current_step = step_idx + 1

                # 1. Move focuser
                logger.info(
                    "autofocus.moving",
                    step=run.current_step,
                    total=run.total_steps,
                    position=position,
                )
                await asyncio.wait_for(focuser.move_to(position), timeout=_MOVE_TIMEOUT)

                # 2. Expose
                logger.info(
                    "autofocus.exposing",
                    step=run.current_step,
                    duration=config.exposure_time,
                )
                image = await asyncio.wait_for(camera.expose(params), timeout=_EXPOSE_TIMEOUT)

                # Always derive dimensions from the FITS file itself so that
                # binning and subframe settings are reflected correctly.
                fits_w, fits_h = await asyncio.to_thread(_read_fits_shape, image.fits_path)
                run.image_width = fits_w or None
                run.image_height = fits_h or None

                # 3. Detect stars and measure sharpness (FWHM or HFD).
                # Wrapped in mem_guard so the heavy numpy/photutils work is
                # serialised with other memory-intensive tasks on low-RAM hosts.
                logger.info("autofocus.detecting_stars", step=run.current_step, metric=config.metric)
                async with mem_guard():
                    fwhm, star_count, raw_stars = await detect_stars(
                        image.fits_path,
                        metric=config.metric,
                        reference_stars=reference_stars if config.lock_stars else None,
                    )

                if config.lock_stars and reference_stars is None and raw_stars:
                    reference_stars = raw_stars

                run.latest_stars = [StarInfo(x=s["x"], y=s["y"], fwhm=s["fwhm"]) for s in raw_stars]

                # 4. Generate preview JPEGs (auto-stretch + linear) with star
                # circles burned in. Done AFTER star detection so circles are
                # always in the final file. _preview_paths is registered here
                # too, so the API endpoint never serves a circle-free version.
                auto_path = str(preview_dir / f"step_{run.current_step:02d}.jpg")
                linear_path = str(preview_dir / f"step_{run.current_step:02d}_linear.jpg")
                try:
                    from astrolol.imaging.preview import fits_to_jpeg, fits_to_jpeg_linear
                    await asyncio.to_thread(
                        fits_to_jpeg,
                        Path(image.fits_path),
                        Path(auto_path),
                        settings.jpeg_quality,
                    )
                    await asyncio.to_thread(
                        fits_to_jpeg_linear,
                        Path(image.fits_path),
                        Path(linear_path),
                        settings.jpeg_quality,
                    )
                    if raw_stars:
                        for p in (auto_path, linear_path):
                            await asyncio.to_thread(_annotate_preview, p, raw_stars, fits_w, fits_h)
                    self._preview_paths[run.current_step] = {"auto": auto_path, "linear": linear_path}
                except Exception as exc:
                    logger.warning("autofocus.preview_failed", step=run.current_step, error=str(exc))

                dp = FocusDataPoint(
                    step=run.current_step,
                    position=position,
                    fwhm=fwhm,
                    star_count=star_count,
                )
                run.data_points.append(dp)

                # 5. Refit the curve (live update for the UI)
                self._refit_curve(run)

                await self._bus.publish(AutofocusDataPointEvent(
                    run_id=run.id,
                    step=run.current_step,
                    total_steps=run.total_steps,
                    position=position,
                    fwhm=fwhm,
                    star_count=star_count,
                ))

                logger.info(
                    "autofocus.data_point",
                    step=run.current_step,
                    position=position,
                    metric=config.metric,
                    value=round(fwhm, 2),
                    stars=star_count,
                )

            # ── Move to optimal position ───────────────────────────────────────
            self._refit_curve(run)

            valid = [dp for dp in run.data_points if dp.fwhm > 0 and dp.star_count > 0]
            if not valid:
                run.sky_problem = True
                raise RuntimeError(
                    "No stars detected at any focuser position. "
                    "Check exposure time, focus range, or star detection threshold."
                )

            if run.curve_fit is None:
                # No valid parabola/hyperbola fit — the sampled points don't form a
                # real V/U shape (too noisy, range too narrow, or genuinely no focus
                # minimum in range). Silently picking the lowest-FWHM sample here
                # would report success on data that isn't a real focus curve, so
                # this is treated as a failure and the focuser is restored below.
                raise RuntimeError(
                    "Focus curve did not fit a valid V shape — the measured points "
                    "don't converge to a minimum in range. Try a larger step size, "
                    "more steps, or a longer exposure."
                )

            optimal_position = max(0, round(run.curve_fit.optimal_position))
            run.optimal_position = optimal_position
            logger.info("autofocus.moving_to_optimal", position=optimal_position)
            await asyncio.wait_for(focuser.move_to(optimal_position), timeout=_MOVE_TIMEOUT)

            run.status = "completed"
            run.completed_at = datetime.now(timezone.utc)

            await self._bus.publish(AutofocusCompletedEvent(
                run_id=run.id,
                optimal_position=optimal_position,
            ))
            logger.info("autofocus.completed", optimal_position=optimal_position)

        except asyncio.CancelledError:
            run.status = "aborted"
            run.completed_at = datetime.now(timezone.utc)
            await self._restore_focus(config.focuser_id, restore_to)
            await self._bus.publish(AutofocusAbortedEvent(run_id=run.id))
            logger.info("autofocus.aborted", run_id=run.id)
            raise

        except Exception as exc:
            run.status = "failed"
            run.error = str(exc)
            run.completed_at = datetime.now(timezone.utc)
            await self._restore_focus(config.focuser_id, restore_to)
            await self._bus.publish(AutofocusFailedEvent(run_id=run.id, reason=str(exc)))
            logger.error("autofocus.failed", run_id=run.id, error=str(exc), exc_info=True)

    async def _restore_focus(self, focuser_id: str, position: int | None) -> None:
        """After a failed or aborted run, put the focuser back where it started — the last
        good focus — instead of leaving it at the end of the sweep. Best effort."""
        if position is None:
            return
        try:
            focuser = self._device_manager.get_focuser(focuser_id)
            await asyncio.wait_for(focuser.move_to(position), timeout=_MOVE_TIMEOUT)
            logger.info("autofocus.focus_restored", position=position)
        except Exception as exc:
            logger.warning("autofocus.focus_restore_failed", position=position, error=str(exc))

    def _refit_curve(self, run: AutofocusRun) -> None:
        valid = [(dp.position, dp.fwhm) for dp in run.data_points if dp.fwhm > 0]
        if len(valid) < 3:
            return
        fit_fn = fit_hyperbola if run.config.fit_algo == "hyperbola" else fit_parabola
        result = fit_fn([p for p, _ in valid], [f for _, f in valid])
        if result is not None:
            a, b, c, optimal = result
            run.curve_fit = CurveFit(a=a, b=b, c=c, optimal_position=optimal)
        else:
            # A fit that was valid on an earlier (smaller) subset of points can
            # stop being valid once more data arrives — e.g. a good-looking early
            # V shape gets swamped by noisy points later in the sweep. Without
            # this, run.curve_fit would keep reporting that stale early fit
            # (and its optimal_position) all the way to the end of the run.
            run.curve_fit = None

    async def _select_filter(self, slot: int, filter_wheel_id: str | None) -> None:
        """Move the requested filter wheel to the requested slot (best-effort).

        filter_wheel_id pins the specific wheel on this camera's optical path (resolved
        by the UI from the active profile's equipment tree). Without it, falls back to
        "the first connected filter wheel" — only correct when exactly one is connected.
        """
        try:
            if filter_wheel_id is not None:
                fw = self._device_manager.get_filter_wheel(filter_wheel_id)
            else:
                fw_devices = [d for d in self._device_manager.list_connected() if d["kind"] == "filter_wheel"]
                if not fw_devices:
                    logger.warning("autofocus.no_filter_wheel", requested_slot=slot)
                    return
                fw = self._device_manager.get_filter_wheel(fw_devices[0]["device_id"])
            await fw.select_filter(slot)
            logger.info("autofocus.filter_selected", slot=slot, filter_wheel_id=filter_wheel_id)
        except Exception as exc:
            logger.warning("autofocus.filter_select_failed", slot=slot, error=str(exc))
