"""FastAPI router for the plate-solving plugin."""
from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

import structlog
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from astrolol.core.events.models import LogEvent
from astrolol.plugins.platesolve.centering import CenterRequest, CenterRun
from astrolol.plugins.platesolve.enrich import compute_fov, enrich_request
from astrolol.plugins.platesolve.models import SolveJob, SolveRequest
from astrolol.plugins.platesolve.settings import PlatesolveSettings
from astrolol.plugins.platesolve.solver import SolveManager

logger = structlog.get_logger()

_D05_URL = (
    "https://master.dl.sourceforge.net/project/astap-program"
    "/star_databases/d05_star_database.deb"
)

router = APIRouter(prefix="/plugins/platesolve", tags=["platesolve"])


def _manager(request: Request) -> SolveManager:
    return request.app.state.solve_manager  # type: ignore[no-any-return]


async def _compute_fov(fits_path: str, request: Request) -> float | None:
    return await compute_fov(fits_path, request.app)


async def _enrich_request(req: SolveRequest, request: Request) -> SolveRequest:
    return await enrich_request(req, request.app)


_PLUGIN_KEY = "platesolve"


@router.get("/settings", response_model=PlatesolveSettings)
async def get_settings(request: Request) -> PlatesolveSettings:
    """Return persisted plate-solve settings (defaults if not yet saved)."""
    raw = request.app.state.profile_store.get_user_settings().plugin_settings.get(_PLUGIN_KEY, {})
    return PlatesolveSettings(**raw)


@router.put("/settings", response_model=PlatesolveSettings)
async def put_settings(body: PlatesolveSettings, request: Request) -> PlatesolveSettings:
    """Persist plate-solve settings."""
    store = request.app.state.profile_store
    current = store.get_user_settings()
    updated = {**current.plugin_settings, _PLUGIN_KEY: body.model_dump()}
    store.update_user_settings(current.model_copy(update={"plugin_settings": updated}))
    return body


class ExposeAndSolveRequest(BaseModel):
    device_id: str
    duration: float = Field(gt=0, description="Exposure duration in seconds")
    binning: int = Field(default=1, ge=1, le=4)
    gain: int | None = None


@router.post("/expose_and_solve", status_code=201, response_model=SolveJob)
async def expose_and_solve(body: ExposeAndSolveRequest, request: Request) -> SolveJob:
    """Expose with the camera then immediately plate-solve the result.
    Both phases run server-side; cancel the returned job to halt either phase."""
    stub = SolveRequest(fits_path="(pending)")
    enriched = await _enrich_request(stub, request)
    return await _manager(request).expose_and_solve(
        device_id=body.device_id,
        imager_manager=request.app.state.imager_manager,
        duration=body.duration,
        binning=body.binning,
        gain=body.gain,
        ra_hint=enriched.ra_hint,
        dec_hint=enriched.dec_hint,
        radius=enriched.radius,
        tolerance=enriched.tolerance,
        fov=None,  # FOV not available until after exposure; astap auto-detects
    )


@router.post("/solve", status_code=201, response_model=SolveJob)
async def start_solve(req: SolveRequest, request: Request) -> SolveJob:
    """Submit a new plate-solve job. Returns immediately with the job id."""
    req = await _enrich_request(req, request)
    return await _manager(request).submit(req)


@router.get("/jobs", response_model=list[SolveJob])
async def list_jobs(request: Request) -> list[SolveJob]:
    """Return all known jobs, most recent first (up to 100)."""
    return _manager(request).list_jobs()


@router.get("/{job_id}/status", response_model=SolveJob)
async def get_job_status(job_id: str, request: Request) -> SolveJob:
    """Poll the status of a specific solve job."""
    job = _manager(request).get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Solve job not found")
    return job


@router.delete("/{job_id}/cancel", status_code=204)
async def cancel_job(job_id: str, request: Request) -> None:
    """Cancel a running solve. No-op if already in a terminal state."""
    try:
        await _manager(request).cancel(job_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Solve job not found")


# ── Centering ─────────────────────────────────────────────────────────────────

@router.post("/center", status_code=202, response_model=CenterRun)
async def start_center(body: CenterRequest, request: Request) -> CenterRun:
    """Start a slew → solve → sync → re-slew centering run. Progress is published as
    platesolve.center_* events; poll GET /center for the result. 409 if one is running."""
    try:
        return await _manager(request).start_center(body)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/center", response_model=CenterRun)
async def get_center(request: Request) -> CenterRun:
    """The current or most recent centering run."""
    run = _manager(request).center_run()
    if run is None:
        raise HTTPException(status_code=404, detail="No centering run yet")
    return run


@router.delete("/center", status_code=204)
async def cancel_center(request: Request) -> None:
    await _manager(request).cancel_center()


class DbStatus(BaseModel):
    installed: bool
    db_path: str


@router.get("/db_status", response_model=DbStatus)
async def db_status(request: Request) -> DbStatus:
    """Return whether the ASTAP star database is present at the configured path."""
    db_path = Path(_manager(request)._astap_db_path)
    installed = db_path.is_dir() and any(db_path.iterdir())
    return DbStatus(installed=installed, db_path=str(db_path))


@router.post("/install_db", status_code=202)
async def install_db(request: Request) -> dict:
    """Download and install the ASTAP d05 star database in the background.
    Progress is published as platesolve log events on the WebSocket stream."""
    event_bus = request.app.state.event_bus
    asyncio.create_task(_do_install_db(event_bus), name="platesolve_install_db")
    return {"status": "started"}


async def _do_install_db(event_bus) -> None:  # type: ignore[type-arg]
    async def log(msg: str, level: str = "info") -> None:
        await event_bus.publish(LogEvent(level=level, component="platesolve", message=msg))

    with tempfile.TemporaryDirectory() as tmpdir:
        deb_path = Path(tmpdir) / "d05_star_database.deb"

        await log(f"Downloading d05 star database from SourceForge…")
        try:
            dl = await asyncio.create_subprocess_exec(
                "curl", "-L", "--progress-bar", "-o", str(deb_path), _D05_URL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
        except FileNotFoundError:
            await log("curl not found — cannot download star database", level="error")
            return

        while True:
            chunk = await dl.stdout.read(4096)  # type: ignore[union-attr]
            if not chunk:
                break
            for part in chunk.decode("utf-8", errors="replace").replace("\r", "\n").splitlines():
                part = part.strip()
                if part:
                    await log(part)
        await dl.wait()

        if dl.returncode != 0:
            await log("Download failed (curl exited non-zero)", level="error")
            return

        await log(f"Download complete. Installing with sudo dpkg -i …")
        try:
            inst = await asyncio.create_subprocess_exec(
                "sudo", "-n", "dpkg", "-i", str(deb_path),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
        except FileNotFoundError:
            await log("sudo/dpkg not found — cannot install star database", level="error")
            return

        while True:
            chunk = await inst.stdout.read(4096)  # type: ignore[union-attr]
            if not chunk:
                break
            for part in chunk.decode("utf-8", errors="replace").splitlines():
                part = part.strip()
                if part:
                    await log(part)
        await inst.wait()

        if inst.returncode == 0:
            await log("d05 star database installed successfully!")
        else:
            await log("Installation failed — check server logs for details", level="error")
