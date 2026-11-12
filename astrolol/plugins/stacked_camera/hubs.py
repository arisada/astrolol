"""The hubs of the cameras in use, and the link from a virtual camera to its real one."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import structlog

from astrolol.plugins.stacked_camera.hub import SourceHub, SubParams
from astrolol.plugins.stacked_camera.probe import CameraCards, probe_camera

logger = structlog.get_logger()


class SourceNotConnected(Exception):
    """The real camera a virtual camera is built on is not available."""


class HubRegistry:
    """One ``SourceHub`` per real camera, found by the device id of that camera.

    The hub follows the camera *instance*: the device manager builds a new one whenever the camera
    is connected again, and a hub still holding the old one would stream from nothing.
    """

    def __init__(
        self,
        device_manager: Any,
        event_bus: Any,
        sub_exposure: Callable[[], float],
        virtual_adapter_keys: frozenset[str] = frozenset(),
    ) -> None:
        self._manager = device_manager
        self.event_bus = event_bus
        self.sub_exposure = sub_exposure
        self._virtual_keys = virtual_adapter_keys
        self._hubs: dict[str, tuple[object, SourceHub]] = {}
        self._cards: dict[str, tuple[object, CameraCards | None]] = {}

    def camera(self, source_id: str) -> Any:
        """The connected real camera *source_id*; ``SourceNotConnected`` if there is none."""
        if not source_id:
            raise SourceNotConnected("Choose the camera to build this one on")
        try:
            camera = self._manager.get_camera(source_id)
            config = self._manager.get_config(source_id)
        except Exception as exc:
            raise SourceNotConnected(f"The camera '{source_id}' is not connected") from exc
        if config.adapter_key in self._virtual_keys:
            raise SourceNotConnected(f"'{source_id}' is itself a stacked camera: choose a real one")
        return camera

    async def hub(self, source_id: str) -> SourceHub:
        camera = self.camera(source_id)
        held = self._hubs.get(source_id)
        if held is not None and held[0] is camera:
            return held[1]
        if held is not None:
            logger.info("stacked_camera.source_replaced", source_id=source_id)
            await held[1].shutdown()
        hub = SourceHub(camera, SubParams(exposure=self.sub_exposure()))
        self._hubs[source_id] = (camera, hub)
        return hub

    async def probe(self, source_id: str) -> None:
        """Learn the camera's cards once per camera instance, while its stream is idle.

        Does nothing when already known, or when a stream is running (the camera cannot expose
        then); a later call tries again.
        """
        camera = self.camera(source_id)
        held = self._cards.get(source_id)
        if held is not None and held[0] is camera:
            return
        hub = self.existing(source_id)
        if hub is not None and (hub.running or hub.leases):
            return
        self._cards[source_id] = (camera, await probe_camera(camera))

    def cards(self, source_id: str) -> CameraCards | None:
        held = self._cards.get(source_id)
        return None if held is None else held[1]

    def real_cameras(self) -> list[str]:
        """Device ids of the connected cameras a virtual camera can be built on."""
        return [
            str(entry["device_id"])
            for entry in self._manager.list_connected()
            if entry.get("kind") == "camera" and entry.get("adapter_key") not in self._virtual_keys
        ]

    def attached(self) -> dict[str, dict[str, str]]:
        """For each real camera with virtual ones on it: {adapter key: device id of the virtual}."""
        found: dict[str, dict[str, str]] = {}
        for entry in self._manager.list_connected():
            key = entry.get("adapter_key")
            if key not in self._virtual_keys:
                continue
            device_id = str(entry["device_id"])
            source_id = str(self._manager.get_config(device_id).params.get("source_id", ""))
            found.setdefault(source_id, {})[str(key)] = device_id
        return found

    def device_id_of(self, adapter: object) -> str | None:
        """The device id the manager knows *adapter* by."""
        try:
            for entry in self._manager.list_connected():
                device_id = str(entry["device_id"])
                if entry.get("kind") == "camera" and self._manager.get_camera(device_id) is adapter:
                    return device_id
        except Exception:
            return None
        return None

    def existing(self, source_id: str) -> SourceHub | None:
        held = self._hubs.get(source_id)
        return None if held is None else held[1]

    def hubs(self) -> dict[str, SourceHub]:
        return {source_id: hub for source_id, (_, hub) in self._hubs.items()}

    async def shutdown(self) -> None:
        held, self._hubs = list(self._hubs.values()), {}
        for _, hub in held:
            await hub.shutdown()
