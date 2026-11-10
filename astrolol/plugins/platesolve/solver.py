"""Plate-solving manager — one asyncio.Task per job, the actual solving done by a Solver backend."""
from __future__ import annotations

import asyncio
import contextlib
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

import structlog

from astrolol.core.events import EventBus
from astrolol.core.mem_guard import mem_guard
from astrolol.plugins.platesolve.events import (
    PlatesolveCancelled,
    PlatesolveCompleted,
    PlatesolveFailed,
    PlatesolveStarted,
)
from astrolol.core.events.models import LogEvent
from astrolol.plugins.platesolve.backends import AstapSolver, Solver, parse_wcs
from astrolol.plugins.platesolve.centering import CenterRequest, CenterResult, CenterRun, Centerer
from astrolol.plugins.platesolve.enrich import enrich_request
from astrolol.plugins.platesolve.models import SolveJob, SolveRequest, SolveResult

logger = structlog.get_logger()

_MAX_JOBS = 100


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Internal runtime job — not a Pydantic model (holds a live asyncio.Task)
# ---------------------------------------------------------------------------

@dataclass
class _Job:
    id: str
    request: SolveRequest
    status: str  # pending | solving | completed | failed | cancelled
    created_at: datetime
    result: SolveResult | None = None
    error: str | None = None
    completed_at: datetime | None = None
    task: asyncio.Task | None = field(default=None, repr=False)

    def to_model(self) -> SolveJob:
        return SolveJob(
            id=self.id,
            status=self.status,  # type: ignore[arg-type]
            request=self.request,
            result=self.result,
            error=self.error,
            created_at=self.created_at,
            completed_at=self.completed_at,
        )


_parse_wcs = parse_wcs  # historical name, used by tests


# ---------------------------------------------------------------------------
# SolveManager
# ---------------------------------------------------------------------------

