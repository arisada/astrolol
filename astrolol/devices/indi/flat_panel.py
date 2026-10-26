# astrolol/devices/indi/flat_panel.py
import structlog
from astrolol.devices.base.models import CoverState, DeviceState, FlatPanelStatus
from astrolol.devices.indi.client import IndiClient

logger = structlog.get_logger()
_COVER_TIMEOUT = 60.0

# Standard INDI light box / dust cap interfaces (INDI::LightBoxInterface, INDI::DustCapInterface),
# then INDIGO's names, which an INDIGO server does not translate for INDI clients.
_CAPS = (                          # (property, closed element, open element)
    ("CAP_PARK", "PARK", "UNPARK"),
    ("AUX_COVER", "CLOSE", "OPEN"),
)
_LIGHTS = (                        # (property, on element, off element)
    ("FLAT_LIGHT_CONTROL", "FLAT_LIGHT_ON", "FLAT_LIGHT_OFF"),
    ("AUX_LIGHT_SWITCH", "ON", "OFF"),
)
_LEVEL = "FLAT_LIGHT_INTENSITY"   # FLAT_LIGHT_INTENSITY_VALUE, the same in both


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

    def _first(self, names: tuple[tuple[str, str, str], ...]) -> tuple[str, str, str] | None:
        return next((n for n in names if self._has(n[0])), None)

    async def _set_cover(self, closed: bool) -> None:
        cap = self._first(_CAPS)
        if cap is None:
            raise ValueError("This device has no motorised cover.")
        prop, closed_element, open_element = cap
        element = closed_element if closed else open_element
        await self._client.set_switch(self._device_name, prop, [element])
        await self._client.wait_prop_busy_then_done(
            self._device_name, prop, busy_timeout=2.0, done_timeout=_COVER_TIMEOUT
        )
        logger.info("indi.flat_panel_cover", device=self._device_name, action=element)

    async def open_cover(self) -> None:
        await self._set_cover(closed=False)

    async def close_cover(self) -> None:
        await self._set_cover(closed=True)

    async def set_light(self, on: bool, brightness: int | None = None) -> None:
        light = self._first(_LIGHTS)
        if light is None:
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
        prop, on_element, off_element = light
        await self._client.set_switch(self._device_name, prop, [on_element if on else off_element])
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
        cap = self._first(_CAPS)
        cover: CoverState | None = None
        if cap is not None:
            cap_v = self._client._get_vector(self._device_name, cap[0])
            closed = self._client.get_switch_state_nowait(self._device_name, cap[0], cap[1])
            if cap_v is not None and cap_v.state == "Busy":
                cover = CoverState.MOVING
            elif closed is None:
                cover = CoverState.UNKNOWN
            else:
                cover = CoverState.CLOSED if closed else CoverState.OPEN

        light = self._first(_LIGHTS)
        light_on = (
            self._client.get_switch_state_nowait(self._device_name, light[0], light[1])
            if light is not None else None
        )
        brightness = self._client.get_number_nowait(
            self._device_name, _LEVEL, "FLAT_LIGHT_INTENSITY_VALUE"
        )
        return FlatPanelStatus(
            state=self._state,
            has_cover=cap is not None,
            cover=cover,
            has_light=light is not None,
            light_on=light_on,
            brightness=int(brightness) if brightness is not None else None,
            max_brightness=self._brightness_range()[1],
        )

    async def ping(self) -> bool:
        return self._first(_LIGHTS) is not None or self._first(_CAPS) is not None
