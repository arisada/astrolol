"""FastAPI router for the plate-solving plugin."""
from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

import structlog
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from astrolol.core.events.models import LogEvent
from plugins.platesolve.models import SolveJob, SolveRequest
from plugins.platesolve.solver import SolveManager

logger = structlog.get_logger()

_D05_URL = (
    "https://master.dl.sourceforge.net/project/astap-program"
    "/star_databases/d05_star_database.deb"
)

router = APIRouter(prefix="/platesolve", tags=["platesolve"])


def _manager(request: Request) -> SolveManager:
    return request.app.state.solve_manager  # type: ignore[no-any-return]


async def _enrich_request(req: SolveRequest, request: Request) -> SolveRequest:
    """Fill in ra_hint/dec_hint from the connected mount and radius from settings."""
    app = request.app

    # Radius from user settings (if caller didn't override)
    if req.radius == 30.0:  # default — check settings
        try:
            settings = app.state.profile_store.get_user_settings()
            req = req.model_copy(update={"radius": settings.astap_search_radius})
        except Exception:
            pass

    # RA/Dec from mount current position
    if req.ra_hint is None or req.dec_hint is None:
        try:
            device_manager = app.state.device_manager
            mounts = [d for d in device_manager.list_connected() if d["kind"] == "mount"]
            if mounts:
                mount = device_manager.get_mount(mounts[0]["device_id"])
                status = await mount.get_status()
                updates: dict = {}
                if req.ra_hint is None and status.ra is not None:
                    updates["ra_hint"] = status.ra * 15.0   # hours → degrees
                if req.dec_hint is None and status.dec is not None:
                    updates["dec_hint"] = status.dec
                if updates:
                    req = req.model_copy(update=updates)
                    logger.info("platesolve.hints_from_mount", **updates)
        except Exception as exc:
            logger.warning("platesolve.hints_unavailable", reason=str(exc))

    return req


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
            line = await dl.stdout.readline()  # type: ignore[union-attr]
            if not line:
                break
            text = line.decode("utf-8", errors="replace").rstrip()
            if text:
                await log(text)
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
            line = await inst.stdout.readline()  # type: ignore[union-attr]
            if not line:
                break
            text = line.decode("utf-8", errors="replace").rstrip()
            if text:
                await log(text)
        await inst.wait()

        if inst.returncode == 0:
            await log("d05 star database installed successfully!")
        else:
            await log("Installation failed — check server logs for details", level="error")
