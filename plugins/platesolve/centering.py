"""Centering: slew → expose → solve → sync → re-slew, until the target is within tolerance.

Used by the sequencer (``await solve_manager.center(...)``), by the REST route
``POST /plugins/platesolve/center`` and, later, by a "slew & center" button.

A failure to *solve* (no stars, clouds, an obstruction) is reported as
``failure="no_solution"`` so callers can treat it as a sky problem and retry later; solving
but not converging within the tolerance is ``failure="not_converged"`` (a pointing or
mechanical problem). Mount errors (slew refused, timeout) raise.
"""

from __future__ import annotations

import asyncio
import math
import time
import uuid
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any, Literal

import structlog
from pydantic import BaseModel, Field

from astrolol.core.events.models import BaseEvent
from plugins.platesolve.events import (
    PlatesolveCenterAttempt,
    PlatesolveCenterFinished,
    PlatesolveCenterStarted,
)
from plugins.platesolve.models import SolveRequest, SolveResult

logger = structlog.get_logger()

SLEW_TIMEOUT_S = 300.0


class CenterRequest(BaseModel):
    mount_id: str
    camera_id: str
    ra: float = Field(ge=0.0, lt=360.0, description="Target ICRS RA, degrees")
    dec: float = Field(ge=-90.0, le=90.0, description="Target ICRS Dec, degrees")
    name: str | None = Field(default=None, description="Target name kept on the mount target")
    tolerance_arcsec: float = Field(default=60.0, gt=0)
    max_attempts: int = Field(default=5, ge=1, le=20)
    exposure_s: float = Field(default=5.0, gt=0)
    binning: int = Field(default=2, ge=1, le=4)
    gain: int | None = None
    slew_first: bool = Field(default=True, description="Slew to the target before the first solve")


class CenterAttempt(BaseModel):
    attempt: int
    solved_ra: float | None = None
    solved_dec: float | None = None
    error_arcsec: float | None = None  # distance from the target; None if not solved
    solve_error: str | None = None
    duration_s: float


class CenterResult(BaseModel):
    success: bool
    failure: Literal["no_solution", "not_converged"] | None = None
    message: str | None = None
    attempts: list[CenterAttempt] = []
    final_error_arcsec: float | None = None


class CenterRun(BaseModel):
    """A centering run started through the REST API."""

    id: str
    status: Literal["running", "completed", "failed", "cancelled"]
    request: CenterRequest
    result: CenterResult | None = None
    error: str | None = None
    started_at: datetime


def separation_arcsec(ra1: float, dec1: float, ra2: float, dec2: float) -> float:
    r1, d1, r2, d2 = map(math.radians, (ra1, dec1, ra2, dec2))
    cos_sep = math.sin(d1) * math.sin(d2) + math.cos(d1) * math.cos(d2) * math.cos(r1 - r2)
    return math.degrees(math.acos(max(-1.0, min(1.0, cos_sep)))) * 3600.0


# (fits_path, request) → result; raises on failure. Injected so tests don't need astap.
SolveFn = Callable[[SolveRequest, str], Awaitable[SolveResult]]
EnrichFn = Callable[[SolveRequest, str], Awaitable[SolveRequest]]


