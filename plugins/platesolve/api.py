"""FastAPI router for the plate-solving plugin."""
from __future__ import annotations

import asyncio
import math
import tempfile
from pathlib import Path

import astropy.io.fits as astropy_fits
import structlog
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from astrolol.core.events.models import LogEvent
from plugins.platesolve.models import SolveJob, SolveRequest
from plugins.platesolve.settings import PlatesolveSettings
from plugins.platesolve.solver import SolveManager

logger = structlog.get_logger()

_D05_URL = (
    "https://master.dl.sourceforge.net/project/astap-program"
    "/star_databases/d05_star_database.deb"
)

router = APIRouter(prefix="/plugins/platesolve", tags=["platesolve"])


def _manager(request: Request) -> SolveManager:
    return request.app.state.solve_manager  # type: ignore[no-any-return]


async def _compute_fov(fits_path: str, request: Request) -> float | None:
    """Compute field width (degrees) from FITS header + CCD_INFO + active profile."""
    app = request.app
    try:
        profile = app.state.active_profile
        if profile is None or not getattr(profile, "telescope", None):
            return None
        focal_length_mm: float = profile.telescope.focal_length
        if not focal_length_mm:
            return None

        # NAXIS1 and XBINNING from the FITS header
        def _read_header() -> tuple[int, int]:
            with astropy_fits.open(fits_path) as hdul:
                hdr = hdul[0].header
                return int(hdr["NAXIS2"]), int(hdr.get("YBINNING", hdr.get("XBINNING", 1)))

        naxis2, ybinning = await asyncio.to_thread(_read_header)

        # Pixel size: try CCD_INFO first, fall back to user settings
        pixel_size_um: float | None = None
        device_manager = app.state.device_manager
        cameras = [d for d in device_manager.list_connected() if d["kind"] == "camera"]
        if cameras:
            cam = device_manager.get_camera(cameras[0]["device_id"])
            if hasattr(cam, "get_pixel_size_um"):
                pixel_size_um = await cam.get_pixel_size_um()

        if pixel_size_um is None:
            raw = app.state.profile_store.get_user_settings().plugin_settings.get("platesolve", {})
            pixel_size_um = PlatesolveSettings(**raw).pixel_size_um

        if not pixel_size_um:
            return None

        sensor_height_mm = pixel_size_um * ybinning * naxis2 / 1000.0
        fov_deg = math.degrees(2 * math.atan(sensor_height_mm / (2 * focal_length_mm)))
        logger.info(
            "platesolve.fov_computed",
            pixel_size_um=pixel_size_um,
            ybinning=ybinning,
            naxis2=naxis2,
            focal_length_mm=focal_length_mm,
            sensor_height_mm=round(sensor_height_mm, 4),
            fov_deg=round(fov_deg, 4),
        )
        return fov_deg
    except Exception as exc:
        logger.warning("platesolve.fov_unavailable", reason=str(exc))
        return None


async def _enrich_request(req: SolveRequest, request: Request) -> SolveRequest:
    """Fill in ra_hint/dec_hint from the connected mount and radius from settings."""
    app = request.app

    # Radius and tolerance from plugin settings (if caller didn't override)
    try:
        raw = app.state.profile_store.get_user_settings().plugin_settings.get("platesolve", {})
        ps = PlatesolveSettings(**raw)
        updates: dict = {}
        if req.radius == 30.0:
            updates["radius"] = ps.astap_search_radius
        if req.tolerance is None:
            updates["tolerance"] = ps.astap_tolerance
        if updates:
            req = req.model_copy(update=updates)
    except Exception:
        pass

    # FOV from FITS header + CCD_INFO + active profile (skip if file doesn't exist yet)
    if req.fov is None and Path(req.fits_path).is_file():
        fov = await _compute_fov(req.fits_path, request)
        if fov is not None:
            req = req.model_copy(update={"fov": fov})

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
