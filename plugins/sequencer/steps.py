"""Step implementations: the hardware actions the runner performs.

A step either succeeds, is *unavailable* (the plugin or device it needs is absent → a
``step_skipped`` event, and the run continues), or *fails* (→ ``StepError``, handled by
the task's error policy). Nothing fails silently.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from typing import Any, Protocol, cast

import structlog

from astrolol.core.events.models import BaseEvent
from astrolol.core.guiding import Guider, GuiderNotConnected, SettleParams
from astrolol.core.sequencer.events import (
    SequencerStepFailed,
    SequencerStepFinished,
    SequencerStepSkipped,
    SequencerStepStarted,
    StepDetails,
    StepKind,
)
from astrolol.core.sequencer.models import Activity, ExposureGroup, ImagingTask, StallKind
from plugins.sequencer.devices import LaneDevices
from plugins.sequencer.settings import SequencerSettings
from plugins.sequencer.targets import ResolvedTarget, TargetUnresolvable, resolve_target

logger = structlog.get_logger()

# Steps after which a retry must re-run the task setup (slew → center → guide).
# Failures while exposing or changing filters are retried in place.
SETUP_STEPS: frozenset[str] = frozenset(
    {
        "resolve_target",
        "slew",
        "center",
        "stop_guiding",
        "start_guiding",
        "autofocus",
        "meridian_flip",
    }
)


class StepError(Exception):
    """A step ran and failed. ``stall_kind`` is set for sky-dependent failures."""

    def __init__(self, step: StepKind, message: str, stall_kind: StallKind | None = None) -> None:
        super().__init__(message)
        self.step = step
        self.stall_kind = stall_kind

    @property
    def needs_setup(self) -> bool:
        return self.step in SETUP_STEPS


class StepHost(Protocol):
    """What steps need from the runner."""

    app: Any
    bus: Any

    @property
    def settings(self) -> SequencerSettings: ...

    async def set_activity(self, activity: Activity | None, message: str | None) -> None: ...


class Steps:
    def __init__(self, host: StepHost) -> None:
        self._host = host

    # ── Plumbing ───────────────────────────────────────────────────────────

    @property
    def _app(self) -> Any:
        return self._host.app

    def _state(self, name: str) -> Any:
        return getattr(self._app.state, name, None)

    async def _publish(self, event: BaseEvent) -> None:
        await self._host.bus.publish(event)

    async def _started(
        self, task_id: str | None, step: StepKind, activity: Activity | None, message: str
    ) -> float:
        await self._host.set_activity(activity, message)
        await self._publish(SequencerStepStarted(task_id=task_id, step=step, message=message))
        logger.info("sequencer.step_started", task_id=task_id, step=step, message=message)
        return time.monotonic()

    async def _finished(
        self, task_id: str | None, step: StepKind, t0: float, details: StepDetails | None = None
    ) -> None:
        duration = round(time.monotonic() - t0, 2)
        await self._publish(
            SequencerStepFinished(
                task_id=task_id, step=step, duration_s=duration, details=details or {}
            )
        )
        logger.info(
            "sequencer.step_finished",
            task_id=task_id,
            step=step,
            duration_s=duration,
            **(details or {}),
        )

    async def skipped(self, task_id: str | None, step: StepKind, reason: str) -> None:
        await self._publish(SequencerStepSkipped(task_id=task_id, step=step, reason=reason))
        logger.warning("sequencer.step_skipped", task_id=task_id, step=step, reason=reason)

    async def failed_continue(self, task_id: str | None, step: StepKind, error: str) -> None:
        """A failure that doesn't stop the task (e.g. a dither that didn't settle)."""
        await self._publish(
            SequencerStepFailed(task_id=task_id, step=step, error=error, handling="continue")
        )
        logger.warning(
            "sequencer.step_failed", task_id=task_id, step=step, error=error, handling="continue"
        )

    async def _await_bus(
        self,
        action: Callable[[], Awaitable[None]],
        device_id: str,
        success: tuple[str, ...],
        failure: tuple[str, ...],
        timeout: float,
    ) -> BaseEvent:
        """Subscribe, run *action*, then wait for a matching event for *device_id*.

        Subscribing first means events published synchronously inside the action are seen.
        Returns the success event; raises RuntimeError on a failure event or timeout.
        """
        q = self._host.bus.subscribe()
        try:
            await action()
            async with asyncio.timeout(timeout):
                while True:
                    event = await q.get()
                    if getattr(event, "device_id", None) != device_id:
                        continue
                    etype = getattr(event, "type", "")
                    if etype in success:
                        return cast(BaseEvent, event)
                    if etype in failure:
                        reason = getattr(event, "reason", None) or etype
                        raise RuntimeError(reason)
        except TimeoutError:
            raise RuntimeError(f"timed out after {timeout:.0f} s") from None
        finally:
            self._host.bus.unsubscribe(q)

    # ── Mount ──────────────────────────────────────────────────────────────

    async def unpark(self, mount_id: str | None) -> None:
        mm = self._state("mount_manager")
        if mount_id is None or mm is None:
            await self.skipped(None, "unpark", "no mount connected")
            return
        try:
            status = await mm.get_status(mount_id)
        except Exception as exc:
            raise StepError("unpark", f"Could not read mount status: {exc}") from exc
        if not status.is_parked:
            return
        t0 = await self._started(None, "unpark", Activity.UNPARKING, "Unparking mount")
        try:
            await mm.unpark(mount_id)
        except Exception as exc:
            raise StepError("unpark", f"Unpark failed: {exc}") from exc
        await self._finished(None, "unpark", t0)

    async def park(self, mount_id: str | None) -> None:
        mm = self._state("mount_manager")
        if mount_id is None or mm is None:
            await self.skipped(None, "park", "no mount connected")
            return
        await self.stop_guiding(None)
        t0 = await self._started(None, "park", Activity.PARKING, "Parking mount")
        try:
            await self._await_bus(
                lambda: mm.park(mount_id),
                mount_id,
                success=("mount.parked",),
                failure=("mount.operation_failed",),
                timeout=self._host.settings.park_timeout_s,
            )
        except Exception as exc:
            raise StepError("park", f"Park failed: {exc}") from exc
        await self._finished(None, "park", t0)

    async def slew(self, task: ImagingTask, target: ResolvedTarget, mount_id: str | None) -> None:
        mm = self._state("mount_manager")
        if mount_id is None or mm is None:
            raise StepError("slew", "No mount connected")
        assert target.ra is not None and target.dec is not None
        import astropy.units as u
        from astropy.coordinates import SkyCoord

        t0 = await self._started(task.id, "slew", Activity.SLEWING, f"Slewing to {target.name}")
        coord = SkyCoord(ra=target.ra * u.deg, dec=target.dec * u.deg, frame="icrs")
        try:
            await mm.set_target(mount_id, coord, name=target.name, source="sequencer")
            await self._await_bus(
                lambda: mm.slew(mount_id),
                mount_id,
                success=("mount.slew_completed",),
                failure=("mount.slew_aborted", "mount.operation_failed"),
                timeout=self._host.settings.slew_timeout_s,
            )
        except Exception as exc:
            raise StepError("slew", f"Slew to {target.name} failed: {exc}") from exc
        await self._finished(
            task.id, "slew", t0, {"ra": round(target.ra, 5), "dec": round(target.dec, 5)}
        )

    async def meridian_flip(self, task: ImagingTask, mount_id: str) -> bool:
        """Flip the mount. Returns False if the mount says no flip is needed."""
        mm = self._state("mount_manager")
        before = await mm.get_status(mount_id)
        t0 = await self._started(task.id, "meridian_flip", Activity.MERIDIAN_FLIP, "Meridian flip")
        try:
            await self._await_bus(
                lambda: mm.meridian_flip(mount_id),
                mount_id,
                success=("mount.meridian_flip_completed",),
                failure=("mount.slew_aborted", "mount.operation_failed"),
                timeout=self._host.settings.flip_timeout_s,
            )
        except ValueError as exc:
            if "No meridian flip needed" not in str(exc):
                raise StepError("meridian_flip", f"Meridian flip failed: {exc}") from exc
            await self.skipped(task.id, "meridian_flip", str(exc))
            return False
        except Exception as exc:
            raise StepError("meridian_flip", f"Meridian flip failed: {exc}") from exc
        after = await mm.get_status(mount_id)
        await self._finished(
            task.id,
            "meridian_flip",
            t0,
            {
                "pier_before": before.pier_side,
                "pier_after": after.pier_side,
                "hour_angle": round(after.hour_angle, 3) if after.hour_angle is not None else None,
            },
        )
        return True

    async def center(self, task: ImagingTask, target: ResolvedTarget, devices: LaneDevices) -> None:
        solve_manager = self._state("solve_manager")
        if solve_manager is None:
            await self.skipped(task.id, "center", "plate solving plugin not enabled")
            return
        if not hasattr(solve_manager, "center"):
            await self.skipped(task.id, "center", "plate solving plugin has no centering support")
            return
        if devices.mount_id is None or devices.camera_id is None:
            raise StepError("center", "Centering needs a connected mount and camera")
        assert target.ra is not None and target.dec is not None
        cfg = self._host.settings
        t0 = await self._started(task.id, "center", Activity.CENTERING, f"Centering {target.name}")
        try:
            result = await solve_manager.center(
                mount_id=devices.mount_id,
                camera_id=devices.camera_id,
                ra=target.ra,
                dec=target.dec,
                name=target.name,
                slew_first=False,  # the task setup (or the flip) has just slewed
                tolerance_arcsec=cfg.center_tolerance_arcsec,
                max_attempts=cfg.center_max_attempts,
                exposure_s=cfg.center_exposure_s,
                binning=cfg.center_binning,
            )
        except Exception as exc:
            raise StepError("center", f"Centering failed: {exc}") from exc
        details: StepDetails = {
            "attempts": len(result.attempts),
            "final_error_arcsec": (
                round(result.final_error_arcsec, 1)
                if result.final_error_arcsec is not None
                else None
            ),
        }
        if not result.success:
            stall = StallKind.CENTERING if result.failure == "no_solution" else None
            raise StepError(
                "center", result.message or "Centering did not succeed", stall_kind=stall
            )
        await self._finished(task.id, "center", t0, details)

    # ── Guiding ────────────────────────────────────────────────────────────

    def _guider(self) -> Guider | None:
        guider: Guider | None = self._state("guider")
        return guider

    def _settle(self) -> SettleParams:
        cfg = self._host.settings
        return SettleParams(
            pixels=cfg.guide_settle_pixels,
            time=cfg.guide_settle_time_s,
            timeout=cfg.guide_settle_timeout_s,
        )

    async def stop_guiding(self, task_id: str | None) -> None:
        guider = self._guider()
        if guider is None:
            return
        status = guider.status()
        if not status.connected or not status.active:
            return
        t0 = await self._started(task_id, "stop_guiding", None, "Stopping guiding")
        try:
            await guider.stop()
        except Exception as exc:
            await self.failed_continue(task_id, "stop_guiding", str(exc))
            return
        await self._finished(task_id, "stop_guiding", t0)

    async def start_guiding(self, task_id: str) -> None:
        guider = self._guider()
        if guider is None:
            await self.skipped(
                task_id, "start_guiding", "no guider enabled (PHD2 or guide simulator)"
            )
            return
        if not guider.status().connected:
            raise StepError("start_guiding", f"The guider ({guider.name}) is not connected")
        t0 = await self._started(
            task_id, "start_guiding", Activity.STARTING_GUIDING, "Starting guiding"
        )
        try:
            await guider.guide(self._settle(), wait_settle=True)
        except GuiderNotConnected as exc:
            raise StepError("start_guiding", f"The guider is not connected: {exc}") from exc
        except Exception as exc:
            raise StepError(
                "start_guiding", f"Guiding did not start or settle: {exc}", StallKind.GUIDING
            ) from exc
        await self._finished(task_id, "start_guiding", t0)

    def guiding_mark(self) -> float | None:
        """Start of a guiding-statistics window (None without a guider)."""
        guider = self._guider()
        return None if guider is None else guider.mark()

    def guiding_stats(self, mark: float | None) -> dict[str, Any]:
        """Guiding RMS / unguided time / losses since *mark*, as SequencerFrameSaved fields."""
        guider = self._guider()
        if mark is None or guider is None:
            return {}
        try:
            stats = guider.stats(mark)
        except Exception as exc:
            logger.warning("sequencer.guiding_stats_failed", error=str(exc))
            return {}
        return {
            "guide_rms_total": stats.rms_total,
            "unguided_s": stats.unguided_s,
            "guiding_losses": stats.losses,
        }

    async def record_guiding_in_fits(self, fits_path: str, guiding: dict[str, Any]) -> None:
        """Write the frame's guiding figures into its FITS header (best effort)."""
        if not guiding:
            return
        from astrolol.imaging.imager import add_fits_header_cards

        cards: dict[str, tuple[Any, str]] = {
            "GUIDLOST": (guiding["unguided_s"], "[s] time without active guiding"),
            "GUIDLOSN": (guiding["guiding_losses"], "times guiding was interrupted"),
        }
        if guiding.get("guide_rms_total") is not None:
            cards["GUIDRMS"] = (guiding["guide_rms_total"], "[arcsec] total guiding RMS")
        try:
            await asyncio.to_thread(add_fits_header_cards, fits_path, cards)
        except Exception as exc:
            logger.warning(
                "sequencer.fits_guiding_cards_failed", fits_path=fits_path, error=str(exc)
            )

    async def dither(self, task_id: str) -> None:
        guider = self._guider()
        if guider is None:
            await self.skipped(task_id, "dither", "no guider enabled (PHD2 or guide simulator)")
            return
        if not guider.status().connected:
            await self.failed_continue(
                task_id, "dither", f"The guider ({guider.name}) is not connected"
            )
            return
        if not guider.health().guiding:
            await self.skipped(
                task_id, "dither", "guiding is down; restarting it will move the star anyway"
            )
            return
        cfg = self._host.settings
        t0 = await self._started(task_id, "dither", Activity.DITHERING, "Dithering")
        try:
            await guider.dither(cfg.dither_pixels, cfg.dither_ra_only, self._settle())
        except Exception as exc:
            await self.failed_continue(task_id, "dither", str(exc))
            return
        await self._finished(task_id, "dither", t0)

    # ── Imaging ────────────────────────────────────────────────────────────

    async def resolve_target(self, task: ImagingTask) -> ResolvedTarget:
        t0 = time.monotonic()
        try:
            resolved = await resolve_target(task.target, self._app)
        except TargetUnresolvable as exc:
            raise StepError("resolve_target", str(exc)) from exc
        if resolved.warning:
            await self.failed_continue(task.id, "resolve_target", resolved.warning)
        await self._finished(
            task.id,
            "resolve_target",
            t0,
            {
                "source": resolved.source,
                "ra": round(resolved.ra, 5) if resolved.ra is not None else None,
                "dec": round(resolved.dec, 5) if resolved.dec is not None else None,
            },
        )
        return resolved

    async def change_filter(self, task_id: str, devices: LaneDevices, filter_name: str) -> None:
        fwm = self._state("filter_wheel_manager")
        if devices.filter_wheel_id is None or fwm is None:
            raise StepError("change_filter", f"No filter wheel for camera '{devices.camera_id}'")
        try:
            status = await fwm.get_status(devices.filter_wheel_id)
        except Exception as exc:
            raise StepError("change_filter", f"Could not read the filter wheel: {exc}") from exc
        names = status.filter_names or []
        if filter_name not in names:
            raise StepError(
                "change_filter",
                f"Filter '{filter_name}' is not in the wheel ({', '.join(names) or 'no names'})",
            )
        slot = names.index(filter_name) + 1
        if status.current_slot == slot:
            return
        t0 = await self._started(
            task_id, "change_filter", Activity.CHANGING_FILTER, f"Filter → {filter_name}"
        )
        try:
            await fwm.select_filter(devices.filter_wheel_id, slot)
        except Exception as exc:
            raise StepError(
                "change_filter", f"Changing to filter '{filter_name}' failed: {exc}"
            ) from exc
        await self._finished(task_id, "change_filter", t0, {"filter": filter_name, "slot": slot})

    async def expose(self, task: ImagingTask, devices: LaneDevices, group: ExposureGroup) -> str:
        """Take one saved frame; returns the FITS path. Cancellation aborts the exposure."""
        im = self._state("imager_manager")
        if im is None or devices.camera_id is None:
            raise StepError("expose", "No camera connected")
        from astrolol.imaging.models import ExposureRequest

        req = ExposureRequest(
            duration=group.duration,
            gain=group.gain,
            binning=group.binning,
            frame_type=group.frame_type,
            save=True,
            object_name=task.target.name,
        )
        timeout = group.duration + self._host.settings.exposure_timeout_margin_s
        try:
            async with asyncio.timeout(timeout):
                result = await im.expose(devices.camera_id, req)
        except TimeoutError:
            raise StepError("expose", f"Exposure timed out after {timeout:.0f} s") from None
        except Exception as exc:
            raise StepError("expose", f"Exposure failed: {exc}") from exc
        return str(result.fits_path)
