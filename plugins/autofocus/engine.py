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
from datetime import datetime, timezone
from pathlib import Path

import structlog

from astrolol.config.settings import settings
from astrolol.core.events import EventBus
from astrolol.devices.base.models import ExposureParams
from astrolol.devices.manager import DeviceManager
from plugins.autofocus.algorithms import fit_parabola
from plugins.autofocus.models import (
    AutofocusAbortedEvent,
    AutofocusCompletedEvent,
    AutofocusConfig,
    AutofocusDataPointEvent,
    AutofocusFailedEvent,
    AutofocusRun,
    AutofocusStartedEvent,
    CurveFit,
    FocusDataPoint,
    StarInfo,
)
from plugins.autofocus.star_detector import detect_stars

logger = structlog.get_logger()

_MOVE_TIMEOUT = 120.0   # seconds to wait for a single focuser move
_EXPOSE_TIMEOUT = 300.0  # seconds to wait for a single exposure


class AutofocusEngine:
    """Manages one autofocus run at a time."""

    def __init__(self, event_bus: EventBus, device_manager: DeviceManager) -> None:
        self._bus = event_bus
        self._device_manager = device_manager
        self._current_run: AutofocusRun | None = None
        self._task: asyncio.Task | None = None
        # Maps step number (1-indexed) → server-side preview JPEG path
        self._preview_paths: dict[int, str] = {}

    @property
    def current_run(self) -> AutofocusRun | None:
        return self._current_run

    def preview_path(self, step: int) -> str | None:
        return self._preview_paths.get(step)

    async def start(self, config: AutofocusConfig) -> AutofocusRun:
        if self._task is not None and not self._task.done():
            raise ValueError("Autofocus is already running. Call abort() first.")

        total_steps = config.num_steps * 2 + 1
        run = AutofocusRun(config=config, status="running", total_steps=total_steps)
        self._current_run = run
        self._preview_paths.clear()

        self._task = asyncio.create_task(self._run(run), name=f"autofocus_{run.id}")
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

        try:
            camera = self._device_manager.get_camera(config.camera_id)
            focuser = self._device_manager.get_focuser(config.focuser_id)

            # Optional: change filter before starting
            if config.filter_slot is not None:
                await self._select_filter(config.filter_slot)

            # Determine starting position
            focuser_status = await focuser.get_status()
            start_pos = focuser_status.position or 0

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

                # 3. Generate preview JPEG
                preview_path = str(preview_dir / f"step_{run.current_step:02d}.jpg")
                try:
                    from astrolol.imaging.preview import fits_to_jpeg
                    await asyncio.to_thread(
                        fits_to_jpeg,
                        Path(image.fits_path),
                        Path(preview_path),
                        settings.jpeg_quality,
                    )
                    self._preview_paths[run.current_step] = preview_path
                except Exception as exc:
                    logger.warning("autofocus.preview_failed", step=run.current_step, error=str(exc))
                    # Keep fits path as fallback (won't be JPEG-servable but doesn't crash)
                    self._preview_paths[run.current_step] = image.fits_path

                # 4. Detect stars and measure FWHM
                logger.info("autofocus.detecting_stars", step=run.current_step)
                fwhm, star_count, raw_stars = await detect_stars(image.fits_path)

                run.latest_stars = [StarInfo(x=s["x"], y=s["y"], fwhm=s["fwhm"]) for s in raw_stars]
                run.image_width = image.width
                run.image_height = image.height

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
                    fwhm=round(fwhm, 2),
                    stars=star_count,
                )

            # ── Move to optimal position ───────────────────────────────────────
            self._refit_curve(run)

            if run.curve_fit is not None:
                optimal_position = max(0, round(run.curve_fit.optimal_position))
            else:
                # No valid parabola — use the position with the lowest FWHM
                valid = [dp for dp in run.data_points if dp.fwhm > 0]
                if valid:
                    optimal_position = min(valid, key=lambda dp: dp.fwhm).position
                else:
                    optimal_position = start_pos

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
            await self._bus.publish(AutofocusAbortedEvent(run_id=run.id))
            logger.info("autofocus.aborted", run_id=run.id)
            raise

        except Exception as exc:
            run.status = "failed"
            run.error = str(exc)
            run.completed_at = datetime.now(timezone.utc)
            await self._bus.publish(AutofocusFailedEvent(run_id=run.id, reason=str(exc)))
            logger.error("autofocus.failed", run_id=run.id, error=str(exc), exc_info=True)

    def _refit_curve(self, run: AutofocusRun) -> None:
        valid = [(dp.position, dp.fwhm) for dp in run.data_points if dp.fwhm > 0]
        if len(valid) < 3:
            return
        result = fit_parabola([p for p, _ in valid], [f for _, f in valid])
        if result is not None:
            a, b, c, optimal = result
            run.curve_fit = CurveFit(a=a, b=b, c=c, optimal_position=optimal)

    async def _select_filter(self, slot: int) -> None:
        """Move the first connected filter wheel to the requested slot (best-effort)."""
        try:
            fw_devices = [d for d in self._device_manager.list_connected() if d["kind"] == "filter_wheel"]
            if fw_devices:
                fw = self._device_manager.get_filter_wheel(fw_devices[0]["device_id"])
                await fw.select_filter(slot)
                logger.info("autofocus.filter_selected", slot=slot)
            else:
                logger.warning("autofocus.no_filter_wheel", requested_slot=slot)
        except Exception as exc:
            logger.warning("autofocus.filter_select_failed", slot=slot, error=str(exc))
