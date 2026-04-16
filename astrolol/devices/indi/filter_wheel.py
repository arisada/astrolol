# astrolol/devices/indi/filter_wheel.py
import asyncio
import structlog
from astrolol.devices.base.models import DeviceState, FilterWheelStatus
from astrolol.devices.indi.client import IndiClient

logger = structlog.get_logger()
_SELECT_TIMEOUT = 30.0


class IndiFilterWheel:
    def __init__(self, device_name: str, client: IndiClient,
                 pre_connect_props: dict | None = None) -> None:
        self._device_name = device_name
        self._client = client
        self._pre_connect_props = pre_connect_props or {}
        self._state = DeviceState.DISCONNECTED

    async def connect(self) -> None:
        await self._client.connect_device(self._device_name)
        for prop_name, prop_def in self._pre_connect_props.items():
            try:
                if "values" in prop_def:
                    await self._client.set_number(self._device_name, prop_name, prop_def["values"])
            except Exception:
                pass
        self._state = DeviceState.CONNECTED

    async def disconnect(self) -> None:
        try:
            await self._client.disconnect_device(self._device_name)
        finally:
            self._state = DeviceState.DISCONNECTED

    async def select_filter(self, slot: int) -> None:
        await self._client.set_number(
            self._device_name, "FILTER_SLOT", {"FILTER_SLOT_VALUE": float(slot)}
        )
        await self._client.wait_prop_busy_then_done(
            self._device_name, "FILTER_SLOT", busy_timeout=1.0, done_timeout=_SELECT_TIMEOUT
        )
        logger.info("indi.filter_wheel_selected", device=self._device_name, slot=slot)

    async def get_status(self) -> FilterWheelStatus:
        fw_v = self._client._get_vector(self._device_name, "FILTER_SLOT")
        is_moving = fw_v is not None and fw_v.state == "Busy"

        current_slot: int | None = None
        slot_count_from_max: int | None = None
        if fw_v is not None:
            try:
                current_slot = int(fw_v.getfloatvalue("FILTER_SLOT_VALUE"))
            except Exception:
                try:
                    member = fw_v.data.get("FILTER_SLOT_VALUE")
                    if member is not None:
                        current_slot = int(float(str(member.membervalue).strip()))
                except Exception:
                    pass
            # Read slot count from the member's max attribute
            try:
                member = fw_v.data.get("FILTER_SLOT_VALUE")
                if member is not None:
                    slot_count_from_max = int(float(str(member.max)))
            except Exception:
                pass

        filter_names: list[str] = []
        name_v = self._client._get_vector(self._device_name, "FILTER_NAME")
        if name_v is not None:
            i = 1
            while True:
                elem = f"FILTER_SLOT_NAME_{i}"
                try:
                    val = name_v[elem]
                    if val is not None:
                        filter_names.append(str(val))
                        i += 1
                    else:
                        break
                except (KeyError, Exception):
                    break

        # filter_count: prefer length of names, fall back to FILTER_SLOT max
        if filter_names:
            filter_count = len(filter_names)
        elif slot_count_from_max and slot_count_from_max > 0:
            filter_count = slot_count_from_max
        else:
            filter_count = None

        return FilterWheelStatus(
            state=self._state,
            current_slot=current_slot,
            filter_count=filter_count,
            filter_names=filter_names,
            is_moving=is_moving,
        )

    async def ping(self) -> bool:
        try:
            v = self._client._get_vector(self._device_name, "FILTER_SLOT")
            return v is not None
        except Exception:
            return False
