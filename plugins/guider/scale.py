"""Pixel scale (arcsec per guide pixel) from the optics, when the equipment tree knows them."""

from __future__ import annotations

from typing import Any

import structlog

from astrolol.equipment.optical_path import find_optical_path_for_camera_device, resolve_optical_paths

logger = structlog.get_logger()

ARCSEC_PER_RADIAN_PER_MICRON_PER_MM = 206.265  # 206265 arcsec per radian, µm over mm


def arcsec_per_pixel(focal_length_mm: float, pixel_size_um: float, binning: int = 1) -> float:
    return ARCSEC_PER_RADIAN_PER_MICRON_PER_MM * pixel_size_um * binning / focal_length_mm


async def derive_pixel_scale(app: Any, camera_id: str | None, binning: int = 1) -> float | None:
    """From the focal length of the telescope above the camera in the active profile and the
    camera's pixel size (the equipment item's, else what the driver reports); None if either
    is unknown."""
    if not camera_id:
        return None
    profile = getattr(app.state, "active_profile", None)
    store = getattr(app.state, "equipment_store", None)
    manager = getattr(app.state, "device_manager", None)
    if profile is None or store is None or manager is None or not profile.roots:
        return None
    try:
        path = find_optical_path_for_camera_device(resolve_optical_paths(profile, store, manager), camera_id)
        if path is None or path.ota is None or not path.ota.focal_length:
            return None
        pixel_um = path.camera.pixel_size_um
        if not pixel_um:
            report = getattr(manager.get_camera(camera_id), "get_pixel_size_um", None)
            pixel_um = await report() if report is not None else None
        if not pixel_um:
            return None
        return arcsec_per_pixel(path.ota.focal_length, pixel_um, binning)
    except Exception as exc:
        logger.warning("guider.pixel_scale_failed", error=str(exc))
        return None
