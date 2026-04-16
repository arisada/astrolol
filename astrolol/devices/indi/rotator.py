# astrolol/devices/indi/rotator.py
import structlog
from astrolol.devices.base.models import DeviceState, RotatorStatus
from astrolol.devices.indi.client import IndiClient

logger = structlog.get_logger()


class IndiRotator:
    """Stub INDI rotator adapter. Discovers ABS_ROTATOR_ANGLE but no control operations yet."""

    def __init__(self, device_name: str, client: IndiClient,
                 pre_connect_props: dict | None = None) -> None:
        self._device_name = device_name
        self._client = client
        self._state = DeviceState.DISCONNECTED

    async def connect(self) -> None:
        await self._client.connect_device(self._device_name)
        self._state = DeviceState.CONNECTED

    async def disconnect(self) -> None:
        try:
            await self._client.disconnect_device(self._device_name)
        finally:
            self._state = DeviceState.DISCONNECTED

    async def get_status(self) -> RotatorStatus:
        angle = self._client.get_number_nowait(
            self._device_name, "ABS_ROTATOR_ANGLE", "ANGLE"
        )
        rot_v = self._client._get_vector(self._device_name, "ABS_ROTATOR_ANGLE")
        is_moving = rot_v is not None and rot_v.state == "Busy"
        return RotatorStatus(
            state=self._state,
            position=angle,
            is_moving=is_moving,
        )

    async def ping(self) -> bool:
        try:
            v = self._client._get_vector(self._device_name, "ABS_ROTATOR_ANGLE")
            return v is not None
        except Exception:
            return False
