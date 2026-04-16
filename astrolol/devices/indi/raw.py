# astrolol/devices/indi/raw.py
import structlog
from astrolol.devices.base.models import DeviceState
from astrolol.devices.indi.client import IndiClient

logger = structlog.get_logger()


class IndiRawDevice:
    """Connects to any INDI driver with no role-specific operations.
    Useful for drivers with no recognized astrolol role — accessible via the INDI panel."""

    def __init__(self, device_name: str, client: IndiClient, **_kwargs) -> None:
        self._device_name = device_name
        self._client = client
        self._state = DeviceState.DISCONNECTED

    async def connect(self) -> None:
        await self._client.connect_device(self._device_name)
        self._state = DeviceState.CONNECTED
        logger.info("indi.raw_device_connected", device=self._device_name)

    async def disconnect(self) -> None:
        try:
            await self._client.disconnect_device(self._device_name)
        finally:
            self._state = DeviceState.DISCONNECTED

    async def ping(self) -> bool:
        return self._state == DeviceState.CONNECTED
