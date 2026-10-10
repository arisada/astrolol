"""Finds the guider's hardware among the devices astrolol has connected."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from astrolol.core.guiding.errors import GuiderNotConnected
from astrolol.devices.base.interfaces import IPulseGuider, IStreamingCamera
from astrolol.devices.base.pulse import PulseGuideNotSupported
from astrolol.imaging.streaming import LoopingExposureStream
from astrolol.plugins.guider.settings import GuiderSettings, pick_pulse_guider


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
        camera = self._raw_camera()
        if isinstance(camera, IStreamingCamera) and getattr(camera, "can_stream", True):
            return camera
        # No native stream: expose back-to-back exposures as one (one wrapper per camera,
        # so its subscriptions survive between calls).
        return self._wrapped.setdefault(id(camera), LoopingExposureStream(camera))  # type: ignore[arg-type]

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
