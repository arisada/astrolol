"""Finds the guider's hardware among the devices astrolol has connected."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import structlog

from astrolol.core.guiding.errors import GuiderNotConnected
from astrolol.devices.base.interfaces import IPulseGuider, IStreamingCamera
from astrolol.devices.base.pulse import PulseGuideNotSupported
from astrolol.imaging.streaming import LoopingExposureStream, streaming_camera
from astrolol.plugins.guider.settings import GuiderSettings, pick_pulse_guider

logger = structlog.get_logger()


@dataclass(frozen=True)
class MountState:
    """What the guider needs to know about the mount: where it points and whether it moves."""

    dec: float | None = None  # degrees
    pier_side: str | None = None  # "East" | "West"
    slewing: bool = False
    tracking: bool | None = None  # None: unknown
    parked: bool = False


class ManagerDevices:
    """``GuideDevices`` backed by the DeviceManager and the guider's current settings."""

    def __init__(self, device_manager: Any, settings: Callable[[], GuiderSettings]) -> None:
        self._manager = device_manager
        self._settings = settings
        self._wrapped: dict[int, LoopingExposureStream] = {}

    def _raw_camera(self) -> object:
        camera_id = self._settings().camera_id
        if not camera_id:
            raise GuiderNotConnected("Choose the guide camera in the guider settings")
        try:
            return self._manager.get_camera(camera_id)  # type: ignore[no-any-return]
        except Exception as exc:
            raise GuiderNotConnected(f"The guide camera '{camera_id}' is not connected") from exc

    def _mount(self) -> object | None:
        mount_id = self._settings().mount_id
        if not mount_id:
            return None
        try:
            return self._manager.get_mount(mount_id)  # type: ignore[no-any-return]
        except Exception as exc:
            raise GuiderNotConnected(f"The mount '{mount_id}' is not connected") from exc

    def camera(self) -> IStreamingCamera:
        return streaming_camera(self._raw_camera(), self._wrapped)

    def pulse_guider(self) -> IPulseGuider:
        output = self._settings().guide_output
        camera = self._raw_camera()
        mount = self._mount() if output == "mount" else None
        if output == "mount" and mount is None:
            raise GuiderNotConnected("Choose the mount in the guider settings to guide through it")
        try:
            return pick_pulse_guider(output, camera, mount)
        except PulseGuideNotSupported as exc:
            raise GuiderNotConnected(str(exc)) from exc

    async def mount_state(self) -> MountState | None:
        """The mount chosen in the settings, else the only one connected; None if neither.

        Guiding through the camera's ST4 output works without it, but knowing the mount's
        declination and pier side keeps a calibration valid across slews and flips.
        """
        try:
            mount = self._mount()
            if mount is None:
                mounts = [d for d in self._manager.list_connected() if d.get("kind") == "mount"]
                if len(mounts) != 1:
                    return None
                mount = self._manager.get_mount(mounts[0]["device_id"])
            status = await mount.get_status()  # type: ignore[attr-defined]
        except Exception as exc:
            logger.debug("guider.mount_state_failed", error=str(exc))
            return None
        return MountState(
            dec=status.dec_jnow if status.dec_jnow is not None else status.dec,
            pier_side=status.pier_side if status.pier_side in ("East", "West") else None,
            slewing=bool(status.is_slewing),
            tracking=bool(status.is_tracking),
            parked=bool(status.is_parked),
        )