class SolveManager:
    """Manages concurrent plate-solve jobs, each solved by the configured Solver backend."""

    def __init__(
        self,
        event_bus: EventBus,
        astap_bin: str = "astap_cli",
        astap_db_path: str = "/opt/astap",
        solver: Solver | None = None,
    ) -> None:
        self._event_bus = event_bus
        # Kept for the ASTAP database endpoints; the solver does the work.
        self._astap_bin = astap_bin
        self._astap_db_path = astap_db_path
        self._solver: Solver = solver or AstapSolver(astap_bin, astap_db_path)
        self._jobs: dict[str, _Job] = {}
        self._app: Any = None
        self._center_run: CenterRun | None = None
        self._center_task: asyncio.Task[None] | None = None

    def attach_app(self, app: Any) -> None:
        """Give the manager access to app.state (mount, imager, profile) for centering."""
        self._app = app

    # ------------------------------------------------------------------
    # Centering
    # ------------------------------------------------------------------

    def _centerer(self) -> Centerer:
        if self._app is None:
            raise RuntimeError("SolveManager.attach_app() was not called")
        app = self._app

        async def enrich(req: SolveRequest, camera_id: str) -> SolveRequest:
            return await enrich_request(req, app, camera_id)

        return Centerer(app, self._event_bus, solve=self._solve, enrich=enrich)

    async def center(self, **kwargs: Any) -> CenterResult:
        """Center a target (see CenterRequest for the arguments). Awaitable and cancellable;
        returns a CenterResult, raises on mount errors."""
        return await self._centerer().run(CenterRequest(**kwargs))

    async def start_center(self, req: CenterRequest) -> CenterRun:
        """Start a centering run in the background (REST). ValueError if one is running."""
        if self._center_task is not None and not self._center_task.done():
            raise ValueError("A centering run is already in progress")
        run = CenterRun(id=uuid4().hex[:12], status="running", request=req, started_at=_now())
        self._center_run = run

        async def _go() -> None:
            try:
                run.result = await self._centerer().run(req, run_id=run.id)
                run.status = "completed" if run.result.success else "failed"
                run.error = None if run.result.success else run.result.message
            except asyncio.CancelledError:
                run.status = "cancelled"
                raise
            except Exception as exc:
                run.status = "failed"
                run.error = str(exc)
                logger.warning("platesolve.center_error", run_id=run.id, error=str(exc))

        self._center_task = asyncio.create_task(_go(), name=f"platesolve_center_{run.id}")
        return run.model_copy()

    def center_run(self) -> CenterRun | None:
        return self._center_run.model_copy() if self._center_run is not None else None

    async def cancel_center(self) -> None:
        task = self._center_task
        if task is not None and not task.done():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        # A task cancelled before it first ran never reaches its own handler.
        if self._center_run is not None and self._center_run.status == "running":
            self._center_run.status = "cancelled"

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def solve(self, **kwargs: Any) -> SolveResult:
        """Solve a single FITS file and await the result directly (no polling).

        Takes the same keyword arguments as SolveRequest (fits_path, ra_hint, dec_hint,
        radius, tolerance, fov) and builds one internally -- like center() does for
        CenterRequest -- so a caller reaching this via app.state (another plugin; see
        plugin_api.py's "plugins must not import each other directly") never needs to
        import SolveRequest itself.

        For callers that need a solve inline in their own control flow rather than as a
        background job -- unlike submit()/expose_and_solve(), which only ever return a
        pollable SolveJob.
        """
        return await self._solve(SolveRequest(**kwargs), job_id=str(uuid4()))

    async def submit(self, request: SolveRequest) -> SolveJob:
        """Create and start a new solve job. Returns immediately."""
        job = _Job(
            id=str(uuid4()),
            request=request,
            status="pending",
            created_at=_now(),
        )
        self._jobs[job.id] = job
        job.task = asyncio.create_task(self._run(job), name=f"platesolve_{job.id[:8]}")
        return job.to_model()

    def get(self, job_id: str) -> SolveJob | None:
        job = self._jobs.get(job_id)
        return job.to_model() if job is not None else None

    def list_jobs(self) -> list[SolveJob]:
        return [j.to_model() for j in sorted(self._jobs.values(), key=lambda j: j.created_at, reverse=True)]

    async def cancel(self, job_id: str) -> bool:
        """Cancel a running job. Returns False if already in a terminal state.
        Raises KeyError if the job does not exist."""
        job = self._jobs.get(job_id)
        if job is None:
            raise KeyError(job_id)
        if job.status in ("completed", "failed", "cancelled"):
            return False
        if job.task is not None:
            job.task.cancel()
        return True

    async def expose_and_solve(
        self,
        device_id: str,
        imager_manager: Any,
        duration: float,
        binning: int = 1,
        gain: int | None = None,
        ra_hint: float | None = None,
        dec_hint: float | None = None,
        radius: float = 30.0,
        tolerance: float | None = None,
        fov: float | None = None,
    ) -> SolveJob:
        """Expose with a camera then plate-solve the result in a single server-side operation."""
        req = SolveRequest(
            fits_path="(pending exposure)",
            ra_hint=ra_hint,
            dec_hint=dec_hint,
            radius=radius,
            tolerance=tolerance,
            fov=fov,
        )
        job = _Job(
            id=str(uuid4()),
            request=req,
            status="exposing",
            created_at=_now(),
        )
        self._jobs[job.id] = job
        job.task = asyncio.create_task(
            self._run_expose_and_solve(job, device_id, imager_manager, duration, binning, gain),
            name=f"platesolve_eas_{job.id[:8]}",
        )
        return job.to_model()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _run_expose_and_solve(
        self,
        job: _Job,
        device_id: str,
        imager_manager: Any,
        duration: float,
        binning: int,
        gain: int | None,
    ) -> None:
        from astrolol.imaging.models import ExposureRequest as ImgExposureRequest

        t0 = time.monotonic()
        await self._event_bus.publish(
            PlatesolveStarted(solve_id=job.id, fits_path="(exposing)")
        )
        try:
            # ── Step 1: expose ────────────────────────────────────────────────
            exp_req = ImgExposureRequest(duration=duration, binning=binning, gain=gain, save=False)
            exposure_result = await imager_manager.expose(device_id, exp_req)
            job.request = job.request.model_copy(update={"fits_path": exposure_result.fits_path})

            # ── Step 2: solve ─────────────────────────────────────────────────
            job.status = "solving"
            result = await self._solve(job.request, job.id)
            duration_ms = int((time.monotonic() - t0) * 1000)
            result = result.model_copy(update={"duration_ms": duration_ms})
            job.status = "completed"
            job.result = result
            job.completed_at = _now()
            logger.info(
                "platesolve.completed",
                solve_id=job.id, ra=result.ra, dec=result.dec, duration_ms=duration_ms,
            )
            await self._event_bus.publish(PlatesolveCompleted(solve_id=job.id, **result.model_dump()))

        except asyncio.CancelledError:
            if job.status == "exposing":
                try:
                    await imager_manager.halt(device_id)
                except Exception:
                    pass
            job.status = "cancelled"
            job.completed_at = _now()
            logger.info("platesolve.cancelled", solve_id=job.id)
            await self._event_bus.publish(PlatesolveCancelled(solve_id=job.id))
            raise
        except Exception as exc:
            job.status = "failed"
            job.error = str(exc)
            job.completed_at = _now()
            logger.warning("platesolve.failed", solve_id=job.id, error=str(exc))
            await self._event_bus.publish(PlatesolveFailed(solve_id=job.id, reason=str(exc)))
        finally:
            self._prune()

    async def _run(self, job: _Job) -> None:
        job.status = "solving"
        t0 = time.monotonic()
        await self._event_bus.publish(
            PlatesolveStarted(solve_id=job.id, fits_path=job.request.fits_path)
        )
        try:
            result = await self._solve(job.request, job.id)
            duration_ms = int((time.monotonic() - t0) * 1000)
            result = result.model_copy(update={"duration_ms": duration_ms})
            job.status = "completed"
            job.result = result
            job.completed_at = _now()
            logger.info(
                "platesolve.completed",
                solve_id=job.id,
                ra=result.ra,
                dec=result.dec,
                duration_ms=duration_ms,
            )
            await self._event_bus.publish(
                PlatesolveCompleted(solve_id=job.id, **result.model_dump())
            )
        except asyncio.CancelledError:
            job.status = "cancelled"
            job.completed_at = _now()
            logger.info("platesolve.cancelled", solve_id=job.id)
            await self._event_bus.publish(PlatesolveCancelled(solve_id=job.id))
            raise
        except Exception as exc:
            job.status = "failed"
            job.error = str(exc)
            job.completed_at = _now()
            logger.warning("platesolve.failed", solve_id=job.id, error=str(exc))
            await self._event_bus.publish(
                PlatesolveFailed(solve_id=job.id, reason=str(exc))
            )
        finally:
            self._prune()

    async def _solve(self, req: SolveRequest, job_id: str) -> SolveResult:
        """Run the solver backend on the image, streaming its output to the log."""
        async def log(text: str) -> None:
            await self._event_bus.publish(
                LogEvent(level="info", component="platesolve", message=text)
            )

        async with mem_guard():
            return await self._solver.solve(req, job_id=job_id, log=log)

    def _prune(self) -> None:
        """Remove oldest terminal jobs when the store grows beyond _MAX_JOBS."""
        if len(self._jobs) <= _MAX_JOBS:
            return
        terminal = [
            j for j in self._jobs.values()
            if j.status in ("completed", "failed", "cancelled")
        ]
        terminal.sort(key=lambda j: j.completed_at or j.created_at)
        for job in terminal[: len(self._jobs) - _MAX_JOBS]:
            del self._jobs[job.id]
