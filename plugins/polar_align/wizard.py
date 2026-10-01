"""Polar-alignment wizard: slews a mount through N points, plate-solves each, and fits
the mount's actual polar-axis offset via solver.fit_pole_offset.

Mirrors plugins/platesolve/centering.py's Centerer shape -- the closest existing
precedent in this codebase for a slew-then-solve loop -- but platesolve is reached only
through app.state (duck-typed), never imported directly, per the plugin-isolation rule
in astrolol/core/plugin_api.py ("plugins must not import from each other directly").
That's also why solve_manager.solve() takes **kwargs rather than a SolveRequest
instance: building one here would require importing plugins.platesolve.models.

CONVERGING (the live, re-solve-without-re-slewing phase that lets the user watch the
error shrink while turning alt/az knobs) is deliberately NOT implemented here. It needs
its own new pure function -- the fitted axis from this module's observations is not
valid once the user starts turning knobs, so "re-solve and report" is a different math
problem, not a repeat of fit_pole_offset -- see SPEC.md section 3. This module currently
stops at DONE once the initial fit is in.
"""
from __future__ import annotations

import asyncio
import contextlib
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

import astropy.units as u
import structlog
from astropy.coordinates import SkyCoord
from pydantic import BaseModel, Field

from astrolol.config.user_settings import MountDeviceSettings
from astrolol.core.events.models import BaseEvent
from astrolol.equipment.models import SiteItem
from astrolol.equipment.optical_path import find_profile_site
from astrolol.imaging.models import ExposureRequest
from astrolol.mount.sky import altitude_of, icrs_to_jnow
from plugins.polar_align.events import (
    PolarAlignFitCompleted,
    PolarAlignPointSolved,
    PolarAlignPointStarted,
    PolarAlignWizardCancelled,
    PolarAlignWizardCompleted,
    PolarAlignWizardFailed,
    PolarAlignWizardStarted,
)
from plugins.polar_align.solver import Observation, PoleOffset, fit_pole_offset

logger = structlog.get_logger()

SLEW_TIMEOUT_S = 300.0
MAX_SOLVE_ATTEMPTS = 3
MAX_DEC_DRIFT_ARCMIN = 1.0


class WizardRequest(BaseModel):
    mount_id: str
    camera_id: str
    exposure_s: float = Field(default=5.0, gt=0)
    binning: int = Field(default=2, ge=1)
    gain: int | None = None
    step_deg: float = Field(
        default=45.0, ge=-80.0, le=80.0,
        description="Signed RA step between points; sign picks the slew direction. "
        "Bounded well clear of the 180deg degenerate case solver.py rejects.",
    )
    # SPEC.md section 6.3: 3 points only for v1 -- a 2-point fit is only reliable away
    # from the equator and solver.py's own guard will reject it near the equator anyway.
    n_points: Literal[3] = 3


class WizardPoint(BaseModel):
    index: int
    mount_ra_hours: float
    solved_ra_hours: float
    solved_dec_deg: float
    when: datetime


class WizardRun(BaseModel):
    id: str
    status: Literal["running", "completed", "failed", "cancelled"] = "running"
    request: WizardRequest
    points: list[WizardPoint] = Field(default_factory=list)
    result: PoleOffset | None = None
    error: str | None = None
    started_at: datetime


def _now() -> datetime:
    return datetime.now(timezone.utc)


