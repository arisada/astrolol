"""Polar-alignment wizard: slews a mount through N points, plate-solves each, and fits
the mount's actual polar-axis offset via solver.fit_pole_offset.

Mirrors plugins/platesolve/centering.py's Centerer shape -- the closest existing
precedent in this codebase for a slew-then-solve loop -- but platesolve is reached only
through app.state (duck-typed), never imported directly, per the plugin-isolation rule
in astrolol/core/plugin_api.py ("plugins must not import from each other directly").
That's also why solve_manager.solve() takes **kwargs rather than a SolveRequest
instance: building one here would require importing plugins.platesolve.models.

CONVERGING (the live, re-solve-without-re-slewing phase that lets the user watch the
error shrink while turning alt/az knobs) uses solver.update_pole_offset, a genuinely
different pure function from fit_pole_offset -- the fitted axis from the initial 3-point
run is not something CONVERGING re-derives, it's an input: each recheck re-solves once
and measures how far that implies the knobs have physically moved the axis since. The
reference point and binning/exposure settings used for a recheck solve are deliberately
reused/tightened versions of the main fit's, not fresh ones at the main fit's full
precision: repeated plate-solving is the expensive part of this whole feature, and a
recheck only needs to track whether the error is shrinking, not re-establish it from
scratch -- see WizardRequest's converge_* fields.
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
from astrolol.mount.sky import alt_az, icrs_to_jnow, jnow_to_icrs, local_sidereal_time_h
from plugins.polar_align.events import (
    PolarAlignErrorUpdated,
    PolarAlignFitCompleted,
    PolarAlignPointSolved,
    PolarAlignPointStarted,
    PolarAlignWizardCancelled,
    PolarAlignWizardCompleted,
    PolarAlignWizardFailed,
    PolarAlignWizardStarted,
)
from plugins.polar_align.solver import (
    ConvergenceUpdate,
    Observation,
    PoleOffset,
    _wrap_hours,
    fit_pole_offset,
    reference_conditioning_margin_deg,
    update_pole_offset,
)

logger = structlog.get_logger()

SLEW_TIMEOUT_S = 300.0
MAX_SOLVE_ATTEMPTS = 3
MAX_DEC_DRIFT_ARCMIN = 1.0

# Target planning (see plan_targets). Auto-picked Dec candidates, as |Dec| (signed by the
# site's hemisphere): well clear of the pole (where precession puts the JNow pole ~9' from
# the ICRS one, and mounts behave awkwardly) and of the equator. The planner scores every
# candidate; the order here doesn't matter. Above roughly the site latitude, points never
# cross the east-west vertical plane where update_pole_offset's symmetric-plane guard
# fires, which is why the band leans high.
AUTO_DEC_CANDIDATES_DEG = (30.0, 35.0, 40.0, 45.0, 50.0, 55.0, 60.0, 65.0, 70.0)
MAX_ABS_DEC_DEG = 80.0
MIN_MERIDIAN_CLEARANCE_H = 0.5  # every point at least this far from the meridian -> no pier flip
MAX_ABS_HA_H = 6.0  # beyond 6h from the meridian a German mount goes counterweight-up
# How long after planning a point must stay usable: the run itself plus a typical
# CONVERGING session at the last point (which keeps tracking -- its Hour Angle grows).
PLAN_VALIDITY_H = 0.5
# Conditioning margins beyond this are all "comfortably fine"; above it the planner prefers
# higher-altitude plans instead of chasing extra margin.
COMFORTABLE_MARGIN_DEG = 15.0


class WizardRequest(BaseModel):
    mount_id: str
    camera_id: str
    exposure_s: float = Field(default=5.0, gt=0)
    binning: int = Field(default=2, ge=1)
    gain: int | None = None
    step_deg: float = Field(
        default=30.0, ge=10.0, le=40.0,
        description="RA step between points (magnitude only -- the direction is chosen from the "
        "mount's current side of the meridian so every point stays on that side). At most 40deg "
        "so 3 points fit between the meridian clearance and the 6h counterweight-down limit.",
    )
    dec_deg: float | None = Field(
        default=None, ge=-MAX_ABS_DEC_DEG, le=MAX_ABS_DEC_DEG,
        description="JNow (mechanical) Dec for all points. None (default) lets the wizard pick "
        "the best-conditioned Dec from AUTO_DEC_CANDIDATES_DEG; it never inherits whatever Dec "
        "the mount happens to be pointing at (which may be the pole, after a park).",
    )
    settle_s: float = Field(default=2.0, ge=0.0, le=60.0, description="Wait after each slew before exposing")
    # SPEC.md section 6.3: 3 points only for v1 -- a 2-point fit is only reliable away
    # from the equator and solver.py's own guard will reject it near the equator anyway.
    n_points: Literal[3] = 3
    # CONVERGING-phase recheck settings -- deliberately separate from the main fit's own
    # exposure_s/binning above, and defaulting to faster/smaller rather than inheriting
    # them: a recheck only needs to track whether the error is shrinking, not re-establish
    # it at the main fit's precision, and repeated plate-solving is the expensive part of
    # this whole feature (see module docstring).
    converge_exposure_s: float | None = Field(default=None, gt=0)
    converge_binning: int | None = Field(default=None, ge=1)
    converge_search_radius_deg: float = Field(
        default=3.0, gt=0,
        description="ASTAP search radius for a recheck solve. Small and tight on purpose: "
        "the mount hasn't been slewed, only the knobs turned a little, so the true position "
        "is known to within a couple of degrees of the reference -- a small radius is what "
        "actually makes a recheck solve fast.",
    )


class TargetPlan(BaseModel):
    """The points the wizard will visit, fixed before the mount moves (see plan_targets)."""

    dec_jnow_deg: float = Field(description="JNow (mechanical) Dec held constant across all points")
    hour_angles_h: list[float] = Field(description="Hour Angle of each point, in visiting order")
    side: Literal["east", "west"] = Field(description="Side of the meridian all points are on")
    reference_margin_deg: float = Field(
        description="Predicted conditioning margin of the last point as the CONVERGING reference "
        "(solver.reference_conditioning_margin_deg, with the true pole standing in for the fit)"
    )


def plan_targets(
    latitude_deg: float,
    current_ha_h: float,
    step_deg: float,
    n_points: int,
    horizon_min_alt_deg: float,
    dec_deg: float | None = None,
) -> TargetPlan:
    """Choose a constant JNow Dec and a monotonic sequence of Hour Angles for the fit.

    Constraints (any violation rules a candidate out):
    - all points on the mount's *current* side of the meridian, at least
      MIN_MERIDIAN_CLEARANCE_H from it and at most MAX_ABS_HA_H -- so no GoTo in the run
      causes a pier flip, whatever Dec/RA the mount started at;
    - every point above the horizon limit now and PLAN_VALIDITY_H later;
    - the *last* point (where the mount stays, so the CONVERGING reference) clears
      update_pole_offset's conditioning guards over that same window.
    Among feasible candidates (Dec x start offset x stepping away from / toward the
    meridian), the one with the best reference margin wins, capped at
    COMFORTABLE_MARGIN_DEG, then the highest minimum altitude. Raises ValueError, before
    anything moves, if no candidate is feasible.
    """
    side = 1.0 if _wrap_hours(current_ha_h) >= 0 else -1.0
    step_h = abs(step_deg) / 15.0
    pole_dec = 90.0 if latitude_deg >= 0 else -90.0
    hemisphere = 1.0 if latitude_deg >= 0 else -1.0
    decs = [dec_deg] if dec_deg is not None else [hemisphere * d for d in AUTO_DEC_CANDIDATES_DEG]
    offsets = [MIN_MERIDIAN_CLEARANCE_H + 0.25 * k for k in range(int((MAX_ABS_HA_H - MIN_MERIDIAN_CLEARANCE_H) / 0.25) + 1)]

    best: tuple[tuple[float, float], TargetPlan] | None = None
    rejected_for = {"horizon": 0, "conditioning": 0}
    for dec in decs:
        for h0 in offsets:
            away = [side * (h0 + i * step_h) for i in range(n_points)]
            if any(abs(h) > MAX_ABS_HA_H for h in away):
                continue
            # away and away[::-1] are the same set of HA values -- min_alt doesn't
            # depend on visiting order, so compute it once instead of per direction.
            min_alt = min(
                alt_az(h + dt, dec, latitude_deg)[0] for h in away for dt in (0.0, PLAN_VALIDITY_H)
            )
            if min_alt < horizon_min_alt_deg:
                rejected_for["horizon"] += 2
                continue
            for has in (away, away[::-1]):
                margin = min(
                    reference_conditioning_margin_deg(0.0, pole_dec, has[-1] + dt, dec, latitude_deg)
                    for dt in (0.0, PLAN_VALIDITY_H)
                )
                if margin <= 0.0:
                    rejected_for["conditioning"] += 1
                    continue
                score = (min(margin, COMFORTABLE_MARGIN_DEG), min_alt)
                if best is None or score > best[0]:
                    best = (
                        score,
                        TargetPlan(
                            dec_jnow_deg=dec,
                            hour_angles_h=has,
                            side="west" if side > 0 else "east",
                            reference_margin_deg=margin,
                        ),
                    )
    if best is None:
        which = f"Dec {dec_deg:g}deg" if dec_deg is not None else "any Dec in the automatic range"
        side_name = "west" if side > 0 else "east"
        reason = (
            "below the horizon limit"
            if rejected_for["horizon"] >= rejected_for["conditioning"]
            else "too poorly conditioned for the live-adjustment rechecks"
        )
        raise ValueError(
            f"No usable set of {n_points} points at {which} on the {side_name} side of the "
            f"meridian (where the mount currently points) -- candidates were {reason}. "
            "Try a different Dec, or point the mount at the other side of the meridian first."
        )
    return best[1]


class WizardPoint(BaseModel):
    index: int
    mount_ra_hours: float
    solved_ra_hours: float
    solved_dec_deg: float
    when: datetime


class WizardRun(BaseModel):
    id: str
    status: Literal["running", "converging", "completed", "failed", "cancelled"] = "running"
    request: WizardRequest
    points: list[WizardPoint] = Field(default_factory=list)
    result: PoleOffset | None = None
    plan: TargetPlan | None = Field(default=None, description="The points chosen before slewing")
    convergence_reference_index: int | None = Field(
        default=None,
        description="Index into points used as the CONVERGING-phase reference -- always the "
        "last point, where the mount is still pointing (plan_targets makes that one the "
        "well-conditioned one)",
    )
    live_offset: ConvergenceUpdate | None = Field(
        default=None, description="Latest CONVERGING-phase reading, updated by each recheck"
    )
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

            # Plan everything before moving: constant *JNow* Dec (the mount's mechanical Dec
            # axis -- constant ICRS Dec would move it by up to ~9' between points, which
            # biases the fit), on the mount's current side of the meridian, above the
            # horizon, with a well-conditioned last point. Independent of the mount's
            # current Dec, which may well be the pole after a park.
            mount_settings = self._mount_settings(app, req.mount_id)
            current_ha = local_sidereal_time_h(_now(), site.longitude) - (status0.ra_jnow or 0.0)
            # plan_targets() is a pure-CPU grid search (hundreds of candidates, each a
            # handful of trig calls) -- off the event loop so it doesn't stall concurrent
            # requests/WebSocket delivery for the run's duration.
            plan = await asyncio.to_thread(
                plan_targets,
                site.latitude, current_ha, req.step_deg, req.n_points,
                mount_settings.horizon_min_alt_deg, req.dec_deg,
            )
            run.plan = plan
            logger.info(
                "polar_align.plan_selected", run_id=run_id, dec_jnow_deg=plan.dec_jnow_deg,
                hour_angles_h=plan.hour_angles_h, side=plan.side,
                reference_margin_deg=plan.reference_margin_deg,
            )
            first_dec_jnow: float | None = None

            with self._suspend_auto_flip(app, req.mount_id):
                for i, ha in enumerate(plan.hour_angles_h):
                    await self._publish(PolarAlignPointStarted(run_id=run_id, index=i))
                    coord = self._target_at(ha, plan.dec_jnow_deg, site.longitude)
                    await self._slew(mm, req.mount_id, coord, name=f"polar_align_{i}")
                    if req.settle_s > 0:
                        await asyncio.sleep(req.settle_s)

                    status = await mm.get_status(req.mount_id)
                    if status.pier_side != start_pier:
                        raise RuntimeError(
                            f"Pier side changed mid-run ({start_pier} -> {status.pier_side}) -- "
                            "a meridian flip invalidates the fit; keep all points on one side "
                            "of the meridian"
                        )
                    # dec_jnow, the mount's own mechanical Dec: that's what fit_pole_offset
                    # needs held constant. Compared to the first point as actually reached,
                    # not the plan, so a constant GoTo offset doesn't trip it.
                    dec_jnow = status.dec_jnow or 0.0
                    if first_dec_jnow is None:
                        first_dec_jnow = dec_jnow
                        # plan_targets() validated the horizon limit against the PLANNED
                        # dec_jnow/HA, before anything moved. A real mount can reach a
                        # meaningfully different position than planned -- e.g. a GoTo
                        # pointing error, plausible on exactly the badly-misaligned mount
                        # this wizard exists to fix -- so that validation only holds if the
                        # mount actually landed close to where it was told to. Re-check
                        # against where it actually is now, not just trust the plan.
                        actual_ha = local_sidereal_time_h(_now(), site.longitude) - (
                            status.ra_jnow or 0.0
                        )
                        actual_alt = alt_az(actual_ha, dec_jnow, site.latitude)[0]
                        if actual_alt < mount_settings.horizon_min_alt_deg:
                            raise RuntimeError(
                                f"First point landed at {actual_alt:.1f}deg altitude, below "
                                f"the {mount_settings.horizon_min_alt_deg:g}deg horizon limit, "
                                "even though the plan was above it -- the mount's GoTo is "
                                "landing somewhere other than commanded (check for a pointing "
                                "model / sync offset), so the plan's safety margins can't be "
                                "trusted"
                            )
                    elif abs(dec_jnow - first_dec_jnow) * 60.0 > MAX_DEC_DRIFT_ARCMIN:
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
                # The CONVERGING reference is the last point: it's where the mount still
                # points, so a recheck re-solves the same pointing. (Picking another, "better
                # conditioned" fit point instead -- as an earlier version did -- compared two
                # pointings 30-90deg apart and failed every recheck; plan_targets now makes
                # the last point the well-conditioned one instead.)
                run.convergence_reference_index = len(run.points) - 1
                # Not "completed": the wizard's own job (producing a fit) is done, but the
                # run as a whole isn't over until the user is satisfied with the live
                # knob-adjustment readings and says so (WizardEngine.cancel() during this
                # phase marks it completed then -- see that method's docstring).
                run.status = "converging"
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

    def _target_at(self, ha_h: float, dec_jnow_deg: float, longitude_deg: float) -> SkyCoord:
        """ICRS coordinate (what MountManager.set_target takes) for a planned Hour Angle and
        JNow Dec, evaluated right now -- so the point lands at its planned HA even though
        earlier points took a while."""
        now = _now()
        ra_jnow = (local_sidereal_time_h(now, longitude_deg) - ha_h) % 24.0
        return jnow_to_icrs(ra_jnow, dec_jnow_deg, now)

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

    async def recheck(self, run: WizardRun) -> None:
        """One CONVERGING-phase reading: expose, solve once (tight hint + small radius --
        see WizardRequest.converge_*, and the module docstring on why), and measure how far
        that implies the knobs have moved the axis since the fixed reference. Raises on a
        bad reading (solve failure, or an update_pole_offset conditioning/ambiguity guard)
        without touching run.status -- a single bad recheck isn't fatal to the run, the
        caller just doesn't get an updated live_offset this time and can try again."""
        if run.status != "converging":
            raise ValueError("Polar alignment is not in the converging phase")
        if run.result is None or not run.points:
            raise RuntimeError("No fit result to converge against")
        app = self._app
        im = getattr(app.state, "imager_manager", None)
        solve_manager = getattr(app.state, "solve_manager", None)
        if im is None or solve_manager is None or not hasattr(solve_manager, "solve"):
            raise RuntimeError(
                "Polar alignment needs the imager and platesolve plugin enabled (solve_manager.solve)"
            )
        site = self._site(app)
        if site is None:
            raise ValueError("No site location configured for the active profile")

        mm = getattr(app.state, "mount_manager", None)
        if mm is None:
            raise RuntimeError("Polar alignment needs the mount manager")

        req = run.request
        reference = run.points[-1]  # where the mount still points -- see run()
        exposure_s = req.converge_exposure_s or req.exposure_s
        binning = req.converge_binning or req.binning

        # The mount's own reported RA now: update_pole_offset carries the reference forward
        # by the motor rotation since it was taken (tracking, in the normal case).
        status = await mm.get_status(req.mount_id)
        t0 = _now()
        exposure = await im.expose(
            req.camera_id,
            ExposureRequest(duration=exposure_s, binning=binning, gain=req.gain, save=False),
        )
        when = t0 + timedelta(seconds=exposure_s / 2.0)
        result = await solve_manager.solve(
            fits_path=str(exposure.fits_path),
            ra_hint=reference.solved_ra_hours * 15.0,
            dec_hint=reference.solved_dec_deg,
            radius=req.converge_search_radius_deg,
        )
        icrs_coord = SkyCoord(ra=result.ra * u.deg, dec=result.dec * u.deg, frame="icrs")
        new_ra_h, new_dec = icrs_to_jnow(icrs_coord, when)

        run.live_offset = update_pole_offset(
            run.result.axis_ha_hours,
            run.result.axis_dec_deg,
            Observation(
                solved_ra_hours=reference.solved_ra_hours,
                solved_dec_deg=reference.solved_dec_deg,
                mount_ra_hours=reference.mount_ra_hours,
                when=reference.when,
            ),
            Observation(
                solved_ra_hours=new_ra_h,
                solved_dec_deg=new_dec,
                mount_ra_hours=status.ra_jnow,
                when=when,
            ),
            site.latitude,
            site.longitude,
        )
        logger.info(
            "polar_align.error_updated", run_id=run.id,
            alt_error_arcmin=run.live_offset.alt_error_arcmin,
            az_error_arcmin=run.live_offset.az_error_arcmin,
        )
        await self._publish(
            PolarAlignErrorUpdated(
                run_id=run.id,
                alt_error_arcmin=run.live_offset.alt_error_arcmin,
                az_error_arcmin=run.live_offset.az_error_arcmin,
            )
        )

    async def finish_converging(self, run: WizardRun) -> None:
        """The user is satisfied and stops CONVERGING -- a completion, not a cancellation
        (nothing failed; see WizardEngine.cancel())."""
        run.status = "completed"
        await self._publish(PolarAlignWizardCompleted(run_id=run.id))

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
        # The background task itself finishes normally on entering "converging" (see
        # PolarAlignWizard.run) -- rechecks from then on are one-shot calls, not a task --
        # so the task-done check above doesn't catch "still in the converging phase",
        # and a run sitting there is still very much in progress from the user's side.
        if self._current_run is not None and self._current_run.status == "converging":
            raise ValueError("Polar alignment is still converging. Finish or cancel it first.")
        run = WizardRun(id=uuid.uuid4().hex[:12], request=req, started_at=_now())
        self._current_run = run
        self._task = asyncio.create_task(self._wizard.run(run), name=f"polar_align_{run.id}")
        return run

    async def recheck(self) -> WizardRun:
        if self._current_run is None:
            raise ValueError("No polar alignment run has been started")
        try:
            await self._wizard.recheck(self._current_run)
        except Exception as exc:
            # Not fatal to the run (the caller just gets no new reading), but must not be
            # silent either: a recheck that keeps failing looks exactly like "the reading
            # never changes" otherwise.
            logger.warning(
                "polar_align.recheck_failed", run_id=self._current_run.id, error=str(exc),
                # A guard/solve rejection is an expected outcome; only a real bug needs a traceback.
                exc_info=not isinstance(exc, (ValueError, RuntimeError)),
            )
            raise
        return self._current_run

    async def cancel(self) -> None:
        """Stop the current run. During CONVERGING this is a completion, not an abort --
        see PolarAlignWizard.finish_converging."""
        if self._current_run is not None and self._current_run.status == "converging":
            await self._wizard.finish_converging(self._current_run)
            return
        if self._task is not None and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
