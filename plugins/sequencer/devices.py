"""Resolve which devices a lane uses, from the active profile's optical paths."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import structlog

from astrolol.core.sequencer.models import Lane
from astrolol.equipment.optical_path import (
    OpticalPath,
    find_optical_path_for_camera_device,
    resolve_optical_paths,
)

logger = structlog.get_logger()


@dataclass
class LaneDevices:
    camera_id: str | None
    filter_wheel_id: str | None
    focuser_id: str | None
    mount_id: str | None
    from_profile: bool  # False = no optical path for this camera, fell back to guesses


def _connected(app: Any, kind: str) -> list[str]:
    dm = getattr(app.state, "device_manager", None)
    if dm is None:
        return []
    return [d["device_id"] for d in dm.list_connected() if d["kind"] == kind]


def _optical_paths(app: Any) -> list[OpticalPath]:
    profile = getattr(app.state, "active_profile", None)
    equipment_store = getattr(app.state, "equipment_store", None)
    dm = getattr(app.state, "device_manager", None)
    if profile is None or equipment_store is None or dm is None or not profile.roots:
        return []
    try:
        return resolve_optical_paths(profile, equipment_store, dm)
    except Exception as exc:
        logger.warning("sequencer.optical_paths_failed", error=str(exc))
        return []


def main_camera_id(app: Any) -> str | None:
    """The profile's main camera: the first optical path with a connected camera,
    else the first connected camera."""
    for path in _optical_paths(app):
        if path.camera_device_id is not None:
            return path.camera_device_id
    cameras = _connected(app, "camera")
    return cameras[0] if cameras else None


def run_mount_id(app: Any) -> str | None:
    """The mount a run uses: the main camera's mount, else the only connected mount."""
    camera_id = main_camera_id(app)
    if camera_id is not None:
        path = find_optical_path_for_camera_device(_optical_paths(app), camera_id)
        if path is not None:
            return path.mount_device_id
    mounts = _connected(app, "mount")
    return mounts[0] if len(mounts) == 1 else None


def resolve_lane_devices(app: Any, lane: Lane) -> LaneDevices:
    """Devices for *lane*. With an optical path for the camera, everything comes from the
    equipment tree. Without one (no profile tree), a device kind is only guessed when
    exactly one of that kind is connected."""
    camera_id = lane.camera_id or main_camera_id(app)
    if camera_id not in _connected(app, "camera"):
        camera_id = None

    path = (
        find_optical_path_for_camera_device(_optical_paths(app), camera_id) if camera_id else None
    )
    if path is not None:
        return LaneDevices(
            camera_id=camera_id,
            filter_wheel_id=path.filter_wheel_device_id,
            focuser_id=path.focuser_device_id,
            mount_id=path.mount_device_id,
            from_profile=True,
        )

    def _only(kind: str) -> str | None:
        ids = _connected(app, kind)
        return ids[0] if len(ids) == 1 else None

    return LaneDevices(
        camera_id=camera_id,
        filter_wheel_id=_only("filter_wheel"),
        focuser_id=_only("focuser"),
        mount_id=_only("mount"),
        from_profile=False,
    )