class PolarAlignWizard:
    """Runs one wizard pass. One at a time: see plugin.py's WizardEngine for the
    task/cancel/current-run bookkeeping (mirrors plugins/autofocus's AutofocusEngine)."""

    def __init__(self, app: Any, bus: Any) -> None:
        self._app = app
        self._bus = bus

    async def run(self, run: WizardRun) -> None:
        """Mutates `run` in place as the wizard progresses (status, points, result/error) --
        the caller (WizardEngine) creates `run` and holds the same reference as
        `current_run`, so progress is visible immediately rather than only once this
        coroutine returns. Mirrors plugins/autofocus/engine.py's AutofocusEngine._run."""
        run_id, req = run.id, run.request
        app = self._app

        try:
            mm = getattr(app.state, "mount_manager", None)
            im = getattr(app.state, "imager_manager", None)
            solve_manager = getattr(app.state, "solve_manager", None)
            if mm is None or im is None:
                raise RuntimeError("Polar alignment needs the mount and imager managers")
            if solve_manager is None or not hasattr(solve_manager, "solve"):
                raise RuntimeError(
                    "Polar alignment needs the platesolve plugin enabled (solve_manager.solve)"
                )

            logger.info("polar_align.wizard_started", run_id=run_id, mount_id=req.mount_id)
            await self._publish(PolarAlignWizardStarted(run_id=run_id))

            site = self._site(app)
            if site is None:
                raise ValueError(
                    "No site location configured for the active profile -- polar alignment "
                    "needs latitude/longitude to fit against true north/south"
                )

            status0 = await mm.get_status(req.mount_id)
            if status0.is_slewing:
                raise ValueError(f"Mount '{req.mount_id}' is already slewing")
            start_pier = status0.pier_side
            # ICRS dec, not dec_jnow: the wizard commands a fixed ICRS dec across all
            # points (see _plan_targets), but JNow dec legitimately varies by RA for a
            # perfectly constant ICRS dec -- full precession+nutation+aberration is a 3D
            # rotation, not a per-coordinate offset -- so comparing dec_jnow across points
            # at different RA would false-positive on a perfectly healthy mount.
            start_dec_icrs = status0.dec or 0.0

            mount_settings = self._mount_settings(app, req.mount_id)
            targets = self._plan_targets(status0.ra, status0.dec, req)
            for i, coord in enumerate(targets):
                alt = altitude_of(coord, _now(), site.latitude, site.longitude)
                if alt < mount_settings.horizon_min_alt_deg:
                    raise ValueError(
                        f"Point {i} ({coord.ra.to_string(unit='hour')} "
                        f"{coord.dec.to_string(unit='deg')}) would be below the horizon limit "
                        f"({alt:.1f}deg < {mount_settings.horizon_min_alt_deg:g}deg) -- aborting "
                        "before moving the mount"
                    )

            with self._suspend_auto_flip(app, req.mount_id):
                for i, coord in enumerate(targets):
                    await self._publish(PolarAlignPointStarted(run_id=run_id, index=i))
                    await self._slew(mm, req.mount_id, coord, name=f"polar_align_{i}")

                    status = await mm.get_status(req.mount_id)
                    if status.pier_side != start_pier:
                        raise RuntimeError(
                            f"Pier side changed mid-run ({start_pier} -> {status.pier_side}) -- "
                            "a meridian flip invalidates the fit; keep all points on one side "
                            "of the meridian"
                        )
                    if abs((status.dec or 0.0) - start_dec_icrs) * 60.0 > MAX_DEC_DRIFT_ARCMIN:
                        raise RuntimeError(
                            f"Dec drifted by more than {MAX_DEC_DRIFT_ARCMIN:g}' mid-run -- "
                            "check for an active mount alignment/pointing model and clear it "
                            "before running polar alignment"
                        )

                    point = await self._solve_point(im, solve_manager, req, i, status)
                    run.points.append(point)
                    logger.info(
                        "polar_align.point_solved", run_id=run_id, index=i,
                        solved_ra_hours=point.solved_ra_hours, solved_dec_deg=point.solved_dec_deg,
                    )
                    await self._publish(
                        PolarAlignPointSolved(
                            run_id=run_id, index=i,
                            solved_ra_hours=point.solved_ra_hours, solved_dec_deg=point.solved_dec_deg,
                        )
                    )

                run.result = fit_pole_offset(
                    [
                        Observation(
                            solved_ra_hours=p.solved_ra_hours,
                            solved_dec_deg=p.solved_dec_deg,
                            mount_ra_hours=p.mount_ra_hours,
                            when=p.when,
                        )
                        for p in run.points
                    ],
                    site.latitude,
                    site.longitude,
                    _now(),
                )
                run.status = "completed"
                logger.info(
                    "polar_align.fit_completed", run_id=run_id,
                    alt_error_arcmin=run.result.alt_error_arcmin,
                    az_error_arcmin=run.result.az_error_arcmin,
                )
                await self._publish(
                    PolarAlignFitCompleted(
                        run_id=run_id,
                        alt_error_arcmin=run.result.alt_error_arcmin,
                        az_error_arcmin=run.result.az_error_arcmin,
                    )
                )
                await self._publish(PolarAlignWizardCompleted(run_id=run_id))
        except asyncio.CancelledError:
            run.status = "cancelled"
            await self._publish(PolarAlignWizardCancelled(run_id=run_id))
            raise
        except Exception as exc:
            run.status = "failed"
            run.error = str(exc)
            logger.warning("polar_align.wizard_failed", run_id=run_id, error=str(exc))
            await self._publish(PolarAlignWizardFailed(run_id=run_id, reason=str(exc)))

        return run

    # ------------------------------------------------------------------

    def _plan_targets(self, start_ra_h: float, start_dec_deg: float, req: WizardRequest) -> list[SkyCoord]:
        """ICRS targets for each point: fixed Dec, RA stepped by step_deg from wherever
        the mount currently points (SPEC.md section 3's "target selection" decision)."""
        targets = []
        for i in range(req.n_points):
            ra_h = (start_ra_h + i * req.step_deg / 15.0) % 24.0
            targets.append(SkyCoord(ra=ra_h * u.hourangle, dec=start_dec_deg * u.deg, frame="icrs"))
        return targets

    def _site(self, app: Any) -> SiteItem | None:
        profile = getattr(app.state, "active_profile", None)
        equipment_store = getattr(app.state, "equipment_store", None)
        if profile is None or equipment_store is None:
            return None
        return find_profile_site(profile, equipment_store)

    def _mount_settings(self, app: Any, device_id: str) -> MountDeviceSettings:
        profile_store = getattr(app.state, "profile_store", None)
        if profile_store is None:
            return MountDeviceSettings()
        raw = profile_store.get_user_settings().mount_settings.get(device_id, {})
        return MountDeviceSettings(**raw)

    def _suspend_auto_flip(self, app: Any, mount_id: str) -> contextlib.AbstractContextManager[None]:
        """Same getattr/hasattr idiom as plugins/sequencer/runner.py's
        _auto_flip_suspended -- suspends for the whole run, CONVERGING included once that
        phase exists, since MountManager's background automation loop would otherwise flip
        the mount mid-adjustment."""
        mm = getattr(app.state, "mount_manager", None)
        if mm is None or not hasattr(mm, "suspend_auto_flip"):
            return contextlib.nullcontext()
        return mm.suspend_auto_flip(mount_id)

    async def _slew(self, mm: Any, mount_id: str, coord: SkyCoord, name: str) -> None:
        await mm.set_target(mount_id, coord, name=name, source="polar_align")
        q = self._bus.subscribe()
        try:
            await mm.slew(mount_id)
            async with asyncio.timeout(SLEW_TIMEOUT_S):
                while True:
                    event: BaseEvent = await q.get()
                    if getattr(event, "device_id", None) != mount_id:
                        continue
                    etype = getattr(event, "type", "")
                    if etype == "mount.slew_completed":
                        return
                    if etype in ("mount.slew_aborted", "mount.operation_failed"):
                        raise RuntimeError(f"Slew failed: {getattr(event, 'reason', None) or etype}")
        except TimeoutError:
            raise RuntimeError(f"Slew timed out after {SLEW_TIMEOUT_S:.0f}s") from None
        finally:
            self._bus.unsubscribe(q)

    async def _solve_point(
        self, im: Any, solve_manager: Any, req: WizardRequest, index: int, status: Any
    ) -> WizardPoint:
        last_error: str | None = None
        for attempt in range(1, MAX_SOLVE_ATTEMPTS + 1):
            t0 = _now()
            exposure = await im.expose(
                req.camera_id,
                ExposureRequest(duration=req.exposure_s, binning=req.binning, gain=req.gain, save=False),
            )
            when = t0 + timedelta(seconds=req.exposure_s / 2.0)
            try:
                result = await solve_manager.solve(
                    fits_path=str(exposure.fits_path),
                    ra_hint=status.ra * 15.0,
                    dec_hint=status.dec,
                )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                last_error = str(exc)
                logger.warning(
                    "polar_align.solve_attempt_failed", index=index, attempt=attempt, error=last_error
                )
                continue
            icrs_coord = SkyCoord(ra=result.ra * u.deg, dec=result.dec * u.deg, frame="icrs")
            solved_ra_h, solved_dec_deg = icrs_to_jnow(icrs_coord, when)
            return WizardPoint(
                index=index,
                mount_ra_hours=status.ra_jnow,
                solved_ra_hours=solved_ra_h,
                solved_dec_deg=solved_dec_deg,
                when=when,
            )
        raise RuntimeError(
            f"Plate solve failed for point {index} after {MAX_SOLVE_ATTEMPTS} attempts: {last_error}"
        )

    async def _publish(self, event: BaseEvent) -> None:
        """Best-effort: a missing/misbehaving event bus must never break the wizard run
        itself, only its live progress reporting."""
        try:
            await self._bus.publish(event)
        except Exception as exc:
            logger.debug("polar_align.event_publish_failed", event_type=event.type, error=str(exc))


class WizardEngine:
    """Task lifecycle (start/cancel/current run) around PolarAlignWizard -- one run at a
    time, server-wide. Mirrors plugins/autofocus/engine.py's AutofocusEngine."""

    def __init__(self, app: Any, event_bus: Any) -> None:
        self._wizard = PolarAlignWizard(app, event_bus)
        self._current_run: WizardRun | None = None
        self._task: asyncio.Task[None] | None = None

    @property
    def current_run(self) -> WizardRun | None:
        return self._current_run

    async def start(self, req: WizardRequest) -> WizardRun:
        if self._task is not None and not self._task.done():
            raise ValueError("Polar alignment is already running. Cancel it first.")
        run = WizardRun(id=uuid.uuid4().hex[:12], request=req, started_at=_now())
        self._current_run = run
        self._task = asyncio.create_task(self._wizard.run(run), name=f"polar_align_{run.id}")
        return run

    async def cancel(self) -> None:
        if self._task is not None and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
