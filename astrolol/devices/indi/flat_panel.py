# astrolol/devices/indi/flat_panel.py
import structlog
from astrolol.devices.base.models import CoverState, DeviceState, FlatPanelStatus
from astrolol.devices.indi.client import IndiClient

logger = structlog.get_logger()
_COVER_TIMEOUT = 60.0

# Standard INDI light box / dust cap interfaces (INDI::LightBoxInterface, INDI::DustCapInterface).
_CAP = "CAP_PARK"                 # PARK = closed, UNPARK = open
_LIGHT = "FLAT_LIGHT_CONTROL"     # FLAT_LIGHT_ON / FLAT_LIGHT_OFF
_LEVEL = "FLAT_LIGHT_INTENSITY"   # FLAT_LIGHT_INTENSITY_VALUE


class IndiFlatPanel:
    def __init__(self, device_name: str, client: IndiClient,
                 pre_connect_props: dict | None = None) -> None:
        self._device_name = device_name
        self._client = client
        self._pre_connect_props = pre_connect_props or {}
        self._state = DeviceState.DISCONNECTED

    async def connect(self) -> None:
        await self._client.connect_device(self._device_name)
        self._state = DeviceState.CONNECTED

    async def disconnect(self) -> None:
        try:
            await self._client.disconnect_device(self._device_name)
        finally:
            self._state = DeviceState.DISCONNECTED

    def _has(self, prop: str) -> bool:
        return self._client._get_vector(self._device_name, prop) is not None

    async def _set_cover(self, element: str) -> None:
        if not self._has(_CAP):
            raise ValueError("This device has no motorised cover.")
        await self._client.set_switch(self._device_name, _CAP, [element])
        await self._client.wait_prop_busy_then_done(
            self._device_name, _CAP, busy_timeout=2.0, done_timeout=_COVER_TIMEOUT
        )
        logger.info("indi.flat_panel_cover", device=self._device_name, action=element)

    async def open_cover(self) -> None:
        await self._set_cover("UNPARK")

    async def close_cover(self) -> None:
        await self._set_cover("PARK")

    async def set_light(self, on: bool, brightness: int | None = None) -> None:
        if not self._has(_LIGHT):
            raise ValueError("This device has no light.")
        if brightness is not None:
            if not self._has(_LEVEL):
                raise ValueError("This device's light has no brightness control.")
            _, max_b = self._brightness_range()
            if not 0 <= brightness <= (max_b if max_b is not None else brightness):
                raise ValueError(f"Brightness must be between 0 and {max_b}.")
            # Set the level before switching on so the panel never flashes at the old one.
            await self._client.set_number(
                self._device_name, _LEVEL, {"FLAT_LIGHT_INTENSITY_VALUE": float(brightness)}
            )
        await self._client.set_switch(
            self._device_name, _LIGHT, ["FLAT_LIGHT_ON" if on else "FLAT_LIGHT_OFF"]
        )
        logger.info("indi.flat_panel_light", device=self._device_name, on=on, brightness=brightness)

    def _brightness_range(self) -> tuple[int | None, int | None]:
        v = self._client._get_vector(self._device_name, _LEVEL)
        member = v.data.get("FLAT_LIGHT_INTENSITY_VALUE") if v is not None else None
        if member is None:
            return None, None
        try:
            return int(float(str(member.min))), int(float(str(member.max)))
        except Exception:
            return None, None

    async def get_status(self) -> FlatPanelStatus:
        has_cover = self._has(_CAP)
        cover: CoverState | None = None
        if has_cover:
            cap_v = self._client._get_vector(self._device_name, _CAP)
            parked = self._client.get_switch_state_nowait(self._device_name, _CAP, "PARK")
            if cap_v is not None and cap_v.state == "Busy":
                cover = CoverState.MOVING
            elif parked is None:
                cover = CoverState.UNKNOWN
            else:
                cover = CoverState.CLOSED if parked else CoverState.OPEN

        has_light = self._has(_LIGHT)
        light_on = (
            self._client.get_switch_state_nowait(self._device_name, _LIGHT, "FLAT_LIGHT_ON")
            if has_light else None
        )
        brightness = self._client.get_number_nowait(
            self._device_name, _LEVEL, "FLAT_LIGHT_INTENSITY_VALUE"
        )
        return FlatPanelStatus(
            state=self._state,
            has_cover=has_cover,
            cover=cover,
            has_light=has_light,
            light_on=light_on,
            brightness=int(brightness) if brightness is not None else None,
            max_brightness=self._brightness_range()[1],
        )

    async def ping(self) -> bool:
        return self._has(_LIGHT) or self._has(_CAP)