class Centerer:
    def __init__(self, app: Any, bus: Any, solve: SolveFn, enrich: EnrichFn) -> None:
        self._app = app
        self._bus = bus
        self._solve = solve
        self._enrich = enrich

    async def run(self, req: CenterRequest, run_id: str | None = None) -> CenterResult:
        run_id = run_id or uuid.uuid4().hex[:12]
        mm = getattr(self._app.state, "mount_manager", None)
        im = getattr(self._app.state, "imager_manager", None)
        if mm is None or im is None:
            raise RuntimeError("Centering needs the mount and imager managers")

        await self._bus.publish(
            PlatesolveCenterStarted(
                run_id=run_id,
                ra=req.ra,
                dec=req.dec,
                tolerance_arcsec=req.tolerance_arcsec,
            )
        )
        logger.info(
            "platesolve.center_started",
            run_id=run_id,
            ra=req.ra,
            dec=req.dec,
            tolerance_arcsec=req.tolerance_arcsec,
        )
        if req.slew_first:
            await self._slew(mm, req)

        attempts: list[CenterAttempt] = []
        result: CenterResult | None = None
        for n in range(1, req.max_attempts + 1):
            attempt = await self._attempt(n, im, req)
            attempts.append(attempt)
            await self._bus.publish(PlatesolveCenterAttempt(run_id=run_id, **attempt.model_dump()))
            logger.info("platesolve.center_attempt", run_id=run_id, **attempt.model_dump())
            if attempt.error_arcsec is not None and attempt.error_arcsec <= req.tolerance_arcsec:
                result = CenterResult(
                    success=True, attempts=attempts, final_error_arcsec=attempt.error_arcsec
                )
                break
            if n == req.max_attempts:
                break
            if attempt.solved_ra is not None and attempt.solved_dec is not None:
                await self._sync(mm, req, attempt.solved_ra, attempt.solved_dec)
                await self._slew(mm, req)

        if result is None:
            solved = [a for a in attempts if a.error_arcsec is not None]
            if not solved:
                last = attempts[-1].solve_error if attempts else None
                result = CenterResult(
                    success=False,
                    failure="no_solution",
                    attempts=attempts,
                    message=f"No plate solution in {len(attempts)} attempt(s)"
                    + (f": {last}" if last else ""),
                )
            else:
                final = solved[-1].error_arcsec
                result = CenterResult(
                    success=False,
                    failure="not_converged",
                    attempts=attempts,
                    final_error_arcsec=final,
                    message=(
                        f"Still {final:.0f}″ off after {len(attempts)} attempts "
                        f"(tolerance {req.tolerance_arcsec:.0f}″)"
                    ),
                )

        await self._bus.publish(
            PlatesolveCenterFinished(
                run_id=run_id,
                success=result.success,
                failure=result.failure,
                final_error_arcsec=result.final_error_arcsec,
                message=result.message,
            )
        )
        logger.info(
            "platesolve.center_finished",
            run_id=run_id,
            success=result.success,
            failure=result.failure,
            final_error_arcsec=result.final_error_arcsec,
        )
        return result

    async def _attempt(self, n: int, im: Any, req: CenterRequest) -> CenterAttempt:
        from astrolol.imaging.models import ExposureRequest

        t0 = time.monotonic()
        exposure = await im.expose(
            req.camera_id,
            ExposureRequest(
                duration=req.exposure_s,
                binning=req.binning,
                gain=req.gain,
                save=False,
            ),
        )
        solve_req = SolveRequest(
            fits_path=str(exposure.fits_path), ra_hint=req.ra, dec_hint=req.dec
        )
        solve_req = await self._enrich(solve_req, req.camera_id)
        try:
            solved = await self._solve(solve_req, f"center-{n}")
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            return CenterAttempt(
                attempt=n, solve_error=str(exc), duration_s=round(time.monotonic() - t0, 2)
            )
        err = separation_arcsec(solved.ra, solved.dec, req.ra, req.dec)
        return CenterAttempt(
            attempt=n,
            solved_ra=solved.ra,
            solved_dec=solved.dec,
            error_arcsec=round(err, 1),
            duration_s=round(time.monotonic() - t0, 2),
        )

    async def _sync(self, mm: Any, req: CenterRequest, ra: float, dec: float) -> None:
        import astropy.units as u
        from astropy.coordinates import SkyCoord

        await mm.sync(req.mount_id, SkyCoord(ra=ra * u.deg, dec=dec * u.deg, frame="icrs"))

    async def _slew(self, mm: Any, req: CenterRequest) -> None:
        import astropy.units as u
        from astropy.coordinates import SkyCoord

        coord = SkyCoord(ra=req.ra * u.deg, dec=req.dec * u.deg, frame="icrs")
        await mm.set_target(req.mount_id, coord, name=req.name, source="platesolve")
        q = self._bus.subscribe()
        try:
            await mm.slew(req.mount_id)
            async with asyncio.timeout(SLEW_TIMEOUT_S):
                while True:
                    event: BaseEvent = await q.get()
                    if getattr(event, "device_id", None) != req.mount_id:
                        continue
                    etype = getattr(event, "type", "")
                    if etype == "mount.slew_completed":
                        return
                    if etype in ("mount.slew_aborted", "mount.operation_failed"):
                        raise RuntimeError(
                            f"Slew failed: {getattr(event, 'reason', None) or etype}"
                        )
        except TimeoutError:
            raise RuntimeError(f"Slew timed out after {SLEW_TIMEOUT_S:.0f} s") from None
        finally:
            self._bus.unsubscribe(q)
