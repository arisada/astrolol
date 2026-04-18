"""Plate-solving manager — runs astap_cli subprocesses, one asyncio.Task per job."""
from __future__ import annotations

import asyncio
import math
import shutil
import tempfile
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import structlog

from astrolol.core.events import (
    EventBus,
    PlatesolveCancelled,
    PlatesolveCompleted,
    PlatesolveFailed,
    PlatesolveStarted,
)
from astrolol.core.events.models import LogEvent
from plugins.platesolve.models import SolveJob, SolveRequest, SolveResult

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


# ---------------------------------------------------------------------------
# WCS parser (blocking — run via asyncio.to_thread)
# ---------------------------------------------------------------------------

def _parse_wcs(fits_path: str) -> SolveResult:
    """Read the WCS solution written by astap_cli -update from a FITS header."""
    import astropy.io.fits as afits

    with afits.open(fits_path) as hdul:
        h = hdul[0].header

        if "CRVAL1" not in h or "CRVAL2" not in h:
            raise RuntimeError("astap_cli returned success but WCS keywords are missing")

        ra = float(h["CRVAL1"])
        dec = float(h["CRVAL2"])

        if "CD1_1" in h:
            cd1_1 = float(h["CD1_1"])
            cd1_2 = float(h.get("CD1_2", 0))
            cd2_1 = float(h.get("CD2_1", 0))
            pixel_scale_deg = math.sqrt(cd1_1 ** 2 + cd2_1 ** 2)
            rotation = math.degrees(math.atan2(-cd1_2, cd1_1)) % 360
        else:
            pixel_scale_deg = abs(float(h.get("CDELT1", 0)))
            rotation = float(h.get("CROTA2", 0))

        pixel_scale = pixel_scale_deg * 3600  # arcsec/pixel
        naxis1 = int(h.get("NAXIS1", 0))
        naxis2 = int(h.get("NAXIS2", 0))
        field_w = naxis1 * pixel_scale_deg
        field_h = naxis2 * pixel_scale_deg

        return SolveResult(
            ra=round(ra, 6),
            dec=round(dec, 6),
            rotation=round(rotation, 2),
            pixel_scale=round(pixel_scale, 4),
            field_w=round(field_w, 4),
            field_h=round(field_h, 4),
        )


# ---------------------------------------------------------------------------
# SolveManager
# ---------------------------------------------------------------------------

class SolveManager:
    """Manages concurrent plate-solve jobs, each running astap_cli in a subprocess."""

    def __init__(
        self,
        event_bus: EventBus,
        astap_bin: str = "astap_cli",
        astap_db_path: str = "/opt/astap",
    ) -> None:
        self._event_bus = event_bus
        self._astap_bin = astap_bin
        self._astap_db_path = astap_db_path
        self._jobs: dict[str, _Job] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

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

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

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
        """Copy the FITS to a temp dir, run astap_cli, stream progress, parse WCS."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_fits = Path(tmpdir) / "solve.fits"
            await asyncio.to_thread(shutil.copy2, req.fits_path, str(tmp_fits))

            cmd = [
                self._astap_bin,
                "-f", str(tmp_fits),
                "-z", "0",        # auto-downsample for speed
                "-r", str(req.radius),
                "-d", self._astap_db_path,
                "-update",
            ]
            if req.ra_hint is not None:
                cmd += ["-ra", str(req.ra_hint / 15.0)]    # degrees → hours
            if req.dec_hint is not None:
                cmd += ["-spd", str(90.0 + req.dec_hint)]  # dec → south-pole distance
            if req.tolerance is not None:
                cmd += ["-t", str(req.tolerance)]
            if req.fov is not None:
                cmd += ["-fov", str(req.fov)]

            logger.info("platesolve.running", solve_id=job_id, cmd=" ".join(cmd))

            if not shutil.which(self._astap_bin):
                raise RuntimeError(
                    f"'{self._astap_bin}' not found — install the astap-cli package"
                )

            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            stderr_chunks: list[bytes] = []

            async def _drain_stderr() -> None:
                while True:
                    chunk = await proc.stderr.read(4096)  # type: ignore[union-attr]
                    if not chunk:
                        break
                    stderr_chunks.append(chunk)

            stderr_task = asyncio.create_task(_drain_stderr())
            try:
                while True:
                    line = await proc.stdout.readline()  # type: ignore[union-attr]
                    if not line:
                        break
                    text = line.decode("utf-8", errors="replace").rstrip()
                    if text:
                        await self._event_bus.publish(
                            LogEvent(level="info", component="platesolve", message=text)
                        )
                await stderr_task
                await proc.wait()
            except asyncio.CancelledError:
                try:
                    proc.kill()
                    await proc.wait()
                except Exception:
                    pass
                raise

            if proc.returncode != 0:
                stderr_text = b"".join(stderr_chunks).decode("utf-8", errors="replace").strip()
                detail = stderr_text or f"exit code {proc.returncode}"
                raise RuntimeError(f"Plate solve failed: {detail}")

            return await asyncio.to_thread(_parse_wcs, str(tmp_fits))

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
