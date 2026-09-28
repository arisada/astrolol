"""Solve-request enrichment: search hints, radius/tolerance from settings, and the field of
view from the equipment tree. Shared by the REST routes and centering."""

from __future__ import annotations

import asyncio
import math
from pathlib import Path
from typing import Any

import astropy.io.fits as astropy_fits
import structlog

from astrolol.equipment.optical_path import (
    find_optical_path_for_camera_device,
    resolve_optical_paths,
)
from plugins.platesolve.models import SolveRequest
from plugins.platesolve.settings import PlatesolveSettings

logger = structlog.get_logger()


async def compute_fov(fits_path: str, app: Any, camera_id: str | None = None) -> float | None:
    """Compute field width (degrees) from FITS header + CCD_INFO + the active profile's
    equipment tree.

    Uses *camera_id*, or the first connected camera (same choice as the pixel-size lookup
    below, so both numbers come from the same optical path), and resolves its ancestor
    OTA's focal length
    from the equipment tree — there is no profile-level "the" telescope any more, since a
    profile can have more than one optical path.
    """
    try:
        profile = app.state.active_profile
        equipment_store = getattr(app.state, "equipment_store", None)
        if profile is None or equipment_store is None or not profile.roots:
            return None

        device_manager = app.state.device_manager
        if camera_id is not None:
            camera_device_id = camera_id
        else:
            cameras = [d for d in device_manager.list_connected() if d["kind"] == "camera"]
            if not cameras:
                return None
            camera_device_id = cameras[0]["device_id"]

        paths = resolve_optical_paths(profile, equipment_store, device_manager)
        path = find_optical_path_for_camera_device(paths, camera_device_id)
        if path is None or path.ota is None:
            return None
        focal_length_mm: float = path.ota.focal_length
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
        cam = device_manager.get_camera(camera_device_id)
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


async def enrich_request(req: SolveRequest, app: Any, camera_id: str | None = None) -> SolveRequest:
    """Fill in ra_hint/dec_hint from the connected mount and radius from settings."""

    # Radius and tolerance from plugin settings (if caller didn't override)
    try:
        raw = app.state.profile_store.get_user_settings().plugin_settings.get("platesolve", {})
        ps = PlatesolveSettings(**raw)
        updates: dict[str, float] = {}
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
        fov = await compute_fov(req.fits_path, app, camera_id)
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
                hints: dict[str, float] = {}
                if req.ra_hint is None and status.ra is not None:
                    hints["ra_hint"] = status.ra * 15.0  # hours → degrees
                if req.dec_hint is None and status.dec is not None:
                    hints["dec_hint"] = status.dec
                if hints:
                    req = req.model_copy(update=hints)
                    logger.info("platesolve.hints_from_mount", **hints)
        except Exception as exc:
            logger.warning("platesolve.hints_unavailable", reason=str(exc))

    return req
