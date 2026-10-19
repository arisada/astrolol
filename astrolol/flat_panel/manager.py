import structlog
from astrolol.core.events import EventBus, FlatPanelChanged
from astrolol.devices.base.models import FlatPanelStatus
from astrolol.devices.manager import DeviceManager

logger = structlog.get_logger()


class FlatPanelManager:
    def __init__(self, device_manager: DeviceManager, event_bus: EventBus) -> None:
        self._device_manager = device_manager
        self._event_bus = event_bus

    async def get_status(self, device_id: str) -> FlatPanelStatus:
        return await self._device_manager.get_flat_panel(device_id).get_status()

    async def open_cover(self, device_id: str) -> FlatPanelStatus:
        panel = self._device_manager.get_flat_panel(device_id)
        await panel.open_cover()
        return await self._changed(device_id, "cover_opened")

    async def close_cover(self, device_id: str) -> FlatPanelStatus:
        panel = self._device_manager.get_flat_panel(device_id)
        await panel.close_cover()
        return await self._changed(device_id, "cover_closed")

    async def set_light(self, device_id: str, on: bool, brightness: int | None = None) -> FlatPanelStatus:
        panel = self._device_manager.get_flat_panel(device_id)
        await panel.set_light(on, brightness)
        return await self._changed(device_id, "light_on" if on else "light_off")

    async def _changed(self, device_id: str, action: str) -> FlatPanelStatus:
        status = await self._device_manager.get_flat_panel(device_id).get_status()
        await self._event_bus.publish(FlatPanelChanged(
            device_id=device_id,
            cover=status.cover.value if status.cover else None,
            light_on=status.light_on,
            brightness=status.brightness,
        ))
        logger.info(f"flat_panel.{action}", device_id=device_id)
        return status
