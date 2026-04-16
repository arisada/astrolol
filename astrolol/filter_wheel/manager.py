import asyncio
from dataclasses import dataclass, field
import structlog
from astrolol.core.events import EventBus, FilterWheelFilterChanged
from astrolol.devices.base.models import FilterWheelStatus
from astrolol.devices.manager import DeviceManager

logger = structlog.get_logger()
SELECT_TIMEOUT = 30.0


class FilterWheelManager:
    def __init__(self, device_manager: DeviceManager, event_bus: EventBus) -> None:
        self._device_manager = device_manager
        self._event_bus = event_bus

    async def select_filter(self, device_id: str, slot: int) -> None:
        fw = self._device_manager.get_filter_wheel(device_id)
        await fw.select_filter(slot)
        status = await fw.get_status()
        name = status.filter_names[slot - 1] if status.filter_names and 0 < slot <= len(status.filter_names) else None
        await self._event_bus.publish(
            FilterWheelFilterChanged(device_id=device_id, slot=slot, filter_name=name)
        )
        logger.info("filter_wheel.filter_changed", device_id=device_id, slot=slot, name=name)

    async def get_status(self, device_id: str) -> FilterWheelStatus:
        fw = self._device_manager.get_filter_wheel(device_id)
        return await fw.get_status()
